"""CLI report output using Rich for colorful terminal tables."""

import logging
from typing import List

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.columns import Columns

from src.strategy.strategy import StockAnalysis

logger = logging.getLogger(__name__)

console = Console()


def _signal_color(signal: str) -> str:
    """Get color for a signal label."""
    colors = {
        "STRONG_BUY": "bold green",
        "BUY": "green",
        "HOLD": "yellow",
        "SELL": "red",
        "STRONG_SELL": "bold red",
    }
    return colors.get(signal, "white")


def _score_color(score: float) -> str:
    """Get color for a numerical score."""
    if score > 0.3:
        return "green"
    elif score < -0.3:
        return "red"
    return "yellow"


def _format_score(score: float) -> Text:
    """Format a score with color."""
    text = Text(f"{score:+.3f}")
    text.stylize(_score_color(score))
    return text


def print_analysis_table(results: List[StockAnalysis]) -> None:
    """Print a summary table of all stock analysis results.

    Args:
        results: List of StockAnalysis objects.
    """
    if not results:
        console.print("[yellow]No analysis results to display.[/yellow]")
        return

    # Header
    console.print()
    console.rule("[bold blue]Stock Sentiment Strategy Report[/bold blue]")
    console.print()

    # Summary table
    table = Table(
        title="Composite Analysis Results",
        show_header=True,
        header_style="bold cyan",
        show_lines=True,
        expand=True,
    )

    table.add_column("Ticker", style="bold", justify="center", width=10)
    table.add_column("Market", justify="center", width=8)
    table.add_column("Sentiment", justify="center", width=11)
    table.add_column("Technical", justify="center", width=11)
    table.add_column("News Vol.", justify="center", width=11)
    table.add_column("Composite", justify="center", width=11)
    table.add_column("Signal", justify="center", width=14)
    table.add_column("Position %", justify="center", width=11)
    table.add_column("News #", justify="center", width=8)

    for r in results:
        sig = r.signal
        signal_text = Text(f"{sig.signal_cn} ({sig.signal})")
        signal_text.stylize(_signal_color(sig.signal))

        pos_text = f"{r.position_pct:.1f}%" if r.position_pct > 0 else "-"

        table.add_row(
            r.ticker,
            r.market,
            _format_score(sig.sentiment_score),
            _format_score(sig.technical_score),
            _format_score(sig.news_volume_score),
            _format_score(sig.composite_score),
            signal_text,
            pos_text,
            str(sig.news_count),
        )

    console.print(table)
    console.print()


def print_stock_detail(analysis: StockAnalysis) -> None:
    """Print detailed analysis for a single stock.

    Args:
        analysis: StockAnalysis object.
    """
    sig = analysis.signal

    # Title
    signal_text = Text(f" {sig.signal_cn} ({sig.signal}) ")
    signal_text.stylize(f"bold {_signal_color(sig.signal)} reverse")

    console.print()
    console.rule(f"[bold]{analysis.ticker} ({analysis.market})[/bold]")
    console.print()
    console.print("  Signal: ", signal_text)
    console.print(f"  Composite Score: ", _format_score(sig.composite_score))
    console.print()

    # Score breakdown
    detail_table = Table(show_header=True, header_style="bold", box=None)
    detail_table.add_column("Component", width=20)
    detail_table.add_column("Score", justify="center", width=12)
    detail_table.add_column("Weight", justify="center", width=10)

    weights = sig.detail.get("weights", {})
    detail_table.add_row("Sentiment", _format_score(sig.sentiment_score), f"{weights.get('sentiment', 0.4):.0%}")
    detail_table.add_row("  RSI", _format_score(sig.detail.get("rsi_score", 0)), "")
    detail_table.add_row("  MACD", _format_score(sig.detail.get("macd_score", 0)), "")
    detail_table.add_row("  MA Trend", _format_score(sig.detail.get("ma_score", 0)), "")
    detail_table.add_row("Technical", _format_score(sig.technical_score), f"{weights.get('technical', 0.4):.0%}")
    detail_table.add_row("News Volume", _format_score(sig.news_volume_score), f"{weights.get('volume', 0.2):.0%}")

    console.print(Panel(detail_table, title="Score Breakdown", border_style="blue"))

    # Latest news
    if analysis.sentiment_results:
        news_table = Table(
            title=f"Latest News ({len(analysis.sentiment_results)} items)",
            show_header=True,
            header_style="bold",
            show_lines=True,
        )
        news_table.add_column("Time", width=16)
        news_table.add_column("Title", width=50)
        news_table.add_column("Sentiment", justify="center", width=12)
        news_table.add_column("Source", width=15)

        for item in analysis.sentiment_results[:10]:  # Show top 10
            news = item["news_item"]
            label = item["label"]
            score = item["score"]

            label_text = Text(f"{label} ({score:+.2f})")
            if label == "positive":
                label_text.stylize("green")
            elif label == "negative":
                label_text.stylize("red")
            else:
                label_text.stylize("yellow")

            news_table.add_row(
                news.published_at.strftime("%m-%d %H:%M"),
                news.title[:48] + ("..." if len(news.title) > 48 else ""),
                label_text,
                news.source[:14],
            )

        console.print(news_table)

    # Position recommendation
    if analysis.position_pct > 0:
        console.print(f"\n  [green]Recommended Position: {analysis.position_pct:.1f}%[/green]")
    else:
        console.print(f"\n  [yellow]Recommended Position: No new allocation[/yellow]")

    console.print()


def print_full_report(results: List[StockAnalysis], show_details: bool = True) -> None:
    """Print complete report with summary and optional details.

    Args:
        results: List of StockAnalysis objects.
        show_details: Whether to show detailed per-stock analysis.
    """
    print_analysis_table(results)

    if show_details:
        for r in results:
            print_stock_detail(r)

    # Footer
    console.rule("[dim]End of Report[/dim]")
    console.print(
        "[dim]Disclaimer: This is for educational purposes only. "
        "Not financial advice.[/dim]",
        justify="center",
    )
    console.print()
