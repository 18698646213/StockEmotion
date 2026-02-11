"""China A-share price data from akshare."""

import logging
from datetime import datetime, timedelta

import pandas as pd

logger = logging.getLogger(__name__)

# Map our interval names to akshare period parameter
_AK_PERIOD_MAP = {
    "1m": "1",         # 1 分钟
    "5m": "5",          # 5 分钟
    "15m": "15",        # 15 分钟
    "daily": "daily",   # 日K
    "weekly": "weekly",  # 周K
    "monthly": "monthly",  # 月K
}


def _normalize_stock_code(code: str) -> str:
    """Ensure stock code is 6 digits."""
    return code.strip().zfill(6)


def fetch_cn_price(
    code: str,
    period_days: int = 120,
    interval: str = "daily",
) -> pd.DataFrame:
    """Fetch A-share stock historical OHLCV data via akshare.

    Args:
        code: A-share stock code (e.g. '600519').
        period_days: Number of calendar days of history to fetch.
        interval: One of '1m', '5m', '15m', 'daily', 'weekly', 'monthly'.

    Returns:
        DataFrame with columns: open, high, low, close, volume.
        Indexed by date. Returns empty DataFrame on failure.
    """
    code = _normalize_stock_code(code)

    try:
        import akshare as ak

        end_date = datetime.now()
        start_date = end_date - timedelta(days=period_days)
        ak_period = _AK_PERIOD_MAP.get(interval, "daily")

        # For intraday data use stock_zh_a_hist_min_em
        if interval in ("1m", "5m", "15m"):
            try:
                df = ak.stock_zh_a_hist_min_em(
                    symbol=code,
                    period=ak_period,
                    adjust="qfq",
                )
            except Exception:
                logger.warning("分钟数据获取失败，降级为日K: %s", code)
                df = ak.stock_zh_a_hist(
                    symbol=code,
                    period="daily",
                    start_date=start_date.strftime("%Y%m%d"),
                    end_date=end_date.strftime("%Y%m%d"),
                    adjust="qfq",
                )
        else:
            df = ak.stock_zh_a_hist(
                symbol=code,
                period=ak_period,
                start_date=start_date.strftime("%Y%m%d"),
                end_date=end_date.strftime("%Y%m%d"),
                adjust="qfq",
            )

        if df is None or df.empty:
            logger.warning("No price data returned for A-share %s (interval=%s)", code, interval)
            return pd.DataFrame()

        # Normalize column names
        col_map = {
            "日期": "date",
            "时间": "date",
            "开盘": "open",
            "最高": "high",
            "最低": "low",
            "收盘": "close",
            "成交量": "volume",
        }
        df = df.rename(columns=col_map)

        # Set date as index
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date")

        # Keep only needed columns
        cols = ["open", "high", "low", "close", "volume"]
        available = [c for c in cols if c in df.columns]
        df = df[available].copy()

        # Ensure numeric types
        for col in available:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df = df.dropna()

        logger.info("Fetched %d price bars for A-share %s (interval=%s)", len(df), code, interval)
        return df

    except Exception as e:
        logger.error("A-share price fetch failed for %s: %s", code, e)
        return pd.DataFrame()
