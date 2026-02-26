"""Base scraper with retry, rate-limiting, and caching."""

import hashlib
import json
import logging
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import requests
import yaml

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


def load_config() -> dict:
    if _CONFIG_PATH.exists():
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


class BaseScraper(ABC):
    """Abstract base for all competition scrapers."""

    def __init__(self, source_name: str):
        self.source_name = source_name
        self.cfg = load_config()
        scraper_cfg = self.cfg.get("scraper", {})
        self.user_agent = scraper_cfg.get(
            "user_agent",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        self.request_delay = scraper_cfg.get("request_delay", 2.0)
        self.max_retries = scraper_cfg.get("max_retries", 3)
        self.retry_delay = scraper_cfg.get("retry_delay", 5.0)
        self.timeout = scraper_cfg.get("timeout", 30)
        self.use_playwright = scraper_cfg.get("use_playwright", True)

        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })
        self._last_request_time = 0.0

        self._cache_dir = Path(__file__).resolve().parent.parent / "data" / ".cache"
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def _rate_limit(self) -> None:
        elapsed = time.time() - self._last_request_time
        if elapsed < self.request_delay:
            time.sleep(self.request_delay - elapsed)
        self._last_request_time = time.time()

    def _cache_key(self, url: str, params: dict | None = None) -> str:
        raw = url + json.dumps(params or {}, sort_keys=True)
        return hashlib.md5(raw.encode()).hexdigest()

    def _get_cached(self, key: str, max_age_hours: float = 24) -> str | None:
        path = self._cache_dir / f"{key}.json"
        if not path.exists():
            return None
        age_hours = (time.time() - path.stat().st_mtime) / 3600
        if age_hours > max_age_hours:
            return None
        with open(path, encoding="utf-8") as f:
            return f.read()

    def _set_cache(self, key: str, content: str) -> None:
        path = self._cache_dir / f"{key}.json"
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    def fetch_url(
        self,
        url: str,
        params: dict | None = None,
        cache_hours: float = 24,
        method: str = "GET",
        json_body: dict | None = None,
    ) -> str:
        """Fetch URL with retry, rate-limiting, and optional caching.

        Returns the response text.
        """
        key = self._cache_key(url, params)
        cached = self._get_cached(key, cache_hours)
        if cached is not None:
            logger.debug("Cache hit: %s", url)
            return cached

        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            self._rate_limit()
            try:
                if method.upper() == "POST":
                    resp = self._session.post(
                        url, params=params, json=json_body, timeout=self.timeout,
                    )
                else:
                    resp = self._session.get(url, params=params, timeout=self.timeout)
                resp.raise_for_status()
                self._set_cache(key, resp.text)
                return resp.text
            except Exception as e:
                last_exc = e
                logger.warning(
                    "[%s] Attempt %d/%d failed for %s: %s",
                    self.source_name, attempt, self.max_retries, url, e,
                )
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay * attempt)

        raise RuntimeError(
            f"[{self.source_name}] All {self.max_retries} attempts failed for {url}"
        ) from last_exc

    def fetch_with_playwright(self, url: str, wait_selector: str | None = None) -> str:
        """Fetch a page using Playwright for JS-rendered content."""
        from playwright.sync_api import sync_playwright

        key = self._cache_key(url)
        cached = self._get_cached(key, 24)
        if cached is not None:
            logger.debug("Cache hit (playwright): %s", url)
            return cached

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=self.user_agent)
            page.goto(url, wait_until="networkidle", timeout=self.timeout * 1000)
            if wait_selector:
                page.wait_for_selector(wait_selector, timeout=15000)
            time.sleep(2)
            content = page.content()
            browser.close()

        self._set_cache(key, content)
        return content

    @abstractmethod
    def scrape_ranking(self, **kwargs) -> list[dict[str, Any]]:
        """Scrape ranking data. Returns list of row dicts."""
        ...

    def close(self) -> None:
        self._session.close()
