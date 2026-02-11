import React from 'react'
import Plot from 'react-plotly.js'
import type { StockAnalysis } from '../types'

interface Props {
  analysis: StockAnalysis
}

export default function SentimentChart({ analysis }: Props) {
  const { sentiment_results, ticker } = analysis

  if (!sentiment_results || sentiment_results.length === 0) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-500 text-sm">
        暂无舆情数据
      </div>
    )
  }

  const sorted = [...sentiment_results].sort(
    (a, b) => new Date(a.published_at).getTime() - new Date(b.published_at).getTime()
  )

  const dates = sorted.map(r => r.published_at)
  const scores = sorted.map(r => r.score)
  const titles = sorted.map(r => r.title.slice(0, 60))
  const colors = sorted.map(r =>
    r.label === 'positive' ? '#22c55e' :
    r.label === 'negative' ? '#ef4444' : '#f59e0b'
  )

  const data: Plotly.Data[] = [
    {
      type: 'scatter',
      x: dates,
      y: scores,
      mode: 'lines+markers',
      marker: { color: colors, size: 8 },
      line: { color: 'rgba(255,255,255,0.15)', width: 1 },
      text: titles,
      hovertemplate: '<b>%{text}</b><br>得分: %{y:.3f}<br>%{x}<extra></extra>',
      name: '舆情',
    },
  ]

  const layout: Partial<Plotly.Layout> = {
    title: {
      text: `${ticker} - 舆情走势`,
      font: { color: '#e5e7eb', size: 14 },
    },
    paper_bgcolor: 'transparent',
    plot_bgcolor: 'rgba(17,24,39,0.5)',
    font: { color: '#9ca3af', size: 10 },
    height: 300,
    margin: { l: 50, r: 20, t: 40, b: 30 },
    yaxis: {
      range: [-1.1, 1.1],
      gridcolor: 'rgba(75,85,99,0.2)',
      title: { text: '得分', font: { size: 10 } },
    },
    xaxis: {
      gridcolor: 'rgba(75,85,99,0.2)',
    },
    showlegend: false,
    shapes: [
      { type: 'line', y0: 0.3, y1: 0.3, x0: 0, x1: 1, xref: 'paper', line: { color: '#22c55e', dash: 'dash', width: 1 } },
      { type: 'line', y0: -0.3, y1: -0.3, x0: 0, x1: 1, xref: 'paper', line: { color: '#ef4444', dash: 'dash', width: 1 } },
      { type: 'line', y0: 0, y1: 0, x0: 0, x1: 1, xref: 'paper', line: { color: '#4b5563', dash: 'dot', width: 1 } },
    ],
  }

  return (
    <Plot
      data={data}
      layout={layout}
      config={{ displayModeBar: false, responsive: true }}
      style={{ width: '100%' }}
    />
  )
}
