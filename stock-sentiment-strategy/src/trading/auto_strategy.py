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


class AutoTrader:
    """AI-driven auto-trading engine with ATR-based risk management."""

    def __init__(self):
        self.config = TradeConfig()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._decisions: list[TradeDecision] = []
        self._lock = threading.Lock()
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
        # 确保旧线程已完全退出
        if self._thread is not None and self._thread.is_alive():
            logger.info("等待旧交易线程退出...")
            self._thread.join(timeout=5)

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
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=10)
            self._thread = None
        logger.info("自动交易已停止")

    def get_status(self) -> dict:
        managed = {}
        for sym, ps in self._positions.items():
            managed[sym] = {
                "direction": ps.direction,
                "entry_price": ps.entry_price,
                "atr": round(ps.atr, 2),
                "stop_loss": round(ps.stop_loss, 2),
                "take_profit": round(ps.take_profit, 2),
                "lots": ps.lots,
            }
        return {
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
            },
            "managed_positions": managed,
            "decisions_count": len(self._decisions),
            "trading_hours": self._is_trading_hours(),
        }

    def get_decisions(self, limit: int = 50) -> list[dict]:
        with self._lock:
            items = self._decisions[-limit:]
        return [
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
            }
            for d in reversed(items)
        ]

    # ------------------------------------------------------------------
    # Core loop
    # ------------------------------------------------------------------

    def _trading_loop(self):
        logger.info("自动交易循环启动")
        while self._running:
            try:
                self._run_one_cycle()
            except Exception as e:
                logger.error("自动交易循环异常: %s", e)
            for _ in range(self.config.analysis_interval):
                if not self._running:
                    break
                time.sleep(1)
        logger.info("自动交易循环结束")

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
        from src.data.tqsdk_service import get_tq_service

        if not self._is_trading_hours():
            logger.debug("当前为休市时段，跳过本轮交易")
            return

        svc = get_tq_service()
        if not svc.is_ready:
            logger.warning("天勤服务未就绪，跳过本轮交易")
            return

        for symbol in self._contracts:
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

        # 2. Real-time quote
        quote = svc.get_quote(symbol)
        if not quote or quote.get("price", 0) <= 0:
            return
        price = quote["price"]

        # 3. ATR(14) from 15-min K-lines
        atr = svc.get_atr(symbol, ATR_PERIOD, ATR_KLINE_DURATION)
        if atr <= 0:
            logger.debug("%s ATR 不可用，跳过", symbol)
            return

        # 4. Sync managed position state with actual TqSdk position
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
                return TradeDecision(
                    timestamp=now, symbol=symbol, action="CLOSE_LONG",
                    lots=long_vol, price=price,
                    reason=f"ATR止损 (现价{price:.1f} <= 止损{ps.stop_loss:.1f}, "
                           f"入场{ps.entry_price:.1f}, ATR={ps.atr:.1f})",
                    signal="STOP_LOSS", composite_score=0,
                    atr=atr, stop_loss=ps.stop_loss, take_profit=ps.take_profit)

            if price >= ps.take_profit:
                return TradeDecision(
                    timestamp=now, symbol=symbol, action="CLOSE_LONG",
                    lots=long_vol, price=price,
                    reason=f"ATR止盈 (现价{price:.1f} >= 目标{ps.take_profit:.1f}, "
                           f"入场{ps.entry_price:.1f}, ATR={ps.atr:.1f})",
                    signal="TAKE_PROFIT", composite_score=0,
                    atr=atr, stop_loss=ps.stop_loss, take_profit=ps.take_profit)

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
                return TradeDecision(
                    timestamp=now, symbol=symbol, action="CLOSE_SHORT",
                    lots=short_vol, price=price,
                    reason=f"ATR止损 (现价{price:.1f} >= 止损{ps.stop_loss:.1f}, "
                           f"入场{ps.entry_price:.1f}, ATR={ps.atr:.1f})",
                    signal="STOP_LOSS", composite_score=0,
                    atr=atr, stop_loss=ps.stop_loss, take_profit=ps.take_profit)

            if price <= ps.take_profit:
                return TradeDecision(
                    timestamp=now, symbol=symbol, action="CLOSE_SHORT",
                    lots=short_vol, price=price,
                    reason=f"ATR止盈 (现价{price:.1f} <= 目标{ps.take_profit:.1f}, "
                           f"入场{ps.entry_price:.1f}, ATR={ps.atr:.1f})",
                    signal="TAKE_PROFIT", composite_score=0,
                    atr=atr, stop_loss=ps.stop_loss, take_profit=ps.take_profit)

        return None

    # ------------------------------------------------------------------
    # Entry checks (AI signal-based)
    # ------------------------------------------------------------------

    def _check_entry(self, symbol: str, signal: str, composite: float,
                     price: float, atr: float) -> TradeDecision:
        now = datetime.now().isoformat()
        threshold = self.config.signal_threshold
        sl_mult = self.config.atr_sl_multiplier
        tp_mult = self.config.atr_tp_multiplier

        if signal in ("STRONG_BUY", "BUY") and composite >= threshold:
            lots = min(self.config.max_lots, 2 if signal == "STRONG_BUY" else 1)
            sl = price - sl_mult * atr
            tp = price + tp_mult * atr
            return TradeDecision(
                timestamp=now, symbol=symbol, action="BUY",
                lots=lots, price=price,
                reason=f"AI做多 {signal} 得分{composite:.2f} | "
                       f"ATR={atr:.1f} SL={sl:.1f} TP={tp:.1f}",
                signal=signal, composite_score=composite,
                atr=atr, stop_loss=sl, take_profit=tp)

        if signal in ("STRONG_SELL", "SELL") and composite <= -threshold:
            lots = min(self.config.max_lots, 2 if signal == "STRONG_SELL" else 1)
            sl = price + sl_mult * atr
            tp = price - tp_mult * atr
            return TradeDecision(
                timestamp=now, symbol=symbol, action="SELL",
                lots=lots, price=price,
                reason=f"AI做空 {signal} 得分{composite:.2f} | "
                       f"ATR={atr:.1f} SL={sl:.1f} TP={tp:.1f}",
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
            logger.info("交易决策: %s %s %s %d手 @ %.1f | ATR=%.1f SL=%.1f TP=%.1f | %s",
                         d.symbol, d.action, d.reason, d.lots, d.price,
                         d.atr, d.stop_loss, d.take_profit, d.order_result or "")
        self._save_state()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_state(self):
        """Persist decisions and managed positions to disk."""
        try:
            PERSIST_DIR.mkdir(parents=True, exist_ok=True)

            with self._lock:
                decisions_data = [
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
                    }
                    for d in self._decisions
                ]

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
                logger.info("已加载自动交易配置: 合约=%s, 间隔=%ds",
                            self._contracts, self.config.analysis_interval)
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
