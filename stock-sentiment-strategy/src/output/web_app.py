"""Streamlit Web dashboard for stock sentiment strategy visualization."""

import logging
from datetime import datetime
from typing import List, Optional

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from src.strategy.strategy import StockAnalysis

logger = logging.getLogger(__name__)


def create_candlestick_chart(analysis: StockAnalysis) -> Optional[go.Figure]:
    """Create a candlestick chart with technical indicators and signal markers.

    Args:
        analysis: StockAnalysis object.

    Returns:
        Plotly Figure or None if no price data.
    """
    df = analysis.price_df
    if df.empty:
        return None

    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        row_heights=[0.7, 0.3],
        subplot_titles=("Price & Moving Averages", "Volume"),
    )

    # Candlestick
    fig.add_trace(
        go.Candlestick(
            x=df.index,
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            name="Price",
            increasing_line_color="#26a69a",
            decreasing_line_color="#ef5350",
        ),
        row=1, col=1,
    )

    # Moving averages
    colors = {"ma5": "#ff9800", "ma10": "#2196f3", "ma20": "#9c27b0", "ma60": "#795548"}
    for ma_col, color in colors.items():
        if ma_col in df.columns:
            fig.add_trace(
                go.Scatter(
                    x=df.index,
                    y=df[ma_col],
                    name=ma_col.upper(),
                    line=dict(color=color, width=1),
                    opacity=0.7,
                ),
                row=1, col=1,
            )

    # Bollinger Bands
    bb_cols = [c for c in df.columns if c.startswith("BBL_") or c.startswith("BBU_") or c.startswith("BBM_")]
    for col in bb_cols:
        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=df[col],
                name=col,
                line=dict(color="gray", width=1, dash="dot"),
                opacity=0.4,
            ),
            row=1, col=1,
        )

    # Volume
    if "volume" in df.columns:
        vol_colors = [
            "#26a69a" if (df["close"].iloc[i] >= df["open"].iloc[i]) else "#ef5350"
            for i in range(len(df))
        ]
        fig.add_trace(
            go.Bar(
                x=df.index,
                y=df["volume"],
                name="Volume",
                marker_color=vol_colors,
                opacity=0.6,
            ),
            row=2, col=1,
        )

    # Signal annotation on the latest bar
    sig = analysis.signal
    last_date = df.index[-1]
    last_close = df["close"].iloc[-1]

    signal_color = {
        "STRONG_BUY": "green", "BUY": "lightgreen",
        "HOLD": "orange", "SELL": "lightsalmon", "STRONG_SELL": "red",
    }.get(sig.signal, "gray")

    fig.add_annotation(
        x=last_date,
        y=last_close,
        text=f"{sig.signal_cn}\n({sig.composite_score:+.3f})",
        showarrow=True,
        arrowhead=2,
        arrowcolor=signal_color,
        font=dict(color=signal_color, size=12),
        bgcolor="rgba(0,0,0,0.6)",
        row=1, col=1,
    )

    fig.update_layout(
        title=f"{analysis.ticker} ({analysis.market}) - Technical Analysis",
        xaxis_rangeslider_visible=False,
        height=600,
        template="plotly_dark",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )

    return fig


def create_sentiment_chart(analysis: StockAnalysis) -> Optional[go.Figure]:
    """Create a sentiment timeline chart.

    Args:
        analysis: StockAnalysis object.

    Returns:
        Plotly Figure or None if no sentiment data.
    """
    if not analysis.sentiment_results:
        return None

    # Build a daily sentiment series
    records = []
    for r in analysis.sentiment_results:
        records.append({
            "date": r["news_item"].published_at,
            "score": r["score"],
            "label": r["label"],
            "title": r["news_item"].title[:60],
        })

    df = pd.DataFrame(records)
    df = df.sort_values("date")

    fig = go.Figure()

    # Color markers by sentiment
    colors = df["label"].map({"positive": "#26a69a", "negative": "#ef5350", "neutral": "#ffa726"})

    fig.add_trace(
        go.Scatter(
            x=df["date"],
            y=df["score"],
            mode="markers+lines",
            marker=dict(color=colors, size=8),
            line=dict(color="rgba(255,255,255,0.3)", width=1),
            text=df["title"],
            hovertemplate="<b>%{text}</b><br>Score: %{y:.3f}<br>Time: %{x}<extra></extra>",
            name="Sentiment",
        )
    )

    # Reference lines
    fig.add_hline(y=0.3, line_dash="dash", line_color="green", opacity=0.5, annotation_text="Bullish threshold")
    fig.add_hline(y=-0.3, line_dash="dash", line_color="red", opacity=0.5, annotation_text="Bearish threshold")
    fig.add_hline(y=0, line_dash="dot", line_color="gray", opacity=0.3)

    fig.update_layout(
        title=f"{analysis.ticker} - News Sentiment Timeline",
        yaxis_title="Sentiment Score",
        xaxis_title="Date",
        height=400,
        template="plotly_dark",
        yaxis=dict(range=[-1.1, 1.1]),
    )

    return fig
