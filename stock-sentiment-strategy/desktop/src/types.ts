// TypeScript types matching the FastAPI response schema

export type MarketType = 'US' | 'CN' | 'FUTURES'

export interface AdviceItem {
  action: 'BUY' | 'SELL' | 'HOLD'
  rule: string
  detail: string
}

export interface SwingData {
  trend: 'bullish' | 'bearish' | 'neutral'
  ma5: number | null
  ma20: number | null
  ma60: number | null
  ma5_ma20_cross: 'golden' | 'death' | 'none'
  entry_price: number | null
  stop_loss_price: number | null
  take_profit_half: number | null
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
  // 期货波段策略
  swing?: SwingData | null
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
  ai_summary: string
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
  market: MarketType
  signal: Signal
  sentiment_results: SentimentResult[]
  price_data: PriceBar[]
  position_pct: number
  timestamp: string
}

export interface StrategyWeights {
  sentiment_weight: number
  technical_weight: number
  volume_weight: number
  max_position: number
  stop_loss: number
  news_lookback_days: number
}

export interface AppConfig {
  finnhub_api_key: string
  deepseek_api_key: string
  deepseek_model: string
  tqsdk_user: string
  tqsdk_connected: boolean
  tqsdk_trade_mode: string     // "sim" or "live"
  tqsdk_broker_id: string
  tqsdk_broker_account: string
  us_stocks: string[]
  cn_stocks: string[]
  futures_contracts: string[]
  sentiment_weight: number
  technical_weight: number
  volume_weight: number
  max_position: number
  stop_loss: number
  news_lookback_days: number
  futures_strategy: StrategyWeights
}

export interface AnalyzeRequest {
  us_stocks: string[]
  cn_stocks: string[]
  futures_contracts: string[]
  days: number
  sentiment_weight: number
  technical_weight: number
  volume_weight: number
  futures_days: number
  futures_sentiment_weight: number
  futures_technical_weight: number
  futures_volume_weight: number
}

// ---------------------------------------------------------------------------
// Trading / Portfolio types
// ---------------------------------------------------------------------------

export interface Position {
  ticker: string
  market: MarketType
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
  market: MarketType
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
  market: MarketType
  action: 'BUY' | 'SELL'
  shares: number
  price: number
}

export interface SignalTradeRequest {
  ticker: string
  market: MarketType
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
  market: MarketType
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
  market: MarketType
  start_date: string
  end_date: string
  initial_capital: number
  metrics: BacktestMetrics
  trades: TradeRecord[]
  equity_curve: { date: string; value: number }[]
  buy_sell_points: { date: string; action: string; price: number }[]
  price_data: PriceBar[]
}

// ---------------------------------------------------------------------------
// Quant Trading types (TqSdk + DeepSeek auto-strategy)
// ---------------------------------------------------------------------------

export interface QuantAccount {
  balance: number
  available: number
  float_profit: number
  position_profit: number
  close_profit: number
  margin: number
  commission: number
  risk_ratio: number
  static_balance: number
}

export interface QuantPosition {
  symbol: string
  long_volume: number
  short_volume: number
  long_avg_price: number
  short_avg_price: number
  float_profit: number
}

export interface QuantDecision {
  timestamp: string
  symbol: string
  action: string
  lots: number
  price: number
  reason: string
  signal: string
  composite_score: number
  order_result: Record<string, unknown> | null
}

export interface QuantAutoStatus {
  running: boolean
  contracts: string[]
  config: {
    max_lots: number
    max_positions: number
    signal_threshold: number
    analysis_interval: number
    atr_sl_multiplier: number
    atr_tp_multiplier: number
    trail_step_atr: number
    trail_move_atr: number
  }
  managed_positions: Record<string, {
    direction: string
    entry_price: number
    atr: number
    stop_loss: number
    take_profit: number
    lots: number
  }>
  decisions_count: number
  decisions: QuantDecision[]
}

export type ActiveView = 'analysis' | 'portfolio' | 'backtest' | 'quant'

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
