import React, { useState, useCallback, useEffect, useRef } from 'react'
import type { StockAnalysis, AdviceItem, SwingData } from '../types'
import type { QuoteData } from '../api'
import { refreshAnalysis } from '../api'
import SignalBadge from './SignalBadge'
import CandlestickChart from './CandlestickChart'
import SentimentChart from './SentimentChart'
import NewsFeed from './NewsFeed'

interface Props {
  analysis: StockAnalysis
  onTrade?: () => void
  onBacktest?: () => void
  onAnalysisUpdate?: (updated: StockAnalysis) => void
}

type Tab = 'chart' | 'sentiment' | 'news' | 'breakdown'

const FULL_REFRESH_INTERVAL_MS = 60_000 // 60s for full data refresh

// ---------------------------------------------------------------------------
// Advice display helpers
// ---------------------------------------------------------------------------

const ACTION_CONFIG: Record<string, { label: string; icon: string; border: string; bg: string; text: string }> = {
  BUY: {
    label: '买入',
    icon: '▲',
    border: 'border-green-500/50',
    bg: 'bg-green-900/20',
    text: 'text-green-400',
  },
  SELL: {
    label: '卖出',
    icon: '▼',
    border: 'border-red-500/50',
    bg: 'bg-red-900/20',
    text: 'text-red-400',
  },
  HOLD: {
    label: '观望',
    icon: '■',
    border: 'border-yellow-500/30',
    bg: 'bg-yellow-900/10',
    text: 'text-yellow-400',
  },
}

function AdvicePanel({ advice, detail }: { advice: AdviceItem[]; detail: StockAnalysis['signal']['detail'] }) {
  if (!advice || advice.length === 0) return null

  // Pick the primary action (first BUY or SELL, else first item)
  const primary = advice.find(a => a.action === 'BUY' || a.action === 'SELL') || advice[0]
  const cfg = ACTION_CONFIG[primary.action] || ACTION_CONFIG.HOLD

  const crossLabel =
    detail.macd_cross === 'golden' ? '金叉' :
    detail.macd_cross === 'death' ? '死叉' : '无交叉'
  const axisLabel = detail.macd_above_zero ? '0 轴上方' : '0 轴下方'

  return (
    <div className={`mx-4 my-3 rounded-lg border ${cfg.border} ${cfg.bg} overflow-hidden`}>
      {/* Primary advice header */}
      <div className="px-4 py-2.5 flex items-center gap-3">
        <span className={`text-lg font-bold ${cfg.text}`}>{cfg.icon}</span>
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <span className={`text-sm font-bold ${cfg.text}`}>
              口诀建议：{cfg.label}
            </span>
            <span className="text-xs text-gray-500">|</span>
            <span className="text-xs text-gray-400">{primary.rule}</span>
          </div>
          <p className="text-xs text-gray-400 mt-0.5">{primary.detail}</p>
        </div>
      </div>

      {/* Indicator status bar */}
      <div className="px-4 py-2 border-t border-gray-800/30 flex items-center gap-4 flex-wrap">
        <div className="flex items-center gap-1.5">
          <span className="text-[10px] text-gray-500 uppercase tracking-wider">RSI6</span>
          <span className={`text-xs font-mono font-semibold ${
            detail.rsi6 !== null && detail.rsi6 <= 30 ? 'text-green-400' :
            detail.rsi6 !== null && detail.rsi6 >= 70 ? 'text-red-400' :
            'text-gray-300'
          }`}>
            {detail.rsi6 !== null ? detail.rsi6.toFixed(1) : 'N/A'}
          </span>
          {detail.rsi6 !== null && detail.rsi6 <= 30 && (
            <span className="text-[10px] px-1 rounded bg-green-900/40 text-green-400">超卖</span>
          )}
          {detail.rsi6 !== null && detail.rsi6 >= 70 && (
            <span className="text-[10px] px-1 rounded bg-red-900/40 text-red-400">超买</span>
          )}
        </div>

        <div className="flex items-center gap-1.5">
          <span className="text-[10px] text-gray-500 uppercase tracking-wider">MACD</span>
          <span className={`text-xs font-semibold ${
            detail.macd_cross === 'golden' ? 'text-green-400' :
            detail.macd_cross === 'death' ? 'text-red-400' :
            'text-gray-400'
          }`}>
            {crossLabel}
          </span>
        </div>

        <div className="flex items-center gap-1.5">
          <span className="text-[10px] text-gray-500 uppercase tracking-wider">位置</span>
          <span className={`text-xs font-semibold ${detail.macd_above_zero ? 'text-blue-400' : 'text-gray-400'}`}>
            {axisLabel}
          </span>
        </div>
      </div>

      {/* Additional advice items (if more than one) */}
      {advice.length > 1 && (
        <div className="px-4 py-2 border-t border-gray-800/30 space-y-1">
          {advice.slice(1).map((a, i) => {
            const c = ACTION_CONFIG[a.action] || ACTION_CONFIG.HOLD
            return (
              <div key={i} className="flex items-start gap-2">
                <span className={`text-[10px] mt-0.5 ${c.text}`}>{c.icon}</span>
                <div>
                  <span className={`text-xs font-medium ${c.text}`}>{a.rule}</span>
                  <p className="text-[11px] text-gray-500">{a.detail}</p>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Futures Swing Strategy Panel (MA5/MA20/MA60)
// ---------------------------------------------------------------------------

function SwingPanel({ swing, advice }: { swing: SwingData; advice: AdviceItem[] }) {
  const isBullish = swing.trend === 'bullish'
  const hasEntry = swing.entry_price !== null

  const primary = advice.find(a => a.action === 'BUY' || a.action === 'SELL') || advice[0]
  const cfg = primary ? (ACTION_CONFIG[primary.action] || ACTION_CONFIG.HOLD) : ACTION_CONFIG.HOLD

  const crossLabel =
    swing.ma5_ma20_cross === 'golden' ? 'MA5↑MA20 金叉' :
    swing.ma5_ma20_cross === 'death' ? 'MA5↓MA20 死叉' : '无交叉'

  return (
    <div className={`mx-4 my-3 rounded-lg border ${cfg.border} ${cfg.bg} overflow-hidden`}>
      {/* Strategy header */}
      <div className="px-4 py-2 flex items-center gap-2 border-b border-gray-800/30">
        <span className="text-[10px] px-1.5 py-0.5 rounded bg-orange-900/40 text-orange-400 font-medium">
          波段策略
        </span>
        <span className="text-[10px] text-gray-500">
          六十均线定方向，五二金叉做波段
        </span>
      </div>

      {/* Primary advice */}
      {primary && (
        <div className="px-4 py-2.5 flex items-center gap-3">
          <span className={`text-lg font-bold ${cfg.text}`}>{cfg.icon}</span>
          <div className="flex-1">
            <div className="flex items-center gap-2">
              <span className={`text-sm font-bold ${cfg.text}`}>
                {cfg.label}
              </span>
              <span className="text-xs text-gray-500">|</span>
              <span className="text-xs text-gray-400">{primary.rule}</span>
            </div>
            <p className="text-xs text-gray-400 mt-0.5">{primary.detail}</p>
          </div>
        </div>
      )}

      {/* MA indicator status bar */}
      <div className="px-4 py-2 border-t border-gray-800/30 flex items-center gap-4 flex-wrap">
        <div className="flex items-center gap-1.5">
          <span className="text-[10px] text-gray-500 uppercase tracking-wider">趋势</span>
          <span className={`text-xs font-semibold ${isBullish ? 'text-green-400' : 'text-red-400'}`}>
            {isBullish ? '多头 ▲' : '空头 ▼'}
          </span>
        </div>

        {swing.ma5 !== null && (
          <div className="flex items-center gap-1">
            <span className="text-[10px] text-gray-500">MA5</span>
            <span className="text-xs font-mono text-gray-300">{swing.ma5}</span>
          </div>
        )}
        {swing.ma20 !== null && (
          <div className="flex items-center gap-1">
            <span className="text-[10px] text-gray-500">MA20</span>
            <span className="text-xs font-mono text-gray-300">{swing.ma20}</span>
          </div>
        )}
        {swing.ma60 !== null && (
          <div className="flex items-center gap-1">
            <span className="text-[10px] text-gray-500">MA60</span>
            <span className="text-xs font-mono text-yellow-400">{swing.ma60}</span>
          </div>
        )}

        <div className="flex items-center gap-1.5">
          <span className="text-[10px] text-gray-500">交叉</span>
          <span className={`text-xs font-semibold ${
            swing.ma5_ma20_cross === 'golden' ? 'text-green-400' :
            swing.ma5_ma20_cross === 'death' ? 'text-red-400' :
            'text-gray-400'
          }`}>
            {crossLabel}
          </span>
        </div>
      </div>

      {/* Entry / SL / TP row (when there's an entry signal) */}
      {hasEntry && (
        <div className="px-4 py-2 border-t border-gray-800/30 grid grid-cols-3 gap-2 text-center">
          <div>
            <p className="text-[10px] text-gray-500 mb-0.5">进场价</p>
            <p className="text-sm font-mono font-semibold text-white">
              {swing.entry_price}
            </p>
          </div>
          <div>
            <p className="text-[10px] text-gray-500 mb-0.5">止损价</p>
            <p className="text-sm font-mono font-semibold text-red-400">
              {swing.stop_loss_price}
            </p>
          </div>
          <div>
            <p className="text-[10px] text-gray-500 mb-0.5">减半目标</p>
            <p className="text-sm font-mono font-semibold text-green-400">
              {swing.take_profit_half}
            </p>
          </div>
        </div>
      )}

      {/* Additional advice items */}
      {advice.length > 1 && (
        <div className="px-4 py-2 border-t border-gray-800/30 space-y-1">
          {advice.slice(1).map((a, i) => {
            const c = ACTION_CONFIG[a.action] || ACTION_CONFIG.HOLD
            return (
              <div key={i} className="flex items-start gap-2">
                <span className={`text-[10px] mt-0.5 ${c.text}`}>{c.icon}</span>
                <div>
                  <span className={`text-xs font-medium ${c.text}`}>{a.rule}</span>
                  <p className="text-[11px] text-gray-500">{a.detail}</p>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main StockCard
// ---------------------------------------------------------------------------

export default function StockCard({ analysis, onTrade, onBacktest, onAnalysisUpdate }: Props) {
  const [activeTab, setActiveTab] = useState<Tab>('chart')
  const [autoRefreshAll, setAutoRefreshAll] = useState(true)
  const [lastRefreshTime, setLastRefreshTime] = useState<string>('')
  const [refreshing, setRefreshing] = useState(false)
  const refreshTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const { signal } = analysis

  // Real-time quote updates swing strategy
  const [liveQuote, setLiveQuote] = useState<QuoteData | null>(null)
  const handleQuoteUpdate = useCallback((q: QuoteData) => setLiveQuote(q), [])

  // Use live data if available, fallback to analysis data
  const liveSwing = (liveQuote?.swing as SwingData | undefined) ?? signal.detail.swing
  const liveAdvice = liveQuote?.advice ?? signal.detail.advice
  const liveSignal = liveQuote?.signal ?? signal.signal
  const liveSignalCn = liveQuote?.signal_cn ?? signal.signal_cn
  const liveScore = liveQuote?.composite_score ?? signal.composite_score

  // Full data refresh (news + sentiment + technicals)
  const doFullRefresh = useCallback(async () => {
    if (!onAnalysisUpdate) return
    setRefreshing(true)
    try {
      const updated = await refreshAnalysis(
        analysis.ticker,
        analysis.market as 'US' | 'CN' | 'FUTURES'
      )
      onAnalysisUpdate(updated)
      const now = new Date()
      setLastRefreshTime(
        `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}:${String(now.getSeconds()).padStart(2, '0')}`
      )
    } catch (err) {
      console.error('Full refresh failed:', err)
    } finally {
      setRefreshing(false)
    }
  }, [analysis.ticker, analysis.market, onAnalysisUpdate])

  // Periodic full refresh timer
  useEffect(() => {
    if (!autoRefreshAll || !onAnalysisUpdate) {
      if (refreshTimerRef.current) clearInterval(refreshTimerRef.current)
      return
    }
    refreshTimerRef.current = setInterval(doFullRefresh, FULL_REFRESH_INTERVAL_MS)
    return () => {
      if (refreshTimerRef.current) clearInterval(refreshTimerRef.current)
    }
  }, [autoRefreshAll, doFullRefresh, onAnalysisUpdate])

  // Reset on ticker change
  useEffect(() => {
    setLiveQuote(null)
    setLastRefreshTime('')
  }, [analysis.ticker])

  const tabs: { key: Tab; label: string }[] = [
    { key: 'chart', label: 'K线图' },
    { key: 'sentiment', label: '舆情走势' },
    { key: 'news', label: `新闻 (${signal.news_count})` },
    { key: 'breakdown', label: '评分明细' },
  ]

  return (
    <div className="bg-gray-900/50 rounded-xl border border-gray-800 overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h3 className="text-base font-bold text-white">{analysis.ticker}</h3>
          <span className={`text-xs px-1.5 py-0.5 rounded ${
            analysis.market === 'US' ? 'bg-blue-900/40 text-blue-400'
            : analysis.market === 'FUTURES' ? 'bg-orange-900/40 text-orange-400'
            : 'bg-red-900/40 text-red-400'
          }`}>
            {analysis.market === 'US' ? '美股' : analysis.market === 'FUTURES' ? '期货' : 'A股'}
          </span>
          {lastRefreshTime && (
            <span className="text-[10px] text-gray-600" title="上次全量刷新">
              更新于 {lastRefreshTime}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {/* Manual full refresh */}
          <button
            onClick={doFullRefresh}
            disabled={refreshing}
            title="立即刷新全部数据（新闻+舆情+技术面）"
            className={`p-1.5 rounded-lg transition-colors ${
              refreshing
                ? 'text-blue-400 bg-blue-900/30'
                : 'text-gray-400 bg-gray-800/50 hover:bg-blue-900/30 hover:text-blue-400'
            }`}
          >
            <svg className={`w-3.5 h-3.5 ${refreshing ? 'animate-spin' : ''}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M1 4v6h6" /><path d="M23 20v-6h-6" />
              <path d="M20.49 9A9 9 0 015.64 5.64L1 10m22 4l-4.64 4.36A9 9 0 013.51 15" />
            </svg>
          </button>
          {/* Auto-refresh toggle */}
          <button
            onClick={() => setAutoRefreshAll(v => !v)}
            title={autoRefreshAll ? '暂停自动刷新（60秒/次）' : '开启自动刷新'}
            className={`p-1.5 rounded-lg text-[10px] font-medium transition-colors ${
              autoRefreshAll
                ? 'text-green-400 bg-green-900/20 hover:bg-green-900/40'
                : 'text-gray-500 bg-gray-800/50 hover:bg-gray-700/50'
            }`}
          >
            {autoRefreshAll ? 'AUTO' : 'OFF'}
          </button>
          {onTrade && (
            <button
              onClick={onTrade}
              className="text-xs px-3 py-1.5 rounded-lg bg-green-600/20 text-green-400
                hover:bg-green-600/30 border border-green-600/30 transition-colors font-medium"
            >
              交易
            </button>
          )}
          {onBacktest && (
            <button
              onClick={onBacktest}
              className="text-xs px-3 py-1.5 rounded-lg bg-purple-600/20 text-purple-400
                hover:bg-purple-600/30 border border-purple-600/30 transition-colors font-medium"
            >
              回测
            </button>
          )}
          <SignalBadge
            signal={liveSignal as any}
            signalCn={liveSignalCn}
            score={liveScore}
          />
          {(liveQuote || autoRefreshAll) && (
            <span className="text-[9px] text-green-500 animate-pulse" title="实时更新中">LIVE</span>
          )}
        </div>
      </div>

      {/* Advice panel: Swing panel for futures, standard for stocks */}
      {analysis.market === 'FUTURES' && liveSwing ? (
        <SwingPanel swing={liveSwing} advice={liveAdvice || []} />
      ) : (
        liveAdvice && liveAdvice.length > 0 && (
          <AdvicePanel advice={liveAdvice} detail={signal.detail} />
        )
      )}

      {/* Metrics row */}
      <div className="grid grid-cols-4 border-b border-gray-800">
        {[
          { label: '舆情', value: signal.sentiment_score, color: 'emerald' },
          { label: '技术面', value: signal.technical_score, color: 'blue' },
          { label: '新闻量', value: signal.news_volume_score, color: 'amber' },
          { label: '建议仓位', value: analysis.position_pct, isPercent: true, color: 'purple' },
        ].map(({ label, value, isPercent, color }) => (
          <div key={label} className="px-4 py-2.5 text-center border-r border-gray-800/50 last:border-r-0">
            <p className="text-xs text-gray-500 mb-0.5">{label}</p>
            <p className={`font-mono text-sm font-semibold ${
              isPercent
                ? (value > 0 ? 'text-purple-400' : 'text-gray-500')
                : (value > 0.3 ? 'text-green-400' : value < -0.3 ? 'text-red-400' : 'text-yellow-400')
            }`}>
              {isPercent
                ? (value > 0 ? `${value.toFixed(1)}%` : '无')
                : `${value >= 0 ? '+' : ''}${value.toFixed(3)}`
              }
            </p>
          </div>
        ))}
      </div>

      {/* Tab bar */}
      <div className="flex border-b border-gray-800">
        {tabs.map(tab => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={`flex-1 px-3 py-2 text-xs font-medium transition-colors
              ${activeTab === tab.key
                ? 'text-blue-400 border-b-2 border-blue-400 bg-blue-900/10'
                : 'text-gray-500 hover:text-gray-300'}`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="p-2">
        {activeTab === 'chart' && <CandlestickChart analysis={analysis} onQuoteUpdate={handleQuoteUpdate} />}
        {activeTab === 'sentiment' && <SentimentChart analysis={analysis} />}
        {activeTab === 'news' && <NewsFeed items={analysis.sentiment_results} />}
        {activeTab === 'breakdown' && (
          <div className="p-3">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-gray-500 border-b border-gray-800">
                  <th className="text-left py-2 font-medium">指标</th>
                  <th className="text-right py-2 font-medium">得分</th>
                </tr>
              </thead>
              <tbody className="text-gray-300">
                {[
                  { name: 'RSI(14) 指标', score: signal.detail.rsi_score },
                  { name: 'MACD 指标', score: signal.detail.macd_score },
                  { name: '均线趋势', score: signal.detail.ma_score },
                  { name: '技术面（综合）', score: signal.technical_score },
                  { name: '舆情得分', score: signal.sentiment_score },
                  { name: '新闻量得分', score: signal.news_volume_score },
                ].map(row => (
                  <tr key={row.name} className="border-b border-gray-800/30">
                    <td className="py-1.5">{row.name}</td>
                    <td className={`py-1.5 text-right font-mono text-xs ${
                      row.score > 0.3 ? 'text-green-400' :
                      row.score < -0.3 ? 'text-red-400' : 'text-yellow-400'
                    }`}>
                      {row.score >= 0 ? '+' : ''}{row.score.toFixed(4)}
                    </td>
                  </tr>
                ))}
                <tr className="font-semibold">
                  <td className="py-2 text-white">总分</td>
                  <td className={`py-2 text-right font-mono ${
                    signal.composite_score > 0.3 ? 'text-green-400' :
                    signal.composite_score < -0.3 ? 'text-red-400' : 'text-yellow-400'
                  }`}>
                    {signal.composite_score >= 0 ? '+' : ''}{signal.composite_score.toFixed(4)}
                  </td>
                </tr>
              </tbody>
            </table>

            {/* Futures swing: MA breakdown */}
            {analysis.market === 'FUTURES' && signal.detail.swing && (
              <div className="mt-4 pt-3 border-t border-gray-800">
                <p className="text-xs font-medium text-orange-400 mb-2">波段策略指标 (MA5/MA20/MA60)</p>
                <div className="grid grid-cols-4 gap-2 text-center">
                  <div className="bg-gray-800/30 rounded-lg py-2">
                    <p className="text-[10px] text-gray-500 mb-0.5">趋势</p>
                    <p className={`text-sm font-semibold ${signal.detail.swing.trend === 'bullish' ? 'text-green-400' : 'text-red-400'}`}>
                      {signal.detail.swing.trend === 'bullish' ? '多头' : '空头'}
                    </p>
                  </div>
                  <div className="bg-gray-800/30 rounded-lg py-2">
                    <p className="text-[10px] text-gray-500 mb-0.5">MA5</p>
                    <p className="text-sm font-mono font-semibold text-gray-300">
                      {signal.detail.swing.ma5 ?? 'N/A'}
                    </p>
                  </div>
                  <div className="bg-gray-800/30 rounded-lg py-2">
                    <p className="text-[10px] text-gray-500 mb-0.5">MA20</p>
                    <p className="text-sm font-mono font-semibold text-gray-300">
                      {signal.detail.swing.ma20 ?? 'N/A'}
                    </p>
                  </div>
                  <div className="bg-gray-800/30 rounded-lg py-2">
                    <p className="text-[10px] text-gray-500 mb-0.5">MA60</p>
                    <p className="text-sm font-mono font-semibold text-yellow-400">
                      {signal.detail.swing.ma60 ?? 'N/A'}
                    </p>
                  </div>
                </div>
                <div className="mt-3 p-2.5 bg-gray-800/20 rounded-lg">
                  <p className="text-[11px] text-gray-400 leading-relaxed">
                    <span className="text-orange-400 font-medium">口诀：</span>
                    六十均线定方向，五二金叉做波段。小止损，拿中段，五千只做一手单。
                  </p>
                </div>
              </div>
            )}

            {/* RSI6 / MACD raw values in breakdown */}
            <div className="mt-4 pt-3 border-t border-gray-800">
              <p className="text-xs font-medium text-gray-400 mb-2">
                {analysis.market === 'FUTURES' ? '辅助指标' : '口诀指标原始值'}
              </p>
              <div className="grid grid-cols-3 gap-3 text-center">
                <div className="bg-gray-800/30 rounded-lg py-2">
                  <p className="text-[10px] text-gray-500 mb-0.5">RSI6</p>
                  <p className={`text-sm font-mono font-semibold ${
                    signal.detail.rsi6 !== null && signal.detail.rsi6 <= 30 ? 'text-green-400' :
                    signal.detail.rsi6 !== null && signal.detail.rsi6 >= 70 ? 'text-red-400' :
                    'text-gray-300'
                  }`}>
                    {signal.detail.rsi6 !== null ? signal.detail.rsi6.toFixed(1) : 'N/A'}
                  </p>
                </div>
                <div className="bg-gray-800/30 rounded-lg py-2">
                  <p className="text-[10px] text-gray-500 mb-0.5">MACD 交叉</p>
                  <p className={`text-sm font-semibold ${
                    signal.detail.macd_cross === 'golden' ? 'text-green-400' :
                    signal.detail.macd_cross === 'death' ? 'text-red-400' :
                    'text-gray-400'
                  }`}>
                    {signal.detail.macd_cross === 'golden' ? '金叉' :
                     signal.detail.macd_cross === 'death' ? '死叉' : '无'}
                  </p>
                </div>
                <div className="bg-gray-800/30 rounded-lg py-2">
                  <p className="text-[10px] text-gray-500 mb-0.5">MACD 位置</p>
                  <p className={`text-sm font-semibold ${signal.detail.macd_above_zero ? 'text-blue-400' : 'text-gray-400'}`}>
                    {signal.detail.macd_above_zero ? '0 轴上' : '0 轴下'}
                  </p>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
