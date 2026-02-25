import React, { useState, useEffect, useRef } from 'react'
import type { WatchlistItem } from '../hooks/useWatchlist'
import type { ActiveView, StrategyWeights } from '../types'
import { updateConfig } from '../api'

interface Props {
  usStocks: string[]
  cnStocks: string[]
  futuresContracts: string[]
  days: number
  sentimentWeight: number
  technicalWeight: number
  volumeWeight: number
  futuresStrategy: StrategyWeights | null
  deepseekApiKey: string
  deepseekModel: string
  tqsdkUser: string
  tqsdkConnected: boolean
  tqsdkTradeMode: string
  tqsdkBrokerId: string
  tqsdkBrokerAccount: string
  loading: boolean
  watchlist: WatchlistItem[]
  onAnalyze: (params: {
    usStocks: string[]
    cnStocks: string[]
    futuresContracts: string[]
    days: number
    sentimentWeight: number
    technicalWeight: number
    volumeWeight: number
    futuresDays: number
    futuresSentimentWeight: number
    futuresTechnicalWeight: number
    futuresVolumeWeight: number
  }) => void
  onRemoveFromWatchlist: (ticker: string) => void
  activeView: ActiveView
  onViewChange: (view: ActiveView) => void
  onSearch: (query: string, market: string) => void
  onAddTicker: (code: string, market: string) => void
  onTqStatusRefresh?: () => void
}

type SidebarTab = 'config' | 'watchlist' | 'trading'
type MarketModule = 'stock' | 'futures'

function StarIcon({ className }: { className?: string }) {
  return (
    <svg className={className || 'w-4 h-4'} fill="currentColor" viewBox="0 0 20 20">
      <path d="M9.049 2.927c.3-.921 1.603-.921 1.902 0l1.07 3.292a1 1 0 00.95.69h3.462c.969 0 1.371 1.24.588 1.81l-2.8 2.034a1 1 0 00-.364 1.118l1.07 3.292c.3.921-.755 1.688-1.54 1.118l-2.8-2.034a1 1 0 00-1.175 0l-2.8 2.034c-.784.57-1.838-.197-1.539-1.118l1.07-3.292a1 1 0 00-.364-1.118L2.98 8.72c-.783-.57-.38-1.81.588-1.81h3.461a1 1 0 00.951-.69l1.07-3.292z" />
    </svg>
  )
}

function SearchBar({
  placeholder,
  onSearch,
  accentColor = 'blue',
}: {
  placeholder: string
  onSearch: (query: string) => void
  accentColor?: 'blue' | 'orange'
}) {
  const [value, setValue] = useState('')
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const ringClass = accentColor === 'orange'
    ? 'focus:ring-orange-500 focus:border-orange-500'
    : 'focus:ring-blue-500 focus:border-blue-500'

  const handleChange = (v: string) => {
    setValue(v)
    if (timerRef.current) clearTimeout(timerRef.current)
    if (v.trim()) {
      timerRef.current = setTimeout(() => onSearch(v.trim()), 400)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && value.trim()) {
      if (timerRef.current) clearTimeout(timerRef.current)
      onSearch(value.trim())
    }
  }

  return (
    <div className="relative">
      <svg className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-500 pointer-events-none"
        fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
      </svg>
      <input
        type="text"
        value={value}
        onChange={e => handleChange(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        className={`w-full bg-gray-800 border border-gray-700 rounded-lg pl-8 pr-8 py-2 text-sm
          text-gray-200 focus:outline-none focus:ring-1 ${ringClass} placeholder-gray-600`}
      />
      {value && (
        <button
          onClick={() => { setValue(''); }}
          className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-600 hover:text-gray-400"
        >
          <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      )}
    </div>
  )
}

function TickerTagList({
  items,
  onChange,
  color = 'blue',
}: {
  items: string[]
  onChange: (items: string[]) => void
  color?: 'blue' | 'orange'
}) {
  const tagBg = color === 'orange'
    ? 'bg-orange-900/30 text-orange-300'
    : 'bg-blue-900/30 text-blue-300'

  if (items.length === 0) {
    return <p className="text-[10px] text-gray-600">暂无已选，请通过搜索添加</p>
  }
  return (
    <div className="flex flex-wrap gap-1">
      {items.map(code => (
        <span key={code} className={`inline-flex items-center gap-1 text-xs font-mono px-2 py-0.5 rounded ${tagBg}`}>
          {code}
          <button
            onClick={() => onChange(items.filter(t => t !== code))}
            className="hover:text-white transition-colors ml-0.5"
          >
            <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </span>
      ))}
    </div>
  )
}

export default function Sidebar({
  usStocks: initialUS,
  cnStocks: initialCN,
  futuresContracts: initialFutures,
  days: initialDays,
  sentimentWeight: initialSW,
  technicalWeight: initialTW,
  volumeWeight: initialVW,
  futuresStrategy: initialFS,
  deepseekApiKey: initialDSKey,
  deepseekModel: initialDSModel,
  tqsdkUser: initialTqUser,
  tqsdkConnected,
  tqsdkTradeMode: initialTqMode,
  tqsdkBrokerId: initialBrokerId,
  tqsdkBrokerAccount: initialBrokerAcct,
  loading,
  watchlist,
  onAnalyze,
  onRemoveFromWatchlist,
  activeView,
  onViewChange,
  onSearch,
  onAddTicker,
  onTqStatusRefresh,
}: Props) {
  const [tab, setTab] = useState<SidebarTab>('config')
  const [marketModule, _setMarketModule] = useState<MarketModule>(
    () => (localStorage.getItem('ss-market-module') as MarketModule) || 'stock'
  )
  const setMarketModule = (m: MarketModule) => {
    _setMarketModule(m)
    localStorage.setItem('ss-market-module', m)
  }

  // Stock inputs (array-based for search component)
  const [usList, setUsList] = useState<string[]>(initialUS)
  const [cnList, setCnList] = useState<string[]>(initialCN)
  const [days, setDays] = useState(initialDays)
  const [sw, setSW] = useState(initialSW)
  const [tw, setTW] = useState(initialTW)
  const [vw, setVW] = useState(initialVW)

  // DeepSeek
  const [dsKey, setDsKey] = useState(initialDSKey)
  const [dsModel, setDsModel] = useState(initialDSModel || 'deepseek-chat')
  const [dsSaved, setDsSaved] = useState(false)

  // TqSdk
  const [tqUser, setTqUser] = useState(initialTqUser || '')
  const [tqPassword, setTqPassword] = useState('')
  const [tqMode, setTqMode] = useState<'sim' | 'live'>((initialTqMode as 'sim' | 'live') || 'sim')
  const [tqBrokerId, setTqBrokerId] = useState(initialBrokerId || '')
  const [tqBrokerAcct, setTqBrokerAcct] = useState(initialBrokerAcct || '')
  const [tqBrokerPwd, setTqBrokerPwd] = useState('')
  const [tqSaved, setTqSaved] = useState(false)

  // Futures inputs (array-based for search component)
  const [futuresList, setFuturesList] = useState<string[]>(initialFutures)
  const [fDays, setFDays] = useState(initialFS?.news_lookback_days ?? 3)
  const [fSW, setFSW] = useState(initialFS?.sentiment_weight ?? 0.2)
  const [fTW, setFTW] = useState(initialFS?.technical_weight ?? 0.6)
  const [fVW, setFVW] = useState(initialFS?.volume_weight ?? 0.2)

  // Sync from backend config
  useEffect(() => { setUsList(initialUS) }, [initialUS.join(',')])
  useEffect(() => { setCnList(initialCN) }, [initialCN.join(',')])
  useEffect(() => { setFuturesList(initialFutures) }, [initialFutures.join(',')])
  useEffect(() => { setDays(initialDays) }, [initialDays])
  useEffect(() => { setSW(initialSW) }, [initialSW])
  useEffect(() => { setTW(initialTW) }, [initialTW])
  useEffect(() => { setVW(initialVW) }, [initialVW])
  useEffect(() => {
    if (initialFS) {
      setFDays(initialFS.news_lookback_days)
      setFSW(initialFS.sentiment_weight)
      setFTW(initialFS.technical_weight)
      setFVW(initialFS.volume_weight)
    }
  }, [initialFS?.sentiment_weight, initialFS?.technical_weight, initialFS?.volume_weight])
  useEffect(() => { setDsKey(initialDSKey) }, [initialDSKey])
  useEffect(() => { setDsModel(initialDSModel || 'deepseek-chat') }, [initialDSModel])
  useEffect(() => { setTqUser(initialTqUser || '') }, [initialTqUser])
  useEffect(() => { setTqMode((initialTqMode as 'sim' | 'live') || 'sim') }, [initialTqMode])
  useEffect(() => { setTqBrokerId(initialBrokerId || '') }, [initialBrokerId])

  // Normalized weights for stocks
  const total = sw + tw + vw
  const normSW = total > 0 ? sw / total : 0.33
  const normTW = total > 0 ? tw / total : 0.33
  const normVW = total > 0 ? vw / total : 0.34

  // Normalized weights for futures
  const fTotal = fSW + fTW + fVW
  const normFSW = fTotal > 0 ? fSW / fTotal : 0.2
  const normFTW = fTotal > 0 ? fTW / fTotal : 0.6
  const normFVW = fTotal > 0 ? fVW / fTotal : 0.2

  const saveWeights = () => {
    updateConfig({
      sentiment_weight: normSW,
      technical_weight: normTW,
      volume_weight: normVW,
      news_lookback_days: days,
      futures_sentiment_weight: normFSW,
      futures_technical_weight: normFTW,
      futures_volume_weight: normFVW,
      futures_news_lookback_days: fDays,
      deepseek_api_key: dsKey,
      deepseek_model: dsModel,
    }).catch(err => console.warn('保存策略权重失败:', err))
  }

  const saveDeepSeekKey = () => {
    updateConfig({ deepseek_api_key: dsKey, deepseek_model: dsModel })
      .then(() => { setDsSaved(true); setTimeout(() => setDsSaved(false), 2000) })
      .catch(err => console.warn('保存 DeepSeek 配置失败:', err))
  }

  const saveTqSdk = () => {
    if (!tqUser || !tqPassword) return
    const payload: Record<string, string> = {
      tqsdk_user: tqUser,
      tqsdk_password: tqPassword,
      tqsdk_trade_mode: tqMode,
    }
    if (tqMode === 'live') {
      payload.tqsdk_broker_id = tqBrokerId
      payload.tqsdk_broker_account = tqBrokerAcct
      payload.tqsdk_broker_password = tqBrokerPwd
    }
    updateConfig(payload)
      .then(() => {
        setTqSaved(true)
        setTimeout(() => setTqSaved(false), 3000)
        // Quick-poll status updates after saving (TqSdk restarts in background)
        if (onTqStatusRefresh) {
          const polls = [2000, 4000, 8000, 12000]
          polls.forEach(ms => setTimeout(onTqStatusRefresh!, ms))
        }
      })
      .catch(err => console.warn('保存天勤配置失败:', err))
  }

  const handleSubmit = () => {
    const usStocks = usList
    const cnStocks = cnList
    const futuresContracts = futuresList

    const sendUS = marketModule === 'stock' ? usStocks : []
    const sendCN = marketModule === 'stock' ? cnStocks : []
    const sendFutures = marketModule === 'futures' ? futuresContracts : []

    updateConfig({
      us_stocks: usStocks,
      cn_stocks: cnStocks,
      futures_contracts: futuresContracts,
      sentiment_weight: normSW,
      technical_weight: normTW,
      volume_weight: normVW,
      news_lookback_days: days,
      futures_sentiment_weight: normFSW,
      futures_technical_weight: normFTW,
      futures_volume_weight: normFVW,
      futures_news_lookback_days: fDays,
      deepseek_api_key: dsKey,
      deepseek_model: dsModel,
    }).catch(err => console.warn('保存配置失败:', err))
    onAnalyze({
      usStocks: sendUS,
      cnStocks: sendCN,
      futuresContracts: sendFutures,
      days,
      sentimentWeight: normSW,
      technicalWeight: normTW,
      volumeWeight: normVW,
      futuresDays: fDays,
      futuresSentimentWeight: normFSW,
      futuresTechnicalWeight: normFTW,
      futuresVolumeWeight: normFVW,
    })
  }

  const handleAnalyzeWatchlistWithConfig = () => {
    const wlUS = watchlist.filter(i => i.market === 'US').map(i => i.ticker)
    const wlCN = watchlist.filter(i => i.market === 'CN').map(i => i.ticker)
    const wlFutures = watchlist.filter(i => i.market === 'FUTURES').map(i => i.ticker)
    saveWeights()
    onAnalyze({
      usStocks: wlUS,
      cnStocks: wlCN,
      futuresContracts: wlFutures,
      days,
      sentimentWeight: normSW,
      technicalWeight: normTW,
      volumeWeight: normVW,
      futuresDays: fDays,
      futuresSentimentWeight: normFSW,
      futuresTechnicalWeight: normFTW,
      futuresVolumeWeight: normFVW,
    })
  }

  const watchlistUS = watchlist.filter(i => i.market === 'US')
  const watchlistCN = watchlist.filter(i => i.market === 'CN')
  const watchlistFutures = watchlist.filter(i => i.market === 'FUTURES')

  const loadWatchlistToConfig = () => {
    setUsList(watchlistUS.map(i => i.ticker))
    setCnList(watchlistCN.map(i => i.ticker))
    setFuturesList(watchlistFutures.map(i => i.ticker))
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
        <button
          onClick={() => onViewChange('quant')}
          className={`flex-1 px-2 py-2 text-[11px] font-medium transition-colors
            ${activeView === 'quant'
              ? 'text-cyan-400 border-b-2 border-cyan-400 bg-cyan-900/10'
              : 'text-gray-600 hover:text-gray-400'}`}
        >
          量化
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
          <div className="p-4 space-y-4">
            {/* DeepSeek AI Config */}
            <div className="bg-purple-900/10 border border-purple-800/30 rounded-lg p-3 space-y-2">
              <div className="flex items-center justify-between">
                <p className="text-[11px] text-purple-400 font-medium">DeepSeek AI 分析</p>
                {dsKey ? (
                  <span className="text-[9px] px-1.5 py-0.5 rounded bg-green-900/40 text-green-400">已配置</span>
                ) : (
                  <span className="text-[9px] px-1.5 py-0.5 rounded bg-gray-800 text-gray-500">未配置</span>
                )}
              </div>
              <input
                type="password"
                value={dsKey}
                onChange={e => setDsKey(e.target.value)}
                placeholder="输入 DeepSeek API Key"
                className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs
                  text-gray-200 font-mono focus:outline-none focus:ring-1 focus:ring-purple-500
                  focus:border-purple-500 placeholder-gray-600"
              />
              <div className="flex gap-2">
                <select
                  value={dsModel}
                  onChange={e => setDsModel(e.target.value)}
                  className="flex-1 bg-gray-800 border border-gray-700 rounded px-2 py-1 text-[10px]
                    text-gray-300 focus:outline-none focus:ring-1 focus:ring-purple-500"
                >
                  <option value="deepseek-chat">deepseek-chat</option>
                  <option value="deepseek-reasoner">deepseek-reasoner</option>
                </select>
                <button
                  onClick={saveDeepSeekKey}
                  className="px-3 py-1 text-[10px] rounded bg-purple-700 hover:bg-purple-600
                    text-white transition-colors"
                >
                  {dsSaved ? '已保存' : '保存'}
                </button>
              </div>
              {!dsKey && (
                <p className="text-[9px] text-gray-600 leading-tight">
                  配置后将使用 AI 进行新闻、舆情、技术分析和投资建议，未配置则使用本地 NLP 模型
                </p>
              )}
            </div>

            {/* Module switcher: Stock vs Futures */}
            <div className="flex rounded-lg bg-gray-800/60 p-0.5">
              <button
                onClick={() => setMarketModule('stock')}
                className={`flex-1 py-1.5 text-xs font-medium rounded-md transition-all
                  ${marketModule === 'stock'
                    ? 'bg-blue-600 text-white shadow-sm'
                    : 'text-gray-400 hover:text-gray-200'}`}
              >
                股票
              </button>
              <button
                onClick={() => setMarketModule('futures')}
                className={`flex-1 py-1.5 text-xs font-medium rounded-md transition-all
                  ${marketModule === 'futures'
                    ? 'bg-orange-600 text-white shadow-sm'
                    : 'text-gray-400 hover:text-gray-200'}`}
              >
                期货
              </button>
            </div>

            {/* ---- Stock module ---- */}
            {marketModule === 'stock' && (
              <div className="space-y-5">
                {/* Search bar */}
                <div>
                  <label className="block text-xs font-medium text-gray-400 mb-1.5">搜索股票</label>
                  <SearchBar
                    placeholder="输入代码或名称，如 茅台、AAPL"
                    onSearch={(q) => onSearch(q, '')}
                    accentColor="blue"
                  />
                </div>

                {/* Selected US stocks */}
                <div>
                  <label className="block text-xs font-medium text-gray-400 mb-1.5">
                    美股 <span className="text-gray-600">({usList.length})</span>
                  </label>
                  <TickerTagList items={usList} onChange={setUsList} color="blue" />
                </div>

                {/* Selected CN stocks */}
                <div>
                  <label className="block text-xs font-medium text-gray-400 mb-1.5">
                    A 股 <span className="text-gray-600">({cnList.length})</span>
                  </label>
                  <TickerTagList items={cnList} onChange={setCnList} color="blue" />
                </div>

                <div>
                  <label className="block text-xs font-medium text-gray-400 mb-1.5">
                    新闻回溯: <span className="text-white font-semibold">{days} 天</span>
                  </label>
                  <input
                    type="range" min={1} max={14} value={days}
                    onChange={e => setDays(Number(e.target.value))}
                    className="w-full accent-blue-500"
                  />
                </div>

                <div className="space-y-3">
                  <p className="text-xs font-medium text-gray-400">股票策略权重</p>
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

            {/* ---- Futures module ---- */}
            {marketModule === 'futures' && (
              <div className="space-y-5">
                {/* TqSdk config card */}
                <div className="bg-cyan-900/10 border border-cyan-800/30 rounded-lg p-3 space-y-2">
                  <div className="flex items-center justify-between">
                    <p className="text-[11px] text-cyan-400 font-medium">天勤量化 (TqSdk)</p>
                    <div className="flex items-center gap-1.5">
                      {tqsdkConnected && (
                        <span className={`text-[9px] px-1.5 py-0.5 rounded flex items-center gap-1 ${
                          tqMode === 'live'
                            ? 'bg-red-900/40 text-red-400'
                            : 'bg-green-900/40 text-green-400'
                        }`}>
                          <span className={`w-1.5 h-1.5 rounded-full animate-pulse ${
                            tqMode === 'live' ? 'bg-red-400' : 'bg-green-400'
                          }`} />
                          {tqMode === 'live' ? '实盘' : '模拟盘'}
                        </span>
                      )}
                      {!tqsdkConnected && tqUser && (
                        <span className="text-[9px] px-1.5 py-0.5 rounded bg-yellow-900/40 text-yellow-400">未连接</span>
                      )}
                      {!tqsdkConnected && !tqUser && (
                        <span className="text-[9px] px-1.5 py-0.5 rounded bg-gray-800 text-gray-500">未配置</span>
                      )}
                    </div>
                  </div>

                  {/* Mode switcher */}
                  <div className="flex rounded bg-gray-800/80 p-0.5">
                    <button
                      onClick={() => setTqMode('sim')}
                      className={`flex-1 py-1 text-[10px] font-medium rounded transition-all
                        ${tqMode === 'sim'
                          ? 'bg-cyan-700 text-white shadow-sm'
                          : 'text-gray-400 hover:text-gray-200'}`}
                    >
                      模拟盘
                    </button>
                    <button
                      onClick={() => setTqMode('live')}
                      className={`flex-1 py-1 text-[10px] font-medium rounded transition-all
                        ${tqMode === 'live'
                          ? 'bg-red-700 text-white shadow-sm'
                          : 'text-gray-400 hover:text-gray-200'}`}
                    >
                      实盘
                    </button>
                  </div>

                  {/* Quick login */}
                  <input
                    type="text"
                    value={tqUser}
                    onChange={e => setTqUser(e.target.value)}
                    placeholder="快期账户（手机号/用户名）"
                    className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs
                      text-gray-200 focus:outline-none focus:ring-1 focus:ring-cyan-500
                      focus:border-cyan-500 placeholder-gray-600"
                  />
                  <input
                    type="password"
                    value={tqPassword}
                    onChange={e => setTqPassword(e.target.value)}
                    placeholder="快期密码"
                    className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs
                      text-gray-200 focus:outline-none focus:ring-1 focus:ring-cyan-500
                      focus:border-cyan-500 placeholder-gray-600"
                  />

                  {/* Live trading fields */}
                  {tqMode === 'live' && (
                    <div className="space-y-2 pt-1 border-t border-red-900/30">
                      <p className="text-[9px] text-red-400 font-medium">实盘配置</p>
                      <input
                        type="text"
                        value={tqBrokerId}
                        onChange={e => setTqBrokerId(e.target.value)}
                        placeholder="期货公司 (如 H海通期货)"
                        className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs
                          text-gray-200 focus:outline-none focus:ring-1 focus:ring-red-500
                          focus:border-red-500 placeholder-gray-600"
                      />
                      <input
                        type="text"
                        value={tqBrokerAcct}
                        onChange={e => setTqBrokerAcct(e.target.value)}
                        placeholder="资金账号"
                        className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs
                          text-gray-200 focus:outline-none focus:ring-1 focus:ring-red-500
                          focus:border-red-500 placeholder-gray-600"
                      />
                      <input
                        type="password"
                        value={tqBrokerPwd}
                        onChange={e => setTqBrokerPwd(e.target.value)}
                        placeholder="交易密码"
                        className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs
                          text-gray-200 focus:outline-none focus:ring-1 focus:ring-red-500
                          focus:border-red-500 placeholder-gray-600"
                      />
                      <p className="text-[9px] text-red-400/70 leading-tight">
                        实盘交易涉及真实资金，请谨慎操作
                      </p>
                    </div>
                  )}

                  <button
                    onClick={saveTqSdk}
                    disabled={!tqUser || !tqPassword || (tqMode === 'live' && (!tqBrokerId || !tqBrokerAcct))}
                    className={`w-full py-1.5 text-[10px] rounded font-medium transition-colors
                      disabled:bg-gray-700 disabled:text-gray-500 text-white
                      ${tqMode === 'live'
                        ? 'bg-red-700 hover:bg-red-600'
                        : 'bg-cyan-700 hover:bg-cyan-600'}`}
                  >
                    {tqSaved ? '已保存，正在连接...' : tqMode === 'live' ? '连接实盘' : '连接模拟盘'}
                  </button>

                  <p className="text-[9px] text-gray-600 leading-tight">
                    {tqMode === 'sim'
                      ? '模拟盘使用虚拟资金，可安全测试策略'
                      : '实盘需填写期货公司和资金账号信息'
                    }
                    {' · '}
                    <a href="https://account.shinnytech.com/" target="_blank" rel="noreferrer"
                      className="text-cyan-500 hover:text-cyan-400">注册快期账户</a>
                  </p>
                </div>

                {/* AI analysis card */}
                <div className="bg-orange-900/10 border border-orange-800/30 rounded-lg p-3">
                  <p className="text-[11px] text-orange-400 font-medium mb-1">DeepSeek AI 期货分析</p>
                  <p className="text-[10px] text-gray-400 leading-relaxed">
                    AI 综合分析新闻舆情、技术指标、均线系统，<br />
                    自动给出交易建议（含进场价、止损、止盈）
                  </p>
                  <div className="mt-2 flex flex-wrap gap-1">
                    {['农产品', '化工', '金属', '能源', '股指'].map(s => (
                      <span key={s} className="text-[9px] px-1.5 py-0.5 rounded bg-orange-900/30 text-orange-300">
                        {s}
                      </span>
                    ))}
                  </div>
                </div>

                {/* Search bar */}
                <div>
                  <label className="block text-xs font-medium text-gray-400 mb-1.5">搜索期货</label>
                  <SearchBar
                    placeholder="输入品种名称，如 玉米、螺纹钢"
                    onSearch={(q) => onSearch(q, 'FUTURES')}
                    accentColor="orange"
                  />
                </div>

                {/* Selected futures */}
                <div>
                  <label className="block text-xs font-medium text-gray-400 mb-1.5">
                    已选合约 <span className="text-gray-600">({futuresList.length})</span>
                  </label>
                  <TickerTagList items={futuresList} onChange={setFuturesList} color="orange" />
                </div>

                <div>
                  <label className="block text-xs font-medium text-gray-400 mb-1.5">
                    新闻回溯: <span className="text-white font-semibold">{fDays} 天</span>
                  </label>
                  <input
                    type="range" min={1} max={14} value={fDays}
                    onChange={e => setFDays(Number(e.target.value))}
                    className="w-full accent-orange-500"
                  />
                </div>

                <div className="space-y-3">
                  <p className="text-xs font-medium text-gray-400">期货策略权重</p>
                  <p className="text-[10px] text-gray-600">期货偏重技术面（趋势跟随），舆情权重较低</p>
                  <div>
                    <div className="flex justify-between text-xs text-gray-500 mb-1">
                      <span>舆情</span>
                      <span className="text-gray-300">{(normFSW * 100).toFixed(0)}%</span>
                    </div>
                    <input
                      type="range" min={0} max={100} value={fSW * 100}
                      onChange={e => setFSW(Number(e.target.value) / 100)}
                      className="w-full accent-emerald-500"
                    />
                  </div>
                  <div>
                    <div className="flex justify-between text-xs text-gray-500 mb-1">
                      <span>技术面</span>
                      <span className="text-gray-300">{(normFTW * 100).toFixed(0)}%</span>
                    </div>
                    <input
                      type="range" min={0} max={100} value={fTW * 100}
                      onChange={e => setFTW(Number(e.target.value) / 100)}
                      className="w-full accent-orange-500"
                    />
                  </div>
                  <div>
                    <div className="flex justify-between text-xs text-gray-500 mb-1">
                      <span>新闻量</span>
                      <span className="text-gray-300">{(normFVW * 100).toFixed(0)}%</span>
                    </div>
                    <input
                      type="range" min={0} max={100} value={fVW * 100}
                      onChange={e => setFVW(Number(e.target.value) / 100)}
                      className="w-full accent-amber-500"
                    />
                  </div>
                </div>
              </div>
            )}
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

                {/* Futures watchlist */}
                {watchlistFutures.length > 0 && (
                  <div>
                    <p className="text-xs font-medium text-gray-400 mb-2">
                      期货 <span className="text-gray-600">({watchlistFutures.length})</span>
                    </p>
                    <div className="space-y-1">
                      {watchlistFutures.map(item => (
                        <div
                          key={item.ticker}
                          className="flex items-center justify-between px-2.5 py-1.5 rounded-lg
                            bg-gray-800/50 hover:bg-gray-800 transition-colors group"
                        >
                          <div className="flex items-center gap-2">
                            <StarIcon className="w-3.5 h-3.5 text-amber-400" />
                            <span className="text-sm font-mono text-white">{item.ticker}</span>
                            <span className="text-[10px] px-1 py-0.5 rounded bg-orange-900/40 text-orange-400">期货</span>
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
                <p>期货：佣金万1（双边）+ T+0</p>
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

        {activeView === 'quant' && (
          <div className="p-4 space-y-4">
            <div className="text-center py-6">
              <div className="text-3xl mb-2 opacity-30">&#x1F916;</div>
              <p className="text-gray-400 text-sm font-medium">量化交易</p>
              <p className="text-gray-600 text-xs mt-1">AI 分析驱动的自动交易系统</p>
            </div>
            <div className="space-y-2 text-xs text-gray-500">
              <div className="bg-gray-800/50 rounded-lg p-3">
                <p className="text-cyan-400 font-medium mb-1">工作原理</p>
                <p>定时调用 DeepSeek 分析期货行情，自动生成交易信号并通过天勤量化执行下单</p>
              </div>
              <div className="bg-gray-800/50 rounded-lg p-3">
                <p className="text-cyan-400 font-medium mb-1">风控规则</p>
                <p>信号阈值过滤、止损/止盈保护、最大持仓限制</p>
              </div>
              <div className="bg-gray-800/50 rounded-lg p-3">
                <p className="text-yellow-400 font-medium mb-1">当前模式</p>
                <p>模拟盘（TqSim），不涉及真实资金</p>
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
            className={`w-full font-semibold py-2.5 px-4 rounded-lg transition-colors text-sm
              flex items-center justify-center gap-2 disabled:bg-gray-700 disabled:text-gray-500
              ${marketModule === 'futures'
                ? 'bg-orange-600 hover:bg-orange-500 text-white'
                : 'bg-blue-600 hover:bg-blue-500 text-white'
              }`}
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
              marketModule === 'futures' ? '分析期货' : '分析股票'
            )}
          </button>
        )}
      </div>
    </aside>
  )
}
