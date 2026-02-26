"""牛钱网 (niumoney.com) 期货实盘大赛排行榜爬虫.

API endpoint: GET https://www.niumoney.com/?app=trader&action=top
Response format: JSONP — jsonp({...})
"""

import json
import logging
import re
from typing import Any

from bs4 import BeautifulSoup

from .base import BaseScraper

logger = logging.getLogger(__name__)

# tid -> 榜单名称
RANKING_TIDS: dict[str, int] = {
    # 年榜
    "year_all": 0,
    "year_2026": 143,
    "year_2025": 125,
    "year_2024": 105,
    "year_2023": 85,
    "year_2022": 68,
    "year_2021": 49,
    "year_2020": 46,
    "year_2019": 35,
    # 季榜
    "q1_2026": 140,
    "q4_2025": 138,
    "q3_2025": 133,
    "q2_2025": 130,
    "q1_2025": 126,
    # 月榜（近期）
    "month_2026_02": 142,
    "month_2026_01": 141,
    "month_2025_12": 139,
    "month_2025_11": 137,
    "month_2025_10": 136,
}

SORT_FIELDS = {
    "net_value": "n",
    "equity": "eq",
    "profit_rate": "pr",
    "net_profit": "tnp",
    "credit": "ct",
    "max_drawdown": "ml",
}

GROUP_NAMES = {
    "all": "",
    "light": "轻量组",
    "heavy": "重量组",
    "option": "期权组",
}


def _strip_html(text: str) -> str:
    if not text:
        return ""
    return BeautifulSoup(text, "html.parser").get_text()


def _parse_amount(raw: str) -> float:
    """Convert '510.58万' / '-3.2亿' to float (元)."""
    text = _strip_html(raw).replace(" ", "").replace(",", "")
    if not text:
        return 0.0
    multiplier = 1.0
    if "亿" in text:
        multiplier = 1e8
    elif "万" in text:
        multiplier = 1e4
    cleaned = re.sub(r"[^\d.\-]", "", text)
    try:
        return float(cleaned) * multiplier
    except ValueError:
        return 0.0


class NiumoneyScraper(BaseScraper):
    """Scraper for 牛钱网 futures trading competition rankings."""

    BASE_URL = "https://www.niumoney.com/"

    def __init__(self):
        super().__init__("niumoney")
        self._session.headers.update({"Referer": "https://www.niumoney.com/cccps/1"})

    def _fetch_page(
        self,
        page: int = 1,
        tid: int = 143,
        group: str = "",
        sort: str = "tnp",
        keyword: str = "",
    ) -> dict[str, Any]:
        params = {
            "app": "trader",
            "action": "top",
            "callback": "jsonp",
            "page": page,
            "tid": tid,
            "tg": group,
            "kw": keyword,
            "ob": sort,
        }
        text = self.fetch_url(self.BASE_URL, params=params, cache_hours=6)
        json_str = re.sub(r"^jsonp\((.*)\);?\s*$", r"\1", text, flags=re.DOTALL)
        data = json.loads(json_str)
        if data.get("response") != 0:
            raise RuntimeError(f"API error: {data.get('message', 'unknown')}")
        return data["data"]

    @staticmethod
    def _process_row(row: dict) -> dict[str, Any]:
        return {
            "rank": int(row.get("no", 0)),
            "uid": row.get("uid", ""),
            "nickname": row.get("user", ""),
            "company": row.get("company", ""),
            "net_value": float(row.get("c_total_nav", 0)),
            "equity": _parse_amount(row.get("equity", "0")),
            "net_profit": _parse_amount(row.get("tn_profit", "0")),
            "profit_rate": float(row.get("profit_rate", 0)),
            "max_drawdown": float(row.get("c_max_lost", 0)),
            "credit_score": float(row.get("c_credit", 0)),
            "total_fee": float(row.get("total_fee", 0)),
            "option_profit": _parse_amount(row.get("optn_profit", "0")),
            "start_date": row.get("first_date", ""),
            "update_date": row.get("dateline", ""),
            "start_equity": _parse_amount(row.get("first_equity", "0")),
            "source": "niumoney",
        }

    def scrape_ranking(
        self,
        tid: int = 143,
        group: str = "",
        sort: str = "tnp",
        max_pages: int | None = None,
    ) -> list[dict[str, Any]]:
        """Scrape ranking pages.

        Args:
            tid: Ranking type id (see RANKING_TIDS).
            group: Group filter (see GROUP_NAMES values).
            sort: Sort field code (see SORT_FIELDS values).
            max_pages: Stop after N pages; None = fetch all.
        """
        all_rows: list[dict[str, Any]] = []
        page = 1
        while True:
            logger.info("[niumoney] page %d (tid=%d)", page, tid)
            data = self._fetch_page(page=page, tid=tid, group=group, sort=sort)
            rows = data.get("data", [])
            if not rows:
                break
            all_rows.extend(self._process_row(r) for r in rows)
            total = int(data.get("total", 0))
            if len(all_rows) >= total:
                break
            if max_pages and page >= max_pages:
                break
            page += 1
        logger.info("[niumoney] scraped %d rows (tid=%d)", len(all_rows), tid)
        return all_rows

    def scrape_summary(self) -> dict[str, Any]:
        """Scrape aggregate summary data (参赛人数 / 保证金规模)."""
        params = {"app": "trader", "action": "summary", "callback": "jsonp"}
        text = self.fetch_url(self.BASE_URL, params=params, cache_hours=6)
        json_str = re.sub(r"^jsonp\((.*)\);?\s*$", r"\1", text, flags=re.DOTALL)
        data = json.loads(json_str)
        if data.get("response") != 0:
            return {}
        return data.get("data", {})
