import React, { useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { getJson, money, shiftDate } from './format'
import { Trend } from './Trend'
import { PublicFinancials } from './PublicFinancials'
import { TransactionImports } from './TransactionImports'
import type { Change, Dashboard, Meta, MetricKey } from './types'
import './style.css'

function Icon({ name, size = 20 }: { name: string; size?: number }) {
  const paths: Record<string, React.ReactNode> = {
    chart: <><path d="M4 19V5M4 19h16M8 15v-4m5 4V7m5 8V4" /></>,
    grid: <><rect x="4" y="4" width="6" height="6" rx="1" /><rect x="14" y="4" width="6" height="6" rx="1" /><rect x="4" y="14" width="6" height="6" rx="1" /><rect x="14" y="14" width="6" height="6" rx="1" /></>,
    box: <><path d="m12 3 9 5v9l-9 5-9-5V8l9-5Zm0 9v10M3 8l9 4 9-4M7.5 5.5l9 5" /></>,
    book: <><path d="M4 4h6l2 2 2-2h6v15h-6l-2 2-2-2H4V4Zm8 2v15" /></>,
    spark: <path d="m12 3 2.4 6.6L21 12l-6.6 2.4L12 21l-2.4-6.6L3 12l6.6-2.4L12 3Z" />,
    arrow: <><path d="M5 12h14m-5-5 5 5-5 5" /></>,
    money: <><path d="m7 4 5 6 5-6M12 10v11M6 11h12M6 16h12" /></>,
    refund: <><path d="M4 10a8 8 0 1 1 1 8M4 4v6h6" /></>,
    alert: <><path d="m12 3 10 18H2L12 3ZM12 9v5m0 3v.1" /></>,
    check: <><circle cx="12" cy="12" r="9" /><path d="m8 12 3 3 5-6" /></>,
  }
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name] || paths.chart}</svg>
}

const metrics: { key: MetricKey; label: string; note: string; icon: string }[] = [
  { key: 'sales_cents', label: '销售额', note: '商品实付金额 · 按支付日', icon: 'money' },
  { key: 'refund_cents', label: '退款金额', note: '成功退款 · 按成功日', icon: 'refund' },
  { key: 'cost_cents', label: '商品成本', note: '采购成本 · 不随退款冲回', icon: 'box' },
  { key: 'contribution_cents', label: '商品贡献利润', note: '销售额 − 退款 − 商品成本', icon: 'chart' },
]

function ChangeValue({ change }: { change: Change }) {
  if (change.percent === null) return <span className="unavailable">— {change.reason}</span>
  return <span className="change" title={change.reason || undefined}>{Number(change.percent) > 0 ? '↗ +' : Number(change.percent) < 0 ? '↘ ' : ''}{change.percent}%{change.reason && <small>（前期为负）</small>}</span>
}

function App({ imported = false }: { imported?: boolean }) {
  const api = imported ? '/api/imports' : '/api'
  const [meta, setMeta] = useState<Meta | null>(null)
  const [data, setData] = useState<Dashboard | null>(null)
  const [draft, setDraft] = useState({ start: '', end: '', product: '' })
  const [filters, setFilters] = useState(draft)
  const [error, setError] = useState('')
  const [formError, setFormError] = useState('')
  const [retry, setRetry] = useState(0)
  const [tab, setTab] = useState('overview')

  useEffect(() => {
    const controller = new AbortController()
    setError('')
    getJson<Meta>(api + '/meta', controller.signal).then(result => {
      if (!result.start_date || !result.end_date) throw new Error('尚未导入交易数据，请点击侧栏的「交易表导入」')
      setMeta(result)
      const initial = { start: [result.start_date, shiftDate(result.end_date, -6)].sort().at(-1)!, end: result.end_date, product: '' }
      setDraft(initial); setFilters(initial)
    }).catch(e => { if (e.name !== 'AbortError') setError(e.message) })
    return () => controller.abort()
  }, [retry, api])

  useEffect(() => {
    if (!filters.start) return
    const controller = new AbortController()
    setData(null); setError('')
    const query = new URLSearchParams({ start: filters.start, end: filters.end })
    if (filters.product) query.set('product_id', filters.product)
    getJson<Dashboard>(api + '/dashboard?' + query, controller.signal).then(setData)
      .catch(e => { if (e.name !== 'AbortError') setError(e.message) })
    return () => controller.abort()
  }, [filters, api])

  function preset(days: number | null) {
    if (!meta) return
    const next = { ...draft, start: days ? [meta.start_date, shiftDate(meta.end_date, 1 - days)].sort().at(-1)! : meta.start_date, end: meta.end_date }
    setDraft(next); setFilters(next); setFormError('')
  }

  return <div className="app-shell">
    <aside className="sidebar">
      <a className="brand" href="#overview"><span className="brand-symbol"><Icon name="chart" size={25} /></span><span>商析 <b>AI</b><small>电商经营复盘助手</small></span></a>
      <div className="workspace"><span className="store-mark">商</span><div>{imported ? '导入店铺 · 未核验' : '模拟店铺'}<small>单店铺 · 人民币</small></div><span className="workspace-dot" /></div>
      <span className="nav-heading">工作空间</span>
      <nav>{[{ id: 'overview', name: '经营概览', icon: 'grid' }, { id: 'trends', name: '每日趋势', icon: 'chart' }, { id: 'products', name: '商品表现', icon: 'box' }, { id: 'definitions', name: '数据与口径', icon: 'book' }].map(item => <a key={item.id} href={'#' + item.id} className={tab === item.id ? 'active' : ''} onClick={() => setTab(item.id)}><Icon name={item.icon} />{item.name}{tab === item.id && <span className="nav-indicator" />}</a>)}</nav>
      <nav aria-label="公开数据"><a href="/public-financials"><Icon name="book" />公开财报导入</a></nav>
      <nav aria-label="交易数据"><a href="/imports"><Icon name="box" />交易表导入</a><a href={imported ? '/' : '/imported'}><Icon name="chart" />{imported ? '切换模拟看板' : '导入数据看板'}</a></nav>
      <div className="ai-note"><span className="mini-label"><Icon name="spark" size={17} /> AI 经营解读</span><strong>后续接入</strong><p>本阶段由程序计算指标，<br />不生成 AI 分析结论。</p></div>
      <div className="sidebar-footer"><span className="avatar">作</span><div>个人求职作品<small>本地演示 · 交易导入已接入</small></div></div>
    </aside>

    <div className="main-shell">
      <header className="topbar"><div>工作空间 <span>/</span> <strong>经营概览</strong></div><div className="topbar-right"><span className="local-dot" /> 本地运行 <span className="separator" /><span className="demo-tag">{imported ? '用户导入 · 来源未核验' : '模拟数据'}</span></div></header>
      <main id="overview">
        <div className="page-heading"><div><div className="eyebrow">COMMERCE INSIGHT / 01</div><h1>把经营变化，看清楚。</h1><p>从销售到商品贡献，让每一次复盘都有数据依据。</p></div><div className="period-stamp"><span>数据观察期</span><strong>{meta ? `${meta.start_date.replaceAll('-', '.')} — ${meta.end_date.replaceAll('-', '.')}` : '加载中'}</strong></div></div>
        <div className="simulation-banner"><Icon name="book" size={18} /><span>{imported ? <><strong>当前展示用户导入数据，来源未核验。</strong> 不包含模拟库与财报库。请保证声明观察期的数据完整；模拟测试文件也会计入此库，不能当成真实商家成果。</> : <><strong>这是一份模拟经营数据。</strong> 固定随机种子生成，仅用于个人项目展示，不代表真实商家经营结果。</>}</span><a href="#definitions">查看说明 <Icon name="arrow" size={14} /></a></div>

        {meta && <form className="filters" onSubmit={e => {
          e.preventDefault()
          const form = new FormData(e.currentTarget)
          const next = { start: String(form.get('start')), end: String(form.get('end')), product: String(form.get('product')) }
          if (next.start > next.end) { setFormError('开始日期不能晚于结束日期'); return }
          setFormError(''); setDraft(next); setFilters(next)
        }}>
          <div className="field date-field"><label htmlFor="start">开始日期</label><input id="start" name="start" type="date" min={meta.start_date} max={meta.end_date} required value={draft.start} onInput={e => { const value = e.currentTarget.value; setDraft(prev => ({ ...prev, start: value })) }} /></div>
          <span className="date-to">—</span><div className="field date-field"><label htmlFor="end">结束日期</label><input id="end" name="end" type="date" min={meta.start_date} max={meta.end_date} required value={draft.end} onInput={e => { const value = e.currentTarget.value; setDraft(prev => ({ ...prev, end: value })) }} /></div>
          <div className="field product-field"><label htmlFor="product">商品范围</label><select id="product" name="product" value={draft.product} onChange={e => { const value = e.currentTarget.value; setDraft(prev => ({ ...prev, product: value })) }}><option value="">全部商品</option>{meta.products.map(p => <option key={p.id} value={p.id}>{p.id} · {p.name}</option>)}</select></div>
          <button className="primary" type="submit">应用筛选 <Icon name="arrow" size={16} /></button>
          <div className="presets"><button type="button" onClick={() => preset(7)}>最近 7 天</button><button type="button" onClick={() => preset(30)}>30 天</button><button type="button" onClick={() => preset(null)}>全部</button></div>
        </form>}
        {formError && <div className="error" role="alert">{formError}</div>}
        {error ? <div className="error" role="alert">数据加载失败：{error}<button onClick={() => setRetry(v => v + 1)}>重新加载</button></div> : !data ? <div className="loading" role="status"><span className="spinner" />正在读取数据并计算指标…</div> : <>
          <div className="section-line"><h2>经营概览 <span>{filters.product ? meta?.products.find(p => p.id === filters.product)?.name : '全部商品'}</span></h2><span>{data.period.start} 至 {data.period.end} · {data.period.days} 天</span></div>
          <div className="metric-grid">{metrics.map(metric => <article key={metric.key} className={'metric-card ' + (metric.key === 'contribution_cents' ? 'featured' : '')}><div className="metric-top"><span>{metric.label}</span><span className="metric-icon"><Icon name={metric.icon} size={18} /></span></div><strong className={'metric-value ' + (data.summary[metric.key] === null ? 'null-value' : '')}>{money(data.summary[metric.key])}</strong><p>{metric.note}</p><div className="metric-bottom"><span>{data.comparison.label}</span><ChangeValue change={data.changes[metric.key]} /></div></article>)}</div>
          {data.summary.missing_cost_lines > 0 && <div className="quality-warning"><Icon name="alert" size={18} /><span><strong>{data.summary.missing_cost_lines} 条有效明细缺少成本。</strong> 已知成本小计 {money(data.summary.known_cost_cents)}；本期总成本与商品贡献利润暂不可计算。请先补齐成本，再判断经营表现。</span><a href="#products">定位商品 ↓</a></div>}

          <div className="analysis-grid">
            <section id="trends" className="panel trend-panel"><div className="panel-title"><div><h2>每日经营趋势</h2><p>沿时间看变化，异常从这里开始定位</p></div><span className="subtle-tag">{data.period.days} 天</span></div><Trend key={`${filters.start}-${filters.end}-${filters.product}`} daily={data.daily} /></section>
            <section className="panel comparison-panel"><div className="panel-title"><div><h2>{data.period.days === 7 ? '本周与上周' : '本期与上期'}</h2><p>相邻、等长的时间窗口</p></div><Icon name="chart" /></div><div className="comparison-period"><span><i />本期 {data.period.start.slice(5)} — {data.period.end.slice(5)}</span><span><i />上期 {data.comparison.start.slice(5)} — {data.comparison.end.slice(5)}</span></div><table className="comparison-table"><thead><tr><th>指标</th><th>本期 / 元</th><th>上期 / 元</th></tr></thead><tbody>{metrics.map(m => <tr key={m.key}><td>{m.label}</td><td>{money(data.summary[m.key], false)}</td><td>{data.comparison.summary ? money(data.comparison.summary[m.key], false) : '无完整数据'}</td></tr>)}</tbody></table><div className="comparison-footnote"><Icon name="book" size={16} /><p>{data.comparison.available ? '环比仅表示数值变化，不自动代表经营改善。前期为零或成本不完整时不计算百分比。' : '上期超出数据观察期，不将未覆盖日期当作零。'}</p></div></section>
          </div>

          <section id="products" className="panel products-panel"><div className="panel-title"><div><h2>商品表现 <span className="count-tag">{data.products.length}</span></h2><p>按商品贡献利润从高到低 · 成本不完整的商品置后</p></div><span className="subtle-tag">人民币 / 元</span></div><div className="table-scroll product-scroll"><table><thead><tr><th className="rank-cell">排名</th><th>商品</th><th>销售额</th><th>退款金额</th><th>商品成本</th><th>商品贡献利润</th><th>数据状态</th></tr></thead><tbody>{data.products.map((p, i) => <tr key={p.product_id}><td><span className={'rank ' + (i < 3 && p.cost_cents !== null ? 'top-rank' : '')}>{p.cost_cents === null ? '—' : String(i + 1).padStart(2, '0')}</span></td><td><div className="product-name">{p.name}</div><span className="product-meta">{p.product_id} · {p.category}</span></td><td>{money(p.sales_cents, false)}</td><td>{money(p.refund_cents, false)}</td><td>{money(p.cost_cents, false)}</td><td className={p.contribution_cents === null ? 'missing-number' : 'profit-number'}>{money(p.contribution_cents, false)}</td><td>{p.missing_cost_lines > 0 ? <span className="status-warning">缺 {p.missing_cost_lines} 条成本</span> : <span className="status-ok">成本完整</span>}</td></tr>)}</tbody></table>{data.products.length === 0 && <div className="empty">所选日期与商品没有支付或成功退款记录，请调整筛选。</div>}</div><div className="table-footer"><span>有效支付明细 {data.summary.paid_lines} 条 · 商品数量 {data.summary.quantity} 件</span><span>跨期退款 {money(data.summary.cross_period_refund_cents)}<small>（按所选范围判断）</small></span></div></section>
        </>}

        <section id="definitions" className="definitions-section"><div className="section-line"><h2>数据有边界，分析才可信。</h2><span>口径版本 1.0</span></div><div className="definition-grid"><article className="panel definition-card"><Icon name="book" /><h3>先统一指标口径</h3><ul><li>有效状态：已支付、已发货、已完成、已退款；待支付与已取消不计。</li><li>销售按支付日；退款按成功日，不重写历史销售；商品成本按支付日快照，退款不冲回成本。</li><li>商品贡献利润包含采购成本和退款冲减；不含佣金、广告、物流、人工、税费等，<strong>不等于净利润</strong>。</li><li>缺失成本不当零；前期为零时不计算环比，前期为负用绝对值作分母。</li></ul></article><article className="panel definition-card"><Icon name="check" /><h3>{imported ? "可追溯的导入数据" : "可检查的模拟数据"}</h3><p>数据范围 {meta?.start_date} 至 {meta?.end_date}。{imported ? "每条导入记录保留文件批次和原始行号；来源未经核验。" : "全部为模拟，无真实客户或商用效果。"}</p><div className="data-stats"><span><strong>{meta?.counts.order_lines.toLocaleString() ?? '—'}</strong>订单明细</span><span><strong>{meta?.counts.products ?? '—'}</strong>商品</span><span><strong>{meta?.counts.refunds ?? '—'}</strong>退款记录</span></div><div className="validation-line"><span className="local-dot" />{imported ? "导入校验" : "生成校验"}{meta?.validation_status === 'passed' ? '通过' : '待读取'} · {imported ? "原始上传记录独立存储" : `固定种子 ${meta?.seed ?? "—"}`}</div></article></div>
          {!imported && <details className="scenario-details"><summary>查看人为设置的经营变化场景 <span>生成规则说明，非 AI 分析</span></summary><div className="scenario-grid">{meta?.scenarios.map(s => <article key={s.id}><span>{s.start_date} — {s.end_date}</span><h3>{s.title}</h3><p>{s.description}</p></article>)}</div></details>}
        </section>
        <footer className="page-footer"><span>商析 AI · 个人求职展示项目</span><span>React + TypeScript / Flask / SQLite · {imported ? "仅本地导入数据" : "仅本地模拟数据"}</span></footer>
      </main>
    </div>
  </div>
}

createRoot(document.getElementById('root')!).render(<React.StrictMode>{location.pathname === '/public-financials' ? <PublicFinancials /> : location.pathname === '/imports' ? <TransactionImports /> : <App imported={location.pathname === '/imported'} />}</React.StrictMode>)
