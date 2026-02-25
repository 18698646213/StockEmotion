"""Strategy engine: orchestrates data collection, analysis, and signal generation.

Provides position sizing recommendations and risk management.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional

import pandas as pd

from src.config import AppConfig, load_config
from src.data.news_us import fetch_us_news, NewsItem
from src.data.news_cn import fetch_cn_news
from src.data.news_futures import fetch_futures_news
from src.data.price_us import fetch_us_price
from src.data.price_cn import fetch_cn_price
from src.data.price_futures import fetch_futures_price
from src.analysis.sentiment import analyze_news_sentiment, compute_aggregate_sentiment
from src.analysis.technical import compute_indicators, compute_technical_score, compute_futures_swing_score
from src.analysis.signal import generate_signal, generate_futures_swing_signal, TradingSignal
from src.analysis.deepseek import analyze_with_deepseek

logger = logging.getLogger(__name__)


@dataclass
class StockAnalysis:
    """Complete analysis result for a single stock."""
    ticker: str
    market: str  # 'US' or 'CN'
    signal: TradingSignal
    news_items: List[NewsItem]
    sentiment_results: List[Dict]
    price_df: pd.DataFrame
    position_pct: float  # Recommended position as percentage
    timestamp: datetime = field(default_factory=datetime.now)


class StrategyEngine:
    """Main strategy engine that coordinates all analysis components."""

    def __init__(self, config: Optional[AppConfig] = None):
        self.config = config or load_config()
        self.history: List[StockAnalysis] = []

    def analyze_us_stock(self, ticker: str) -> StockAnalysis:
        """Run full analysis pipeline for a US stock."""
        cfg = self.config.strategy
        logger.info("Analyzing US stock: %s", ticker)

        news_items = fetch_us_news(
            ticker,
            api_key=self.config.finnhub_api_key,
            lookback_days=cfg.news_lookback_days,
        )

        price_df = fetch_us_price(ticker)
        if not price_df.empty:
            price_df = compute_indicators(price_df)

        tech_scores = compute_technical_score(price_df)

        # Try DeepSeek AI analysis first
        ds = self.config.deepseek
        ai_result = None
        if ds.api_key:
            ai_result = analyze_with_deepseek(ds, ticker, "US", news_items, tech_scores)

        if ai_result:
            signal, sentiment_results = self._build_signal_from_ai(
                ticker, ai_result, news_items, tech_scores, cfg)
        else:
            sentiment_results = analyze_news_sentiment(news_items)
            sentiment_score = compute_aggregate_sentiment(sentiment_results)
            signal = generate_signal(
                ticker=ticker,
                sentiment_score=sentiment_score,
                technical_scores=tech_scores,
                news_count=len(news_items),
                sentiment_weight=cfg.sentiment_weight,
                technical_weight=cfg.technical_weight,
                volume_weight=cfg.volume_weight,
            )

        position_pct = self._compute_position(signal, cfg.max_position)

        result = StockAnalysis(
            ticker=ticker,
            market="US",
            signal=signal,
            news_items=news_items,
            sentiment_results=sentiment_results,
            price_df=price_df,
            position_pct=position_pct,
        )

        self.history.append(result)
        return result

    def analyze_cn_stock(self, code: str) -> StockAnalysis:
        """Run full analysis pipeline for an A-share stock."""
        cfg = self.config.strategy
        logger.info("Analyzing A-share: %s", code)

        news_items = fetch_cn_news(code, lookback_days=cfg.news_lookback_days)

        price_df = fetch_cn_price(code)
        if not price_df.empty:
            price_df = compute_indicators(price_df)

        tech_scores = compute_technical_score(price_df)

        ds = self.config.deepseek
        ai_result = None
        if ds.api_key:
            ai_result = analyze_with_deepseek(ds, code, "CN", news_items, tech_scores)

        if ai_result:
            signal, sentiment_results = self._build_signal_from_ai(
                code, ai_result, news_items, tech_scores, cfg)
        else:
            sentiment_results = analyze_news_sentiment(news_items)
            sentiment_score = compute_aggregate_sentiment(sentiment_results)
            signal = generate_signal(
                ticker=code,
                sentiment_score=sentiment_score,
                technical_scores=tech_scores,
                news_count=len(news_items),
                sentiment_weight=cfg.sentiment_weight,
                technical_weight=cfg.technical_weight,
                volume_weight=cfg.volume_weight,
            )

        position_pct = self._compute_position(signal, cfg.max_position)

        result = StockAnalysis(
            ticker=code,
            market="CN",
            signal=signal,
            news_items=news_items,
            sentiment_results=sentiment_results,
            price_df=price_df,
            position_pct=position_pct,
        )

        self.history.append(result)
        return result

    def analyze_futures_contract(self, symbol: str) -> StockAnalysis:
        """Run full analysis pipeline for a Chinese futures contract."""
        cfg = self.config.futures_strategy
        symbol = symbol.strip().upper()
        logger.info("Analyzing futures (swing): %s (sentiment=%.0f%% tech=%.0f%% vol=%.0f%%)",
                     symbol, cfg.sentiment_weight * 100, cfg.technical_weight * 100, cfg.volume_weight * 100)

        news_items = fetch_futures_news(symbol, lookback_days=cfg.news_lookback_days)

        price_df = fetch_futures_price(symbol)
        if not price_df.empty:
            price_df = compute_indicators(price_df)

        swing_scores = compute_futures_swing_score(price_df)

        ds = self.config.deepseek
        ai_result = None
        if ds.api_key:
            swing_data = swing_scores.get("swing")
            ai_result = analyze_with_deepseek(
                ds, symbol, "FUTURES", news_items, swing_scores, swing_data)

        if ai_result:
            signal, sentiment_results = self._build_signal_from_ai(
                symbol, ai_result, news_items, swing_scores, cfg, is_futures=True)
        else:
            sentiment_results = analyze_news_sentiment(news_items)
            sentiment_score = compute_aggregate_sentiment(sentiment_results)
            signal = generate_futures_swing_signal(
                ticker=symbol,
                sentiment_score=sentiment_score,
                swing_scores=swing_scores,
                news_count=len(news_items),
                sentiment_weight=cfg.sentiment_weight,
                technical_weight=cfg.technical_weight,
                volume_weight=cfg.volume_weight,
            )

        position_pct = self._compute_position(signal, cfg.max_position)

        result = StockAnalysis(
            ticker=symbol,
            market="FUTURES",
            signal=signal,
            news_items=news_items,
            sentiment_results=sentiment_results,
            price_df=price_df,
            position_pct=position_pct,
        )

        self.history.append(result)
        return result

    def analyze_all(self) -> List[StockAnalysis]:
        """Analyze all stocks in the watchlist.

        Returns:
            List of StockAnalysis results.
        """
        results: List[StockAnalysis] = []

        for ticker in self.config.us_stocks:
            try:
                result = self.analyze_us_stock(ticker)
                results.append(result)
            except Exception as e:
                logger.error("Failed to analyze US stock %s: %s", ticker, e)

        for code in self.config.cn_stocks:
            try:
                result = self.analyze_cn_stock(code)
                results.append(result)
            except Exception as e:
                logger.error("Failed to analyze A-share %s: %s", code, e)

        for symbol in self.config.futures_contracts:
            try:
                result = self.analyze_futures_contract(symbol)
                results.append(result)
            except Exception as e:
                logger.error("Failed to analyze futures %s: %s", symbol, e)

        return results

    def _build_signal_from_ai(
        self,
        ticker: str,
        ai: Dict,
        news_items: list,
        tech_scores: Dict,
        cfg,
        is_futures: bool = False,
    ) -> tuple:
        """Build TradingSignal + sentiment_results from DeepSeek AI output."""
        sentiment_score = float(ai.get("sentiment_score", 0.0))
        composite = float(ai.get("composite_score", 0.0))

        ai_advice = ai.get("investment_advice", [])
        if not isinstance(ai_advice, list):
            ai_advice = [{"action": "HOLD", "rule": "AI分析", "detail": str(ai_advice)}]

        news_summary = ai.get("news_summary", "")
        tech_analysis = ai.get("technical_analysis", "")

        if news_summary:
            ai_advice.insert(0, {
                "action": "HOLD",
                "rule": "AI新闻摘要",
                "detail": news_summary,
            })
        if tech_analysis:
            ai_advice.insert(1 if news_summary else 0, {
                "action": "HOLD",
                "rule": "AI技术解读",
                "detail": tech_analysis,
            })

        detail = {
            "rsi_score": tech_scores.get("rsi_score", 0.0),
            "macd_score": tech_scores.get("macd_score", 0.0),
            "ma_score": tech_scores.get("ma_score", 0.0),
            "weights": {
                "sentiment": cfg.sentiment_weight,
                "technical": cfg.technical_weight,
                "volume": cfg.volume_weight,
            },
            "rsi6": tech_scores.get("rsi6"),
            "macd_cross": tech_scores.get("macd_cross", "none"),
            "macd_above_zero": tech_scores.get("macd_above_zero", False),
            "advice": ai_advice,
        }

        if is_futures:
            detail["swing"] = tech_scores.get("swing")

        signal = TradingSignal(
            ticker=ticker,
            sentiment_score=round(sentiment_score, 4),
            technical_score=round(tech_scores.get("composite", 0.0), 4),
            news_volume_score=0.0,
            composite_score=round(max(-1.0, min(1.0, composite)), 4),
            signal=ai.get("signal", "HOLD"),
            signal_cn=ai.get("signal_cn", "持有"),
            news_count=len(news_items),
            detail=detail,
        )

        # Build per-news sentiment using AI's individual analysis
        ai_news_sentiments = ai.get("news_sentiments", [])
        ns_by_index = {}
        for ns in ai_news_sentiments:
            if isinstance(ns, dict) and "index" in ns:
                ns_by_index[int(ns["index"])] = ns

        sentiment_results = []

        # Insert DeepSeek overall analysis as a synthetic top entry
        if news_summary:
            sentiment_results.append({
                "news_item": NewsItem(
                    title="DeepSeek AI 新闻综合分析",
                    summary=news_summary,
                    source="DeepSeek AI",
                    published_at=datetime.now(),
                    ticker=ticker,
                ),
                "score": sentiment_score,
                "label": ai.get("sentiment_label", "neutral"),
                "ai_summary": news_summary,
            })

        if tech_analysis:
            sentiment_results.append({
                "news_item": NewsItem(
                    title="DeepSeek AI 技术面解读",
                    summary=tech_analysis,
                    source="DeepSeek AI",
                    published_at=datetime.now(),
                    ticker=ticker,
                ),
                "score": composite,
                "label": "positive" if composite > 0.1 else ("negative" if composite < -0.1 else "neutral"),
                "ai_summary": tech_analysis,
            })

        # Original news items with per-item AI analysis
        for i, item in enumerate(news_items, 1):
            ns = ns_by_index.get(i, {})
            sentiment_results.append({
                "news_item": item,
                "score": float(ns.get("score", sentiment_score)),
                "label": ns.get("label", ai.get("sentiment_label", "neutral")),
                "ai_summary": ns.get("summary", ""),
            })

        return signal, sentiment_results

    def _compute_position(self, signal: TradingSignal, max_position: float) -> float:
        """Compute recommended position size based on signal strength.

        Args:
            signal: Trading signal.
            max_position: Maximum position percentage (e.g. 0.2 = 20%).

        Returns:
            Recommended position as a percentage [0, max_position].
        """
        score = signal.composite_score

        if score > 0.3:
            # Buy signal: scale position with signal strength
            strength = min((score - 0.3) / 0.7, 1.0)  # 0 to 1
            return round(strength * max_position * 100, 1)
        elif score < -0.3:
            # Sell signal: recommend reducing position
            return 0.0
        else:
            # Hold: maintain current position (no new allocation)
            return 0.0
