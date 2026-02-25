import React, { useState, useEffect, useCallback, useRef } from 'react'
import Plot from 'react-plotly.js'
import type { StockAnalysis, PriceBar } from '../types'
import { SIGNAL_COLORS } from '../types'
import { fetchPrice, fetchQuote, type QuoteData } from '../api'

interface Props {
  analysis: StockAnalysis
  onQuoteUpdate?: (quote: QuoteData) => void
}

// ---------------------------------------------------------------------------
// Timeframe configuration
// ---------------------------------------------------------------------------

interface TimeframeOption {
  key: string
  label: string
  interval: string
  periodDays: number
}

const TIMEFRAMES: TimeframeOption[] = [
  { key: 'realtime', label: '分时', interval: '1m', periodDays: 1 },
  { key: '5day', label: '五日', interval: '5m', periodDays: 5 },
  { key: 'daily', label: '日K', interval: 'daily', periodDays: 120 },
  { key: 'weekly', label: '周K', interval: 'weekly', periodDays: 365 },
  { key: 'monthly', label: '月K', interval: 'monthly', periodDays: 1095 },
  { key: 'minute', label: '分钟', interval: '15m', periodDays: 5 },
]

const REFRESH_INTERVAL_MS = 10_000 // 10s polling

// ---------------------------------------------------------------------------
// Market-aware color helpers
// ---------------------------------------------------------------------------

function getMarketColors(market: string) {
  if (market === 'CN') {
    return {
      up: '#ef4444',
      down: '#22c55e',
      upAlpha: 'rgba(239,68,68,0.45)',
      downAlpha: 'rgba(34,197,94,0.45)',
    }
  }
  return {
    up: '#22c55e',
    down: '#ef4444',
    upAlpha: 'rgba(34,197,94,0.45)',
    downAlpha: 'rgba(239,68,68,0.45)',
  }
}

// ---------------------------------------------------------------------------
// Date formatting helpers
// ---------------------------------------------------------------------------

function formatDateCN(dateStr: string, interval: string): string {
  const d = new Date(dateStr)
  if (isNaN(d.getTime())) return dateStr

  if (interval === '1m' || interval === '5m' || interval === '15m') {
    return `${d.getMonth() + 1}月${d.getDate()}日 ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
  }
  return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日`
}

function formatTime(iso: string): string {
  const d = new Date(iso)
  if (isNaN(d.getTime())) return ''
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function CandlestickChart({ analysis, onQuoteUpdate }: Props) {
  const { price_data: initialData, signal, ticker, market } = analysis

  const [activeTimeframe, setActiveTimeframe] = useState('daily')
  const [priceData, setPriceData] = useState<PriceBar[]>(initialData || [])
  const [loading, setLoading] = useState(false)
  const [quote, setQuote] = useState<QuoteData | null>(null)
  const [autoRefresh, setAutoRefresh] = useState(true)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Derive lastClose from price data
  const lastBar = priceData.length > 0 ? priceData[priceData.length - 1] : null
  const currentPrice = quote?.price ?? lastBar?.close ?? 0
  const prevClose = priceData.length > 1 ? priceData[priceData.length - 2].close : (lastBar?.open ?? 0)
  const changePct = quote?.change_pct ?? (prevClose ? ((currentPrice - prevClose) / prevClose * 100) : 0)

  // Reset on ticker change
  useEffect(() => {
    setActiveTimeframe('daily')
    setPriceData(initialData || [])
    setQuote(null)
  }, [ticker])

  const activeTimeframeRef = useRef(activeTimeframe)
  activeTimeframeRef.current = activeTimeframe

  // Poll real-time quote AND refresh chart data
  const pollData = useCallback(async () => {
    try {
      const [q] = await Promise.all([
        fetchQuote(ticker, market).catch(() => null),
      ])
      if (q) {
        setQuote(q)
        onQuoteUpdate?.(q)
      }

      // Also refresh K-line data for the active timeframe
      const tf = TIMEFRAMES.find(t => t.key === activeTimeframeRef.current)
      if (tf) {
        if (tf.key === 'daily') {
          // For daily: re-fetch to get any intraday bar update
          const freshData = await fetchPrice({
            ticker, market, interval: tf.interval, period_days: tf.periodDays,
          }).catch(() => null)
          if (freshData && freshData.length > 0) setPriceData(freshData)
        } else if (['realtime', '5day', 'minute'].includes(tf.key)) {
          // For intraday timeframes: always refresh
          const freshData = await fetchPrice({
            ticker, market, interval: tf.interval, period_days: tf.periodDays,
          }).catch(() => null)
          if (freshData && freshData.length > 0) setPriceData(freshData)
        }
      }
    } catch (_) { /* ignore */ }
  }, [ticker, market, onQuoteUpdate])

  useEffect(() => {
    if (!autoRefresh) {
      if (timerRef.current) clearInterval(timerRef.current)
      return
    }
    pollData()
    timerRef.current = setInterval(pollData, REFRESH_INTERVAL_MS)
    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, [autoRefresh, pollData])

  const handleTimeframeChange = useCallback(async (tf: TimeframeOption) => {
    setActiveTimeframe(tf.key)

    if (tf.key === 'daily') {
      setPriceData(initialData || [])
      return
    }

    setLoading(true)
    try {
      const data = await fetchPrice({
        ticker,
        market,
        interval: tf.interval,
        period_days: tf.periodDays,
      })
      setPriceData(data)
    } catch (err) {
      console.error('获取行情数据失败:', err)
      setPriceData(initialData || [])
    } finally {
      setLoading(false)
    }
  }, [ticker, market, initialData])

  if ((!priceData || priceData.length === 0) && !loading) {
    return (
      <div>
        <TimeframeBar
          active={activeTimeframe}
          onChange={handleTimeframeChange}
          autoRefresh={autoRefresh}
          onToggleRefresh={() => setAutoRefresh(v => !v)}
          onManualRefresh={pollData}
          quote={quote}
          currentPrice={currentPrice}
          changePct={changePct}
          market={market}
        />
        <div className="flex items-center justify-center h-64 text-gray-500 text-sm">
          暂无行情数据
        </div>
      </div>
    )
  }

  const currentTf = TIMEFRAMES.find(t => t.key === activeTimeframe) || TIMEFRAMES[2]
  const colors = getMarketColors(market)

  const dates = priceData.map(d => d.date)
  const opens = priceData.map(d => d.open)
  const highs = priceData.map(d => d.high)
  const lows = priceData.map(d => d.low)
  const closes = priceData.map(d => d.close)
  const volumes = priceData.map(d => d.volume)

  const volColors = priceData.map(d =>
    d.close >= d.open ? colors.upAlpha : colors.downAlpha
  )

  const hoverTexts = priceData.map(d => {
    const dateCN = formatDateCN(d.date, currentTf.interval)
    return `${dateCN}<br>开: ${d.open.toFixed(2)}<br>高: ${d.high.toFixed(2)}<br>低: ${d.low.toFixed(2)}<br>收: ${d.close.toFixed(2)}`
  })

  const signalColor = SIGNAL_COLORS[signal.signal]
  const lastDate = dates[dates.length - 1]
  const isIntraday = ['1m', '5m', '15m'].includes(currentTf.interval)
  const priceIsUp = currentPrice >= prevClose

  const data: Plotly.Data[] = [
    ...(isIntraday && currentTf.key === 'realtime'
      ? [{
          type: 'scatter' as const,
          x: dates,
          y: closes,
          mode: 'lines' as const,
          line: { color: colors.up, width: 1.5 },
          fill: 'tozeroy' as const,
          fillcolor: colors.upAlpha,
          name: '价格',
          text: hoverTexts,
          hoverinfo: 'text' as const,
          xaxis: 'x' as const,
          yaxis: 'y' as const,
        }]
      : [{
          type: 'candlestick' as const,
          x: dates,
          open: opens,
          high: highs,
          low: lows,
          close: closes,
          increasing: { line: { color: colors.up } },
          decreasing: { line: { color: colors.down } },
          name: '价格',
          text: hoverTexts,
          hoverinfo: 'text' as const,
          xaxis: 'x' as const,
          yaxis: 'y' as const,
        }]
    ),
    {
      type: 'bar',
      x: dates,
      y: volumes,
      marker: { color: volColors },
      name: '成交量',
      xaxis: 'x',
      yaxis: 'y2',
      opacity: 0.6,
      hovertemplate: '成交量: %{y:,.0f}<extra></extra>',
    },
  ]

  const marketLabel = market === 'CN' ? 'A股' : market === 'FUTURES' ? '期货' : '美股'

  // Current price horizontal line
  const priceLineColor = priceIsUp ? colors.up : colors.down
  const shapes: Partial<Plotly.Shape>[] = currentPrice > 0 ? [
    {
      type: 'line',
      xref: 'paper',
      x0: 0,
      x1: 1,
      yref: 'y',
      y0: currentPrice,
      y1: currentPrice,
      line: {
        color: priceLineColor,
        width: 1,
        dash: 'dot',
      },
    },
  ] : []

  // Annotations: current price label + signal label
  const annotations: Partial<Plotly.Annotations>[] = []

  // Current price label on right edge
  if (currentPrice > 0) {
    annotations.push({
      xref: 'paper',
      x: 1.0,
      yref: 'y',
      y: currentPrice,
      text: `${currentPrice.toFixed(2)}`,
      showarrow: false,
      font: { color: '#fff', size: 10 },
      bgcolor: priceLineColor,
      borderpad: 3,
      xanchor: 'left',
    })
  }

  // Signal annotation
  if (!isIntraday && lastDate) {
    annotations.push({
      x: lastDate,
      y: currentPrice || closes[closes.length - 1],
      text: `${signal.signal_cn}（${signal.composite_score >= 0 ? '+' : ''}${signal.composite_score.toFixed(3)}）`,
      showarrow: true,
      arrowhead: 2,
      arrowcolor: signalColor,
      font: { color: signalColor, size: 11 },
      bgcolor: 'rgba(0,0,0,0.7)',
      bordercolor: signalColor,
      borderwidth: 1,
      borderpad: 4,
    })
  }

  const layout: Partial<Plotly.Layout> = {
    title: {
      text: `${ticker}（${marketLabel}）- ${currentTf.label}`,
      font: { color: '#e5e7eb', size: 14 },
    },
    paper_bgcolor: 'transparent',
    plot_bgcolor: 'rgba(17,24,39,0.5)',
    font: { color: '#9ca3af', size: 10 },
    height: 420,
    margin: { l: 50, r: 60, t: 40, b: 40 },
    xaxis: {
      rangeslider: { visible: false },
      gridcolor: 'rgba(75,85,99,0.2)',
      type: isIntraday ? 'date' : undefined,
      tickformat: isIntraday ? '%H:%M' : '%Y-%m-%d',
      hoverformat: isIntraday ? '%Y-%m-%d %H:%M' : '%Y年%m月%d日',
      fixedrange: false,
    },
    yaxis: {
      domain: [0.25, 1],
      gridcolor: 'rgba(75,85,99,0.2)',
      side: 'right',
      title: { text: '价格', font: { size: 10, color: '#6b7280' } },
      fixedrange: true,
      autorange: true,
    },
    yaxis2: {
      domain: [0, 0.2],
      gridcolor: 'rgba(75,85,99,0.2)',
      side: 'right',
      title: { text: '成交量', font: { size: 10, color: '#6b7280' } },
      fixedrange: true,
    },
    showlegend: false,
    dragmode: 'pan',
    shapes,
    annotations,
  }

  return (
    <div>
      <TimeframeBar
        active={activeTimeframe}
        onChange={handleTimeframeChange}
        autoRefresh={autoRefresh}
        onToggleRefresh={() => setAutoRefresh(v => !v)}
        onManualRefresh={pollData}
        quote={quote}
        currentPrice={currentPrice}
        changePct={changePct}
        market={market}
      />

      {loading ? (
        <div className="flex items-center justify-center h-64">
          <div className="text-center">
            <svg className="animate-spin h-6 w-6 text-blue-500 mx-auto mb-2" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            <p className="text-gray-500 text-xs">加载行情数据...</p>
          </div>
        </div>
      ) : (
        <div className="plotly-chart-wrapper">
          <style>{`.plotly-chart-wrapper .modebar-container { left: 8px !important; right: auto !important; }`}</style>
          <Plot
            data={data}
            layout={layout}
            config={{
              displayModeBar: true,
              displaylogo: false,
              responsive: true,
              scrollZoom: true,
              modeBarButtonsToRemove: [
                'autoScale2d', 'lasso2d', 'select2d',
                'hoverClosestCartesian', 'hoverCompareCartesian',
                'toggleSpikelines',
              ],
              locale: 'zh-CN',
              locales: {
                'zh-CN': {
                  dictionary: {
                    'Zoom': '缩放',
                    'Pan': '平移',
                    'Zoom in': '放大',
                    'Zoom out': '缩小',
                    'Reset axes': '重置',
                    'Download plot as a png': '保存为图片',
                    'Autoscale': '自动缩放',
                    'Toggle Spike Lines': '辅助线',
                  },
                  format: {
                    days: ['星期日', '星期一', '星期二', '星期三', '星期四', '星期五', '星期六'],
                    shortDays: ['日', '一', '二', '三', '四', '五', '六'],
                    months: ['一月', '二月', '三月', '四月', '五月', '六月', '七月', '八月', '九月', '十月', '十一月', '十二月'],
                    shortMonths: ['1月', '2月', '3月', '4月', '5月', '6月', '7月', '8月', '9月', '10月', '11月', '12月'],
                    date: '%Y年%m月%d日',
                  },
                },
              },
            }}
            style={{ width: '100%' }}
          />
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Price bar + Timeframe tab bar
// ---------------------------------------------------------------------------

function TimeframeBar({
  active,
  onChange,
  autoRefresh,
  onToggleRefresh,
  onManualRefresh,
  quote,
  currentPrice,
  changePct,
  market,
}: {
  active: string
  onChange: (tf: TimeframeOption) => void
  autoRefresh: boolean
  onToggleRefresh: () => void
  onManualRefresh: () => void
  quote: QuoteData | null
  currentPrice: number
  changePct: number
  market: string
}) {
  const isUp = changePct >= 0
  const colors = getMarketColors(market)
  const priceColor = market === 'CN'
    ? (isUp ? 'text-red-400' : 'text-green-400')
    : (isUp ? 'text-green-400' : 'text-red-400')

  return (
    <div className="px-2 py-1.5 mb-1 space-y-1.5">
      {/* Current price bar */}
      {currentPrice > 0 && (
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className={`text-xl font-bold font-mono ${priceColor}`}>
              {currentPrice.toFixed(2)}
            </span>
            <span className={`text-sm font-mono ${priceColor}`}>
              {isUp ? '+' : ''}{changePct.toFixed(2)}%
            </span>
            {quote && (
              <span className="text-[10px] text-gray-600">
                {formatTime(quote.timestamp)}
              </span>
            )}
          </div>

          <div className="flex items-center gap-2">
            {quote && quote.high > 0 && (
              <div className="flex items-center gap-1.5 text-[10px]">
                <span className="text-gray-500">高</span>
                <span className="text-gray-300 font-mono">{quote.high.toFixed(2)}</span>
                <span className="text-gray-500 ml-1">低</span>
                <span className="text-gray-300 font-mono">{quote.low.toFixed(2)}</span>
              </div>
            )}
            <button
              onClick={onManualRefresh}
              title="立即刷新"
              className="p-1 rounded text-gray-400 bg-gray-800/50 hover:bg-blue-900/40 hover:text-blue-400 transition-colors"
            >
              <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M1 4v6h6" /><path d="M23 20v-6h-6" />
                <path d="M20.49 9A9 9 0 015.64 5.64L1 10m22 4l-4.64 4.36A9 9 0 013.51 15" />
              </svg>
            </button>
            <button
              onClick={onToggleRefresh}
              title={autoRefresh ? '暂停自动刷新' : '开启自动刷新'}
              className={`p-1 rounded transition-colors ${
                autoRefresh
                  ? 'text-green-400 bg-green-900/20 hover:bg-green-900/40'
                  : 'text-gray-500 bg-gray-800/50 hover:bg-gray-700/50'
              }`}
            >
              {autoRefresh ? (
                <svg className="w-3.5 h-3.5 animate-spin" style={{ animationDuration: '3s' }} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M21 12a9 9 0 11-6.219-8.56" />
                </svg>
              ) : (
                <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <rect x="6" y="4" width="4" height="16" />
                  <rect x="14" y="4" width="4" height="16" />
                </svg>
              )}
            </button>
          </div>
        </div>
      )}

      {/* Timeframe buttons */}
      <div className="flex gap-1">
        {TIMEFRAMES.map(tf => (
          <button
            key={tf.key}
            onClick={() => onChange(tf)}
            className={`px-2.5 py-1 text-xs rounded transition-colors
              ${active === tf.key
                ? 'bg-blue-600 text-white'
                : 'bg-gray-800/50 text-gray-400 hover:bg-gray-700/50 hover:text-gray-200'
              }`}
          >
            {tf.label}
          </button>
        ))}
      </div>
    </div>
  )
}
