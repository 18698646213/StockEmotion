// API client for communicating with the Python FastAPI backend

import type {
  StockAnalysis, AppConfig, AnalyzeRequest,
  PortfolioSummary, TradeRecord, TradeResult,
  TradeRequest, SignalTradeRequest, BacktestRequest, BacktestReport,
  QuantTradeLogEntry, PaginatedResult,
} from './types'

const API_BASE = 'http://127.0.0.1:8321'

// Default timeout: 10 seconds for normal requests
const DEFAULT_TIMEOUT = 10_000
// Analyze can take very long (model loading + news fetching + NLP): 10 minutes
const ANALYZE_TIMEOUT = 600_000

async function request<T>(
  path: string,
  options?: RequestInit & { timeout?: number }
): Promise<T> {
  const url = `${API_BASE}${path}`
  const timeout = options?.timeout ?? DEFAULT_TIMEOUT

  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeout)

  try {
    const res = await fetch(url, {
      headers: { 'Content-Type': 'application/json' },
      ...options,
      signal: controller.signal,
    })

    if (!res.ok) {
      const text = await res.text().catch(() => '未知错误')
      throw new Error(`接口错误 (${res.status}): ${text}`)
    }

    return res.json()
  } catch (err: any) {
    if (err.name === 'AbortError') {
      throw new Error(`请求超时 (${Math.round(timeout / 1000)}秒)，后端可能仍在处理中`)
    }
    if (err.message?.includes('Failed to fetch') || err.message?.includes('ERR_CONNECTION_REFUSED')) {
      throw new Error('无法连接到后端服务，请检查 Python 后端是否正在运行')
    }
    throw err
  } finally {
    clearTimeout(timer)
  }
}

export async function healthCheck(): Promise<boolean> {
  try {
    await request<{ status: string }>('/api/health', { timeout: 3000 })
    return true
  } catch {
    return false
  }
}

export interface TqStatus {
  tqsdk_connected: boolean
  tqsdk_trade_mode: string
}

export async function getTqStatus(): Promise<TqStatus> {
  const data = await request<TqStatus>('/api/health', { timeout: 3000 })
  return data
}

export async function getConfig(): Promise<AppConfig> {
  return request<AppConfig>('/api/config')
}

export interface ConfigUpdatePayload {
  us_stocks?: string[]
  cn_stocks?: string[]
  futures_contracts?: string[]
  finnhub_api_key?: string
  deepseek_api_key?: string
  deepseek_model?: string
  tqsdk_user?: string
  tqsdk_password?: string
  tqsdk_trade_mode?: string
  tqsdk_broker_id?: string
  tqsdk_broker_account?: string
  tqsdk_broker_password?: string
  sentiment_weight?: number
  technical_weight?: number
  volume_weight?: number
  news_lookback_days?: number
  futures_sentiment_weight?: number
  futures_technical_weight?: number
  futures_volume_weight?: number
  futures_news_lookback_days?: number
}

export async function updateConfig(
  updates: ConfigUpdatePayload
): Promise<AppConfig> {
  return request<AppConfig>('/api/config', {
    method: 'POST',
    body: JSON.stringify(updates),
  })
}

export async function analyzeStocks(
  req: AnalyzeRequest
): Promise<StockAnalysis[]> {
  return request<StockAnalysis[]>('/api/analyze', {
    method: 'POST',
    body: JSON.stringify(req),
    timeout: ANALYZE_TIMEOUT,
  })
}

export async function analyzeSingle(
  ticker: string,
  market: 'US' | 'CN' | 'FUTURES' = 'US'
): Promise<StockAnalysis> {
  return request<StockAnalysis>(
    `/api/analyze/${ticker}?market=${market}`,
    { method: 'POST', timeout: ANALYZE_TIMEOUT }
  )
}

// Lightweight full refresh (news + sentiment + technicals), 60s timeout
const REFRESH_TIMEOUT = 60_000

export async function refreshAnalysis(
  ticker: string,
  market: 'US' | 'CN' | 'FUTURES' = 'US'
): Promise<StockAnalysis> {
  return request<StockAnalysis>(
    `/api/refresh/${encodeURIComponent(ticker)}?market=${market}`,
    { timeout: REFRESH_TIMEOUT }
  )
}

export interface PriceRequest {
  ticker: string
  market: 'US' | 'CN' | 'FUTURES'
  interval: string  // '1m' | '5m' | '15m' | 'daily' | 'weekly' | 'monthly'
  period_days: number
}

export async function fetchPrice(
  req: PriceRequest
): Promise<import('./types').PriceBar[]> {
  return request<import('./types').PriceBar[]>('/api/price', {
    method: 'POST',
    body: JSON.stringify(req),
    timeout: 30_000,
  })
}

// ---------------------------------------------------------------------------
// Real-time quote
// ---------------------------------------------------------------------------

export interface QuoteData {
  ticker: string
  market: string
  price: number
  change_pct: number
  high: number
  low: number
  volume: number
  timestamp: string
  swing: import('./types').SwingData | null
  advice: import('./types').AdviceItem[]
  signal: string
  signal_cn: string
  composite_score: number
}

// ---------------------------------------------------------------------------
// Ticker search
// ---------------------------------------------------------------------------

export interface SearchResult {
  code: string
  name: string
  market: 'CN' | 'FUTURES' | 'US'
}

export interface SearchDetailItem {
  code: string
  name: string
  market: string
  price: number
  change_pct: number
  change_amt: number
  volume: number
  open_interest: number
  amplitude: number
  settlement: number
  pre_settlement: number
  pre_close: number
  open_price: number
  high: number
  low: number
  turnover: number
  turnover_rate: number
}

export async function searchTickers(
  query: string,
  market: string = ''
): Promise<SearchResult[]> {
  if (!query.trim()) return []
  return request<SearchResult[]>(
    `/api/search?q=${encodeURIComponent(query)}&market=${encodeURIComponent(market)}`,
    { timeout: 5_000 }
  )
}

export async function searchTickerDetails(
  query: string,
  market: string = ''
): Promise<SearchDetailItem[]> {
  if (!query.trim()) return []
  return request<SearchDetailItem[]>(
    `/api/search/detail?q=${encodeURIComponent(query)}&market=${encodeURIComponent(market)}`,
    { timeout: 30_000 }
  )
}

export async function fetchQuote(
  ticker: string,
  market: 'US' | 'CN' | 'FUTURES' = 'FUTURES'
): Promise<QuoteData> {
  return request<QuoteData>(
    `/api/quote/${encodeURIComponent(ticker)}?market=${market}`,
    { timeout: 15_000 }
  )
}

// ---------------------------------------------------------------------------
// Trading / Portfolio API
// ---------------------------------------------------------------------------

export async function getPortfolio(): Promise<PortfolioSummary> {
  return request<PortfolioSummary>('/api/portfolio', { timeout: 30_000 })
}

export async function resetPortfolio(
  initialCapital: number = 100_000
): Promise<PortfolioSummary> {
  return request<PortfolioSummary>('/api/portfolio/reset', {
    method: 'POST',
    body: JSON.stringify({ initial_capital: initialCapital }),
  })
}

export async function executeTrade(
  req: TradeRequest
): Promise<TradeResult> {
  return request<TradeResult>('/api/trade', {
    method: 'POST',
    body: JSON.stringify(req),
    timeout: 30_000,
  })
}

export async function executeSignalTrade(
  req: SignalTradeRequest
): Promise<TradeResult> {
  return request<TradeResult>('/api/trade/signal', {
    method: 'POST',
    body: JSON.stringify(req),
    timeout: 30_000,
  })
}

export async function getTradeHistory(): Promise<TradeRecord[]> {
  return request<TradeRecord[]>('/api/trades', { timeout: 15_000 })
}

export async function runBacktest(
  req: BacktestRequest
): Promise<BacktestReport> {
  return request<BacktestReport>('/api/backtest', {
    method: 'POST',
    body: JSON.stringify(req),
    timeout: ANALYZE_TIMEOUT,
  })
}

// ---------------------------------------------------------------------------
// Quant Trading API (TqSdk + DeepSeek)
// ---------------------------------------------------------------------------

import type { QuantAccount, QuantPosition, QuantAutoStatus, QuantDecision } from './types'

export async function getQuantAccount(): Promise<{
  connected: boolean
  trade_mode?: string
  account: QuantAccount | null
  positions: QuantPosition[]
}> {
  return request('/api/quant/account', { timeout: 10_000 })
}

export async function getQuantPositions(): Promise<QuantPosition[]> {
  return request<QuantPosition[]>('/api/quant/positions', { timeout: 10_000 })
}

export async function placeQuantOrder(params: {
  symbol: string
  direction: string
  offset: string
  volume: number
  price: number
}): Promise<Record<string, unknown>> {
  return request('/api/quant/order', {
    method: 'POST',
    body: JSON.stringify(params),
    timeout: 15_000,
  })
}

export async function closeQuantPosition(
  symbol: string, direction: string = ''
): Promise<Record<string, unknown>> {
  const qs = new URLSearchParams({ symbol })
  if (direction) qs.set('direction', direction)
  return request(`/api/quant/close?${qs}`, { method: 'POST', timeout: 15_000 })
}

export async function startAutoTrade(params: {
  contracts: string[]
  max_lots?: number
  max_positions?: number
  signal_threshold?: number
  analysis_interval?: number
  atr_sl_multiplier?: number
  atr_tp_multiplier?: number
  trail_step_atr?: number
  trail_move_atr?: number
  max_risk_per_trade?: number
  max_risk_ratio?: number
  close_before_market_close?: boolean
  strategy_mode?: string
  intraday_kline_duration?: number
  intraday_scan_interval?: number
  max_daily_loss?: number
  max_consecutive_losses?: number
}): Promise<Record<string, unknown>> {
  return request('/api/quant/auto/start', {
    method: 'POST',
    body: JSON.stringify(params),
    timeout: 10_000,
  })
}

export async function stopAutoTrade(): Promise<Record<string, unknown>> {
  return request('/api/quant/auto/stop', { method: 'POST', timeout: 10_000 })
}

export async function updateAutoContracts(action: 'add' | 'remove', symbol: string): Promise<{
  status: string; message: string; contracts: string[]
}> {
  return request('/api/quant/auto/contracts', {
    method: 'POST',
    body: JSON.stringify({ action, symbol }),
    timeout: 10_000,
  })
}

export async function getAutoTradeStatus(): Promise<QuantAutoStatus> {
  return request<QuantAutoStatus>('/api/quant/auto/status', { timeout: 10_000 })
}

export async function getAutoDecisions(page: number = 1, pageSize: number = 20): Promise<{
  items: QuantDecision[]; total: number; page: number; page_size: number
}> {
  return request(`/api/quant/auto/decisions?page=${page}&page_size=${pageSize}`, { timeout: 10_000 })
}

export async function getQuantTrades(): Promise<Record<string, unknown>[]> {
  return request('/api/quant/trades', { timeout: 10_000 })
}

export async function clearAutoDecisions(): Promise<{ status: string; message: string }> {
  return request('/api/quant/auto/decisions', { method: 'DELETE', timeout: 10_000 })
}

export async function getQuantTradeLog(params?: {
  page?: number; page_size?: number
}): Promise<PaginatedResult<QuantTradeLogEntry>> {
  const p = params?.page || 1
  const ps = params?.page_size || 50
  return request(`/api/quant/auto/trade-log?page=${p}&page_size=${ps}`, { timeout: 10_000 })
}
