import { useState } from 'react'
import { money } from './format'
import type { Daily, MetricKey } from './types'

const series: { key: MetricKey; label: string; color: string }[] = [
  { key: 'sales_cents', label: '销售额', color: '#6255d9' },
  { key: 'contribution_cents', label: '商品贡献利润', color: '#29988d' },
  { key: 'refund_cents', label: '退款金额', color: '#d8953e' },
]

export function Trend({ daily }: { daily: Daily[] }) {
  const [active, setActive] = useState<number | null>(null)
  const selected = active === null ? null : daily[active]
  const width = 800, height = 254, left = 66, right = 16, top = 20, bottom = 35
  // 此处仅计算 SVG 坐标；业务数值均由 API 提供。
  const values = daily.flatMap(row => series.map(s => row[s.key]).filter((v): v is number => v !== null))
  const min = Math.min(0, ...values), max = Math.max(100, ...values)
  const x = (i: number) => left + (daily.length === 1 ? .5 : i / (daily.length - 1)) * (width - left - right)
  const y = (v: number) => top + (max - v) / (max - min) * (height - top - bottom)
  const points = (key: MetricKey) => {
    let started = false
    return daily.map((row, i) => {
      const value = row[key]
      if (value === null) { started = false; return '' }
      const command = started ? 'L' : 'M'
      started = true
      return `${command}${x(i)},${y(value)}`
    }).join(' ')
  }
  return <>
    <div className="chart-legend">{series.map(s => <span key={s.key}><i style={{ background: s.color }} />{s.label}</span>)}<span className="unit">单位：元</span></div>
    <div className="chart-container">
      <svg viewBox={`0 0 ${width} ${height}`} aria-label="每日销售额、退款和商品贡献利润趋势；下方可展开精确数据" role="img">
        {[0, 1, 2, 3, 4].map(i => {
          const v = min + (max - min) * i / 4
          return <g key={i}><line x1={left} y1={y(v)} x2={width - right} y2={y(v)} stroke="#eeedf4" strokeDasharray="4 5" /><text x={left - 12} y={y(v) + 4} textAnchor="end">{(v / 100).toLocaleString('zh-CN', { maximumFractionDigits: 0 })}</text></g>
        })}
        {min < 0 && <line x1={left} y1={y(0)} x2={width - right} y2={y(0)} stroke="#bebacb" />}
        {series.map(s => <path key={s.key} d={points(s.key)} stroke={s.color} fill="none" strokeWidth="2.8" strokeLinecap="round" strokeLinejoin="round" />)}
        {daily.map((row, i) => <g key={row.date}>
          {(i === 0 || i === daily.length - 1 || i % Math.max(1, Math.ceil(daily.length / 7)) === 0) && <text x={x(i)} y={height - 8} textAnchor="middle">{row.date.slice(5).replace('-', '/')}</text>}
          {series.map(s => row[s.key] !== null && (daily.length <= 14 || active === i) ? <circle key={s.key} cx={x(i)} cy={y(row[s.key]!)} r={active === i ? 4.5 : 3} fill={s.color} stroke="white" strokeWidth="1.5" /> : null)}
          <rect x={x(i) - (width - left - right) / Math.max(daily.length - 1, 1) / 2} y={top} width={(width - left - right) / Math.max(daily.length - 1, 1)} height={height - top - bottom} fill="transparent" onMouseEnter={() => setActive(i)} onMouseLeave={() => setActive(null)} />
        </g>)}
      </svg>
    </div>
    <div className="chart-readout" aria-live="polite">{selected ? <><strong>{selected.date}</strong>{series.map(s => <span key={s.key}>{s.label} {money(selected[s.key])}</span>)}</> : '悬停查看每日金额 · 成本缺失的日期，贡献利润曲线留空'}</div>
    <details className="daily-details"><summary>查看每日明细</summary><div className="table-scroll"><table><thead><tr><th>日期</th><th>销售额</th><th>退款金额</th><th>商品成本</th><th>商品贡献利润</th></tr></thead><tbody>{daily.map(row => <tr key={row.date}><td>{row.date}</td><td>{money(row.sales_cents)}</td><td>{money(row.refund_cents)}</td><td>{money(row.cost_cents)}</td><td>{money(row.contribution_cents)}</td></tr>)}</tbody></table></div></details>
  </>
}
