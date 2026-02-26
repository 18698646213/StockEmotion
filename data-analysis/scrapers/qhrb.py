"""期货日报 (spds.qhrb.com.cn) 全国期货实盘大赛爬虫.

The official competition site uses ASP.NET with ViewState.
Pages: http://spds.qhrb.com.cn:8888/SP12/SPOverSee1.aspx (第12届)
       http://spds.qhrb.com.cn:8888/ShiPan/S10/Index.aspx (第10届)
"""

import logging
import re
from typing import Any

from bs4 import BeautifulSoup

from .base import BaseScraper

logger = logging.getLogger(__name__)

GROUP_PAGES = {
    "light": "SPOverSee1.aspx",
    "heavy": "SPOverSee2.aspx",
    "fund": "SPOverSee3.aspx",
    "programmatic": "SPOverSee4.aspx",
}


class QhrbScraper(BaseScraper):
    """Scraper for 期货日报 official competition (ASP.NET pages)."""

    BASE_URL = "http://spds.qhrb.com.cn:8888"

    def __init__(self):
        super().__init__("qhrb")

    def _parse_table(self, html: str) -> list[dict[str, Any]]:
        """Parse the ranking table from an ASP.NET page."""
        soup = BeautifulSoup(html, "lxml")
        table = soup.find("table", {"class": re.compile(r"grid|table|data", re.I)})
        if not table:
            tables = soup.find_all("table")
            for t in tables:
                rows = t.find_all("tr")
                if len(rows) > 5:
                    table = t
                    break
        if not table:
            logger.warning("[qhrb] No data table found")
            return []

        rows = table.find_all("tr")
        if len(rows) < 2:
            return []

        header_cells = rows[0].find_all(["th", "td"])
        headers = [c.get_text(strip=True) for c in header_cells]

        COL_MAP = {
            "排名": "rank", "名次": "rank",
            "客户昵称": "nickname", "昵称": "nickname",
            "当日权益": "equity",
            "风险度": "risk_ratio",
            "净利润": "net_profit", "累计净利润": "net_profit",
            "净利润得分": "profit_score",
            "回撤率": "max_drawdown", "最大回撤率": "max_drawdown",
            "累计净值": "net_value",
            "参考收益率": "profit_rate", "收益率": "profit_rate",
            "综合得分": "credit_score", "综合分": "credit_score",
        }

        mapped_headers = []
        for h in headers:
            matched = False
            for cn, en in COL_MAP.items():
                if cn in h:
                    mapped_headers.append(en)
                    matched = True
                    break
            if not matched:
                mapped_headers.append(h)

        results: list[dict[str, Any]] = []
        for tr in rows[1:]:
            cells = tr.find_all("td")
            if len(cells) != len(mapped_headers):
                continue
            row: dict[str, Any] = {}
            for header, cell in zip(mapped_headers, cells):
                text = cell.get_text(strip=True)
                if header in ("rank",):
                    try:
                        row[header] = int(text)
                    except ValueError:
                        row[header] = text
                elif header in ("equity", "net_profit", "net_value", "profit_rate",
                                "max_drawdown", "credit_score", "risk_ratio", "profit_score"):
                    cleaned = re.sub(r"[^\d.\-]", "", text)
                    try:
                        row[header] = float(cleaned) if cleaned else 0.0
                    except ValueError:
                        row[header] = 0.0
                else:
                    row[header] = text
            row["source"] = "qhrb"
            results.append(row)

        return results

    def _get_aspnet_page(self, url: str, page_num: int = 1) -> str:
        """Handle ASP.NET postback pagination."""
        if page_num <= 1:
            return self.fetch_url(url, cache_hours=12)

        html = self.fetch_url(url, cache_hours=12)
        soup = BeautifulSoup(html, "lxml")

        viewstate = ""
        vs_tag = soup.find("input", {"name": "__VIEWSTATE"})
        if vs_tag:
            viewstate = vs_tag.get("value", "")
        event_validation = ""
        ev_tag = soup.find("input", {"name": "__EVENTVALIDATION"})
        if ev_tag:
            event_validation = ev_tag.get("value", "")

        form_data = {
            "__VIEWSTATE": viewstate,
            "__EVENTVALIDATION": event_validation,
            "__EVENTTARGET": "AspNetPager1",
            "__EVENTARGUMENT": str(page_num),
        }

        self._rate_limit()
        resp = self._session.post(url, data=form_data, timeout=self.timeout)
        resp.raise_for_status()
        return resp.text

    def scrape_ranking(
        self,
        edition: int = 12,
        group: str = "light",
        max_pages: int | None = 5,
    ) -> list[dict[str, Any]]:
        """Scrape ranking from 期货日报 official site.

        Args:
            edition: Competition edition number (e.g. 10, 12).
            group: 'light', 'heavy', 'fund', 'programmatic'.
            max_pages: Max pages to scrape (ASP.NET pagination).
        """
        page_name = GROUP_PAGES.get(group, "SPOverSee1.aspx")
        url = f"{self.BASE_URL}/SP{edition}/{page_name}"

        all_rows: list[dict[str, Any]] = []
        page = 1
        while True:
            logger.info("[qhrb] edition=%d group=%s page=%d", edition, group, page)
            try:
                html = self._get_aspnet_page(url, page)
                rows = self._parse_table(html)
                if not rows:
                    break
                all_rows.extend(rows)
                if max_pages and page >= max_pages:
                    break
                page += 1
            except Exception as e:
                logger.warning("[qhrb] Failed at page %d: %s", page, e)
                break

        logger.info("[qhrb] scraped %d rows (edition=%d, group=%s)", len(all_rows), edition, group)
        return all_rows

    def scrape_account_detail(self, edition: int, account_id: str) -> dict[str, Any]:
        """Scrape individual account evaluation data."""
        url = f"{self.BASE_URL}/ShiPan/S{edition}/Index.aspx"
        params = {"id": account_id}
        try:
            html = self.fetch_url(url, params=params, cache_hours=24)
            soup = BeautifulSoup(html, "lxml")

            result: dict[str, Any] = {"account_id": account_id, "source": "qhrb"}
            tables = soup.find_all("table")
            for table in tables:
                for tr in table.find_all("tr"):
                    cells = tr.find_all("td")
                    if len(cells) >= 2:
                        key = cells[0].get_text(strip=True)
                        val = cells[1].get_text(strip=True)
                        if key:
                            result[key] = val
            return result
        except Exception as e:
            logger.error("[qhrb] account detail failed: %s", e)
            return {"account_id": account_id, "error": str(e)}
