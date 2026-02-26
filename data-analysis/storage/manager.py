"""CSV/JSON data storage manager with dedup and incremental updates."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"


class StorageManager:
    """Manage scraped competition data on disk (CSV files)."""

    def __init__(self, base_dir: Path | str | None = None):
        self.base_dir = Path(base_dir) if base_dir else _DATA_DIR
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _source_dir(self, source: str) -> Path:
        d = self.base_dir / source
        d.mkdir(parents=True, exist_ok=True)
        return d

    @staticmethod
    def _make_filename(source: str, label: str, ext: str = "csv") -> str:
        ts = datetime.now().strftime("%Y%m%d")
        safe_label = label.replace("/", "_").replace(" ", "_")
        return f"{source}_{safe_label}_{ts}.{ext}"

    def save_rows(
        self,
        rows: list[dict[str, Any]],
        source: str,
        label: str,
        dedup_key: str | None = "nickname",
    ) -> Path:
        """Save list-of-dicts to a CSV file, deduplicating against existing data.

        Returns the path to the saved file.
        """
        if not rows:
            logger.warning("No rows to save for %s/%s", source, label)
            return Path()

        df_new = pd.DataFrame(rows)
        existing = self.load_latest(source, label)
        if existing is not None and not existing.empty and dedup_key and dedup_key in df_new.columns:
            combined = pd.concat([existing, df_new], ignore_index=True)
            combined = combined.drop_duplicates(subset=[dedup_key], keep="last")
        else:
            combined = df_new

        out_dir = self._source_dir(source)
        fname = self._make_filename(source, label)
        path = out_dir / fname
        combined.to_csv(path, index=False, encoding="utf-8-sig")
        logger.info("Saved %d rows -> %s", len(combined), path)
        return path

    def load_latest(self, source: str, label: str) -> pd.DataFrame | None:
        """Load the most recent CSV for the given source + label."""
        d = self._source_dir(source)
        prefix = f"{source}_{label.replace('/', '_').replace(' ', '_')}_"
        matches = sorted(d.glob(f"{prefix}*.csv"), reverse=True)
        if not matches:
            return None
        path = matches[0]
        logger.debug("Loading %s", path)
        return pd.read_csv(path, encoding="utf-8-sig")

    def load_all(self, source: str) -> pd.DataFrame:
        """Load and concat all CSVs for a given source."""
        d = self._source_dir(source)
        files = sorted(d.glob("*.csv"))
        if not files:
            return pd.DataFrame()
        frames = [pd.read_csv(f, encoding="utf-8-sig") for f in files]
        return pd.concat(frames, ignore_index=True)

    def save_json(self, data: Any, source: str, label: str) -> Path:
        out_dir = self._source_dir(source)
        fname = self._make_filename(source, label, ext="json")
        path = out_dir / fname
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info("Saved JSON -> %s", path)
        return path

    def list_files(self, source: str | None = None) -> list[Path]:
        if source:
            d = self._source_dir(source)
            return sorted(d.glob("*.*"))
        return sorted(self.base_dir.rglob("*.*"))
