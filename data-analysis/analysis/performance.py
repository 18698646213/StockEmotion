"""选手表现分析：收益分布、夏普比率、最大回撤、胜率分析."""

import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class PerformanceAnalyzer:
    """Analyze individual trader performance metrics."""

    def __init__(self, df: pd.DataFrame, risk_free_rate: float = 0.02):
        """
        Args:
            df: DataFrame with trader data (must have profit_rate, max_drawdown, etc.)
            risk_free_rate: Annual risk-free rate for Sharpe/Sortino estimation.
        """
        self.df = df.copy()
        self.risk_free_rate = risk_free_rate
        self._ensure_numeric()

    def _ensure_numeric(self) -> None:
        for col in ["profit_rate", "max_drawdown", "net_value", "credit_score",
                     "net_profit", "equity", "win_rate", "annualized_return"]:
            if col in self.df.columns:
                self.df[col] = pd.to_numeric(self.df[col], errors="coerce")

    def return_statistics(self) -> dict[str, Any]:
        """Comprehensive return statistics."""
        col = "profit_rate"
        if col not in self.df.columns:
            return {}
        s = self.df[col].dropna()
        if s.empty:
            return {}

        return {
            "count": int(len(s)),
            "mean": float(s.mean()),
            "std": float(s.std()),
            "skew": float(s.skew()),
            "kurtosis": float(s.kurtosis()),
            "min": float(s.min()),
            "max": float(s.max()),
            "percentiles": {
                "p5": float(s.quantile(0.05)),
                "p10": float(s.quantile(0.10)),
                "p25": float(s.quantile(0.25)),
                "p50": float(s.quantile(0.50)),
                "p75": float(s.quantile(0.75)),
                "p90": float(s.quantile(0.90)),
                "p95": float(s.quantile(0.95)),
            },
        }

    def estimate_sharpe(self) -> pd.Series:
        """Estimate Sharpe-like ratio from cross-sectional data.

        Uses profit_rate as cumulative return proxy.
        Sharpe ≈ (return - risk_free) / std(return).
        """
        if "profit_rate" not in self.df.columns:
            return pd.Series(dtype=float)
        returns = self.df["profit_rate"] / 100.0
        excess = returns - self.risk_free_rate
        std = returns.std()
        if std == 0:
            return pd.Series(0, index=self.df.index)
        return excess / std

    def estimate_sortino(self) -> pd.Series:
        """Estimate Sortino-like ratio (downside deviation only)."""
        if "profit_rate" not in self.df.columns:
            return pd.Series(dtype=float)
        returns = self.df["profit_rate"] / 100.0
        downside = returns[returns < self.risk_free_rate]
        downside_std = downside.std() if len(downside) > 1 else returns.std()
        if downside_std == 0:
            return pd.Series(0, index=self.df.index)
        return (returns - self.risk_free_rate) / downside_std

    def drawdown_analysis(self) -> dict[str, Any]:
        """Analyze max drawdown distribution."""
        col = "max_drawdown"
        if col not in self.df.columns:
            return {}
        s = self.df[col].dropna()
        if s.empty:
            return {}
        return {
            "count": int(len(s)),
            "mean": float(s.mean()),
            "median": float(s.median()),
            "std": float(s.std()),
            "min": float(s.min()),
            "max": float(s.max()),
            "pct_under_10": float((s < 10).mean()),
            "pct_under_20": float((s < 20).mean()),
            "pct_under_50": float((s < 50).mean()),
            "pct_over_50": float((s >= 50).mean()),
        }

    def win_rate_analysis(self) -> dict[str, Any]:
        """Analyze win rate distribution."""
        col = "win_rate"
        if col not in self.df.columns:
            return {}
        s = self.df[col].dropna()
        if s.empty:
            return {}
        return {
            "count": int(len(s)),
            "mean": float(s.mean()),
            "median": float(s.median()),
            "std": float(s.std()),
            "pct_over_50": float((s > 50).mean()),
            "pct_over_60": float((s > 60).mean()),
        }

    def risk_return_profile(self) -> pd.DataFrame:
        """Create risk-return profile for each trader."""
        cols_needed = ["nickname", "profit_rate", "max_drawdown"]
        available = [c for c in cols_needed if c in self.df.columns]
        if len(available) < 2:
            return pd.DataFrame()

        profile = self.df[available].copy()
        if "profit_rate" in profile.columns and "max_drawdown" in profile.columns:
            dd = profile["max_drawdown"].replace(0, np.nan)
            profile["return_drawdown_ratio"] = profile["profit_rate"] / dd

        if "net_value" in self.df.columns:
            profile["net_value"] = self.df["net_value"]
        if "credit_score" in self.df.columns:
            profile["credit_score"] = self.df["credit_score"]
        if "win_rate" in self.df.columns:
            profile["win_rate"] = self.df["win_rate"]

        return profile

    def top_performers(self, n: int = 20) -> pd.DataFrame:
        """Identify top performers with balanced risk-return."""
        profile = self.risk_return_profile()
        if profile.empty or "return_drawdown_ratio" not in profile.columns:
            if "profit_rate" in self.df.columns:
                return self.df.nlargest(n, "profit_rate")
            return pd.DataFrame()
        return profile.nlargest(n, "return_drawdown_ratio")

    def correlation_matrix(self) -> pd.DataFrame:
        """Correlation between performance metrics."""
        num_cols = [c for c in ["profit_rate", "max_drawdown", "net_value",
                                "credit_score", "equity", "win_rate"]
                    if c in self.df.columns]
        if len(num_cols) < 2:
            return pd.DataFrame()
        return self.df[num_cols].corr()
