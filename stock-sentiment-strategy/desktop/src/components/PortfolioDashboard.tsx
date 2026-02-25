import React, { useState, useEffect, useCallback } from 'react'
import type { PortfolioSummary, TradeRecord } from '../types'
import { getPortfolio, resetPortfolio, getTradeHistory } from '../api'
import TradeHistory from './TradeHistory'

interface Props {
  onSellClick?: (ticker: string, market: 'US' | 'CN') => void
  refreshKey?: number
}

export default function PortfolioDashboard({ onSellClick, refreshKey }: Props) {
  const [summary, setSummary] = useState<PortfolioSummary | null>(null)
  const [trades, setTrades] = useState<TradeRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showHistory, setShowHistory] = useState(false)
  const [resetting, setResetting] = useState(false)
  const [resetCapital, setResetCapital] = useState('100000')
  const [showResetConfirm, setShowResetConfirm] = useState(false)

  const loadData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [portfolioData, tradeData] = await Promise.all([
        getPortfolio(),
        getTradeHistory(),
      ])
      setSummary(portfolioData)
      setTrades(tradeData)
    } catch (e: any) {
      setError(e.message || '加载持仓数据失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { loadData() }, [loadData, refreshKey])

  const handleReset = async () => {
    setResetting(true)
    try {
      const capital = Number(resetCapital) || 100000
      const data = await resetPortfolio(capital)
      setSummary(data)
      setTrades([])
      setShowResetConfirm(false)
    } catch (e: any) {
      setError(e.message || '重置失败')
    } finally {
      setResetting(false)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-center">
          <svg className="animate-spin h-8 w-8 text-blue-500 mx-auto mb-3" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          <p className="text-gray-500 text-sm">加载持仓数据...</p>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-red-900/30 border border-red-800 rounded-lg px-4 py-3 text-red-300 text-sm">
        {error}
        <button onClick={loadData} className="ml-3 text-blue-400 hover:text-blue-300 underline">重试</button>
      </div>
    )
  }

  if (!summary) return null

  const pnlColor = summary.total_pnl >= 0 ? 'text-green-400' : 'text-red-400'
  const pnlSign = summary.total_pnl >= 0 ? '+' : ''

  return (
    <div className="space-y-6">
      {/* Statistics cards */}
      <div className="grid grid-cols-5 gap-3">
        {[
          { label: '总资产', value: `${summary.total_value.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}`, color: 'text-white' },
          { label: '可用资金', value: `${summary.cash.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}`, color: 'text-gray-300' },
          { label: '总盈亏', value: `${pnlSign}${summary.total_pnl.toFixed(2)} (${pnlSign}${summary.total_pnl_pct.toFixed(2)}%)`, color: pnlColor },
          { label: '已实现盈亏', value: `${summary.realized_pnl >= 0 ? '+' : ''}${summary.realized_pnl.toFixed(2)}`, color: summary.realized_pnl >= 0 ? 'text-green-400' : 'text-red-400' },
          { label: '浮动盈亏', value: `${summary.unrealized_pnl >= 0 ? '+' : ''}${summary.unrealized_pnl.toFixed(2)}`, color: summary.unrealized_pnl >= 0 ? 'text-green-400' : 'text-red-400' },
        ].map(item => (
          <div key={item.label} className="bg-gray-900/50 rounded-lg border border-gray-800 p-3 text-center">
            <p className="text-[10px] text-gray-500 mb-1">{item.label}</p>
            <p className={`text-sm font-mono font-semibold ${item.color}`}>{item.value}</p>
          </div>
        ))}
      </div>

      {/* Stats row */}
      <div className="flex items-center gap-6 text-xs text-gray-400">
        <span>初始资金: <span className="text-gray-300 font-mono">{summary.initial_capital.toLocaleString()}</span></span>
        <span>交易次数: <span className="text-gray-300 font-mono">{summary.trade_count}</span></span>
        <span>胜率: <span className="text-gray-300 font-mono">{summary.win_rate.toFixed(1)}%</span></span>
        <div className="flex-1" />
        <button
          onClick={() => setShowHistory(!showHistory)}
          className="text-blue-400 hover:text-blue-300 transition-colors"
        >
          {showHistory ? '隐藏交易记录' : '查看交易记录'} ({trades.length})
        </button>
        <button
          onClick={() => setShowResetConfirm(!showResetConfirm)}
          className="text-gray-500 hover:text-red-400 transition-colors"
        >
          重置账户
        </button>
        <button
          onClick={loadData}
          className="text-gray-500 hover:text-blue-400 transition-colors"
          title="刷新"
        >
          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
          </svg>
        </button>
      </div>

      {/* Reset confirm */}
      {showResetConfirm && (
        <div className="bg-red-900/20 border border-red-800/50 rounded-lg p-4 space-y-3">
          <p className="text-sm text-red-300">确定要重置账户吗？所有持仓和交易记录将被清除。</p>
          <div className="flex items-center gap-3">
            <label className="text-xs text-gray-400">初始资金:</label>
            <input
              type="number"
              value={resetCapital}
              onChange={e => setResetCapital(e.target.value)}
              className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-sm text-white font-mono w-32
                focus:outline-none focus:ring-1 focus:ring-red-500"
            />
            <button
              onClick={handleReset}
              disabled={resetting}
              className="bg-red-600 hover:bg-red-500 text-white text-xs px-3 py-1.5 rounded transition-colors disabled:bg-gray-700"
            >
              {resetting ? '重置中...' : '确认重置'}
            </button>
            <button
              onClick={() => setShowResetConfirm(false)}
              className="text-gray-500 hover:text-gray-300 text-xs"
            >取消</button>
          </div>
        </div>
      )}

      {/* Positions table */}
      {summary.positions.length > 0 ? (
        <div className="bg-gray-900/50 rounded-lg border border-gray-800 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-gray-500 border-b border-gray-800 bg-gray-900/50">
                <th className="text-left py-2 px-3 font-medium">股票</th>
                <th className="text-left py-2 px-2 font-medium">市场</th>
                <th className="text-right py-2 px-2 font-medium">持仓</th>
                <th className="text-right py-2 px-2 font-medium">成本价</th>
                <th className="text-right py-2 px-2 font-medium">现价</th>
                <th className="text-right py-2 px-2 font-medium">浮动盈亏</th>
                <th className="text-right py-2 px-2 font-medium">盈亏比</th>
                <th className="text-center py-2 px-3 font-medium">操作</th>
              </tr>
            </thead>
            <tbody className="text-gray-300">
              {summary.positions.map(pos => (
                <tr key={pos.ticker} className="border-b border-gray-800/30 hover:bg-gray-800/30 transition-colors">
                  <td className="py-2 px-3 font-mono font-semibold text-white">{pos.ticker}</td>
                  <td className="py-2 px-2">
                    <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                      pos.market === 'US' ? 'bg-blue-900/40 text-blue-400'
                      : pos.market === 'FUTURES' ? 'bg-orange-900/40 text-orange-400'
                      : 'bg-red-900/40 text-red-400'
                    }`}>
                      {pos.market === 'US' ? '美股' : pos.market === 'FUTURES' ? '期货' : 'A股'}
                    </span>
                  </td>
                  <td className="py-2 px-2 text-right font-mono">{pos.shares}</td>
                  <td className="py-2 px-2 text-right font-mono">{pos.avg_cost.toFixed(2)}</td>
                  <td className="py-2 px-2 text-right font-mono">{pos.current_price.toFixed(2)}</td>
                  <td className={`py-2 px-2 text-right font-mono ${pos.unrealized_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    {pos.unrealized_pnl >= 0 ? '+' : ''}{pos.unrealized_pnl.toFixed(2)}
                  </td>
                  <td className={`py-2 px-2 text-right font-mono ${pos.unrealized_pnl_pct >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                    {pos.unrealized_pnl_pct >= 0 ? '+' : ''}{pos.unrealized_pnl_pct.toFixed(2)}%
                  </td>
                  <td className="py-2 px-3 text-center">
                    <button
                      onClick={() => onSellClick?.(pos.ticker, pos.market as 'US' | 'CN')}
                      disabled={pos.sellable_shares <= 0}
                      className="text-xs text-red-400 hover:text-red-300 disabled:text-gray-600 transition-colors"
                    >
                      {pos.sellable_shares > 0 ? '卖出' : 'T+1'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="text-center py-12">
          <div className="text-4xl mb-3 opacity-20">&#x1F4B0;</div>
          <p className="text-gray-500 text-sm mb-1">暂无持仓</p>
          <p className="text-gray-600 text-xs">在分析页面中选择股票进行交易</p>
        </div>
      )}

      {/* Trade history */}
      {showHistory && trades.length > 0 && (
        <TradeHistory trades={trades} />
      )}
    </div>
  )
}
