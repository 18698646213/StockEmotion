import React, { useState } from 'react'
import type { TradeRecord } from '../types'

interface Props {
  trades: TradeRecord[]
}

type FilterSource = 'all' | 'manual' | 'signal' | 'backtest'
type FilterAction = 'all' | 'BUY' | 'SELL'

const SOURCE_LABELS: Record<string, string> = {
  manual: '手动',
  signal: '信号',
  backtest: '回测',
}

export default function TradeHistory({ trades }: Props) {
  const [filterSource, setFilterSource] = useState<FilterSource>('all')
  const [filterAction, setFilterAction] = useState<FilterAction>('all')
  const [filterTicker, setFilterTicker] = useState('')

  const filtered = trades.filter(t => {
    if (filterSource !== 'all' && t.signal_source !== filterSource) return false
    if (filterAction !== 'all' && t.action !== filterAction) return false
    if (filterTicker && !t.ticker.toLowerCase().includes(filterTicker.toLowerCase())) return false
    return true
  })

  const tickers = Array.from(new Set(trades.map(t => t.ticker)))

  return (
    <div className="bg-gray-900/50 rounded-lg border border-gray-800 overflow-hidden">
      <div className="px-4 py-2.5 border-b border-gray-800 flex items-center gap-4">
        <h4 className="text-sm font-semibold text-white">交易记录</h4>
        <span className="text-xs text-gray-500">{filtered.length} 条</span>
        <div className="flex-1" />

        {/* Filters */}
        <div className="flex items-center gap-2">
          <input
            type="text"
            placeholder="搜索代码"
            value={filterTicker}
            onChange={e => setFilterTicker(e.target.value)}
            className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs text-white
              w-20 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
          <select
            value={filterAction}
            onChange={e => setFilterAction(e.target.value as FilterAction)}
            className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs text-gray-300
              focus:outline-none focus:ring-1 focus:ring-blue-500"
          >
            <option value="all">全部方向</option>
            <option value="BUY">买入</option>
            <option value="SELL">卖出</option>
          </select>
          <select
            value={filterSource}
            onChange={e => setFilterSource(e.target.value as FilterSource)}
            className="bg-gray-800 border border-gray-700 rounded px-2 py-1 text-xs text-gray-300
              focus:outline-none focus:ring-1 focus:ring-blue-500"
          >
            <option value="all">全部来源</option>
            <option value="manual">手动</option>
            <option value="signal">信号</option>
            <option value="backtest">回测</option>
          </select>
        </div>
      </div>

      <div className="max-h-[400px] overflow-y-auto">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-gray-900">
            <tr className="text-xs text-gray-500 border-b border-gray-800">
              <th className="text-left py-2 px-3 font-medium">时间</th>
              <th className="text-left py-2 px-2 font-medium">股票</th>
              <th className="text-center py-2 px-2 font-medium">方向</th>
              <th className="text-right py-2 px-2 font-medium">数量</th>
              <th className="text-right py-2 px-2 font-medium">价格</th>
              <th className="text-right py-2 px-2 font-medium">金额</th>
              <th className="text-right py-2 px-2 font-medium">手续费</th>
              <th className="text-center py-2 px-3 font-medium">来源</th>
            </tr>
          </thead>
          <tbody className="text-gray-300">
            {filtered.length === 0 ? (
              <tr>
                <td colSpan={8} className="text-center py-8 text-gray-600 text-xs">
                  暂无交易记录
                </td>
              </tr>
            ) : (
              filtered.map(trade => (
                <tr key={trade.id} className="border-b border-gray-800/30 hover:bg-gray-800/30 transition-colors">
                  <td className="py-1.5 px-3 text-xs text-gray-400 font-mono">
                    {formatTimestamp(trade.timestamp)}
                  </td>
                  <td className="py-1.5 px-2">
                    <span className="font-mono font-semibold text-white">{trade.ticker}</span>
                    <span className={`ml-1 text-[9px] px-1 py-0.5 rounded ${
                      trade.market === 'US' ? 'bg-blue-900/40 text-blue-400'
                      : trade.market === 'FUTURES' ? 'bg-orange-900/40 text-orange-400'
                      : 'bg-red-900/40 text-red-400'
                    }`}>
                      {trade.market === 'US' ? '美' : trade.market === 'FUTURES' ? '期' : 'A'}
                    </span>
                  </td>
                  <td className="py-1.5 px-2 text-center">
                    <span className={`text-xs font-semibold px-1.5 py-0.5 rounded
                      ${trade.action === 'BUY'
                        ? 'bg-green-900/30 text-green-400'
                        : 'bg-red-900/30 text-red-400'
                      }`}>
                      {trade.action === 'BUY' ? '买' : '卖'}
                    </span>
                  </td>
                  <td className="py-1.5 px-2 text-right font-mono">
                    {trade.shares}
                    <span className="text-[10px] text-gray-500 ml-0.5">
                      {trade.market === 'FUTURES' ? '手' : '股'}
                    </span>
                  </td>
                  <td className="py-1.5 px-2 text-right font-mono">{trade.price.toFixed(2)}</td>
                  <td className="py-1.5 px-2 text-right font-mono">{trade.amount.toFixed(2)}</td>
                  <td className="py-1.5 px-2 text-right font-mono text-gray-500">{trade.total_fee.toFixed(2)}</td>
                  <td className="py-1.5 px-3 text-center">
                    <span className={`text-[10px] px-1.5 py-0.5 rounded
                      ${trade.signal_source === 'signal' ? 'bg-blue-900/30 text-blue-400'
                        : trade.signal_source === 'backtest' ? 'bg-purple-900/30 text-purple-400'
                        : 'bg-gray-800 text-gray-400'
                      }`}>
                      {SOURCE_LABELS[trade.signal_source] || trade.signal_source}
                    </span>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function formatTimestamp(ts: string): string {
  try {
    const d = new Date(ts)
    return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
  } catch {
    return ts
  }
}
