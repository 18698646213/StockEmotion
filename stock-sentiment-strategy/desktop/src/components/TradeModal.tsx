import React, { useState, useMemo, useEffect } from 'react'
import type { StockAnalysis, TradeResult } from '../types'
import { executeTrade, executeSignalTrade } from '../api'

interface Props {
  analysis: StockAnalysis
  cash: number
  currentShares: number
  onClose: () => void
  onTradeComplete: () => void
}

type TradeTab = 'buy' | 'sell' | 'signal'

// A-share fee rates (for preview)
const CN_COMM_RATE = 0.00025
const CN_MIN_COMM = 5
const CN_STAMP_TAX = 0.0005
const CN_TRANSFER = 0.00001

function estimateFee(market: string, action: string, shares: number, price: number) {
  const amount = shares * price
  if (market === 'CN') {
    const comm = Math.max(amount * CN_COMM_RATE, CN_MIN_COMM)
    const tax = action === 'SELL' ? amount * CN_STAMP_TAX : 0
    const transfer = amount * CN_TRANSFER
    return { commission: comm, stamp_tax: tax, transfer_fee: transfer, total: comm + tax + transfer }
  }
  return { commission: 0, stamp_tax: 0, transfer_fee: 0, total: 0 }
}

export default function TradeModal({ analysis, cash, currentShares, onClose, onTradeComplete }: Props) {
  const [tab, setTab] = useState<TradeTab>('buy')
  const [shares, setShares] = useState<number>(analysis.market === 'CN' ? 100 : 1)
  const [price, setPrice] = useState<number>(0)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<TradeResult | null>(null)

  // Set initial price from last close
  useEffect(() => {
    if (analysis.price_data.length > 0) {
      setPrice(analysis.price_data[analysis.price_data.length - 1].close)
    }
  }, [analysis])

  const fee = useMemo(() =>
    estimateFee(analysis.market, tab === 'sell' ? 'SELL' : 'BUY', shares, price),
    [analysis.market, tab, shares, price]
  )

  const totalCost = tab === 'sell'
    ? shares * price - fee.total
    : shares * price + fee.total

  const maxBuyShares = useMemo(() => {
    if (price <= 0) return 0
    const maxAmount = cash - (analysis.market === 'CN' ? CN_MIN_COMM : 0)
    const raw = Math.floor(maxAmount / price)
    return analysis.market === 'CN' ? Math.floor(raw / 100) * 100 : raw
  }, [cash, price, analysis.market])

  const handleTrade = async () => {
    setLoading(true)
    setResult(null)
    try {
      if (tab === 'signal') {
        const sig = analysis.signal
        const res = await executeSignalTrade({
          ticker: analysis.ticker,
          market: analysis.market,
          signal: sig.signal,
          composite_score: sig.composite_score,
          position_pct: analysis.position_pct,
          price,
        })
        setResult(res)
      } else {
        const res = await executeTrade({
          ticker: analysis.ticker,
          market: analysis.market,
          action: tab === 'buy' ? 'BUY' : 'SELL',
          shares,
          price,
        })
        setResult(res)
      }
      onTradeComplete()
    } catch (e: any) {
      setResult({ success: false, error_msg: e.message || '交易失败', trade: null, fee_detail: null })
    } finally {
      setLoading(false)
    }
  }

  const canSubmit = tab === 'signal' || (shares > 0 && price > 0)

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
         onClick={onClose}>
      <div className="bg-gray-900 border border-gray-700 rounded-xl w-[420px] max-h-[90vh] overflow-y-auto shadow-2xl"
           onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-gray-800">
          <div className="flex items-center gap-2">
            <h3 className="text-white font-bold">{analysis.ticker}</h3>
            <span className={`text-[10px] px-1.5 py-0.5 rounded
              ${analysis.market === 'US' ? 'bg-blue-900/40 text-blue-400' : 'bg-red-900/40 text-red-400'}`}>
              {analysis.market === 'US' ? '美股' : 'A股'}
            </span>
          </div>
          <button onClick={onClose} className="text-gray-500 hover:text-white transition-colors">
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-gray-800">
          {(['buy', 'sell', 'signal'] as TradeTab[]).map(t => (
            <button
              key={t}
              onClick={() => { setTab(t); setResult(null) }}
              className={`flex-1 py-2 text-xs font-medium transition-colors
                ${tab === t
                  ? t === 'buy' ? 'text-green-400 border-b-2 border-green-400 bg-green-900/10'
                  : t === 'sell' ? 'text-red-400 border-b-2 border-red-400 bg-red-900/10'
                  : 'text-blue-400 border-b-2 border-blue-400 bg-blue-900/10'
                  : 'text-gray-500 hover:text-gray-300'}`}
            >
              {t === 'buy' ? '买入' : t === 'sell' ? '卖出' : '一键跟单'}
            </button>
          ))}
        </div>

        {/* Content */}
        <div className="p-5 space-y-4">
          {/* Account info */}
          <div className="flex justify-between text-xs">
            <span className="text-gray-500">可用资金</span>
            <span className="text-white font-mono">{cash.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}</span>
          </div>
          {currentShares > 0 && (
            <div className="flex justify-between text-xs">
              <span className="text-gray-500">当前持仓</span>
              <span className="text-white font-mono">{currentShares} 股</span>
            </div>
          )}

          {tab === 'signal' ? (
            /* Signal trade info */
            <div className="bg-gray-800/50 rounded-lg p-3 space-y-2">
              <div className="flex justify-between text-xs">
                <span className="text-gray-400">信号</span>
                <span className={`font-semibold ${
                  analysis.signal.signal.includes('BUY') ? 'text-green-400' :
                  analysis.signal.signal.includes('SELL') ? 'text-red-400' : 'text-yellow-400'
                }`}>{analysis.signal.signal_cn}</span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-gray-400">综合评分</span>
                <span className="text-white font-mono">{analysis.signal.composite_score.toFixed(3)}</span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-gray-400">建议仓位</span>
                <span className="text-white font-mono">{analysis.position_pct.toFixed(1)}%</span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-gray-400">参考价格</span>
                <span className="text-white font-mono">{price.toFixed(2)}</span>
              </div>
            </div>
          ) : (
            /* Manual trade form */
            <>
              <div>
                <label className="block text-xs text-gray-400 mb-1">
                  价格
                </label>
                <input
                  type="number"
                  step="0.01"
                  value={price || ''}
                  onChange={e => setPrice(Number(e.target.value))}
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm
                    text-white font-mono focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
              </div>
              <div>
                <div className="flex justify-between items-center mb-1">
                  <label className="text-xs text-gray-400">
                    股数 {analysis.market === 'CN' && <span className="text-gray-600">(100整数倍)</span>}
                  </label>
                  {tab === 'buy' && (
                    <button
                      onClick={() => setShares(maxBuyShares)}
                      className="text-[10px] text-blue-400 hover:text-blue-300"
                    >全仓 ({maxBuyShares})</button>
                  )}
                  {tab === 'sell' && currentShares > 0 && (
                    <button
                      onClick={() => setShares(currentShares)}
                      className="text-[10px] text-red-400 hover:text-red-300"
                    >全部卖出 ({currentShares})</button>
                  )}
                </div>
                <input
                  type="number"
                  step={analysis.market === 'CN' ? 100 : 1}
                  min={0}
                  value={shares || ''}
                  onChange={e => setShares(Number(e.target.value))}
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm
                    text-white font-mono focus:outline-none focus:ring-1 focus:ring-blue-500"
                />
              </div>

              {/* Fee preview */}
              {shares > 0 && price > 0 && (
                <div className="bg-gray-800/50 rounded-lg p-3 space-y-1.5">
                  <div className="flex justify-between text-xs">
                    <span className="text-gray-500">交易金额</span>
                    <span className="text-gray-300 font-mono">{(shares * price).toFixed(2)}</span>
                  </div>
                  {analysis.market === 'CN' && (
                    <>
                      <div className="flex justify-between text-xs">
                        <span className="text-gray-500">佣金</span>
                        <span className="text-gray-300 font-mono">{fee.commission.toFixed(2)}</span>
                      </div>
                      {fee.stamp_tax > 0 && (
                        <div className="flex justify-between text-xs">
                          <span className="text-gray-500">印花税</span>
                          <span className="text-gray-300 font-mono">{fee.stamp_tax.toFixed(2)}</span>
                        </div>
                      )}
                      <div className="flex justify-between text-xs">
                        <span className="text-gray-500">过户费</span>
                        <span className="text-gray-300 font-mono">{fee.transfer_fee.toFixed(4)}</span>
                      </div>
                    </>
                  )}
                  <div className="flex justify-between text-xs border-t border-gray-700 pt-1.5">
                    <span className="text-gray-400 font-medium">
                      {tab === 'sell' ? '预计到账' : '预计花费'}
                    </span>
                    <span className={`font-mono font-semibold ${tab === 'sell' ? 'text-green-400' : 'text-red-400'}`}>
                      {totalCost.toFixed(2)}
                    </span>
                  </div>
                </div>
              )}

              {/* T+1 warning */}
              {analysis.market === 'CN' && tab === 'buy' && (
                <div className="text-[10px] text-amber-400/70 bg-amber-900/10 rounded px-2 py-1.5">
                  A 股 T+1 规则：今日买入的股票明日起方可卖出
                </div>
              )}
            </>
          )}

          {/* Result message */}
          {result && (
            <div className={`rounded-lg px-3 py-2 text-xs ${
              result.success
                ? 'bg-green-900/30 border border-green-800 text-green-300'
                : 'bg-red-900/30 border border-red-800 text-red-300'
            }`}>
              {result.success
                ? result.trade
                  ? `${result.trade.action === 'BUY' ? '买入' : '卖出'}成功：${result.trade.shares}股 @${result.trade.price.toFixed(2)}，手续费 ${result.trade.total_fee.toFixed(2)}`
                  : result.error_msg || '操作成功'
                : result.error_msg
              }
            </div>
          )}

          {/* Submit button */}
          <button
            onClick={handleTrade}
            disabled={loading || !canSubmit}
            className={`w-full py-2.5 rounded-lg font-semibold text-sm transition-colors
              flex items-center justify-center gap-2
              ${tab === 'sell'
                ? 'bg-red-600 hover:bg-red-500 disabled:bg-gray-700'
                : 'bg-green-600 hover:bg-green-500 disabled:bg-gray-700'
              } text-white disabled:text-gray-500`}
          >
            {loading ? (
              <>
                <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                执行中...
              </>
            ) : (
              tab === 'signal' ? '一键跟单' : tab === 'buy' ? '确认买入' : '确认卖出'
            )}
          </button>
        </div>
      </div>
    </div>
  )
}
