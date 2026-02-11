import React, { useState } from 'react'
import type { WatchlistItem } from '../hooks/useWatchlist'
import type { ActiveView } from '../types'

interface Props {
  usStocks: string[]
  cnStocks: string[]
  days: number
  sentimentWeight: number
  technicalWeight: number
  volumeWeight: number
  loading: boolean
  watchlist: WatchlistItem[]
  onAnalyze: (params: {
    usStocks: string[]
    cnStocks: string[]
    days: number
    sentimentWeight: number
    technicalWeight: number
    volumeWeight: number
  }) => void
  onRemoveFromWatchlist: (ticker: string) => void
  activeView: ActiveView
  onViewChange: (view: ActiveView) => void
}

type SidebarTab = 'config' | 'watchlist' | 'trading'

function StarIcon({ className }: { className?: string }) {
  return (
    <svg className={className || 'w-4 h-4'} fill="currentColor" viewBox="0 0 20 20">
      <path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z" />
    </svg>
  )
}

export default function Sidebar({
  usStocks: initialUS,
  cnStocks: initialCN,
  days: initialDays,
  sentimentWeight: initialSW,
  technicalWeight: initialTW,
  volumeWeight: initialVW,
  loading,
  watchlist,
  onAnalyze,
  onRemoveFromWatchlist,
  activeView,
  onViewChange,
}: Props) {
  const [tab, setTab] = useState<SidebarTab>('config')
  const [usText, setUsText] = useState(initialUS.join('\n'))
  const [cnText, setCnText] = useState(initialCN.join('\n'))
  const [days, setDays] = useState(initialDays)
  const [sw, setSW] = useState(initialSW)
  const [tw, setTW] = useState(initialTW)
  const [vw, setVW] = useState(initialVW)

  const total = sw + tw + vw
  const normSW = total > 0 ? sw / total : 0.33
  const normTW = total > 0 ? tw / total : 0.33
  const normVW = total > 0 ? vw / total : 0.34

  const handleSubmit = () => {
    const usStocks = usText.split('\n').map(s => s.trim().toUpperCase()).filter(Boolean)
    const cnStocks = cnText.split('\n').map(s => s.trim()).filter(Boolean)
    onAnalyze({
      usStocks,
      cnStocks,
      days,
      sentimentWeight: normSW,
      technicalWeight: normTW,
      volumeWeight: normVW,
    })
  }

  // 分析自选股：使用当前表单配置的权重和天数
  const handleAnalyzeWatchlistWithConfig = () => {
    const wlUS = watchlist.filter(i => i.market === 'US').map(i => i.ticker)
    const wlCN = watchlist.filter(i => i.market === 'CN').map(i => i.ticker)
    onAnalyze({
      usStocks: wlUS,
      cnStocks: wlCN,
      days,
      sentimentWeight: normSW,
      technicalWeight: normTW,
      volumeWeight: normVW,
    })
  }

  const watchlistUS = watchlist.filter(i => i.market === 'US')
  const watchlistCN = watchlist.filter(i => i.market === 'CN')

  // Load watchlist items into the text areas
  const loadWatchlistToConfig = () => {
    setUsText(watchlistUS.map(i => i.ticker).join('\n'))
    setCnText(watchlistCN.map(i => i.ticker).join('\n'))
    setTab('config')
  }

  return (
    <aside className="w-72 bg-gray-900 border-r border-gray-800 flex flex-col h-full">
      {/* Header */}
      <div className="p-4 border-b border-gray-800">
        <h1 className="text-lg font-bold text-white tracking-tight">股票舆情策略</h1>
        <p className="text-xs text-gray-500 mt-0.5">基于新闻驱动的交易策略</p>
      </div>

      {/* View navigation */}
      <div className="flex border-b border-gray-800">
        <button
          onClick={() => onViewChange('analysis')}
          className={`flex-1 px-2 py-2 text-[11px] font-medium transition-colors
            ${activeView === 'analysis'
              ? 'text-blue-400 border-b-2 border-blue-400 bg-blue-900/10'
              : 'text-gray-600 hover:text-gray-400'}`}
        >
          分析
        </button>
        <button
          onClick={() => onViewChange('portfolio')}
          className={`flex-1 px-2 py-2 text-[11px] font-medium transition-colors
            ${activeView === 'portfolio'
              ? 'text-green-400 border-b-2 border-green-400 bg-green-900/10'
              : 'text-gray-600 hover:text-gray-400'}`}
        >
          模拟交易
        </button>
        <button
          onClick={() => onViewChange('backtest')}
          className={`flex-1 px-2 py-2 text-[11px] font-medium transition-colors
            ${activeView === 'backtest'
              ? 'text-purple-400 border-b-2 border-purple-400 bg-purple-900/10'
              : 'text-gray-600 hover:text-gray-400'}`}
        >
          回测
        </button>
      </div>

      {/* Tab switcher (only in analysis view) */}
      {activeView === 'analysis' && (
        <div className="flex border-b border-gray-800">
          <button
            onClick={() => setTab('config')}
            className={`flex-1 px-3 py-2 text-xs font-medium transition-colors
              ${tab === 'config'
                ? 'text-blue-400 border-b-2 border-blue-400 bg-blue-900/10'
                : 'text-gray-500 hover:text-gray-300'}`}
          >
            分析配置
          </button>
          <button
            onClick={() => setTab('watchlist')}
            className={`flex-1 px-3 py-2 text-xs font-medium transition-colors relative
              ${tab === 'watchlist'
                ? 'text-amber-400 border-b-2 border-amber-400 bg-amber-900/10'
                : 'text-gray-500 hover:text-gray-300'}`}
          >
            自选股
            {watchlist.length > 0 && (
              <span className="ml-1.5 inline-flex items-center justify-center w-4 h-4 text-[10px] rounded-full bg-amber-500/20 text-amber-400">
                {watchlist.length}
              </span>
            )}
          </button>
        </div>
      )}

      {/* Tab content */}
      <div className="flex-1 overflow-y-auto">
        {activeView === 'analysis' && tab === 'config' && (
          <div className="p-4 space-y-5">
            {/* US Stocks */}
            <div>
              <label className="block text-xs font-medium text-gray-400 mb-1.5">
                美股代码 <span className="text-gray-600">（每行一个）</span>
              </label>
              <textarea
                value={usText}
                onChange={e => setUsText(e.target.value)}
                rows={4}
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm
                  text-gray-200 font-mono focus:outline-none focus:ring-1 focus:ring-blue-500
                  focus:border-blue-500 resize-none"
                placeholder="AAPL&#10;TSLA&#10;NVDA"
              />
            </div>

            {/* CN Stocks */}
            <div>
              <label className="block text-xs font-medium text-gray-400 mb-1.5">
                A股代码 <span className="text-gray-600">（每行一个）</span>
              </label>
              <textarea
                value={cnText}
                onChange={e => setCnText(e.target.value)}
                rows={4}
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm
                  text-gray-200 font-mono focus:outline-none focus:ring-1 focus:ring-blue-500
                  focus:border-blue-500 resize-none"
                placeholder="600519&#10;000858&#10;300750"
              />
            </div>

            {/* Lookback days */}
            <div>
              <label className="block text-xs font-medium text-gray-400 mb-1.5">
                新闻回溯: <span className="text-white font-semibold">{days} 天</span>
              </label>
              <input
                type="range"
                min={1}
                max={14}
                value={days}
                onChange={e => setDays(Number(e.target.value))}
                className="w-full accent-blue-500"
              />
            </div>

            {/* Weights */}
            <div className="space-y-3">
              <p className="text-xs font-medium text-gray-400">策略权重</p>

              <div>
                <div className="flex justify-between text-xs text-gray-500 mb-1">
                  <span>舆情</span>
                  <span className="text-gray-300">{(normSW * 100).toFixed(0)}%</span>
                </div>
                <input
                  type="range" min={0} max={100} value={sw * 100}
                  onChange={e => setSW(Number(e.target.value) / 100)}
                  className="w-full accent-emerald-500"
                />
              </div>

              <div>
                <div className="flex justify-between text-xs text-gray-500 mb-1">
                  <span>技术面</span>
                  <span className="text-gray-300">{(normTW * 100).toFixed(0)}%</span>
                </div>
                <input
                  type="range" min={0} max={100} value={tw * 100}
                  onChange={e => setTW(Number(e.target.value) / 100)}
                  className="w-full accent-blue-500"
                />
              </div>

              <div>
                <div className="flex justify-between text-xs text-gray-500 mb-1">
                  <span>新闻量</span>
                  <span className="text-gray-300">{(normVW * 100).toFixed(0)}%</span>
                </div>
                <input
                  type="range" min={0} max={100} value={vw * 100}
                  onChange={e => setVW(Number(e.target.value) / 100)}
                  className="w-full accent-amber-500"
                />
              </div>
            </div>
          </div>
        )}

        {activeView === 'analysis' && tab === 'watchlist' && (
          <div className="p-4">
            {watchlist.length === 0 ? (
              <div className="text-center py-8">
                <StarIcon className="w-8 h-8 text-gray-700 mx-auto mb-3" />
                <p className="text-gray-500 text-sm mb-1">暂无自选股</p>
                <p className="text-gray-600 text-xs">分析后在结果表中点击星标添加</p>
              </div>
            ) : (
              <div className="space-y-4">
                {/* US watchlist */}
                {watchlistUS.length > 0 && (
                  <div>
                    <p className="text-xs font-medium text-gray-400 mb-2">
                      美股 <span className="text-gray-600">({watchlistUS.length})</span>
                    </p>
                    <div className="space-y-1">
                      {watchlistUS.map(item => (
                        <div
                          key={item.ticker}
                          className="flex items-center justify-between px-2.5 py-1.5 rounded-lg
                            bg-gray-800/50 hover:bg-gray-800 transition-colors group"
                        >
                          <div className="flex items-center gap-2">
                            <StarIcon className="w-3.5 h-3.5 text-amber-400" />
                            <span className="text-sm font-mono text-white">{item.ticker}</span>
                            <span className="text-[10px] px-1 py-0.5 rounded bg-blue-900/40 text-blue-400">美股</span>
                          </div>
                          <button
                            onClick={() => onRemoveFromWatchlist(item.ticker)}
                            className="text-gray-600 hover:text-red-400 transition-colors opacity-0 group-hover:opacity-100"
                            title="移除"
                          >
                            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                            </svg>
                          </button>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* CN watchlist */}
                {watchlistCN.length > 0 && (
                  <div>
                    <p className="text-xs font-medium text-gray-400 mb-2">
                      A股 <span className="text-gray-600">({watchlistCN.length})</span>
                    </p>
                    <div className="space-y-1">
                      {watchlistCN.map(item => (
                        <div
                          key={item.ticker}
                          className="flex items-center justify-between px-2.5 py-1.5 rounded-lg
                            bg-gray-800/50 hover:bg-gray-800 transition-colors group"
                        >
                          <div className="flex items-center gap-2">
                            <StarIcon className="w-3.5 h-3.5 text-amber-400" />
                            <span className="text-sm font-mono text-white">{item.ticker}</span>
                            <span className="text-[10px] px-1 py-0.5 rounded bg-red-900/40 text-red-400">A股</span>
                          </div>
                          <button
                            onClick={() => onRemoveFromWatchlist(item.ticker)}
                            className="text-gray-600 hover:text-red-400 transition-colors opacity-0 group-hover:opacity-100"
                            title="移除"
                          >
                            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                            </svg>
                          </button>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Action buttons */}
                <div className="pt-2 space-y-2">
                  <button
                    onClick={loadWatchlistToConfig}
                    className="w-full text-xs text-gray-400 hover:text-white bg-gray-800/50 hover:bg-gray-800
                      py-2 px-3 rounded-lg transition-colors text-center"
                  >
                    导入到分析配置
                  </button>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Portfolio / Backtest sidebar info */}
        {activeView === 'portfolio' && (
          <div className="p-4 space-y-4">
            <div className="text-center py-6">
              <div className="text-3xl mb-2 opacity-30">&#x1F4B0;</div>
              <p className="text-gray-400 text-sm font-medium">模拟交易</p>
              <p className="text-gray-600 text-xs mt-1">管理虚拟持仓、查看交易记录</p>
            </div>
            <div className="space-y-2 text-xs text-gray-500">
              <div className="bg-gray-800/50 rounded-lg p-3">
                <p className="text-gray-400 font-medium mb-1">手动交易</p>
                <p>在分析页面选择股票后点击「交易」按钮</p>
              </div>
              <div className="bg-gray-800/50 rounded-lg p-3">
                <p className="text-gray-400 font-medium mb-1">一键跟单</p>
                <p>根据分析信号自动计算仓位和方向</p>
              </div>
              <div className="bg-gray-800/50 rounded-lg p-3">
                <p className="text-gray-400 font-medium mb-1">仿真规则</p>
                <p>A 股：佣金万2.5 + 印花税0.05% + T+1</p>
                <p>美股：零佣金 + T+0</p>
              </div>
            </div>
          </div>
        )}

        {activeView === 'backtest' && (
          <div className="p-4 space-y-4">
            <div className="text-center py-6">
              <div className="text-3xl mb-2 opacity-30">&#x1F4CA;</div>
              <p className="text-gray-400 text-sm font-medium">策略回测</p>
              <p className="text-gray-600 text-xs mt-1">在历史数据上验证交易策略</p>
            </div>
            <div className="space-y-2 text-xs text-gray-500">
              <div className="bg-gray-800/50 rounded-lg p-3">
                <p className="text-gray-400 font-medium mb-1">回测说明</p>
                <p>基于技术指标口诀规则，在历史价格数据上模拟买卖操作</p>
              </div>
              <div className="bg-gray-800/50 rounded-lg p-3">
                <p className="text-gray-400 font-medium mb-1">关键指标</p>
                <p>总收益率、年化收益、最大回撤、夏普比率、胜率、盈亏比</p>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Bottom buttons */}
      <div className="p-4 border-t border-gray-800 space-y-2">
        {activeView === 'analysis' && tab === 'watchlist' && watchlist.length > 0 && (
          <button
            onClick={handleAnalyzeWatchlistWithConfig}
            disabled={loading}
            className="w-full bg-amber-600 hover:bg-amber-500 disabled:bg-gray-700 disabled:text-gray-500
              text-white font-semibold py-2.5 px-4 rounded-lg transition-colors text-sm
              flex items-center justify-center gap-2"
          >
            {loading ? (
              <>
                <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                分析中...
              </>
            ) : (
              <>
                <StarIcon className="w-4 h-4" />
                分析自选股
              </>
            )}
          </button>
        )}
        {activeView === 'analysis' && (
          <button
            onClick={handleSubmit}
            disabled={loading}
            className="w-full bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 disabled:text-gray-500
              text-white font-semibold py-2.5 px-4 rounded-lg transition-colors text-sm
              flex items-center justify-center gap-2"
          >
            {loading ? (
              <>
                <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                分析中...
              </>
            ) : (
              '开始分析'
            )}
          </button>
        )}
      </div>
    </aside>
  )
}
