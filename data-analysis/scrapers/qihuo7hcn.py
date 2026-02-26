"""七禾网 (trader.7hcn.com) 实战排行榜爬虫.

APIs:
  - GET /api/trader/contest/contestList     — 综合排行榜
  - GET /api/trader/contest/futuresList     — 品种盈利排行
  - GET /api/trader/AnalyseData/get         — 选手图表数据 (权益/净值/回撤/品种)
  - GET /api/trader/AnalyseData/overviewData — 选手每日结存
  - GET /api/trader/AnalyseData/closeStat   — 选手平仓统计
"""

import logging
import re
from typing import Any

from .base import BaseScraper

logger = logging.getLogger(__name__)

TID_MAP: dict[str, int] = {
    "all": 0,
    "2021-2022": 57,
    "2022-2023": 59,
    "2023-2024": 60,
    "2024-2025": 61,
    "2025-2026": 62,
    "long_term": 63,
}

TAG_MAP = {
    "nav": "累计净值",
    "credit": "综合积分",
    "pf": "年化收益率",
    "tnp": "收益金额",
    "w": "胜率",
}

FUTURES_CODES: dict[str, str] = {
    "IF": "沪深300", "IH": "上证50", "IC": "中证500", "IM": "中证1000",
    "T": "十债", "TF": "五债", "TS": "二债", "TL": "三十年国债",
    "CU": "铜", "BC": "国际铜", "AL": "铝", "ZN": "锌", "NI": "镍",
    "PB": "铅", "SN": "锡", "SS": "不锈钢", "AO": "氧化铝",
    "AU": "黄金", "AG": "白银",
    "RB": "螺纹钢", "HC": "热卷", "I": "铁矿石", "J": "焦炭", "JM": "焦煤",
    "SM": "锰硅", "SF": "硅铁", "FG": "玻璃",
    "SC": "原油", "FU": "燃料油", "BU": "沥青", "RU": "橡胶",
    "TA": "PTA", "L": "塑料", "PP": "聚丙烯", "V": "PVC", "MA": "甲醇",
    "EG": "乙二醇", "EB": "苯乙烯", "PG": "液化石油气",
    "M": "豆粕", "RM": "菜粕", "Y": "豆油", "OI": "菜油", "P": "棕榈油",
    "CF": "棉花", "SR": "白糖", "C": "玉米", "CS": "淀粉",
    "AP": "苹果", "JD": "鸡蛋", "LH": "生猪", "PK": "花生",
    "EC": "集运指数",
}


def _clean_html(text: str) -> str:
    if not isinstance(text, str):
        return str(text) if text is not None else ""
    return re.sub(r"<[^>]+>", "", text)


def _parse_unit(text: str) -> float:
    """Parse '43.94万' -> 439400.0"""
    text = _clean_html(text)
    m = re.search(r"([\d.]+)\s*(万|亿)?", text)
    if not m:
        return 0.0
    val = float(m.group(1))
    unit = m.group(2)
    if unit == "万":
        return val * 1e4
    if unit == "亿":
        return val * 1e8
    return val


class Qihuo7hcnScraper(BaseScraper):
    """Scraper for 七禾网 trading competition rankings."""

    BASE_URL = "https://trader.7hcn.com"

    def __init__(self):
        super().__init__("qihuo7hcn")
        self._session.headers.update({"Referer": "https://trader.7hcn.com/"})

    def _fetch_contest_page(
        self,
        page: int = 1,
        tid: int = 62,
        tag: str = "nav",
        number: int = 50,
        keyword: str = "",
    ) -> dict[str, Any]:
        url = f"{self.BASE_URL}/api/trader/contest/contestList"
        params = {"number": number, "page": page, "tid": tid, "tag": tag, "kw": keyword}
        text = self.fetch_url(url, params=params, cache_hours=6)
        import json
        data = json.loads(text)
        if data.get("response") != 0:
            raise RuntimeError(f"7hcn API error: {data.get('message', 'unknown')}")
        return data.get("data", {})

    def _fetch_futures_page(
        self,
        futures_code: str,
        page: int = 1,
        number: int = 50,
        tid: int = 0,
    ) -> dict[str, Any]:
        url = f"{self.BASE_URL}/api/trader/contest/futuresList"
        params = {
            "number": number, "page": page,
            "futures": futures_code.lower(), "tid": tid,
        }
        text = self.fetch_url(url, params=params, cache_hours=6)
        import json
        data = json.loads(text)
        if data.get("response") != 0:
            raise RuntimeError(f"7hcn futures API error: {data.get('message')}")
        return data.get("data", {})

    @staticmethod
    def _safe_float(val: Any, strip_pct: bool = False) -> float:
        if val is None:
            return 0.0
        s = _clean_html(str(val)).strip()
        if strip_pct:
            s = s.rstrip("%")
        s = s.replace(",", "")
        if not s:
            return 0.0
        try:
            return float(s)
        except ValueError:
            cleaned = re.sub(r"[^\d.\-]", "", s)
            return float(cleaned) if cleaned else 0.0

    @classmethod
    def _process_contest_row(cls, row: dict) -> dict[str, Any]:
        return {
            "rank": int(row.get("no", 0)),
            "uid": row.get("uid", ""),
            "nickname": _clean_html(row.get("user", "")),
            "company": _clean_html(row.get("company", "")),
            "net_value": cls._safe_float(row.get("total_nav", 0)),
            "equity": _parse_unit(row.get("equity", "0")),
            "avg_equity": _parse_unit(row.get("avg_equity", "0")),
            "profit_rate": cls._safe_float(row.get("total_yield", 0), strip_pct=True),
            "max_drawdown": cls._safe_float(row.get("max_lost", "0"), strip_pct=True),
            "credit_score": cls._safe_float(row.get("credit", 0)),
            "annualized_return": cls._safe_float(row.get("annualized_return", 0)),
            "win_rate": cls._safe_float(row.get("winning", 0)),
            "start_date": row.get("first_date", ""),
            "update_date": row.get("dateline", ""),
            "source": "qihuo7hcn",
        }

    @classmethod
    def _process_futures_row(cls, row: dict) -> dict[str, Any]:
        return {
            "rank": int(row.get("no", 0)),
            "nickname": _clean_html(row.get("user", "")),
            "company": _clean_html(row.get("company", "")),
            "profit": _parse_unit(row.get("profit", "0")),
            "avg_profit": cls._safe_float(row.get("avg_profit", 0)),
            "fee": _parse_unit(row.get("fee", "0")),
            "win_rate": cls._safe_float(row.get("winning", 0)),
            "equity": _parse_unit(row.get("equity", "0")),
            "start_date": row.get("first_date", ""),
            "update_date": row.get("dateline", ""),
            "source": "qihuo7hcn",
        }

    def scrape_ranking(
        self,
        tid: str | int = "2025-2026",
        tag: str = "nav",
        max_pages: int | None = None,
    ) -> list[dict[str, Any]]:
        """Scrape contest ranking list.

        Args:
            tid: Period key (from TID_MAP) or raw integer id.
            tag: Sort tag — 'nav', 'credit', 'pf', 'tnp', 'w'.
            max_pages: Limit pages; None = all.
        """
        if isinstance(tid, int):
            tid_val = tid
        else:
            tid_val = TID_MAP.get(str(tid))
            if tid_val is None:
                try:
                    tid_val = int(tid)
                except ValueError:
                    tid_val = 62
        all_rows: list[dict[str, Any]] = []
        page = 1
        while True:
            logger.info("[7hcn] contest page %d (tid=%s, tag=%s)", page, tid, tag)
            data = self._fetch_contest_page(page=page, tid=tid_val, tag=tag)
            rows = data.get("data", [])
            if not rows:
                break
            all_rows.extend(self._process_contest_row(r) for r in rows)
            page_nav = data.get("pageNav", "")
            if not page_nav or f"page={page + 1}" not in str(page_nav):
                break
            if max_pages and page >= max_pages:
                break
            page += 1
        logger.info("[7hcn] scraped %d contest rows", len(all_rows))
        return all_rows

    def scrape_futures_ranking(
        self,
        futures_code: str,
        tid: str | int = "all",
        max_pages: int | None = None,
    ) -> list[dict[str, Any]]:
        """Scrape per-variety profit ranking."""
        tid_val = TID_MAP.get(str(tid), 0) if not isinstance(tid, int) else tid
        all_rows: list[dict[str, Any]] = []
        page = 1
        while True:
            logger.info("[7hcn] futures %s page %d", futures_code, page)
            data = self._fetch_futures_page(futures_code, page=page, tid=tid_val)
            rows = data.get("data", [])
            if not rows:
                break
            all_rows.extend(self._process_futures_row(r) for r in rows)
            page_nav = data.get("pageNav", "")
            if not page_nav or f"page={page + 1}" not in str(page_nav):
                break
            if max_pages and page >= max_pages:
                break
            page += 1
        logger.info("[7hcn] scraped %d rows for %s", len(all_rows), futures_code)
        return all_rows

    # ------------------------------------------------------------------
    # Trader detail APIs
    # ------------------------------------------------------------------

    def _fetch_json(self, url: str, params: dict) -> dict:
        import json as _json
        text = self.fetch_url(url, params=params, cache_hours=12)
        text = re.sub(r"^[a-zA-Z_]+\((.*)\);?\s*$", r"\1", text, flags=re.DOTALL)
        data = _json.loads(text)
        if data.get("response") != 0:
            raise RuntimeError(f"7hcn detail API error: {data.get('message')}")
        return data.get("data", {})

    def scrape_trader_chart(
        self, aid: int, chart_type: str = "equity", tid: int = 0,
    ) -> list[dict[str, Any]]:
        """Fetch chart data for a single trader.

        Args:
            aid: Account id (from ranking uid field).
            chart_type: 'equity' | 'nav' | 'drawdown' | 'variety' | 'profit' | 'position'.
            tid: Period id (0 = all).
        """
        url = f"{self.BASE_URL}/api/trader/AnalyseData/get"
        params = {"aid": aid, "tid": tid, "type": chart_type}
        data = self._fetch_json(url, params)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("data", data.get("list", [data]))
        return []

    def scrape_trader_daily(self, aid: int, tid: int = 0) -> list[dict[str, Any]]:
        """Fetch daily settlement data (每日结存) for a trader."""
        url = f"{self.BASE_URL}/api/trader/AnalyseData/overviewData"
        params = {"aid": aid, "tid": tid, "page": 1, "number": 500}
        data = self._fetch_json(url, params)
        if isinstance(data, dict):
            return data.get("data", [])
        return data if isinstance(data, list) else []

    def scrape_trader_close_stat(self, aid: int, tid: int = 0) -> list[dict[str, Any]]:
        """Fetch close/settlement stats for a trader."""
        url = f"{self.BASE_URL}/api/trader/AnalyseData/closeStat"
        params = {"aid": aid, "tid": tid}
        data = self._fetch_json(url, params)
        if isinstance(data, dict):
            return data.get("data", [data])
        return data if isinstance(data, list) else []

    def scrape_trader_full(self, aid: int, tid: int = 0) -> dict[str, Any]:
        """Scrape all available detail data for a trader.

        Returns a dict with keys: equity_curve, nav_curve, drawdown_curve,
        variety_breakdown, daily_settlement, close_stats.
        """
        result: dict[str, Any] = {"aid": aid}
        for chart in ["equity", "nav", "drawdown", "variety", "profit", "position"]:
            try:
                result[chart] = self.scrape_trader_chart(aid, chart, tid)
                logger.info("[7hcn] aid=%d chart=%s: %d items", aid, chart, len(result[chart]))
            except Exception as e:
                logger.warning("[7hcn] aid=%d chart=%s failed: %s", aid, chart, e)
                result[chart] = []
        try:
            result["daily"] = self.scrape_trader_daily(aid, tid)
            logger.info("[7hcn] aid=%d daily: %d items", aid, len(result["daily"]))
        except Exception as e:
            logger.warning("[7hcn] aid=%d daily failed: %s", aid, e)
            result["daily"] = []
        return result
