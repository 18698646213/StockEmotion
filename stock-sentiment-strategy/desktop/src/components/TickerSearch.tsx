import React, { useState, useRef, useEffect, useCallback } from 'react'
import { createPortal } from 'react-dom'
import { searchTickers, type SearchResult } from '../api'

interface Props {
  market: string
  selected: string[]
  onChange: (tickers: string[]) => void
  placeholder?: string
  accentColor?: 'blue' | 'orange'
}

export default function TickerSearch({
  market,
  selected,
  onChange,
  placeholder = '搜索代码或名称...',
  accentColor = 'blue',
}: Props) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<SearchResult[]>([])
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [focusIdx, setFocusIdx] = useState(-1)
  const [dropStyle, setDropStyle] = useState<React.CSSProperties>({})
  const inputRef = useRef<HTMLInputElement>(null)
  const dropRef = useRef<HTMLDivElement>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const doSearch = useCallback(async (q: string) => {
    if (!q.trim()) {
      setResults([])
      setOpen(false)
      return
    }
    setLoading(true)
    try {
      const data = await searchTickers(q, market)
      setResults(data)
      setOpen(data.length > 0)
      setFocusIdx(-1)
    } catch {
      setResults([])
    } finally {
      setLoading(false)
    }
  }, [market])

  const handleInput = (val: string) => {
    setQuery(val)
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => doSearch(val), 200)
  }

  const addTicker = (code: string) => {
    const upper = code.toUpperCase()
    if (!selected.includes(upper)) {
      onChange([...selected, upper])
    }
    setQuery('')
    setResults([])
    setOpen(false)
    inputRef.current?.focus()
  }

  const removeTicker = (code: string) => {
    onChange(selected.filter(t => t !== code))
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setFocusIdx(prev => Math.min(prev + 1, results.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setFocusIdx(prev => Math.max(prev - 1, 0))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      if (focusIdx >= 0 && focusIdx < results.length) {
        addTicker(results[focusIdx].code)
      } else if (query.trim()) {
        addTicker(query.trim())
      }
    } else if (e.key === 'Escape') {
      setOpen(false)
    }
  }

  // Position dropdown using fixed positioning relative to the input
  const updateDropdownPosition = useCallback(() => {
    if (!inputRef.current) return
    const rect = inputRef.current.getBoundingClientRect()
    setDropStyle({
      position: 'fixed',
      top: rect.bottom + 4,
      left: rect.left,
      width: rect.width,
      zIndex: 9999,
    })
  }, [])

  useEffect(() => {
    if (open) updateDropdownPosition()
  }, [open, updateDropdownPosition])

  // Close on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (dropRef.current && !dropRef.current.contains(e.target as Node) &&
          inputRef.current && !inputRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  // Close on scroll of any parent
  useEffect(() => {
    if (!open) return
    const handler = () => {
      if (open) updateDropdownPosition()
    }
    window.addEventListener('scroll', handler, true)
    return () => window.removeEventListener('scroll', handler, true)
  }, [open, updateDropdownPosition])

  const tagBg = accentColor === 'orange'
    ? 'bg-orange-900/30 text-orange-300'
    : 'bg-blue-900/30 text-blue-300'

  const inputRing = accentColor === 'orange'
    ? 'focus:ring-orange-500 focus:border-orange-500'
    : 'focus:ring-blue-500 focus:border-blue-500'

  const dropdown = open && results.length > 0 ? createPortal(
    <div
      ref={dropRef}
      style={dropStyle}
      className="bg-gray-800 border border-gray-700 rounded-lg shadow-2xl max-h-52 overflow-y-auto"
    >
      {results.map((item, idx) => {
        const isSelected = selected.includes(item.code.toUpperCase())
        return (
          <button
            key={`${item.market}-${item.code}`}
            onClick={() => addTicker(item.code)}
            className={`w-full text-left px-3 py-2 text-sm flex items-center justify-between
              transition-colors border-b border-gray-700/40 last:border-0
              ${idx === focusIdx ? 'bg-gray-700/60' : 'hover:bg-gray-700/40'}
              ${isSelected ? 'opacity-40' : ''}`}
          >
            <div className="flex items-center gap-2 min-w-0">
              <span className="font-mono text-gray-200 shrink-0">{item.code}</span>
              <span className="text-gray-400 truncate">{item.name}</span>
            </div>
            {isSelected && (
              <span className="text-[9px] text-gray-500 shrink-0">已添加</span>
            )}
          </button>
        )
      })}
    </div>,
    document.body,
  ) : null

  return (
    <div>
      {/* Selected tags */}
      {selected.length > 0 && (
        <div className="flex flex-wrap gap-1 mb-1.5">
          {selected.map(code => (
            <span
              key={code}
              className={`inline-flex items-center gap-1 text-xs font-mono px-2 py-0.5 rounded ${tagBg}`}
            >
              {code}
              <button
                onClick={() => removeTicker(code)}
                className="hover:text-white transition-colors ml-0.5"
              >
                <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </span>
          ))}
        </div>
      )}

      {/* Search input */}
      <div className="relative">
        <svg className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-500 pointer-events-none"
          fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
        </svg>
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={e => handleInput(e.target.value)}
          onKeyDown={handleKeyDown}
          onFocus={() => { if (results.length > 0) setOpen(true) }}
          placeholder={placeholder}
          className={`w-full bg-gray-800 border border-gray-700 rounded-lg pl-8 pr-8 py-2 text-sm
            text-gray-200 focus:outline-none focus:ring-1 ${inputRing}
            placeholder-gray-600`}
        />
        {loading && (
          <div className="absolute right-2.5 top-1/2 -translate-y-1/2">
            <svg className="animate-spin h-3.5 w-3.5 text-gray-500" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
          </div>
        )}
        {!loading && query && (
          <button
            onClick={() => { setQuery(''); setResults([]); setOpen(false) }}
            className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-600 hover:text-gray-400"
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        )}
      </div>

      {dropdown}
    </div>
  )
}
