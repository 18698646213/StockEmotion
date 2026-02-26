"""Plotly chart generators for competition data analysis."""

import logging
from typing import Any

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

logger = logging.getLogger(__name__)


class CompetitionCharts:
    """Generate competition analysis charts using Plotly."""

    COLORS = px.colors.qualitative.Set2

    @staticmethod
    def return_distribution(
        df: pd.DataFrame,
        col: str = "profit_rate",
        title: str = "收益率分布",
    ) -> go.Figure:
        """Histogram of return distribution with KDE overlay."""
        s = pd.to_numeric(df[col], errors="coerce").dropna()
        fig = go.Figure()
        fig.add_trace(go.Histogram(
            x=s, nbinsx=50, name="频数",
            marker_color="steelblue", opacity=0.75,
        ))
        fig.add_vline(x=0, line_dash="dash", line_color="red", annotation_text="零线")
        fig.add_vline(
            x=float(s.median()), line_dash="dot", line_color="green",
            annotation_text=f"中位数={s.median():.1f}%",
        )
        fig.update_layout(
            title=title, xaxis_title="收益率 (%)", yaxis_title="人数",
            template="plotly_white",
        )
        return fig

    @staticmethod
    def risk_return_scatter(
        df: pd.DataFrame,
        x_col: str = "max_drawdown",
        y_col: str = "profit_rate",
        size_col: str | None = "equity",
        title: str = "风险收益散点图",
    ) -> go.Figure:
        """Scatter plot: drawdown vs return, sized by equity."""
        plot_df = df[[c for c in [x_col, y_col, size_col, "nickname"] if c and c in df.columns]].dropna()
        if plot_df.empty:
            return go.Figure()

        hover = plot_df["nickname"] if "nickname" in plot_df.columns else None
        fig = go.Figure()

        marker_kwargs: dict[str, Any] = {"color": plot_df[y_col], "colorscale": "RdYlGn", "showscale": True}
        if size_col and size_col in plot_df.columns:
            sizes = plot_df[size_col]
            normalized = (sizes - sizes.min()) / (sizes.max() - sizes.min() + 1) * 20 + 5
            marker_kwargs["size"] = normalized

        fig.add_trace(go.Scatter(
            x=plot_df[x_col], y=plot_df[y_col],
            mode="markers",
            marker=marker_kwargs,
            text=hover,
            hovertemplate="<b>%{text}</b><br>最大回撤: %{x:.1f}%<br>收益率: %{y:.1f}%<extra></extra>",
        ))
        fig.add_hline(y=0, line_dash="dash", line_color="gray")
        fig.update_layout(
            title=title,
            xaxis_title="最大回撤 (%)",
            yaxis_title="收益率 (%)",
            template="plotly_white",
        )
        return fig

    @staticmethod
    def nav_curves(
        nav_df: pd.DataFrame,
        title: str = "净值曲线对比",
    ) -> go.Figure:
        """Line chart of net value over time for multiple traders."""
        fig = go.Figure()
        for col in nav_df.columns:
            fig.add_trace(go.Scatter(
                x=nav_df.index, y=nav_df[col],
                mode="lines+markers", name=col,
            ))
        fig.add_hline(y=1.0, line_dash="dash", line_color="gray", annotation_text="基准线")
        fig.update_layout(
            title=title, xaxis_title="时间周期", yaxis_title="累计净值",
            template="plotly_white", hovermode="x unified",
        )
        return fig

    @staticmethod
    def rank_heatmap(
        rank_df: pd.DataFrame,
        title: str = "排名变化热力图",
    ) -> go.Figure:
        """Heatmap showing rank changes over time."""
        if rank_df.empty:
            return go.Figure()
        fig = go.Figure(data=go.Heatmap(
            z=rank_df.values,
            x=rank_df.columns.tolist(),
            y=rank_df.index.tolist(),
            colorscale="RdYlGn_r",
            text=rank_df.values,
            texttemplate="%{text}",
            hovertemplate="选手: %{y}<br>周期: %{x}<br>排名: %{z}<extra></extra>",
        ))
        fig.update_layout(
            title=title, xaxis_title="时间周期", yaxis_title="选手",
            template="plotly_white", height=max(400, len(rank_df) * 25),
        )
        return fig

    @staticmethod
    def company_bar(
        company_df: pd.DataFrame,
        top_n: int = 20,
        title: str = "期货公司参赛统计",
    ) -> go.Figure:
        """Bar chart of participants per futures company."""
        if "participants" not in company_df.columns:
            return go.Figure()
        top = company_df.nlargest(top_n, "participants")
        fig = go.Figure(go.Bar(
            x=top["participants"], y=top.index,
            orientation="h", marker_color="steelblue",
            text=top["participants"], textposition="auto",
        ))
        fig.update_layout(
            title=title, xaxis_title="参赛人数", yaxis_title="期货公司",
            template="plotly_white", height=max(400, top_n * 30),
            yaxis=dict(autorange="reversed"),
        )
        return fig

    @staticmethod
    def equity_pie(
        df: pd.DataFrame,
        title: str = "资金规模分布",
    ) -> go.Figure:
        """Pie chart of equity size distribution."""
        if "equity" not in df.columns:
            return go.Figure()
        s = pd.to_numeric(df["equity"], errors="coerce").dropna()
        bins = [0, 100_000, 500_000, 1_000_000, 5_000_000, float("inf")]
        labels = ["<10万", "10-50万", "50-100万", "100-500万", ">500万"]
        cats = pd.cut(s, bins=bins, labels=labels)
        counts = cats.value_counts().sort_index()

        fig = go.Figure(go.Pie(
            labels=counts.index.tolist(),
            values=counts.values.tolist(),
            hole=0.3,
            textinfo="label+percent",
        ))
        fig.update_layout(title=title, template="plotly_white")
        return fig

    @staticmethod
    def market_overview(
        overview_df: pd.DataFrame,
        title: str = "市场概况趋势",
    ) -> go.Figure:
        """Multi-panel overview: participation, median return, drawdown."""
        if overview_df.empty:
            return go.Figure()

        panels = []
        if "participants" in overview_df.columns:
            panels.append(("participants", "参赛人数"))
        if "median_return" in overview_df.columns:
            panels.append(("median_return", "中位数收益率 (%)"))
        if "pct_profitable" in overview_df.columns:
            panels.append(("pct_profitable", "盈利占比"))
        if "median_drawdown" in overview_df.columns:
            panels.append(("median_drawdown", "中位数回撤 (%)"))

        if not panels:
            return go.Figure()

        fig = make_subplots(
            rows=len(panels), cols=1,
            subplot_titles=[p[1] for p in panels],
            shared_xaxes=True,
        )
        for i, (col, label) in enumerate(panels, 1):
            fig.add_trace(
                go.Scatter(
                    x=overview_df.index, y=overview_df[col],
                    mode="lines+markers", name=label,
                ),
                row=i, col=1,
            )
        fig.update_layout(
            title=title, template="plotly_white",
            height=250 * len(panels), showlegend=False,
        )
        return fig

    @staticmethod
    def dashboard(
        df: pd.DataFrame,
        title: str = "期货实盘大赛分析仪表盘",
    ) -> go.Figure:
        """Comprehensive dashboard with key metrics."""
        fig = make_subplots(
            rows=2, cols=2,
            subplot_titles=["收益率分布", "风险收益", "资金规模", "Top 10 收益"],
            specs=[
                [{"type": "histogram"}, {"type": "scatter"}],
                [{"type": "pie"}, {"type": "bar"}],
            ],
        )

        if "profit_rate" in df.columns:
            pr = pd.to_numeric(df["profit_rate"], errors="coerce").dropna()
            fig.add_trace(
                go.Histogram(x=pr, nbinsx=40, marker_color="steelblue", opacity=0.7, showlegend=False),
                row=1, col=1,
            )

        if "max_drawdown" in df.columns and "profit_rate" in df.columns:
            fig.add_trace(
                go.Scatter(
                    x=pd.to_numeric(df["max_drawdown"], errors="coerce"),
                    y=pd.to_numeric(df["profit_rate"], errors="coerce"),
                    mode="markers", marker=dict(size=5, opacity=0.5), showlegend=False,
                ),
                row=1, col=2,
            )

        if "equity" in df.columns:
            s = pd.to_numeric(df["equity"], errors="coerce").dropna()
            bins = [0, 100_000, 500_000, 1_000_000, 5_000_000, float("inf")]
            labels = ["<10万", "10-50万", "50-100万", "100-500万", ">500万"]
            cats = pd.cut(s, bins=bins, labels=labels)
            counts = cats.value_counts().sort_index()
            fig.add_trace(
                go.Pie(labels=counts.index.tolist(), values=counts.values.tolist(), hole=0.3, showlegend=False),
                row=2, col=1,
            )

        if "net_profit" in df.columns and "nickname" in df.columns:
            top10 = df.nlargest(10, "net_profit")
            fig.add_trace(
                go.Bar(
                    x=top10["net_profit"], y=top10["nickname"],
                    orientation="h", marker_color="green", showlegend=False,
                ),
                row=2, col=2,
            )

        fig.update_layout(
            title=title, template="plotly_white", height=800, width=1200,
        )
        return fig
