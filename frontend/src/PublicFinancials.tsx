import { useEffect, useState } from 'react'
import { AppShell } from './Shell'
import './public-financials.css'

type DatasetType = 'annual' | 'quarterly' | 'business'
type Fact = { period: string; business_unit: string; metric: string; value: string; value_cents: number; dataset_type: DatasetType; source_page: string; source_url: string; notes: string }
type Check = { period: string; kind: string; metric: string; status: 'passed' | 'pending' | 'failed' }
type Overview = { facts: Fact[]; checks: Check[]; manifest: { company_name: string; company_code: string; warnings: string[] }; metrics: Record<string, string>; business_units: Record<string, string> }
type Preview = { valid: boolean; rows: number; new_rows: number; duplicates: number; inserted?: number; errors: { row: number | null; message: string }[]; error_count: number; samples: Fact[]; checks: Check[] }
const labels: Record<DatasetType, string> = { annual: '年度财务', quarterly: '单季财务', business: '业务分类' }
const amount = (cents: number | null) => cents === null ? '—' : (cents / 100).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

export function PublicFinancials() {
  const [data, setData] = useState<Overview | null>(null)
  const [datasetType, setDatasetType] = useState<DatasetType>('annual')
  const [view, setView] = useState<DatasetType>('annual')
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<Preview | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [loadError, setLoadError] = useState('')
  const [message, setMessage] = useState('')
  const [revision, setRevision] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    setLoadError('')
    fetch('/api/public-financials', { signal: controller.signal }).then(async response => {
      if (!response.ok) throw new Error('无法读取公开财报数据，请确认后端已重启到第二阶段版本。')
      return response.json() as Promise<Overview>
    }).then(setData).catch(e => { if (e.name !== 'AbortError') setLoadError(e.message) })
    return () => controller.abort()
  }, [revision])

  function resetPreview() { setPreview(null); setError(''); setMessage('') }
  async function upload(action: 'preview' | 'commit') {
    if (!file || busy) return
    setBusy(true); setError(''); setMessage('')
    const form = new FormData()
    form.set('dataset_type', datasetType); form.set('file', file)
    try {
      const response = await fetch('/api/public-financials/' + action, { method: 'POST', headers: { 'X-Import-Request': 'commerce-insight' }, body: form })
      const result = await response.json()
      if ('error' in result) throw new Error(result.error)
      if (!('valid' in result)) throw new Error('服务响应异常，请重试')
      setPreview(result)
      if (response.ok && action === 'commit') {
        setMessage(`导入完成：新增 ${result.inserted} 项，跳过 ${result.duplicates} 项完全重复数据。`)
        setView(datasetType); setRevision(v => v + 1)
      }
    } catch (e) {
      setPreview(null)
      setError(e instanceof Error ? e.message : '导入失败，请重试')
    } finally { setBusy(false) }
  }
  const facts = data?.facts.filter(f => f.dataset_type === view).sort((a, b) => a.period.localeCompare(b.period) || a.business_unit.localeCompare(b.business_unit) || a.metric.localeCompare(b.metric)) ?? []
  const annualValue = (year: string, metric: string) => data?.facts.find(f => f.dataset_type === 'annual' && f.period === year && f.metric === metric)?.value_cents ?? null
  const passed = data?.checks.filter(c => c.status === 'passed').length ?? 0
  const pending = data?.checks.filter(c => c.status === 'pending').length ?? 24
  const failed = data?.checks.filter(c => c.status === 'failed').length ?? 0
  const imported = data?.facts.length ?? 0

  return <AppShell page="public-financials" title="公开财报导入" sourceTag="公开资料 · 独立数据">
    <div className="public-page">
    <main className="public-main">
      <div className="public-heading"><div><div className="eyebrow">COMMERCE INSIGHT / 02</div><h1>从公开财报，建立可核查的数据底稿。</h1><p>厦门吉宏科技股份有限公司 · 002803.SZ · 2022—2025</p></div><span className="public-badge">公开年报 · 非内部订单</span></div>
      <div className="public-notice"><strong>独立数据分支。</strong> 本页导入真实公开汇总数据，原模拟订单库保持不变。金额为人民币元；年度、季度、业务分类分别分析，禁止合并求和。</div>

      <section className="public-section panel">
        <div className="public-section-title"><div><span className="public-step">01 / IMPORT</span><h2>选择文件，先预览再导入</h2></div><span className="subtle-tag">本地处理 · 最大 5 MB</span></div>
        <div className="public-import-grid">
          <form className="public-form" onSubmit={e => { e.preventDefault(); void upload('preview') }}>
            <label htmlFor="public-type">数据类型 / Excel 工作表</label>
            <select id="public-type" value={datasetType} disabled={busy} onChange={e => { setDatasetType(e.target.value as DatasetType); resetPreview() }}>
              {(Object.keys(labels) as DatasetType[]).map(type => <option key={type} value={type}>{labels[type]} · {type}_data</option>)}
            </select>
            <label htmlFor="public-file">上传标准 CSV 或 Excel 文件</label>
            <input id="public-file" type="file" accept=".csv,.xlsx" required disabled={busy} onChange={e => { setFile(e.target.files?.[0] ?? null); resetPreview() }} />
            <p>一个 Excel 包含三张原始数据表，每次只读取所选工作表。CSV 须匹配所选类型，采用 UTF-8 编码。</p>
            <div className="public-actions"><button className="primary" disabled={!file || busy} type="submit">{busy ? '正在校验…' : '校验并预览'}</button><button className="public-confirm" disabled={busy || !preview?.valid || preview.inserted !== undefined} type="button" onClick={() => void upload('commit')}>确认导入</button></div>
          </form>
          <aside className="public-downloads"><h3>使用已核验的数据包</h3><p>132 项事实 · 4 份年报 · 每项保留页码与来源链接</p><a className="public-download-primary" href="/api/public-financials/files/jihong_public_financials.xlsx">下载 Excel 数据包 ↗</a><div className="public-csv-links">{(Object.keys(labels) as DatasetType[]).map(type => <a key={type} href={`/api/public-financials/files/${type}_data.csv`}>{labels[type]} CSV ↓</a>)}</div><p>建议顺序：年度 → 季度 → 业务分类。重复导入会跳过相同事实；存在金额、来源冲突或合计不一致时，整批拒绝写入。</p></aside>
        </div>
        {error && <div className="error" role="alert">{error}</div>}
        {message && <div className="public-success" role="status">{message}</div>}
        {preview && <div className="public-preview" aria-live="polite">
          <h3>{preview.valid ? '校验通过' : '校验未通过，不会写入数据'}<span>文件记录 {preview.rows} · 可新增 {preview.new_rows} · 重复 {preview.duplicates}</span></h3>
          {preview.errors.length > 0 && <div className="public-errors" role="alert"><p>共 {preview.error_count} 个问题，最多显示前 100 个：</p><ul>{preview.errors.map((item, index) => <li key={index}>{item.row ? `第 ${item.row} 行：` : ''}{item.message}</li>)}</ul></div>}
          <p className="public-fineprint">预览前 6 项。这里的校验覆盖格式、重复和可计算合计，不代表对上传内容完成财务审计。</p>
          <div className="table-scroll"><table><thead><tr><th>期间</th><th>业务</th><th>指标</th><th>金额 / 元</th><th>来源</th></tr></thead><tbody>{preview.samples.map((fact, index) => <tr key={index}><td>{fact.period}</td><td>{data?.business_units[fact.business_unit] ?? fact.business_unit}</td><td>{data?.metrics[fact.metric] ?? fact.metric}</td><td className="public-number">{amount(fact.value_cents)}</td><td><a href={fact.source_url} target="_blank" rel="noreferrer">年报第 {fact.source_page} 页 ↗</a></td></tr>)}</tbody></table></div>
        </div>}
      </section>

      {loadError && <div className="error" role="alert">{loadError}<button onClick={() => setRevision(v => v + 1)}>重新加载</button></div>}
      <section className="public-section panel">
        <div className="public-section-title"><div><span className="public-step">02 / VERIFY</span><h2>已导入数据与合计核验</h2></div><span className="subtle-tag">{imported} / 132 项</span></div>
        <div className="public-quality"><span>合计一致 <strong>{passed}</strong></span><span>等待补齐 <strong>{pending}</strong></span><span>合计不符 <strong>{failed}</strong></span><p>四个季度及各业务之和分别对照年度值。未导入的值显示「—」，不补零。</p></div>
        {imported === 0 ? <div className="public-empty"><h3>{data ? '还没有导入公开财报数据' : '正在读取数据…'}</h3><p>下载上方文件，选择「年度财务」，完成预览和确认后，这里将显示年度汇总。</p></div> : <>
          <div className="table-scroll"><table className="public-annual"><caption>年度概览 · 人民币元 · 按各年原披露口径</caption><thead><tr><th>年度</th><th>营业收入</th><th>营业成本</th><th>毛利（计算值）</th><th>毛利率</th><th>归母净利润</th></tr></thead><tbody>{['2022', '2023', '2024', '2025'].map(year => {
            const revenue = annualValue(year, 'revenue'), cost = annualValue(year, 'cost_of_revenue')
            const gross = revenue === null || cost === null ? null : revenue - cost
            return <tr key={year}><td>{year}</td><td>{amount(revenue)}</td><td>{amount(cost)}</td><td>{amount(gross)}</td><td>{gross === null || !revenue ? '—' : (gross / revenue * 100).toFixed(2) + '%'}</td><td>{amount(annualValue(year, 'net_profit_parent'))}</td></tr>
          })}</tbody></table></div>
          <p className="public-fineprint">毛利 = 营业收入 − 营业成本，不等于净利润；这里不计算原模拟订单的商品贡献利润。</p>
          <div className="public-tabs" aria-label="数据视图">{(Object.keys(labels) as DatasetType[]).map(type => <button type="button" key={type} aria-pressed={view === type} className={view === type ? 'selected' : ''} onClick={() => setView(type)}>{labels[type]} <span>{data?.facts.filter(f => f.dataset_type === type).length}</span></button>)}</div>
          {facts.length ? <div className="table-scroll public-facts"><table><thead><tr><th>期间</th><th>业务</th><th>指标</th><th>金额 / 元</th><th>来源</th></tr></thead><tbody>{facts.map(fact => <tr key={[fact.period, fact.business_unit, fact.metric].join('/')}><td>{fact.period}</td><td>{data?.business_units[fact.business_unit]}</td><td>{data?.metrics[fact.metric]}</td><td className="public-number">{amount(fact.value_cents)}</td><td><a href={fact.source_url} target="_blank" rel="noreferrer">第 {fact.source_page} 页 ↗</a></td></tr>)}</tbody></table></div> : <div className="public-empty">这个类型还没有导入数据，请选择对应工作表后导入。</div>}
        </>}
      </section>

      <section className="public-boundaries"><span className="public-step">03 / DEFINITIONS</span><h2>先说明边界，再解释变化。</h2><ol>{data?.manifest.warnings.map(warning => <li key={warning}>{warning}</li>)}</ol><p>这是基于公开资料的个人分析项目，不代表与吉宏股份存在客户或实习合作。本阶段不生成 AI 结论，不提供投资建议。</p></section>
      <footer className="page-footer"><span>商析 AI · 第二阶段：公开财报导入</span><span>Excel / CSV → 格式校验 → 独立 SQLite → 来源追溯</span></footer>
    </main>
    </div>
  </AppShell>
}
