"""Chinese futures price data.

Data sources (in priority order):
  1. 天勤量化 TqSdk (if configured) — tick-level accuracy, free for futures
  2. akshare / Sina Finance (fallback)

Supports:
  - Main contracts (C0, M0, RB0 …)
  - Specific month contracts (C2605, RB2510 …)
  - Daily / weekly / monthly / intraday intervals
"""

import logging
import re
from datetime import datetime, timedelta

import pandas as pd

logger = logging.getLogger(__name__)

_MAIN_CONTRACT_RE = re.compile(r"^[A-Z]{1,2}0$")


def _is_main_contract(symbol: str) -> bool:
    return bool(_MAIN_CONTRACT_RE.match(symbol))


def _fetch_daily(symbol: str, period_days: int) -> pd.DataFrame:
    """Fetch daily data using the best-suited akshare function."""
    import akshare as ak
    cutoff = datetime.now() - timedelta(days=period_days)

    # futures_zh_daily_sina returns English column names for all symbols
    try:
        df = ak.futures_zh_daily_sina(symbol=symbol)
        if df is not None and not df.empty:
            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"])
                df = df.set_index("date")
            cols = ["open", "high", "low", "close", "volume"]
            available = [c for c in cols if c in df.columns]
            df = df[available].copy()
            for col in available:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            df = df.dropna()
            df = df[df.index >= pd.Timestamp(cutoff)]
            if not df.empty:
                return df
    except Exception as e:
        logger.debug("futures_zh_daily_sina failed for %s: %s", symbol, e)

    # Fallback: futures_main_sina (Chinese column names)
    try:
        df = ak.futures_main_sina(symbol=symbol)
        if df is not None and not df.empty:
            col_map = {
                "日期": "date", "开盘价": "open", "最高价": "high",
                "最低价": "low", "收盘价": "close", "成交量": "volume",
            }
            df = df.rename(columns=col_map)
            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"])
                df = df.set_index("date")
            cols = ["open", "high", "low", "close", "volume"]
            available = [c for c in cols if c in df.columns]
            df = df[available].copy()
            for col in available:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            df = df.dropna()
            df = df[df.index >= pd.Timestamp(cutoff)]
            if not df.empty:
                return df
    except Exception as e:
        logger.debug("futures_main_sina failed for %s: %s", symbol, e)

    return pd.DataFrame()


def _fetch_intraday(symbol: str, period: str, period_days: int) -> pd.DataFrame:
    """Fetch intraday minute data.

    Args:
        period: '1', '5', '15', '30', '60'
    """
    import akshare as ak
    cutoff = datetime.now() - timedelta(days=period_days)

    try:
        df = ak.futures_zh_minute_sina(symbol=symbol, period=period)
        if df is None or df.empty:
            return pd.DataFrame()

        if "datetime" in df.columns:
            df["datetime"] = pd.to_datetime(df["datetime"])
            df = df.set_index("datetime")

        cols = ["open", "high", "low", "close", "volume"]
        available = [c for c in cols if c in df.columns]
        df = df[available].copy()
        for col in available:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna()
        df = df[df.index >= pd.Timestamp(cutoff)]
        return df

    except Exception as e:
        logger.warning("futures_zh_minute_sina failed for %s period=%s: %s", symbol, period, e)
        return pd.DataFrame()


def _resample_weekly_monthly(df: pd.DataFrame, freq: str) -> pd.DataFrame:
    """Resample daily data to weekly or monthly."""
    if df.empty:
        return df
    agg = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
    }
    if "volume" in df.columns:
        agg["volume"] = "sum"
    available_agg = {k: v for k, v in agg.items() if k in df.columns}
    resampled = df.resample(freq).agg(available_agg).dropna()
    return resampled


def _try_tqsdk(symbol: str, interval: str, period_days: int) -> pd.DataFrame:
    """Try fetching data via TqSdk. Returns empty DataFrame if unavailable."""
    try:
        from src.data.tqsdk_service import get_tq_service
        svc = get_tq_service()
        if not svc.is_ready:
            return pd.DataFrame()

        duration_map = {
            "1m": 60, "5m": 300, "15m": 900, "daily": 86400,
        }
        duration = duration_map.get(interval)
        if duration is None:
            return pd.DataFrame()

        bars_estimate = {
            60: period_days * 240,
            300: period_days * 48,
            900: period_days * 16,
            86400: period_days,
        }
        count = min(bars_estimate.get(duration, period_days), 8000)

        df = svc.get_klines(symbol, duration, count)
        if df is not None and not df.empty:
            logger.info("天勤K线: %s %s %d条", symbol, interval, len(df))
            return df
    except Exception as e:
        logger.debug("天勤K线获取失败 %s: %s", symbol, e)
    return pd.DataFrame()


def fetch_futures_price(
    symbol: str,
    period_days: int = 120,
    interval: str = "daily",
) -> pd.DataFrame:
    """Fetch Chinese futures OHLCV data with flexible interval.

    Data source priority: TqSdk (if configured) > akshare (Sina).

    Args:
        symbol: Futures symbol. Main contracts: 'C0', 'M0', 'RB0'.
                Specific months: 'C2605', 'RB2510'.
        period_days: Number of calendar days of history.
        interval: '1m', '5m', '15m', 'daily', 'weekly', 'monthly'.

    Returns:
        DataFrame with columns: open, high, low, close, volume.
        Indexed by date/datetime. Empty DataFrame on failure.
    """
    symbol = symbol.strip().upper()

    # 1) Try TqSdk first (not for weekly/monthly, we resample daily)
    if interval not in ("weekly", "monthly") and not _is_main_contract(symbol):
        df = _try_tqsdk(symbol, interval, period_days)
        if not df.empty:
            return df

    # 2) Fallback to akshare
    try:
        if interval in ("1m", "5m", "15m"):
            minute_map = {"1m": "1", "5m": "5", "15m": "15"}
            df = _fetch_intraday(symbol, minute_map[interval], period_days)
        elif interval in ("weekly", "monthly"):
            df = _fetch_daily(symbol, max(period_days, 365))
            freq = "W" if interval == "weekly" else "ME"
            df = _resample_weekly_monthly(df, freq)
        else:
            df = _fetch_daily(symbol, period_days)

        if not df.empty:
            logger.info("Fetched %d bars for futures %s (interval=%s)", len(df), symbol, interval)
        else:
            logger.warning("No price data for futures %s (interval=%s)", symbol, interval)

        return df

    except Exception as e:
        logger.error("Futures price fetch failed for %s: %s", symbol, e)
        return pd.DataFrame()
