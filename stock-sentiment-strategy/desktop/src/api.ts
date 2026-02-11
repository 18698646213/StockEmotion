// API client for communicating with the Python FastAPI backend

import type {
  StockAnalysis, AppConfig, AnalyzeRequest,
  PortfolioSummary, TradeRecord, TradeResult,
  TradeRequest, SignalTradeRequest, BacktestRequest, BacktestReport,
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

export async function getConfig(): Promise<AppConfig> {
  return request<AppConfig>('/api/config')
}

export async function updateConfig(
  updates: Partial<AppConfig>
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
  market: 'US' | 'CN' = 'US'
): Promise<StockAnalysis> {
  return request<StockAnalysis>(
    `/api/analyze/${ticker}?market=${market}`,
    { method: 'POST', timeout: ANALYZE_TIMEOUT }
  )
}

export interface PriceRequest {
  ticker: string
  market: 'US' | 'CN'
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
