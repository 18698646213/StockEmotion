import React, { useState } from 'react'
import Plot from 'react-plotly.js'
import type { BacktestReport, BacktestRequest, PriceBar } from '../types'
import { runBacktest } from '../api'
import PnLChart from './PnLChart'
import TradeHistory from './TradeHistory'

export default function BacktestPanel({
  futuresContracts = [],
}: {
  futuresContracts?: string[]
}) {
  const [ticker, setTicker] = useState('')
  const [market, setMarket] = useState<'US' | 'CN' | 'FUTURES'>('US')
  const [startDate, setStartDate] = useState(() => {
    const d = new Date()
    d.setFullYear(d.getFullYear() - 1)
    return d.toISOString().slice(0, 10)
  })
  const [endDate, setEndDate] = useState(() => new Date().toISOString().slice(0, 10))
  const [capital, setCapital] = useState('100000')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [report, setReport] = useState<BacktestReport | null>(null)

  const handleRun = async () => {
    if (!ticker.trim()) {
      setError('请输入股票代码')
      return
    }
    setLoading(true)
    setError(null)
    setReport(null)
    try {
      const data = await runBacktest({
        ticker: ticker.trim().toUpperCase(),
        market,
        start_date: startDate,
        end_date: endDate,
        initial_capital: Number(capital) || 100000,
      })
      if (data.equity_curve.length === 0) {
        setError('回测日期范围内无可用数据，请调整日期或检查股票代码')
      } else {
        setReport(data)
      }
    } catch (e: any) {
      setError(e.message || '回测失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-6">
      {/* Config form */}
      <div className="bg-gray-900/50 rounded-lg border border-gray-800 p-5">
        <h3 className="text-sm font-semibold text-white mb-4">回测配置</h3>
        <div className="grid grid-cols-6 gap-4 items-end">
          <div>
            <label className="block text-xs text-gray-400 mb-1">市场</label>
            <select
              value={market}
              onChange={e => {
                const m = e.target.value as 'US' | 'CN' | 'FUTURES'
                setMarket(m)
                if (m === 'FUTURES' && futuresContracts.length > 0) {
                  setTicker(futuresContracts[0])
                } else if (m !== 'FUTURES') {
                  setTicker('')
                }
              }}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm
                text-white focus:outline-none focus:ring-1 focus:ring-blue-500"
            >
              <option value="US">美股</option>
              <option value="CN">A股</option>
              <option value="FUTURES">期货</option>
            </select>
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">
              {market === 'FUTURES' ? '期货合约' : '股票代码'}
            </label>
            {market === 'FUTURES' && futuresContracts.length > 0 ? (
              <select
                value={ticker}
                onChange={e => setTicker(e.target.value)}
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm
                  text-white font-mono focus:outline-none focus:ring-1 focus:ring-blue-500"
              >
                {futuresContracts.map(c => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
            ) : (
              <input
                type="text"
                value={ticker}
                onChange={e => setTicker(e.target.value)}
                placeholder={market === 'FUTURES' ? 'RB0 / C2605' : 'AAPL / 600519'}
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm
                  text-white font-mono focus:outline-none focus:ring-1 focus:ring-blue-500"
              />
            )}
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">起始日期</label>
            <input
              type="date"
              value={startDate}
              onChange={e => setStartDate(e.target.value)}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm
                text-white focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">结束日期</label>
            <input
              type="date"
              value={endDate}
              onChange={e => setEndDate(e.target.value)}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm
                text-white focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">初始资金</label>
            <input
              type="number"
              value={capital}
              onChange={e => setCapital(e.target.value)}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm
                text-white font-mono focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
          </div>
          <div>
            <button
              onClick={handleRun}
              disabled={loading}
              className="w-full bg-purple-600 hover:bg-purple-500 disabled:bg-gray-700 disabled:text-gray-500
                text-white font-semibold py-2 px-4 rounded-lg transition-colors text-sm
                flex items-center justify-center gap-2"
            >
              {loading ? (
                <>
                  <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  回测中...
                </>
              ) : '开始回测'}
            </button>
          </div>
        </div>
      </div>

      {error && (
        <div className="bg-red-900/30 border border-red-800 rounded-lg px-4 py-3 text-red-300 text-sm">
          {error}
        </div>
      )}

      {loading && (
        <div className="flex items-center justify-center py-16">
          <div className="text-center">
            <svg className="animate-spin h-10 w-10 text-purple-500 mx-auto mb-4" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            <p className="text-gray-400 text-sm">正在运行回测，获取历史数据并模拟交易...</p>
            <p className="text-gray-600 text-xs mt-1">这可能需要几十秒，请耐心等待</p>
          </div>
        </div>
      )}

      {/* Report */}
      {report && !loading && (
        <div className="space-y-6">
          {/* Metrics cards */}
          <div className="grid grid-cols-7 gap-3">
            {[
              { label: '总收益率', value: `${report.metrics.total_return >= 0 ? '+' : ''}${report.metrics.total_return.toFixed(2)}%`, color: report.metrics.total_return >= 0 ? 'text-green-400' : 'text-red-400' },
              { label: '年化收益', value: `${report.metrics.annual_return >= 0 ? '+' : ''}${report.metrics.annual_return.toFixed(2)}%`, color: report.metrics.annual_return >= 0 ? 'text-green-400' : 'text-red-400' },
              { label: '最大回撤', value: `-${report.metrics.max_drawdown.toFixed(2)}%`, color: 'text-red-400' },
              { label: '夏普比率', value: report.metrics.sharpe_ratio.toFixed(2), color: report.metrics.sharpe_ratio > 0 ? 'text-green-400' : 'text-red-400' },
              { label: '胜率', value: `${report.metrics.win_rate.toFixed(1)}%`, color: report.metrics.win_rate >= 50 ? 'text-green-400' : 'text-amber-400' },
              { label: '盈亏比', value: report.metrics.profit_loss_ratio.toFixed(2), color: report.metrics.profit_loss_ratio > 1 ? 'text-green-400' : 'text-red-400' },
              { label: '交易次数', value: `${report.metrics.total_trades}`, color: 'text-gray-300' },
            ].map(item => (
              <div key={item.label} className="bg-gray-900/50 rounded-lg border border-gray-800 p-3 text-center">
                <p className="text-[10px] text-gray-500 mb-1">{item.label}</p>
                <p className={`text-sm font-mono font-bold ${item.color}`}>{item.value}</p>
              </div>
            ))}
          </div>

          {/* Equity curve */}
          <PnLChart
            equityCurve={report.equity_curve}
            initialCapital={report.initial_capital}
          />

          {/* K-line with buy/sell markers */}
          {report.price_data && report.price_data.length > 0 && (
            <BacktestCandlestick
              priceData={report.price_data}
              buySellPoints={report.buy_sell_points}
              market={report.market as 'US' | 'CN' | 'FUTURES'}
              ticker={report.ticker}
            />
          )}

          {/* Trade history */}
          {report.trades && report.trades.length > 0 && (
            <TradeHistory trades={report.trades as any} />
          )}
        </div>
      )}
    </div>
  )
}


// ---------------------------------------------------------------------------
// Backtest candlestick with buy/sell markers
// ---------------------------------------------------------------------------

function BacktestCandlestick({
  priceData,
  buySellPoints,
  market,
  ticker,
}: {
  priceData: PriceBar[]
  buySellPoints: { date: string; action: string; price: number }[]
  market: 'US' | 'CN' | 'FUTURES'
  ticker: string
}) {
  // CN market: red up, green down (Chinese convention)
  // US/FUTURES: green up, red down (international convention)
  const upColor = market === 'CN' ? '#ef4444' : '#22c55e'
  const downColor = market === 'CN' ? '#22c55e' : '#ef4444'

  const dates = priceData.map(d => d.date)
  const opens = priceData.map(d => d.open)
  const highs = priceData.map(d => d.high)
  const lows = priceData.map(d => d.low)
  const closes = priceData.map(d => d.close)

  const buyPoints = buySellPoints.filter(p => p.action === 'BUY')
  const sellPoints = buySellPoints.filter(p => p.action === 'SELL')

  const data: Plotly.Data[] = [
    {
      type: 'candlestick',
      x: dates,
      open: opens,
      high: highs,
      low: lows,
      close: closes,
      increasing: { line: { color: upColor } },
      decreasing: { line: { color: downColor } },
      name: '价格',
      hoverinfo: 'x+y',
    },
    // Buy markers
    {
      type: 'scatter',
      x: buyPoints.map(p => p.date),
      y: buyPoints.map(p => p.price),
      mode: 'markers',
      marker: {
        symbol: 'triangle-up',
        size: 12,
        color: '#22c55e',
        line: { color: '#16a34a', width: 1 },
      },
      name: '买入',
      hovertemplate: '买入<br>%{x}<br>价格: %{y:.2f}<extra></extra>',
    },
    // Sell markers
    {
      type: 'scatter',
      x: sellPoints.map(p => p.date),
      y: sellPoints.map(p => p.price),
      mode: 'markers',
      marker: {
        symbol: 'triangle-down',
        size: 12,
        color: '#ef4444',
        line: { color: '#dc2626', width: 1 },
      },
      name: '卖出',
      hovertemplate: '卖出<br>%{x}<br>价格: %{y:.2f}<extra></extra>',
    },
  ]

  const layout: Partial<Plotly.Layout> = {
    title: {
      text: `${ticker} 回测买卖点`,
      font: { color: '#e5e7eb', size: 13 },
    },
    paper_bgcolor: 'transparent',
    plot_bgcolor: 'rgba(17,24,39,0.5)',
    font: { color: '#9ca3af', size: 10 },
    height: 380,
    margin: { l: 50, r: 20, t: 40, b: 40 },
    xaxis: {
      rangeslider: { visible: false },
      gridcolor: 'rgba(75,85,99,0.2)',
    },
    yaxis: {
      gridcolor: 'rgba(75,85,99,0.2)',
      side: 'right',
    },
    showlegend: true,
    legend: {
      x: 0, y: 1,
      font: { size: 10, color: '#9ca3af' },
      bgcolor: 'transparent',
    },
    dragmode: 'pan',
  }

  return (
    <Plot
      data={data}
      layout={layout}
      config={{
        displayModeBar: true,
        displaylogo: false,
        responsive: true,
        scrollZoom: true,
        modeBarButtonsToRemove: ['autoScale2d', 'lasso2d', 'select2d'],
      }}
      style={{ width: '100%' }}
    />
  )
}
