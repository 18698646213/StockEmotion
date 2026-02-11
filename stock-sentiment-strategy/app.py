#!/usr/bin/env python3
"""Streamlit Web dashboard for the stock sentiment strategy system.

Run with: streamlit run app.py
"""

import logging
import streamlit as st
import pandas as pd

from src.config import load_config
from src.strategy.strategy import StrategyEngine, StockAnalysis
from src.output.web_app import create_candlestick_chart, create_sentiment_chart

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
for name in ["urllib3", "httpx", "httpcore", "filelock", "transformers"]:
    logging.getLogger(name).setLevel(logging.WARNING)


def signal_badge(signal: str, signal_cn: str, score: float) -> str:
    """Create an HTML badge for signal display."""
    colors = {
        "STRONG_BUY": ("#1b5e20", "#c8e6c9"),
        "BUY": ("#2e7d32", "#e8f5e9"),
        "HOLD": ("#e65100", "#fff3e0"),
        "SELL": ("#c62828", "#ffebee"),
        "STRONG_SELL": ("#b71c1c", "#ffcdd2"),
    }
    bg, text_bg = colors.get(signal, ("#424242", "#e0e0e0"))
    return (
        f'<div style="background-color:{text_bg};color:{bg};padding:8px 16px;'
        f'border-radius:8px;text-align:center;font-weight:bold;font-size:1.2em;">'
        f'{signal_cn} ({signal})<br>'
        f'<span style="font-size:0.8em;">Score: {score:+.3f}</span></div>'
    )


def render_stock_card(analysis: StockAnalysis) -> None:
    """Render a complete analysis card for one stock."""
    sig = analysis.signal

    st.markdown(f"### {analysis.ticker} ({analysis.market})")

    # Signal badge
    st.markdown(signal_badge(sig.signal, sig.signal_cn, sig.composite_score), unsafe_allow_html=True)
    st.markdown("")

    # Score metrics
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Sentiment", f"{sig.sentiment_score:+.3f}")
    col2.metric("Technical", f"{sig.technical_score:+.3f}")
    col3.metric("News Volume", f"{sig.news_volume_score:+.3f}")
    col4.metric("Position", f"{analysis.position_pct:.1f}%" if analysis.position_pct > 0 else "N/A")

    # Charts
    tab1, tab2, tab3 = st.tabs(["K-Line Chart", "Sentiment Timeline", "News Feed"])

    with tab1:
        fig = create_candlestick_chart(analysis)
        if fig:
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No price data available.")

    with tab2:
        fig = create_sentiment_chart(analysis)
        if fig:
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No sentiment data available.")

    with tab3:
        if analysis.sentiment_results:
            news_data = []
            for r in analysis.sentiment_results:
                news = r["news_item"]
                emoji = {"positive": "🟢", "negative": "🔴", "neutral": "🟡"}.get(r["label"], "⚪")
                news_data.append({
                    "Time": news.published_at.strftime("%Y-%m-%d %H:%M"),
                    "Sentiment": f"{emoji} {r['label']} ({r['score']:+.2f})",
                    "Title": news.title,
                    "Source": news.source,
                })
            st.dataframe(pd.DataFrame(news_data), use_container_width=True, hide_index=True)
        else:
            st.info("No news items found.")

    # Score breakdown expander
    with st.expander("Score Breakdown"):
        breakdown = {
            "Component": ["RSI", "MACD", "MA Trend", "Technical (composite)", "Sentiment", "News Volume", "**TOTAL**"],
            "Score": [
                f"{sig.detail.get('rsi_score', 0):+.4f}",
                f"{sig.detail.get('macd_score', 0):+.4f}",
                f"{sig.detail.get('ma_score', 0):+.4f}",
                f"{sig.technical_score:+.4f}",
                f"{sig.sentiment_score:+.4f}",
                f"{sig.news_volume_score:+.4f}",
                f"**{sig.composite_score:+.4f}**",
            ],
        }
        st.table(pd.DataFrame(breakdown))

    st.divider()


def main() -> None:
    st.set_page_config(
        page_title="Stock Sentiment Strategy",
        page_icon="📈",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    st.title("📈 Stock News Sentiment Trading Strategy")
    st.caption("Combining NLP sentiment analysis with technical indicators for A-shares and US stocks")

    # Sidebar configuration
    with st.sidebar:
        st.header("⚙️ Settings")

        config = load_config()

        # US stocks input
        us_input = st.text_area(
            "US Stock Tickers (one per line)",
            value="\n".join(config.us_stocks),
            height=120,
        )
        us_stocks = [s.strip().upper() for s in us_input.strip().split("\n") if s.strip()]

        # CN stocks input
        cn_input = st.text_area(
            "A-Share Codes (one per line)",
            value="\n".join(config.cn_stocks),
            height=120,
        )
        cn_stocks = [s.strip() for s in cn_input.strip().split("\n") if s.strip()]

        # Parameters
        st.subheader("Strategy Parameters")
        lookback_days = st.slider("News Lookback Days", 1, 14, config.strategy.news_lookback_days)
        sentiment_weight = st.slider("Sentiment Weight", 0.0, 1.0, config.strategy.sentiment_weight, 0.05)
        technical_weight = st.slider("Technical Weight", 0.0, 1.0, config.strategy.technical_weight, 0.05)
        volume_weight = st.slider("News Volume Weight", 0.0, 1.0, config.strategy.volume_weight, 0.05)

        # Normalize weights
        total_weight = sentiment_weight + technical_weight + volume_weight
        if total_weight > 0:
            sentiment_weight /= total_weight
            technical_weight /= total_weight
            volume_weight /= total_weight

        st.caption(f"Normalized: S={sentiment_weight:.2f} T={technical_weight:.2f} V={volume_weight:.2f}")

        analyze_btn = st.button("🚀 Run Analysis", type="primary", use_container_width=True)

    # Main content
    if analyze_btn:
        # Update config
        config.us_stocks = us_stocks
        config.cn_stocks = cn_stocks
        config.strategy.news_lookback_days = lookback_days
        config.strategy.sentiment_weight = sentiment_weight
        config.strategy.technical_weight = technical_weight
        config.strategy.volume_weight = volume_weight

        engine = StrategyEngine(config)

        with st.spinner("Analyzing stocks... This may take a minute for model loading on first run."):
            results = engine.analyze_all()

        if not results:
            st.warning("No results. Check your stock tickers and network connection.")
            return

        # Summary table
        st.subheader("📊 Summary")
        summary_data = []
        for r in results:
            sig = r.signal
            summary_data.append({
                "Ticker": r.ticker,
                "Market": r.market,
                "Sentiment": f"{sig.sentiment_score:+.3f}",
                "Technical": f"{sig.technical_score:+.3f}",
                "Composite": f"{sig.composite_score:+.3f}",
                "Signal": f"{sig.signal_cn} ({sig.signal})",
                "Position %": f"{r.position_pct:.1f}%" if r.position_pct > 0 else "-",
                "News #": sig.news_count,
            })

        st.dataframe(pd.DataFrame(summary_data), use_container_width=True, hide_index=True)
        st.divider()

        # Detailed per-stock cards
        st.subheader("📋 Detailed Analysis")
        for r in results:
            render_stock_card(r)

        # Disclaimer
        st.caption(
            "⚠️ Disclaimer: This tool is for educational and research purposes only. "
            "It does not constitute financial advice. Always do your own research."
        )

    else:
        # Welcome screen
        st.info("👈 Configure your stock watchlist in the sidebar and click **Run Analysis** to start.")

        col1, col2, col3 = st.columns(3)
        with col1:
            st.markdown("### 📰 News Sentiment")
            st.markdown("Analyzes financial news using FinBERT NLP models for both English and Chinese text.")
        with col2:
            st.markdown("### 📉 Technical Analysis")
            st.markdown("Computes RSI, MACD, Moving Averages, and Bollinger Bands for trend detection.")
        with col3:
            st.markdown("### 🎯 Composite Signal")
            st.markdown("Combines sentiment + technicals + news volume anomaly into a weighted trading signal.")


if __name__ == "__main__":
    main()
