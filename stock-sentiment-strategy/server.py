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

from src.config import load_config, save_config, AppConfig, StrategyConfig, FuturesStrategyConfig, DeepSeekConfig, TqSdkConfig
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
    futures_contracts: List[str] = []
    days: int = 3
    sentiment_weight: float = 0.4
    technical_weight: float = 0.4
    volume_weight: float = 0.2
    # Separate futures strategy weights
    futures_days: int = 3
    futures_sentiment_weight: float = 0.2
    futures_technical_weight: float = 0.6
    futures_volume_weight: float = 0.2


class ConfigUpdateRequest(BaseModel):
    us_stocks: Optional[List[str]] = None
    cn_stocks: Optional[List[str]] = None
    futures_contracts: Optional[List[str]] = None
    finnhub_api_key: Optional[str] = None
    deepseek_api_key: Optional[str] = None
    deepseek_model: Optional[str] = None
    tqsdk_user: Optional[str] = None
    tqsdk_password: Optional[str] = None
    tqsdk_trade_mode: Optional[str] = None       # "sim" or "live"
    tqsdk_broker_id: Optional[str] = None
    tqsdk_broker_account: Optional[str] = None
    tqsdk_broker_password: Optional[str] = None
    # Stock strategy
    sentiment_weight: Optional[float] = None
    technical_weight: Optional[float] = None
    volume_weight: Optional[float] = None
    news_lookback_days: Optional[int] = None
    # Futures strategy
    futures_sentiment_weight: Optional[float] = None
    futures_technical_weight: Optional[float] = None
    futures_volume_weight: Optional[float] = None
    futures_news_lookback_days: Optional[int] = None


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
    ai_summary: str = ""


class AdviceItemResponse(BaseModel):
    action: str          # "BUY" | "SELL" | "HOLD"
    rule: str            # 口诀规则名
    detail: str          # 详细说明


class SwingDataResponse(BaseModel):
    """Futures swing strategy MA5/MA20/MA60 data."""
    trend: str = "neutral"            # "bullish" | "bearish" | "neutral"
    ma5: Optional[float] = None
    ma20: Optional[float] = None
    ma60: Optional[float] = None
    ma5_ma20_cross: str = "none"      # "golden" | "death" | "none"
    entry_price: Optional[float] = None
    stop_loss_price: Optional[float] = None
    take_profit_half: Optional[float] = None


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
    # 期货波段策略
    swing: Optional[SwingDataResponse] = None


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


class StrategyWeightsResponse(BaseModel):
    sentiment_weight: float
    technical_weight: float
    volume_weight: float
    max_position: float
    stop_loss: float
    news_lookback_days: int


class ConfigResponse(BaseModel):
    finnhub_api_key: str
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-chat"
    tqsdk_user: str = ""
    tqsdk_connected: bool = False
    tqsdk_trade_mode: str = "sim"
    tqsdk_broker_id: str = ""
    tqsdk_broker_account: str = ""
    us_stocks: List[str]
    cn_stocks: List[str]
    futures_contracts: List[str]
    # Stock strategy (backward compat flat fields)
    sentiment_weight: float
    technical_weight: float
    volume_weight: float
    max_position: float
    stop_loss: float
    news_lookback_days: int
    # Futures strategy
    futures_strategy: StrategyWeightsResponse


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
            ai_summary=r.get("ai_summary", ""),
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
            swing=SwingDataResponse(**sig.detail["swing"]) if sig.detail.get("swing") else None,
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

# ---------------------------------------------------------------------------
# Search cache: populated once on startup
# ---------------------------------------------------------------------------
_search_cn_stocks: list[dict] = []      # [{"code": "600519", "name": "贵州茅台"}, ...]
_search_futures: list[dict] = []        # [{"code": "C0", "name": "玉米"}, ...]


def _load_search_cache():
    """Pre-load stock/futures lists for fast search."""
    global _search_cn_stocks, _search_futures
    import threading

    def _load_cn():
        global _search_cn_stocks
        try:
            import akshare as ak
            df = ak.stock_info_a_code_name()
            _search_cn_stocks = [
                {"code": str(row["code"]), "name": str(row["name"])}
                for _, row in df.iterrows()
            ]
            logger.info("A股搜索缓存已加载: %d 条", len(_search_cn_stocks))
        except Exception as e:
            logger.warning("加载A股列表失败: %s", e)

    def _load_futures():
        global _search_futures
        try:
            from src.data.news_futures import FUTURES_DISPLAY_NAMES
            _search_futures = [
                {"code": code, "name": name}
                for code, name in FUTURES_DISPLAY_NAMES.items()
            ]
            logger.info("期货搜索缓存已加载: %d 条", len(_search_futures))
        except Exception as e:
            logger.warning("加载期货列表失败: %s", e)

    threading.Thread(target=_load_cn, daemon=True).start()
    _load_futures()


@app.on_event("startup")
def on_startup():
    import threading
    ds_key = _config.deepseek.api_key
    if ds_key:
        logger.info("DeepSeek API 已配置 (model=%s)，使用 AI 分析模式", _config.deepseek.model)
    else:
        logger.info("DeepSeek API 未配置，将回退到本地 NLP 模型（首次分析时加载）")
    _load_search_cache()
    threading.Thread(target=_build_futures_cn_names, daemon=True).start()

    # Start TqSdk service if configured
    if _config.tqsdk.user and _config.tqsdk.password:
        def _start_tq():
            try:
                from src.data.tqsdk_service import get_tq_service
                svc = get_tq_service()
                svc.start(
                    _config.tqsdk.user, _config.tqsdk.password,
                    trade_mode=_config.tqsdk.trade_mode,
                    broker_id=_config.tqsdk.broker_id,
                    broker_account=_config.tqsdk.broker_account,
                    broker_password=_config.tqsdk.broker_password,
                )
            except Exception as e:
                logger.warning("天勤量化启动失败: %s", e)
        threading.Thread(target=_start_tq, daemon=True).start()
    else:
        logger.info("天勤量化未配置，期货行情使用 akshare")

    logger.info("服务已启动")


class SearchResult(BaseModel):
    code: str
    name: str
    market: str  # "CN" / "FUTURES" / "US"


class SearchDetailItem(BaseModel):
    code: str
    name: str
    market: str
    price: float = 0
    change_pct: float = 0
    change_amt: float = 0
    volume: float = 0
    open_interest: float = 0
    amplitude: float = 0
    settlement: float = 0
    pre_settlement: float = 0
    pre_close: float = 0
    open_price: float = 0
    high: float = 0
    low: float = 0
    turnover: float = 0
    turnover_rate: float = 0


# Chinese name -> futures_zh_realtime symbol mapping
_FUTURES_CN_NAMES: dict[str, str] = {}


def _build_futures_cn_names():
    """Build reverse mapping: Chinese name -> realtime symbol for search."""
    global _FUTURES_CN_NAMES
    try:
        import akshare as ak
        marks = ak.futures_symbol_mark()
        for _, row in marks.iterrows():
            cn_name = str(row["symbol"]).strip()
            _FUTURES_CN_NAMES[cn_name] = cn_name
        logger.info("期货品种名称映射已加载: %d 条", len(_FUTURES_CN_NAMES))
    except Exception as e:
        logger.warning("加载期货品种名称映射失败: %s", e)


@app.get("/api/search", response_model=List[SearchResult])
def search_tickers(q: str = "", market: str = ""):
    """Search stocks/futures by code or name. Returns up to 20 matches."""
    query = q.strip().upper()
    if not query:
        return []

    results: list[SearchResult] = []
    mkt = market.upper()

    if mkt in ("", "CN"):
        for item in _search_cn_stocks:
            if query in item["code"] or query in item["name"].upper():
                results.append(SearchResult(code=item["code"], name=item["name"], market="CN"))
                if len(results) >= 20:
                    return results

    if mkt in ("", "FUTURES"):
        for item in _search_futures:
            if query in item["code"].upper() or query in item["name"].upper():
                results.append(SearchResult(code=item["code"], name=item["name"], market="FUTURES"))
                if len(results) >= 20:
                    return results

    if mkt in ("", "US"):
        if query.isalpha() and len(query) <= 5:
            results.append(SearchResult(code=query, name=query, market="US"))

    return results[:20]


@app.get("/api/search/detail", response_model=List[SearchDetailItem])
def search_detail(q: str = "", market: str = ""):
    """Search with detailed realtime market data for display.

    For futures: uses futures_zh_realtime to get all contracts of a commodity.
    For CN stocks: searches by name/code and fetches realtime snapshot.
    """
    import akshare as ak
    from concurrent.futures import ThreadPoolExecutor, as_completed

    query = q.strip()
    if not query:
        return []

    mkt = market.upper()
    results: list[SearchDetailItem] = []

    # --- Futures ---
    if mkt in ("", "FUTURES"):
        query_upper = query.upper()
        cn_query = query  # keep original case for Chinese matching

        # Find the Chinese commodity name to pass to futures_zh_realtime
        commodity_names: list[str] = []

        # Direct Chinese name match
        for cn_name in _FUTURES_CN_NAMES:
            if cn_query in cn_name:
                commodity_names.append(cn_name)

        # Also check FUTURES_DISPLAY_NAMES values (from news_futures.py)
        from src.data.news_futures import FUTURES_DISPLAY_NAMES
        for code, dname in FUTURES_DISPLAY_NAMES.items():
            if cn_query in dname or query_upper in code.upper():
                if dname not in commodity_names:
                    commodity_names.append(dname)

        seen_symbols = set()
        for cn_name in commodity_names[:5]:
            try:
                df = ak.futures_zh_realtime(symbol=cn_name)
                if df is not None and not df.empty:
                    for _, row in df.iterrows():
                        sym = str(row.get("symbol", ""))
                        if sym in seen_symbols or sym.endswith("0"):
                            continue
                        seen_symbols.add(sym)
                        trade = _safe_float(row.get("trade"))
                        pre_settle = _safe_float(row.get("presettlement")) or _safe_float(row.get("prevsettlement"))
                        pre_close = _safe_float(row.get("preclose"))
                        high_val = _safe_float(row.get("high"))
                        low_val = _safe_float(row.get("low"))
                        amp = round((high_val - low_val) / pre_settle * 100, 2) if pre_settle else 0
                        change_base = pre_settle or pre_close
                        change_amt = round(trade - change_base, 2) if change_base else 0

                        results.append(SearchDetailItem(
                            code=sym,
                            name=str(row.get("name", cn_name)),
                            market="FUTURES",
                            price=trade,
                            change_pct=_safe_float(row.get("changepercent")) * 100,
                            change_amt=change_amt,
                            volume=_safe_float(row.get("volume")),
                            open_interest=_safe_float(row.get("position")),
                            amplitude=amp,
                            settlement=_safe_float(row.get("settlement")),
                            pre_settlement=pre_settle,
                            pre_close=pre_close,
                            open_price=_safe_float(row.get("open")),
                            high=high_val,
                            low=low_val,
                        ))
            except Exception as e:
                logger.debug("期货实时行情获取失败 (%s): %s", cn_name, e)

    # --- A-shares ---
    if mkt in ("", "CN"):
        query_upper = query.upper()
        cn_query = query

        matches = []
        for item in _search_cn_stocks:
            if cn_query.upper() in item["name"].upper() or query_upper in item["code"]:
                matches.append(item)
                if len(matches) >= 15:
                    break

        def _fetch_cn_detail(item: dict) -> Optional[SearchDetailItem]:
            try:
                df = ak.stock_bid_ask_em(symbol=item["code"])
                if df is None or df.empty:
                    return None
                data = {str(r["item"]): r["value"] for _, r in df.iterrows()}
                price = _safe_float(data.get("最新"))
                pre_close = _safe_float(data.get("昨收"))
                high_val = _safe_float(data.get("最高"))
                low_val = _safe_float(data.get("最低"))
                change_pct = _safe_float(data.get("涨幅"))
                change_amt = _safe_float(data.get("涨跌"))
                amp = round((high_val - low_val) / pre_close * 100, 2) if pre_close else 0
                return SearchDetailItem(
                    code=item["code"],
                    name=item["name"],
                    market="CN",
                    price=price,
                    change_pct=change_pct,
                    change_amt=change_amt,
                    volume=_safe_float(data.get("总手")),
                    amplitude=amp,
                    pre_close=pre_close,
                    open_price=_safe_float(data.get("今开")),
                    high=high_val,
                    low=low_val,
                    turnover=_safe_float(data.get("金额")),
                    turnover_rate=_safe_float(data.get("换手")),
                )
            except Exception as e:
                logger.debug("A股快照获取失败 (%s): %s", item["code"], e)
                return None

        with ThreadPoolExecutor(max_workers=5) as pool:
            futures_map = {pool.submit(_fetch_cn_detail, m): m for m in matches}
            for fut in as_completed(futures_map):
                r = fut.result()
                if r:
                    results.append(r)

        cn_results = [r for r in results if r.market == "CN"]
        cn_results.sort(key=lambda x: abs(x.volume), reverse=True)

    # --- US stocks ---
    if mkt in ("", "US"):
        query_upper = query.upper()
        if query_upper.isalpha() and len(query_upper) <= 5:
            results.append(SearchDetailItem(
                code=query_upper, name=query_upper, market="US"))

    return results[:30]


def _safe_float(val, default: float = 0.0) -> float:
    """Convert a value to float safely."""
    if val is None:
        return default
    try:
        f = float(val)
        return f if f == f else default  # NaN check
    except (ValueError, TypeError):
        return default


@app.get("/api/health")
def health():
    tq_ok = False
    tq_mode = _config.tqsdk.trade_mode
    try:
        from src.data.tqsdk_service import get_tq_service
        svc = get_tq_service()
        tq_ok = svc.is_ready
        if tq_ok:
            tq_mode = svc.trade_mode
    except Exception:
        pass
    return {
        "status": "ok",
        "models_ready": True,
        "deepseek_configured": bool(_config.deepseek.api_key),
        "tqsdk_connected": tq_ok,
        "tqsdk_trade_mode": tq_mode,
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/api/config", response_model=ConfigResponse)
def get_config():
    fs = _config.futures_strategy
    tq_connected = False
    try:
        from src.data.tqsdk_service import get_tq_service
        tq_connected = get_tq_service().is_ready
    except Exception:
        pass
    return ConfigResponse(
        finnhub_api_key=_config.finnhub_api_key,
        deepseek_api_key=_config.deepseek.api_key,
        deepseek_model=_config.deepseek.model,
        tqsdk_user=_config.tqsdk.user,
        tqsdk_connected=tq_connected,
        tqsdk_trade_mode=_config.tqsdk.trade_mode,
        tqsdk_broker_id=_config.tqsdk.broker_id,
        tqsdk_broker_account=_config.tqsdk.broker_account,
        us_stocks=_config.us_stocks,
        cn_stocks=_config.cn_stocks,
        futures_contracts=_config.futures_contracts,
        sentiment_weight=_config.strategy.sentiment_weight,
        technical_weight=_config.strategy.technical_weight,
        volume_weight=_config.strategy.volume_weight,
        max_position=_config.strategy.max_position,
        stop_loss=_config.strategy.stop_loss,
        news_lookback_days=_config.strategy.news_lookback_days,
        futures_strategy=StrategyWeightsResponse(
            sentiment_weight=fs.sentiment_weight,
            technical_weight=fs.technical_weight,
            volume_weight=fs.volume_weight,
            max_position=fs.max_position,
            stop_loss=fs.stop_loss,
            news_lookback_days=fs.news_lookback_days,
        ),
    )


@app.post("/api/config", response_model=ConfigResponse)
def update_config(req: ConfigUpdateRequest):
    global _config
    if req.us_stocks is not None:
        _config.us_stocks = req.us_stocks
    if req.cn_stocks is not None:
        _config.cn_stocks = req.cn_stocks
    if req.futures_contracts is not None:
        _config.futures_contracts = req.futures_contracts
    if req.finnhub_api_key is not None:
        _config.finnhub_api_key = req.finnhub_api_key
    if req.deepseek_api_key is not None:
        _config.deepseek.api_key = req.deepseek_api_key
    if req.deepseek_model is not None:
        _config.deepseek.model = req.deepseek_model
    # TqSdk
    tq_changed = False
    if req.tqsdk_user is not None:
        _config.tqsdk.user = req.tqsdk_user
        tq_changed = True
    if req.tqsdk_password is not None:
        _config.tqsdk.password = req.tqsdk_password
        tq_changed = True
    if req.tqsdk_trade_mode is not None:
        _config.tqsdk.trade_mode = req.tqsdk_trade_mode
        tq_changed = True
    if req.tqsdk_broker_id is not None:
        _config.tqsdk.broker_id = req.tqsdk_broker_id
        tq_changed = True
    if req.tqsdk_broker_account is not None:
        _config.tqsdk.broker_account = req.tqsdk_broker_account
        tq_changed = True
    if req.tqsdk_broker_password is not None:
        _config.tqsdk.broker_password = req.tqsdk_broker_password
        tq_changed = True
    if tq_changed and _config.tqsdk.user and _config.tqsdk.password:
        import threading
        def _restart_tq():
            try:
                from src.data.tqsdk_service import get_tq_service
                svc = get_tq_service()
                svc.stop()
                import time; time.sleep(1)
                svc.start(
                    _config.tqsdk.user, _config.tqsdk.password,
                    trade_mode=_config.tqsdk.trade_mode,
                    broker_id=_config.tqsdk.broker_id,
                    broker_account=_config.tqsdk.broker_account,
                    broker_password=_config.tqsdk.broker_password,
                )
            except Exception as e:
                logger.warning("天勤量化重启失败: %s", e)
        threading.Thread(target=_restart_tq, daemon=True).start()
    # Stock strategy
    if req.sentiment_weight is not None:
        _config.strategy.sentiment_weight = req.sentiment_weight
    if req.technical_weight is not None:
        _config.strategy.technical_weight = req.technical_weight
    if req.volume_weight is not None:
        _config.strategy.volume_weight = req.volume_weight
    if req.news_lookback_days is not None:
        _config.strategy.news_lookback_days = req.news_lookback_days
    # Futures strategy
    if req.futures_sentiment_weight is not None:
        _config.futures_strategy.sentiment_weight = req.futures_sentiment_weight
    if req.futures_technical_weight is not None:
        _config.futures_strategy.technical_weight = req.futures_technical_weight
    if req.futures_volume_weight is not None:
        _config.futures_strategy.volume_weight = req.futures_volume_weight
    if req.futures_news_lookback_days is not None:
        _config.futures_strategy.news_lookback_days = req.futures_news_lookback_days
    # 持久化保存到 config.yaml
    try:
        save_config(_config)
    except Exception as e:
        logger.warning("保存配置失败: %s", e)
    return get_config()


@app.post("/api/analyze", response_model=List[StockAnalysisResponse])
def analyze(req: AnalyzeRequest):
    """Run analysis on the given stock lists."""
    import time
    start_time = time.time()

    total = len(req.us_stocks) + len(req.cn_stocks) + len(req.futures_contracts)
    logger.info("=" * 60)
    logger.info("开始分析 %d 只标的 (美股: %s, A股: %s, 期货: %s)",
                total, req.us_stocks, req.cn_stocks, req.futures_contracts)

    config = AppConfig(
        finnhub_api_key=_config.finnhub_api_key,
        deepseek=_config.deepseek,
        us_stocks=req.us_stocks,
        cn_stocks=req.cn_stocks,
        futures_contracts=req.futures_contracts,
        strategy=StrategyConfig(
            sentiment_weight=req.sentiment_weight,
            technical_weight=req.technical_weight,
            volume_weight=req.volume_weight,
            max_position=_config.strategy.max_position,
            stop_loss=_config.strategy.stop_loss,
            news_lookback_days=req.days,
        ),
        futures_strategy=FuturesStrategyConfig(
            sentiment_weight=req.futures_sentiment_weight,
            technical_weight=req.futures_technical_weight,
            volume_weight=req.futures_volume_weight,
            max_position=_config.futures_strategy.max_position,
            stop_loss=_config.futures_strategy.stop_loss,
            news_lookback_days=req.futures_days,
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
    """Analyze a single stock or futures contract."""
    engine = StrategyEngine(_config)
    if market.upper() == "CN":
        result = engine.analyze_cn_stock(ticker)
    elif market.upper() == "FUTURES":
        result = engine.analyze_futures_contract(ticker)
    else:
        result = engine.analyze_us_stock(ticker)
    return stock_analysis_to_response(result)


@app.get("/api/refresh/{ticker}", response_model=StockAnalysisResponse)
def refresh_single(ticker: str, market: str = "US"):
    """Lightweight full re-analysis for real-time dashboard refresh.

    Same pipeline as analyze_single (news + sentiment + technicals) but
    exposed as GET so the frontend can call it from a simple polling loop
    without constructing a POST body.
    """
    import time
    start = time.time()
    mkt = market.upper()
    logger.info("刷新 %s (%s)...", ticker, mkt)

    engine = StrategyEngine(_config)
    if mkt == "CN":
        result = engine.analyze_cn_stock(ticker)
    elif mkt == "FUTURES":
        result = engine.analyze_futures_contract(ticker)
    else:
        result = engine.analyze_us_stock(ticker)

    elapsed = time.time() - start
    logger.info("刷新 %s 完成，耗时 %.1f 秒", ticker, elapsed)
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
    from src.data.price_futures import fetch_futures_price

    logger.info("获取行情: %s (%s) interval=%s period=%d天",
                req.ticker, req.market, req.interval, req.period_days)

    if req.market.upper() == "CN":
        df = fetch_cn_price(req.ticker, period_days=req.period_days, interval=req.interval)
    elif req.market.upper() == "FUTURES":
        df = fetch_futures_price(req.ticker, period_days=req.period_days, interval=req.interval)
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
# Real-time quote + swing recalculation
# ---------------------------------------------------------------------------

class QuoteResponse(BaseModel):
    ticker: str
    market: str
    price: float
    change_pct: float
    high: float
    low: float
    volume: float
    timestamp: str
    swing: Optional[dict] = None
    advice: List[AdviceItemResponse] = []
    signal: str = "HOLD"
    signal_cn: str = "持有"
    composite_score: float = 0.0


# DeepSeek analysis cache for /api/quote (avoid calling AI every 10s)
# key: "ticker:market" -> {"result": dict, "ts": float}
_ds_quote_cache: dict = {}
_DS_CACHE_TTL = 300  # 5 minutes


def _get_cached_ds_analysis(ticker: str, market: str, tech_scores: dict) -> Optional[dict]:
    """Get cached DeepSeek analysis, or run a new one if stale."""
    import time
    if not _config.deepseek.api_key:
        return None

    cache_key = f"{ticker}:{market}"
    now = time.time()
    cached = _ds_quote_cache.get(cache_key)
    if cached and (now - cached["ts"]) < _DS_CACHE_TTL:
        return cached["result"]

    # Run DeepSeek analysis in this request (will be cached for subsequent polls)
    try:
        from src.data.news_futures import fetch_futures_news
        from src.data.news_cn import fetch_cn_news
        from src.data.news_us import fetch_us_news
        from src.analysis.deepseek import analyze_with_deepseek

        mkt = market.upper()
        if mkt == "FUTURES":
            news = fetch_futures_news(ticker, lookback_days=_config.futures_strategy.news_lookback_days)
            swing_data = tech_scores.get("swing")
            result = analyze_with_deepseek(
                _config.deepseek, ticker, mkt, news, tech_scores, swing_data)
        elif mkt == "CN":
            news = fetch_cn_news(ticker, lookback_days=_config.strategy.news_lookback_days)
            result = analyze_with_deepseek(
                _config.deepseek, ticker, mkt, news, tech_scores)
        else:
            news = fetch_us_news(
                ticker, api_key=_config.finnhub_api_key,
                lookback_days=_config.strategy.news_lookback_days)
            result = analyze_with_deepseek(
                _config.deepseek, ticker, mkt, news, tech_scores)

        if result:
            _ds_quote_cache[cache_key] = {"result": result, "ts": now}
            logger.info("DeepSeek quote 分析完成: %s (%s), 缓存 %ds", ticker, mkt, _DS_CACHE_TTL)
        return result
    except Exception as e:
        logger.warning("DeepSeek quote 分析失败 %s: %s", ticker, e)
        return None


@app.get("/api/quote/{ticker}")
def get_quote(ticker: str, market: str = "FUTURES"):
    """Get real-time price and recalculate swing strategy.

    Uses minute-level data for the real-time price, and daily data for
    MA5/20/60 swing signal calculation.  When DeepSeek is configured,
    also provides AI-powered advice (cached for 5 minutes).
    """
    from src.data.price_futures import fetch_futures_price
    from src.data.price_cn import fetch_cn_price
    from src.data.price_us import fetch_us_price
    from src.analysis.technical import compute_indicators, compute_futures_swing_score, compute_technical_score
    from src.analysis.signal import score_to_signal

    ticker = ticker.strip().upper()
    mkt = market.upper()

    empty = QuoteResponse(
        ticker=ticker, market=mkt,
        price=0, change_pct=0, high=0, low=0, volume=0,
        timestamp=datetime.now().isoformat(),
    )

    # --- 1. Fetch real-time price (TqSdk preferred, fallback to 1m data) ---
    realtime_price = None
    realtime_high = None
    realtime_low = None
    realtime_vol = None
    tq_quote = None

    if mkt == "FUTURES":
        try:
            from src.data.tqsdk_service import get_tq_service
            svc = get_tq_service()
            if svc.is_ready:
                tq_quote = svc.get_quote(ticker)
                if tq_quote and tq_quote.get("price", 0) > 0:
                    realtime_price = tq_quote["price"]
                    realtime_high = tq_quote.get("high", realtime_price)
                    realtime_low = tq_quote.get("low", realtime_price)
                    realtime_vol = tq_quote.get("volume", 0)
                    logger.debug("天勤实时行情: %s = %.2f", ticker, realtime_price)
        except Exception as e:
            logger.debug("天勤实时行情不可用 %s: %s", ticker, e)

    if realtime_price is None:
        try:
            if mkt == "FUTURES":
                rt_df = fetch_futures_price(ticker, period_days=2, interval="1m")
            elif mkt == "CN":
                rt_df = fetch_cn_price(ticker, period_days=2, interval="1m")
            else:
                rt_df = fetch_us_price(ticker, period_days=2, interval="1m")

            if rt_df is not None and not rt_df.empty:
                rt_last = rt_df.iloc[-1]
                realtime_price = float(rt_last["close"])
                realtime_high = float(rt_last.get("high", realtime_price))
                realtime_low = float(rt_last.get("low", realtime_price))
                realtime_vol = float(rt_last.get("volume", 0))
        except Exception as e:
            logger.debug("1m data unavailable for %s: %s", ticker, e)

    # --- 2. Fetch daily data for MA calculation ---
    if mkt == "FUTURES":
        df = fetch_futures_price(ticker, period_days=120, interval="daily")
    elif mkt == "CN":
        df = fetch_cn_price(ticker, period_days=120, interval="daily")
    else:
        df = fetch_us_price(ticker, period_days=120, interval="daily")

    if df is None or df.empty:
        if realtime_price is not None:
            empty.price = realtime_price
        return empty

    df = compute_indicators(df)
    last = df.iloc[-1]
    prev_close = float(df.iloc[-2]["close"]) if len(df) > 1 else float(last["close"])

    cur_price = realtime_price if realtime_price is not None else float(last["close"])
    change_pct = round((cur_price - prev_close) / prev_close * 100, 2) if prev_close else 0

    resp = QuoteResponse(
        ticker=ticker,
        market=mkt,
        price=cur_price,
        change_pct=change_pct,
        high=realtime_high if realtime_high is not None else float(last.get("high", cur_price)),
        low=realtime_low if realtime_low is not None else float(last.get("low", cur_price)),
        volume=realtime_vol if realtime_vol is not None else float(last.get("volume", 0)),
        timestamp=datetime.now().isoformat(),
    )

    # --- 3. Compute local technical scores (always, for real-time MA data) ---
    if mkt == "FUTURES":
        swing_scores = compute_futures_swing_score(df)
        resp.swing = swing_scores.get("swing")
    else:
        swing_scores = compute_technical_score(df)

    # --- 4. Try DeepSeek AI analysis (cached) ---
    ai = _get_cached_ds_analysis(ticker, mkt, swing_scores)

    if ai:
        # Use DeepSeek results for advice and signal
        ai_advice = ai.get("investment_advice", [])
        news_summary = ai.get("news_summary", "")
        tech_analysis = ai.get("technical_analysis", "")

        advice_items = []
        if news_summary:
            advice_items.append(AdviceItemResponse(
                action="HOLD", rule="AI新闻摘要", detail=news_summary))
        if tech_analysis:
            advice_items.append(AdviceItemResponse(
                action="HOLD", rule="AI技术解读", detail=tech_analysis))
        for a in ai_advice:
            if isinstance(a, dict):
                action = a.get("action", "HOLD")
                if action not in ("BUY", "SELL", "HOLD"):
                    action = "HOLD"
                advice_items.append(AdviceItemResponse(
                    action=action,
                    rule=a.get("rule", "AI建议"),
                    detail=a.get("detail", ""),
                ))

        resp.advice = advice_items
        resp.composite_score = max(-1.0, min(1.0, float(ai.get("composite_score", 0.0))))
        resp.signal = ai.get("signal", "HOLD")
        resp.signal_cn = ai.get("signal_cn", "持有")
    else:
        composite = swing_scores.get("composite", 0.0)
        signal_en, signal_cn = score_to_signal(composite)
        local_advice = swing_scores.get("advice", [])
        if not local_advice:
            local_advice = [{"action": "HOLD", "rule": "请配置 DeepSeek",
                             "detail": "配置 DeepSeek API Key 后可获得 AI 驱动的全面分析和交易建议"}]
        resp.advice = [AdviceItemResponse(**a) for a in local_advice]
        resp.signal = signal_en
        resp.signal_cn = signal_cn
        resp.composite_score = composite

    return resp


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
                elif pos.market == "FUTURES":
                    from src.data.price_futures import fetch_futures_price
                    df = fetch_futures_price(ticker, period_days=5, interval="daily")
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
# Quant Trading API (TqSdk + DeepSeek auto-strategy)
# ---------------------------------------------------------------------------

class AutoTradeStartRequest(BaseModel):
    contracts: List[str]
    max_lots: int = 1
    max_positions: int = 3
    atr_sl_multiplier: float = 1.5
    atr_tp_multiplier: float = 3.0
    trail_step_atr: float = 0.5
    trail_move_atr: float = 0.25
    signal_threshold: float = 0.3
    analysis_interval: int = 300
    max_risk_per_trade: float = 0.02
    max_risk_ratio: float = 0.80
    close_before_market_close: bool = True

class ManualOrderRequest(BaseModel):
    symbol: str
    direction: str        # BUY / SELL
    offset: str           # OPEN / CLOSE
    volume: int = 1
    price: float = 0      # 0 = market order


@app.get("/api/quant/account")
def quant_account():
    """Get TqSdk trading account info."""
    try:
        from src.data.tqsdk_service import get_tq_service
        svc = get_tq_service()
        configured_mode = _config.tqsdk.trade_mode or "sim"
        if not svc.is_ready:
            return {"connected": False, "trade_mode": configured_mode, "account": None, "positions": []}

        # Ensure positions are subscribed for auto-trader contracts
        from src.trading.auto_strategy import get_auto_trader
        trader = get_auto_trader()
        for sym in (trader._contracts or []):
            svc.get_quote(sym)

        acct = svc.get_account_info()
        positions = svc.get_all_positions()
        return {
            "connected": True,
            "trade_mode": svc.trade_mode,
            "account": acct,
            "positions": positions,
        }
    except Exception as e:
        logger.warning("获取量化账户失败: %s", e)
        return {"connected": False, "trade_mode": "sim", "account": None, "positions": [], "error": str(e)}


@app.get("/api/quant/positions")
def quant_positions():
    try:
        from src.data.tqsdk_service import get_tq_service
        svc = get_tq_service()
        if not svc.is_ready:
            return []
        return svc.get_all_positions()
    except Exception:
        return []


@app.post("/api/quant/order")
def quant_manual_order(req: ManualOrderRequest):
    """Place a manual order through TqSdk."""
    from src.data.tqsdk_service import get_tq_service
    svc = get_tq_service()
    if not svc.is_ready:
        return {"status": "ERROR", "error": "天勤服务未连接"}
    result = svc.place_order(
        req.symbol, req.direction.upper(), req.offset.upper(),
        req.volume, req.price)
    return result


@app.post("/api/quant/close")
def quant_close_position(symbol: str, direction: str = ""):
    """Close positions for a symbol."""
    from src.data.tqsdk_service import get_tq_service
    svc = get_tq_service()
    if not svc.is_ready:
        return {"status": "ERROR", "error": "天勤服务未连接"}
    return svc.close_position(symbol, direction.upper())


@app.get("/api/quant/trades")
def quant_trade_log():
    """Get trade execution history."""
    from src.data.tqsdk_service import get_tq_service
    svc = get_tq_service()
    log = svc.get_trade_log() if svc.is_ready else []
    # Remove non-serializable tq_order objects
    clean = []
    for entry in log:
        e = {k: v for k, v in entry.items() if k != "tq_order"}
        clean.append(e)
    return clean


@app.post("/api/quant/auto/start")
def quant_auto_start(req: AutoTradeStartRequest):
    """Start AI auto-trading strategy."""
    from src.data.tqsdk_service import get_tq_service
    from src.trading.auto_strategy import get_auto_trader, TradeConfig

    svc = get_tq_service()
    if not svc.is_ready:
        return {"status": "ERROR", "error": "天勤服务未连接，请先配置天勤账户"}

    trader = get_auto_trader()
    if trader.is_running:
        return {"status": "ERROR", "error": "自动交易已在运行中"}

    config = TradeConfig(
        max_lots=req.max_lots,
        max_positions=req.max_positions,
        atr_sl_multiplier=req.atr_sl_multiplier,
        atr_tp_multiplier=req.atr_tp_multiplier,
        trail_step_atr=req.trail_step_atr,
        trail_move_atr=req.trail_move_atr,
        signal_threshold=req.signal_threshold,
        analysis_interval=req.analysis_interval,
        max_risk_per_trade=req.max_risk_per_trade,
        max_risk_ratio=req.max_risk_ratio,
        close_before_market_close=req.close_before_market_close,
        enabled=True,
    )
    trader.start(req.contracts, config)
    return {"status": "OK", "message": f"自动交易已启动: {req.contracts}"}


@app.post("/api/quant/auto/stop")
def quant_auto_stop():
    """Stop AI auto-trading."""
    from src.trading.auto_strategy import get_auto_trader
    trader = get_auto_trader()
    trader.stop()
    return {"status": "OK", "message": "自动交易已停止"}


@app.get("/api/quant/auto/status")
def quant_auto_status():
    """Get auto-trading status and recent decisions."""
    from src.trading.auto_strategy import get_auto_trader
    from src.data.tqsdk_service import get_tq_service
    trader = get_auto_trader()
    status = trader.get_status()

    atr_values = {}
    try:
        svc = get_tq_service()
        if svc.is_ready:
            for sym in (status.get("contracts") or _config.futures_contracts or []):
                atr_val = svc.get_atr(sym)
                if atr_val > 0:
                    atr_values[sym] = round(atr_val, 2)
    except Exception:
        pass

    return {
        **status,
        "atr_values": atr_values,
        "decisions": trader.get_decisions(limit=30),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8321
    logger.info("Starting FastAPI server on http://127.0.0.1:%d", port)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
