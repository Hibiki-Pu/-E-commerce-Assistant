import { useEffect, useState } from 'react'
import { getJson } from './format'
import { AppShell } from './Shell'
import './transaction-imports.css'

type Kind = 'orders' | 'refunds' | 'costs'
interface Issue { row: number | null; field: string; message: string }
interface Report {
  valid: boolean; total_rows?: number; new_rows?: number; duplicate_count?: number;
  error_count?: number; inserted?: number; updated_cost_rows?: number;
  backfilled_order_lines?: number; missing_cost_lines?: number;
  sheet?: string; encoding?: string; sha256?: string; batch_id?: number;
  filename?: string; errors: Issue[]; warnings: Issue[]; duplicates: Issue[];
}
interface ImportMeta {
  ready: boolean; start_date?: string; end_date?: string;
  counts: Record<string, number>; missing_cost_lines?: number;
  batches: { id: number; kind: Kind; filename: string; sha256: string; imported_at: string }[];
}
const labels: Record<Kind, string> = { orders: '订单明细', refunds: '退款明细', costs: '商品成本' }
const headers: Record<Kind, string[]> = {
  orders: ['订单明细ID', '订单号', '商品编码', '商品名称', '支付日期', '订单状态', '数量', '实付金额'],
  refunds: ['退款流水ID', '订单明细ID', '退款日期', '退款状态', '退款金额'],
  costs: ['商品编码', '成本生效日期', '单位成本'],
}

function IssueList({ title, items, tone }: { title: string; items: Issue[]; tone: string }) {
  const [page, setPage] = useState(0)
  if (!items.length) return null
  const pages = Math.ceil(items.length / 25)
  return <section className={'issue-list ' + tone}>
    <h3>{title} <span>{items.length} 项</span></h3>
    <div className="table-scroll"><table>
      <thead><tr><th>原始行号</th><th>字段</th><th>说明</th></tr></thead>
      <tbody>{items.slice(page * 25, page * 25 + 25).map((item, i) => <tr key={i}>
        <td>{item.row === null ? '文件级' : `第 ${item.row} 行`}</td>
        <td>{item.field}</td><td>{item.message}</td>
      </tr>)}</tbody>
    </table></div>
    {pages > 1 && <div className="issue-pager">
      <button disabled={page === 0} onClick={() => setPage(p => p - 1)}>上一页</button>
      <span>{page + 1} / {pages} 页 · 全部结果可下载，无截断</span>
      <button disabled={page === pages - 1} onClick={() => setPage(p => p + 1)}>下一页</button>
    </div>}
  </section>
}

export function TransactionImports() {
  const [kind, setKind] = useState<Kind>('orders')
  const [file, setFile] = useState<File | null>(null)
  const [start, setStart] = useState('2026-08-01')
  const [end, setEnd] = useState('2026-08-30')
  const [meta, setMeta] = useState<ImportMeta | null>(null)
  const [report, setReport] = useState<Report | null>(null)
  const [busy, setBusy] = useState(false)
  const [committed, setCommitted] = useState(false)
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    getJson<ImportMeta>('/api/imports/meta', controller.signal).then(result => {
      setMeta(result)
      if (result.ready && result.start_date && result.end_date) {
        setStart(result.start_date); setEnd(result.end_date)
      }
    }).catch(e => { if (e.name !== 'AbortError') setError(e.message) })
    return () => controller.abort()
  }, [revision])

  function invalidate() { setReport(null); setCommitted(false); setError('') }

  async function upload(action: 'preview' | 'commit') {
    if (!file) { setError('请先选择文件'); return }
    if (!start || !end || start > end) { setError('请填写有效观察期，开始日期不能晚于结束日期'); return }
    const body = new FormData()
    body.append('kind', kind); body.append('start', start); body.append('end', end); body.append('file', file)
    setBusy(true); setError(''); setCommitted(false)
    try {
      const response = await fetch('/api/imports/' + action, {
        method: 'POST', headers: { 'X-Import-Request': 'commerce-insight' }, body,
        signal: AbortSignal.timeout(60_000),
      })
      const result = await response.json()
      const next = { ...result, errors: result.errors || [], warnings: result.warnings || [], duplicates: result.duplicates || [] }
      if (!response.ok && !result.errors) throw new Error(result.error || '导入请求失败')
      setReport(next)
      if (response.ok && action === 'commit') { setCommitted(true); setRevision(v => v + 1) }
    } catch (e) {
      setReport(null)
      const message = e instanceof Error ? e.message : '连接失败'
      setError(action === 'commit'
        ? `未收到明确提交结果：${message}。请重新预览同一文件确认；若已提交会显示重复，不会再次计数。`
        : `校验请求失败：${message}。请检查本地后端。`)
    } finally { setBusy(false) }
  }

  function downloadReport() {
    const blob = new Blob([JSON.stringify(report, null, 2)], { type: 'application/json;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url; link.download = 'transaction-import-report.json'; link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }

  return <AppShell page="imports" title="交易表导入" sourceTag="用户导入 · 来源未核验">
    <div className="import-page">
    <main>
      <div className="eyebrow">DATA IMPORT / 02</div>
      <h1>先检查数据，再开始复盘。</h1>
      <p className="import-intro">导入订单、退款和成本。保留错误行，明确处理重复，让每个指标都能追溯。</p>
      <div className="import-notice"><strong>三个数据源，独立保存。</strong> 本页写入单店铺交易导入库，不覆盖模拟数据或公开财报。
        上传数据来源未核验，不自动认定为真实商家数据。公司财报没有订单流水，请使用<a href="/public-financials">公开财报入口</a>。</div>

      <div className="import-layout">
        <section className="panel upload-panel">
          <h2>01 / 选择数据与观察期</h2>
          <fieldset disabled={busy}>
            <label htmlFor="import-kind">数据类型</label>
            <select id="import-kind" value={kind} onChange={e => { setKind(e.target.value as Kind); invalidate() }}>
              {Object.entries(labels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
            <div className="import-dates"><div><label htmlFor="scope-start">观察期开始</label>
              <input id="scope-start" type="date" value={start} disabled={meta?.ready} onInput={e => { setStart(e.currentTarget.value); invalidate() }} /></div>
              <div><label htmlFor="scope-end">观察期结束</label>
                <input id="scope-end" type="date" value={end} disabled={meta?.ready} onInput={e => { setEnd(e.currentTarget.value); invalidate() }} /></div></div>
            <p className="import-help">包含首尾，最多 90 天。首个成功导入后固定，请确保这段期间的订单和退款数据完整；未上传记录不会被系统推断补齐。</p>
            <label htmlFor="transaction-file">选择 Excel / CSV 文件</label>
            <input id="transaction-file" type="file" accept=".csv,.xlsx" onChange={e => { setFile(e.target.files?.[0] || null); invalidate() }} />
            <p className="import-help">每次一个文件，最多 5 MB / 5000 行。XLSX 多工作表时读取「{labels[kind]}」；CSV 支持 UTF-8、GB18030。文件仅在本机处理，不保留原始附件。</p>
            <button className="primary" disabled={!file || busy} onClick={() => upload('preview')}>{busy ? '正在检查…' : '校验并预览'}</button>
          </fieldset>
        </section>

        <aside className="panel protocol-panel"><h2>表头与校验规则</h2>
          <div className="header-chips">{headers[kind].map(h => <code key={h}>{h}</code>)}</div>
          <p>首行为表头，支持模板中英文列名，列顺序可调整。额外列、重复表头或缺字段会报错，不会悄悄忽略。</p>
          <ul><li>编号须是文本，订单号可以重复，订单明细 ID 必须唯一。</li>
            <li>金额单位为人民币元，最多两位小数，程序转换为整数分。</li>
            <li>日期用 YYYY-MM-DD、YYYY/MM/DD 或 Excel 日期单元格。时间按上海业务日归属。</li>
            <li>缺失成本保持未知，利润不可计算；已有已知成本不自动覆盖。</li>
            <li>有任一错误则整份拒绝；相同主键不同内容报冲突。</li></ul>
          <details><summary>下载模拟测试文件（不是公司经营数据）</summary>
            <div className="example-links">
              <a href="/api/imports/examples/orders">订单示例</a><a href="/api/imports/examples/refunds">退款示例</a>
              <a href="/api/imports/examples/costs">成本缺失示例</a><a href="/api/imports/examples/costs_complete">补齐成本示例</a>
              <a href="/api/imports/examples/orders_errors">错误行示例</a>
            </div><p>测试文件日期为 2026-08-24～25，观察期可选 2026-08-01～30；编号均以 SIM 开头。</p>
          </details>
        </aside>
      </div>
      {error && <div className="error" role="alert">{error}</div>}

      {report && <section className="panel import-result" aria-live="polite">
        <div className="result-heading"><h2>02 / {committed ? '导入结果' : '校验预览'}</h2><button onClick={downloadReport}>下载完整校验结果 JSON</button></div>
        <p className={report.valid ? 'result-valid' : 'result-invalid'}>
          {committed ? `已提交：新增 ${report.inserted || 0} 行，补齐 ${report.backfilled_order_lines || 0} 条订单成本。`
            : report.valid ? '校验通过。预览没有写入数据库；请检查警告和重复行，再确认导入。' : '校验未通过：整份文件未导入，请修正下列错误后重新预览。'}
        </p>
        <div className="import-counts">
          <span><strong>{report.total_rows ?? '—'}</strong>数据行（含空白）</span><span><strong>{report.new_rows ?? 0}</strong>待新增</span>
          <span><strong>{report.duplicate_count ?? 0}</strong>相同重复</span><span><strong>{report.error_count ?? report.errors.length}</strong>错误</span>
          <span><strong>{report.updated_cost_rows ?? 0}</strong>成本版本补齐</span>
        </div>
        <p className="import-help">文件：{report.filename || file?.name} · 工作表：{report.sheet || '—'} · 编码：{report.encoding || '—'}。
          {report.missing_cost_lines !== undefined && ` 检查后的导入库仍有 ${report.missing_cost_lines} 条明细缺成本（有错误时此数量仅为试算）。`}</p>
        <IssueList key={'errors' + JSON.stringify(report.errors)} title="需要修正的错误" items={report.errors} tone="error-tone" />
        <IssueList key={'warnings' + JSON.stringify(report.warnings)} title="请确认的警告" items={report.warnings} tone="warning-tone" />
        <IssueList key={'duplicates' + JSON.stringify(report.duplicates)} title="明确跳过的重复行" items={report.duplicates} tone="duplicate-tone" />
        {!committed && <button className="primary" disabled={!report.valid || busy} onClick={() => upload('commit')}>{busy ? '正在提交…' : report.warnings.length ? '接受警告并确认导入' : '确认导入'}</button>}
        {committed && <a className="import-dashboard-link" href="/imported">查看导入数据经营看板 →</a>}
      </section>}

      <section className="panel import-history"><h2>03 / 当前导入库</h2>
        <p>{meta?.ready ? `${meta.counts.order_lines || 0} 条订单明细 · ${meta.counts.refunds || 0} 条退款 · ${meta.counts.product_costs || 0} 条成本版本 · ${meta.missing_cost_lines || 0} 条明细缺成本` : '尚未导入交易数据。可先导入成本再导订单，也可先导订单后补成本；退款必须在对应订单之后导入。'}</p>
        {!!meta?.batches.length && <div className="table-scroll"><table><thead><tr><th>批次</th><th>类型</th><th>文件名</th><th>导入时间（UTC）</th><th>文件 SHA256（前 12 位）</th></tr></thead>
          <tbody>{meta.batches.map(batch => <tr key={batch.id}><td>#{batch.id}</td><td>{labels[batch.kind]}</td><td>{batch.filename}</td><td>{batch.imported_at}</td><td><code title={batch.sha256}>{batch.sha256.slice(0, 12)}</code></td></tr>)}</tbody></table></div>}
        <p className="import-help">最近 50 个有效写入批次。纯重复导入不新增批次；所有成功行在数据库保留文件批次与原始行号。未提交的完整错误报告可在上方下载。</p>
      </section>
      <footer className="page-footer">仅本地处理 · 单店铺 / 人民币 · 不接模型，不执行表格文本或公式</footer>
    </main>
    </div>
  </AppShell>
}
