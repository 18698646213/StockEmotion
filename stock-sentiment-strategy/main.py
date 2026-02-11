#!/usr/bin/env python3
"""CLI entry point for the stock sentiment strategy system.

Usage:
    python main.py                           # Analyze default watchlist
    python main.py --us AAPL TSLA            # Analyze specific US stocks
    python main.py --cn 600519 000858        # Analyze specific A-shares
    python main.py --us AAPL --cn 600519     # Both markets
    python main.py --days 5                  # Custom lookback days
    python main.py --no-details              # Summary table only
"""

import argparse
import logging
import sys

from src.config import load_config
from src.strategy.strategy import StrategyEngine
from src.output.cli_report import print_full_report


def setup_logging(verbose: bool = False) -> None:
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # Suppress noisy third-party loggers
    for name in ["urllib3", "httpx", "httpcore", "filelock", "transformers"]:
        logging.getLogger(name).setLevel(logging.WARNING)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stock News Sentiment Trading Strategy",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--us", nargs="+", metavar="TICKER", help="US stock tickers to analyze")
    parser.add_argument("--cn", nargs="+", metavar="CODE", help="A-share stock codes to analyze")
    parser.add_argument("--days", type=int, default=None, help="News lookback days (default: from config)")
    parser.add_argument("--config", type=str, default=None, help="Path to config.yaml")
    parser.add_argument("--no-details", action="store_true", help="Show summary table only")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging")

    args = parser.parse_args()
    setup_logging(args.verbose)

    # Load config
    config = load_config(args.config)

    # Override watchlist if specified
    if args.us is not None:
        config.us_stocks = args.us
    if args.cn is not None:
        config.cn_stocks = args.cn
    if args.days is not None:
        config.strategy.news_lookback_days = args.days

    # If no specific stocks given and defaults are empty, show help
    if not config.us_stocks and not config.cn_stocks:
        parser.print_help()
        sys.exit(1)

    # Run analysis
    engine = StrategyEngine(config)
    results = engine.analyze_all()

    # Output report
    print_full_report(results, show_details=not args.no_details)


if __name__ == "__main__":
    main()
