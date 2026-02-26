"""Technical indicator computation.

Calculates RSI, MACD, Moving Averages, and Bollinger Bands,
then produces a composite technical score in [-1, 1].

Also includes a dedicated futures swing strategy based on MA5/MA20/MA60.
"""

import logging
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lightweight technical indicator helpers (replaces pandas-ta dependency)
# ---------------------------------------------------------------------------

def _rsi(series: pd.Series, length: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / length, min_periods=length).mean()
    avg_loss = loss.ewm(alpha=1 / length, min_periods=length).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _sma(series: pd.Series, length: int) -> pd.Series:
    return series.rolling(window=length).mean()


def _macd(
    series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> pd.DataFrame:
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return pd.DataFrame({
        f"MACD_{fast}_{slow}_{signal}": macd_line,
        f"MACDs_{fast}_{slow}_{signal}": signal_line,
        f"MACDh_{fast}_{slow}_{signal}": histogram,
    })


def _bbands(series: pd.Series, length: int = 20, std: float = 2.0) -> pd.DataFrame:
    mid = series.rolling(window=length).mean()
    rolling_std = series.rolling(window=length).std()
    upper = mid + std * rolling_std
    lower = mid - std * rolling_std
    return pd.DataFrame({
        f"BBL_{length}_{std}": lower,
        f"BBM_{length}_{std}": mid,
        f"BBU_{length}_{std}": upper,
    })


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add technical indicator columns to a price DataFrame.

    Args:
        df: DataFrame with columns: open, high, low, close, volume.
            Must be indexed by date.

    Returns:
        DataFrame with additional indicator columns added.
    """
    if df.empty or "close" not in df.columns:
        return df

    df = df.copy()

    df["rsi"] = _rsi(df["close"], length=14)
    df["rsi6"] = _rsi(df["close"], length=6)

    macd_result = _macd(df["close"], fast=12, slow=26, signal=9)
    df = pd.concat([df, macd_result], axis=1)

    for period in [5, 10, 20, 60]:
        df[f"ma{period}"] = _sma(df["close"], length=period)

    bb = _bbands(df["close"], length=20, std=2)
    df = pd.concat([df, bb], axis=1)

    return df


def compute_rsi_score(rsi_value: Optional[float]) -> float:
    """Convert RSI to a score in [-1, 1].

    RSI < 30 => oversold => bullish => positive score
    RSI > 70 => overbought => bearish => negative score
    RSI 30-70 => neutral, linearly mapped

    Args:
        rsi_value: RSI value (0-100).

    Returns:
        Score in [-1, 1].
    """
    if rsi_value is None or pd.isna(rsi_value):
        return 0.0

    if rsi_value <= 30:
        # Oversold: strong buy signal
        return round((30 - rsi_value) / 30, 4)
    elif rsi_value >= 70:
        # Overbought: strong sell signal
        return round((70 - rsi_value) / 30, 4)
    else:
        # Neutral zone: map 30-70 to small range [-0.3, 0.3]
        return round((50 - rsi_value) / 66.67, 4)


def compute_macd_score(df: pd.DataFrame) -> float:
    """Compute MACD-based score from the latest data.

    Args:
        df: DataFrame with MACD columns.

    Returns:
        Score in [-1, 1].
    """
    # Find MACD histogram column
    hist_col = None
    for col in df.columns:
        if "MACDh" in col or "MACD_12_26_9" in col:
            if "h" in col.lower() or "hist" in col.lower():
                hist_col = col
                break

    if hist_col is None:
        # Try to find any MACD signal column
        macd_col = signal_col = None
        for col in df.columns:
            if col.startswith("MACD") and "s" not in col.lower() and "h" not in col.lower():
                macd_col = col
            elif col.startswith("MACDs") or "signal" in col.lower():
                signal_col = col

        if macd_col and signal_col:
            last_macd = df[macd_col].iloc[-1]
            last_signal = df[signal_col].iloc[-1]
            if pd.notna(last_macd) and pd.notna(last_signal):
                diff = last_macd - last_signal
                return round(max(-1, min(1, diff / max(abs(last_macd), 0.01))), 4)
        return 0.0

    last_hist = df[hist_col].iloc[-1]
    if pd.isna(last_hist):
        return 0.0

    # Normalize histogram: clip to [-1, 1]
    # Use recent max for normalization
    recent_abs_max = df[hist_col].abs().rolling(20).max().iloc[-1]
    if pd.isna(recent_abs_max) or recent_abs_max == 0:
        recent_abs_max = abs(last_hist) if last_hist != 0 else 1.0

    score = last_hist / recent_abs_max
    return round(max(-1.0, min(1.0, score)), 4)


def compute_ma_score(df: pd.DataFrame) -> float:
    """Compute moving average trend score.

    Bullish when short-term MAs are above long-term MAs.

    Args:
        df: DataFrame with MA columns.

    Returns:
        Score in [-1, 1].
    """
    if df.empty:
        return 0.0

    last = df.iloc[-1]
    close = last.get("close")
    if close is None or pd.isna(close):
        return 0.0

    signals = []

    # Price vs MA comparisons
    for ma_col in ["ma5", "ma10", "ma20", "ma60"]:
        ma_val = last.get(ma_col)
        if ma_val is not None and pd.notna(ma_val) and ma_val > 0:
            pct = (close - ma_val) / ma_val
            signals.append(max(-1, min(1, pct * 10)))  # Scale up for sensitivity

    # Short-term MA vs long-term MA
    ma5 = last.get("ma5")
    ma20 = last.get("ma20")
    if ma5 is not None and ma20 is not None and pd.notna(ma5) and pd.notna(ma20) and ma20 > 0:
        cross = (ma5 - ma20) / ma20
        signals.append(max(-1, min(1, cross * 15)))

    if not signals:
        return 0.0

    return round(sum(signals) / len(signals), 4)


def compute_technical_score(df: pd.DataFrame) -> Dict:
    """Compute composite technical score from all indicators.

    Args:
        df: Price DataFrame (with indicators already computed by compute_indicators).

    Returns:
        Dict with individual and composite scores:
        {rsi_score, macd_score, ma_score, composite}
    """
    if df.empty:
        return {"rsi_score": 0.0, "macd_score": 0.0, "ma_score": 0.0, "composite": 0.0}

    last = df.iloc[-1]

    rsi_val = last.get("rsi")
    rsi_score = compute_rsi_score(rsi_val)
    macd_score = compute_macd_score(df)
    ma_score = compute_ma_score(df)

    # Weighted composite: RSI 30%, MACD 40%, MA 30%
    composite = rsi_score * 0.3 + macd_score * 0.4 + ma_score * 0.3
    composite = round(max(-1.0, min(1.0, composite)), 4)

    # ---- 口诀规则引擎所需的原始数据 ----
    rsi6_val = float(last.get("rsi6")) if last.get("rsi6") is not None and pd.notna(last.get("rsi6")) else None
    macd_cross = detect_macd_cross(df)
    macd_above_zero = detect_macd_above_zero(df)
    advice = generate_rule_advice(rsi6_val, macd_cross, macd_above_zero)

    return {
        "rsi_score": rsi_score,
        "macd_score": macd_score,
        "ma_score": ma_score,
        "composite": composite,
        # 口诀规则相关
        "rsi6": round(rsi6_val, 2) if rsi6_val is not None else None,
        "macd_cross": macd_cross,         # "golden" | "death" | "none"
        "macd_above_zero": macd_above_zero,  # True / False
        "advice": advice,                  # list of advice dicts
    }


# ---------------------------------------------------------------------------
# 口诀规则引擎
# ---------------------------------------------------------------------------

def detect_macd_cross(df: pd.DataFrame) -> str:
    """检测最近是否发生 MACD 金叉或死叉。

    金叉：MACD 线从下方穿越信号线（前一根 MACD < Signal, 当前 MACD >= Signal）
    死叉：MACD 线从上方穿越信号线（前一根 MACD > Signal, 当前 MACD <= Signal）

    Returns:
        "golden" | "death" | "none"
    """
    if len(df) < 3:
        return "none"

    # 查找 MACD 线和信号线列名
    macd_col = signal_col = None
    for col in df.columns:
        col_lower = col.lower()
        if col.startswith("MACD") and "s" not in col_lower and "h" not in col_lower:
            macd_col = col
        elif col.startswith("MACDs") or (col.startswith("MACD") and "s" in col_lower and "h" not in col_lower):
            signal_col = col

    if macd_col is None or signal_col is None:
        return "none"

    # 取最近 3 根 bar 判断交叉（容忍 1 根滞后）
    try:
        for i in range(-1, -4, -1):
            curr_m = df[macd_col].iloc[i]
            curr_s = df[signal_col].iloc[i]
            prev_m = df[macd_col].iloc[i - 1]
            prev_s = df[signal_col].iloc[i - 1]

            if pd.isna(curr_m) or pd.isna(curr_s) or pd.isna(prev_m) or pd.isna(prev_s):
                continue

            if prev_m < prev_s and curr_m >= curr_s:
                return "golden"
            if prev_m > prev_s and curr_m <= curr_s:
                return "death"
    except (IndexError, KeyError):
        pass

    return "none"


def detect_macd_above_zero(df: pd.DataFrame) -> bool:
    """检测当前 MACD 线是否在 0 轴上方。"""
    macd_col = None
    for col in df.columns:
        col_lower = col.lower()
        if col.startswith("MACD") and "s" not in col_lower and "h" not in col_lower:
            macd_col = col
            break

    if macd_col is None:
        return False

    try:
        val = df[macd_col].iloc[-1]
        return bool(pd.notna(val) and val > 0)
    except (IndexError, KeyError):
        return False


def generate_rule_advice(
    rsi6: Optional[float],
    macd_cross: str,
    macd_above_zero: bool,
) -> list:
    """根据口诀规则生成买卖建议列表。

    口诀：
      RSI6 破 30，MACD 金叉 → 短线买
      RSI6 破 70，MACD 死叉 → 短线卖
      0 轴上金叉大胆做，0 轴下金叉少碰
      震荡不上 70、不下 30 → 不操作

    Returns:
        List of dicts: [{"action": "BUY"|"SELL"|"HOLD", "rule": str, "detail": str}]
    """
    advice_list = []

    if rsi6 is None:
        advice_list.append({
            "action": "HOLD",
            "rule": "数据不足",
            "detail": "RSI6 数据不足，无法判断",
        })
        return advice_list

    # ---- 规则 1: RSI6 破 30 + MACD 金叉 → 短线买 ----
    if rsi6 <= 30 and macd_cross == "golden":
        confidence = "高" if macd_above_zero else "中"
        advice_list.append({
            "action": "BUY",
            "rule": "RSI6 破 30 + MACD 金叉 → 短线买",
            "detail": f"RSI6={rsi6:.1f} 进入超卖区，MACD 出现金叉，短线买入信号（置信度: {confidence}）",
        })

    # ---- 规则 2: RSI6 破 70 + MACD 死叉 → 短线卖 ----
    if rsi6 >= 70 and macd_cross == "death":
        advice_list.append({
            "action": "SELL",
            "rule": "RSI6 破 70 + MACD 死叉 → 短线卖",
            "detail": f"RSI6={rsi6:.1f} 进入超买区，MACD 出现死叉，短线卖出信号",
        })

    # ---- 规则 3: 0 轴上金叉大胆做 / 0 轴下金叉少碰 ----
    if macd_cross == "golden" and rsi6 > 30:
        if macd_above_zero:
            advice_list.append({
                "action": "BUY",
                "rule": "0 轴上金叉 → 大胆做",
                "detail": f"MACD 在 0 轴上方出现金叉，趋势向好，可积极操作（RSI6={rsi6:.1f}）",
            })
        else:
            advice_list.append({
                "action": "HOLD",
                "rule": "0 轴下金叉 → 少碰",
                "detail": f"MACD 在 0 轴下方出现金叉，反弹力度不确定，建议观望（RSI6={rsi6:.1f}）",
            })

    # ---- 规则 4: 仅 RSI6 超买/超卖但无交叉确认 ----
    if rsi6 <= 30 and macd_cross != "golden" and not any(a["action"] == "BUY" for a in advice_list):
        advice_list.append({
            "action": "HOLD",
            "rule": "RSI6 超卖但无金叉确认",
            "detail": f"RSI6={rsi6:.1f} 处于超卖区，但 MACD 尚未金叉，等待确认信号",
        })

    if rsi6 >= 70 and macd_cross != "death" and not any(a["action"] == "SELL" for a in advice_list):
        advice_list.append({
            "action": "HOLD",
            "rule": "RSI6 超买但无死叉确认",
            "detail": f"RSI6={rsi6:.1f} 处于超买区，但 MACD 尚未死叉，注意风险",
        })

    # ---- 规则 5: 震荡区间 → 不操作 ----
    if 30 < rsi6 < 70 and macd_cross == "none":
        advice_list.append({
            "action": "HOLD",
            "rule": "震荡区间 → 不操作",
            "detail": f"RSI6={rsi6:.1f} 处于 30-70 震荡区间，无明确交叉信号，建议观望",
        })

    # 兜底
    if not advice_list:
        advice_list.append({
            "action": "HOLD",
            "rule": "无明确信号",
            "detail": f"RSI6={rsi6:.1f}，MACD {'金叉' if macd_cross == 'golden' else '死叉' if macd_cross == 'death' else '无交叉'}，暂无明确操作建议",
        })

    return advice_list


# ===========================================================================
# 期货技术数据计算（纯数据，不含策略建议——策略由 DeepSeek AI 提供）
# ===========================================================================

def _detect_ma_cross(df: pd.DataFrame, fast_col: str, slow_col: str, lookback: int = 3) -> str:
    """Detect golden/death cross between two MA lines within recent bars."""
    if len(df) < lookback + 1:
        return "none"
    try:
        for i in range(-1, -(lookback + 1), -1):
            curr_fast = df[fast_col].iloc[i]
            curr_slow = df[slow_col].iloc[i]
            prev_fast = df[fast_col].iloc[i - 1]
            prev_slow = df[slow_col].iloc[i - 1]
            if pd.isna(curr_fast) or pd.isna(curr_slow) or pd.isna(prev_fast) or pd.isna(prev_slow):
                continue
            if prev_fast < prev_slow and curr_fast >= curr_slow:
                return "golden"
            if prev_fast > prev_slow and curr_fast <= curr_slow:
                return "death"
    except (IndexError, KeyError):
        pass
    return "none"


def compute_futures_swing_score(df: pd.DataFrame) -> Dict:
    """Compute raw technical data for futures (MA, RSI, MACD, cross signals).

    Only provides numerical data and indicator values — no fixed strategy
    advice.  Strategy interpretation is delegated to DeepSeek AI.

    Returns:
        Dict with technical scores and swing raw data.
    """
    empty = {
        "rsi_score": 0.0, "macd_score": 0.0, "ma_score": 0.0, "composite": 0.0,
        "rsi6": None, "macd_cross": "none", "macd_above_zero": False, "advice": [],
        "swing": {
            "trend": "neutral",
            "ma5": None, "ma20": None, "ma60": None,
            "ma5_ma20_cross": "none",
            "entry_price": None, "stop_loss_price": None,
            "take_profit_half": None,
        },
    }

    if df.empty or len(df) < 60:
        return empty

    last = df.iloc[-1]
    close = last.get("close")
    ma5 = last.get("ma5")
    ma20 = last.get("ma20")
    ma60 = last.get("ma60")

    if any(v is None or pd.isna(v) for v in [close, ma5, ma20, ma60]):
        return empty

    close = float(close)
    ma5 = float(ma5)
    ma20 = float(ma20)
    ma60 = float(ma60)

    trend = "bullish" if close > ma60 else "bearish"
    ma5_ma20_cross = _detect_ma_cross(df, "ma5", "ma20", lookback=3)

    rsi_val = last.get("rsi")
    rsi_score = compute_rsi_score(rsi_val if pd.notna(rsi_val) else None)
    macd_score = compute_macd_score(df)
    ma_score = compute_ma_score(df)
    rsi6_val = float(last.get("rsi6")) if last.get("rsi6") is not None and pd.notna(last.get("rsi6")) else None
    macd_cross = detect_macd_cross(df)
    macd_above_zero = detect_macd_above_zero(df)

    composite = rsi_score * 0.2 + macd_score * 0.4 + ma_score * 0.4
    composite = round(max(-1.0, min(1.0, composite)), 4)

    return {
        "rsi_score": rsi_score,
        "macd_score": macd_score,
        "ma_score": ma_score,
        "composite": composite,
        "rsi6": round(rsi6_val, 2) if rsi6_val is not None else None,
        "macd_cross": macd_cross,
        "macd_above_zero": macd_above_zero,
        "advice": [],
        "swing": {
            "trend": trend,
            "ma5": round(ma5, 2),
            "ma20": round(ma20, 2),
            "ma60": round(ma60, 2),
            "ma5_ma20_cross": ma5_ma20_cross,
            "entry_price": None,
            "stop_loss_price": None,
            "take_profit_half": None,
        },
    }
