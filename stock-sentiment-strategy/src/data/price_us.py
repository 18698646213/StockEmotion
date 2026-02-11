"""US stock price data from Yahoo Finance (yfinance)."""

import logging
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

# Map our interval names to yfinance parameters
_YF_INTERVAL_MAP = {
    "1m": {"interval": "1m", "period": "1d"},       # 分时 (intraday 1-min)
    "5m": {"interval": "5m", "period": "5d"},        # 五日分钟
    "15m": {"interval": "15m", "period": "5d"},      # 分钟
    "daily": {"interval": "1d", "period": None},     # 日K
    "weekly": {"interval": "1wk", "period": None},   # 周K
    "monthly": {"interval": "1mo", "period": None},  # 月K
}


def fetch_us_price(
    ticker: str,
    period_days: int = 120,
    interval: str = "daily",
) -> pd.DataFrame:
    """Fetch US stock historical OHLCV data.

    Args:
        ticker: US stock ticker symbol (e.g. 'AAPL').
        period_days: Number of calendar days of history to fetch.
        interval: One of '1m', '5m', '15m', 'daily', 'weekly', 'monthly'.

    Returns:
        DataFrame with columns: open, high, low, close, volume.
        Indexed by date. Returns empty DataFrame on failure.
    """
    try:
        stock = yf.Ticker(ticker)
        params = _YF_INTERVAL_MAP.get(interval, _YF_INTERVAL_MAP["daily"])
        yf_interval = params["interval"]
        yf_period = params["period"]

        if yf_period:
            # For intraday intervals, use period directly
            df = stock.history(period=yf_period, interval=yf_interval)
        else:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=period_days)
            df = stock.history(
                start=start_date.strftime("%Y-%m-%d"),
                end=end_date.strftime("%Y-%m-%d"),
                interval=yf_interval,
            )

        if df is None or df.empty:
            logger.warning("No price data returned for US stock %s (interval=%s)", ticker, interval)
            return pd.DataFrame()

        # Normalize column names to lowercase
        df = df.rename(columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        })

        # Keep only needed columns
        cols = ["open", "high", "low", "close", "volume"]
        available = [c for c in cols if c in df.columns]
        df = df[available].copy()

        df.index.name = "date"
        # Remove timezone info if present
        if hasattr(df.index, 'tz') and df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        df.index = pd.to_datetime(df.index)

        logger.info("Fetched %d price bars for US stock %s (interval=%s)", len(df), ticker, interval)
        return df

    except Exception as e:
        logger.error("US price fetch failed for %s: %s", ticker, e)
        return pd.DataFrame()
