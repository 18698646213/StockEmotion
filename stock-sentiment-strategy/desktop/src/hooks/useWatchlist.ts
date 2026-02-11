import { useState, useEffect, useCallback } from 'react'

export interface WatchlistItem {
  ticker: string
  market: 'US' | 'CN'
  addedAt: string // ISO timestamp
}

const STORAGE_KEY = 'stock-sentiment-watchlist'

function loadWatchlist(): WatchlistItem[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const items = JSON.parse(raw)
    if (!Array.isArray(items)) return []
    return items
  } catch {
    return []
  }
}

function saveWatchlist(items: WatchlistItem[]): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(items))
  } catch {
    // localStorage full or unavailable
  }
}

export function useWatchlist() {
  const [items, setItems] = useState<WatchlistItem[]>(loadWatchlist)

  // Persist on every change
  useEffect(() => {
    saveWatchlist(items)
  }, [items])

  const add = useCallback((ticker: string, market: 'US' | 'CN') => {
    setItems(prev => {
      if (prev.some(i => i.ticker === ticker)) return prev
      return [...prev, { ticker, market, addedAt: new Date().toISOString() }]
    })
  }, [])

  const remove = useCallback((ticker: string) => {
    setItems(prev => prev.filter(i => i.ticker !== ticker))
  }, [])

  const toggle = useCallback((ticker: string, market: 'US' | 'CN') => {
    setItems(prev => {
      if (prev.some(i => i.ticker === ticker)) {
        return prev.filter(i => i.ticker !== ticker)
      }
      return [...prev, { ticker, market, addedAt: new Date().toISOString() }]
    })
  }, [])

  const has = useCallback((ticker: string) => {
    return items.some(i => i.ticker === ticker)
  }, [items])

  const usStocks = items.filter(i => i.market === 'US').map(i => i.ticker)
  const cnStocks = items.filter(i => i.market === 'CN').map(i => i.ticker)

  return { items, usStocks, cnStocks, add, remove, toggle, has }
}
