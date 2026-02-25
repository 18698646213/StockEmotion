"""US stock news collection from Finnhub and Yahoo Finance."""

import logging
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import List

import finnhub
import yfinance as yf

logger = logging.getLogger(__name__)


@dataclass
class NewsItem:
    """Unified news item format across all data sources."""
    title: str
    summary: str
    source: str
    published_at: datetime
    ticker: str
    url: str = ""


def fetch_finnhub_news(
    ticker: str,
    api_key: str,
    lookback_days: int = 7,
) -> List[NewsItem]:
    """Fetch company news from Finnhub API.

    Args:
        ticker: US stock ticker symbol (e.g. 'AAPL').
        api_key: Finnhub API key.
        lookback_days: Number of days to look back.

    Returns:
        List of NewsItem objects.
    """
    items: List[NewsItem] = []
    if not api_key or api_key == "YOUR_KEY":
        logger.warning("Finnhub API key not configured, skipping Finnhub news.")
        return items

    try:
        client = finnhub.Client(api_key=api_key)
        end_date = datetime.now()
        start_date = end_date - timedelta(days=lookback_days)
        raw = client.company_news(
            ticker,
            _from=start_date.strftime("%Y-%m-%d"),
            to=end_date.strftime("%Y-%m-%d"),
        )
        for article in raw:
            headline = article.get("headline", "")
            summary = article.get("summary", "")
            # Finnhub sometimes returns empty summary; fall back to headline
            if not summary or not summary.strip():
                summary = headline
            items.append(
                NewsItem(
                    title=headline,
                    summary=summary,
                    source=article.get("source", "finnhub"),
                    published_at=datetime.fromtimestamp(article.get("datetime", 0)),
                    ticker=ticker,
                    url=article.get("url", ""),
                )
            )
    except Exception as e:
        logger.error("Finnhub news fetch failed for %s: %s", ticker, e)

    return items


def fetch_yfinance_news(ticker: str) -> List[NewsItem]:
    """Fetch news from Yahoo Finance as fallback.

    Args:
        ticker: US stock ticker symbol.

    Returns:
        List of NewsItem objects.
    """
    items: List[NewsItem] = []
    try:
        stock = yf.Ticker(ticker)
        news = stock.news or []
        for article in news:
            # yfinance >= 0.2.31 may return different structures
            pub_time = article.get("providerPublishTime", 0)
            if isinstance(pub_time, (int, float)):
                pub_dt = datetime.fromtimestamp(pub_time)
            else:
                pub_dt = datetime.now()

            title = article.get("title", "")
            # Try multiple field names for summary (yfinance varies by version)
            summary = (
                article.get("summary")
                or article.get("description")
                or article.get("content")
                or ""
            )
            # If summary is still empty or whitespace-only, use the title
            if not summary or not summary.strip():
                summary = title

            url = article.get("link") or article.get("url") or ""

            items.append(
                NewsItem(
                    title=title,
                    summary=summary,
                    source=article.get("publisher", "yahoo"),
                    published_at=pub_dt,
                    ticker=ticker,
                    url=url,
                )
            )
    except Exception as e:
        logger.error("Yahoo Finance news fetch failed for %s: %s", ticker, e)

    return items


def fetch_us_news(
    ticker: str,
    api_key: str = "",
    lookback_days: int = 7,
) -> List[NewsItem]:
    """Fetch US stock news, trying Finnhub first then Yahoo Finance fallback.

    Args:
        ticker: US stock ticker symbol.
        api_key: Finnhub API key.
        lookback_days: Number of days to look back.

    Returns:
        Combined list of NewsItem objects, deduplicated by title.
    """
    items = fetch_finnhub_news(ticker, api_key, lookback_days)

    # Always supplement with Yahoo Finance
    yf_items = fetch_yfinance_news(ticker)

    # Deduplicate by title
    seen_titles = {item.title.lower().strip() for item in items}
    for item in yf_items:
        key = item.title.lower().strip()
        if key and key not in seen_titles:
            seen_titles.add(key)
            items.append(item)

    # Sort by publish time descending
    items.sort(key=lambda x: x.published_at, reverse=True)

    # Apply date filter
    cutoff = datetime.now() - timedelta(days=lookback_days)
    filtered = [n for n in items if n.published_at >= cutoff]

    # If date filtering removed everything, fall back to most recent items
    if not filtered and items:
        filtered = items[:5]
        logger.info(
            "Date filter returned 0 US news for %s (cutoff=%s), using %d most recent",
            ticker, cutoff.strftime("%Y-%m-%d"), len(filtered),
        )

    logger.info("Fetched %d US news items for %s", len(filtered), ticker)
    return filtered
