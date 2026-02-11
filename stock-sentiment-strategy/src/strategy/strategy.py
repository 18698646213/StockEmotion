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
from src.data.price_us import fetch_us_price
from src.data.price_cn import fetch_cn_price
from src.analysis.sentiment import analyze_news_sentiment, compute_aggregate_sentiment
from src.analysis.technical import compute_indicators, compute_technical_score
from src.analysis.signal import generate_signal, TradingSignal

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
        """Run full analysis pipeline for a US stock.

        Args:
            ticker: US stock ticker symbol.

        Returns:
            StockAnalysis result.
        """
        cfg = self.config.strategy
        logger.info("Analyzing US stock: %s", ticker)

        # 1. Fetch news
        news_items = fetch_us_news(
            ticker,
            api_key=self.config.finnhub_api_key,
            lookback_days=cfg.news_lookback_days,
        )

        # 2. Sentiment analysis
        sentiment_results = analyze_news_sentiment(news_items)
        sentiment_score = compute_aggregate_sentiment(sentiment_results)

        # 3. Fetch price data and compute technical indicators
        price_df = fetch_us_price(ticker)
        if not price_df.empty:
            price_df = compute_indicators(price_df)

        tech_scores = compute_technical_score(price_df)

        # 4. Generate trading signal
        signal = generate_signal(
            ticker=ticker,
            sentiment_score=sentiment_score,
            technical_scores=tech_scores,
            news_count=len(news_items),
            sentiment_weight=cfg.sentiment_weight,
            technical_weight=cfg.technical_weight,
            volume_weight=cfg.volume_weight,
        )

        # 5. Compute position recommendation
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
        """Run full analysis pipeline for an A-share stock.

        Args:
            code: A-share stock code (e.g. '600519').

        Returns:
            StockAnalysis result.
        """
        cfg = self.config.strategy
        logger.info("Analyzing A-share: %s", code)

        # 1. Fetch news
        news_items = fetch_cn_news(code, lookback_days=cfg.news_lookback_days)

        # 2. Sentiment analysis
        sentiment_results = analyze_news_sentiment(news_items)
        sentiment_score = compute_aggregate_sentiment(sentiment_results)

        # 3. Fetch price data and compute technical indicators
        price_df = fetch_cn_price(code)
        if not price_df.empty:
            price_df = compute_indicators(price_df)

        tech_scores = compute_technical_score(price_df)

        # 4. Generate trading signal
        signal = generate_signal(
            ticker=code,
            sentiment_score=sentiment_score,
            technical_scores=tech_scores,
            news_count=len(news_items),
            sentiment_weight=cfg.sentiment_weight,
            technical_weight=cfg.technical_weight,
            volume_weight=cfg.volume_weight,
        )

        # 5. Compute position recommendation
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

        return results

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
