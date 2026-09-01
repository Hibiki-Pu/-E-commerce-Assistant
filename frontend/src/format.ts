export const money = (cents: number | null, symbol = true): string => cents === null ? '不可计算' :
  (symbol ? '¥' : '') + (cents / 100).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

export const shiftDate = (day: string, offset: number): string => {
  const value = new Date(day + 'T00:00:00Z')
  value.setUTCDate(value.getUTCDate() + offset)
  return value.toISOString().slice(0, 10)
}

export async function getJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  const timeout = AbortSignal.timeout(15_000)
  const combined = signal ? AbortSignal.any([signal, timeout]) : timeout
  let response: Response
  try {
    response = await fetch(url, { signal: combined })
  } catch (error) {
    if (timeout.aborted) throw new Error('请求超时，请检查本地后端服务。')
    if (signal?.aborted) throw error
    throw new Error('无法连接本地后端，请确认 start.cmd 正在运行。')
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body.error || `请求失败（${response.status}），请检查后端是否已启动。`)
  }
  return response.json() as Promise<T>
}
