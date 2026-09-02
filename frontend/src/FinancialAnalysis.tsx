import { useEffect, useState } from 'react'
import { getJson } from './format'
import { AppShell, Icon } from './Shell'
import './financial-analysis.css'

type Source = { id: string; report_year: string; page: number; url: string }
type Metric = { id: string; key: string; label: string; value_cents?: number; value_percent?: string; previous_value_cents?: number | null; previous_value_percent?: string | null; yoy_percent?: string | null; change_percentage_points?: string | null; source_ids: string[] }
type Evidence = {
  evidence_hash: string; company: { code: string; name: string }; year: string; previous_year: string | null;
  core_metrics: Metric[]; anomalies: { id: string; level: string; title: string; evidence_ids: string[] }[];
  profit_cash_flow: { profit_cents: number; operating_cash_flow_cents: number; gap_cents: number; cash_profit_ratio_percent: string | null; boundary: string; source_ids: string[] };
  concentration: { reconciled: boolean; hhi: string; top_business: Business; businesses: Business[]; comparability_note: string | null };
  risks: { id: string; title: string; detail: string; evidence_ids: string[] }[]; sources: Source[]; analysis_boundaries: string[];
}
type Business = { id: string; label: string; revenue_cents: number; share_percent: string; source_ids: string[] }
type Claim = { text: string; evidence_ids: string[] }
type Narrative = { core_summary: Claim[]; year_over_year: Claim[]; profit_cash_flow: Claim[]; concentration: Claim[]; risks: { title: string; detail: string; evidence_ids: string[] }[] }
type Options = { companies: { code: string; name: string; years: string[] }[]; ai_configured: boolean; model: string }
type Generated = { evidence: Evidence; narrative: Narrative; review_status: string; trace: { response_id: string | null; model: string; generated_at: string; evidence_hash: string } }

const money = (cents: number) => (cents / 100 / 100_000_000).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' 亿元'
const signed = (value: string | null | undefined, suffix = '%') => value === null || value === undefined ? '无可比数据' : `${Number(value) > 0 ? '+' : ''}${value}${suffix}`

function TextSection({ title, items }: { title: string; items: Claim[] }) {
  return <section className="ai-text-section"><h3>{title}</h3><ul>{items.map((item, index) => <li key={index}><span>{item.text}</span><code>证据：{item.evidence_ids.join('、')}</code></li>)}</ul></section>
}

export function FinancialAnalysis() {
  const [options, setOptions] = useState<Options | null>(null)
  const [company, setCompany] = useState('')
  const [year, setYear] = useState('')
  const [evidence, setEvidence] = useState<Evidence | null>(null)
  const [generated, setGenerated] = useState<Generated | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    getJson<Options>('/api/financial-analysis/options', controller.signal).then(result => {
      setOptions(result)
      const first = result.companies[0]
      setCompany(first?.code || '')
      setYear(first?.years.at(-1) || '')
    }).catch(e => { if (e.name !== 'AbortError') setError(e.message) })
    return () => controller.abort()
  }, [])

  useEffect(() => {
    setGenerated(null); setEvidence(null); setError('')
    if (!company || !year) return
    const controller = new AbortController()
    getJson<Evidence>(`/api/financial-analysis/evidence?company_code=${encodeURIComponent(company)}&year=${encodeURIComponent(year)}`, controller.signal)
      .then(setEvidence).catch(e => { if (e.name !== 'AbortError') setError(e.message) })
    return () => controller.abort()
  }, [company, year])

  async function generate() {
    if (!company || !year || busy) return
    setBusy(true); setError(''); setGenerated(null)
    try {
      const response = await fetch('/api/financial-analysis/generate', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Analysis-Request': 'commerce-insight' }, body: JSON.stringify({ company_code: company, year }), signal: AbortSignal.timeout(75_000) })
      const result = await response.json()
      if (!response.ok) throw new Error(result.error || 'AI 分析生成失败')
      setGenerated(result); setEvidence(result.evidence)
    } catch (e) { setError(e instanceof Error ? e.message : 'AI 分析生成失败') }
    finally { setBusy(false) }
  }

  const selectedCompany = options?.companies.find(item => item.code === company)
  return <AppShell page="financial-analysis" title="AI 财报分析" sourceTag="公开财报 · 待人工复核">
    <main className="financial-analysis-page">
      <div className="analysis-hero"><div><div className="eyebrow">FINANCIAL ANALYSIS / 03</div><h1>先算清楚，再让 AI 解释。</h1><p>选择公司和年份，程序生成可核对的分析底稿；模型只能基于这些证据组织文字。</p></div><span className="analysis-status"><Icon name="spark" size={16} />{options?.ai_configured ? `${options.model} 已配置` : '模型尚未配置'}</span></div>

      <section className="analysis-controls panel">
        <div><label htmlFor="analysis-company">公司</label><select id="analysis-company" value={company} onChange={e => { setCompany(e.target.value); setYear(options?.companies.find(item => item.code === e.target.value)?.years.at(-1) || '') }}>{options?.companies.map(item => <option key={item.code} value={item.code}>{item.name} · {item.code}</option>)}</select></div>
        <div><label htmlFor="analysis-year">年份</label><select id="analysis-year" value={year} onChange={e => setYear(e.target.value)} disabled={!selectedCompany?.years.length}><option value="">请选择</option>{selectedCompany?.years.map(item => <option key={item} value={item}>{item} 年</option>)}</select></div>
        <button className="primary" type="button" onClick={generate} disabled={!evidence || !options?.ai_configured || busy}>{busy ? 'AI 正在分析…' : options?.ai_configured ? '生成 AI 分析' : '需配置 API Key'}</button>
        <p>{selectedCompany?.years.length ? '切换年份会重新读取财报证据。调用模型可能产生 API 费用；结果标记为待人工复核。' : <>尚无可分析年份，请先到<a href="/public-financials">公开财报导入</a>完成年度和业务分类数据。</>}</p>
      </section>

      {error && <div className="error" role="alert">{error}</div>}
      {generated && <section className="panel ai-narrative" aria-live="polite"><div className="analysis-section-title"><div><span>AI EXPLANATION</span><h2>AI 财报解读</h2></div><span className="pending-review">AI 生成 · 待人工复核</span></div><div className="ai-text-grid"><TextSection title="核心指标摘要" items={generated.narrative.core_summary} /><TextSection title="同比变化和异常" items={generated.narrative.year_over_year} /><TextSection title="利润与现金流差异" items={generated.narrative.profit_cash_flow} /><TextSection title="业务集中度" items={generated.narrative.concentration} /><section className="ai-text-section wide"><h3>风险提示</h3>{generated.narrative.risks.map((risk, index) => <article key={index}><strong>{risk.title}</strong><p>{risk.detail}</p><code>证据：{risk.evidence_ids.join('、')}</code></article>)}</section></div><footer>模型 {generated.trace.model} · 证据指纹 {generated.trace.evidence_hash.slice(0, 12)} · 本次结果未自动保存</footer></section>}

      {!evidence && !error && <div className="analysis-loading" role="status">{year ? '正在计算财报分析底稿…' : '等待已导入的年度和业务分类数据'}</div>}
      {evidence && <>
        <section className="evidence-heading"><div><span>PROGRAM-CALCULATED EVIDENCE</span><h2>{evidence.company.name} · {evidence.year} 年分析底稿</h2></div><span>整数分计算 · as_reported</span></section>
        <div className="analysis-metric-grid">{evidence.core_metrics.map(metric => <article className="analysis-metric panel" key={metric.id}><span>{metric.label}</span><strong>{metric.value_cents !== undefined ? money(metric.value_cents) : `${metric.value_percent}%`}</strong><p>{metric.yoy_percent !== undefined ? `同比 ${signed(metric.yoy_percent)}` : `同比 ${signed(metric.change_percentage_points, ' 个百分点')}`}</p><code>{metric.id}</code></article>)}</div>

        <div className="analysis-detail-grid">
          <section className="panel analysis-detail"><div className="analysis-section-title"><div><span>CHANGE CHECK</span><h2>同比变化和异常指标</h2></div><strong>{evidence.anomalies.length}</strong></div>{evidence.anomalies.length ? <ul className="anomaly-list">{evidence.anomalies.map(item => <li key={item.id}><Icon name="alert" size={16} /><span>{item.title}<code>{item.evidence_ids.join('、')}</code></span></li>)}</ul> : <p className="analysis-empty">没有指标触发当前异常阈值；这不代表没有经营风险。</p>}</section>
          <section className="panel analysis-detail"><div className="analysis-section-title"><div><span>CASH VS PROFIT</span><h2>利润与经营现金流</h2></div><code>CASH-PROFIT-GAP</code></div><div className="cash-comparison"><span><small>归母净利润</small><strong>{money(evidence.profit_cash_flow.profit_cents)}</strong></span><span><small>经营现金流</small><strong>{money(evidence.profit_cash_flow.operating_cash_flow_cents)}</strong></span><span><small>现金流减利润</small><strong>{money(evidence.profit_cash_flow.gap_cents)}</strong></span></div><p>{evidence.profit_cash_flow.boundary}</p></section>
        </div>

        <section className="panel concentration-panel"><div className="analysis-section-title"><div><span>BUSINESS CONCENTRATION</span><h2>业务集中度分析</h2></div><span>HHI {evidence.concentration.hhi} · {evidence.concentration.reconciled ? '与年度收入一致' : '合计未通过'}</span></div><div className="business-bars">{evidence.concentration.businesses.map(item => <div key={item.id}><div><strong>{item.label}</strong><span>{money(item.revenue_cents)} · {item.share_percent}%</span></div><i><b style={{ width: `${Math.max(1, Number(item.share_percent))}%` }} /></i><code>{item.id}</code></div>)}</div>{evidence.concentration.comparability_note && <p className="quality-warning">{evidence.concentration.comparability_note}</p>}</section>

        <div className="analysis-detail-grid">
          <section className="panel analysis-detail"><div className="analysis-section-title"><div><span>RISK REGISTER</span><h2>程序风险提示</h2></div></div><div className="risk-list">{evidence.risks.map(item => <article key={item.id}><strong>{item.title}</strong><p>{item.detail}</p><code>{item.id}</code></article>)}</div></section>
          <section className="panel analysis-detail"><div className="analysis-section-title"><div><span>SOURCES</span><h2>数据来源</h2></div><strong>{evidence.sources.length}</strong></div><div className="source-list">{evidence.sources.map(source => <a key={source.id} href={source.url} target="_blank" rel="noreferrer"><span>{source.report_year} 年报 · 第 {source.page} 页</span><code>{source.id}</code><b>↗</b></a>)}</div><p>相同年报页只列一次。点击打开巨潮资讯官方 PDF，自行核对原文。</p></section>
        </div>
        <div className="analysis-boundary">{evidence.analysis_boundaries.map(item => <span key={item}><Icon name="check" size={15} />{item}</span>)}</div>
      </>}
      <footer className="page-footer"><span>商析 AI · 第三阶段：AI 财报分析</span><span>程序计算 → 结构化证据 → 模型解释 → 人工复核</span></footer>
    </main>
  </AppShell>
}
