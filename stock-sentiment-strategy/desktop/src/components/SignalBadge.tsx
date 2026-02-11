import React from 'react'
import type { SignalType } from '../types'
import { SIGNAL_BG_COLORS } from '../types'

interface Props {
  signal: SignalType
  signalCn: string
  score: number
  size?: 'sm' | 'md' | 'lg'
}

const textColorMap: Record<SignalType, string> = {
  STRONG_BUY: 'text-green-400',
  BUY: 'text-green-300',
  HOLD: 'text-yellow-300',
  SELL: 'text-red-300',
  STRONG_SELL: 'text-red-400',
}

export default function SignalBadge({ signal, signalCn, score, size = 'md' }: Props) {
  const sizeClasses = {
    sm: 'px-2 py-1 text-xs',
    md: 'px-3 py-1.5 text-sm',
    lg: 'px-4 py-2 text-base',
  }

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-lg font-semibold
        ${SIGNAL_BG_COLORS[signal]} ${textColorMap[signal]} ${sizeClasses[size]}
        border border-current/20`}
    >
      <span>{signalCn}</span>
      <span className="ml-1 font-mono text-xs opacity-60">{score >= 0 ? '+' : ''}{score.toFixed(3)}</span>
    </span>
  )
}
