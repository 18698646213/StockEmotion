import React, { useState } from 'react'
import type { SentimentResult } from '../types'

interface Props {
  items: SentimentResult[]
}

function SentimentDot({ label }: { label: string }) {
  const color =
    label === 'positive' ? 'bg-green-500' :
    label === 'negative' ? 'bg-red-500' : 'bg-yellow-500'

  return <span className={`inline-block w-2 h-2 rounded-full ${color}`} />
}

function LabelBadge({ label }: { label: string }) {
  const config =
    label === 'positive'
      ? { text: '正面', cls: 'bg-green-900/40 text-green-400' }
      : label === 'negative'
      ? { text: '负面', cls: 'bg-red-900/40 text-red-400' }
      : { text: '中性', cls: 'bg-yellow-900/40 text-yellow-400' }

  return (
    <span className={`text-xs px-1.5 py-0.5 rounded ${config.cls}`}>
      {config.text}
    </span>
  )
}

function NewsDetailPanel({ item }: { item: SentimentResult }) {
  const scoreColor =
    item.label === 'positive' ? 'text-green-400' :
    item.label === 'negative' ? 'text-red-400' : 'text-yellow-400'

  const summary = item.summary && item.summary.trim() ? item.summary : null
  const hasDedicatedSummary = summary && summary !== item.title

  return (
    <div className="px-3 pb-3 pt-1 ml-4 border-l-2 border-gray-700/50">
      <div className="flex items-center gap-2 mb-2 flex-wrap">
        <LabelBadge label={item.label} />
        <span className={`text-xs font-mono font-semibold ${scoreColor}`}>
          AI 情感得分: {item.score >= 0 ? '+' : ''}{item.score.toFixed(3)}
        </span>
        <span className="text-xs text-gray-500">|</span>
        <span className="text-xs text-gray-500">来源: {item.source}</span>
        <span className="text-xs text-gray-500">
          {new Date(item.published_at).toLocaleString('zh-CN', {
            year: 'numeric', month: '2-digit', day: '2-digit',
            hour: '2-digit', minute: '2-digit',
          })}
        </span>
      </div>

      {item.ai_summary && (
        <div className="mb-2 px-2.5 py-1.5 rounded bg-purple-900/20 border border-purple-700/30">
          <div className="flex items-center gap-1 mb-0.5">
            <svg className="w-3 h-3 text-purple-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
            </svg>
            <span className="text-xs font-medium text-purple-400">DeepSeek AI 解读</span>
          </div>
          <p className="text-xs text-gray-300 leading-relaxed">{item.ai_summary}</p>
        </div>
      )}

      {hasDedicatedSummary ? (
        <p className="text-xs text-gray-400 leading-relaxed whitespace-pre-wrap">
          {summary}
        </p>
      ) : (
        <p className="text-xs text-gray-600 italic">该新闻来源未提供详细摘要</p>
      )}

      {item.url && (
        <a
          href={item.url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 text-xs text-blue-400 hover:text-blue-300 mt-2 transition-colors"
        >
          <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
          </svg>
          查看原文
        </a>
      )}
    </div>
  )
}

export default function NewsFeed({ items }: Props) {
  const [expandedIndex, setExpandedIndex] = useState<number | null>(null)

  if (!items || items.length === 0) {
    return (
      <div className="flex items-center justify-center h-32 text-gray-500 text-sm">
        暂无新闻
      </div>
    )
  }

  const toggle = (i: number) => {
    setExpandedIndex(prev => prev === i ? null : i)
  }

  return (
    <div className="space-y-0 divide-y divide-gray-800/50 max-h-[500px] overflow-y-auto">
      {items.map((item, i) => {
        const scoreColor =
          item.label === 'positive' ? 'text-green-400' :
          item.label === 'negative' ? 'text-red-400' : 'text-yellow-400'
        const scoreBg =
          item.label === 'positive' ? 'bg-green-900/20' :
          item.label === 'negative' ? 'bg-red-900/20' : 'bg-yellow-900/20'
        const isExpanded = expandedIndex === i

        return (
          <div key={i} className="group">
            <div
              onClick={() => toggle(i)}
              className={`px-3 py-2.5 cursor-pointer transition-colors
                ${isExpanded ? 'bg-gray-800/30' : 'hover:bg-gray-800/20'}`}
            >
              <div className="flex items-start gap-2">
                <div className="mt-1.5 shrink-0">
                  <SentimentDot label={item.label} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-start gap-2">
                    <p className={`text-sm text-gray-200 leading-snug flex-1
                      ${isExpanded ? '' : 'line-clamp-2'}`}>
                      {item.title}
                    </p>
                    <svg
                      className={`w-4 h-4 shrink-0 mt-0.5 text-gray-500 transition-transform duration-200
                        ${isExpanded ? 'rotate-180' : ''}`}
                      fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
                    >
                      <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                    </svg>
                  </div>

                  {item.ai_summary && (
                    <div className={`mt-1.5 px-2 py-1 rounded text-xs leading-relaxed ${scoreBg} border border-gray-700/40`}>
                      <span className="text-purple-400 font-medium mr-1">AI:</span>
                      <span className="text-gray-300">{item.ai_summary}</span>
                    </div>
                  )}

                  <div className="flex items-center gap-3 mt-1">
                    <span className="text-xs text-gray-500">
                      {new Date(item.published_at).toLocaleString('zh-CN', {
                        month: '2-digit', day: '2-digit',
                        hour: '2-digit', minute: '2-digit',
                      })}
                    </span>
                    <span className="text-xs text-gray-600">{item.source}</span>
                    <span className={`text-xs font-mono ${scoreColor}`}>
                      {item.score >= 0 ? '+' : ''}{item.score.toFixed(2)}
                    </span>
                    {item.url && (
                      <a
                        href={item.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        onClick={(e) => e.stopPropagation()}
                        className="inline-flex items-center gap-1 text-xs text-blue-400 hover:text-blue-300 transition-colors ml-auto shrink-0"
                      >
                        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                          <path strokeLinecap="round" strokeLinejoin="round" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                        </svg>
                        跳转原文
                      </a>
                    )}
                  </div>
                </div>
              </div>
            </div>

            {isExpanded && <NewsDetailPanel item={item} />}
          </div>
        )
      })}
    </div>
  )
}
