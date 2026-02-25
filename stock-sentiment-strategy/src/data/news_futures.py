"""Chinese futures news collection.

Primary source: EastMoney keyword search (ak.stock_news_em) — works for ALL
commodity types with precise keyword matching.
Secondary source: SHMET metal news (ak.futures_news_shmet) for metals.
Fallback: CCTV macro news filtered by keywords.
"""

import logging
import re
from datetime import datetime, timedelta
from typing import List

from src.data.news_us import NewsItem
from src.data.news_cn import fetch_cctv_news

logger = logging.getLogger(__name__)

_FALLBACK_NEWS_COUNT = 5

# ---------------------------------------------------------------------------
# Symbol -> Chinese keyword(s) for news search
# ---------------------------------------------------------------------------

_SYMBOL_KEYWORDS: dict[str, List[str]] = {
    # ===== DCE (大商所) - 农产品 =====
    "C":  ["玉米", "玉米期货", "玉米价格", "玉米淀粉", "饲料玉米"],
    "CS": ["玉米淀粉", "淀粉", "淀粉价格"],
    "A":  ["大豆", "豆一", "大豆价格", "大豆进口"],
    "B":  ["大豆", "豆二", "大豆进口", "大豆价格"],
    "M":  ["豆粕", "豆粕价格", "饲料", "养殖"],
    "Y":  ["豆油", "豆油价格", "食用油"],
    "P":  ["棕榈油", "棕榈油价格", "食用油"],
    "JD": ["鸡蛋", "鸡蛋价格", "蛋鸡", "养殖"],
    "LH": ["生猪", "猪肉", "生猪价格", "养殖"],
    "RR": ["粳米", "大米", "稻谷"],
    "LG": ["原木", "木材", "木材价格"],
    # DCE - 化工
    "L":  ["塑料", "聚乙烯", "塑料价格", "PE"],
    "V":  ["PVC", "聚氯乙烯", "PVC价格"],
    "PP": ["聚丙烯", "PP价格", "塑料"],
    "EG": ["乙二醇", "乙二醇价格", "聚酯"],
    "EB": ["苯乙烯", "苯乙烯价格"],
    "PG": ["液化气", "LPG", "液化气价格"],
    "BZ": ["纯苯", "纯苯价格"],
    # DCE - 黑色
    "I":  ["铁矿石", "铁矿", "铁矿石价格", "钢铁"],
    "J":  ["焦炭", "焦炭价格", "焦化"],
    "JM": ["焦煤", "焦煤价格", "煤炭"],

    # ===== CZCE (郑商所) =====
    "CF": ["棉花", "棉花价格", "纺织"],
    "SR": ["白糖", "白糖价格", "食糖", "糖价"],
    "TA": ["PTA", "PTA价格", "聚酯"],
    "MA": ["甲醇", "甲醇价格", "甲醇期货"],
    "OI": ["菜油", "菜籽油", "菜油价格", "食用油"],
    "RM": ["菜粕", "菜粕价格", "油菜籽"],
    "FG": ["玻璃", "玻璃价格", "浮法玻璃", "光伏玻璃"],
    "SA": ["纯碱", "纯碱价格", "玻璃"],
    "AP": ["苹果", "苹果价格", "苹果期货"],
    "CJ": ["红枣", "红枣价格"],
    "UR": ["尿素", "尿素价格", "化肥"],
    "PF": ["短纤", "短纤价格", "聚酯"],
    "PK": ["花生", "花生价格", "油料"],
    "SF": ["硅铁", "硅铁价格"],
    "SM": ["锰硅", "锰硅价格"],
    "CY": ["棉纱", "棉纱价格", "纺织"],
    "WH": ["小麦", "强麦", "小麦价格"],
    "RS": ["菜籽", "油菜籽"],
    "SH": ["烧碱", "烧碱价格"],
    "PX": ["对二甲苯", "PX价格"],
    "PR": ["瓶片", "瓶片价格"],
    "PL": ["丙烯", "丙烯价格"],

    # ===== SHFE (上期所) - 金属 =====
    "CU": ["铜", "沪铜", "铜价格", "铜价"],
    "AL": ["铝", "沪铝", "铝价格", "铝价"],
    "ZN": ["锌", "沪锌", "锌价格"],
    "PB": ["铅", "沪铅", "铅价格"],
    "NI": ["镍", "沪镍", "镍价格", "不锈钢"],
    "SN": ["锡", "沪锡", "锡价格"],
    "AU": ["黄金", "沪金", "金价", "黄金价格"],
    "AG": ["白银", "沪银", "银价", "白银价格"],
    "SS": ["不锈钢", "不锈钢价格"],
    "AO": ["氧化铝", "氧化铝价格"],
    # SHFE - 其他
    "RB": ["螺纹钢", "螺纹钢价格", "钢铁", "钢材"],
    "HC": ["热卷", "热卷价格", "钢铁"],
    "BU": ["沥青", "沥青价格"],
    "RU": ["橡胶", "天然橡胶", "橡胶价格"],
    "FU": ["燃料油", "燃料油价格"],
    "SP": ["纸浆", "纸浆价格"],
    "BR": ["丁二烯橡胶"],

    # ===== INE (能源中心) =====
    "SC": ["原油", "石油", "原油价格", "油价"],
    "NR": ["橡胶", "20号胶", "橡胶价格"],
    "LU": ["低硫燃油", "燃料油", "燃油价格"],
    "BC": ["铜", "国际铜", "铜价"],
    "EC": ["集运", "集装箱", "集运指数", "航运"],

    # ===== CFFEX (中金所) =====
    "IF": ["沪深300", "股指期货", "A股"],
    "IH": ["上证50", "股指期货", "A股"],
    "IC": ["中证500", "股指期货", "A股"],
    "IM": ["中证1000", "股指期货", "A股"],
    "TF": ["国债期货", "5年国债", "利率"],
    "TS": ["国债期货", "2年国债", "利率"],
    "T":  ["国债期货", "10年国债", "利率"],

    # ===== GFEX (广期所) =====
    "SI": ["工业硅", "工业硅价格", "多晶硅"],
    "LC": ["碳酸锂", "锂", "锂价格", "新能源"],
    "PS": ["多晶硅", "多晶硅价格", "光伏"],
    "PT": ["铂", "铂金价格"],
    "PD": ["钯", "钯金价格"],
}

# Full symbol -> display name
FUTURES_DISPLAY_NAMES: dict[str, str] = {
    "CU0": "沪铜", "AL0": "沪铝", "ZN0": "沪锌", "PB0": "沪铅",
    "NI0": "沪镍", "SN0": "沪锡", "AU0": "沪金", "AG0": "沪银",
    "RB0": "螺纹钢", "HC0": "热卷", "BU0": "沥青", "RU0": "橡胶",
    "FU0": "燃料油", "SP0": "纸浆", "SS0": "不锈钢", "AO0": "氧化铝",
    "BR0": "丁二烯橡胶",
    "I0": "铁矿石", "J0": "焦炭", "JM0": "焦煤",
    "M0": "豆粕", "Y0": "豆油", "P0": "棕榈油", "A0": "豆一", "B0": "豆二",
    "C0": "玉米", "CS0": "淀粉", "JD0": "鸡蛋", "LH0": "生猪",
    "L0": "塑料", "V0": "PVC", "PP0": "聚丙烯", "EG0": "乙二醇",
    "EB0": "苯乙烯", "PG0": "液化气", "RR0": "粳米", "LG0": "原木",
    "BZ0": "纯苯",
    "TA0": "PTA", "MA0": "甲醇", "CF0": "棉花", "SR0": "白糖",
    "OI0": "菜油", "RM0": "菜粕", "FG0": "玻璃", "SA0": "纯碱",
    "AP0": "苹果", "CJ0": "红枣", "UR0": "尿素", "PF0": "短纤",
    "PK0": "花生", "SF0": "硅铁", "SM0": "锰硅", "CY0": "棉纱",
    "WH0": "强麦", "RS0": "菜籽", "SH0": "烧碱", "PX0": "对二甲苯",
    "PR0": "瓶片", "PL0": "丙烯",
    "SC0": "原油", "NR0": "20号胶", "LU0": "低硫燃油", "BC0": "国际铜",
    "EC0": "集运指数",
    "IF0": "沪深300", "IH0": "上证50", "IC0": "中证500", "IM0": "中证1000",
    "TF0": "5年国债", "TS0": "2年国债", "T0": "10年国债",
    "SI0": "工业硅", "LC0": "碳酸锂", "PS0": "多晶硅", "PT0": "铂", "PD0": "钯",
}

# SHMET metal categories (for secondary metal-specific news)
_SHMET_NAME_MAP: dict[str, str] = {
    "CU": "铜", "AL": "铝", "ZN": "锌", "PB": "铅",
    "NI": "镍", "SN": "锡", "AU": "贵金属", "AG": "贵金属",
    "SS": "小金属", "AO": "小金属", "BC": "铜",
    "SI": "小金属", "LC": "小金属",
}

# Regex to strip trailing digits from a symbol: C2605 -> C, RB2510 -> RB
_BASE_RE = re.compile(r"^([A-Z]{1,2})\d*$")


def get_futures_display_name(symbol: str) -> str:
    """Return the Chinese display name for a futures symbol."""
    return FUTURES_DISPLAY_NAMES.get(symbol.strip().upper(), symbol)


def _extract_base(symbol: str) -> str:
    """Extract base product code: C2605->C, RB0->RB, MA2509->MA."""
    m = _BASE_RE.match(symbol.strip().upper())
    return m.group(1) if m else symbol.strip().upper()


def _get_keywords(symbol: str) -> List[str]:
    """Get search keywords for a futures symbol."""
    base = _extract_base(symbol)
    return _SYMBOL_KEYWORDS.get(base, [])


# ---------------------------------------------------------------------------
# News sources
# ---------------------------------------------------------------------------

def _fetch_eastmoney_news(
    keyword: str,
    symbol: str,
) -> List[NewsItem]:
    """Fetch commodity news from EastMoney via keyword search.

    Returns ALL items (up to ~10 per keyword); date filtering is done by the caller.
    """
    items: List[NewsItem] = []

    try:
        import akshare as ak
        df = ak.stock_news_em(symbol=keyword)
        if df is None or df.empty:
            return []

        for _, row in df.iterrows():
            title = str(row.get("新闻标题", ""))
            content = str(row.get("新闻内容", ""))
            if not title or title == "nan":
                continue

            pub_raw = row.get("发布时间", "")
            try:
                pub_dt = datetime.strptime(str(pub_raw)[:19], "%Y-%m-%d %H:%M:%S")
            except Exception:
                pub_dt = datetime.now()

            source = str(row.get("文章来源", "东方财富"))
            url = str(row.get("新闻链接", ""))

            items.append(NewsItem(
                title=title,
                summary=content[:500] if content and content != "nan" else title,
                source=source,
                published_at=pub_dt,
                ticker=symbol,
                url=url,
            ))
    except Exception as e:
        logger.debug("EastMoney news failed for keyword '%s': %s", keyword, e)
        return []

    return items


def _fetch_shmet_news(
    cn_name: str,
    symbol: str,
    lookback_days: int = 7,
) -> List[NewsItem]:
    """Fetch metal-specific news from Shanghai Metals Market via akshare."""
    cutoff = datetime.now() - timedelta(days=lookback_days)
    items: List[NewsItem] = []

    try:
        import akshare as ak
        df = ak.futures_news_shmet(symbol=cn_name)
        if df is None or df.empty:
            return []

        for _, row in df.iterrows():
            content = str(row.get("内容", ""))
            if not content or content == "nan":
                continue

            title = content.split("。")[0][:60] if "。" in content else content[:60]

            pub_raw = row.get("发布时间", None)
            try:
                if hasattr(pub_raw, "to_pydatetime"):
                    pub_dt = pub_raw.to_pydatetime().replace(tzinfo=None)
                else:
                    pub_dt = datetime.strptime(str(pub_raw)[:19], "%Y-%m-%d %H:%M:%S")
            except Exception:
                pub_dt = datetime.now()

            items.append(NewsItem(
                title=title,
                summary=content[:500],
                source="上海有色金属网",
                published_at=pub_dt,
                ticker=symbol,
            ))
    except Exception as e:
        logger.debug("SHMET news failed for %s (%s): %s", symbol, cn_name, e)
        return []

    filtered = [n for n in items if n.published_at >= cutoff]
    if not filtered and items:
        items.sort(key=lambda x: x.published_at, reverse=True)
        filtered = items[:_FALLBACK_NEWS_COUNT]

    return filtered


def _filter_by_keywords(items: List[NewsItem], keywords: List[str]) -> List[NewsItem]:
    """Keep only news items whose title or summary contains at least one keyword."""
    if not keywords:
        return items
    result = []
    for item in items:
        text = item.title + item.summary
        if any(kw in text for kw in keywords):
            result.append(item)
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_MIN_NEWS_TARGET = 8
_MAX_NEWS_ITEMS = 20


def fetch_futures_news(
    symbol: str,
    lookback_days: int = 7,
) -> List[NewsItem]:
    """Fetch futures-related news specific to the given commodity.

    Strategy:
      1. EastMoney keyword search with ALL keywords (each returns ~10 items)
      2. SHMET metal news (for metals only)
      3. CCTV macro news filtered by keywords (final fallback)
      4. Date-sort and cap at _MAX_NEWS_ITEMS
    """
    symbol = symbol.strip().upper()
    base = _extract_base(symbol)
    keywords = _get_keywords(symbol)
    all_items: List[NewsItem] = []
    seen_titles: set = set()

    def _dedupe_add(new_items: List[NewsItem]):
        for item in new_items:
            key = item.title[:30]
            if key not in seen_titles:
                seen_titles.add(key)
                all_items.append(item)

    # Primary keywords are the first 1-2 (exact commodity name);
    # the rest are broader terms used only if we still need more.
    primary_kws = keywords[:2]
    broader_kws = keywords[2:]

    # 1a. EastMoney — primary keywords (exact match, all items kept)
    for kw in primary_kws:
        items = _fetch_eastmoney_news(kw, symbol)
        _dedupe_add(items)

    # 1b. EastMoney — broader keywords (filtered by core keyword to stay relevant)
    core_kw = primary_kws[:1]  # e.g. ["玉米"] — strictest filter
    if len(all_items) < _MIN_NEWS_TARGET and core_kw:
        for kw in broader_kws:
            items = _fetch_eastmoney_news(kw, symbol)
            items = _filter_by_keywords(items, core_kw)
            _dedupe_add(items)
            if len(all_items) >= _MAX_NEWS_ITEMS:
                break

    # 2. SHMET for metals
    shmet_cat = _SHMET_NAME_MAP.get(base)
    if shmet_cat and len(all_items) < _MAX_NEWS_ITEMS:
        items = _fetch_shmet_news(shmet_cat, symbol, lookback_days)
        _dedupe_add(items)

    # 3. Fallback: CCTV macro news filtered by commodity keywords
    if len(all_items) < _MIN_NEWS_TARGET:
        cctv_items = fetch_cctv_news()
        for item in cctv_items:
            item.ticker = symbol
        if keywords:
            filtered = _filter_by_keywords(cctv_items, keywords)
            _dedupe_add(filtered)
        if len(all_items) < 3:
            _dedupe_add(cctv_items[:_FALLBACK_NEWS_COUNT])

    all_items.sort(key=lambda x: x.published_at, reverse=True)
    all_items = all_items[:_MAX_NEWS_ITEMS]

    logger.info(
        "Fetched %d news items for futures %s (keywords=%s)",
        len(all_items), symbol, keywords,
    )
    return all_items
