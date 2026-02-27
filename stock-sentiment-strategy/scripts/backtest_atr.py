"""ATR 策略回测脚本 — 支持波段/日内v1-v4 多种模式。

用法:
  python scripts/backtest_atr.py                       # 日内v4 (默认)
  python scripts/backtest_atr.py --mode intraday_v3    # 日内v3
  python scripts/backtest_atr.py --mode intraday       # 日内v1
  python scripts/backtest_atr.py --mode swing          # 波段模式
  python scripts/backtest_atr.py --symbol C2605        # 指定合约

v4 改进 (基于v3数据诊断):
  - SL 1.8 ATR / TP 2.5 ATR: 止损远离噪声区 (v3仅0.09%被假止损55.8%)
  - 30分钟趋势过滤: 只顺大周期方向开仓, 避免逆势交易
  - 盈亏平衡止损: 浮盈≥1R后止损移至成本价, 消除回吐风险
  - 开盘跳过15分钟: 避开集合竞价后的震荡噪声
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import argparse
import math
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import List, Optional
from datetime import timedelta

# ── 参数 ──────────────────────────────────────────────────────

PROFILES = {
    "swing": {
        "kline_period": "15",
        "atr_period": 14,
        "sl_mult": 1.5,
        "tp_mult": 3.0,
        "trail_step": 0.5,
        "trail_move": 0.25,
        "risk_per_trade": 0.02,
        "max_daily_loss": None,
        "max_consec_loss": None,
        "no_entry_after": None,
        "force_close_time": None,
    },
    "intraday": {
        "kline_period": "5",
        "atr_period": 14,
        "sl_mult": 1.0,
        "tp_mult": 2.0,
        "trail_step": 0.3,
        "trail_move": 0.15,
        "risk_per_trade": 0.01,
        "max_daily_loss": 0.03,
        "max_consec_loss": 3,
        "no_entry_after": (14, 30),
        "force_close_time": (14, 55),
        "signal_threshold": 0.5,
        "adx_min": None,
        "atr_filter": False,
        "active_hours": None,
    },
    "intraday_v2": {
        "kline_period": "5",
        "atr_period": 14,
        "sl_mult": 1.2,
        "tp_mult": 2.0,
        "trail_step": 0.3,
        "trail_move": 0.15,
        "risk_per_trade": 0.01,
        "max_daily_loss": 0.03,
        "max_consec_loss": 3,
        "no_entry_after": (14, 30),
        "force_close_time": (14, 55),
        "signal_threshold": 0.6,
        "adx_min": 20,
        "atr_filter": True,
        "active_hours": [((9, 15), (10, 30)), ((13, 30), (14, 30))],
    },
    "intraday_v3": {
        "kline_period": "5",
        "atr_period": 14,
        "sl_mult": 1.2,
        "tp_mult": 2.0,
        "trail_step": 0.3,
        "trail_move": 0.15,
        "risk_per_trade": 0.01,
        "max_daily_loss": 0.03,
        "max_consec_loss": 3,
        "no_entry_after": (14, 30),
        "force_close_time": (14, 55),
        "signal_threshold": 0.55,
        "adx_min": 15,
        "atr_filter": False,
        "active_hours": None,
    },
    # v4a: v3 + 仅30分趋势过滤
    "intraday_v4a": {
        "kline_period": "5",
        "atr_period": 14,
        "sl_mult": 1.2,
        "tp_mult": 2.0,
        "trail_step": 0.3,
        "trail_move": 0.15,
        "risk_per_trade": 0.01,
        "max_daily_loss": 0.03,
        "max_consec_loss": 3,
        "no_entry_after": (14, 30),
        "force_close_time": (14, 55),
        "signal_threshold": 0.55,
        "adx_min": 15,
        "atr_filter": False,
        "active_hours": None,
        "htf_trend_filter": True,
        "breakeven_at_1r": False,
        "skip_open_minutes": 0,
    },
    # v4b: v3 + 加宽SL/TP保持2:1 + 盈亏平衡
    "intraday_v4b": {
        "kline_period": "5",
        "atr_period": 14,
        "sl_mult": 1.5,
        "tp_mult": 3.0,
        "trail_step": 0.3,
        "trail_move": 0.15,
        "risk_per_trade": 0.01,
        "max_daily_loss": 0.03,
        "max_consec_loss": 3,
        "no_entry_after": (14, 30),
        "force_close_time": (14, 55),
        "signal_threshold": 0.55,
        "adx_min": 15,
        "atr_filter": False,
        "active_hours": None,
        "htf_trend_filter": False,
        "breakeven_at_1r": True,
        "skip_open_minutes": 0,
    },
    # v4c: v3 + 仅跳过开盘15分钟
    "intraday_v4c": {
        "kline_period": "5",
        "atr_period": 14,
        "sl_mult": 1.2,
        "tp_mult": 2.0,
        "trail_step": 0.3,
        "trail_move": 0.15,
        "risk_per_trade": 0.01,
        "max_daily_loss": 0.03,
        "max_consec_loss": 3,
        "no_entry_after": (14, 30),
        "force_close_time": (14, 55),
        "signal_threshold": 0.55,
        "adx_min": 15,
        "atr_filter": False,
        "active_hours": None,
        "htf_trend_filter": False,
        "breakeven_at_1r": False,
        "skip_open_minutes": 15,
    },
    # v6a: v5 + 仅要求HTF趋势对齐(不允许中性)
    "intraday_v6a": {
        "kline_period": "5", "atr_period": 14, "sl_mult": 1.2, "tp_mult": 2.0,
        "trail_step": 0.3, "trail_move": 0.15, "risk_per_trade": 0.01,
        "max_daily_loss": 0.03, "max_consec_loss": 3,
        "no_entry_after": (14, 30), "force_close_time": (14, 55),
        "signal_threshold": 0.55, "adx_min": 15, "atr_filter": False,
        "active_hours": None, "htf_trend_filter": True,
        "require_htf_aligned": True,
        "no_entry_hours": [3, 6, 13],
        "min_atr_percentile": 0.0,
    },
    # v6b: v5 + 仅提高阈值到0.60
    "intraday_v6b": {
        "kline_period": "5", "atr_period": 14, "sl_mult": 1.2, "tp_mult": 2.0,
        "trail_step": 0.3, "trail_move": 0.15, "risk_per_trade": 0.01,
        "max_daily_loss": 0.03, "max_consec_loss": 3,
        "no_entry_after": (14, 30), "force_close_time": (14, 55),
        "signal_threshold": 0.60, "adx_min": 15, "atr_filter": False,
        "active_hours": None, "htf_trend_filter": True,
        "no_entry_hours": [3, 6, 13],
        "min_atr_percentile": 0.0,
    },
    # v6c: v5 + 仅ATR>25%分位过滤
    "intraday_v6c": {
        "kline_period": "5", "atr_period": 14, "sl_mult": 1.2, "tp_mult": 2.0,
        "trail_step": 0.3, "trail_move": 0.15, "risk_per_trade": 0.01,
        "max_daily_loss": 0.03, "max_consec_loss": 3,
        "no_entry_after": (14, 30), "force_close_time": (14, 55),
        "signal_threshold": 0.55, "adx_min": 15, "atr_filter": False,
        "active_hours": None, "htf_trend_filter": True,
        "no_entry_hours": [3, 6, 13],
        "min_atr_percentile": 0.25,
    },
    # v6: v5 + HTF严格对齐 (AB测试最优: 只在30分趋势明确时顺势开仓)
    "intraday_v6": {
        "kline_period": "5", "atr_period": 14, "sl_mult": 1.2, "tp_mult": 2.0,
        "trail_step": 0.3, "trail_move": 0.15, "risk_per_trade": 0.01,
        "max_daily_loss": 0.03, "max_consec_loss": 3,
        "no_entry_after": (14, 30), "force_close_time": (14, 55),
        "signal_threshold": 0.55, "adx_min": 15, "atr_filter": False,
        "active_hours": None, "htf_trend_filter": True,
        "require_htf_aligned": True,
        "no_entry_hours": [3, 6, 13],
        "min_atr_percentile": 0.0,
    },
    # v5a: v4 + 仅时间止损25根
    "intraday_v5a": {
        "kline_period": "5", "atr_period": 14, "sl_mult": 1.2, "tp_mult": 2.0,
        "trail_step": 0.3, "trail_move": 0.15, "risk_per_trade": 0.01,
        "max_daily_loss": 0.03, "max_consec_loss": 3,
        "no_entry_after": (14, 30), "force_close_time": (14, 55),
        "signal_threshold": 0.55, "adx_min": 15, "atr_filter": False,
        "active_hours": None, "htf_trend_filter": True,
        "breakeven_at_1r": False, "skip_open_minutes": 0,
        "time_stop_bars": 25, "tighten_after_bars": 0, "no_entry_hours": [],
    },
    # v5b: v4 + 仅跟踪收紧(15根后)
    "intraday_v5b": {
        "kline_period": "5", "atr_period": 14, "sl_mult": 1.2, "tp_mult": 2.0,
        "trail_step": 0.3, "trail_move": 0.15, "risk_per_trade": 0.01,
        "max_daily_loss": 0.03, "max_consec_loss": 3,
        "no_entry_after": (14, 30), "force_close_time": (14, 55),
        "signal_threshold": 0.55, "adx_min": 15, "atr_filter": False,
        "active_hours": None, "htf_trend_filter": True,
        "breakeven_at_1r": False, "skip_open_minutes": 0,
        "time_stop_bars": 0, "tighten_after_bars": 15, "tighten_atr_mult": 0.8,
        "no_entry_hours": [],
    },
    # v5c: v4 + 仅跳过03时
    "intraday_v5c": {
        "kline_period": "5", "atr_period": 14, "sl_mult": 1.2, "tp_mult": 2.0,
        "trail_step": 0.3, "trail_move": 0.15, "risk_per_trade": 0.01,
        "max_daily_loss": 0.03, "max_consec_loss": 3,
        "no_entry_after": (14, 30), "force_close_time": (14, 55),
        "signal_threshold": 0.55, "adx_min": 15, "atr_filter": False,
        "active_hours": None, "htf_trend_filter": True,
        "breakeven_at_1r": False, "skip_open_minutes": 0,
        "time_stop_bars": 0, "tighten_after_bars": 0, "no_entry_hours": [3],
    },
    # v5: v4 + 跳过低效时段 (03/06/13) — 数据驱动AB测试最优
    "intraday_v5": {
        "kline_period": "5", "atr_period": 14, "sl_mult": 1.2, "tp_mult": 2.0,
        "trail_step": 0.3, "trail_move": 0.15, "risk_per_trade": 0.01,
        "max_daily_loss": 0.03, "max_consec_loss": 3,
        "no_entry_after": (14, 30), "force_close_time": (14, 55),
        "signal_threshold": 0.55, "adx_min": 15, "atr_filter": False,
        "active_hours": None, "htf_trend_filter": True,
        "breakeven_at_1r": False, "skip_open_minutes": 0,
        "time_stop_bars": 0, "tighten_after_bars": 0,
        "no_entry_hours": [3, 6, 13],
    },
    # v4: v3 + 30分钟趋势过滤 (AB测试中唯一有效改进)
    "intraday_v4": {
        "kline_period": "5",
        "atr_period": 14,
        "sl_mult": 1.2,
        "tp_mult": 2.0,
        "trail_step": 0.3,
        "trail_move": 0.15,
        "risk_per_trade": 0.01,
        "max_daily_loss": 0.03,
        "max_consec_loss": 3,
        "no_entry_after": (14, 30),
        "force_close_time": (14, 55),
        "signal_threshold": 0.55,
        "adx_min": 15,
        "atr_filter": False,
        "active_hours": None,
        "htf_trend_filter": True,
        "breakeven_at_1r": False,
        "skip_open_minutes": 0,
    },
}

INITIAL_EQUITY = 100_000.0
VOLUME_MULTIPLE = 10
PAUSE_MINUTES = 30

KNOWN_MULTIPLIERS = {
    "C": 10, "SA": 20, "JD": 10, "M": 10,
    "I": 100, "RB": 10, "AG": 15, "AU": 1000,
    "TA": 5, "FU": 10, "MA": 10, "EG": 10,
    "OI": 10, "SR": 10, "CF": 5, "AP": 10,
    "LH": 16, "LC": 1, "EC": 50, "SI": 5,
    "SC": 1000, "CU": 5, "AL": 5, "ZN": 5,
    "NI": 1, "SN": 1, "SS": 5,
}

def guess_multiplier(symbol: str) -> int:
    import re
    m = re.match(r"([A-Za-z]+)", symbol)
    if m:
        code = m.group(1).upper()
        if code in KNOWN_MULTIPLIERS:
            return KNOWN_MULTIPLIERS[code]
    return 10

# ── 数据结构 ──────────────────────────────────────────────────

@dataclass
class Position:
    direction: str
    entry_price: float
    lots: int
    stop_loss: float
    take_profit: float
    atr_at_entry: float
    highest_favorable: float = 0.0
    entry_time: str = ""
    breakeven_triggered: bool = False
    entry_bar_idx: int = 0
    sl_tightened: bool = False

@dataclass
class TradeRecord:
    entry_time: str
    exit_time: str
    direction: str
    entry_price: float
    exit_price: float
    lots: int
    pnl: float
    exit_reason: str
    signal_strength: float = 0.0
    atr_percentile: float = 0.0
    htf_trend_aligned: bool = False

# ── ATR ───────────────────────────────────────────────────────

def calc_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low = df["high"], df["low"]
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(window=period, min_periods=period).mean()

# ── 入场信号: 波段 ────────────────────────────────────────────

def calc_signals_swing(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ma5"] = df["close"].rolling(5).mean()
    df["ma20"] = df["close"].rolling(20).mean()

    delta = df["close"].diff()
    gain = delta.where(delta > 0, 0.0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    df["rsi"] = 100 - 100 / (1 + rs)

    df["signal"] = 0
    mp, m2p = df["ma5"].shift(1), df["ma20"].shift(1)
    df.loc[(mp <= m2p) & (df["ma5"] > df["ma20"]) & (df["rsi"] < 70), "signal"] = 1
    df.loc[(mp >= m2p) & (df["ma5"] < df["ma20"]) & (df["rsi"] > 30), "signal"] = -1
    return df

# ── ADX(14) ──────────────────────────────────────────────────

def calc_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    atr_s = tr.rolling(period).mean()

    plus_di = 100 * (plus_dm.rolling(period).mean() / atr_s.replace(0, np.nan))
    minus_di = 100 * (minus_dm.rolling(period).mean() / atr_s.replace(0, np.nan))
    dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan))
    return dx.rolling(period).mean()

# ── 30 分钟高时间框架趋势 ─────────────────────────────────────

def calc_htf_trend(df: pd.DataFrame) -> pd.Series:
    """Resample 5-min data to 30-min and compute trend direction.
    Returns a Series aligned to original 5-min index:
      +1 = bullish (30-min close > MA5_30m), -1 = bearish, 0 = neutral.
    """
    ohlcv = df[["open", "high", "low", "close", "volume"]].copy()
    r30 = ohlcv.resample("30min").agg({
        "open": "first", "high": "max", "low": "min",
        "close": "last", "volume": "sum",
    }).dropna()

    ma5 = r30["close"].rolling(5).mean()
    ma10 = r30["close"].rolling(10).mean()

    trend = pd.Series(0, index=r30.index)
    trend[(r30["close"] > ma5) & (ma5 > ma10)] = 1
    trend[(r30["close"] < ma5) & (ma5 < ma10)] = -1

    trend = trend.reindex(df.index, method="ffill").fillna(0).astype(int)
    return trend


# ── 入场信号: 日内 7 因子 ─────────────────────────────────────

def calc_signals_intraday(df: pd.DataFrame, threshold: float = 0.5) -> pd.DataFrame:
    """7-factor intraday signal with configurable threshold.
    Also computes ADX and ATR_MA20 columns for optional filtering.
    """
    df = df.copy()
    close = df["close"]
    high = df["high"]
    low = df["low"]

    df["ma5"] = close.rolling(5).mean()
    df["ma10"] = close.rolling(10).mean()
    df["ma20"] = close.rolling(20).mean()
    df["vol_ma20"] = df["volume"].rolling(20).mean()

    # RSI(6)
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).rolling(6).mean()
    loss_s = (-delta.where(delta < 0, 0.0)).rolling(6).mean()
    rs = gain / loss_s.replace(0, np.nan)
    df["rsi6"] = 100 - 100 / (1 + rs)

    # MACD
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    df["dif"] = ema12 - ema26
    df["dea"] = df["dif"].ewm(span=9, adjust=False).mean()

    # KDJ(9,3,3)
    low9 = low.rolling(9).min()
    high9 = high.rolling(9).max()
    rsv = (close - low9) / (high9 - low9).replace(0, np.nan) * 100
    df["k_val"] = rsv.ewm(com=2, adjust=False).mean()
    df["d_val"] = df["k_val"].ewm(com=2, adjust=False).mean()
    df["j_val"] = 3 * df["k_val"] - 2 * df["d_val"]

    # ADX(14) — for v2 filtering
    df["adx"] = calc_adx(df, 14)

    # 30-min higher-timeframe trend — for v4 filtering
    df["htf_trend"] = calc_htf_trend(df)

    # OI (if available)
    has_oi = "open_interest" in df.columns or "hold" in df.columns
    oi_col = "open_interest" if "open_interest" in df.columns else ("hold" if "hold" in df.columns else None)

    df["prev_rsi"] = df["rsi6"].shift(1)
    df["prev_dif"] = df["dif"].shift(1)
    df["prev_dea"] = df["dea"].shift(1)
    df["prev_k"] = df["k_val"].shift(1)
    df["prev_d"] = df["d_val"].shift(1)
    df["prev_high"] = df["high"].shift(1)
    df["prev_low"] = df["low"].shift(1)

    df["signal"] = 0
    df["strength"] = 0.0

    for i in range(1, len(df)):
        r = df.iloc[i]
        check_cols = ["ma5", "ma10", "ma20", "rsi6", "dif", "dea", "k_val", "d_val"]
        if any(pd.isna(r[c]) for c in check_cols):
            continue

        bull_ma = r["ma5"] > r["ma10"] > r["ma20"]
        bear_ma = r["ma5"] < r["ma10"] < r["ma20"]
        rsi_bull = (r["prev_rsi"] < 35 and r["rsi6"] > 35) or r["rsi6"] < 30
        rsi_bear = (r["prev_rsi"] > 65 and r["rsi6"] < 65) or r["rsi6"] > 70
        macd_golden = r["prev_dif"] <= r["prev_dea"] and r["dif"] > r["dea"]
        macd_death = r["prev_dif"] >= r["prev_dea"] and r["dif"] < r["dea"]
        kdj_bull = (r["prev_k"] <= r["prev_d"] and r["k_val"] > r["d_val"]) or r["j_val"] < 0
        kdj_bear = (r["prev_k"] >= r["prev_d"] and r["k_val"] < r["d_val"]) or r["j_val"] > 100
        vol_confirm = (r["volume"] > r["vol_ma20"] * 1.2) if r["vol_ma20"] > 0 else False

        oi_increasing = False
        if has_oi and oi_col and i >= 5:
            oi_now = df.iloc[i][oi_col]
            oi_prev = df.iloc[i - 5][oi_col]
            if not (pd.isna(oi_now) or pd.isna(oi_prev)) and oi_prev > 0:
                oi_increasing = oi_now > oi_prev * 1.005

        breakout = r["close"] > r["prev_high"]
        breakdown = r["close"] < r["prev_low"]

        # BUY score
        buy_score = 0.0
        if bull_ma:       buy_score += 0.25
        if macd_golden:   buy_score += 0.25
        if rsi_bull:      buy_score += 0.15
        if kdj_bull:      buy_score += 0.10
        if vol_confirm:   buy_score += 0.10
        if oi_increasing: buy_score += 0.10
        if breakout:      buy_score += 0.05

        if buy_score >= threshold:
            if 40 <= r["rsi6"] <= 60 and not macd_golden and not kdj_bull:
                continue
            df.iloc[i, df.columns.get_loc("signal")] = 1
            df.iloc[i, df.columns.get_loc("strength")] = min(buy_score, 1.0)
            continue

        # SELL score
        sell_score = 0.0
        if bear_ma:       sell_score += 0.25
        if macd_death:    sell_score += 0.25
        if rsi_bear:      sell_score += 0.15
        if kdj_bear:      sell_score += 0.10
        if vol_confirm:   sell_score += 0.10
        if oi_increasing: sell_score += 0.10
        if breakdown:     sell_score += 0.05

        if sell_score >= threshold:
            if 40 <= r["rsi6"] <= 60 and not macd_death and not kdj_bear:
                continue
            df.iloc[i, df.columns.get_loc("signal")] = -1
            df.iloc[i, df.columns.get_loc("strength")] = min(sell_score, 1.0)

    return df

# ── 回测主逻辑 ────────────────────────────────────────────────

def run_backtest(df: pd.DataFrame, params: dict) -> dict:
    atr_period = params["atr_period"]
    sl_mult = params["sl_mult"]
    tp_mult = params["tp_mult"]
    trail_step = params["trail_step"]
    trail_move = params["trail_move"]
    risk_pct = params["risk_per_trade"]
    max_daily_loss = params.get("max_daily_loss")
    max_consec = params.get("max_consec_loss")
    no_entry_after = params.get("no_entry_after")
    force_close_time = params.get("force_close_time")
    adx_min = params.get("adx_min")
    atr_filter = params.get("atr_filter", False)
    active_hours = params.get("active_hours")
    sig_threshold = params.get("signal_threshold", 0.5)
    htf_trend_filter = params.get("htf_trend_filter", False)
    breakeven_at_1r = params.get("breakeven_at_1r", False)
    skip_open_minutes = params.get("skip_open_minutes", 0)
    time_stop_bars = params.get("time_stop_bars", 0)
    tighten_after_bars = params.get("tighten_after_bars", 0)
    tighten_atr_mult = params.get("tighten_atr_mult", 0.8)
    no_entry_hours = params.get("no_entry_hours", [])
    require_htf_aligned = params.get("require_htf_aligned", False)
    min_atr_percentile = params.get("min_atr_percentile", 0.0)

    df["atr"] = calc_atr(df, atr_period)

    if params.get("kline_period") == "5":
        df = calc_signals_intraday(df, threshold=sig_threshold)
        need_cols = ["atr", "ma5", "ma10", "ma20", "rsi6", "k_val", "d_val"]
    else:
        df = calc_signals_swing(df)
        need_cols = ["atr", "ma5", "ma20", "rsi"]

    if atr_filter:
        df["atr_ma20"] = df["atr"].rolling(20).mean()

    df["atr_pct"] = df["atr"].rolling(100, min_periods=20).rank(pct=True)

    df = df.dropna(subset=need_cols).copy()

    equity = INITIAL_EQUITY
    position: Optional[Position] = None
    trades: List[TradeRecord] = []
    equity_curve = []
    _entry_meta: dict = {}

    daily_pnl = 0.0
    consec_losses = 0
    pause_until = pd.Timestamp.min
    last_date = None

    for i in range(len(df)):
        row = df.iloc[i]
        ts = df.index[i]
        ts_str = str(ts)
        price = row["close"]
        high = row["high"]
        low = row["low"]
        atr = row["atr"]
        sig = int(row["signal"])
        cur_date = ts.date() if hasattr(ts, 'date') else pd.Timestamp(ts).date()
        cur_hm = (ts.hour, ts.minute) if hasattr(ts, 'hour') else (0, 0)

        # Daily reset
        if last_date is not None and cur_date != last_date:
            daily_pnl = 0.0
            consec_losses = 0
            pause_until = pd.Timestamp.min
        last_date = cur_date

        # Force close at end of day (intraday mode)
        if force_close_time and position is not None:
            fh, fm = force_close_time
            if cur_hm >= (fh, fm):
                if position.direction == "LONG":
                    pnl = (price - position.entry_price) * position.lots * VOLUME_MULTIPLE
                else:
                    pnl = (position.entry_price - price) * position.lots * VOLUME_MULTIPLE
                equity += pnl
                daily_pnl += pnl
                if pnl < 0:
                    consec_losses += 1
                else:
                    consec_losses = 0
                trades.append(TradeRecord(
                    entry_time=position.entry_time, exit_time=ts_str,
                    direction=position.direction,
                    entry_price=position.entry_price, exit_price=round(price, 1),
                    lots=position.lots, pnl=round(pnl, 2), exit_reason="收盘平仓",
                    signal_strength=_entry_meta.get("strength", 0),
                    atr_percentile=_entry_meta.get("atr_pct", 0.5),
                    htf_trend_aligned=_entry_meta.get("htf_aligned", False)))
                position = None
                equity_curve.append({"time": ts_str, "equity": round(equity, 2)})
                continue

        # Time stop: close after N bars
        if position is not None and time_stop_bars > 0:
            bars_held = i - position.entry_bar_idx
            if bars_held >= time_stop_bars:
                if position.direction == "LONG":
                    pnl = (price - position.entry_price) * position.lots * VOLUME_MULTIPLE
                else:
                    pnl = (position.entry_price - price) * position.lots * VOLUME_MULTIPLE
                equity += pnl
                daily_pnl += pnl
                if pnl < 0:
                    consec_losses += 1
                    if max_consec and consec_losses >= max_consec:
                        pause_until = ts + timedelta(minutes=PAUSE_MINUTES)
                else:
                    consec_losses = 0
                trades.append(TradeRecord(
                    entry_time=position.entry_time, exit_time=ts_str,
                    direction=position.direction,
                    entry_price=position.entry_price, exit_price=round(price, 1),
                    lots=position.lots, pnl=round(pnl, 2), exit_reason="时间止损",
                    signal_strength=_entry_meta.get("strength", 0),
                    atr_percentile=_entry_meta.get("atr_pct", 0.5),
                    htf_trend_aligned=_entry_meta.get("htf_aligned", False)))
                position = None
                equity_curve.append({"time": ts_str, "equity": round(equity, 2)})
                continue

        # Tighten trailing after N bars
        if position is not None and tighten_after_bars > 0 and not position.sl_tightened:
            bars_held = i - position.entry_bar_idx
            if bars_held >= tighten_after_bars:
                tight_dist = position.atr_at_entry * tighten_atr_mult
                if position.direction == "LONG":
                    tight_sl = high - tight_dist
                    position.stop_loss = max(position.stop_loss, tight_sl)
                else:
                    tight_sl = low + tight_dist
                    position.stop_loss = min(position.stop_loss, tight_sl)
                position.sl_tightened = True

        # SL / TP / Trailing + Breakeven
        if position is not None:
            exit_price = None
            exit_reason = ""

            if position.direction == "LONG":
                # Breakeven: move SL to entry once profit >= 1R
                if breakeven_at_1r and not position.breakeven_triggered:
                    one_r = position.atr_at_entry * sl_mult
                    if high >= position.entry_price + one_r:
                        position.stop_loss = max(position.stop_loss, position.entry_price)
                        position.breakeven_triggered = True

                if low <= position.stop_loss:
                    exit_price, exit_reason = position.stop_loss, "止损"
                elif high >= position.take_profit:
                    exit_price, exit_reason = position.take_profit, "止盈"
                else:
                    if high > position.highest_favorable:
                        old_fav = position.highest_favorable
                        position.highest_favorable = high
                        step_th = trail_step * position.atr_at_entry
                        if step_th > 0:
                            steps = int((high - old_fav) / step_th)
                            if steps > 0:
                                new_sl = position.stop_loss + steps * trail_move * position.atr_at_entry
                                position.stop_loss = max(position.stop_loss, new_sl)
            else:
                # Breakeven: move SL to entry once profit >= 1R
                if breakeven_at_1r and not position.breakeven_triggered:
                    one_r = position.atr_at_entry * sl_mult
                    if low <= position.entry_price - one_r:
                        position.stop_loss = min(position.stop_loss, position.entry_price)
                        position.breakeven_triggered = True

                if high >= position.stop_loss:
                    exit_price, exit_reason = position.stop_loss, "止损"
                elif low <= position.take_profit:
                    exit_price, exit_reason = position.take_profit, "止盈"
                else:
                    if low < position.highest_favorable:
                        old_fav = position.highest_favorable
                        position.highest_favorable = low
                        step_th = trail_step * position.atr_at_entry
                        if step_th > 0:
                            steps = int((old_fav - low) / step_th)
                            if steps > 0:
                                new_sl = position.stop_loss - steps * trail_move * position.atr_at_entry
                                position.stop_loss = min(position.stop_loss, new_sl)

            if exit_price is not None:
                if position.direction == "LONG":
                    pnl = (exit_price - position.entry_price) * position.lots * VOLUME_MULTIPLE
                else:
                    pnl = (position.entry_price - exit_price) * position.lots * VOLUME_MULTIPLE
                equity += pnl
                daily_pnl += pnl

                is_loss = pnl < 0
                if is_loss:
                    consec_losses += 1
                    if max_consec and consec_losses >= max_consec:
                        pause_until = ts + timedelta(minutes=PAUSE_MINUTES)
                else:
                    consec_losses = 0

                trades.append(TradeRecord(
                    entry_time=position.entry_time, exit_time=ts_str,
                    direction=position.direction,
                    entry_price=position.entry_price, exit_price=round(exit_price, 1),
                    lots=position.lots, pnl=round(pnl, 2), exit_reason=exit_reason,
                    signal_strength=_entry_meta.get("strength", 0),
                    atr_percentile=_entry_meta.get("atr_pct", 0.5),
                    htf_trend_aligned=_entry_meta.get("htf_aligned", False)))
                position = None

        # Entry
        if position is None and atr > 0 and sig != 0:
            can_enter = True

            # Time filter (no_entry_after)
            if no_entry_after and cur_hm >= no_entry_after:
                can_enter = False

            # Active hours filter (v2): only trade within specified windows
            if can_enter and active_hours:
                in_window = False
                for (sh, sm), (eh, em) in active_hours:
                    if (sh, sm) <= cur_hm <= (eh, em):
                        in_window = True
                        break
                if not in_window:
                    can_enter = False

            # No-entry hours filter (v5): skip statistically losing hours
            if can_enter and no_entry_hours and cur_hm[0] in no_entry_hours:
                can_enter = False

            # Skip opening minutes (v4): avoid noisy open auction bars
            if can_enter and skip_open_minutes > 0:
                session_starts = [(9, 0), (13, 30), (21, 0)]
                for sh, sm in session_starts:
                    start_min = sh * 60 + sm
                    cur_min = cur_hm[0] * 60 + cur_hm[1]
                    if start_min <= cur_min < start_min + skip_open_minutes:
                        can_enter = False
                        break

            # Higher-timeframe trend filter (v4/v6)
            if can_enter and htf_trend_filter and "htf_trend" in df.columns:
                htf = int(row["htf_trend"]) if not pd.isna(row.get("htf_trend", np.nan)) else 0
                if require_htf_aligned:
                    # v6: require HTF trend to MATCH signal direction (skip neutral too)
                    if sig == 1 and htf != 1:
                        can_enter = False
                    elif sig == -1 and htf != -1:
                        can_enter = False
                else:
                    # v4: only block counter-trend (allow neutral)
                    if sig == 1 and htf == -1:
                        can_enter = False
                    elif sig == -1 and htf == 1:
                        can_enter = False

            # ATR percentile filter (v6): skip low-volatility environments
            if can_enter and min_atr_percentile > 0 and "atr_pct" in df.columns:
                cur_atr_pct = row["atr_pct"] if not pd.isna(row.get("atr_pct", np.nan)) else 0.5
                if cur_atr_pct < min_atr_percentile:
                    can_enter = False

            # ADX trend filter (v2): skip when market has no trend
            if can_enter and adx_min is not None:
                cur_adx = row.get("adx", np.nan) if hasattr(row, "get") else row["adx"] if "adx" in df.columns else np.nan
                if pd.isna(cur_adx) or cur_adx < adx_min:
                    can_enter = False

            # ATR volatility filter (v2): skip low-vol environments
            if can_enter and atr_filter and "atr_ma20" in df.columns:
                cur_atr_ma = row["atr_ma20"] if "atr_ma20" in row.index else np.nan
                if not pd.isna(cur_atr_ma) and atr < cur_atr_ma:
                    can_enter = False

            # Daily loss limit
            if can_enter and max_daily_loss and equity > 0:
                if daily_pnl < 0 and abs(daily_pnl) / equity >= max_daily_loss:
                    can_enter = False

            # Consecutive loss pause
            if can_enter and ts < pause_until:
                can_enter = False

            if can_enter:
                sl_distance = atr * sl_mult
                loss_per_lot = sl_distance * VOLUME_MULTIPLE
                max_loss = equity * risk_pct
                lots = max(1, int(max_loss / loss_per_lot))

                sig_str = row.get("strength", 0.0) if hasattr(row, "get") else row["strength"] if "strength" in df.columns else 0.0
                atr_pctile = row.get("atr_pct", 0.5) if hasattr(row, "get") else row["atr_pct"] if "atr_pct" in df.columns else 0.5
                htf_val = int(row.get("htf_trend", 0)) if "htf_trend" in df.columns else 0
                htf_aligned = (sig == 1 and htf_val == 1) or (sig == -1 and htf_val == -1)
                _entry_meta = {"strength": float(sig_str), "atr_pct": float(atr_pctile), "htf_aligned": htf_aligned}

                if sig == 1:
                    sl = price - sl_distance
                    tp = price + atr * tp_mult
                    position = Position("LONG", price, lots, sl, tp, atr, price, ts_str, entry_bar_idx=i)
                elif sig == -1:
                    sl = price + sl_distance
                    tp = price - atr * tp_mult
                    position = Position("SHORT", price, lots, sl, tp, atr, price, ts_str, entry_bar_idx=i)

        equity_curve.append({"time": ts_str, "equity": round(equity, 2)})

    # Force close remaining
    if position is not None:
        last_price = df.iloc[-1]["close"]
        if position.direction == "LONG":
            pnl = (last_price - position.entry_price) * position.lots * VOLUME_MULTIPLE
        else:
            pnl = (position.entry_price - last_price) * position.lots * VOLUME_MULTIPLE
        equity += pnl
        trades.append(TradeRecord(
            entry_time=position.entry_time, exit_time=str(df.index[-1]),
            direction=position.direction,
            entry_price=position.entry_price, exit_price=round(last_price, 1),
            lots=position.lots, pnl=round(pnl, 2), exit_reason="回测结束强平",
            signal_strength=_entry_meta.get("strength", 0),
            atr_percentile=_entry_meta.get("atr_pct", 0.5),
            htf_trend_aligned=_entry_meta.get("htf_aligned", False)))

    return compute_report(trades, equity_curve, equity)


def compute_report(trades: List[TradeRecord], equity_curve: list, final_equity: float) -> dict:
    total_return = (final_equity - INITIAL_EQUITY) / INITIAL_EQUITY * 100
    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    win_rate = len(wins) / len(trades) * 100 if trades else 0
    total_profit = sum(t.pnl for t in wins)
    total_loss = sum(abs(t.pnl) for t in losses) or 1
    avg_win = total_profit / len(wins) if wins else 0
    avg_loss = total_loss / len(losses) if losses else 1
    profit_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 0

    equities = [e["equity"] for e in equity_curve]
    max_dd = 0
    peak = equities[0] if equities else INITIAL_EQUITY
    for v in equities:
        if v > peak:
            peak = v
        dd = (peak - v) / peak * 100 if peak > 0 else 0
        max_dd = max(max_dd, dd)

    # Daily P&L breakdown
    daily_map: dict[str, float] = {}
    for t in trades:
        day = t.exit_time[:10]
        daily_map[day] = daily_map.get(day, 0) + t.pnl
    daily_wins = sum(1 for v in daily_map.values() if v > 0)
    daily_total = len(daily_map)
    daily_win_rate = daily_wins / daily_total * 100 if daily_total else 0

    return {
        "initial_equity": INITIAL_EQUITY,
        "final_equity": round(final_equity, 2),
        "total_return_pct": round(total_return, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "total_trades": len(trades),
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate_pct": round(win_rate, 1),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "profit_loss_ratio": round(profit_loss_ratio, 2),
        "total_profit": round(total_profit, 2),
        "total_loss": round(total_loss, 2),
        "daily_win_rate_pct": round(daily_win_rate, 1),
        "trading_days_total": daily_total,
        "trading_days_win": daily_wins,
        "trades": trades,
        "equity_curve": equity_curve,
    }


# ── 数据获取 ──────────────────────────────────────────────────

def load_csv_klines(csv_path: str) -> Optional[pd.DataFrame]:
    """Load K-line data from a CSV file (exported from TqSdk API)."""
    try:
        df = pd.read_csv(csv_path)
        if df.empty:
            return None
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.set_index("datetime")
        for col in ("open", "high", "low", "close", "volume"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        if "open_interest" in df.columns:
            df["open_interest"] = pd.to_numeric(df["open_interest"], errors="coerce")
        return df.dropna(subset=["close"])
    except Exception as e:
        print(f"加载CSV失败: {e}")
        return None


def fetch_klines(symbol: str, period: str = "5") -> Optional[pd.DataFrame]:
    """Fetch minute klines via akshare (Sina Finance)."""
    import akshare as ak
    try:
        df = ak.futures_zh_minute_sina(symbol=symbol, period=period)
        if df is None or df.empty:
            return None
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.set_index("datetime")
        for col in ("open", "high", "low", "close", "volume"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        return df.dropna(subset=["close"])
    except Exception as e:
        print(f"获取K线失败: {e}")
        return None


# ── 主入口 ────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="ATR 策略回测")
    parser.add_argument("--mode", choices=list(PROFILES.keys()), default="intraday_v4")
    parser.add_argument("--symbol", default="C2605")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--mult", type=int, default=0, help="合约乘数 (0=自动)")
    parser.add_argument("--csv", default="", help="CSV 文件路径 (跳过在线获取)")
    args = parser.parse_args()

    params = PROFILES[args.mode]
    mode_names = {k: k for k in PROFILES}
    mode_names.update({
        "swing": "波段趋势", "intraday": "日内v1", "intraday_v2": "日内v2(增强)",
        "intraday_v3": "日内v3(均衡)", "intraday_v4": "日内v4(+趋势过滤)",
        "intraday_v5": "日内v5(数据驱动)",
        "intraday_v5a": "v5a(+时间止损)", "intraday_v5b": "v5b(+跟踪收紧)",
        "intraday_v5c": "v5c(+跳过03时)",
    })
    mode_cn = mode_names[args.mode]

    global VOLUME_MULTIPLE
    VOLUME_MULTIPLE = args.mult if args.mult > 0 else guess_multiplier(args.symbol)

    print("=" * 60)
    print(f"  {args.symbol} {mode_cn}策略回测 ({params['kline_period']}分钟K线)")
    print("=" * 60)
    print(f"\n策略参数:")
    print(f"  ATR 周期     = {params['atr_period']}")
    print(f"  止损倍数     = {params['sl_mult']} × ATR")
    print(f"  止盈倍数     = {params['tp_mult']} × ATR (风险回报比 1:{params['tp_mult']/params['sl_mult']:.1f})")
    print(f"  跟踪步进     = {params['trail_step']} ATR / 移动 {params['trail_move']} ATR")
    print(f"  单笔风险     = {params['risk_per_trade']*100:.0f}% 权益")
    print(f"  合约乘数     = {VOLUME_MULTIPLE}")
    print(f"  初始资金     = ¥{INITIAL_EQUITY:,.0f}")

    if args.mode.startswith("intraday"):
        print(f"  日亏损上限   = {params['max_daily_loss']*100:.0f}% 权益")
        print(f"  连续止损暂停 = {params['max_consec_loss']}次 → 暂停{PAUSE_MINUTES}分钟")
        print(f"  入场截止     = {params['no_entry_after'][0]}:{params['no_entry_after'][1]:02d}")
        print(f"  收盘强平     = {params['force_close_time'][0]}:{params['force_close_time'][1]:02d}")
        th = params.get("signal_threshold", 0.5)
        print(f"  信号阈值     = {th}")
        print(f"  入场信号     = 7因子: MA(0.25)+MACD(0.25)+RSI6(0.15)+KDJ(0.10)+量(0.10)+仓(0.10)+突破(0.05)")
        if params.get("adx_min"):
            print(f"  ADX趋势过滤  = ADX ≥ {params['adx_min']}")
        if params.get("atr_filter"):
            print(f"  ATR波动过滤  = ATR ≥ ATR_MA(20)")
        if params.get("active_hours"):
            windows = " + ".join(f"{sh}:{sm:02d}-{eh}:{em:02d}" for (sh,sm),(eh,em) in params["active_hours"])
            print(f"  活跃时段     = {windows}")
        if params.get("htf_trend_filter"):
            if params.get("require_htf_aligned"):
                print(f"  30分趋势过滤 = 严格 (必须顺势, 中性也跳过)")
            else:
                print(f"  30分趋势过滤 = 开启 (只顺30分钟趋势方向开仓)")
        if params.get("min_atr_percentile", 0) > 0:
            print(f"  ATR分位过滤  = ATR ≥ {params['min_atr_percentile']*100:.0f}% 百分位")
        if params.get("breakeven_at_1r"):
            print(f"  盈亏平衡     = 浮盈≥1R后止损移至成本价")
        if params.get("skip_open_minutes"):
            print(f"  开盘跳过     = 每节开盘前{params['skip_open_minutes']}分钟不入场")
        if params.get("time_stop_bars"):
            print(f"  时间止损     = {params['time_stop_bars']}根K线 ({params['time_stop_bars']*5}分钟) 后强平")
        if params.get("tighten_after_bars"):
            print(f"  跟踪收紧     = {params['tighten_after_bars']}根后SL收紧至{params.get('tighten_atr_mult',0.8)}ATR")
        if params.get("no_entry_hours"):
            print(f"  禁止入场时段 = {params['no_entry_hours']}时")
    else:
        print(f"  入场信号     = MA5/MA20 交叉 + RSI(14) 过滤")

    if args.csv:
        print(f"\n从CSV文件加载: {args.csv}")
        df = load_csv_klines(args.csv)
    else:
        print(f"\n正在获取 {args.symbol} {params['kline_period']}分钟K线数据...")
        df = fetch_klines(args.symbol, params["kline_period"])

    if df is None or df.empty:
        print("无法获取K线数据")
        sys.exit(1)

    print(f"获取到 {len(df)} 根K线")
    print(f"全部范围: {df.index[0]} ~ {df.index[-1]}")

    cutoff = df.index[-1] - timedelta(days=args.days)
    df = df[df.index >= cutoff]
    print(f"截取最近{args.days}天: {df.index[0]} ~ {df.index[-1]}")
    print(f"K线数量: {len(df)} 根")
    trading_days = df.index.normalize().nunique()
    print(f"交易天数: {trading_days} 天")

    print(f"\n正在运行回测...")
    report = run_backtest(df, params)

    # ── Output ──
    reset = "\033[0m"
    pnl = report['final_equity'] - report['initial_equity']
    c = "\033[32m" if pnl >= 0 else "\033[31m"

    print("\n" + "=" * 60)
    print(f"  回测结果 ({mode_cn})")
    print("=" * 60)
    print(f"\n  初始资金:       ¥{report['initial_equity']:>12,.2f}")
    print(f"  最终权益:       ¥{report['final_equity']:>12,.2f}")
    print(f"  净利润:         {c}¥{pnl:>12,.2f}{reset}")
    print(f"  总收益率:       {c}{report['total_return_pct']:>11.2f}%{reset}")
    print(f"  最大回撤:       {report['max_drawdown_pct']:>11.2f}%")

    print(f"\n  总交易次数:     {report['total_trades']:>8d}")
    print(f"  盈利次数:       {report['win_count']:>8d}")
    print(f"  亏损次数:       {report['loss_count']:>8d}")
    print(f"  胜率(笔):       {report['win_rate_pct']:>11.1f}%")
    print(f"  日胜率:         {report['daily_win_rate_pct']:>11.1f}% ({report['trading_days_win']}/{report['trading_days_total']}天)")
    print(f"  平均盈利:       ¥{report['avg_win']:>12,.2f}")
    print(f"  平均亏损:       ¥{report['avg_loss']:>12,.2f}")
    print(f"  盈亏比:         {report['profit_loss_ratio']:>11.2f}")

    print(f"\n  {'='*58}")
    print(f"  交易明细:")
    print(f"  {'─'*58}")
    print(f"  {'方向':>4} {'入场时间':>18} {'开仓':>8} {'平仓':>8} {'手':>3} {'盈亏':>10} {'原因'}")
    print(f"  {'─'*58}")
    for t in report["trades"]:
        pnl_str = f"¥{t.pnl:>+,.2f}"
        tc = "\033[32m" if t.pnl > 0 else "\033[31m"
        d_cn = "做多" if t.direction == "LONG" else "做空"
        entry_short = t.entry_time[5:16] if len(t.entry_time) > 16 else t.entry_time
        print(f"  {d_cn:>4} {entry_short:>18} {t.entry_price:>8.1f} {t.exit_price:>8.1f} "
              f"{t.lots:>3d} {tc}{pnl_str:>10}{reset} {t.exit_reason}")

    print(f"\n  期望值 = 胜率×平均盈利 - 败率×平均亏损")
    wr = report['win_rate_pct'] / 100
    ev = wr * report['avg_win'] - (1 - wr) * report['avg_loss']
    ev_c = "\033[32m" if ev >= 0 else "\033[31m"
    print(f"         = {wr:.1%} × ¥{report['avg_win']:,.0f} - {1-wr:.1%} × ¥{report['avg_loss']:,.0f}")
    print(f"         = {ev_c}¥{ev:>+,.2f} / 笔{reset}")

    calmar = abs(report['total_return_pct'] / report['max_drawdown_pct']) if report['max_drawdown_pct'] > 0 else 0
    print(f"\n  收益/回撤比:    {calmar:>11.2f}")


if __name__ == "__main__":
    main()
