import React, { useState, useEffect, useCallback, useRef } from 'react'
import type { StockAnalysis, AppConfig, ActiveView } from './types'
import { getConfig, analyzeStocks, healthCheck, getTqStatus, searchTickerDetails, type SearchDetailItem } from './api'
import { useWatchlist } from './hooks/useWatchlist'
import Sidebar from './components/Sidebar'
import SummaryTable from './components/SummaryTable'
import StockCard from './components/StockCard'
import PortfolioDashboard from './components/PortfolioDashboard'
import BacktestPanel from './components/BacktestPanel'
import TradeModal from './components/TradeModal'
import SearchResultsPanel from './components/SearchResultsPanel'
import QuantTradingPanel from './components/QuantTradingPanel'

type Status = 'connecting' | 'ready' | 'error'

function useElapsedTimer(active: boolean) {
  const [elapsed, setElapsed] = useState(0)
  const startRef = useRef(0)

  useEffect(() => {
    if (!active) {
      setElapsed(0)
      return
    }
    startRef.current = Date.now()
    setElapsed(0)
    const interval = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startRef.current) / 1000))
    }, 1000)
    return () => clearInterval(interval)
  }, [active])

  return elapsed
}

function formatElapsed(s: number): string {
  if (s < 60) return `${s} 秒`
  const m = Math.floor(s / 60)
  const sec = s % 60
  return `${m} 分 ${sec} 秒`
}

export default function App() {
  const [status, setStatus] = useState<Status>('connecting')
  const [config, setConfig] = useState<AppConfig | null>(null)
  const [results, setResults] = useState<StockAnalysis[]>([])
  const [selectedTicker, _setSelectedTicker] = useState<string | null>(
    () => localStorage.getItem('ss-selected-ticker')
  )
  const setSelectedTicker = (t: string | null) => {
    _setSelectedTicker(t)
    if (t) localStorage.setItem('ss-selected-ticker', t)
    else localStorage.removeItem('ss-selected-ticker')
  }
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [stockCount, setStockCount] = useState(0)
  const elapsed = useElapsedTimer(loading)
  const watchlist = useWatchlist()

  // View switching: analysis | portfolio | backtest
  const [activeView, setActiveView] = useState<ActiveView>('analysis')

  // Search state
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<SearchDetailItem[]>([])
  const [searchLoading, setSearchLoading] = useState(false)
  const [showSearch, setShowSearch] = useState(false)

  // Trade modal
  const [tradeModalAnalysis, setTradeModalAnalysis] = useState<StockAnalysis | null>(null)
  const [portfolioCash, setPortfolioCash] = useState(0)
  const [currentHolding, setCurrentHolding] = useState(0)
  const [portfolioRefreshKey, setPortfolioRefreshKey] = useState(0)

  // Health check on mount
  useEffect(() => {
    let cancelled = false
    let attempts = 0

    const check = async () => {
      while (!cancelled && attempts < 120) {
        attempts++
        const ok = await healthCheck()
        if (ok) {
          if (!cancelled) {
            setStatus('ready')
            // Load config
            try {
              const cfg = await getConfig()
              setConfig(cfg)
            } catch (e) {
              console.error('Failed to load config:', e)
            }
          }
          return
        }
        await new Promise(r => setTimeout(r, 500))
      }
      if (!cancelled) setStatus('error')
    }

    check()
    return () => { cancelled = true }
  }, [])

  // Poll TqSdk connection status every 5s
  useEffect(() => {
    if (status !== 'ready') return
    const timer = setInterval(async () => {
      try {
        const st = await getTqStatus()
        setConfig(prev => {
          if (!prev) return prev
          if (prev.tqsdk_connected === st.tqsdk_connected &&
              prev.tqsdk_trade_mode === st.tqsdk_trade_mode) return prev
          return { ...prev, tqsdk_connected: st.tqsdk_connected, tqsdk_trade_mode: st.tqsdk_trade_mode }
        })
      } catch { /* ignore */ }
    }, 5000)
    return () => clearInterval(timer)
  }, [status])

  const refreshTqStatus = useCallback(async () => {
    try {
      const st = await getTqStatus()
      setConfig(prev => {
        if (!prev) return prev
        if (prev.tqsdk_connected === st.tqsdk_connected &&
            prev.tqsdk_trade_mode === st.tqsdk_trade_mode) return prev
        return { ...prev, tqsdk_connected: st.tqsdk_connected, tqsdk_trade_mode: st.tqsdk_trade_mode }
      })
    } catch { /* ignore */ }
  }, [])

  const handleAnalyze = useCallback(async (params: {
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
  }) => {
    const total = params.usStocks.length + params.cnStocks.length + params.futuresContracts.length
    if (total === 0) {
      setError('请至少输入一个股票/期货代码')
      return
    }

    setActiveView('analysis')
    setLoading(true)
    setStockCount(total)
    setError(null)
    setResults([])
    setSelectedTicker(null)

    try {
      const data = await analyzeStocks({
        us_stocks: params.usStocks,
        cn_stocks: params.cnStocks,
        futures_contracts: params.futuresContracts,
        days: params.days,
        sentiment_weight: params.sentimentWeight,
        technical_weight: params.technicalWeight,
        volume_weight: params.volumeWeight,
        futures_days: params.futuresDays,
        futures_sentiment_weight: params.futuresSentimentWeight,
        futures_technical_weight: params.futuresTechnicalWeight,
        futures_volume_weight: params.futuresVolumeWeight,
      })
      setResults(data)
      if (data.length > 0) {
        setSelectedTicker(data[0].ticker)
      }
      if (data.length === 0) {
        setError('未获取到分析结果，请检查股票代码是否正确')
      }
    } catch (e: any) {
      setError(e.message || '分析失败')
      console.error('Analysis error:', e)
    } finally {
      setLoading(false)
      setStockCount(0)
    }
  }, [])

  // Open trade modal
  const openTradeModal = useCallback(async (analysis: StockAnalysis) => {
    try {
      const { getPortfolio } = await import('./api')
      const portfolio = await getPortfolio()
      setPortfolioCash(portfolio.cash)
      const pos = portfolio.positions.find(p => p.ticker === analysis.ticker)
      setCurrentHolding(pos?.shares || 0)
    } catch {
      setPortfolioCash(100000)
      setCurrentHolding(0)
    }
    setTradeModalAnalysis(analysis)
  }, [])

  const closeTradeModal = useCallback(() => {
    setTradeModalAnalysis(null)
  }, [])

  const handleTradeComplete = useCallback(() => {
    setPortfolioRefreshKey(k => k + 1)
  }, [])

  // Hot-update a single ticker's analysis data (called by StockCard refresh)
  const handleAnalysisUpdate = useCallback((updated: StockAnalysis) => {
    setResults(prev => prev.map(r => r.ticker === updated.ticker ? updated : r))
  }, [])

  // Search: fetch detailed results from backend
  const handleSearch = useCallback(async (query: string, market: string) => {
    setSearchQuery(query)
    setShowSearch(true)
    setSearchLoading(true)
    setActiveView('analysis')
    try {
      const data = await searchTickerDetails(query, market)
      setSearchResults(data)
    } catch (e: any) {
      console.error('Search error:', e)
      setSearchResults([])
    } finally {
      setSearchLoading(false)
    }
  }, [])

  const handleSearchClose = useCallback(() => {
    setShowSearch(false)
    setSearchQuery('')
    setSearchResults([])
  }, [])

  const handleSearchSelect = useCallback((item: SearchDetailItem) => {
    const code = item.code.toUpperCase()
    const market = item.market.toUpperCase()

    setConfig(prev => {
      if (!prev) return prev
      const next = { ...prev }
      if (market === 'FUTURES') {
        if (!next.futures_contracts.includes(code)) {
          next.futures_contracts = [...next.futures_contracts, code]
        }
      } else if (market === 'CN') {
        if (!next.cn_stocks.includes(code)) {
          next.cn_stocks = [...next.cn_stocks, code]
        }
      } else {
        if (!next.us_stocks.includes(code)) {
          next.us_stocks = [...next.us_stocks, code]
        }
      }
      return next
    })
    setShowSearch(false)
    setSearchQuery('')
    setSearchResults([])
  }, [])

  const handleAddTicker = useCallback((code: string, market: string) => {
    const upper = code.toUpperCase()
    const mkt = market.toUpperCase()
    setConfig(prev => {
      if (!prev) return prev
      const next = { ...prev }
      if (mkt === 'FUTURES') {
        if (!next.futures_contracts.includes(upper)) {
          next.futures_contracts = [...next.futures_contracts, upper]
        }
      } else if (mkt === 'CN') {
        if (!next.cn_stocks.includes(upper)) {
          next.cn_stocks = [...next.cn_stocks, upper]
        }
      } else {
        if (!next.us_stocks.includes(upper)) {
          next.us_stocks = [...next.us_stocks, upper]
        }
      }
      return next
    })
  }, [])

  // Loading / error screens
  if (status === 'connecting') {
    return (
      <div className="flex items-center justify-center h-screen bg-gray-950">
        <div className="text-center">
          <svg className="animate-spin h-8 w-8 text-blue-500 mx-auto mb-4" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          <p className="text-gray-400 text-sm">正在启动 Python 后端...</p>
          <p className="text-gray-600 text-xs mt-1">正在连接后端服务...</p>
        </div>
      </div>
    )
  }

  if (status === 'error') {
    return (
      <div className="flex items-center justify-center h-screen bg-gray-950">
        <div className="text-center max-w-md">
          <div className="text-red-500 text-4xl mb-4">!</div>
          <h2 className="text-white text-lg font-semibold mb-2">连接失败</h2>
          <p className="text-gray-400 text-sm mb-4">
            无法连接到 Python 后端，请确保已安装依赖：
          </p>
          <code className="text-xs bg-gray-800 text-gray-300 px-3 py-2 rounded block">
            cd stock-sentiment-strategy && pip install -r requirements.txt
          </code>
        </div>
      </div>
    )
  }

  const selectedAnalysis = results.find(r => r.ticker === selectedTicker) || null

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar
        usStocks={config?.us_stocks || []}
        cnStocks={config?.cn_stocks || []}
        futuresContracts={config?.futures_contracts || []}
        days={config?.news_lookback_days || 3}
        sentimentWeight={config?.sentiment_weight || 0.4}
        technicalWeight={config?.technical_weight || 0.4}
        volumeWeight={config?.volume_weight || 0.2}
        futuresStrategy={config?.futures_strategy || null}
        deepseekApiKey={config?.deepseek_api_key || ''}
        deepseekModel={config?.deepseek_model || 'deepseek-chat'}
        tqsdkUser={config?.tqsdk_user || ''}
        tqsdkConnected={config?.tqsdk_connected || false}
        tqsdkTradeMode={config?.tqsdk_trade_mode || 'sim'}
        tqsdkBrokerId={config?.tqsdk_broker_id || ''}
        tqsdkBrokerAccount={config?.tqsdk_broker_account || ''}
        loading={loading}
        watchlist={watchlist.items}
        onAnalyze={handleAnalyze}
        onRemoveFromWatchlist={watchlist.remove}
        activeView={activeView}
        onViewChange={setActiveView}
        onSearch={handleSearch}
        onAddTicker={handleAddTicker}
        onTqStatusRefresh={refreshTqStatus}
      />

      <main className="flex-1 overflow-y-auto bg-gray-950 p-6">
        {error && (
          <div className="mb-4 bg-red-900/30 border border-red-800 rounded-lg px-4 py-3 text-red-300 text-sm">
            {error}
          </div>
        )}

        {/* Search results overlay */}
        {showSearch && activeView === 'analysis' && (
          <SearchResultsPanel
            query={searchQuery}
            results={searchResults}
            loading={searchLoading}
            onSelect={handleSearchSelect}
            onClose={handleSearchClose}
          />
        )}

        {/* Analysis view */}
        {activeView === 'analysis' && !showSearch && (
          <>
            {loading && (
              <div className="flex items-center justify-center h-full">
                <div className="text-center">
                  <svg className="animate-spin h-10 w-10 text-blue-500 mx-auto mb-4" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  <h3 className="text-white text-lg font-semibold mb-2">
                    正在分析 {stockCount} 只股票...
                  </h3>
                  <p className="text-gray-400 text-sm mb-1">
                    已用时间: <span className="text-white font-mono">{formatElapsed(elapsed)}</span>
                  </p>
                  <div className="mt-3 space-y-1 text-xs text-gray-500">
                    {elapsed < 10 && <p>正在获取新闻数据...</p>}
                    {elapsed >= 10 && elapsed < 30 && <p>正在进行 AI 分析...</p>}
                    {elapsed >= 30 && elapsed < 60 && <p>正在获取行情数据并计算技术指标...</p>}
                    {elapsed >= 60 && <p>处理中，请耐心等待...</p>}
                  </div>
                </div>
              </div>
            )}

            {results.length === 0 && !loading && (
              <div className="flex items-center justify-center h-full">
                <div className="text-center max-w-lg">
                  <div className="text-5xl mb-4 opacity-20">&#x1F4C8;</div>
                  <h2 className="text-xl font-semibold text-gray-300 mb-2">
                    股票舆情策略分析
                  </h2>
                  <p className="text-gray-500 text-sm leading-relaxed">
                    在左侧配置自选股列表，点击 <strong>开始分析</strong> 即可根据新闻舆情与技术指标生成交易信号。
                  </p>
                  <div className="mt-6 grid grid-cols-3 gap-4 text-center">
                    <div className="bg-gray-900/50 rounded-lg p-3">
                      <p className="text-emerald-400 font-semibold text-lg mb-1">AI 分析</p>
                      <p className="text-gray-500 text-xs">DeepSeek 驱动新闻舆情与投资建议</p>
                    </div>
                    <div className="bg-gray-900/50 rounded-lg p-3">
                      <p className="text-blue-400 font-semibold text-lg mb-1">技术指标</p>
                      <p className="text-gray-500 text-xs">RSI、MACD、均线趋势、布林带</p>
                    </div>
                    <div className="bg-gray-900/50 rounded-lg p-3">
                      <p className="text-amber-400 font-semibold text-lg mb-1">综合信号</p>
                      <p className="text-gray-500 text-xs">多维度评分与仓位建议</p>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {results.length > 0 && (
              <div className="space-y-6">
                <SummaryTable
                  results={results}
                  selectedTicker={selectedTicker}
                  onSelect={setSelectedTicker}
                  isInWatchlist={watchlist.has}
                  onToggleWatchlist={watchlist.toggle}
                />

                {selectedAnalysis && (
                  <StockCard
                    analysis={selectedAnalysis}
                    onTrade={() => openTradeModal(selectedAnalysis)}
                    onBacktest={() => setActiveView('backtest')}
                    onAnalysisUpdate={handleAnalysisUpdate}
                  />
                )}
              </div>
            )}
          </>
        )}

        {/* Portfolio view */}
        {activeView === 'portfolio' && (
          <PortfolioDashboard
            refreshKey={portfolioRefreshKey}
          />
        )}

        {/* Backtest view */}
        {activeView === 'backtest' && (
          <BacktestPanel />
        )}

        {activeView === 'quant' && (
          <QuantTradingPanel
            futuresContracts={config?.futures_contracts || []}
            tqsdkConnected={config?.tqsdk_connected || false}
            tqsdkTradeMode={config?.tqsdk_trade_mode || 'sim'}
          />
        )}
      </main>

      {/* Trade modal */}
      {tradeModalAnalysis && (
        <TradeModal
          analysis={tradeModalAnalysis}
          cash={portfolioCash}
          currentShares={currentHolding}
          onClose={closeTradeModal}
          onTradeComplete={handleTradeComplete}
        />
      )}
    </div>
  )
}
