"""Configuration loader for the stock sentiment strategy system."""

import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import List

import yaml


@dataclass
class StrategyConfig:
    sentiment_weight: float = 0.4
    technical_weight: float = 0.4
    volume_weight: float = 0.2
    max_position: float = 0.2
    stop_loss: float = -0.08
    news_lookback_days: int = 3


@dataclass
class AppConfig:
    finnhub_api_key: str = "YOUR_KEY"
    us_stocks: List[str] = field(default_factory=lambda: ["AAPL", "TSLA", "NVDA", "MSFT", "GOOGL"])
    cn_stocks: List[str] = field(default_factory=lambda: ["600519", "000858", "601318", "000001", "300750"])
    strategy: StrategyConfig = field(default_factory=StrategyConfig)


def load_config(config_path: str | None = None) -> AppConfig:
    """Load configuration from YAML file.

    Looks for config.yaml in the project root by default.
    """
    if config_path is None:
        config_path = os.path.join(Path(__file__).parent.parent, "config.yaml")

    if not os.path.exists(config_path):
        return AppConfig()

    with open(config_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    watchlist = raw.get("watchlist", {})
    strategy_raw = raw.get("strategy", {})

    strategy = StrategyConfig(
        sentiment_weight=strategy_raw.get("sentiment_weight", 0.4),
        technical_weight=strategy_raw.get("technical_weight", 0.4),
        volume_weight=strategy_raw.get("volume_weight", 0.2),
        max_position=strategy_raw.get("max_position", 0.2),
        stop_loss=strategy_raw.get("stop_loss", -0.08),
        news_lookback_days=strategy_raw.get("news_lookback_days", 3),
    )

    defaults = AppConfig()
    return AppConfig(
        finnhub_api_key=raw.get("finnhub_api_key", "YOUR_KEY"),
        us_stocks=watchlist.get("us_stocks", defaults.us_stocks),
        cn_stocks=watchlist.get("cn_stocks", defaults.cn_stocks),
        strategy=strategy,
    )
