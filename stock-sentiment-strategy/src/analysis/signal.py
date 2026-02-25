"""Trading signal generation by combining sentiment, technical, and news volume scores.

Composite scoring formula:
    total = sentiment_score * w_s + technical_score * w_t + news_volume_score * w_v

Signal mapping:
    > 0.6   => STRONG_BUY
    0.3~0.6 => BUY
   -0.3~0.3 => HOLD
   -0.6~-0.3 => SELL
    < -0.6  => STRONG_SELL
"""

import logging
import math
from dataclasses import dataclass
from typing import List, Dict

from src.data.news_us import NewsItem

logger = logging.getLogger(__name__)


@dataclass
class TradingSignal:
    """Represents a composite trading signal for a stock."""
    ticker: str
    sentiment_score: float
    technical_score: float
    news_volume_score: float
    composite_score: float
    signal: str  # STRONG_BUY, BUY, HOLD, SELL, STRONG_SELL
    signal_cn: str  # Chinese label
    news_count: int
    detail: Dict


def score_to_signal(score: float) -> tuple:
    """Convert composite score to signal label.

    Args:
        score: Composite score in [-1, 1].

    Returns:
        Tuple of (english_label, chinese_label).
    """
    if score > 0.6:
        return "STRONG_BUY", "强买入"
    elif score > 0.3:
        return "BUY", "买入"
    elif score > -0.3:
        return "HOLD", "持有"
    elif score > -0.6:
        return "SELL", "卖出"
    else:
        return "STRONG_SELL", "强卖出"


def compute_news_volume_score(
    current_count: int,
    baseline_count: float = 5.0,
) -> float:
    """Compute news volume anomaly score.

    A sudden spike in news volume may indicate a significant event.
    Positive spike -> could be positive or negative, so use moderate signal.

    Args:
        current_count: Number of news items in the lookback window.
        baseline_count: Expected average news count.

    Returns:
        Score in [-1, 1]. Higher volume gives a moderate positive/attention signal.
    """
    if baseline_count <= 0:
        baseline_count = 1.0

    if current_count == 0:
        return -0.2  # No news can be slightly bearish

    ratio = current_count / baseline_count

    if ratio <= 1.0:
        # Normal or below-normal volume
        return 0.0
    else:
        # Above-normal: log scale to avoid extreme values
        # More news = more attention, moderate positive signal
        score = min(1.0, math.log2(ratio) / 3.0)
        return round(score, 4)


def generate_signal(
    ticker: str,
    sentiment_score: float,
    technical_scores: Dict,
    news_count: int,
    sentiment_weight: float = 0.4,
    technical_weight: float = 0.4,
    volume_weight: float = 0.2,
    baseline_news_count: float = 5.0,
) -> TradingSignal:
    """Generate a composite trading signal for a stock.

    Args:
        ticker: Stock ticker/code.
        sentiment_score: Aggregate sentiment score in [-1, 1].
        technical_scores: Dict from compute_technical_score.
        news_count: Number of news items analyzed.
        sentiment_weight: Weight for sentiment score.
        technical_weight: Weight for technical score.
        volume_weight: Weight for news volume score.
        baseline_news_count: Expected average news count for volume anomaly.

    Returns:
        TradingSignal object.
    """
    tech_composite = technical_scores.get("composite", 0.0)
    news_vol_score = compute_news_volume_score(news_count, baseline_news_count)

    composite = (
        sentiment_score * sentiment_weight
        + tech_composite * technical_weight
        + news_vol_score * volume_weight
    )
    composite = round(max(-1.0, min(1.0, composite)), 4)

    signal_en, signal_cn = score_to_signal(composite)

    return TradingSignal(
        ticker=ticker,
        sentiment_score=round(sentiment_score, 4),
        technical_score=round(tech_composite, 4),
        news_volume_score=round(news_vol_score, 4),
        composite_score=composite,
        signal=signal_en,
        signal_cn=signal_cn,
        news_count=news_count,
        detail={
            "rsi_score": technical_scores.get("rsi_score", 0.0),
            "macd_score": technical_scores.get("macd_score", 0.0),
            "ma_score": technical_scores.get("ma_score", 0.0),
            "weights": {
                "sentiment": sentiment_weight,
                "technical": technical_weight,
                "volume": volume_weight,
            },
            # 口诀规则引擎数据
            "rsi6": technical_scores.get("rsi6"),
            "macd_cross": technical_scores.get("macd_cross", "none"),
            "macd_above_zero": technical_scores.get("macd_above_zero", False),
            "advice": technical_scores.get("advice", []),
        },
    )


def generate_futures_swing_signal(
    ticker: str,
    sentiment_score: float,
    swing_scores: Dict,
    news_count: int,
    sentiment_weight: float = 0.2,
    technical_weight: float = 0.6,
    volume_weight: float = 0.2,
    baseline_news_count: float = 3.0,
) -> TradingSignal:
    """Minimal fallback signal for futures when DeepSeek is unavailable.

    Combines raw technical scores with sentiment.  No fixed strategy rules —
    those are handled by DeepSeek AI when configured.
    """
    swing_composite = swing_scores.get("composite", 0.0)
    news_vol_score = compute_news_volume_score(news_count, baseline_news_count)

    composite = (
        sentiment_score * sentiment_weight
        + swing_composite * technical_weight
        + news_vol_score * volume_weight
    )
    composite = round(max(-1.0, min(1.0, composite)), 4)

    signal_en, signal_cn = score_to_signal(composite)

    advice = swing_scores.get("advice", [])
    if not advice:
        advice = [{"action": "HOLD", "rule": "请配置 DeepSeek",
                    "detail": "配置 DeepSeek API Key 后可获得 AI 驱动的投资建议"}]

    return TradingSignal(
        ticker=ticker,
        sentiment_score=round(sentiment_score, 4),
        technical_score=round(swing_composite, 4),
        news_volume_score=round(news_vol_score, 4),
        composite_score=composite,
        signal=signal_en,
        signal_cn=signal_cn,
        news_count=news_count,
        detail={
            "rsi_score": swing_scores.get("rsi_score", 0.0),
            "macd_score": swing_scores.get("macd_score", 0.0),
            "ma_score": swing_scores.get("ma_score", 0.0),
            "weights": {
                "sentiment": sentiment_weight,
                "technical": technical_weight,
                "volume": volume_weight,
            },
            "rsi6": swing_scores.get("rsi6"),
            "macd_cross": swing_scores.get("macd_cross", "none"),
            "macd_above_zero": swing_scores.get("macd_above_zero", False),
            "advice": advice,
            "swing": swing_scores.get("swing", {}),
        },
    )
