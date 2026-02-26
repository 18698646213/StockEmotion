"""自动量化交易策略引擎。

基于 DeepSeek AI 分析结果自动执行期货交易（通过天勤量化 TqSdk）。

止盈止损策略基于 ATR（Average True Range）：
  - 止损 = 入场价 ∓ 1.5 × ATR(14)（15分钟K线）
  - 初始止盈 = 入场价 ± 3 × ATR（2:1 风险回报比）
  - 跟踪止盈：价格每有利移动 0.5 ATR，止损跟进 0.25 ATR

流程:
  1. 定时获取 DeepSeek 对持仓合约的分析结果（信号 + 建议价位）
  2. 计算 ATR(14) 设定止盈止损
  3. 将 AI 信号转化为交易动作（开仓/平仓/止损/止盈）
  4. 动态跟踪止盈（trailing stop）
  5. 通过 TqSdk 执行下单
"""

import json
import logging
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

PERSIST_DIR = Path(__file__).resolve().parent.parent.parent / "data"
DECISIONS_FILE = PERSIST_DIR / "auto_decisions.json"
POSITIONS_FILE = PERSIST_DIR / "auto_positions.json"
CONFIG_FILE = PERSIST_DIR / "auto_config.json"

# ---------------------------------------------------------------------------
# ATR 参数
# ---------------------------------------------------------------------------
ATR_PERIOD = 14
ATR_KLINE_DURATION = 900       # 15分钟K线
ATR_SL_MULTIPLIER = 1.5        # 止损 = 1.5 × ATR
ATR_TP_MULTIPLIER = 3.0        # 初始止盈 = 3 × ATR（2:1 风险回报比）
TRAIL_STEP_ATR = 0.5           # 价格每有利移动 0.5 ATR
TRAIL_MOVE_ATR = 0.25          # 止损跟进 0.25 ATR
MAX_RISK_PER_TRADE = 0.02      # 单笔最大亏损占权益比例 (2%)
MAX_RISK_RATIO = 0.80          # 最大仓位风险度 (保证金/权益, 80%)


@dataclass
class TradeConfig:
    """Auto-trading risk parameters."""
    max_lots: int = 1
    max_positions: int = 3
    signal_threshold: float = 0.3
    analysis_interval: int = 300
    atr_sl_multiplier: float = ATR_SL_MULTIPLIER
    atr_tp_multiplier: float = ATR_TP_MULTIPLIER
    trail_step_atr: float = TRAIL_STEP_ATR
    trail_move_atr: float = TRAIL_MOVE_ATR
    max_risk_per_trade: float = MAX_RISK_PER_TRADE
    max_risk_ratio: float = MAX_RISK_RATIO
    close_before_market_close: bool = True
    enabled: bool = False


@dataclass
class PositionState:
    """Tracks a managed position's ATR-based stop levels."""
    symbol: str
    direction: str          # "LONG" or "SHORT"
    entry_price: float
    atr: float              # ATR at entry time
    stop_loss: float        # current stop-loss (dynamically updated by trailing)
    take_profit: float      # initial take-profit target
    highest_since_entry: float = 0.0   # for trailing long
    lowest_since_entry: float = 0.0    # for trailing short
    lots: int = 0
    opened_at: str = ""


@dataclass
class TradeDecision:
    """A single trade decision made by the strategy."""
    timestamp: str
    symbol: str
    action: str          # BUY / SELL / CLOSE_LONG / CLOSE_SHORT / HOLD
    lots: int
    price: float
    reason: str
    signal: str
    composite_score: float
    atr: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    order_result: Optional[dict] = None
    entry_price: float = 0.0
    pnl_points: float = 0.0       # 每手盈亏点数
    pnl_pct: float = 0.0          # 盈亏百分比 (基于入场价)
    holding_seconds: int = 0       # 持仓时长(秒)


class AutoTrader:
    """AI-driven auto-trading engine with ATR-based risk management."""

    def __init__(self):
        self.config = TradeConfig()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._decisions: list[TradeDecision] = []
        self._lock = threading.Lock()
        self._cycle_lock = threading.Lock()   # prevents concurrent analysis cycles
        self._contracts: list[str] = []
        self._positions: dict[str, PositionState] = {}
        self._load_state()

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self, contracts: list[str], config: Optional[TradeConfig] = None):
        if self._running:
            logger.warning("自动交易已在运行中")
            return

        # Force-stop any lingering thread before starting a new one
        old = self._thread
        if old is not None and old.is_alive():
            logger.info("等待旧交易线程退出...")
            self._running = False
            old.join(timeout=30)
            if old.is_alive():
                logger.warning("旧线程仍在运行，将被新线程取代（cycle_lock 防止并发）")

        if config:
            self.config = config
        self._contracts = list(dict.fromkeys(c.strip().upper() for c in contracts if c.strip()))
        if not self._contracts:
            logger.warning("没有指定交易合约，无法启动自动交易")
            return

        self._running = True
        self.config.enabled = True
        self._save_config()
        self._thread = threading.Thread(
            target=self._trading_loop, daemon=True, name="auto-trader")
        self._thread.start()
        logger.info("自动交易已启动: %s, 间隔=%ds, ATR止损=%.1fx, ATR止盈=%.1fx",
                     self._contracts, self.config.analysis_interval,
                     self.config.atr_sl_multiplier, self.config.atr_tp_multiplier)

    def stop(self):
        self._running = False
        self.config.enabled = False
        t = self._thread
        if t is not None and t.is_alive():
            t.join(timeout=30)
        self._thread = None
        logger.info("自动交易已停止")

    @staticmethod
    def _safe_round(val, ndigits: int = 2) -> float:
        import math
        if val is None:
            return 0.0
        try:
            f = float(val)
            if math.isnan(f) or math.isinf(f):
                return 0.0
            return round(f, ndigits)
        except (TypeError, ValueError):
            return 0.0

    @classmethod
    def _sanitize(cls, obj):
        """Recursively replace NaN/Inf with 0 in a dict/list for JSON safety."""
        import math
        if isinstance(obj, dict):
            return {k: cls._sanitize(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [cls._sanitize(v) for v in obj]
        if isinstance(obj, float):
            if math.isnan(obj) or math.isinf(obj):
                return 0.0
        return obj

    def get_status(self) -> dict:
        managed = {}
        unrealized_pnl = 0.0
        for sym, ps in self._positions.items():
            cur_price = self._get_current_price(sym)
            if ps.direction == "LONG":
                float_pnl = (cur_price - ps.entry_price) * ps.lots if cur_price else 0.0
            else:
                float_pnl = (ps.entry_price - cur_price) * ps.lots if cur_price else 0.0
            float_pct = (float_pnl / ps.entry_price * 100) if ps.entry_price > 0 else 0.0
            unrealized_pnl += float_pnl
            managed[sym] = {
                "direction": ps.direction,
                "entry_price": ps.entry_price,
                "atr": self._safe_round(ps.atr),
                "stop_loss": self._safe_round(ps.stop_loss),
                "take_profit": self._safe_round(ps.take_profit),
                "lots": ps.lots,
                "current_price": cur_price,
                "float_pnl": self._safe_round(float_pnl),
                "float_pnl_pct": self._safe_round(float_pct),
            }

        pnl_summary = self._calc_pnl_summary()
        account_pnl = self._get_account_pnl()

        result = {
            "running": self._running,
            "contracts": self._contracts,
            "config": {
                "max_lots": self.config.max_lots,
                "max_positions": self.config.max_positions,
                "signal_threshold": self.config.signal_threshold,
                "analysis_interval": self.config.analysis_interval,
                "atr_sl_multiplier": self.config.atr_sl_multiplier,
                "atr_tp_multiplier": self.config.atr_tp_multiplier,
                "trail_step_atr": self.config.trail_step_atr,
                "trail_move_atr": self.config.trail_move_atr,
                "max_risk_per_trade": self.config.max_risk_per_trade,
                "max_risk_ratio": self.config.max_risk_ratio,
                "close_before_market_close": self.config.close_before_market_close,
            },
            "managed_positions": managed,
            "pnl_summary": pnl_summary,
            "account_pnl": account_pnl,
            "unrealized_pnl": self._safe_round(unrealized_pnl),
            "decisions_count": len(self._decisions),
            "trading_hours": self._is_trading_hours(),
        }
        return self._sanitize(result)

    def _get_account_pnl(self) -> dict:
        """Get account-level P&L from TqSdk (total since account inception)."""
        try:
            from src.data.tqsdk_service import get_tq_service
            svc = get_tq_service()
            if not svc.is_ready:
                return {}
            acct = svc.get_account_info()
            if not acct:
                return {}
            close_profit = float(acct.get("close_profit", 0))
            float_profit = float(acct.get("float_profit", 0))
            commission = float(acct.get("commission", 0))
            balance = float(acct.get("balance", 0))
            static_balance = float(acct.get("static_balance", 0))
            return {
                "close_profit": self._safe_round(close_profit),
                "float_profit": self._safe_round(float_profit),
                "commission": self._safe_round(commission),
                "net_pnl": self._safe_round(close_profit + float_profit - commission),
                "balance": self._safe_round(balance),
                "static_balance": self._safe_round(static_balance),
                "daily_pnl": self._safe_round(balance - static_balance),
            }
        except Exception:
            return {}

    def _get_current_price(self, symbol: str) -> float:
        try:
            from src.data.tqsdk_service import get_tq_service
            svc = get_tq_service()
            if svc.is_ready:
                q = svc.get_quote(symbol)
                if q and q.get("price", 0) > 0:
                    return q["price"]
        except Exception:
            pass
        return 0.0

    def _calc_pnl_summary(self) -> dict:
        """Aggregate realized P&L from all closed trades."""
        closed = [d for d in self._decisions
                  if d.action in ("CLOSE_LONG", "CLOSE_SHORT") and d.entry_price > 0]
        if not closed:
            return {
                "total_trades": 0, "wins": 0, "losses": 0, "win_rate": 0,
                "total_pnl_points": 0, "avg_pnl_points": 0,
                "max_win_points": 0, "max_loss_points": 0,
                "total_pnl_pct": 0, "avg_holding_seconds": 0,
            }
        wins = [d for d in closed if d.pnl_points > 0]
        losses = [d for d in closed if d.pnl_points < 0]
        total_pts = sum(d.pnl_points for d in closed)
        max_win = max((d.pnl_points for d in closed), default=0)
        max_loss = min((d.pnl_points for d in closed), default=0)
        avg_hold = sum(d.holding_seconds for d in closed) / len(closed)
        sr = self._safe_round
        return {
            "total_trades": len(closed),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": sr(len(wins) / len(closed) * 100, 1),
            "total_pnl_points": sr(total_pts),
            "avg_pnl_points": sr(total_pts / len(closed)),
            "max_win_points": sr(max_win),
            "max_loss_points": sr(max_loss),
            "total_pnl_pct": sr(sum(d.pnl_pct for d in closed)),
            "avg_holding_seconds": int(avg_hold),
        }

    def get_decisions(self, limit: int = 50) -> list[dict]:
        with self._lock:
            items = self._decisions[-limit:]
        rows = [
            {
                "timestamp": d.timestamp,
                "symbol": d.symbol,
                "action": d.action,
                "lots": d.lots,
                "price": d.price,
                "reason": d.reason,
                "signal": d.signal,
                "composite_score": d.composite_score,
                "atr": d.atr,
                "stop_loss": d.stop_loss,
                "take_profit": d.take_profit,
                "order_result": d.order_result,
                "entry_price": d.entry_price,
                "pnl_points": d.pnl_points,
                "pnl_pct": d.pnl_pct,
                "holding_seconds": d.holding_seconds,
            }
            for d in reversed(items)
        ]
        return self._sanitize(rows)

    # ------------------------------------------------------------------
    # Core loop
    # ------------------------------------------------------------------

    def _trading_loop(self):
        logger.info("自动交易循环启动 (thread=%s)", threading.current_thread().name)
        while self._running:
            try:
                self._run_one_cycle()
            except Exception as e:
                logger.error("自动交易循环异常: %s", e)
            for tick in range(self.config.analysis_interval):
                if not self._running:
                    break
                time.sleep(1)
                if tick % 2 == 0 and self._positions:
                    try:
                        self._monitor_stop_levels()
                    except Exception as e:
                        logger.debug("SL/TP 监控异常: %s", e)
        logger.info("自动交易循环结束 (thread=%s)", threading.current_thread().name)

    def _monitor_stop_levels(self):
        """High-frequency SL/TP check — runs every ~2s between analysis cycles."""
        if not self._cycle_lock.acquire(blocking=False):
            return
        try:
            self._do_monitor_stop_levels()
        finally:
            self._cycle_lock.release()

    @staticmethod
    def _is_near_market_close() -> bool:
        """Check if we're within 5 minutes of day-session close (14:55-15:00)."""
        now = datetime.now()
        t = now.hour * 60 + now.minute
        return 14 * 60 + 55 <= t < 15 * 60

    def _do_monitor_stop_levels(self):
        if not self._is_trading_hours():
            return
        from src.data.tqsdk_service import get_tq_service
        svc = get_tq_service()
        if not svc.is_ready:
            return

        near_close = self.config.close_before_market_close and self._is_near_market_close()

        for symbol in list(self._positions.keys()):
            ps = self._positions.get(symbol)
            if ps is None:
                continue

            quote = svc.get_quote(symbol)
            if not quote or quote.get("price", 0) <= 0:
                continue
            price = quote["price"]

            pos = svc.get_position_info(symbol)
            long_vol = pos.get("long_volume", 0) if pos else 0
            short_vol = pos.get("short_volume", 0) if pos else 0
            if long_vol == 0 and short_vol == 0:
                continue

            # Near market close: force close all positions
            if near_close:
                pnl_pts, pnl_pct, hold_sec = self._calc_pnl(ps, price)
                action = "CLOSE_LONG" if long_vol > 0 else "CLOSE_SHORT"
                lots = long_vol if long_vol > 0 else short_vol
                close_decision = TradeDecision(
                    timestamp=datetime.now().isoformat(),
                    symbol=symbol, action=action, lots=lots, price=price,
                    reason=f"收盘前平仓 (14:55规则, 现价{price:.1f}, "
                           f"入场{ps.entry_price:.1f}, 盈亏={pnl_pts:+.1f}点/{pnl_pct:+.2f}%)",
                    signal="MARKET_CLOSE", composite_score=0,
                    atr=ps.atr, stop_loss=ps.stop_loss, take_profit=ps.take_profit,
                    entry_price=ps.entry_price, pnl_points=pnl_pts,
                    pnl_pct=pnl_pct, holding_seconds=hold_sec)
                logger.info("收盘前自动平仓: %s %s 现价=%.1f 盈亏=%+.1f点",
                            symbol, action, price, pnl_pts)
                close_decision.order_result = self._execute(close_decision, svc)
                self._record(close_decision)
                if close_decision.action in ("CLOSE_LONG", "CLOSE_SHORT"):
                    self._positions.pop(symbol, None)
                    self._save_state()
                continue

            atr = ps.atr
            exit_decision = self._check_exit(symbol, price, atr, long_vol, short_vol)
            if exit_decision:
                logger.info("实时止盈止损触发: %s 现价=%.1f", symbol, price)
                exit_decision.order_result = self._execute(exit_decision, svc)
                self._record(exit_decision)
                if exit_decision.action in ("CLOSE_LONG", "CLOSE_SHORT"):
                    self._positions.pop(symbol, None)
                    self._save_state()

    @staticmethod
    def _is_trading_hours() -> bool:
        """Check if current time is within futures trading sessions.

        Chinese futures sessions:
          Day:   09:00-11:30, 13:30-15:00
          Night: 21:00-23:59, 00:00-02:30
        """
        now = datetime.now()
        t = now.hour * 60 + now.minute  # minutes since midnight
        if 9 * 60 <= t < 11 * 60 + 30:      # 09:00 - 11:30
            return True
        if 13 * 60 + 30 <= t < 15 * 60:     # 13:30 - 15:00
            return True
        if t >= 21 * 60:                      # 21:00 - 23:59
            return True
        if t < 2 * 60 + 30:                   # 00:00 - 02:30
            return True
        return False

    def _run_one_cycle(self):
        if not self._cycle_lock.acquire(blocking=False):
            logger.warning("上一轮分析仍在进行，跳过本轮")
            return
        try:
            self._do_run_one_cycle()
        finally:
            self._cycle_lock.release()

    def _do_run_one_cycle(self):
        from src.data.tqsdk_service import get_tq_service

        if not self._is_trading_hours():
            logger.debug("当前为休市时段，跳过本轮交易")
            return

        svc = get_tq_service()
        if not svc.is_ready:
            logger.warning("天勤服务未就绪，跳过本轮交易")
            return

        for symbol in self._contracts:
            if not self._running:
                break
            try:
                self._analyze_and_trade(symbol, svc)
            except Exception as e:
                logger.error("合约 %s 交易决策异常: %s", symbol, e)

    # ------------------------------------------------------------------
    # Per-contract logic
    # ------------------------------------------------------------------

    def _analyze_and_trade(self, symbol: str, svc):
        from src.data.price_futures import fetch_futures_price
        from src.analysis.technical import compute_indicators, compute_futures_swing_score
        from src.config import load_config

        cfg = load_config()

        # 1. Current position from TqSdk
        pos = svc.get_position_info(symbol)
        long_vol = pos.get("long_volume", 0) if pos else 0
        short_vol = pos.get("short_volume", 0) if pos else 0
        long_avg = pos.get("long_avg_price", 0) if pos else 0
        short_avg = pos.get("short_avg_price", 0) if pos else 0

        # 2. Sync managed position state FIRST (before quote/ATR checks)
        #    so stale positions get cleaned even when market data is unavailable
        has_actual = long_vol > 0 or short_vol > 0
        if not has_actual and symbol in self._positions:
            logger.info("同步清除无实盘持仓: %s", symbol)
            self._positions.pop(symbol)
            self._save_state()

        # 3. Real-time quote
        quote = svc.get_quote(symbol)
        if not quote or quote.get("price", 0) <= 0:
            return
        price = quote["price"]

        # 4. ATR(14) from 15-min K-lines
        atr = svc.get_atr(symbol, ATR_PERIOD, ATR_KLINE_DURATION)
        if atr <= 0:
            logger.debug("%s ATR 不可用，跳过", symbol)
            return

        # 5. Full sync (restore tracking for positions found in TqSdk but not managed)
        self._sync_position_state(symbol, long_vol, short_vol, long_avg, short_avg, atr)

        # 5. Check trailing stop / stop-loss / take-profit for existing positions
        exit_decision = self._check_exit(symbol, price, atr, long_vol, short_vol)
        if exit_decision:
            exit_decision.order_result = self._execute(exit_decision, svc)
            self._record(exit_decision)
            if exit_decision.action in ("CLOSE_LONG", "CLOSE_SHORT"):
                self._positions.pop(symbol, None)
                self._save_state()
            return

        # 6. If no position, get AI signal for potential entry
        if long_vol == 0 and short_vol == 0:
            df = fetch_futures_price(symbol, period_days=120, interval="daily")
            if df is None or df.empty:
                return
            df = compute_indicators(df)
            tech_scores = compute_futures_swing_score(df)

            analysis = self._get_deepseek_analysis(symbol, cfg, tech_scores)
            if not analysis:
                return

            signal = analysis.get("signal", "HOLD")
            composite = float(analysis.get("composite_score", 0))

            entry_decision = self._check_entry(symbol, signal, composite, price, atr)
            if entry_decision.action != "HOLD":
                entry_decision.order_result = self._execute(entry_decision, svc)
                if entry_decision.order_result and entry_decision.order_result.get("status") != "ERROR":
                    self._create_position_state(
                        symbol, entry_decision.action, entry_decision.lots,
                        price, atr)
            self._record(entry_decision)
        else:
            now = datetime.now().isoformat()
            ps = self._positions.get(symbol)
            sl_str = f"SL={ps.stop_loss:.1f}" if ps else ""
            tp_str = f"TP={ps.take_profit:.1f}" if ps else ""
            self._record(TradeDecision(
                timestamp=now, symbol=symbol, action="HOLD",
                lots=0, price=price,
                reason=f"持仓中 ATR={atr:.1f} {sl_str} {tp_str}",
                signal="HOLD", composite_score=0, atr=atr,
                stop_loss=ps.stop_loss if ps else 0,
                take_profit=ps.take_profit if ps else 0,
            ))

    # ------------------------------------------------------------------
    # Position state management
    # ------------------------------------------------------------------

    def _sync_position_state(self, symbol: str, long_vol: int, short_vol: int,
                             long_avg: float, short_avg: float, atr: float):
        """Ensure managed state is consistent with actual TqSdk positions."""
        has_actual = long_vol > 0 or short_vol > 0
        ps = self._positions.get(symbol)

        if has_actual and ps is None:
            direction = "LONG" if long_vol > 0 else "SHORT"
            entry = long_avg if direction == "LONG" else short_avg
            lots = long_vol if direction == "LONG" else short_vol
            if entry > 0:
                self._create_position_state(
                    symbol, "BUY" if direction == "LONG" else "SELL",
                    lots, entry, atr)
                logger.info("恢复持仓跟踪: %s %s 入场%.1f ATR=%.1f",
                            symbol, direction, entry, atr)
        elif not has_actual and ps is not None:
            self._positions.pop(symbol, None)
            self._save_state()

    def _create_position_state(self, symbol: str, action: str, lots: int,
                               entry_price: float, atr: float):
        """Create a new managed position with ATR-based stop levels."""
        sl_mult = self.config.atr_sl_multiplier
        tp_mult = self.config.atr_tp_multiplier

        if action == "BUY":
            stop_loss = entry_price - sl_mult * atr
            take_profit = entry_price + tp_mult * atr
            direction = "LONG"
        else:
            stop_loss = entry_price + sl_mult * atr
            take_profit = entry_price - tp_mult * atr
            direction = "SHORT"

        self._positions[symbol] = PositionState(
            symbol=symbol,
            direction=direction,
            entry_price=entry_price,
            atr=atr,
            stop_loss=stop_loss,
            take_profit=take_profit,
            highest_since_entry=entry_price,
            lowest_since_entry=entry_price,
            lots=lots,
            opened_at=datetime.now().isoformat(),
        )
        logger.info("ATR 风控: %s %s 入场=%.1f ATR=%.1f 止损=%.1f 止盈=%.1f",
                     symbol, direction, entry_price, atr, stop_loss, take_profit)
        self._save_state()

    # ------------------------------------------------------------------
    # Exit checks (stop-loss, take-profit, trailing stop)
    # ------------------------------------------------------------------

    def _calc_pnl(self, ps: PositionState, exit_price: float) -> tuple[float, float, int]:
        """Calculate P&L for a closing trade.

        Returns (pnl_points, pnl_pct, holding_seconds).
        """
        if ps.direction == "LONG":
            pnl_pts = exit_price - ps.entry_price
        else:
            pnl_pts = ps.entry_price - exit_price
        pnl_pct = (pnl_pts / ps.entry_price * 100) if ps.entry_price > 0 else 0.0
        hold_sec = 0
        if ps.opened_at:
            try:
                opened = datetime.fromisoformat(ps.opened_at)
                hold_sec = int((datetime.now() - opened).total_seconds())
            except (ValueError, TypeError):
                pass
        return round(pnl_pts, 4), round(pnl_pct, 4), hold_sec

    def _check_exit(self, symbol: str, price: float, atr: float,
                    long_vol: int, short_vol: int) -> Optional[TradeDecision]:
        ps = self._positions.get(symbol)
        if ps is None:
            return None

        now = datetime.now().isoformat()

        # Update trailing for LONG
        if ps.direction == "LONG" and long_vol > 0:
            if price > ps.highest_since_entry:
                old_high = ps.highest_since_entry
                ps.highest_since_entry = price

                # Trailing: every 0.5 ATR price rises, move SL up 0.25 ATR
                step = self.config.trail_step_atr * ps.atr
                move = self.config.trail_move_atr * ps.atr
                if step > 0:
                    steps = int((price - old_high) / step)
                    if steps > 0:
                        new_sl = ps.stop_loss + steps * move
                        if new_sl > ps.stop_loss:
                            logger.info("跟踪止盈上移: %s SL %.1f → %.1f (价格%.1f)",
                                        symbol, ps.stop_loss, new_sl, price)
                            ps.stop_loss = new_sl
                            self._save_state()

            if price <= ps.stop_loss:
                pnl_pts, pnl_pct, hold_sec = self._calc_pnl(ps, price)
                return TradeDecision(
                    timestamp=now, symbol=symbol, action="CLOSE_LONG",
                    lots=long_vol, price=price,
                    reason=f"ATR止损 (现价{price:.1f} <= 止损{ps.stop_loss:.1f}, "
                           f"入场{ps.entry_price:.1f}, ATR={ps.atr:.1f}, "
                           f"盈亏={pnl_pts:+.1f}点/{pnl_pct:+.2f}%)",
                    signal="STOP_LOSS", composite_score=0,
                    atr=atr, stop_loss=ps.stop_loss, take_profit=ps.take_profit,
                    entry_price=ps.entry_price, pnl_points=pnl_pts,
                    pnl_pct=pnl_pct, holding_seconds=hold_sec)

            if price >= ps.take_profit:
                pnl_pts, pnl_pct, hold_sec = self._calc_pnl(ps, price)
                return TradeDecision(
                    timestamp=now, symbol=symbol, action="CLOSE_LONG",
                    lots=long_vol, price=price,
                    reason=f"ATR止盈 (现价{price:.1f} >= 目标{ps.take_profit:.1f}, "
                           f"入场{ps.entry_price:.1f}, ATR={ps.atr:.1f}, "
                           f"盈亏={pnl_pts:+.1f}点/{pnl_pct:+.2f}%)",
                    signal="TAKE_PROFIT", composite_score=0,
                    atr=atr, stop_loss=ps.stop_loss, take_profit=ps.take_profit,
                    entry_price=ps.entry_price, pnl_points=pnl_pts,
                    pnl_pct=pnl_pct, holding_seconds=hold_sec)

        # Update trailing for SHORT
        if ps.direction == "SHORT" and short_vol > 0:
            if price < ps.lowest_since_entry:
                old_low = ps.lowest_since_entry
                ps.lowest_since_entry = price

                step = self.config.trail_step_atr * ps.atr
                move = self.config.trail_move_atr * ps.atr
                if step > 0:
                    steps = int((old_low - price) / step)
                    if steps > 0:
                        new_sl = ps.stop_loss - steps * move
                        if new_sl < ps.stop_loss:
                            logger.info("跟踪止盈下移: %s SL %.1f → %.1f (价格%.1f)",
                                        symbol, ps.stop_loss, new_sl, price)
                            ps.stop_loss = new_sl
                            self._save_state()

            if price >= ps.stop_loss:
                pnl_pts, pnl_pct, hold_sec = self._calc_pnl(ps, price)
                return TradeDecision(
                    timestamp=now, symbol=symbol, action="CLOSE_SHORT",
                    lots=short_vol, price=price,
                    reason=f"ATR止损 (现价{price:.1f} >= 止损{ps.stop_loss:.1f}, "
                           f"入场{ps.entry_price:.1f}, ATR={ps.atr:.1f}, "
                           f"盈亏={pnl_pts:+.1f}点/{pnl_pct:+.2f}%)",
                    signal="STOP_LOSS", composite_score=0,
                    atr=atr, stop_loss=ps.stop_loss, take_profit=ps.take_profit,
                    entry_price=ps.entry_price, pnl_points=pnl_pts,
                    pnl_pct=pnl_pct, holding_seconds=hold_sec)

            if price <= ps.take_profit:
                pnl_pts, pnl_pct, hold_sec = self._calc_pnl(ps, price)
                return TradeDecision(
                    timestamp=now, symbol=symbol, action="CLOSE_SHORT",
                    lots=short_vol, price=price,
                    reason=f"ATR止盈 (现价{price:.1f} <= 目标{ps.take_profit:.1f}, "
                           f"入场{ps.entry_price:.1f}, ATR={ps.atr:.1f}, "
                           f"盈亏={pnl_pts:+.1f}点/{pnl_pct:+.2f}%)",
                    signal="TAKE_PROFIT", composite_score=0,
                    atr=atr, stop_loss=ps.stop_loss, take_profit=ps.take_profit,
                    entry_price=ps.entry_price, pnl_points=pnl_pts,
                    pnl_pct=pnl_pct, holding_seconds=hold_sec)

        return None

    # ------------------------------------------------------------------
    # Entry checks (AI signal-based)
    # ------------------------------------------------------------------

    def _calc_dynamic_lots(self, symbol: str, price: float, atr: float) -> int:
        """Calculate position size so max loss per trade <= max_risk_per_trade × equity.

        Formula: lots = (equity × risk%) / (ATR × sl_multiplier × volume_multiple)
        Falls back to config.max_lots if account/quote data is unavailable.
        """
        try:
            from src.data.tqsdk_service import get_tq_service
            svc = get_tq_service()
            if not svc.is_ready:
                return self.config.max_lots
            acct = svc.get_account_info()
            if not acct:
                return self.config.max_lots
            equity = float(acct.get("balance", 0))
            if equity <= 0:
                return self.config.max_lots

            quote = svc.get_quote(symbol)
            vol_mult = float(quote.get("volume_multiple", 0)) if quote else 0
            if vol_mult <= 0:
                logger.warning("合约 %s 无法获取合约乘数，回退为 max_lots=%d",
                               symbol, self.config.max_lots)
                return self.config.max_lots
        except Exception:
            return self.config.max_lots

        sl_distance = atr * self.config.atr_sl_multiplier
        if sl_distance <= 0:
            return self.config.max_lots

        max_loss = equity * self.config.max_risk_per_trade
        loss_per_lot = sl_distance * vol_mult
        lots = int(max_loss / loss_per_lot)
        lots = max(1, min(lots, self.config.max_lots))
        logger.debug("动态仓位: 权益=%.0f, 单笔最大亏损=%.0f (%.0f%%), "
                     "SL距离=%.1f, 合约乘数=%.0f, 每手亏损=%.0f, 计算手数=%d",
                     equity, max_loss, self.config.max_risk_per_trade * 100,
                     sl_distance, vol_mult, loss_per_lot, lots)
        return lots

    def _check_risk_ratio(self) -> tuple[bool, float]:
        """Check if current risk ratio (margin/equity) is below max threshold.

        Returns (can_open, current_ratio).
        """
        try:
            from src.data.tqsdk_service import get_tq_service
            svc = get_tq_service()
            if not svc.is_ready:
                return True, 0.0
            acct = svc.get_account_info()
            if not acct:
                return True, 0.0
            risk_ratio = float(acct.get("risk_ratio", 0))
            can_open = risk_ratio < self.config.max_risk_ratio
            if not can_open:
                logger.warning("风险度过高 %.1f%% >= %.1f%%，禁止开仓",
                               risk_ratio * 100, self.config.max_risk_ratio * 100)
            return can_open, risk_ratio
        except Exception:
            return True, 0.0

    def _check_entry(self, symbol: str, signal: str, composite: float,
                     price: float, atr: float) -> TradeDecision:
        now = datetime.now().isoformat()
        threshold = self.config.signal_threshold
        sl_mult = self.config.atr_sl_multiplier
        tp_mult = self.config.atr_tp_multiplier

        if signal in ("STRONG_BUY", "BUY") and composite >= threshold:
            can_open, risk_ratio = self._check_risk_ratio()
            if not can_open:
                return TradeDecision(
                    timestamp=now, symbol=symbol, action="HOLD",
                    lots=0, price=price,
                    reason=f"AI做多 {signal} 得分{composite:.2f}，"
                           f"但风险度 {risk_ratio:.0%} >= {self.config.max_risk_ratio:.0%}，禁止开仓",
                    signal=signal, composite_score=composite, atr=atr)
            lots = self._calc_dynamic_lots(symbol, price, atr)
            sl = price - sl_mult * atr
            tp = price + tp_mult * atr
            return TradeDecision(
                timestamp=now, symbol=symbol, action="BUY",
                lots=lots, price=price,
                reason=f"AI做多 {signal} 得分{composite:.2f} | "
                       f"ATR={atr:.1f} SL={sl:.1f} TP={tp:.1f} "
                       f"手数={lots}(风控{self.config.max_risk_per_trade:.0%})",
                signal=signal, composite_score=composite,
                atr=atr, stop_loss=sl, take_profit=tp)

        if signal in ("STRONG_SELL", "SELL") and composite <= -threshold:
            can_open, risk_ratio = self._check_risk_ratio()
            if not can_open:
                return TradeDecision(
                    timestamp=now, symbol=symbol, action="HOLD",
                    lots=0, price=price,
                    reason=f"AI做空 {signal} 得分{composite:.2f}，"
                           f"但风险度 {risk_ratio:.0%} >= {self.config.max_risk_ratio:.0%}，禁止开仓",
                    signal=signal, composite_score=composite, atr=atr)
            lots = self._calc_dynamic_lots(symbol, price, atr)
            sl = price + sl_mult * atr
            tp = price - tp_mult * atr
            return TradeDecision(
                timestamp=now, symbol=symbol, action="SELL",
                lots=lots, price=price,
                reason=f"AI做空 {signal} 得分{composite:.2f} | "
                       f"ATR={atr:.1f} SL={sl:.1f} TP={tp:.1f} "
                       f"手数={lots}(风控{self.config.max_risk_per_trade:.0%})",
                signal=signal, composite_score=composite,
                atr=atr, stop_loss=sl, take_profit=tp)

        reason = f"信号={signal}, 得分={composite:.2f}, ATR={atr:.1f}"
        if abs(composite) < threshold:
            reason += f" (未达阈值 {threshold})"
        return TradeDecision(
            timestamp=now, symbol=symbol, action="HOLD",
            lots=0, price=price, reason=reason,
            signal=signal, composite_score=composite, atr=atr)

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def _execute(self, decision: TradeDecision, svc) -> Optional[dict]:
        try:
            if decision.action == "BUY":
                return svc.place_order(
                    decision.symbol, "BUY", "OPEN",
                    decision.lots, decision.price)
            elif decision.action == "SELL":
                return svc.place_order(
                    decision.symbol, "SELL", "OPEN",
                    decision.lots, decision.price)
            elif decision.action == "CLOSE_LONG":
                return svc.place_order(
                    decision.symbol, "SELL", "CLOSE",
                    decision.lots, decision.price)
            elif decision.action == "CLOSE_SHORT":
                return svc.place_order(
                    decision.symbol, "BUY", "CLOSE",
                    decision.lots, decision.price)
        except Exception as e:
            logger.error("执行交易失败 %s: %s", decision.symbol, e)
            return {"status": "ERROR", "error": str(e)}
        return None

    # ------------------------------------------------------------------
    # DeepSeek analysis
    # ------------------------------------------------------------------

    def _get_deepseek_analysis(self, symbol: str, cfg, tech_scores: dict) -> Optional[dict]:
        try:
            from src.data.news_futures import fetch_futures_news
            from src.analysis.deepseek import analyze_with_deepseek

            news = fetch_futures_news(
                symbol, lookback_days=cfg.futures_strategy.news_lookback_days)
            swing_data = tech_scores.get("swing")
            return analyze_with_deepseek(
                cfg.deepseek, symbol, "FUTURES", news, tech_scores, swing_data)
        except Exception as e:
            logger.warning("DeepSeek 分析失败 %s: %s", symbol, e)
            return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _record(self, d: TradeDecision):
        with self._lock:
            self._decisions.append(d)
            if len(self._decisions) > 500:
                self._decisions = self._decisions[-300:]
        if d.action != "HOLD":
            pnl_str = ""
            if d.action in ("CLOSE_LONG", "CLOSE_SHORT") and d.entry_price > 0:
                pnl_str = f" | 盈亏={d.pnl_points:+.1f}点({d.pnl_pct:+.2f}%) 持仓{d.holding_seconds}s"
            logger.info("交易决策: %s %s %d手 @ %.1f | ATR=%.1f SL=%.1f TP=%.1f%s | %s",
                         d.symbol, d.action, d.lots, d.price,
                         d.atr, d.stop_loss, d.take_profit, pnl_str,
                         d.order_result or "")
        self._save_state()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_state(self):
        """Persist decisions and managed positions to disk."""
        try:
            PERSIST_DIR.mkdir(parents=True, exist_ok=True)

            with self._lock:
                decisions_data = []
                for d in self._decisions:
                    odr = d.order_result
                    if odr and not isinstance(odr, (dict, list, str)):
                        odr = {"raw": str(odr)}
                    elif isinstance(odr, dict):
                        odr = {k: v for k, v in odr.items()
                               if isinstance(v, (str, int, float, bool, type(None)))}
                    decisions_data.append({
                        "timestamp": d.timestamp,
                        "symbol": d.symbol,
                        "action": d.action,
                        "lots": d.lots,
                        "price": d.price,
                        "reason": d.reason,
                        "signal": d.signal,
                        "composite_score": d.composite_score,
                        "atr": d.atr,
                        "stop_loss": d.stop_loss,
                        "take_profit": d.take_profit,
                        "order_result": odr,
                        "entry_price": d.entry_price,
                        "pnl_points": d.pnl_points,
                        "pnl_pct": d.pnl_pct,
                        "holding_seconds": d.holding_seconds,
                    })

            decisions_data = self._sanitize(decisions_data)
            with open(DECISIONS_FILE, "w", encoding="utf-8") as f:
                json.dump(decisions_data, f, ensure_ascii=False, indent=2)

            positions_data = {
                sym: asdict(ps) for sym, ps in self._positions.items()
            }
            with open(POSITIONS_FILE, "w", encoding="utf-8") as f:
                json.dump(positions_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("保存自动交易记录失败: %s", e)

    def _save_config(self):
        """Persist trade config and contracts to disk."""
        try:
            PERSIST_DIR.mkdir(parents=True, exist_ok=True)
            data = {
                "contracts": self._contracts,
                "max_lots": self.config.max_lots,
                "max_positions": self.config.max_positions,
                "signal_threshold": self.config.signal_threshold,
                "analysis_interval": self.config.analysis_interval,
                "atr_sl_multiplier": self.config.atr_sl_multiplier,
                "atr_tp_multiplier": self.config.atr_tp_multiplier,
                "trail_step_atr": self.config.trail_step_atr,
                "trail_move_atr": self.config.trail_move_atr,
                "max_risk_per_trade": self.config.max_risk_per_trade,
                "max_risk_ratio": self.config.max_risk_ratio,
                "close_before_market_close": self.config.close_before_market_close,
            }
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("保存自动交易配置失败: %s", e)

    def _load_state(self):
        """Restore decisions, managed positions, and config from disk."""
        # Load config (must be before decisions so get_status shows correct values)
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._contracts = data.get("contracts", [])
                self.config.max_lots = data.get("max_lots", self.config.max_lots)
                self.config.max_positions = data.get("max_positions", self.config.max_positions)
                self.config.signal_threshold = data.get("signal_threshold", self.config.signal_threshold)
                self.config.analysis_interval = data.get("analysis_interval", self.config.analysis_interval)
                self.config.atr_sl_multiplier = data.get("atr_sl_multiplier", self.config.atr_sl_multiplier)
                self.config.atr_tp_multiplier = data.get("atr_tp_multiplier", self.config.atr_tp_multiplier)
                self.config.trail_step_atr = data.get("trail_step_atr", self.config.trail_step_atr)
                self.config.trail_move_atr = data.get("trail_move_atr", self.config.trail_move_atr)
                self.config.max_risk_per_trade = data.get("max_risk_per_trade", self.config.max_risk_per_trade)
                self.config.max_risk_ratio = data.get("max_risk_ratio", self.config.max_risk_ratio)
                self.config.close_before_market_close = data.get("close_before_market_close", self.config.close_before_market_close)
                logger.info("已加载自动交易配置: 合约=%s, 间隔=%ds",
                            self._contracts, self.config.analysis_interval)
                self._save_config()
            except Exception as e:
                logger.warning("加载自动交易配置失败: %s", e)

        if DECISIONS_FILE.exists():
            try:
                with open(DECISIONS_FILE, "r", encoding="utf-8") as f:
                    items = json.load(f)
                for item in items:
                    self._decisions.append(TradeDecision(
                        timestamp=item.get("timestamp", ""),
                        symbol=item.get("symbol", ""),
                        action=item.get("action", ""),
                        lots=item.get("lots", 0),
                        price=item.get("price", 0),
                        reason=item.get("reason", ""),
                        signal=item.get("signal", ""),
                        composite_score=item.get("composite_score", 0),
                        atr=item.get("atr", 0),
                        stop_loss=item.get("stop_loss", 0),
                        take_profit=item.get("take_profit", 0),
                        order_result=item.get("order_result"),
                        entry_price=item.get("entry_price", 0),
                        pnl_points=item.get("pnl_points", 0),
                        pnl_pct=item.get("pnl_pct", 0),
                        holding_seconds=item.get("holding_seconds", 0),
                    ))
                logger.info("已加载 %d 条自动交易决策记录", len(self._decisions))
            except Exception as e:
                logger.warning("加载自动交易决策记录失败: %s", e)

        if POSITIONS_FILE.exists():
            try:
                with open(POSITIONS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for sym, ps_data in data.items():
                    self._positions[sym] = PositionState(**ps_data)
                logger.info("已加载 %d 个管理持仓状态", len(self._positions))
            except Exception as e:
                logger.warning("加载管理持仓状态失败: %s", e)


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

_trader: Optional[AutoTrader] = None
_trader_lock = threading.Lock()


def get_auto_trader() -> AutoTrader:
    global _trader
    if _trader is None:
        with _trader_lock:
            if _trader is None:
                _trader = AutoTrader()
    return _trader
