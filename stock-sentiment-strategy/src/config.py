"""Configuration loader for the stock sentiment strategy system."""

import logging
import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import List

import yaml

logger = logging.getLogger(__name__)

# Default config path (project root)
_DEFAULT_CONFIG_PATH = os.path.join(Path(__file__).parent.parent, "config.yaml")


@dataclass
class StrategyConfig:
    sentiment_weight: float = 0.4
    technical_weight: float = 0.4
    volume_weight: float = 0.2
    max_position: float = 0.2
    stop_loss: float = -0.08
    news_lookback_days: int = 7


@dataclass
class FuturesStrategyConfig:
    """Futures use heavier technical weight by default (trend-following)."""
    sentiment_weight: float = 0.2
    technical_weight: float = 0.6
    volume_weight: float = 0.2
    max_position: float = 0.3
    stop_loss: float = -0.05
    news_lookback_days: int = 3


@dataclass
class DeepSeekConfig:
    api_key: str = ""
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-chat"


@dataclass
class TqSdkConfig:
    user: str = ""
    password: str = ""
    trade_mode: str = "sim"         # "sim" = 模拟盘 TqSim, "live" = 实盘 TqAccount
    broker_id: str = ""             # 实盘: 期货公司编号 (如 "H海通期货")
    broker_account: str = ""        # 实盘: 资金账号
    broker_password: str = ""       # 实盘: 交易密码


@dataclass
class AppConfig:
    finnhub_api_key: str = "YOUR_KEY"
    deepseek: DeepSeekConfig = field(default_factory=DeepSeekConfig)
    tqsdk: TqSdkConfig = field(default_factory=TqSdkConfig)
    us_stocks: List[str] = field(default_factory=lambda: ["AAPL", "TSLA", "NVDA", "MSFT", "GOOGL"])
    cn_stocks: List[str] = field(default_factory=lambda: ["600519", "000858", "601318", "000001", "300750"])
    futures_contracts: List[str] = field(default_factory=lambda: ["RB0", "CU0", "AU0", "SC0", "IF0"])
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    futures_strategy: FuturesStrategyConfig = field(default_factory=FuturesStrategyConfig)


def load_config(config_path: str | None = None) -> AppConfig:
    """Load configuration from YAML file.

    Looks for config.yaml in the project root by default.
    """
    if config_path is None:
        config_path = _DEFAULT_CONFIG_PATH

    if not os.path.exists(config_path):
        return AppConfig()

    with open(config_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    watchlist = raw.get("watchlist", {})
    strategy_raw = raw.get("strategy", {})
    futures_raw = raw.get("futures_strategy", {})

    strategy = StrategyConfig(
        sentiment_weight=strategy_raw.get("sentiment_weight", 0.4),
        technical_weight=strategy_raw.get("technical_weight", 0.4),
        volume_weight=strategy_raw.get("volume_weight", 0.2),
        max_position=strategy_raw.get("max_position", 0.2),
        stop_loss=strategy_raw.get("stop_loss", -0.08),
        news_lookback_days=strategy_raw.get("news_lookback_days", 7),
    )

    f_defaults = FuturesStrategyConfig()
    futures_strategy = FuturesStrategyConfig(
        sentiment_weight=futures_raw.get("sentiment_weight", f_defaults.sentiment_weight),
        technical_weight=futures_raw.get("technical_weight", f_defaults.technical_weight),
        volume_weight=futures_raw.get("volume_weight", f_defaults.volume_weight),
        max_position=futures_raw.get("max_position", f_defaults.max_position),
        stop_loss=futures_raw.get("stop_loss", f_defaults.stop_loss),
        news_lookback_days=futures_raw.get("news_lookback_days", f_defaults.news_lookback_days),
    )

    ds_raw = raw.get("deepseek", {})
    deepseek = DeepSeekConfig(
        api_key=ds_raw.get("api_key", ""),
        base_url=ds_raw.get("base_url", "https://api.deepseek.com"),
        model=ds_raw.get("model", "deepseek-chat"),
    )

    tq_raw = raw.get("tqsdk", {})
    tqsdk = TqSdkConfig(
        user=tq_raw.get("user", ""),
        password=tq_raw.get("password", ""),
        trade_mode=tq_raw.get("trade_mode", "sim"),
        broker_id=tq_raw.get("broker_id", ""),
        broker_account=tq_raw.get("broker_account", ""),
        broker_password=tq_raw.get("broker_password", ""),
    )

    defaults = AppConfig()
    return AppConfig(
        finnhub_api_key=raw.get("finnhub_api_key", "YOUR_KEY"),
        deepseek=deepseek,
        tqsdk=tqsdk,
        us_stocks=watchlist.get("us_stocks", defaults.us_stocks),
        cn_stocks=watchlist.get("cn_stocks", defaults.cn_stocks),
        futures_contracts=watchlist.get("futures_contracts", defaults.futures_contracts),
        strategy=strategy,
        futures_strategy=futures_strategy,
    )


def save_config(config: AppConfig, config_path: str | None = None) -> None:
    """Persist the current AppConfig back to the YAML file."""
    if config_path is None:
        config_path = _DEFAULT_CONFIG_PATH

    data = {
        "finnhub_api_key": config.finnhub_api_key,
        "deepseek": {
            "api_key": config.deepseek.api_key,
            "base_url": config.deepseek.base_url,
            "model": config.deepseek.model,
        },
        "tqsdk": {
            "user": config.tqsdk.user,
            "password": config.tqsdk.password,
            "trade_mode": config.tqsdk.trade_mode,
            "broker_id": config.tqsdk.broker_id,
            "broker_account": config.tqsdk.broker_account,
            "broker_password": config.tqsdk.broker_password,
        },
        "watchlist": {
            "us_stocks": config.us_stocks,
            "cn_stocks": config.cn_stocks,
            "futures_contracts": config.futures_contracts,
        },
        "strategy": {
            "sentiment_weight": config.strategy.sentiment_weight,
            "technical_weight": config.strategy.technical_weight,
            "volume_weight": config.strategy.volume_weight,
            "max_position": config.strategy.max_position,
            "stop_loss": config.strategy.stop_loss,
            "news_lookback_days": config.strategy.news_lookback_days,
        },
        "futures_strategy": {
            "sentiment_weight": config.futures_strategy.sentiment_weight,
            "technical_weight": config.futures_strategy.technical_weight,
            "volume_weight": config.futures_strategy.volume_weight,
            "max_position": config.futures_strategy.max_position,
            "stop_loss": config.futures_strategy.stop_loss,
            "news_lookback_days": config.futures_strategy.news_lookback_days,
        },
    }

    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    logger.info("配置已保存到 %s", config_path)
