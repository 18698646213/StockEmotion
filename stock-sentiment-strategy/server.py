#!/usr/bin/env python3
"""FastAPI REST server wrapping StrategyEngine for the Electron desktop app.

Run with: python server.py
Or: uvicorn server:app --host 127.0.0.1 --port 8321
"""

import logging
import sys
from dataclasses import asdict
from datetime import datetime
from typing import List, Optional

import pandas as pd
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn

from src.config import load_config, AppConfig, StrategyConfig
from src.strategy.strategy import StrategyEngine
from src.trading.portfolio import Portfolio
from src.trading.trade_engine import TradeEngine
from src.trading.backtest import BacktestEngine

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
for name in ["urllib3", "httpx", "httpcore", "filelock", "transformers", "huggingface_hub"]:
    logging.getLogger(name).setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pydantic request / response models
# ---------------------------------------------------------------------------

class AnalyzeRequest(BaseModel):
    us_stocks: List[str] = []
    cn_stocks: List[str] = []
    days: int = 3
    sentiment_weight: float = 0.4
    technical_weight: float = 0.4
    volume_weight: float = 0.2


class ConfigUpdateRequest(BaseModel):
    us_stocks: Optional[List[str]] = None
    cn_stocks: Optional[List[str]] = None
    finnhub_api_key: Optional[str] = None
    sentiment_weight: Optional[float] = None
    technical_weight: Optional[float] = None
    volume_weight: Optional[float] = None
    news_lookback_days: Optional[int] = None


class NewsItemResponse(BaseModel):
    title: str
    summary: str
    source: str
    published_at: str
    ticker: str
    url: str = ""


class SentimentResultResponse(BaseModel):
    title: str
    summary: str
    score: float
    label: str
    source: str
    published_at: str
    url: str = ""


class AdviceItemResponse(BaseModel):
    action: str          # "BUY" | "SELL" | "HOLD"
    rule: str            # 口诀规则名
    detail: str          # 详细说明


class SignalDetailResponse(BaseModel):
    rsi_score: float
    macd_score: float
    ma_score: float
    weights: dict
    # 口诀规则引擎
    rsi6: Optional[float] = None
    macd_cross: str = "none"         # "golden" | "death" | "none"
    macd_above_zero: bool = False
    advice: List[AdviceItemResponse] = []


class SignalResponse(BaseModel):
    ticker: str
    sentiment_score: float
    technical_score: float
    news_volume_score: float
    composite_score: float
    signal: str
    signal_cn: str
    news_count: int
    detail: SignalDetailResponse


class PriceBarResponse(BaseModel):
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float


class StockAnalysisResponse(BaseModel):
    ticker: str
    market: str
    signal: SignalResponse
    sentiment_results: List[SentimentResultResponse]
    price_data: List[PriceBarResponse]
    position_pct: float
    timestamp: str


class ConfigResponse(BaseModel):
    finnhub_api_key: str
    us_stocks: List[str]
    cn_stocks: List[str]
    sentiment_weight: float
    technical_weight: float
    volume_weight: float
    max_position: float
    stop_loss: float
    news_lookback_days: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def stock_analysis_to_response(analysis) -> StockAnalysisResponse:
    """Convert a StockAnalysis dataclass to a JSON-serializable response."""
    sig = analysis.signal

    # Convert sentiment results
    sentiment_items = []
    for r in analysis.sentiment_results:
        news = r["news_item"]
        # Ensure summary is never empty; fall back to title
        summary = news.summary if (news.summary and news.summary.strip()) else news.title
        sentiment_items.append(SentimentResultResponse(
            title=news.title,
            summary=summary,
            score=r["score"],
            label=r["label"],
            source=news.source,
            published_at=news.published_at.isoformat(),
            url=news.url or "",
        ))

    # Convert price DataFrame to list of dicts
    price_bars = []
    if analysis.price_df is not None and not analysis.price_df.empty:
        df = analysis.price_df
        for idx, row in df.iterrows():
            price_bars.append(PriceBarResponse(
                date=idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx),
                open=round(float(row.get("open", 0)), 4),
                high=round(float(row.get("high", 0)), 4),
                low=round(float(row.get("low", 0)), 4),
                close=round(float(row.get("close", 0)), 4),
                volume=float(row.get("volume", 0)),
            ))

    # Convert signal
    signal_resp = SignalResponse(
        ticker=sig.ticker,
        sentiment_score=sig.sentiment_score,
        technical_score=sig.technical_score,
        news_volume_score=sig.news_volume_score,
        composite_score=sig.composite_score,
        signal=sig.signal,
        signal_cn=sig.signal_cn,
        news_count=sig.news_count,
        detail=SignalDetailResponse(
            rsi_score=sig.detail.get("rsi_score", 0.0),
            macd_score=sig.detail.get("macd_score", 0.0),
            ma_score=sig.detail.get("ma_score", 0.0),
            weights=sig.detail.get("weights", {}),
            rsi6=sig.detail.get("rsi6"),
            macd_cross=sig.detail.get("macd_cross", "none"),
            macd_above_zero=sig.detail.get("macd_above_zero", False),
            advice=[
                AdviceItemResponse(**a) for a in sig.detail.get("advice", [])
            ],
        ),
    )

    return StockAnalysisResponse(
        ticker=analysis.ticker,
        market=analysis.market,
        signal=signal_resp,
        sentiment_results=sentiment_items,
        price_data=price_bars,
        position_pct=analysis.position_pct,
        timestamp=analysis.timestamp.isoformat(),
    )


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="Stock Sentiment Strategy API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global config
_config = load_config()


_models_ready = False

def _preload_models_background():
    """Preload NLP models in a background thread."""
    global _models_ready
    try:
        from src.analysis.sentiment import _get_model
        logger.info("后台预加载英文 NLP 模型 (ProsusAI/finbert)...")
        _get_model("ProsusAI/finbert")
        logger.info("英文 NLP 模型加载完成")
        logger.info("后台预加载中文 NLP 模型 (uer/roberta-base-finetuned-chinanews-chinese)...")
        _get_model("uer/roberta-base-finetuned-chinanews-chinese")
        logger.info("中文 NLP 模型加载完成")
        _models_ready = True
        logger.info("所有 NLP 模型预加载完成，服务就绪")
    except Exception as e:
        _models_ready = True  # Allow analysis to proceed; models will load on demand
        logger.warning("模型预加载失败 (将在首次分析时加载): %s", e)


@app.on_event("startup")
def on_startup():
    """Start model preloading in background thread."""
    import threading
    t = threading.Thread(target=_preload_models_background, daemon=True)
    t.start()
    logger.info("NLP 模型正在后台加载，服务已启动")


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "models_ready": _models_ready,
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/api/config", response_model=ConfigResponse)
def get_config():
    return ConfigResponse(
        finnhub_api_key=_config.finnhub_api_key,
        us_stocks=_config.us_stocks,
        cn_stocks=_config.cn_stocks,
        sentiment_weight=_config.strategy.sentiment_weight,
        technical_weight=_config.strategy.technical_weight,
        volume_weight=_config.strategy.volume_weight,
        max_position=_config.strategy.max_position,
        stop_loss=_config.strategy.stop_loss,
        news_lookback_days=_config.strategy.news_lookback_days,
    )


@app.post("/api/config", response_model=ConfigResponse)
def update_config(req: ConfigUpdateRequest):
    global _config
    if req.us_stocks is not None:
        _config.us_stocks = req.us_stocks
    if req.cn_stocks is not None:
        _config.cn_stocks = req.cn_stocks
    if req.finnhub_api_key is not None:
        _config.finnhub_api_key = req.finnhub_api_key
    if req.sentiment_weight is not None:
        _config.strategy.sentiment_weight = req.sentiment_weight
    if req.technical_weight is not None:
        _config.strategy.technical_weight = req.technical_weight
    if req.volume_weight is not None:
        _config.strategy.volume_weight = req.volume_weight
    if req.news_lookback_days is not None:
        _config.strategy.news_lookback_days = req.news_lookback_days
    return get_config()


@app.post("/api/analyze", response_model=List[StockAnalysisResponse])
def analyze(req: AnalyzeRequest):
    """Run analysis on the given stock lists."""
    import time
    start_time = time.time()

    total = len(req.us_stocks) + len(req.cn_stocks)
    logger.info("=" * 60)
    logger.info("开始分析 %d 只股票 (美股: %s, A股: %s)",
                total, req.us_stocks, req.cn_stocks)

    config = AppConfig(
        finnhub_api_key=_config.finnhub_api_key,
        us_stocks=req.us_stocks,
        cn_stocks=req.cn_stocks,
        strategy=StrategyConfig(
            sentiment_weight=req.sentiment_weight,
            technical_weight=req.technical_weight,
            volume_weight=req.volume_weight,
            max_position=_config.strategy.max_position,
            stop_loss=_config.strategy.stop_loss,
            news_lookback_days=req.days,
        ),
    )

    engine = StrategyEngine(config)
    results = engine.analyze_all()

    elapsed = time.time() - start_time
    logger.info("分析完成，共 %d 个结果，耗时 %.1f 秒", len(results), elapsed)
    logger.info("=" * 60)
    return [stock_analysis_to_response(r) for r in results]


@app.post("/api/analyze/{ticker}", response_model=StockAnalysisResponse)
def analyze_single(ticker: str, market: str = "US"):
    """Analyze a single stock."""
    engine = StrategyEngine(_config)
    if market.upper() == "CN":
        result = engine.analyze_cn_stock(ticker)
    else:
        result = engine.analyze_us_stock(ticker)
    return stock_analysis_to_response(result)


class PriceRequest(BaseModel):
    ticker: str
    market: str = "US"            # "US" or "CN"
    interval: str = "daily"       # 1m, 5m, 15m, daily, weekly, monthly
    period_days: int = 120


@app.post("/api/price", response_model=List[PriceBarResponse])
def get_price(req: PriceRequest):
    """Fetch price data for a given ticker with flexible interval."""
    from src.data.price_us import fetch_us_price
    from src.data.price_cn import fetch_cn_price

    logger.info("获取行情: %s (%s) interval=%s period=%d天",
                req.ticker, req.market, req.interval, req.period_days)

    if req.market.upper() == "CN":
        df = fetch_cn_price(req.ticker, period_days=req.period_days, interval=req.interval)
    else:
        df = fetch_us_price(req.ticker, period_days=req.period_days, interval=req.interval)

    bars = []
    if df is not None and not df.empty:
        for idx, row in df.iterrows():
            # For intraday data, include time in the date string
            if hasattr(idx, "strftime"):
                if req.interval in ("1m", "5m", "15m"):
                    date_str = idx.strftime("%Y-%m-%d %H:%M")
                else:
                    date_str = idx.strftime("%Y-%m-%d")
            else:
                date_str = str(idx)
            bars.append(PriceBarResponse(
                date=date_str,
                open=round(float(row.get("open", 0)), 4),
                high=round(float(row.get("high", 0)), 4),
                low=round(float(row.get("low", 0)), 4),
                close=round(float(row.get("close", 0)), 4),
                volume=float(row.get("volume", 0)),
            ))

    logger.info("返回 %d 条行情数据", len(bars))
    return bars


# ---------------------------------------------------------------------------
# Trading: global portfolio & trade engine
# ---------------------------------------------------------------------------

_portfolio = Portfolio.load()
_trade_engine = TradeEngine(_portfolio)


class TradeRequest(BaseModel):
    ticker: str
    market: str = "US"     # 'US' or 'CN'
    action: str = "BUY"    # 'BUY' or 'SELL'
    shares: int = 100
    price: float = 0.0


class SignalTradeRequest(BaseModel):
    ticker: str
    market: str = "US"
    signal: str = "BUY"                # STRONG_BUY | BUY | HOLD | SELL | STRONG_SELL
    composite_score: float = 0.0
    position_pct: float = 0.0
    price: float = 0.0


class ResetPortfolioRequest(BaseModel):
    initial_capital: float = 100_000.0


class BacktestRequest(BaseModel):
    ticker: str
    market: str = "US"
    start_date: str = ""
    end_date: str = ""
    initial_capital: float = 100_000.0


class TradeResultResponse(BaseModel):
    success: bool
    error_msg: str = ""
    trade: Optional[dict] = None
    fee_detail: Optional[dict] = None


@app.get("/api/portfolio")
def get_portfolio():
    """Get current portfolio summary."""
    # Try to get current prices for unrealized PnL
    price_map = {}
    for ticker, pos in _portfolio.positions.items():
        if pos.shares > 0:
            try:
                if pos.market == "CN":
                    from src.data.price_cn import fetch_cn_price
                    df = fetch_cn_price(ticker, period_days=5, interval="daily")
                else:
                    from src.data.price_us import fetch_us_price
                    df = fetch_us_price(ticker, period_days=5, interval="daily")
                if df is not None and not df.empty:
                    price_map[ticker] = float(df.iloc[-1]["close"])
            except Exception:
                pass  # Use avg_cost as fallback

    return _portfolio.get_summary(price_map)


@app.post("/api/portfolio/reset")
def reset_portfolio(req: ResetPortfolioRequest):
    """Reset portfolio to initial state."""
    global _portfolio, _trade_engine
    _portfolio = Portfolio(initial_capital=req.initial_capital)
    _portfolio.save()
    _trade_engine = TradeEngine(_portfolio)
    logger.info("Portfolio reset with capital=%.0f", req.initial_capital)
    return _portfolio.get_summary()


@app.post("/api/trade", response_model=TradeResultResponse)
def execute_trade(req: TradeRequest):
    """Execute a manual buy/sell trade."""
    logger.info("手动交易: %s %s x%d @%.2f (%s)",
                req.action, req.ticker, req.shares, req.price, req.market)

    if req.action.upper() == "BUY":
        result = _trade_engine.execute_buy(
            req.ticker, req.market, req.shares, req.price, "manual")
    elif req.action.upper() == "SELL":
        result = _trade_engine.execute_sell(
            req.ticker, req.market, req.shares, req.price, "manual")
    else:
        return TradeResultResponse(success=False, error_msg=f"未知操作: {req.action}")

    return TradeResultResponse(
        success=result.success,
        error_msg=result.error_msg,
        trade=_trade_to_dict(result.trade) if result.trade else None,
        fee_detail=_fee_to_dict(result.fee_detail) if result.fee_detail else None,
    )


@app.post("/api/trade/signal", response_model=TradeResultResponse)
def execute_signal_trade(req: SignalTradeRequest):
    """Execute a trade based on analysis signal."""
    logger.info("信号交易: %s %s signal=%s score=%.3f pct=%.1f price=%.2f",
                req.ticker, req.market, req.signal, req.composite_score,
                req.position_pct, req.price)

    result = _trade_engine.execute_signal_trade(
        req.ticker, req.market, req.signal,
        req.composite_score, req.position_pct, req.price,
    )

    return TradeResultResponse(
        success=result.success,
        error_msg=result.error_msg,
        trade=_trade_to_dict(result.trade) if result.trade else None,
        fee_detail=_fee_to_dict(result.fee_detail) if result.fee_detail else None,
    )


@app.get("/api/trades")
def get_trades():
    """Get trade history."""
    from dataclasses import asdict
    return [asdict(t) for t in reversed(_portfolio.trades)]


@app.post("/api/backtest")
def run_backtest(req: BacktestRequest):
    """Run a historical backtest."""
    logger.info("回测请求: %s (%s) %s ~ %s, capital=%.0f",
                req.ticker, req.market, req.start_date, req.end_date, req.initial_capital)

    engine = BacktestEngine(initial_capital=req.initial_capital)
    report = engine.run(req.ticker, req.market, req.start_date, req.end_date)

    from dataclasses import asdict
    return asdict(report)


def _trade_to_dict(trade) -> dict:
    """Convert a Trade dataclass to a plain dict."""
    from dataclasses import asdict
    return asdict(trade)


def _fee_to_dict(fee) -> dict:
    """Convert a CommissionDetail to a plain dict."""
    from dataclasses import asdict
    return asdict(fee)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8321
    logger.info("Starting FastAPI server on http://127.0.0.1:%d", port)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
