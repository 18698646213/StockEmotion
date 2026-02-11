import React from 'react'
import type { StockAnalysis } from '../types'
import SignalBadge from './SignalBadge'

interface Props {
  results: StockAnalysis[]
  selectedTicker: string | null
  onSelect: (ticker: string) => void
  isInWatchlist: (ticker: string) => boolean
  onToggleWatchlist: (ticker: string, market: 'US' | 'CN') => void
}

function ScoreCell({ value }: { value: number }) {
  const color =
    value > 0.3 ? 'text-green-400' :
    value < -0.3 ? 'text-red-400' :
    'text-yellow-400'

  return (
    <span className={`font-mono text-xs ${color}`}>
      {value >= 0 ? '+' : ''}{value.toFixed(3)}
    </span>
  )
}

function StarButton({ active, onClick }: { active: boolean; onClick: (e: React.MouseEvent) => void }) {
  return (
    <button
      onClick={onClick}
      className={`p-0.5 rounded transition-colors ${
        active
          ? 'text-amber-400 hover:text-amber-300'
          : 'text-gray-600 hover:text-amber-400'
      }`}
      title={active ? '取消自选' : '添加自选'}
    >
      <svg className="w-4 h-4" fill={active ? 'currentColor' : 'none'} viewBox="0 0 20 20" stroke="currentColor" strokeWidth={active ? 0 : 1.5}>
        <path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z" />
      </svg>
    </button>
  )
}

export default function SummaryTable({ results, selectedTicker, onSelect, isInWatchlist, onToggleWatchlist }: Props) {
  if (results.length === 0) return null

  return (
    <div className="bg-gray-900/50 rounded-xl border border-gray-800 overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-800">
        <h2 className="text-sm font-semibold text-gray-300">分析概览</h2>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-xs text-gray-500 border-b border-gray-800/50">
              <th className="px-2 py-2.5 text-center font-medium w-8"></th>
              <th className="px-3 py-2.5 text-left font-medium">代码</th>
              <th className="px-3 py-2.5 text-center font-medium">市场</th>
              <th className="px-3 py-2.5 text-center font-medium">舆情</th>
              <th className="px-3 py-2.5 text-center font-medium">技术面</th>
              <th className="px-3 py-2.5 text-center font-medium">新闻量</th>
              <th className="px-3 py-2.5 text-center font-medium">综合</th>
              <th className="px-3 py-2.5 text-center font-medium">信号</th>
              <th className="px-3 py-2.5 text-center font-medium">仓位</th>
              <th className="px-3 py-2.5 text-center font-medium">新闻数</th>
            </tr>
          </thead>
          <tbody>
            {results.map((r) => (
              <tr
                key={r.ticker}
                onClick={() => onSelect(r.ticker)}
                className={`cursor-pointer border-b border-gray-800/30 transition-colors
                  ${selectedTicker === r.ticker
                    ? 'bg-blue-900/20'
                    : 'hover:bg-gray-800/30'}`}
              >
                <td className="px-2 py-2.5 text-center">
                  <StarButton
                    active={isInWatchlist(r.ticker)}
                    onClick={(e) => {
                      e.stopPropagation()
                      onToggleWatchlist(r.ticker, r.market)
                    }}
                  />
                </td>
                <td className="px-3 py-2.5 font-semibold text-white">{r.ticker}</td>
                <td className="px-3 py-2.5 text-center">
                  <span className={`text-xs px-1.5 py-0.5 rounded
                    ${r.market === 'US' ? 'bg-blue-900/40 text-blue-400' : 'bg-red-900/40 text-red-400'}`}>
                    {r.market === 'US' ? '美股' : 'A股'}
                  </span>
                </td>
                <td className="px-3 py-2.5 text-center"><ScoreCell value={r.signal.sentiment_score} /></td>
                <td className="px-3 py-2.5 text-center"><ScoreCell value={r.signal.technical_score} /></td>
                <td className="px-3 py-2.5 text-center"><ScoreCell value={r.signal.news_volume_score} /></td>
                <td className="px-3 py-2.5 text-center"><ScoreCell value={r.signal.composite_score} /></td>
                <td className="px-3 py-2.5 text-center">
                  <SignalBadge
                    signal={r.signal.signal}
                    signalCn={r.signal.signal_cn}
                    score={r.signal.composite_score}
                    size="sm"
                  />
                </td>
                <td className="px-3 py-2.5 text-center text-gray-400 font-mono text-xs">
                  {r.position_pct > 0 ? `${r.position_pct.toFixed(1)}%` : '-'}
                </td>
                <td className="px-3 py-2.5 text-center text-gray-400 text-xs">
                  {r.signal.news_count}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
