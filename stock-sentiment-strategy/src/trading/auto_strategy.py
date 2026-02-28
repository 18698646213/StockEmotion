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
from typing import List, Optional, Union

logger = logging.getLogger(__name__)

PERSIST_DIR = Path(__file__).resolve().parent.parent.parent / "data"
DECISIONS_FILE = PERSIST_DIR / "auto_decisions.json"
POSITIONS_FILE = PERSIST_DIR / "auto_positions.json"
CONFIG_FILE = PERSIST_DIR / "auto_config.json"
TRADE_LOG_FILE = PERSIST_DIR / "auto_trade_log.json"

# ---------------------------------------------------------------------------
# ATR 参数 — 波段模式默认值
# ---------------------------------------------------------------------------
ATR_PERIOD = 14
ATR_KLINE_DURATION = 900       # 15分钟K线
ATR_SL_MULTIPLIER = 1.5        # 止损 = 1.5 × ATR
ATR_TP_MULTIPLIER = 3.0        # 初始止盈 = 3 × ATR（2:1 风险回报比）
TRAIL_STEP_ATR = 0.5           # 价格每有利移动 0.5 ATR
TRAIL_MOVE_ATR = 0.25          # 止损跟进 0.25 ATR
MAX_RISK_PER_TRADE = 0.02      # 单笔最大亏损占权益比例 (2%)
MAX_RISK_RATIO = 0.80          # 最大仓位风险度 (保证金/权益, 80%)

# ---------------------------------------------------------------------------
# 日内模式预设值 (对标 spritetu: 88%日胜率, 最大亏损520, 从不让浮盈转亏)
# ---------------------------------------------------------------------------
INTRADAY_KLINE_DURATION = 300  # 5分钟K线
INTRADAY_SL_MULT = 1.2         # v6: 1.2 ATR 止损
INTRADAY_TP_MULT = 2.0         # 盈亏比 2:1
INTRADAY_TRAIL_STEP = 0.3      # 更快锁利
INTRADAY_TRAIL_MOVE = 0.15     # 更紧跟踪
INTRADAY_RISK_PER_TRADE = 0.01 # 日内单笔 1%
INTRADAY_SCAN_INTERVAL = 15    # 日内扫描间隔(秒)
INTRADAY_MAX_DAILY_LOSS = 0.03 # 日亏损上限 3%
INTRADAY_MAX_CONSEC_LOSS = 3   # 连续止损暂停阈值
INTRADAY_PAUSE_MINUTES = 30    # 连续止损后暂停分钟数
INTRADAY_NO_ENTRY_AFTER = 55   # 14:55 后不新开仓 (分钟偏移 = 14*60+55)
INTRADAY_SIGNAL_THRESHOLD = 0.55  # v6: 7因子入场阈值
INTRADAY_ADX_MIN = 15             # v6: ADX 最低趋势强度
INTRADAY_NO_ENTRY_HOURS = {3, 6, 13}  # v6: 跳过低效时段 (凌晨3点/早6点/午盘开盘)
POSITION_MONITOR_INTERVAL = 0.5        # 持仓时止盈止损监控间隔 (秒)


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
    # 日内模式
    strategy_mode: str = "swing"              # "swing"(波段) / "intraday"(日内)
    intraday_kline_duration: int = INTRADAY_KLINE_DURATION
    intraday_scan_interval: int = INTRADAY_SCAN_INTERVAL
    max_daily_loss: float = INTRADAY_MAX_DAILY_LOSS
    max_consecutive_losses: int = INTRADAY_MAX_CONSEC_LOSS


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
        self._trade_log: list[dict] = []
        self._lock = threading.Lock()
        self._cycle_lock = threading.Lock()   # prevents concurrent analysis cycles
        self._contracts: list[str] = []
        self._positions: dict[str, PositionState] = {}
        # 日内模式状态
        self._ai_bias: dict[str, str] = {}       # {symbol: "LONG_BIAS"/"SHORT_BIAS"/"NEUTRAL"}
        self._ai_bias_updated: float = 0.0        # timestamp of last AI bias update
        self._daily_pnl: float = 0.0               # today's realized P&L
        self._daily_loss_count: int = 0            # consecutive losses today
        self._pause_until: float = 0.0             # pause trading until this timestamp
        self._last_trade_date: str = ""            # for daily reset
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
        if self.config.strategy_mode == "intraday":
            self.config.close_before_market_close = True
        sl_m, tp_m, _, _, rpt = self._get_effective_params()
        logger.info("自动交易已启动: %s, 模式=%s, 间隔=%ds, SL=%.1fx, TP=%.1fx, 单笔=%s",
                     self._contracts, self.config.strategy_mode,
                     (self.config.intraday_scan_interval
                      if self.config.strategy_mode == "intraday"
                      else self.config.analysis_interval),
                     sl_m, tp_m, f"{rpt:.0%}")

    def stop(self):
        self._running = False
        self.config.enabled = False
        self._save_config()
        t = self._thread
        if t is not None and t.is_alive():
            t.join(timeout=30)
        self._thread = None
        logger.info("自动交易已停止")

    def add_contract(self, symbol: str) -> tuple[bool, str]:
        """Add a contract to the trading list (works while running)."""
        sym = symbol.strip().upper()
        if not sym:
            return False, "合约代码为空"
        if sym in self._contracts:
            return False, f"{sym} 已在交易列表中"
        self._contracts.append(sym)
        self._save_config()
        logger.info("运行时添加合约: %s → %s", sym, self._contracts)
        return True, f"已添加 {sym}"

    def remove_contract(self, symbol: str) -> tuple[bool, str]:
        """Remove a contract from the trading list (works while running)."""
        sym = symbol.strip().upper()
        if sym not in self._contracts:
            return False, f"{sym} 不在交易列表中"
        if sym in self._positions:
            return False, f"{sym} 尚有持仓，请先平仓再移除"
        self._contracts.remove(sym)
        self._ai_bias.pop(sym, None)
        self._save_config()
        logger.info("运行时移除合约: %s → %s", sym, self._contracts)
        return True, f"已移除 {sym}"

    def auto_resume(self) -> bool:
        """Resume auto-trading if previously enabled. Returns True if resumed."""
        if self._running:
            return False
        if not self.config.enabled:
            return False
        if not self._contracts:
            logger.info("自动恢复跳过：没有保存的交易合约")
            return False
        logger.info("检测到上次退出前自动交易处于启用状态，正在恢复: %s", self._contracts)
        self.start(self._contracts)
        return True

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

        sl_m, tp_m, trail_s, trail_mv, rpt = self._get_effective_params()
        is_intraday = self.config.strategy_mode == "intraday"

        config_out = {
            "max_lots": self.config.max_lots,
            "max_positions": self.config.max_positions,
            "signal_threshold": INTRADAY_SIGNAL_THRESHOLD if is_intraday else self.config.signal_threshold,
            "analysis_interval": self.config.analysis_interval,
            "atr_sl_multiplier": sl_m,
            "atr_tp_multiplier": tp_m,
            "trail_step_atr": trail_s,
            "trail_move_atr": trail_mv,
            "max_risk_per_trade": rpt,
            "max_risk_ratio": self.config.max_risk_ratio,
            "close_before_market_close": self.config.close_before_market_close,
            "strategy_mode": self.config.strategy_mode,
            "intraday_kline_duration": self.config.intraday_kline_duration if is_intraday else ATR_KLINE_DURATION,
            "intraday_scan_interval": self.config.intraday_scan_interval,
            "max_daily_loss": self.config.max_daily_loss,
            "max_consecutive_losses": self.config.max_consecutive_losses,
        }

        if is_intraday:
            config_out["strategy_version"] = "v6"
            config_out["adx_min"] = INTRADAY_ADX_MIN
            config_out["htf_trend_filter"] = True
            config_out["htf_require_aligned"] = True
            config_out["no_entry_hours"] = sorted(INTRADAY_NO_ENTRY_HOURS)
            config_out["no_entry_after"] = "14:55"
            config_out["pause_after_consecutive_losses"] = INTRADAY_MAX_CONSEC_LOSS
            config_out["pause_minutes"] = INTRADAY_PAUSE_MINUTES
            config_out["position_monitor_interval_ms"] = int(POSITION_MONITOR_INTERVAL * 1000)

        result = {
            "running": self._running,
            "contracts": self._contracts,
            "config": config_out,
            "effective_params": {
                "sl_mult": sl_m,
                "tp_mult": tp_m,
                "trail_step": trail_s,
                "trail_move": trail_mv,
                "risk_per_trade": rpt,
            },
            "ai_bias": dict(self._ai_bias),
            "daily_pnl": self._safe_round(self._daily_pnl),
            "daily_loss_count": self._daily_loss_count,
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

    def get_decisions(self, limit: int = 50, *,
                      page: int = 1, page_size: int = 0) -> Union[dict, List[dict]]:
        """Return decisions. If page_size > 0, return paginated result dict;
        otherwise fall back to legacy list (limit most recent)."""
        with self._lock:
            total = len(self._decisions)
            if page_size > 0:
                end = total - (page - 1) * page_size
                start = end - page_size
                start = max(start, 0)
                end = max(end, 0)
                items = list(reversed(self._decisions[start:end]))
            else:
                items = list(reversed(self._decisions[-limit:]))

        def _to_dict(d: TradeDecision) -> dict:
            return {
                "timestamp": d.timestamp, "symbol": d.symbol,
                "action": d.action, "lots": d.lots, "price": d.price,
                "reason": d.reason, "signal": d.signal,
                "composite_score": d.composite_score, "atr": d.atr,
                "stop_loss": d.stop_loss, "take_profit": d.take_profit,
                "order_result": d.order_result,
                "entry_price": d.entry_price, "pnl_points": d.pnl_points,
                "pnl_pct": d.pnl_pct, "holding_seconds": d.holding_seconds,
            }

        rows = self._sanitize([_to_dict(d) for d in items])
        if page_size > 0:
            return {"items": rows, "total": total, "page": page, "page_size": page_size}
        return rows

    def clear_decisions(self):
        """Clear all decision records from memory and disk."""
        with self._lock:
            self._decisions.clear()
        self._save_state()
        logger.info("已清除所有 AI 决策日志")

    def get_trade_log(self, *, page: int = 1, page_size: int = 50) -> dict:
        """Return paginated open/close trade log (newest first)."""
        with self._lock:
            total = len(self._trade_log)
            end = total - (page - 1) * page_size
            start = end - page_size
            start = max(start, 0)
            end = max(end, 0)
            items = list(reversed(self._trade_log[start:end]))
        return {"items": self._sanitize(items), "total": total,
                "page": page, "page_size": page_size}

    # ------------------------------------------------------------------
    # Core loop
    # ------------------------------------------------------------------

    # Trading session open times (hour, minute)
    _SESSION_OPENS = [(9, 0), (13, 30), (21, 0)]

    def _trading_loop(self):
        logger.info("自动交易循环启动 (thread=%s, mode=%s)",
                     threading.current_thread().name, self.config.strategy_mode)
        was_trading = self._is_trading_hours()

        if self.config.strategy_mode == "intraday":
            self._trading_loop_intraday(was_trading)
        else:
            self._trading_loop_swing(was_trading)

        logger.info("自动交易循环结束 (thread=%s)", threading.current_thread().name)

    def _trading_loop_swing(self, was_trading: bool):
        """Original swing trading loop: AI analysis every N seconds."""
        while self._running:
            now_trading = self._is_trading_hours()
            if now_trading and not was_trading:
                logger.info("检测到新交易时段开盘，立即执行分析")
            was_trading = now_trading

            try:
                self._run_one_cycle()
            except Exception as e:
                logger.error("自动交易循环异常: %s", e)

            sleep_secs = self._seconds_until_next_event()
            if self._positions:
                total_ticks = int(sleep_secs / POSITION_MONITOR_INTERVAL)
                for _ in range(total_ticks):
                    if not self._running:
                        break
                    time.sleep(POSITION_MONITOR_INTERVAL)
                    try:
                        self._monitor_stop_levels()
                    except Exception as e:
                        logger.debug("SL/TP 监控异常: %s", e)
            else:
                for _ in range(sleep_secs):
                    if not self._running:
                        break
                    time.sleep(1)

    def _trading_loop_intraday(self, was_trading: bool):
        """Intraday loop: fast local scans + periodic AI bias refresh."""
        from src.config import load_config
        AI_BIAS_INTERVAL = 1800  # refresh AI directional bias every 30 min

        while self._running:
            now_trading = self._is_trading_hours()
            if now_trading and not was_trading:
                logger.info("日内模式: 新交易时段开盘")
                self._reset_daily_state()
            was_trading = now_trading

            if not now_trading:
                sleep_secs = self._seconds_until_next_event()
                for _ in range(min(sleep_secs, 60)):
                    if not self._running:
                        return
                    time.sleep(1)
                continue

            self._reset_daily_state()

            # Periodically refresh AI bias (low frequency)
            if time.time() - self._ai_bias_updated > AI_BIAS_INTERVAL:
                try:
                    cfg = load_config()
                    self._update_ai_bias(cfg)
                except Exception as e:
                    logger.warning("AI方向更新异常: %s", e)

            # Fast local scan cycle
            try:
                self._run_one_cycle()
            except Exception as e:
                logger.error("日内交易扫描异常: %s", e)

            scan_interval = self.config.intraday_scan_interval
            if self._positions:
                total_ticks = int(scan_interval / POSITION_MONITOR_INTERVAL)
                for _ in range(total_ticks):
                    if not self._running:
                        break
                    time.sleep(POSITION_MONITOR_INTERVAL)
                    try:
                        self._monitor_stop_levels()
                    except Exception as e:
                        logger.debug("SL/TP 监控异常: %s", e)
            else:
                for _ in range(scan_interval):
                    if not self._running:
                        break
                    time.sleep(1)

    def _monitor_stop_levels(self):
        """High-frequency SL/TP check — runs every 500ms when positions exist."""
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
                    if self.config.strategy_mode == "intraday":
                        is_loss = pnl_pts < 0
                        self._record_intraday_pnl(pnl_pts, is_loss)
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
                    if self.config.strategy_mode == "intraday":
                        is_loss = exit_decision.pnl_points is not None and exit_decision.pnl_points < 0
                        pnl_val = exit_decision.pnl_points or 0
                        self._record_intraday_pnl(pnl_val, is_loss)
                    self._positions.pop(symbol, None)
                    self._save_state()

    def _seconds_until_next_event(self) -> int:
        """Return seconds to sleep: either the normal interval or until the
        next session opens, whichever comes first."""
        interval = self.config.analysis_interval
        if self._is_trading_hours():
            return interval

        now = datetime.now()
        now_mins = now.hour * 60 + now.minute
        secs_into_min = now.second

        best = interval
        for h, m in self._SESSION_OPENS:
            open_mins = h * 60 + m
            diff = open_mins - now_mins
            if diff <= 0:
                diff += 24 * 60
            secs = diff * 60 - secs_into_min
            if secs < best:
                best = secs

        return max(1, best)

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

        # 4. ATR(14) — use 5-min klines in intraday mode, 15-min otherwise
        kline_dur = (self.config.intraday_kline_duration
                     if self.config.strategy_mode == "intraday"
                     else ATR_KLINE_DURATION)
        atr = svc.get_atr(symbol, ATR_PERIOD, kline_dur)
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
                if self.config.strategy_mode == "intraday":
                    is_loss = exit_decision.pnl_points is not None and exit_decision.pnl_points < 0
                    pnl_val = exit_decision.pnl_points or 0
                    self._record_intraday_pnl(pnl_val, is_loss)
                self._positions.pop(symbol, None)
                self._save_state()
            return

        # 6. If no position, determine entry signal based on mode
        if long_vol == 0 and short_vol == 0:
            if self.config.strategy_mode == "intraday":
                self._intraday_entry(symbol, svc, price, atr, cfg)
            else:
                self._swing_entry(symbol, svc, price, atr, cfg)
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
    # Entry: swing mode (original AI-based)
    # ------------------------------------------------------------------

    def _swing_entry(self, symbol: str, svc, price: float, atr: float, cfg):
        from src.data.price_futures import fetch_futures_price
        from src.analysis.technical import compute_indicators, compute_futures_swing_score

        df = fetch_futures_price(symbol, period_days=120, interval="daily")
        if df is None or df.empty:
            return
        df = compute_indicators(df)
        tech_scores = compute_futures_swing_score(df)

        analysis = self._get_deepseek_analysis(symbol, cfg, tech_scores)
        if not analysis:
            logger.warning("%s DeepSeek 返回空结果，记录 HOLD", symbol)
            self._record(TradeDecision(
                timestamp=datetime.now().isoformat(), symbol=symbol,
                action="HOLD", lots=0, price=price,
                reason="DeepSeek 分析无结果", signal="HOLD",
                composite_score=0, atr=atr))
            return

        signal = analysis.get("signal", "HOLD")
        try:
            composite = float(analysis.get("composite_score", 0) or 0)
        except (TypeError, ValueError):
            composite = 0.0
        logger.info("%s DeepSeek 信号=%s 得分=%.2f", symbol, signal, composite)

        entry_decision = self._check_entry(symbol, signal, composite, price, atr)
        if entry_decision.action != "HOLD":
            entry_decision.order_result = self._execute(entry_decision, svc)
            if entry_decision.order_result and entry_decision.order_result.get("status") != "ERROR":
                self._create_position_state(
                    symbol, entry_decision.action, entry_decision.lots,
                    price, atr)
        self._record(entry_decision)

    # ------------------------------------------------------------------
    # Entry: intraday mode (dual-layer: AI bias + local technical)
    # ------------------------------------------------------------------

    def _intraday_entry(self, symbol: str, svc, price: float, atr: float, cfg):
        # Layer 0: intraday risk check
        can_trade, risk_reason = self._check_intraday_risk()
        if not can_trade:
            self._record(TradeDecision(
                timestamp=datetime.now().isoformat(), symbol=symbol,
                action="HOLD", lots=0, price=price,
                reason=f"日内风控: {risk_reason}",
                signal="HOLD", composite_score=0, atr=atr))
            return

        # Layer 1: AI directional bias (refreshed every ~15-30 min)
        bias = self._ai_bias.get(symbol, "NEUTRAL")

        # Layer 2: local 5-min K-line technical signal (7-factor v6)
        local_signal, strength = self._calc_intraday_signal(symbol, svc)
        if local_signal == "HOLD":
            return

        # Layer 3 (v6): 30-min higher-timeframe trend — require strict alignment
        htf = self._calc_htf_trend(symbol, svc)
        if local_signal == "BUY" and htf != 1:
            logger.debug("%s BUY信号但30分趋势非多头(htf=%d)，跳过", symbol, htf)
            return
        if local_signal == "SELL" and htf != -1:
            logger.debug("%s SELL信号但30分趋势非空头(htf=%d)，跳过", symbol, htf)
            return

        # Layer 4 (v6): ADX trend strength
        adx = self._calc_adx(symbol, svc)
        if adx < INTRADAY_ADX_MIN:
            logger.debug("%s ADX=%.1f < %d，趋势不明确，跳过", symbol, adx, INTRADAY_ADX_MIN)
            return

        # Direction filter: local signal must agree with AI bias
        if bias == "LONG_BIAS" and local_signal == "SELL":
            logger.debug("%s 本地做空信号与AI多头偏向冲突，跳过", symbol)
            return
        if bias == "SHORT_BIAS" and local_signal == "BUY":
            logger.debug("%s 本地做多信号与AI空头偏向冲突，跳过", symbol)
            return

        composite = strength if local_signal == "BUY" else -strength
        entry_decision = self._check_entry(symbol, local_signal, composite, price, atr)
        if entry_decision.action != "HOLD":
            entry_decision.reason = (
                f"日内{local_signal} 技术强度={strength:.2f} "
                f"AI偏向={bias} | {entry_decision.reason}")
            entry_decision.order_result = self._execute(entry_decision, svc)
            if entry_decision.order_result and entry_decision.order_result.get("status") != "ERROR":
                self._create_position_state(
                    symbol, entry_decision.action, entry_decision.lots,
                    price, atr)
        self._record(entry_decision)

    def _update_ai_bias(self, cfg):
        """Refresh AI directional bias for all contracts in parallel."""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        def _fetch_bias(symbol):
            from src.data.price_futures import fetch_futures_price
            from src.analysis.technical import compute_indicators, compute_futures_swing_score
            try:
                df = fetch_futures_price(symbol, period_days=120, interval="daily")
                if df is None or df.empty:
                    return symbol, None
                df = compute_indicators(df)
                tech_scores = compute_futures_swing_score(df)
                analysis = self._get_deepseek_analysis(symbol, cfg, tech_scores)
                return symbol, analysis
            except Exception as e:
                logger.warning("AI方向更新失败 %s: %s", symbol, e)
                return symbol, None

        contracts = [s for s in self._contracts if self._running]
        with ThreadPoolExecutor(max_workers=min(4, len(contracts))) as pool:
            futures = {pool.submit(_fetch_bias, s): s for s in contracts}
            for fut in as_completed(futures):
                symbol, analysis = fut.result()
                if not analysis:
                    continue
                signal = analysis.get("signal", "HOLD")
                composite = float(analysis.get("composite_score", 0) or 0)

                if signal in ("STRONG_BUY", "BUY") or composite > 0.15:
                    self._ai_bias[symbol] = "LONG_BIAS"
                elif signal in ("STRONG_SELL", "SELL") or composite < -0.15:
                    self._ai_bias[symbol] = "SHORT_BIAS"
                else:
                    self._ai_bias[symbol] = "NEUTRAL"

                logger.info("AI方向更新: %s → %s (signal=%s, score=%.2f)",
                            symbol, self._ai_bias[symbol], signal, composite)

        self._ai_bias_updated = time.time()

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
        sl_mult, tp_mult, _, _, _ = self._get_effective_params()

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

        _, _, trail_step_mult, trail_move_mult, _ = self._get_effective_params()

        # Update trailing for LONG
        if ps.direction == "LONG" and long_vol > 0:
            if price > ps.highest_since_entry:
                old_high = ps.highest_since_entry
                ps.highest_since_entry = price

                step = trail_step_mult * ps.atr
                move = trail_move_mult * ps.atr
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

                step = trail_step_mult * ps.atr
                move = trail_move_mult * ps.atr
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

        sl_mult, _, _, _, risk_pct = self._get_effective_params()
        sl_distance = atr * sl_mult
        if sl_distance <= 0:
            return self.config.max_lots

        max_loss = equity * risk_pct
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

    # ------------------------------------------------------------------
    # Intraday local technical signal engine (no DeepSeek dependency)
    # ------------------------------------------------------------------

    def _calc_htf_trend(self, symbol: str, svc) -> int:
        """Compute 30-min higher-timeframe trend direction.

        Returns +1 (bullish), -1 (bearish), or 0 (neutral).
        Uses 30-min K-lines with MA5/MA10 alignment.
        """
        import numpy as np
        df30 = svc.get_klines(symbol, duration_seconds=1800, count=60)
        if df30 is None or len(df30) < 15:
            return 0

        close = df30["close"].astype(float)
        ma5 = close.rolling(5).mean()
        ma10 = close.rolling(10).mean()
        last = len(df30) - 1

        c, m5, m10 = close.iloc[last], ma5.iloc[last], ma10.iloc[last]
        if any(np.isnan(v) for v in [c, m5, m10]):
            return 0

        if c > m5 and m5 > m10:
            return 1
        if c < m5 and m5 < m10:
            return -1
        return 0

    def _calc_adx(self, symbol: str, svc, period: int = 14) -> float:
        """Compute ADX(14) from 5-min K-lines. Returns 0 on failure."""
        import numpy as np
        duration = self.config.intraday_kline_duration
        df = svc.get_klines(symbol, duration_seconds=duration, count=100)
        if df is None or len(df) < period * 3:
            return 0.0

        high = df["high"].astype(float)
        low = df["low"].astype(float)
        close = df["close"].astype(float)

        plus_dm = high.diff()
        minus_dm = -low.diff()
        plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
        minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

        import pandas as pd
        tr = pd.concat([high - low, (high - close.shift(1)).abs(),
                        (low - close.shift(1)).abs()], axis=1).max(axis=1)
        atr_s = tr.rolling(period).mean()

        plus_di = 100 * (plus_dm.rolling(period).mean() / atr_s.replace(0, np.nan))
        minus_di = 100 * (minus_dm.rolling(period).mean() / atr_s.replace(0, np.nan))
        dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan))
        adx = dx.rolling(period).mean()
        val = adx.iloc[-1]
        return 0.0 if np.isnan(val) else float(val)

    def _calc_intraday_signal(self, symbol: str, svc) -> tuple[str, float]:
        """Compute 7-factor intraday entry signal from 5-min K-line technicals.

        Factors: MA(0.25) + MACD(0.25) + RSI6(0.15) + KDJ(0.10) +
                 Volume(0.10) + OI(0.10) + Breakout(0.05)

        Returns (signal, strength) where signal is "BUY"/"SELL"/"HOLD"
        and strength is a confidence score in [0, 1].
        """
        import numpy as np
        duration = self.config.intraday_kline_duration
        df = svc.get_klines(symbol, duration_seconds=duration, count=100)
        if df is None or len(df) < 30:
            return "HOLD", 0.0

        close = df["close"].astype(float)
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        volume = df["volume"].astype(float)

        ma5 = close.rolling(5).mean()
        ma10 = close.rolling(10).mean()
        ma20 = close.rolling(20).mean()
        vol_ma20 = volume.rolling(20).mean()

        delta = close.diff()
        gain = delta.where(delta > 0, 0.0).rolling(6).mean()
        loss_s = (-delta.where(delta < 0, 0.0)).rolling(6).mean()
        rs = gain / loss_s.replace(0, np.nan)
        rsi6 = 100 - 100 / (1 + rs)

        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        dif = ema12 - ema26
        dea = dif.ewm(span=9, adjust=False).mean()

        # KDJ(9,3,3)
        low9 = low.rolling(9).min()
        high9 = high.rolling(9).max()
        rsv = (close - low9) / (high9 - low9).replace(0, np.nan) * 100
        k_val = rsv.ewm(com=2, adjust=False).mean()
        d_val = k_val.ewm(com=2, adjust=False).mean()
        j_val = 3 * k_val - 2 * d_val

        last = len(df) - 1
        if last < 5:
            return "HOLD", 0.0

        cur_ma5, cur_ma10, cur_ma20 = ma5.iloc[last], ma10.iloc[last], ma20.iloc[last]
        cur_rsi, prev_rsi = rsi6.iloc[last], rsi6.iloc[last - 1]
        cur_dif, prev_dif = dif.iloc[last], dif.iloc[last - 1]
        cur_dea, prev_dea = dea.iloc[last], dea.iloc[last - 1]
        cur_k, prev_k = k_val.iloc[last], k_val.iloc[last - 1]
        cur_d, prev_d = d_val.iloc[last], d_val.iloc[last - 1]
        cur_j = j_val.iloc[last]
        cur_vol, cur_vol_ma = volume.iloc[last], vol_ma20.iloc[last]
        cur_close = close.iloc[last]
        prev_high, prev_low = high.iloc[last - 1], low.iloc[last - 1]

        check_vals = [cur_ma5, cur_ma10, cur_ma20, cur_rsi, cur_dif, cur_dea, cur_k, cur_d]
        if any(np.isnan(v) for v in check_vals):
            return "HOLD", 0.0

        # Shared factors
        bull_ma = cur_ma5 > cur_ma10 > cur_ma20
        bear_ma = cur_ma5 < cur_ma10 < cur_ma20
        rsi_bull = (prev_rsi < 35 and cur_rsi > 35) or cur_rsi < 30
        rsi_bear = (prev_rsi > 65 and cur_rsi < 65) or cur_rsi > 70
        macd_golden = prev_dif <= prev_dea and cur_dif > cur_dea
        macd_death = prev_dif >= prev_dea and cur_dif < cur_dea
        kdj_bull = (prev_k <= prev_d and cur_k > cur_d) or cur_j < 0
        kdj_bear = (prev_k >= prev_d and cur_k < cur_d) or cur_j > 100
        vol_confirm = cur_vol > cur_vol_ma * 1.2 if cur_vol_ma > 0 else False
        breakout = cur_close > prev_high
        breakdown = cur_close < prev_low

        # OI (open interest) change
        oi_increasing = False
        oi_col = None
        for col in ("open_interest", "hold", "open_oi"):
            if col in df.columns:
                oi_col = col
                break
        if oi_col and last >= 5:
            try:
                oi_now = float(df[oi_col].iloc[last])
                oi_prev = float(df[oi_col].iloc[last - 5])
                if oi_prev > 0 and not np.isnan(oi_now) and not np.isnan(oi_prev):
                    oi_increasing = oi_now > oi_prev * 1.005
            except (ValueError, TypeError):
                pass

        threshold = INTRADAY_SIGNAL_THRESHOLD

        # BUY score (7 factors)
        buy_score = 0.0
        if bull_ma:       buy_score += 0.25
        if macd_golden:   buy_score += 0.25
        if rsi_bull:      buy_score += 0.15
        if kdj_bull:      buy_score += 0.10
        if vol_confirm:   buy_score += 0.10
        if oi_increasing: buy_score += 0.10
        if breakout:      buy_score += 0.05

        if buy_score >= threshold:
            if 40 <= cur_rsi <= 60 and not macd_golden and not kdj_bull:
                return "HOLD", 0.0
            return "BUY", min(buy_score, 1.0)

        # SELL score (7 factors)
        sell_score = 0.0
        if bear_ma:       sell_score += 0.25
        if macd_death:    sell_score += 0.25
        if rsi_bear:      sell_score += 0.15
        if kdj_bear:      sell_score += 0.10
        if vol_confirm:   sell_score += 0.10
        if oi_increasing: sell_score += 0.10
        if breakdown:     sell_score += 0.05

        if sell_score >= threshold:
            if 40 <= cur_rsi <= 60 and not macd_death and not kdj_bear:
                return "HOLD", 0.0
            return "SELL", min(sell_score, 1.0)

        return "HOLD", 0.0

    # ------------------------------------------------------------------
    # Intraday risk control
    # ------------------------------------------------------------------

    def _reset_daily_state(self):
        """Reset daily counters at the start of a new trading day."""
        today = datetime.now().strftime("%Y-%m-%d")
        if self._last_trade_date != today:
            self._daily_pnl = 0.0
            self._daily_loss_count = 0
            self._pause_until = 0.0
            self._last_trade_date = today
            self._ai_bias = {}
            self._ai_bias_updated = 0.0
            logger.info("日内状态已重置 (新交易日: %s)", today)

    def _check_intraday_risk(self) -> tuple[bool, str]:
        """Check if intraday risk limits allow new entry.

        Returns (can_trade, reason).
        """
        now = time.time()
        if now < self._pause_until:
            remaining = int(self._pause_until - now)
            return False, f"连续止损暂停中 (剩余{remaining}s)"

        try:
            from src.data.tqsdk_service import get_tq_service
            svc = get_tq_service()
            if svc.is_ready:
                acct = svc.get_account_info()
                if acct:
                    equity = float(acct.get("balance", 0))
                    if equity > 0 and self._daily_pnl < 0:
                        loss_ratio = abs(self._daily_pnl) / equity
                        if loss_ratio >= self.config.max_daily_loss:
                            return False, (f"日亏损已达 {loss_ratio:.1%} "
                                           f">= {self.config.max_daily_loss:.0%}，今日停止交易")
        except Exception:
            pass

        now_dt = datetime.now()
        t = now_dt.hour * 60 + now_dt.minute
        if 14 * 60 + 30 <= t < 15 * 60:
            return False, "14:30后不新开仓（日内模式）"

        # v6: skip low-efficiency hours (03:xx, 06:xx, 13:xx)
        if now_dt.hour in INTRADAY_NO_ENTRY_HOURS:
            return False, f"{now_dt.hour}:00时段为低效时段，跳过入场"

        return True, ""

    def _record_intraday_pnl(self, pnl: float, is_loss: bool):
        """Track intraday P&L and consecutive losses."""
        self._daily_pnl += pnl
        if is_loss:
            self._daily_loss_count += 1
            if self._daily_loss_count >= self.config.max_consecutive_losses:
                self._pause_until = time.time() + INTRADAY_PAUSE_MINUTES * 60
                logger.warning("连续%d次止损，暂停交易%d分钟",
                               self._daily_loss_count, INTRADAY_PAUSE_MINUTES)
        else:
            self._daily_loss_count = 0

    def _get_effective_params(self) -> tuple[float, float, float, float, float]:
        """Return (sl_mult, tp_mult, trail_step, trail_move, risk_per_trade)
        based on strategy mode."""
        if self.config.strategy_mode == "intraday":
            return (INTRADAY_SL_MULT, INTRADAY_TP_MULT,
                    INTRADAY_TRAIL_STEP, INTRADAY_TRAIL_MOVE,
                    INTRADAY_RISK_PER_TRADE)
        return (self.config.atr_sl_multiplier, self.config.atr_tp_multiplier,
                self.config.trail_step_atr, self.config.trail_move_atr,
                self.config.max_risk_per_trade)

    def _check_entry(self, symbol: str, signal: str, composite: float,
                     price: float, atr: float) -> TradeDecision:
        now = datetime.now().isoformat()
        threshold = self.config.signal_threshold
        sl_mult, tp_mult, _, _, risk_pct = self._get_effective_params()
        mode_tag = "日内" if self.config.strategy_mode == "intraday" else "AI"

        if signal in ("STRONG_BUY", "BUY") and composite >= threshold:
            can_open, risk_ratio = self._check_risk_ratio()
            if not can_open:
                return TradeDecision(
                    timestamp=now, symbol=symbol, action="HOLD",
                    lots=0, price=price,
                    reason=f"{mode_tag}做多 {signal} 得分{composite:.2f}，"
                           f"但风险度 {risk_ratio:.0%} >= {self.config.max_risk_ratio:.0%}，禁止开仓",
                    signal=signal, composite_score=composite, atr=atr)
            lots = self._calc_dynamic_lots(symbol, price, atr)
            sl = price - sl_mult * atr
            tp = price + tp_mult * atr
            return TradeDecision(
                timestamp=now, symbol=symbol, action="BUY",
                lots=lots, price=price,
                reason=f"{mode_tag}做多 {signal} 得分{composite:.2f} | "
                       f"ATR={atr:.1f} SL={sl:.1f} TP={tp:.1f} "
                       f"手数={lots}(风控{risk_pct:.0%})",
                signal=signal, composite_score=composite,
                atr=atr, stop_loss=sl, take_profit=tp)

        if signal in ("STRONG_SELL", "SELL") and composite <= -threshold:
            can_open, risk_ratio = self._check_risk_ratio()
            if not can_open:
                return TradeDecision(
                    timestamp=now, symbol=symbol, action="HOLD",
                    lots=0, price=price,
                    reason=f"{mode_tag}做空 {signal} 得分{composite:.2f}，"
                           f"但风险度 {risk_ratio:.0%} >= {self.config.max_risk_ratio:.0%}，禁止开仓",
                    signal=signal, composite_score=composite, atr=atr)
            lots = self._calc_dynamic_lots(symbol, price, atr)
            sl = price + sl_mult * atr
            tp = price - tp_mult * atr
            return TradeDecision(
                timestamp=now, symbol=symbol, action="SELL",
                lots=lots, price=price,
                reason=f"{mode_tag}做空 {signal} 得分{composite:.2f} | "
                       f"ATR={atr:.1f} SL={sl:.1f} TP={tp:.1f} "
                       f"手数={lots}(风控{risk_pct:.0%})",
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
            self._append_trade_log(d)
        self._save_state()

    def _append_trade_log(self, d: TradeDecision):
        """Record open/close trades to the separate trade log."""
        is_close = d.action in ("CLOSE_LONG", "CLOSE_SHORT")
        entry = {
            "timestamp": d.timestamp,
            "symbol": d.symbol,
            "action": d.action,
            "type": "close" if is_close else "open",
            "direction": "LONG" if d.action in ("BUY", "CLOSE_LONG") else "SHORT",
            "lots": d.lots,
            "price": d.price,
            "atr": d.atr,
            "stop_loss": d.stop_loss,
            "take_profit": d.take_profit,
            "signal": d.signal,
            "composite_score": d.composite_score,
            "reason": d.reason,
            "order_result": d.order_result,
        }
        if is_close:
            entry["entry_price"] = d.entry_price
            entry["pnl_points"] = d.pnl_points
            entry["pnl_pct"] = d.pnl_pct
            entry["holding_seconds"] = d.holding_seconds
        with self._lock:
            self._trade_log.append(entry)

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

            with self._lock:
                trade_log_data = list(self._trade_log)
            trade_log_data = self._sanitize(trade_log_data)
            with open(TRADE_LOG_FILE, "w", encoding="utf-8") as f:
                json.dump(trade_log_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("保存自动交易记录失败: %s", e)

    def _save_config(self):
        """Persist trade config and contracts to disk."""
        try:
            PERSIST_DIR.mkdir(parents=True, exist_ok=True)
            data = {
                "contracts": self._contracts,
                "enabled": self.config.enabled,
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
                "strategy_mode": self.config.strategy_mode,
                "intraday_kline_duration": self.config.intraday_kline_duration,
                "intraday_scan_interval": self.config.intraday_scan_interval,
                "max_daily_loss": self.config.max_daily_loss,
                "max_consecutive_losses": self.config.max_consecutive_losses,
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
                self.config.strategy_mode = data.get("strategy_mode", self.config.strategy_mode)
                self.config.intraday_kline_duration = data.get("intraday_kline_duration", self.config.intraday_kline_duration)
                self.config.intraday_scan_interval = data.get("intraday_scan_interval", self.config.intraday_scan_interval)
                self.config.max_daily_loss = data.get("max_daily_loss", self.config.max_daily_loss)
                self.config.max_consecutive_losses = data.get("max_consecutive_losses", self.config.max_consecutive_losses)
                self.config.enabled = data.get("enabled", False)
                logger.info("已加载自动交易配置: 合约=%s, 模式=%s, 间隔=%ds, enabled=%s",
                            self._contracts, self.config.strategy_mode,
                            self.config.analysis_interval, self.config.enabled)
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

        if TRADE_LOG_FILE.exists():
            try:
                with open(TRADE_LOG_FILE, "r", encoding="utf-8") as f:
                    self._trade_log = json.load(f)
                logger.info("已加载 %d 条持仓交易记录", len(self._trade_log))
            except Exception as e:
                logger.warning("加载持仓交易记录失败: %s", e)


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
