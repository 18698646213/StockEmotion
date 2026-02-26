"""排行榜统计分析：参赛人数、收益分布、盈亏比例、组别差异."""

import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class RankingAnalyzer:
    """Analyze competition ranking data."""

    def __init__(self, df: pd.DataFrame):
        self.df = df.copy()
        self._ensure_numeric()

    def _ensure_numeric(self) -> None:
        num_cols = [
            "net_value", "equity", "net_profit", "profit_rate",
            "max_drawdown", "credit_score", "win_rate",
        ]
        for col in num_cols:
            if col in self.df.columns:
                self.df[col] = pd.to_numeric(self.df[col], errors="coerce")

    def summary(self) -> dict[str, Any]:
        """Overall summary statistics."""
        df = self.df
        total = len(df)
        if total == 0:
            return {"total_participants": 0}

        profitable = df[df["net_profit"] > 0] if "net_profit" in df.columns else pd.DataFrame()
        losing = df[df["net_profit"] < 0] if "net_profit" in df.columns else pd.DataFrame()

        result: dict[str, Any] = {
            "total_participants": total,
            "profitable_count": len(profitable),
            "losing_count": len(losing),
            "profit_ratio": len(profitable) / total if total else 0,
        }

        if "equity" in df.columns:
            result["total_equity"] = df["equity"].sum()
            result["avg_equity"] = df["equity"].mean()
            result["median_equity"] = df["equity"].median()

        if "net_profit" in df.columns:
            result["total_net_profit"] = df["net_profit"].sum()
            result["avg_net_profit"] = df["net_profit"].mean()
            result["median_net_profit"] = df["net_profit"].median()

        return result

    def return_distribution(self) -> dict[str, Any]:
        """Analyze the distribution of profit rates."""
        col = "profit_rate"
        if col not in self.df.columns:
            return {}
        s = self.df[col].dropna()
        if s.empty:
            return {}

        return {
            "count": len(s),
            "mean": float(s.mean()),
            "std": float(s.std()),
            "min": float(s.min()),
            "q25": float(s.quantile(0.25)),
            "median": float(s.median()),
            "q75": float(s.quantile(0.75)),
            "max": float(s.max()),
            "skew": float(s.skew()),
            "kurtosis": float(s.kurtosis()),
            "pct_positive": float((s > 0).mean()),
            "pct_gt_50": float((s > 50).mean()),
            "pct_gt_100": float((s > 100).mean()),
            "pct_lt_neg50": float((s < -50).mean()),
        }

    def profit_loss_analysis(self) -> dict[str, Any]:
        """Analyze profitable vs losing traders."""
        if "net_profit" not in self.df.columns:
            return {}
        df = self.df
        profitable = df[df["net_profit"] > 0]
        losing = df[df["net_profit"] < 0]
        breakeven = df[df["net_profit"] == 0]

        result: dict[str, Any] = {
            "profitable": len(profitable),
            "losing": len(losing),
            "breakeven": len(breakeven),
        }
        if len(profitable) > 0:
            result["avg_profit"] = float(profitable["net_profit"].mean())
            result["max_profit"] = float(profitable["net_profit"].max())
        if len(losing) > 0:
            result["avg_loss"] = float(losing["net_profit"].mean())
            result["max_loss"] = float(losing["net_profit"].min())
        if len(profitable) > 0 and len(losing) > 0:
            result["profit_loss_ratio"] = abs(
                profitable["net_profit"].mean() / losing["net_profit"].mean()
            )
        return result

    def group_comparison(self, group_col: str = "group") -> pd.DataFrame:
        """Compare performance across groups (轻量组/重量组/期权组).

        If no explicit group column, tries to infer from equity levels.
        """
        df = self.df.copy()
        if group_col not in df.columns and "equity" in df.columns:
            df["group"] = pd.cut(
                df["equity"],
                bins=[0, 500_000, float("inf")],
                labels=["轻量组(<50万)", "重量组(>=50万)"],
            )
            group_col = "group"

        if group_col not in df.columns:
            return pd.DataFrame()

        agg_cols = {}
        for col in ["profit_rate", "max_drawdown", "net_value", "credit_score", "net_profit"]:
            if col in df.columns:
                agg_cols[col] = ["count", "mean", "median", "std"]

        if not agg_cols:
            return pd.DataFrame()

        return df.groupby(group_col).agg(agg_cols)

    def company_stats(self) -> pd.DataFrame:
        """Statistics per futures company."""
        if "company" not in self.df.columns:
            return pd.DataFrame()
        df = self.df
        grp = df.groupby("company")
        result = grp.agg(
            participants=("company", "count"),
        )
        if "profit_rate" in df.columns:
            result["avg_return"] = grp["profit_rate"].mean()
            result["median_return"] = grp["profit_rate"].median()
        if "net_profit" in df.columns:
            result["total_profit"] = grp["net_profit"].sum()
            result["profitable_pct"] = grp["net_profit"].apply(lambda x: (x > 0).mean())
        return result.sort_values("participants", ascending=False)

    def top_n(self, n: int = 20, by: str = "net_profit") -> pd.DataFrame:
        """Get top N traders by specified column."""
        if by not in self.df.columns:
            return pd.DataFrame()
        return self.df.nlargest(n, by)
