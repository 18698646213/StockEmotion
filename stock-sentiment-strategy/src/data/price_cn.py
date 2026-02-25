"""China A-share price data via Eastmoney HTTP API (with akshare fallback)."""

import json
import logging
from datetime import datetime, timedelta

import pandas as pd
import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Eastmoney kline interval mapping
# ---------------------------------------------------------------------------
# klt: 1=1min, 5=5min, 15=15min, 30=30min, 60=60min, 101=daily, 102=weekly, 103=monthly
_KLT_MAP = {
    "1m": "1",
    "5m": "5",
    "15m": "15",
    "daily": "101",
    "weekly": "102",
    "monthly": "103",
}

# Market prefix: 1=SH, 0=SZ
_MARKET_PREFIX = {
    "6": "1",   # 60xxxx → 上海
    "9": "1",   # 9xxxxx → 上海B
    "0": "0",   # 00xxxx → 深圳
    "3": "0",   # 30xxxx → 创业板
    "2": "0",   # 2xxxxx → 深圳B
}

# akshare period mapping (fallback)
_AK_PERIOD_MAP = {
    "1m": "1",
    "5m": "5",
    "15m": "15",
    "daily": "daily",
    "weekly": "weekly",
    "monthly": "monthly",
}


def _normalize_stock_code(code: str) -> str:
    """Ensure stock code is 6 digits."""
    return code.strip().zfill(6)


def _get_secid(code: str) -> str:
    """Build Eastmoney secid like '1.600519' or '0.000001'."""
    prefix = _MARKET_PREFIX.get(code[0], "1")
    return f"{prefix}.{code}"


# ---------------------------------------------------------------------------
# Primary: direct Eastmoney HTTP API
# ---------------------------------------------------------------------------

def _fetch_eastmoney_kline(
    code: str,
    interval: str = "daily",
    period_days: int = 120,
) -> pd.DataFrame:
    """Fetch kline data directly from Eastmoney HTTP API.

    Uses HTTP (not HTTPS) to avoid connectivity issues in some networks.
    """
    code = _normalize_stock_code(code)
    secid = _get_secid(code)
    klt = _KLT_MAP.get(interval, "101")

    end_date = datetime.now()
    start_date = end_date - timedelta(days=period_days)

    url = "http://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "ut": "7eea3edcaed734bea9cbfc24409ed989",
        "klt": klt,
        "fqt": "1",  # 前复权
        "secid": secid,
        "beg": start_date.strftime("%Y%m%d"),
        "end": end_date.strftime("%Y%m%d"),
    }

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36",
    }

    resp = requests.get(url, params=params, headers=headers, timeout=10)
    resp.raise_for_status()

    data = resp.json()
    klines = data.get("data", {}).get("klines", [])
    if not klines:
        return pd.DataFrame()

    # Each kline: "date,open,close,high,low,volume,amount,amplitude,pct_change,change,turnover"
    rows = []
    for line in klines:
        parts = line.split(",")
        if len(parts) < 6:
            continue
        rows.append({
            "date": parts[0],
            "open": float(parts[1]),
            "close": float(parts[2]),
            "high": float(parts[3]),
            "low": float(parts[4]),
            "volume": float(parts[5]),
        })

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")

    return df


# ---------------------------------------------------------------------------
# Fallback: akshare
# ---------------------------------------------------------------------------

def _fetch_akshare_kline(
    code: str,
    interval: str = "daily",
    period_days: int = 120,
) -> pd.DataFrame:
    """Fallback: fetch via akshare if direct API fails."""
    import akshare as ak

    end_date = datetime.now()
    start_date = end_date - timedelta(days=period_days)
    ak_period = _AK_PERIOD_MAP.get(interval, "daily")

    if interval in ("1m", "5m", "15m"):
        df = ak.stock_zh_a_hist_min_em(
            symbol=code,
            period=ak_period,
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
        return pd.DataFrame()

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

    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date")

    cols = ["open", "high", "low", "close", "volume"]
    available = [c for c in cols if c in df.columns]
    df = df[available].copy()

    for col in available:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    return df.dropna()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_cn_price(
    code: str,
    period_days: int = 120,
    interval: str = "daily",
) -> pd.DataFrame:
    """Fetch A-share stock historical OHLCV data.

    Tries direct Eastmoney HTTP API first, falls back to akshare.

    Args:
        code: A-share stock code (e.g. '600519').
        period_days: Number of calendar days of history to fetch.
        interval: One of '1m', '5m', '15m', 'daily', 'weekly', 'monthly'.

    Returns:
        DataFrame with columns: open, high, low, close, volume.
        Indexed by date. Returns empty DataFrame on failure.
    """
    code = _normalize_stock_code(code)

    # --- Primary: direct HTTP API ---
    try:
        df = _fetch_eastmoney_kline(code, interval, period_days)
        if df is not None and not df.empty:
            logger.info(
                "Fetched %d price bars for A-share %s (interval=%s) via Eastmoney HTTP",
                len(df), code, interval,
            )
            return df
        logger.warning("Eastmoney HTTP returned empty for %s, trying akshare...", code)
    except Exception as e:
        logger.warning("Eastmoney HTTP failed for %s: %s, trying akshare...", code, e)

    # --- Fallback: akshare ---
    try:
        df = _fetch_akshare_kline(code, interval, period_days)
        if df is not None and not df.empty:
            logger.info(
                "Fetched %d price bars for A-share %s (interval=%s) via akshare",
                len(df), code, interval,
            )
            return df
    except Exception as e:
        logger.error("akshare also failed for %s: %s", code, e)

    logger.error("A-share price fetch failed for %s (all sources exhausted)", code)
    return pd.DataFrame()
