import React from 'react'
import type { SearchDetailItem } from '../api'

interface Props {
  query: string
  results: SearchDetailItem[]
  loading: boolean
  onSelect: (item: SearchDetailItem) => void
  onClose: () => void
}

function formatVolume(v: number): string {
  if (!v) return '-'
  if (v >= 1e8) return (v / 1e8).toFixed(2) + '亿'
  if (v >= 1e4) return (v / 1e4).toFixed(1) + '万'
  return v.toLocaleString()
}

function formatMoney(v: number): string {
  if (!v) return '-'
  if (v >= 1e8) return (v / 1e8).toFixed(2) + '亿'
  if (v >= 1e4) return (v / 1e4).toFixed(1) + '万'
  return v.toFixed(2)
}

function formatPrice(v: number): string {
  if (!v) return '-'
  return v.toFixed(2)
}

function PctBadge({ value }: { value: number }) {
  if (!value && value !== 0) return <span className="text-gray-500">-</span>
  const isUp = value > 0
  const isDown = value < 0
  return (
    <span className={`font-mono text-sm ${isUp ? 'text-red-400' : isDown ? 'text-green-400' : 'text-gray-400'}`}>
      {isUp ? '+' : ''}{value.toFixed(2)}%
    </span>
  )
}

function ChangeCell({ value }: { value: number }) {
  if (!value && value !== 0) return <span className="text-gray-500">-</span>
  const isUp = value > 0
  const isDown = value < 0
  return (
    <span className={`font-mono text-sm ${isUp ? 'text-red-400' : isDown ? 'text-green-400' : 'text-gray-400'}`}>
      {isUp ? '+' : ''}{value.toFixed(2)}
    </span>
  )
}

export default function SearchResultsPanel({ query, results, loading, onSelect, onClose }: Props) {
  const isFutures = results.length > 0 && results[0].market === 'FUTURES'
  const isCN = results.length > 0 && results[0].market === 'CN'

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <button
            onClick={onClose}
            className="text-gray-500 hover:text-gray-300 transition-colors"
            title="返回"
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M10 19l-7-7m0 0l7-7m-7 7h18" />
            </svg>
          </button>
          <div>
            <h2 className="text-lg font-semibold text-white">
              搜索结果
              <span className="text-gray-500 text-sm font-normal ml-2">"{query}"</span>
            </h2>
            {!loading && (
              <p className="text-xs text-gray-500 mt-0.5">
                共 {results.length} 条结果，点击行添加到分析列表
              </p>
            )}
          </div>
        </div>
      </div>

      {/* Loading */}
      {loading && (
        <div className="flex items-center justify-center py-20">
          <div className="text-center">
            <svg className="animate-spin h-8 w-8 text-blue-500 mx-auto mb-3" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            <p className="text-gray-400 text-sm">正在获取实时行情...</p>
          </div>
        </div>
      )}

      {/* No results */}
      {!loading && results.length === 0 && (
        <div className="flex items-center justify-center py-20">
          <div className="text-center">
            <div className="text-4xl mb-3 opacity-20">&#x1F50D;</div>
            <p className="text-gray-400">未找到匹配的结果</p>
            <p className="text-gray-600 text-xs mt-1">请尝试其他关键词</p>
          </div>
        </div>
      )}

      {/* Results table */}
      {!loading && results.length > 0 && (
        <div className="flex-1 overflow-auto rounded-lg border border-gray-800">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-gray-900 z-10">
              <tr className="text-xs text-gray-500 border-b border-gray-800">
                <th className="text-left px-3 py-2.5 font-medium whitespace-nowrap">合约</th>
                <th className="text-right px-3 py-2.5 font-medium whitespace-nowrap">最新价</th>
                <th className="text-right px-3 py-2.5 font-medium whitespace-nowrap">涨跌幅</th>
                <th className="text-right px-3 py-2.5 font-medium whitespace-nowrap">涨跌额</th>
                <th className="text-right px-3 py-2.5 font-medium whitespace-nowrap">成交量</th>
                {isFutures && (
                  <th className="text-right px-3 py-2.5 font-medium whitespace-nowrap">持仓量</th>
                )}
                <th className="text-right px-3 py-2.5 font-medium whitespace-nowrap">振幅</th>
                <th className="text-right px-3 py-2.5 font-medium whitespace-nowrap">今开</th>
                <th className="text-right px-3 py-2.5 font-medium whitespace-nowrap">最高</th>
                <th className="text-right px-3 py-2.5 font-medium whitespace-nowrap">最低</th>
                {isFutures && (
                  <>
                    <th className="text-right px-3 py-2.5 font-medium whitespace-nowrap">今结</th>
                    <th className="text-right px-3 py-2.5 font-medium whitespace-nowrap">昨结</th>
                  </>
                )}
                <th className="text-right px-3 py-2.5 font-medium whitespace-nowrap">昨收</th>
                {isCN && (
                  <>
                    <th className="text-right px-3 py-2.5 font-medium whitespace-nowrap">成交额</th>
                    <th className="text-right px-3 py-2.5 font-medium whitespace-nowrap">换手率</th>
                  </>
                )}
              </tr>
            </thead>
            <tbody>
              {results.map((item, idx) => {
                const isUp = item.change_pct > 0
                const isDown = item.change_pct < 0
                const rowBg = idx % 2 === 0 ? 'bg-gray-950' : 'bg-gray-900/50'
                const priceColor = isUp ? 'text-red-400' : isDown ? 'text-green-400' : 'text-gray-200'

                return (
                  <tr
                    key={`${item.market}-${item.code}`}
                    onClick={() => onSelect(item)}
                    className={`${rowBg} hover:bg-blue-900/20 cursor-pointer transition-colors border-b border-gray-800/50 last:border-0`}
                  >
                    {/* Contract name + code */}
                    <td className="px-3 py-2.5 whitespace-nowrap">
                      <div className="flex items-center gap-2">
                        <span className={`text-[9px] px-1.5 py-0.5 rounded font-medium shrink-0 ${
                          item.market === 'FUTURES'
                            ? 'bg-orange-900/40 text-orange-400'
                            : item.market === 'CN'
                            ? 'bg-red-900/40 text-red-400'
                            : 'bg-blue-900/40 text-blue-400'
                        }`}>
                          {item.market === 'FUTURES' ? '期货' : item.market === 'CN' ? 'A股' : '美股'}
                        </span>
                        <div className="flex items-baseline gap-1.5">
                          <span className="font-mono text-xs text-gray-400">{item.code}</span>
                          <span className="font-medium text-gray-100">{item.name}</span>
                        </div>
                      </div>
                    </td>
                    {/* Price */}
                    <td className={`text-right px-3 py-2.5 font-mono font-semibold ${priceColor} whitespace-nowrap`}>
                      {formatPrice(item.price)}
                    </td>
                    {/* Change % */}
                    <td className="text-right px-3 py-2.5 whitespace-nowrap">
                      <PctBadge value={item.change_pct} />
                    </td>
                    {/* Change amount */}
                    <td className="text-right px-3 py-2.5 whitespace-nowrap">
                      <ChangeCell value={item.change_amt} />
                    </td>
                    {/* Volume */}
                    <td className="text-right px-3 py-2.5 text-gray-300 font-mono whitespace-nowrap">
                      {formatVolume(item.volume)}
                    </td>
                    {/* Open interest (futures only) */}
                    {isFutures && (
                      <td className="text-right px-3 py-2.5 text-gray-300 font-mono whitespace-nowrap">
                        {formatVolume(item.open_interest)}
                      </td>
                    )}
                    {/* Amplitude */}
                    <td className="text-right px-3 py-2.5 text-gray-400 font-mono whitespace-nowrap">
                      {item.amplitude ? item.amplitude.toFixed(2) + '%' : '-'}
                    </td>
                    {/* Open */}
                    <td className="text-right px-3 py-2.5 text-gray-300 font-mono whitespace-nowrap">
                      {formatPrice(item.open_price)}
                    </td>
                    {/* High */}
                    <td className="text-right px-3 py-2.5 text-red-400/70 font-mono whitespace-nowrap">
                      {formatPrice(item.high)}
                    </td>
                    {/* Low */}
                    <td className="text-right px-3 py-2.5 text-green-400/70 font-mono whitespace-nowrap">
                      {formatPrice(item.low)}
                    </td>
                    {/* Settlement (futures) */}
                    {isFutures && (
                      <>
                        <td className="text-right px-3 py-2.5 text-gray-300 font-mono whitespace-nowrap">
                          {formatPrice(item.settlement)}
                        </td>
                        <td className="text-right px-3 py-2.5 text-gray-400 font-mono whitespace-nowrap">
                          {formatPrice(item.pre_settlement)}
                        </td>
                      </>
                    )}
                    {/* Pre-close */}
                    <td className="text-right px-3 py-2.5 text-gray-400 font-mono whitespace-nowrap">
                      {formatPrice(item.pre_close)}
                    </td>
                    {/* CN-specific columns */}
                    {isCN && (
                      <>
                        <td className="text-right px-3 py-2.5 text-gray-300 font-mono whitespace-nowrap">
                          {formatMoney(item.turnover)}
                        </td>
                        <td className="text-right px-3 py-2.5 text-gray-400 font-mono whitespace-nowrap">
                          {item.turnover_rate ? item.turnover_rate.toFixed(2) + '%' : '-'}
                        </td>
                      </>
                    )}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
