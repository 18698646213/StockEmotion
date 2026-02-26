import React, { useState, useEffect, useCallback, useRef } from 'react'
import type { QuantAccount, QuantPosition, QuantDecision, QuantAutoStatus } from '../types'
import {
  getQuantAccount, startAutoTrade, stopAutoTrade,
  getAutoTradeStatus, placeQuantOrder, closeQuantPosition,
} from '../api'

function formatMoney(n: number): string {
  if (Math.abs(n) >= 1e8) return (n / 1e8).toFixed(2) + '亿'
  if (Math.abs(n) >= 1e4) return (n / 1e4).toFixed(2) + '万'
  return n.toFixed(2)
}

function PnlText({ value }: { value: number }) {
  const color = value > 0 ? 'text-red-400' : value < 0 ? 'text-green-400' : 'text-gray-400'
  const prefix = value > 0 ? '+' : ''
  return <span className={color}>{prefix}{formatMoney(value)}</span>
}

function SignalBadge({ signal }: { signal: string }) {
  const map: Record<string, string> = {
    STRONG_BUY: 'bg-red-900/60 text-red-300',
    BUY: 'bg-red-900/30 text-red-400',
    HOLD: 'bg-gray-800 text-gray-400',
    SELL: 'bg-green-900/30 text-green-400',
    STRONG_SELL: 'bg-green-900/60 text-green-300',
  }
  return (
    <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${map[signal] || map.HOLD}`}>
      {signal}
    </span>
  )
}

function ActionBadge({ action }: { action: string }) {
  const map: Record<string, string> = {
    BUY: 'bg-red-900/40 text-red-300',
    SELL: 'bg-green-900/40 text-green-300',
    CLOSE_LONG: 'bg-yellow-900/40 text-yellow-300',
    CLOSE_SHORT: 'bg-yellow-900/40 text-yellow-300',
    HOLD: 'bg-gray-800 text-gray-500',
  }
  const labels: Record<string, string> = {
    BUY: '做多', SELL: '做空', CLOSE_LONG: '平多',
    CLOSE_SHORT: '平空', HOLD: '观望',
  }
  return (
    <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${map[action] || map.HOLD}`}>
      {labels[action] || action}
    </span>
  )
}

interface Props {
  futuresContracts: string[]
  tqsdkConnected: boolean
  tqsdkTradeMode: string
}

export default function QuantTradingPanel({ futuresContracts, tqsdkConnected, tqsdkTradeMode }: Props) {
  const [account, setAccount] = useState<QuantAccount | null>(null)
  const [positions, setPositions] = useState<QuantPosition[]>([])
  const [autoStatus, setAutoStatus] = useState<QuantAutoStatus | null>(null)
  const tradeMode = tqsdkTradeMode === 'live' ? 'live' : 'sim'
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [showHold, setShowHold] = useState(false)

  // Auto-trade config
  const [maxLots, setMaxLots] = useState(1)
  const [maxPositions, setMaxPositions] = useState(3)
  const [threshold, setThreshold] = useState(0.3)
  const [interval, setInterval_] = useState(300)
  const [atrSlMult, setAtrSlMult] = useState(1.5)
  const [atrTpMult, setAtrTpMult] = useState(3.0)
  const [trailStep, setTrailStep] = useState(0.5)
  const [trailMove, setTrailMove] = useState(0.25)
  const [maxRiskPerTrade, setMaxRiskPerTrade] = useState(0.02)
  const [maxRiskRatio, setMaxRiskRatio] = useState(0.80)
  const [closeBeforeClose, setCloseBeforeClose] = useState(true)

  // Manual order
  const [manualSymbol, setManualSymbol] = useState('')
  const [manualDir, setManualDir] = useState<'BUY' | 'SELL'>('BUY')
  const [manualOffset, setManualOffset] = useState<'OPEN' | 'CLOSE'>('OPEN')
  const [manualVol, setManualVol] = useState(1)
  const [manualPrice, setManualPrice] = useState(0)
  const [orderMsg, setOrderMsg] = useState('')

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const configLoaded = useRef(false)

  const refresh = useCallback(async () => {
    try {
      const [acctData, statusData] = await Promise.all([
        getQuantAccount(),
        getAutoTradeStatus(),
      ])
      if (acctData.account) setAccount(acctData.account)
      setPositions(acctData.positions || [])
      setAutoStatus(statusData)

      if (!configLoaded.current && statusData?.config) {
        const c = statusData.config
        if (c.max_lots != null) setMaxLots(c.max_lots)
        if (c.max_positions != null) setMaxPositions(c.max_positions)
        if (c.signal_threshold != null) setThreshold(c.signal_threshold)
        if (c.analysis_interval != null) setInterval_(c.analysis_interval)
        if (c.atr_sl_multiplier != null) setAtrSlMult(c.atr_sl_multiplier)
        if (c.atr_tp_multiplier != null) setAtrTpMult(c.atr_tp_multiplier)
        if (c.trail_step_atr != null) setTrailStep(c.trail_step_atr)
        if (c.trail_move_atr != null) setTrailMove(c.trail_move_atr)
        if (c.max_risk_per_trade != null) setMaxRiskPerTrade(c.max_risk_per_trade)
        if (c.max_risk_ratio != null) setMaxRiskRatio(c.max_risk_ratio)
        if (c.close_before_market_close != null) setCloseBeforeClose(c.close_before_market_close)
        configLoaded.current = true
      }
    } catch (e: any) {
      console.error('Quant refresh error:', e)
    }
  }, [])

  useEffect(() => {
    refresh()
    pollRef.current = setInterval(refresh, 5000)
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [refresh])

  const handleStartAuto = async () => {
    if (!tqsdkConnected) {
      setError('请先连接天勤量化')
      return
    }
    if (futuresContracts.length === 0) {
      setError('请先在左侧添加期货合约')
      return
    }
    setLoading(true)
    setError('')
    try {
      await startAutoTrade({
        contracts: futuresContracts,
        max_lots: maxLots,
        max_positions: maxPositions,
        signal_threshold: threshold,
        analysis_interval: interval,
        atr_sl_multiplier: atrSlMult,
        atr_tp_multiplier: atrTpMult,
        trail_step_atr: trailStep,
        trail_move_atr: trailMove,
        max_risk_per_trade: maxRiskPerTrade,
        max_risk_ratio: maxRiskRatio,
        close_before_market_close: closeBeforeClose,
      })
      await refresh()
      // 启动后短时间密集轮询，快速捕获第一轮分析结果
      const burst = setInterval(refresh, 3000)
      setTimeout(() => clearInterval(burst), 30000)
    } catch (e: any) {
      setError(e.message || '启动失败')
    } finally {
      setLoading(false)
    }
  }

  const handleStopAuto = async () => {
    setLoading(true)
    try {
      await stopAutoTrade()
      await refresh()
    } catch (e: any) {
      setError(e.message || '停止失败')
    } finally {
      setLoading(false)
    }
  }

  const handleManualOrder = async () => {
    if (!manualSymbol.trim()) return
    setOrderMsg('')
    try {
      const res = await placeQuantOrder({
        symbol: manualSymbol.trim().toUpperCase(),
        direction: manualDir,
        offset: manualOffset,
        volume: manualVol,
        price: manualPrice,
      })
      setOrderMsg(JSON.stringify(res))
      await refresh()
    } catch (e: any) {
      setOrderMsg('下单失败: ' + e.message)
    }
  }

  const handleClose = async (symbol: string) => {
    try {
      await closeQuantPosition(symbol)
      await refresh()
    } catch (e: any) {
      setError('平仓失败: ' + e.message)
    }
  }

  const isAutoRunning = autoStatus?.running || false
  const decisions = autoStatus?.decisions || []

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-white">量化交易</h2>
          <p className="text-xs text-gray-500 mt-0.5">
            DeepSeek AI 分析 + 天勤量化执行
          </p>
        </div>
        <div className="flex items-center gap-2">
          {tqsdkConnected ? (
            <span className={`text-[10px] px-2 py-1 rounded-full flex items-center gap-1.5
              ${tradeMode === 'live'
                ? 'bg-red-900/40 text-red-400'
                : 'bg-green-900/40 text-green-400'}`}>
              <span className={`w-1.5 h-1.5 rounded-full animate-pulse
                ${tradeMode === 'live' ? 'bg-red-400' : 'bg-green-400'}`} />
              {tradeMode === 'live' ? '实盘模式' : '模拟盘'}
            </span>
          ) : (
            <span className="text-[10px] px-2 py-1 rounded-full bg-red-900/40 text-red-400">
              天勤未连接
            </span>
          )}
          {isAutoRunning && (
            <span className="text-[10px] px-2 py-1 rounded-full bg-orange-900/40 text-orange-400 flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 rounded-full bg-orange-400 animate-pulse" />
              自动交易运行中
            </span>
          )}
          {isAutoRunning && (autoStatus as any)?.trading_hours === false && (
            <span className="text-[10px] px-2 py-1 rounded-full bg-gray-800 text-gray-400">
              休市中
            </span>
          )}
        </div>
      </div>

      {/* Live trading warning */}
      {tradeMode === 'live' && tqsdkConnected && (
        <div className="bg-red-900/20 border border-red-800/50 rounded-lg p-3 flex items-start gap-2.5">
          <span className="text-lg shrink-0">&#9888;&#65039;</span>
          <div>
            <p className="text-sm font-semibold text-red-400">当前为实盘交易模式</p>
            <p className="text-[11px] text-red-400/70 mt-0.5">
              所有下单操作将使用真实资金，请确认风控参数后再启动自动交易。
              如需切换回模拟盘，请在左侧天勤配置中切换。
            </p>
          </div>
        </div>
      )}

      {error && (
        <div className="bg-red-900/20 border border-red-800/40 rounded-lg p-3 text-sm text-red-400">
          {error}
          <button onClick={() => setError('')} className="ml-2 text-red-500 hover:text-red-300">x</button>
        </div>
      )}

      {/* Account Overview */}
      {account && (
        <div className="grid grid-cols-4 gap-3">
          {[
            { label: '账户权益', value: formatMoney(account.balance), color: 'text-white' },
            { label: '可用资金', value: formatMoney(account.available), color: 'text-blue-400' },
            { label: '持仓盈亏', value: null, pnl: account.float_profit },
            { label: '占用保证金', value: formatMoney(account.margin), color: 'text-yellow-400' },
          ].map((item, i) => (
            <div key={i} className="bg-gray-900 border border-gray-800 rounded-lg p-3">
              <p className="text-[10px] text-gray-500 mb-1">{item.label}</p>
              {item.pnl !== undefined ? (
                <p className="text-sm font-semibold"><PnlText value={item.pnl} /></p>
              ) : (
                <p className={`text-sm font-semibold ${item.color}`}>{item.value}</p>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Account PnL Summary */}
      {autoStatus?.account_pnl && autoStatus.account_pnl.balance > 0 && (
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
          <h3 className="text-xs font-semibold text-gray-400 mb-3">账户总盈亏</h3>
          <div className="grid grid-cols-5 gap-3">
            <div>
              <p className="text-[10px] text-gray-500 mb-1">已实现盈亏</p>
              <p className="text-sm font-semibold"><PnlText value={autoStatus.account_pnl.close_profit} /></p>
            </div>
            <div>
              <p className="text-[10px] text-gray-500 mb-1">持仓浮盈</p>
              <p className="text-sm font-semibold"><PnlText value={autoStatus.account_pnl.float_profit} /></p>
            </div>
            <div>
              <p className="text-[10px] text-gray-500 mb-1">手续费</p>
              <p className="text-sm font-semibold text-yellow-400">{formatMoney(autoStatus.account_pnl.commission)}</p>
            </div>
            <div>
              <p className="text-[10px] text-gray-500 mb-1">净盈亏</p>
              <p className="text-sm font-semibold"><PnlText value={autoStatus.account_pnl.net_pnl} /></p>
            </div>
            <div>
              <p className="text-[10px] text-gray-500 mb-1">今日盈亏</p>
              <p className="text-sm font-semibold"><PnlText value={autoStatus.account_pnl.daily_pnl} /></p>
            </div>
          </div>
          {autoStatus.pnl_summary && autoStatus.pnl_summary.total_trades > 0 && (
            <div className="mt-3 pt-3 border-t border-gray-800 flex gap-6 text-[11px]">
              <span className="text-gray-500">AI交易 <span className="text-white">{autoStatus.pnl_summary.total_trades}笔</span></span>
              <span className="text-gray-500">胜率 <span className={autoStatus.pnl_summary.win_rate >= 50 ? 'text-red-400' : 'text-green-400'}>{autoStatus.pnl_summary.win_rate}%</span></span>
              <span className="text-gray-500">{autoStatus.pnl_summary.wins}胜 {autoStatus.pnl_summary.losses}负</span>
              <span className="text-gray-500">最大盈利 <span className="text-red-400">+{autoStatus.pnl_summary.max_win_points}</span></span>
              <span className="text-gray-500">最大亏损 <span className="text-green-400">{autoStatus.pnl_summary.max_loss_points}</span></span>
            </div>
          )}
        </div>
      )}

      <div className="grid grid-cols-2 gap-6">
        {/* Left: Auto Trading Control */}
        <div className="space-y-4">
          <h3 className="text-sm font-semibold text-gray-300 border-b border-gray-800 pb-2">
            AI 自动交易
          </h3>

          {/* Config */}
          <div className="space-y-3">
            <div className="grid grid-cols-3 gap-3">
              <div>
                <label className="block text-[10px] text-gray-500 mb-1">每次手数</label>
                <input type="number" min={1} max={10} value={maxLots}
                  onChange={e => setMaxLots(Number(e.target.value))}
                  disabled={isAutoRunning}
                  className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs text-gray-200
                    disabled:opacity-50 focus:outline-none focus:ring-1 focus:ring-cyan-500" />
              </div>
              <div>
                <label className="block text-[10px] text-gray-500 mb-1">最大持仓</label>
                <input type="number" min={1} max={10} value={maxPositions}
                  onChange={e => setMaxPositions(Number(e.target.value))}
                  disabled={isAutoRunning}
                  className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs text-gray-200
                    disabled:opacity-50 focus:outline-none focus:ring-1 focus:ring-cyan-500" />
              </div>
              <div>
                <label className="block text-[10px] text-gray-500 mb-1">信号阈值</label>
                <input type="number" min={0.1} max={0.9} step={0.05} value={threshold}
                  onChange={e => setThreshold(Number(e.target.value))}
                  disabled={isAutoRunning}
                  className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs text-gray-200
                    disabled:opacity-50 focus:outline-none focus:ring-1 focus:ring-cyan-500" />
              </div>
            </div>

            {/* ATR Risk Management */}
            <div className="bg-gray-900/50 rounded-lg p-3 space-y-2">
              <div className="flex items-center justify-between">
                <p className="text-[10px] text-cyan-400 font-medium">ATR 风控（基于15分钟K线 ATR(14)）</p>
              </div>
              {(autoStatus as any)?.atr_values && Object.keys((autoStatus as any).atr_values).length > 0 && (
                <div className="flex flex-wrap gap-2">
                  {Object.entries((autoStatus as any).atr_values as Record<string, number>).map(([sym, val]) => (
                    <span key={sym} className="text-[10px] bg-gray-800 border border-gray-700 rounded px-2 py-0.5 font-mono">
                      <span className="text-gray-400">{sym}</span>
                      <span className="text-cyan-400 ml-1.5">{val}</span>
                    </span>
                  ))}
                </div>
              )}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[10px] text-gray-500 mb-1">
                    止损倍数 <span className="text-gray-600">({atrSlMult}×ATR)</span>
                  </label>
                  <input type="number" min={0.5} max={5} step={0.25} value={atrSlMult}
                    onChange={e => setAtrSlMult(Number(e.target.value))}
                    disabled={isAutoRunning}
                    className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs text-gray-200
                      disabled:opacity-50 focus:outline-none focus:ring-1 focus:ring-cyan-500" />
                </div>
                <div>
                  <label className="block text-[10px] text-gray-500 mb-1">
                    止盈倍数 <span className="text-gray-600">({atrTpMult}×ATR)</span>
                  </label>
                  <input type="number" min={1} max={10} step={0.5} value={atrTpMult}
                    onChange={e => setAtrTpMult(Number(e.target.value))}
                    disabled={isAutoRunning}
                    className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs text-gray-200
                      disabled:opacity-50 focus:outline-none focus:ring-1 focus:ring-cyan-500" />
                </div>
                <div>
                  <label className="block text-[10px] text-gray-500 mb-1">
                    跟踪步进 <span className="text-gray-600">({trailStep}×ATR)</span>
                  </label>
                  <input type="number" min={0.1} max={2} step={0.1} value={trailStep}
                    onChange={e => setTrailStep(Number(e.target.value))}
                    disabled={isAutoRunning}
                    className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs text-gray-200
                      disabled:opacity-50 focus:outline-none focus:ring-1 focus:ring-cyan-500" />
                </div>
                <div>
                  <label className="block text-[10px] text-gray-500 mb-1">
                    止损跟进 <span className="text-gray-600">({trailMove}×ATR)</span>
                  </label>
                  <input type="number" min={0.1} max={1} step={0.05} value={trailMove}
                    onChange={e => setTrailMove(Number(e.target.value))}
                    disabled={isAutoRunning}
                    className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs text-gray-200
                      disabled:opacity-50 focus:outline-none focus:ring-1 focus:ring-cyan-500" />
                </div>
              </div>
              <p className="text-[9px] text-gray-600 leading-snug">
                止损 = 入场价 ∓ {atrSlMult}×ATR | 止盈 = 入场价 ± {atrTpMult}×ATR（{(atrTpMult / atrSlMult).toFixed(1)}:1 盈亏比）
                <br />跟踪止盈：价格每有利移动 {trailStep}×ATR，止损跟进 {trailMove}×ATR
              </p>
            </div>

            {/* Position Risk Management */}
            <div className="bg-gray-900/50 rounded-lg p-3 space-y-2">
              <p className="text-[10px] text-yellow-400 font-medium">仓位风控（大赛策略）</p>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[10px] text-gray-500 mb-1">
                    单笔风险 <span className="text-gray-600">({(maxRiskPerTrade * 100).toFixed(0)}%权益)</span>
                  </label>
                  <input type="number" min={0.005} max={0.05} step={0.005} value={maxRiskPerTrade}
                    onChange={e => setMaxRiskPerTrade(Number(e.target.value))}
                    disabled={isAutoRunning}
                    className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs text-gray-200
                      disabled:opacity-50 focus:outline-none focus:ring-1 focus:ring-cyan-500" />
                </div>
                <div>
                  <label className="block text-[10px] text-gray-500 mb-1">
                    最大风险度 <span className="text-gray-600">({(maxRiskRatio * 100).toFixed(0)}%)</span>
                  </label>
                  <input type="number" min={0.3} max={0.9} step={0.05} value={maxRiskRatio}
                    onChange={e => setMaxRiskRatio(Number(e.target.value))}
                    disabled={isAutoRunning}
                    className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs text-gray-200
                      disabled:opacity-50 focus:outline-none focus:ring-1 focus:ring-cyan-500" />
                </div>
              </div>
              <div className="flex items-center gap-2 mt-1">
                <input type="checkbox" checked={closeBeforeClose}
                  onChange={e => setCloseBeforeClose(e.target.checked)}
                  disabled={isAutoRunning}
                  className="accent-cyan-500 w-3 h-3" />
                <label className="text-[10px] text-gray-400">
                  收盘前自动平仓（14:55 日盘平仓）
                </label>
              </div>
              <p className="text-[9px] text-gray-600 leading-snug">
                动态仓位：手数 = 权益×{(maxRiskPerTrade * 100).toFixed(0)}% / (ATR×{atrSlMult}×合约乘数) | 保证金/权益 {'>'} {(maxRiskRatio * 100).toFixed(0)}% 禁止开仓
              </p>
            </div>

            <div>
              <label className="block text-[10px] text-gray-500 mb-1">
                分析周期: <span className="text-gray-300">{interval}秒 ({(interval / 60).toFixed(0)}分钟)</span>
              </label>
              <input type="range" min={60} max={1800} step={60} value={interval}
                onChange={e => setInterval_(Number(e.target.value))}
                disabled={isAutoRunning}
                className="w-full accent-cyan-500" />
            </div>
          </div>

          {/* Contracts info */}
          <div className="bg-gray-900/50 rounded-lg p-3">
            <p className="text-[10px] text-gray-500 mb-1.5">交易合约</p>
            <div className="flex flex-wrap gap-1">
              {(isAutoRunning ? (autoStatus?.contracts || []) : futuresContracts).map(c => (
                <span key={c} className="text-xs font-mono px-2 py-0.5 rounded bg-orange-900/30 text-orange-300">
                  {c}
                </span>
              ))}
              {futuresContracts.length === 0 && !isAutoRunning && (
                <p className="text-[10px] text-gray-600">请先在左侧搜索并添加期货合约</p>
              )}
            </div>
          </div>

          {/* Start / Stop */}
          {isAutoRunning ? (
            <button onClick={handleStopAuto} disabled={loading}
              className="w-full bg-red-700 hover:bg-red-600 text-white font-semibold py-2.5 rounded-lg
                transition-colors text-sm disabled:opacity-50">
              {loading ? '处理中...' : '停止自动交易'}
            </button>
          ) : (
            <button onClick={handleStartAuto} disabled={loading || !tqsdkConnected}
              className="w-full bg-cyan-700 hover:bg-cyan-600 text-white font-semibold py-2.5 rounded-lg
                transition-colors text-sm disabled:opacity-50 disabled:bg-gray-700">
              {loading ? '启动中...' : '启动 AI 自动交易'}
            </button>
          )}
        </div>

        {/* Right: Manual Order */}
        <div className="space-y-4">
          <h3 className="text-sm font-semibold text-gray-300 border-b border-gray-800 pb-2">
            手动下单
          </h3>

          <div className="grid grid-cols-2 gap-3">
            <div className="col-span-2">
              <label className="block text-[10px] text-gray-500 mb-1">合约代码</label>
              <input type="text" value={manualSymbol}
                onChange={e => setManualSymbol(e.target.value)}
                placeholder="如 C2605"
                className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs text-gray-200
                  focus:outline-none focus:ring-1 focus:ring-cyan-500 font-mono placeholder-gray-600" />
            </div>
            <div>
              <label className="block text-[10px] text-gray-500 mb-1">方向</label>
              <select value={manualDir} onChange={e => setManualDir(e.target.value as 'BUY' | 'SELL')}
                className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs text-gray-200
                  focus:outline-none focus:ring-1 focus:ring-cyan-500">
                <option value="BUY">买入 (做多)</option>
                <option value="SELL">卖出 (做空)</option>
              </select>
            </div>
            <div>
              <label className="block text-[10px] text-gray-500 mb-1">开平</label>
              <select value={manualOffset} onChange={e => setManualOffset(e.target.value as 'OPEN' | 'CLOSE')}
                className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs text-gray-200
                  focus:outline-none focus:ring-1 focus:ring-cyan-500">
                <option value="OPEN">开仓</option>
                <option value="CLOSE">平仓</option>
              </select>
            </div>
            <div>
              <label className="block text-[10px] text-gray-500 mb-1">手数</label>
              <input type="number" min={1} max={100} value={manualVol}
                onChange={e => setManualVol(Number(e.target.value))}
                className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs text-gray-200
                  focus:outline-none focus:ring-1 focus:ring-cyan-500" />
            </div>
            <div>
              <label className="block text-[10px] text-gray-500 mb-1">价格 (0=市价)</label>
              <input type="number" min={0} step={1} value={manualPrice}
                onChange={e => setManualPrice(Number(e.target.value))}
                className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-1.5 text-xs text-gray-200
                  focus:outline-none focus:ring-1 focus:ring-cyan-500" />
            </div>
          </div>

          <button onClick={handleManualOrder} disabled={!tqsdkConnected || !manualSymbol.trim()}
            className="w-full bg-blue-700 hover:bg-blue-600 text-white font-semibold py-2 rounded-lg
              transition-colors text-sm disabled:opacity-50 disabled:bg-gray-700">
            下单
          </button>

          {orderMsg && (
            <p className="text-[10px] text-gray-400 bg-gray-900 rounded p-2 break-all">{orderMsg}</p>
          )}
        </div>
      </div>

      {/* Positions */}
      {tqsdkConnected && (
        <div>
          <h3 className="text-sm font-semibold text-gray-300 border-b border-gray-800 pb-2 mb-3">
            当前持仓
            {positions.length > 0 && (
              <span className="text-[10px] text-gray-600 ml-2 font-normal">
                ({positions.length} 个合约)
              </span>
            )}
          </h3>
          {positions.length === 0 ? (
            <div className="text-center py-6 bg-gray-900/30 rounded-lg border border-gray-800/50">
              <p className="text-gray-500 text-xs">暂无持仓</p>
            </div>
          ) : (
          <div className="overflow-auto rounded-lg border border-gray-800">
            <table className="w-full text-sm">
              <thead className="bg-gray-900">
                <tr className="text-xs text-gray-500 border-b border-gray-800">
                  <th className="text-left px-3 py-2">合约</th>
                  <th className="text-center px-3 py-2">方向</th>
                  <th className="text-right px-3 py-2">手数</th>
                  <th className="text-right px-3 py-2">开仓价</th>
                  <th className="text-right px-3 py-2">最新价</th>
                  <th className="text-right px-3 py-2">止损</th>
                  <th className="text-right px-3 py-2">止盈</th>
                  <th className="text-right px-3 py-2">浮动盈亏</th>
                  <th className="text-center px-3 py-2">操作</th>
                </tr>
              </thead>
              <tbody>
                {positions.map(p => {
                  const mp = (autoStatus as any)?.managed_positions?.[p.symbol]
                  const isLong = p.long_volume > 0
                  const isShort = p.short_volume > 0
                  const entryPrice = isLong ? p.long_avg_price : p.short_avg_price
                  const vol = isLong ? p.long_volume : p.short_volume
                  const pnlPct = entryPrice > 0 && p.last_price > 0
                    ? ((isLong ? 1 : -1) * (p.last_price - entryPrice) / entryPrice * 100)
                    : 0
                  return (
                    <tr key={p.symbol} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                      <td className="px-3 py-2 font-mono text-gray-200 font-medium">{p.symbol}</td>
                      <td className="px-3 py-2 text-center">
                        {isLong && <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-900/30 text-red-400 font-medium">多</span>}
                        {isShort && <span className="text-[10px] px-1.5 py-0.5 rounded bg-green-900/30 text-green-400 font-medium">空</span>}
                      </td>
                      <td className="px-3 py-2 text-right text-gray-300">{vol}</td>
                      <td className="px-3 py-2 text-right text-gray-300">
                        {entryPrice > 0 ? entryPrice.toFixed(1) : '-'}
                      </td>
                      <td className="px-3 py-2 text-right text-white font-medium">
                        {p.last_price > 0 ? p.last_price.toFixed(1) : '-'}
                      </td>
                      <td className="px-3 py-2 text-right text-red-400/70">
                        {mp?.stop_loss ? mp.stop_loss.toFixed(1) : '-'}
                      </td>
                      <td className="px-3 py-2 text-right text-green-400/70">
                        {mp?.take_profit ? mp.take_profit.toFixed(1) : '-'}
                      </td>
                      <td className="px-3 py-2 text-right">
                        <div className="flex flex-col items-end">
                          <PnlText value={p.float_profit} />
                          {pnlPct !== 0 && (
                            <span className={`text-[9px] ${pnlPct > 0 ? 'text-red-500/70' : 'text-green-500/70'}`}>
                              {pnlPct > 0 ? '+' : ''}{pnlPct.toFixed(2)}%
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="px-3 py-2 text-center">
                        <button onClick={() => handleClose(p.symbol)}
                          className="text-[10px] px-2 py-0.5 rounded bg-yellow-900/30 text-yellow-400
                            hover:bg-yellow-900/50 transition-colors">
                          平仓
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          )}

          {/* Managed positions from auto-trader (strategy SL/TP tracking) */}
          {autoStatus?.managed_positions && Object.keys(autoStatus.managed_positions).length > 0 && (
            <div className="mt-3 bg-gray-900/30 rounded-lg border border-gray-800/50 p-3">
              <p className="text-[10px] text-cyan-400 font-medium mb-2">AI 策略持仓管理</p>
              <div className="grid gap-2">
                {Object.entries(autoStatus.managed_positions).map(([sym, mp]) => {
                  const pos = positions.find(p => p.symbol === sym)
                  const lastPrice = mp.current_price || pos?.last_price || 0
                  return (
                    <div key={sym} className="flex items-center gap-3 text-xs bg-gray-800/40 rounded px-3 py-2">
                      <span className="font-mono text-gray-200 font-medium w-16">{sym}</span>
                      <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${
                        mp.direction === 'LONG' ? 'bg-red-900/30 text-red-400' : 'bg-green-900/30 text-green-400'
                      }`}>
                        {mp.direction === 'LONG' ? '多' : '空'}×{mp.lots}
                      </span>
                      <span className="text-gray-500">
                        入场 <span className="text-gray-300">{mp.entry_price.toFixed(1)}</span>
                      </span>
                      {lastPrice > 0 && (
                        <span className="text-gray-500">
                          现价 <span className="text-white">{lastPrice.toFixed(1)}</span>
                        </span>
                      )}
                      <span className="text-gray-500">
                        止损 <span className="text-red-400/80">{mp.stop_loss.toFixed(1)}</span>
                      </span>
                      <span className="text-gray-500">
                        止盈 <span className="text-green-400/80">{mp.take_profit.toFixed(1)}</span>
                      </span>
                      <span className="text-gray-500">
                        ATR <span className="text-cyan-400/80">{mp.atr.toFixed(1)}</span>
                      </span>
                      {mp.float_pnl !== undefined && mp.float_pnl !== 0 && (
                        <span className="text-gray-500">
                          浮盈 <PnlText value={mp.float_pnl} />
                          <span className={`text-[9px] ml-0.5 ${mp.float_pnl_pct > 0 ? 'text-red-500/60' : 'text-green-500/60'}`}>
                            ({mp.float_pnl_pct > 0 ? '+' : ''}{mp.float_pnl_pct.toFixed(2)}%)
                          </span>
                        </span>
                      )}
                    </div>
                  )
                })}
              </div>
            </div>
          )}
        </div>
      )}

      {/* AI Decision Log */}
      {decisions.length > 0 && (() => {
        const filtered = showHold ? decisions : decisions.filter((d: any) => d.action !== 'HOLD')
        const actionCount = decisions.filter((d: any) => d.action !== 'HOLD').length
        return (
        <div>
          <div className="flex items-center justify-between border-b border-gray-800 pb-2 mb-3">
            <h3 className="text-sm font-semibold text-gray-300">
              AI 交易决策日志
              <span className="text-[10px] text-gray-600 ml-2 font-normal">
                ({actionCount} 条交易 / 共 {autoStatus?.decisions_count || 0} 条)
              </span>
            </h3>
            <button onClick={() => setShowHold(!showHold)}
              className={`text-[10px] px-2 py-0.5 rounded transition-colors ${
                showHold ? 'bg-gray-700 text-gray-300' : 'bg-gray-800 text-gray-500 hover:text-gray-300'}`}>
              {showHold ? '隐藏观望' : '显示观望'}
            </button>
          </div>
          {filtered.length === 0 ? (
            <p className="text-xs text-gray-600 text-center py-4">暂无交易动作记录</p>
          ) : (
          <div className="overflow-auto rounded-lg border border-gray-800 max-h-[400px]">
            <table className="w-full text-xs">
              <thead className="bg-gray-900 sticky top-0 z-10">
                <tr className="text-gray-500 border-b border-gray-800">
                  <th className="text-left px-3 py-2">时间</th>
                  <th className="text-left px-3 py-2">合约</th>
                  <th className="text-center px-3 py-2">信号</th>
                  <th className="text-right px-3 py-2">得分</th>
                  <th className="text-center px-3 py-2">动作</th>
                  <th className="text-right px-3 py-2">手数</th>
                  <th className="text-right px-3 py-2">价格</th>
                  <th className="text-right px-3 py-2">ATR</th>
                  <th className="text-right px-3 py-2">止损</th>
                  <th className="text-right px-3 py-2">止盈</th>
                  <th className="text-right px-3 py-2">盈亏</th>
                  <th className="text-left px-3 py-2">原因</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((d: any, i: number) => {
                  const isClose = d.action === 'CLOSE_LONG' || d.action === 'CLOSE_SHORT'
                  const hasPnl = isClose && d.entry_price > 0
                  const holdMin = d.holding_seconds > 0 ? Math.floor(d.holding_seconds / 60) : 0
                  return (
                  <tr key={i} className={`border-b border-gray-800/30 ${
                    isClose ? (d.pnl_points > 0 ? 'bg-red-900/10' : 'bg-green-900/10')
                    : d.action !== 'HOLD' ? 'bg-cyan-900/5' : ''}`}>
                    <td className="px-3 py-1.5 text-gray-500 whitespace-nowrap">
                      {d.timestamp.slice(11, 19)}
                    </td>
                    <td className="px-3 py-1.5 font-mono text-gray-300">{d.symbol}</td>
                    <td className="px-3 py-1.5 text-center"><SignalBadge signal={d.signal} /></td>
                    <td className={`px-3 py-1.5 text-right font-mono ${
                      d.composite_score > 0 ? 'text-red-400' : d.composite_score < 0 ? 'text-green-400' : 'text-gray-500'
                    }`}>
                      {d.composite_score ? (d.composite_score > 0 ? '+' : '') + d.composite_score.toFixed(2) : '-'}
                    </td>
                    <td className="px-3 py-1.5 text-center"><ActionBadge action={d.action} /></td>
                    <td className="px-3 py-1.5 text-right text-gray-400">{d.lots || '-'}</td>
                    <td className="px-3 py-1.5 text-right text-gray-400">
                      {d.price?.toFixed(1)}
                      {hasPnl && <span className="text-[9px] text-gray-600 block">入{d.entry_price.toFixed(1)}</span>}
                    </td>
                    <td className="px-3 py-1.5 text-right text-cyan-500/70">
                      {d.atr ? d.atr.toFixed(1) : '-'}
                    </td>
                    <td className="px-3 py-1.5 text-right text-red-400/70">
                      {d.stop_loss ? d.stop_loss.toFixed(1) : '-'}
                    </td>
                    <td className="px-3 py-1.5 text-right text-green-400/70">
                      {d.take_profit ? d.take_profit.toFixed(1) : '-'}
                    </td>
                    <td className="px-3 py-1.5 text-right">
                      {hasPnl ? (
                        <div className="flex flex-col items-end">
                          <span className={`font-mono font-medium ${d.pnl_points > 0 ? 'text-red-400' : 'text-green-400'}`}>
                            {d.pnl_points > 0 ? '+' : ''}{d.pnl_points.toFixed(1)}
                          </span>
                          <span className={`text-[9px] ${d.pnl_pct > 0 ? 'text-red-500/60' : 'text-green-500/60'}`}>
                            {d.pnl_pct > 0 ? '+' : ''}{d.pnl_pct.toFixed(2)}%
                            {holdMin > 0 && <span className="text-gray-600 ml-1">{holdMin}分钟</span>}
                          </span>
                        </div>
                      ) : (
                        <span className="text-gray-700">-</span>
                      )}
                    </td>
                    <td className="px-3 py-1.5 text-gray-500 max-w-[260px] truncate" title={d.reason}>
                      {d.reason}
                    </td>
                  </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          )}
        </div>
        )
      })()}

      {/* Empty state when not connected */}
      {!tqsdkConnected && (
        <div className="text-center py-12">
          <div className="text-4xl mb-3 opacity-20">&#x1F4C8;</div>
          <p className="text-gray-400 text-sm font-medium mb-1">量化交易需要连接天勤量化</p>
          <p className="text-gray-600 text-xs">请在左侧期货模块中配置天勤账户后使用</p>
        </div>
      )}
    </div>
  )
}
