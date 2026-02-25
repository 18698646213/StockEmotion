"""China A-share news collection from akshare (Eastmoney / Sina Finance)."""

import logging
from datetime import datetime, timedelta
from typing import List

from src.data.news_us import NewsItem

logger = logging.getLogger(__name__)

# When date-based filtering returns 0 results, return the N most recent items
_FALLBACK_NEWS_COUNT = 5


def _normalize_stock_code(code: str) -> str:
    """Ensure stock code is 6 digits."""
    return code.strip().zfill(6)


def fetch_eastmoney_news(code: str, lookback_days: int = 7) -> List[NewsItem]:
    """Fetch individual stock news from Eastmoney via akshare.

    Args:
        code: A-share stock code (e.g. '600519').
        lookback_days: Number of days to look back.

    Returns:
        List of NewsItem objects.
    """
    code = _normalize_stock_code(code)
    cutoff = datetime.now() - timedelta(days=lookback_days)

    all_parsed: List[NewsItem] = []

    try:
        import akshare as ak

        df = ak.stock_news_em(symbol=code)

        if df is None or df.empty:
            return []

        for _, row in df.iterrows():
            title = str(row.get("新闻标题", ""))
            content = str(row.get("新闻内容", ""))
            if not content or not content.strip() or content == "nan":
                content = title
            source = str(row.get("文章来源", "eastmoney"))
            url = str(row.get("新闻链接", ""))

            pub_str = str(row.get("发布时间", ""))
            try:
                pub_dt = datetime.strptime(pub_str, "%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError):
                pub_dt = datetime.now()

            all_parsed.append(
                NewsItem(
                    title=title,
                    summary=content[:500] if len(content) > 500 else content,
                    source=source,
                    published_at=pub_dt,
                    ticker=code,
                    url=url,
                )
            )
    except Exception as e:
        logger.error("Eastmoney news fetch failed for %s: %s", code, e)
        return []

    # Filter by lookback window
    items = [n for n in all_parsed if n.published_at >= cutoff]

    # If date filtering removed everything, fall back to the most recent items
    if not items and all_parsed:
        all_parsed.sort(key=lambda x: x.published_at, reverse=True)
        items = all_parsed[:_FALLBACK_NEWS_COUNT]
        logger.info(
            "Date filter returned 0 for %s (cutoff=%s), using %d most recent items instead",
            code, cutoff.strftime("%Y-%m-%d"), len(items),
        )

    return items


def fetch_cctv_news() -> List[NewsItem]:
    """Fetch CCTV financial news (macro-level) via akshare.

    Returns:
        List of NewsItem objects (ticker set to 'MACRO').
    """
    items: List[NewsItem] = []
    try:
        import akshare as ak

        df = ak.news_cctv(date=datetime.now().strftime("%Y%m%d"))

        if df is None or df.empty:
            return items

        for _, row in df.iterrows():
            title = str(row.get("title", ""))
            content = str(row.get("content", title))

            items.append(
                NewsItem(
                    title=title,
                    summary=content[:500] if len(content) > 500 else content,
                    source="CCTV",
                    published_at=datetime.now(),
                    ticker="MACRO",
                )
            )
    except Exception as e:
        logger.error("CCTV news fetch failed: %s", e)

    return items


def fetch_cn_news(code: str, lookback_days: int = 3) -> List[NewsItem]:
    """Fetch A-share stock news with multiple sources.

    Args:
        code: A-share stock code (e.g. '600519').
        lookback_days: Number of days to look back.

    Returns:
        List of NewsItem objects sorted by publish time descending.
    """
    items = fetch_eastmoney_news(code, lookback_days)

    # Sort by publish time descending
    items.sort(key=lambda x: x.published_at, reverse=True)
    logger.info("Fetched %d CN news items for %s", len(items), code)
    return items
