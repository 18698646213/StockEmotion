import React, { useState, useEffect, useCallback } from 'react'
import Plot from 'react-plotly.js'
import type { StockAnalysis, PriceBar } from '../types'
import { SIGNAL_COLORS } from '../types'
import { fetchPrice } from '../api'

interface Props {
  analysis: StockAnalysis
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

// ---------------------------------------------------------------------------
// Market-aware color helpers
// ---------------------------------------------------------------------------

/** A股: 红涨绿跌 (Chinese convention)  |  美股: 绿涨红跌 (Western convention) */
function getMarketColors(market: 'US' | 'CN') {
  if (market === 'CN') {
    return {
      up: '#ef4444',       // 红 — 涨
      down: '#22c55e',     // 绿 — 跌
      upAlpha: 'rgba(239,68,68,0.45)',
      downAlpha: 'rgba(34,197,94,0.45)',
    }
  }
  return {
    up: '#22c55e',         // 绿 — 涨
    down: '#ef4444',       // 红 — 跌
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

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function CandlestickChart({ analysis }: Props) {
  const { price_data: initialData, signal, ticker, market } = analysis

  const [activeTimeframe, setActiveTimeframe] = useState('daily')
  const [priceData, setPriceData] = useState<PriceBar[]>(initialData || [])
  const [loading, setLoading] = useState(false)

  // Reset to daily when ticker changes
  useEffect(() => {
    setActiveTimeframe('daily')
    setPriceData(initialData || [])
  }, [ticker])

  const handleTimeframeChange = useCallback(async (tf: TimeframeOption) => {
    setActiveTimeframe(tf.key)

    if (tf.key === 'daily') {
      // Use the original data from the analysis
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
      // Fallback to original data
      setPriceData(initialData || [])
    } finally {
      setLoading(false)
    }
  }, [ticker, market, initialData])

  if ((!priceData || priceData.length === 0) && !loading) {
    return (
      <div>
        <TimeframeBar active={activeTimeframe} onChange={handleTimeframeChange} />
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

  // Volume bar colors based on market convention
  const volColors = priceData.map(d =>
    d.close >= d.open ? colors.upAlpha : colors.downAlpha
  )

  // Custom hover text in Chinese
  const hoverTexts = priceData.map(d => {
    const dateCN = formatDateCN(d.date, currentTf.interval)
    return `${dateCN}<br>开: ${d.open.toFixed(2)}<br>高: ${d.high.toFixed(2)}<br>低: ${d.low.toFixed(2)}<br>收: ${d.close.toFixed(2)}`
  })

  const signalColor = SIGNAL_COLORS[signal.signal]
  const lastDate = dates[dates.length - 1]
  const lastClose = closes[closes.length - 1]

  const isIntraday = ['1m', '5m', '15m'].includes(currentTf.interval)

  const data: Plotly.Data[] = [
    // Use line chart for intraday (realtime), candlestick for others
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

  const marketLabel = market === 'CN' ? 'A股' : '美股'

  const layout: Partial<Plotly.Layout> = {
    title: {
      text: `${ticker}（${marketLabel}）- ${currentTf.label}`,
      font: { color: '#e5e7eb', size: 14 },
    },
    paper_bgcolor: 'transparent',
    plot_bgcolor: 'rgba(17,24,39,0.5)',
    font: { color: '#9ca3af', size: 10 },
    height: 420,
    margin: { l: 50, r: 20, t: 40, b: 40 },
    xaxis: {
      rangeslider: { visible: false },
      gridcolor: 'rgba(75,85,99,0.2)',
      type: isIntraday ? 'date' : undefined,
      tickformat: isIntraday ? '%H:%M' : '%Y-%m-%d',
      hoverformat: isIntraday ? '%Y-%m-%d %H:%M' : '%Y年%m月%d日',
      // Allow scroll zoom on x-axis
      fixedrange: false,
    },
    yaxis: {
      domain: [0.25, 1],
      gridcolor: 'rgba(75,85,99,0.2)',
      side: 'right',
      title: { text: '价格', font: { size: 10, color: '#6b7280' } },
      fixedrange: true,   // 锁定 Y 轴，缩放不改变高度
      autorange: true,
    },
    yaxis2: {
      domain: [0, 0.2],
      gridcolor: 'rgba(75,85,99,0.2)',
      side: 'right',
      title: { text: '成交量', font: { size: 10, color: '#6b7280' } },
      fixedrange: true,   // 锁定成交量 Y 轴
    },
    showlegend: false,
    dragmode: 'pan',       // 默认拖拽为左右平移
    // Only show signal annotation for non-intraday
    annotations: !isIntraday && lastDate ? [
      {
        x: lastDate,
        y: lastClose,
        text: `${signal.signal_cn}（${signal.composite_score >= 0 ? '+' : ''}${signal.composite_score.toFixed(3)}）`,
        showarrow: true,
        arrowhead: 2,
        arrowcolor: signalColor,
        font: { color: signalColor, size: 11 },
        bgcolor: 'rgba(0,0,0,0.7)',
        bordercolor: signalColor,
        borderwidth: 1,
        borderpad: 4,
      },
    ] : [],
  }

  return (
    <div>
      <TimeframeBar active={activeTimeframe} onChange={handleTimeframeChange} />

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
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Timeframe tab bar
// ---------------------------------------------------------------------------

function TimeframeBar({
  active,
  onChange,
}: {
  active: string
  onChange: (tf: TimeframeOption) => void
}) {
  return (
    <div className="flex gap-1 px-2 py-1.5 mb-1">
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
  )
}
