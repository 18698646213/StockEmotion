"""趋势追踪：净值曲线、排名变化、跨周期对比."""

import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class TrendAnalyzer:
    """Track trends across multiple ranking snapshots over time."""

    def __init__(self):
        self._snapshots: list[tuple[str, pd.DataFrame]] = []

    def add_snapshot(self, label: str, df: pd.DataFrame) -> None:
        """Add a ranking snapshot for a specific time period.

        Args:
            label: Period label (e.g. '2026_01', 'q1_2026').
            df: DataFrame with ranking data (must have 'nickname').
        """
        self._snapshots.append((label, df.copy()))
        self._snapshots.sort(key=lambda x: x[0])

    @property
    def labels(self) -> list[str]:
        return [s[0] for s in self._snapshots]

    def track_trader(self, nickname: str) -> pd.DataFrame:
        """Track a single trader across snapshots.

        Returns DataFrame indexed by period label with columns for each metric.
        """
        records: list[dict[str, Any]] = []
        for label, df in self._snapshots:
            mask = df["nickname"] == nickname
            if mask.any():
                row = df[mask].iloc[0].to_dict()
                row["period"] = label
                records.append(row)
        if not records:
            return pd.DataFrame()
        return pd.DataFrame(records).set_index("period")

    def rank_changes(self, top_n: int = 50) -> pd.DataFrame:
        """Track rank changes of top N traders across snapshots.

        Returns a pivot table: rows = nicknames, columns = period labels, values = rank.
        """
        if len(self._snapshots) < 2:
            return pd.DataFrame()

        last_label, last_df = self._snapshots[-1]
        if "rank" not in last_df.columns or "nickname" not in last_df.columns:
            return pd.DataFrame()
        top_traders = last_df.nsmallest(top_n, "rank")["nickname"].tolist()

        records: list[dict[str, Any]] = []
        for label, df in self._snapshots:
            for _, row in df.iterrows():
                if row.get("nickname") in top_traders:
                    records.append({
                        "nickname": row["nickname"],
                        "period": label,
                        "rank": row.get("rank"),
                    })

        if not records:
            return pd.DataFrame()

        pivot = pd.DataFrame(records).pivot_table(
            index="nickname", columns="period", values="rank", aggfunc="first",
        )
        return pivot[sorted(pivot.columns)]

    def net_value_curves(self, nicknames: list[str] | None = None) -> pd.DataFrame:
        """Extract net value time series across snapshots.

        Returns pivot table: rows = period, columns = nickname, values = net_value.
        """
        records: list[dict[str, Any]] = []
        for label, df in self._snapshots:
            if "net_value" not in df.columns:
                continue
            for _, row in df.iterrows():
                if nicknames and row.get("nickname") not in nicknames:
                    continue
                records.append({
                    "period": label,
                    "nickname": row.get("nickname"),
                    "net_value": row.get("net_value"),
                })

        if not records:
            return pd.DataFrame()

        return pd.DataFrame(records).pivot_table(
            index="period", columns="nickname", values="net_value", aggfunc="first",
        )

    def market_overview(self) -> pd.DataFrame:
        """Aggregate market-level statistics across snapshots.

        Returns DataFrame with one row per snapshot.
        """
        records: list[dict[str, Any]] = []
        for label, df in self._snapshots:
            entry: dict[str, Any] = {"period": label, "participants": len(df)}
            if "net_value" in df.columns:
                nv = pd.to_numeric(df["net_value"], errors="coerce").dropna()
                entry["median_nav"] = float(nv.median()) if len(nv) else None
                entry["mean_nav"] = float(nv.mean()) if len(nv) else None
            if "profit_rate" in df.columns:
                pr = pd.to_numeric(df["profit_rate"], errors="coerce").dropna()
                entry["median_return"] = float(pr.median()) if len(pr) else None
                entry["mean_return"] = float(pr.mean()) if len(pr) else None
                entry["pct_profitable"] = float((pr > 0).mean()) if len(pr) else None
            if "max_drawdown" in df.columns:
                dd = pd.to_numeric(df["max_drawdown"], errors="coerce").dropna()
                entry["median_drawdown"] = float(dd.median()) if len(dd) else None
            records.append(entry)

        return pd.DataFrame(records).set_index("period") if records else pd.DataFrame()

    def period_comparison(self, col: str = "profit_rate") -> pd.DataFrame:
        """Compare distribution of a metric across periods.

        Returns DataFrame with descriptive stats per period.
        """
        records: list[dict[str, Any]] = []
        for label, df in self._snapshots:
            if col not in df.columns:
                continue
            s = pd.to_numeric(df[col], errors="coerce").dropna()
            if s.empty:
                continue
            records.append({
                "period": label,
                "count": len(s),
                "mean": float(s.mean()),
                "std": float(s.std()),
                "min": float(s.min()),
                "q25": float(s.quantile(0.25)),
                "median": float(s.median()),
                "q75": float(s.quantile(0.75)),
                "max": float(s.max()),
            })
        return pd.DataFrame(records).set_index("period") if records else pd.DataFrame()
