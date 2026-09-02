import { useEffect, useState, type ReactNode } from 'react'

export type ShellPage = 'dashboard' | 'imported' | 'public-financials' | 'imports'
type Theme = 'light' | 'dark'

export function Icon({ name, size = 20 }: { name: string; size?: number }) {
  const paths: Record<string, ReactNode> = {
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
    sun: <><circle cx="12" cy="12" r="4" /><path d="M12 2v2m0 16v2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4M2 12h2m16 0h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></>,
    moon: <path d="M20 15.2A8.5 8.5 0 0 1 8.8 4 8.5 8.5 0 1 0 20 15.2Z" />,
  }
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name] || paths.chart}</svg>
}

function initialTheme(): Theme {
  try { return localStorage.getItem('commerce-insight-theme') === 'dark' ? 'dark' : 'light' }
  catch { return 'light' }
}

export function AppShell({ page, section = 'overview', onSectionChange, title, sourceTag, children }: {
  page: ShellPage
  section?: string
  onSectionChange?: (section: string) => void
  title: string
  sourceTag: string
  children: ReactNode
}) {
  const [theme, setTheme] = useState<Theme>(initialTheme)
  const isDashboard = page === 'dashboard' || page === 'imported'
  const imported = page === 'imported'

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    try { localStorage.setItem('commerce-insight-theme', theme) } catch { /* 本地存储不可用时仍可在当前页面切换 */ }
  }, [theme])

  const dashboardHref = (id: string) => isDashboard ? `#${id}` : `/#${id}`
  const sections = [
    { id: 'overview', name: '经营概览', icon: 'grid' },
    { id: 'trends', name: '每日趋势', icon: 'chart' },
    { id: 'products', name: '商品表现', icon: 'box' },
    { id: 'definitions', name: '数据与口径', icon: 'book' },
  ]

  return <div className="app-shell">
    <aside className="sidebar">
      <a className="brand" href="/"><span className="brand-symbol"><Icon name="chart" size={25} /></span><span>商析 <b>AI</b><small>电商经营复盘助手</small></span></a>
      <div className="workspace"><span className="store-mark">商</span><div>{imported ? '导入店铺 · 未核验' : '本地数据工作台'}<small>单店铺 · 人民币</small></div><span className="workspace-dot" /></div>
      <span className="nav-heading">工作空间</span>
      <nav>{sections.map(item => <a key={item.id} href={dashboardHref(item.id)} className={isDashboard && section === item.id ? 'active' : ''} onClick={() => isDashboard && onSectionChange?.(item.id)}><Icon name={item.icon} />{item.name}{isDashboard && section === item.id && <span className="nav-indicator" />}</a>)}</nav>
      <nav aria-label="公开数据"><a className={page === 'public-financials' ? 'active' : ''} href="/public-financials"><Icon name="book" />公开财报导入{page === 'public-financials' && <span className="nav-indicator" />}</a></nav>
      <nav aria-label="交易数据"><a className={page === 'imports' ? 'active' : ''} href="/imports"><Icon name="box" />交易表导入{page === 'imports' && <span className="nav-indicator" />}</a><a className={page === 'imported' ? 'active' : ''} href="/imported"><Icon name="chart" />导入数据看板{page === 'imported' && <span className="nav-indicator" />}</a></nav>
      <div className="ai-note"><span className="mini-label"><Icon name="spark" size={17} /> AI 经营解读</span><strong>后续接入</strong><p>本阶段由程序计算指标，<br />不生成 AI 分析结论。</p></div>
      <div className="sidebar-footer"><span className="avatar">作</span><div>个人求职作品<small>本地演示 · 交易导入已接入</small></div></div>
    </aside>

    <div className="main-shell">
      <header className="topbar"><div>工作空间 <span>/</span> <strong>{title}</strong></div><div className="topbar-right"><button className="theme-toggle" type="button" aria-label={theme === 'light' ? '切换为夜间模式' : '切换为白天模式'} aria-pressed={theme === 'dark'} onClick={() => setTheme(value => value === 'light' ? 'dark' : 'light')}><Icon name={theme === 'light' ? 'moon' : 'sun'} size={16} /><span>{theme === 'light' ? '夜间' : '白天'}</span></button><span className="local-dot" /> 本地运行 <span className="separator" /><span className="demo-tag">{sourceTag}</span></div></header>
      {children}
    </div>
  </div>
}
