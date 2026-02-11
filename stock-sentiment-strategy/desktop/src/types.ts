// TypeScript types matching the FastAPI response schema

export interface AdviceItem {
  action: 'BUY' | 'SELL' | 'HOLD'
  rule: string
  detail: string
}

export interface SignalDetail {
  rsi_score: number
  macd_score: number
  ma_score: number
  weights: {
    sentiment: number
    technical: number
    volume: number
  }
  // 口诀规则引擎
  rsi6: number | null
  macd_cross: 'golden' | 'death' | 'none'
  macd_above_zero: boolean
  advice: AdviceItem[]
}

export interface Signal {
  ticker: string
  sentiment_score: number
  technical_score: number
  news_volume_score: number
  composite_score: number
  signal: 'STRONG_BUY' | 'BUY' | 'HOLD' | 'SELL' | 'STRONG_SELL'
  signal_cn: string
  news_count: number
  detail: SignalDetail
}

export interface SentimentResult {
  title: string
  summary: string
  score: number
  label: 'positive' | 'negative' | 'neutral'
  source: string
  published_at: string
  url: string
}

export interface PriceBar {
  date: string
  open: number
  high: number
  low: number
  close: number
  volume: number
}

export interface StockAnalysis {
  ticker: string
  market: 'US' | 'CN'
  signal: Signal
  sentiment_results: SentimentResult[]
  price_data: PriceBar[]
  position_pct: number
  timestamp: string
}

export interface AppConfig {
  finnhub_api_key: string
  us_stocks: string[]
  cn_stocks: string[]
  sentiment_weight: number
  technical_weight: number
  volume_weight: number
  max_position: number
  stop_loss: number
  news_lookback_days: number
}

export interface AnalyzeRequest {
  us_stocks: string[]
  cn_stocks: string[]
  days: number
  sentiment_weight: number
  technical_weight: number
  volume_weight: number
}

// ---------------------------------------------------------------------------
// Trading / Portfolio types
// ---------------------------------------------------------------------------

export interface Position {
  ticker: string
  market: 'US' | 'CN'
  shares: number
  avg_cost: number
  current_price: number
  unrealized_pnl: number
  unrealized_pnl_pct: number
  sellable_shares: number
}

export interface TradeRecord {
  id: string
  ticker: string
  market: 'US' | 'CN'
  action: 'BUY' | 'SELL'
  shares: number
  price: number
  amount: number
  commission: number
  stamp_tax: number
  transfer_fee: number
  total_fee: number
  timestamp: string
  signal_source: 'manual' | 'signal' | 'backtest'
}

export interface PortfolioSummary {
  initial_capital: number
  cash: number
  market_value: number
  total_value: number
  total_pnl: number
  total_pnl_pct: number
  realized_pnl: number
  unrealized_pnl: number
  positions: Position[]
  win_rate: number
  trade_count: number
}

export interface TradeRequest {
  ticker: string
  market: 'US' | 'CN'
  action: 'BUY' | 'SELL'
  shares: number
  price: number
}

export interface SignalTradeRequest {
  ticker: string
  market: 'US' | 'CN'
  signal: string
  composite_score: number
  position_pct: number
  price: number
}

export interface TradeResult {
  success: boolean
  error_msg: string
  trade: TradeRecord | null
  fee_detail: {
    commission: number
    stamp_tax: number
    transfer_fee: number
    total: number
  } | null
}

export interface BacktestRequest {
  ticker: string
  market: 'US' | 'CN'
  start_date: string
  end_date: string
  initial_capital: number
}

export interface BacktestMetrics {
  total_return: number
  annual_return: number
  max_drawdown: number
  sharpe_ratio: number
  win_rate: number
  profit_loss_ratio: number
  total_trades: number
}

export interface BacktestReport {
  ticker: string
  market: 'US' | 'CN'
  start_date: string
  end_date: string
  initial_capital: number
  metrics: BacktestMetrics
  trades: TradeRecord[]
  equity_curve: { date: string; value: number }[]
  buy_sell_points: { date: string; action: string; price: number }[]
  price_data: PriceBar[]
}

export type ActiveView = 'analysis' | 'portfolio' | 'backtest'

export type SignalType = Signal['signal']

export const SIGNAL_COLORS: Record<SignalType, string> = {
  STRONG_BUY: '#16a34a',
  BUY: '#22c55e',
  HOLD: '#f59e0b',
  SELL: '#ef4444',
  STRONG_SELL: '#dc2626',
}

export const SIGNAL_BG_COLORS: Record<SignalType, string> = {
  STRONG_BUY: 'bg-green-900/50',
  BUY: 'bg-green-800/30',
  HOLD: 'bg-yellow-900/30',
  SELL: 'bg-red-800/30',
  STRONG_SELL: 'bg-red-900/50',
}
