"""天勤量化 (TqSdk) 数据 + 交易服务。

提供期货实时行情、K线数据、模拟/实盘交易能力。
需要注册快期账户：https://account.shinnytech.com/

使用方式：
    from src.data.tqsdk_service import get_tq_service
    svc = get_tq_service()           # 获取全局单例
    svc.start("user", "password")    # 启动（仅首次）
    quote = svc.get_quote("C2605")   # 获取行情
    df = svc.get_klines("C2605", 86400, 200)  # 日线 K 线
    svc.place_order("C2605", "BUY", "OPEN", 1)  # 下单
"""

import json
import logging
import math
import re
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

PERSIST_DIR = Path(__file__).resolve().parent.parent.parent / "data"
TRADE_LOG_FILE = PERSIST_DIR / "tqsdk_trade_log.json"

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 合约代码映射: 我们的格式 -> TqSdk 格式
# 我们: C2605, RB2510, CU2605
# TqSdk: DCE.c2605, SHFE.rb2510, SHFE.cu2605
# ---------------------------------------------------------------------------

_EXCHANGE_MAP: dict[str, str] = {
    # 大连商品交易所 (DCE) — 小写
    "A": "DCE", "B": "DCE", "C": "DCE", "CS": "DCE",
    "I": "DCE", "J": "DCE", "JD": "DCE", "JM": "DCE",
    "L": "DCE", "LH": "DCE", "LG": "DCE", "M": "DCE",
    "P": "DCE", "PP": "DCE", "V": "DCE", "Y": "DCE",
    "EG": "DCE", "EB": "DCE", "PG": "DCE", "RR": "DCE",
    "BZ": "DCE",

    # 上海期货交易所 (SHFE) — 小写
    "CU": "SHFE", "AL": "SHFE", "ZN": "SHFE", "PB": "SHFE",
    "NI": "SHFE", "SN": "SHFE", "AU": "SHFE", "AG": "SHFE",
    "RB": "SHFE", "HC": "SHFE", "BU": "SHFE", "RU": "SHFE",
    "FU": "SHFE", "SP": "SHFE", "SS": "SHFE", "AO": "SHFE",
    "BR": "SHFE", "WR": "SHFE",

    # 郑州商品交易所 (CZCE) — 大写, 3位数字
    "TA": "CZCE", "MA": "CZCE", "CF": "CZCE", "SR": "CZCE",
    "OI": "CZCE", "RM": "CZCE", "FG": "CZCE", "SA": "CZCE",
    "AP": "CZCE", "CJ": "CZCE", "UR": "CZCE", "PF": "CZCE",
    "PK": "CZCE", "SF": "CZCE", "SM": "CZCE", "CY": "CZCE",
    "WH": "CZCE", "RS": "CZCE", "SH": "CZCE", "PX": "CZCE",
    "PR": "CZCE", "PL": "CZCE",

    # 上海国际能源交易中心 (INE) — 小写
    "SC": "INE", "NR": "INE", "LU": "INE", "BC": "INE",
    "EC": "INE",

    # 中国金融期货交易所 (CFFEX) — 大写
    "IF": "CFFEX", "IH": "CFFEX", "IC": "CFFEX", "IM": "CFFEX",
    "TF": "CFFEX", "TS": "CFFEX", "T": "CFFEX",

    # 广州期货交易所 (GFEX) — 小写
    "SI": "GFEX", "LC": "GFEX", "PS": "GFEX", "PT": "GFEX",
    "PD": "GFEX",
}

_BASE_RE = re.compile(r"^([A-Z]{1,2})(\d+)$")


def to_tq_symbol(our_symbol: str) -> Optional[str]:
    """Convert our symbol (e.g. 'C2605') to TqSdk format (e.g. 'DCE.c2605').

    CZCE uses uppercase + 3-digit month; others use lowercase + 4-digit month.
    """
    sym = our_symbol.strip().upper()
    m = _BASE_RE.match(sym)
    if not m:
        return None
    base, digits = m.group(1), m.group(2)
    exchange = _EXCHANGE_MAP.get(base)
    if not exchange:
        return None

    if exchange == "CZCE":
        month = digits[-3:] if len(digits) >= 3 else digits
        return f"{exchange}.{base}{month}"
    elif exchange in ("CFFEX",):
        return f"{exchange}.{base}{digits}"
    else:
        return f"{exchange}.{base.lower()}{digits}"


def from_tq_symbol(tq_symbol: str) -> str:
    """Convert TqSdk symbol (e.g. 'DCE.c2605') back to our format ('C2605').

    CZCE uses 3-digit month codes (e.g. SA605) while our format uses 4-digit
    (SA2605), so we prepend '2' for the decade.
    """
    if "." not in tq_symbol:
        return tq_symbol.upper()
    exchange, code = tq_symbol.split(".", 1)
    code_upper = code.upper()
    if exchange == "CZCE":
        import re
        m = re.match(r"^([A-Z]+)(\d{3})$", code_upper)
        if m:
            return f"{m.group(1)}2{m.group(2)}"
    return code_upper


# ---------------------------------------------------------------------------
# TqSdk 后台数据服务
# ---------------------------------------------------------------------------

class TqDataService:
    """Long-running TqSdk service in a background thread.

    TqSdk uses asyncio internally and requires its own event loop.
    We run it in a daemon thread and communicate via thread-safe caches.
    Supports both TqSim (paper) and TqAccount (live) trading modes.
    """

    def __init__(self):
        self._api = None
        self._user = ""
        self._password = ""
        self._trade_mode = "sim"      # "sim" or "live"
        self._broker_id = ""
        self._broker_account = ""
        self._broker_password = ""
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._ready = threading.Event()

        # Caches (thread-safe reads since Python GIL protects dict reads)
        self._quotes: dict[str, object] = {}       # tq_symbol -> Quote object
        self._kline_cache: dict[str, pd.DataFrame] = {}  # cache key -> DataFrame
        self._atr_cache: dict[str, float] = {}     # cache key -> ATR value

        # Pending subscription requests
        self._pending_quotes: list[str] = []
        self._pending_klines: list[tuple] = []      # (tq_symbol, duration, count, cache_key)
        self._pending_atr: list[tuple] = []          # (tq_symbol, duration, count, period, cache_key)
        self._lock = threading.Lock()

        # Trading state
        self._account = None          # TqSdk account object
        self._positions: dict[str, object] = {}  # tq_symbol -> Position object
        self._pending_orders: list[dict] = []    # queued order requests
        self._order_results: dict[str, dict] = {}  # order_id -> result
        self._trade_log: list[dict] = []         # all executed trades
        self._load_trade_log()

    @property
    def is_ready(self) -> bool:
        return self._ready.is_set() and self._running

    @property
    def trade_mode(self) -> str:
        """Current trade mode: 'sim' or 'live'."""
        return self._trade_mode

    def start(self, user: str, password: str, *,
              trade_mode: str = "sim",
              broker_id: str = "",
              broker_account: str = "",
              broker_password: str = "") -> bool:
        """Start the TqSdk background service.

        Args:
            trade_mode: "sim" for paper trading (TqSim), "live" for real trading (TqAccount).
            broker_id: Required for live mode — broker name (e.g. "H海通期货").
            broker_account: Required for live mode — fund account number.
            broker_password: Required for live mode — trading password.
        """
        if not user or not password:
            logger.info("天勤量化未配置账户，跳过启动")
            return False
        if self._running:
            return True

        self._user = user
        self._password = password
        self._trade_mode = trade_mode if trade_mode in ("sim", "live") else "sim"
        self._broker_id = broker_id
        self._broker_account = broker_account
        self._broker_password = broker_password

        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="tqsdk")
        self._running = True
        self._thread.start()

        ok = self._ready.wait(timeout=15)
        if ok:
            mode_label = "实盘" if self._trade_mode == "live" else "模拟盘"
            logger.info("天勤量化服务已启动 (%s)", mode_label)
        else:
            logger.warning("天勤量化服务启动超时")
            self._running = False
        return ok

    def stop(self):
        self._running = False
        if self._api:
            try:
                self._api.close()
            except Exception:
                pass
        self._ready.clear()

    def _run_loop(self):
        """Background thread: runs the TqSdk event loop."""
        try:
            from tqsdk import TqApi, TqAuth

            auth = TqAuth(self._user, self._password)
            if self._trade_mode == "live" and self._broker_id and self._broker_account:
                from tqsdk import TqAccount
                account = TqAccount(
                    self._broker_id, self._broker_account, self._broker_password)
                self._api = TqApi(auth=auth, account=account)
                logger.info("天勤以实盘模式连接: %s / %s", self._broker_id, self._broker_account)
            else:
                self._api = TqApi(auth=auth)
                logger.info("天勤以模拟盘模式连接 (TqSim)")

            self._account = self._api.get_account()
            self._ready.set()

            while self._running:
                self._process_pending()
                self._process_orders()
                try:
                    self._api.wait_update(deadline=time.time() + 0.5)
                except Exception as e:
                    if self._running:
                        logger.debug("tqsdk wait_update: %s", e)
        except Exception as e:
            logger.error("天勤量化服务异常: %s", e)
        finally:
            self._ready.clear()
            self._running = False
            if self._api:
                try:
                    self._api.close()
                except Exception:
                    pass
                self._api = None

    def _process_pending(self):
        """Process queued subscription requests (must run in tqsdk thread)."""
        with self._lock:
            quotes = list(self._pending_quotes)
            self._pending_quotes.clear()
            klines = list(self._pending_klines)
            self._pending_klines.clear()
            atr_reqs = list(self._pending_atr)
            self._pending_atr.clear()

        for tq_sym in quotes:
            if tq_sym not in self._quotes:
                try:
                    self._quotes[tq_sym] = self._api.get_quote(tq_sym)
                    logger.debug("天勤订阅行情: %s", tq_sym)
                except Exception as e:
                    logger.warning("天勤订阅 %s 失败: %s", tq_sym, e)
            if tq_sym not in self._positions:
                try:
                    self._positions[tq_sym] = self._api.get_position(tq_sym)
                except Exception as e:
                    logger.warning("天勤订阅持仓 %s 失败: %s", tq_sym, e)

        for tq_sym, duration, count, cache_key in klines:
            try:
                df = self._api.get_kline_serial(tq_sym, duration, data_length=count)
                if df is not None and not df.empty:
                    self._kline_cache[cache_key] = df
                    logger.debug("天勤K线缓存: %s (%ds x %d)", tq_sym, duration, count)
            except Exception as e:
                logger.warning("天勤K线 %s 失败: %s", tq_sym, e)

        for tq_sym, duration, count, period, cache_key in atr_reqs:
            try:
                from tqsdk.ta import ATR as TqATR
                kline_serial = self._api.get_kline_serial(
                    tq_sym, duration, data_length=count)
                if kline_serial is not None and len(kline_serial) >= period:
                    atr_df = TqATR(kline_serial, period)
                    atr_val = atr_df["atr"].iloc[-1]
                    if _is_valid(atr_val) and atr_val > 0:
                        self._atr_cache[cache_key] = float(atr_val)
                        logger.debug("天勤ATR(%d): %s = %.2f (%ds K线)",
                                     period, tq_sym, atr_val, duration)
            except Exception as e:
                logger.warning("天勤ATR计算失败 %s: %s", tq_sym, e)

    # ----- Public API (called from FastAPI threads) -----

    def get_quote(self, our_symbol: str) -> Optional[dict]:
        """Get latest quote for a futures contract. Returns dict or None."""
        if not self.is_ready:
            return None

        tq_sym = to_tq_symbol(our_symbol)
        if not tq_sym:
            return None

        if tq_sym not in self._quotes:
            with self._lock:
                self._pending_quotes.append(tq_sym)
            # Wait briefly for initial data
            for _ in range(30):
                time.sleep(0.1)
                if tq_sym in self._quotes:
                    q = self._quotes[tq_sym]
                    if _is_valid(q.last_price):
                        break

        q = self._quotes.get(tq_sym)
        if q is None:
            return None

        lp = q.last_price
        if not _is_valid(lp):
            return None

        pre_settle = q.pre_settlement if _is_valid(q.pre_settlement) else 0
        pre_close = q.pre_close if _is_valid(q.pre_close) else 0
        change_base = pre_settle or pre_close
        change_pct = ((lp - change_base) / change_base * 100) if change_base else 0
        change_amt = lp - change_base if change_base else 0
        high_val = q.highest if _is_valid(q.highest) else lp
        low_val = q.lowest if _is_valid(q.lowest) else lp
        amp = ((high_val - low_val) / change_base * 100) if change_base else 0

        return {
            "code": from_tq_symbol(tq_sym),
            "name": getattr(q, "instrument_name", "") or from_tq_symbol(tq_sym),
            "market": "FUTURES",
            "price": lp,
            "change_pct": round(change_pct, 4),
            "change_amt": round(change_amt, 2),
            "volume": q.volume if _is_valid(q.volume) else 0,
            "open_interest": q.open_interest if _is_valid(q.open_interest) else 0,
            "amplitude": round(amp, 2),
            "settlement": q.settlement if _is_valid(q.settlement) else 0,
            "pre_settlement": pre_settle,
            "pre_close": pre_close,
            "open_price": q.open if _is_valid(q.open) else 0,
            "high": high_val,
            "low": low_val,
            "turnover": q.amount if _is_valid(q.amount) else 0,
            "upper_limit": q.upper_limit if _is_valid(q.upper_limit) else 0,
            "lower_limit": q.lower_limit if _is_valid(q.lower_limit) else 0,
            "pre_open_interest": q.pre_open_interest if _is_valid(q.pre_open_interest) else 0,
            "volume_multiple": q.volume_multiple if _is_valid(q.volume_multiple) else 0,
            "bid_price1": q.bid_price1 if _is_valid(q.bid_price1) else 0,
            "ask_price1": q.ask_price1 if _is_valid(q.ask_price1) else 0,
        }

    def get_klines(self, our_symbol: str, duration_seconds: int = 86400,
                   count: int = 200) -> Optional[pd.DataFrame]:
        """Get K-line data. Returns DataFrame with OHLCV columns or None.

        duration_seconds: K-line period (60=1min, 300=5min, 900=15min, 86400=daily)
        count: number of bars (max 8000)
        """
        if not self.is_ready:
            return None

        tq_sym = to_tq_symbol(our_symbol)
        if not tq_sym:
            return None

        cache_key = f"{tq_sym}:{duration_seconds}:{count}"

        if cache_key not in self._kline_cache:
            with self._lock:
                self._pending_klines.append((tq_sym, duration_seconds, count, cache_key))
            for _ in range(50):
                time.sleep(0.1)
                if cache_key in self._kline_cache:
                    break

        raw = self._kline_cache.get(cache_key)
        if raw is None or raw.empty:
            return None

        df = raw.copy()
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.set_index("datetime")
        df = df.rename(columns={
            "open": "open", "high": "high", "low": "low", "close": "close",
            "volume": "volume", "close_oi": "open_interest",
        })
        cols = ["open", "high", "low", "close", "volume"]
        if "open_interest" in df.columns:
            cols.append("open_interest")
        return df[cols].dropna(subset=["close"])

    def get_atr(self, our_symbol: str, period: int = 14,
                 duration_seconds: int = 900) -> float:
        """Get ATR(period) using tqsdk.ta.ATR official implementation.

        Uses TqSdk's built-in ATR calculation on K-line serial data.
        See: https://doc.shinnytech.com/tqsdk/latest/reference/tqsdk.ta.html#tqsdk.ta.ATR

        Args:
            period: ATR lookback period (default 14)
            duration_seconds: K-line granularity (default 900 = 15min)
        Returns:
            ATR value, or 0.0 if data unavailable.
        """
        if not self.is_ready:
            return 0.0

        tq_sym = to_tq_symbol(our_symbol)
        if not tq_sym:
            return 0.0

        count = period + 10
        cache_key = f"atr:{tq_sym}:{duration_seconds}:{period}"

        with self._lock:
            self._pending_atr.append((tq_sym, duration_seconds, count, period, cache_key))

        for _ in range(50):
            time.sleep(0.1)
            if cache_key in self._atr_cache:
                return self._atr_cache[cache_key]

        return 0.0

    # ----- Order processing (runs in TqSdk thread) -----

    def _process_orders(self):
        """Process queued order requests. Must run in the TqSdk thread."""
        with self._lock:
            orders = list(self._pending_orders)
            self._pending_orders.clear()

        for req in orders:
            oid = req["id"]
            tq_sym = req["tq_symbol"]
            direction = req["direction"]
            offset = req["offset"]
            volume = req["volume"]
            price = req.get("price")

            try:
                # Ensure we have position info
                if tq_sym not in self._positions:
                    self._positions[tq_sym] = self._api.get_position(tq_sym)

                if price and price > 0:
                    order = self._api.insert_order(
                        symbol=tq_sym, direction=direction, offset=offset,
                        volume=volume, limit_price=price)
                else:
                    order = self._api.insert_order(
                        symbol=tq_sym, direction=direction, offset=offset,
                        volume=volume)

                self._order_results[oid] = {
                    "id": oid, "status": "SUBMITTED",
                    "symbol": from_tq_symbol(tq_sym),
                    "direction": direction, "offset": offset,
                    "volume": volume, "price": price or 0,
                    "time": datetime.now().isoformat(),
                    "tq_order": order,
                }
                logger.info("天勤下单: %s %s %s %d手 @ %s",
                            tq_sym, direction, offset, volume, price or "市价")
            except Exception as e:
                self._order_results[oid] = {
                    "id": oid, "status": "ERROR", "error": str(e),
                    "symbol": from_tq_symbol(tq_sym),
                    "direction": direction, "offset": offset,
                    "volume": volume, "price": price or 0,
                    "time": datetime.now().isoformat(),
                }
                logger.error("天勤下单失败: %s", e)

    # ----- Trading Public API (called from FastAPI threads) -----

    def get_account_info(self) -> Optional[dict]:
        """Get account balance, available funds, etc."""
        if not self.is_ready or self._account is None:
            return None
        a = self._account
        return {
            "balance": a.balance if _is_valid(a.balance) else 0,
            "available": a.available if _is_valid(a.available) else 0,
            "float_profit": a.float_profit if _is_valid(a.float_profit) else 0,
            "position_profit": a.position_profit if _is_valid(a.position_profit) else 0,
            "close_profit": a.close_profit if _is_valid(a.close_profit) else 0,
            "margin": a.margin if _is_valid(a.margin) else 0,
            "commission": a.commission if _is_valid(a.commission) else 0,
            "risk_ratio": a.risk_ratio if _is_valid(a.risk_ratio) else 0,
            "static_balance": a.static_balance if _is_valid(a.static_balance) else 0,
        }

    def get_position_info(self, our_symbol: str) -> Optional[dict]:
        """Get position info for a specific contract."""
        if not self.is_ready:
            return None
        tq_sym = to_tq_symbol(our_symbol)
        if not tq_sym:
            return None

        if tq_sym not in self._positions:
            with self._lock:
                self._pending_quotes.append(tq_sym)
            time.sleep(0.5)

        pos = self._positions.get(tq_sym)
        if pos is None:
            return {"symbol": our_symbol, "long_volume": 0, "short_volume": 0,
                    "long_avg_price": 0, "short_avg_price": 0, "float_profit": 0}
        fp_long = pos.float_profit_long if _is_valid(pos.float_profit_long) else 0
        fp_short = pos.float_profit_short if _is_valid(pos.float_profit_short) else 0
        return {
            "symbol": our_symbol,
            "long_volume": int(pos.pos_long) if _is_valid(pos.pos_long) else 0,
            "short_volume": int(pos.pos_short) if _is_valid(pos.pos_short) else 0,
            "long_avg_price": pos.open_price_long if _is_valid(pos.open_price_long) else 0,
            "short_avg_price": pos.open_price_short if _is_valid(pos.open_price_short) else 0,
            "float_profit": fp_long + fp_short,
        }

    def get_all_positions(self) -> list[dict]:
        """Get all positions with non-zero volume.

        Proactively subscribes positions for all contracts that have quotes
        subscribed, so we never miss positions opened via other channels.
        """
        if not self.is_ready:
            return []

        need_sub = [s for s in self._quotes if s not in self._positions]
        if need_sub:
            with self._lock:
                self._pending_quotes.extend(need_sub)
            import time
            time.sleep(0.3)

        result = []
        for tq_sym, pos in self._positions.items():
            long_vol = int(pos.pos_long) if _is_valid(pos.pos_long) else 0
            short_vol = int(pos.pos_short) if _is_valid(pos.pos_short) else 0
            if long_vol == 0 and short_vol == 0:
                continue

            our_sym = from_tq_symbol(tq_sym)
            last_price = 0.0
            q = self._quotes.get(tq_sym)
            if q is not None:
                lp = getattr(q, "last_price", None)
                if lp is not None and _is_valid(lp):
                    last_price = float(lp)

            fp_long = pos.float_profit_long if _is_valid(pos.float_profit_long) else 0
            fp_short = pos.float_profit_short if _is_valid(pos.float_profit_short) else 0
            result.append({
                "symbol": our_sym,
                "long_volume": long_vol,
                "short_volume": short_vol,
                "long_avg_price": pos.open_price_long if _is_valid(pos.open_price_long) else 0,
                "short_avg_price": pos.open_price_short if _is_valid(pos.open_price_short) else 0,
                "float_profit": fp_long + fp_short,
                "last_price": last_price,
            })
        return result

    def place_order(self, our_symbol: str, direction: str, offset: str,
                    volume: int, price: float = 0) -> dict:
        """Queue an order. Returns order tracking dict.

        Args:
            direction: "BUY" or "SELL"
            offset: "OPEN" or "CLOSE" or "CLOSETODAY"
            volume: number of lots
            price: limit price (0 = market order)
        """
        if not self.is_ready:
            return {"id": "", "status": "ERROR", "error": "天勤服务未连接"}

        tq_sym = to_tq_symbol(our_symbol)
        if not tq_sym:
            return {"id": "", "status": "ERROR", "error": f"无法识别合约: {our_symbol}"}

        oid = str(uuid.uuid4())[:8]
        req = {
            "id": oid, "tq_symbol": tq_sym,
            "direction": direction, "offset": offset,
            "volume": volume, "price": price if price > 0 else None,
        }

        with self._lock:
            self._pending_orders.append(req)

        # Wait for order to be processed
        for _ in range(50):
            time.sleep(0.1)
            if oid in self._order_results:
                result = self._order_results[oid]
                self._trade_log.append(result)
                self._save_trade_log()
                return result

        return {"id": oid, "status": "TIMEOUT", "error": "下单超时"}

    def close_position(self, our_symbol: str, direction: str = "") -> dict:
        """Close all positions for a symbol. If direction is empty, close both."""
        pos = self.get_position_info(our_symbol)
        if not pos:
            return {"status": "ERROR", "error": "无法获取持仓"}

        results = []
        if pos["long_volume"] > 0 and direction in ("", "LONG"):
            r = self.place_order(our_symbol, "SELL", "CLOSE", pos["long_volume"])
            results.append(r)
        if pos["short_volume"] > 0 and direction in ("", "SHORT"):
            r = self.place_order(our_symbol, "BUY", "CLOSE", pos["short_volume"])
            results.append(r)

        if not results:
            return {"status": "OK", "message": "无持仓需要平仓"}
        return {"status": "OK", "orders": results}

    def get_trade_log(self) -> list[dict]:
        """Get all trade log entries."""
        return list(self._trade_log)

    def _save_trade_log(self):
        """Persist trade log to JSON file."""
        try:
            PERSIST_DIR.mkdir(parents=True, exist_ok=True)
            serializable = []
            for entry in self._trade_log:
                clean = {}
                for k, v in entry.items():
                    if k == "tq_order":
                        continue
                    clean[k] = v
                serializable.append(clean)
            with open(TRADE_LOG_FILE, "w", encoding="utf-8") as f:
                json.dump(serializable, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("保存成交记录失败: %s", e)

    def _load_trade_log(self):
        """Restore trade log from JSON file."""
        if TRADE_LOG_FILE.exists():
            try:
                with open(TRADE_LOG_FILE, "r", encoding="utf-8") as f:
                    self._trade_log = json.load(f)
                logger.info("已加载 %d 条成交记录", len(self._trade_log))
            except Exception as e:
                logger.warning("加载成交记录失败: %s", e)

    def get_all_quotes_for_commodity(self, cn_name: str) -> list[dict]:
        """Get quotes for all contracts of a commodity (for search results).

        This uses the main contract + discovers available contracts.
        Not as straightforward as akshare's futures_zh_realtime.
        Falls back to None if not possible.
        """
        return []


def _is_valid(val) -> bool:
    """Check if a numeric value is valid (not NaN/None)."""
    if val is None:
        return False
    try:
        return not math.isnan(float(val))
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------

_instance: Optional[TqDataService] = None
_instance_lock = threading.Lock()


def get_tq_service() -> TqDataService:
    """Get or create the global TqDataService singleton."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = TqDataService()
    return _instance
