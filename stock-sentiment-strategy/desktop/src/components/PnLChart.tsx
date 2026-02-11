import React from 'react'
import Plot from 'react-plotly.js'

interface Props {
  equityCurve: { date: string; value: number }[]
  initialCapital: number
}

export default function PnLChart({ equityCurve, initialCapital }: Props) {
  if (!equityCurve || equityCurve.length === 0) {
    return (
      <div className="flex items-center justify-center h-48 text-gray-500 text-sm">
        暂无收益数据
      </div>
    )
  }

  const dates = equityCurve.map(p => p.date)
  const values = equityCurve.map(p => p.value)
  const baseline = dates.map(() => initialCapital)

  // Calculate drawdown areas
  let peak = values[0]
  const drawdown = values.map(v => {
    if (v > peak) peak = v
    return peak > 0 ? ((peak - v) / peak) * 100 : 0
  })

  const data: Plotly.Data[] = [
    {
      type: 'scatter',
      x: dates,
      y: values,
      mode: 'lines',
      name: '净值',
      line: { color: values[values.length - 1] >= initialCapital ? '#22c55e' : '#ef4444', width: 2 },
      fill: 'tonexty',
      fillcolor: values[values.length - 1] >= initialCapital
        ? 'rgba(34,197,94,0.1)' : 'rgba(239,68,68,0.1)',
      hovertemplate: '%{x}<br>净值: %{y:,.2f}<extra></extra>',
    },
    {
      type: 'scatter',
      x: dates,
      y: baseline,
      mode: 'lines',
      name: '基准',
      line: { color: '#6b7280', width: 1, dash: 'dash' },
      hoverinfo: 'skip',
    },
  ]

  const layout: Partial<Plotly.Layout> = {
    title: { text: '收益曲线', font: { color: '#e5e7eb', size: 13 } },
    paper_bgcolor: 'transparent',
    plot_bgcolor: 'rgba(17,24,39,0.5)',
    font: { color: '#9ca3af', size: 10 },
    height: 280,
    margin: { l: 60, r: 20, t: 35, b: 35 },
    xaxis: {
      gridcolor: 'rgba(75,85,99,0.2)',
      tickformat: '%Y-%m-%d',
    },
    yaxis: {
      gridcolor: 'rgba(75,85,99,0.2)',
      title: { text: '净值', font: { size: 10, color: '#6b7280' } },
    },
    showlegend: false,
    hovermode: 'x unified',
  }

  return (
    <Plot
      data={data}
      layout={layout}
      config={{
        displayModeBar: false,
        responsive: true,
        locale: 'zh-CN',
      }}
      style={{ width: '100%' }}
    />
  )
}
