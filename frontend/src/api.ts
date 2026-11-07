import { useCallback, useEffect, useRef, useState } from 'react'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) { super(message); this.status = status }
}

type Listener = (status: number) => void
let authListener: Listener = () => {}
export const onAuthProblem = (fn: Listener) => { authListener = fn }

export async function api<T = any>(path: string, opts: { method?: string; body?: unknown } = {}): Promise<T> {
  const res = await fetch('/api' + path, {
    method: opts.method || (opts.body !== undefined ? 'POST' : 'GET'),
    headers: { 'x-requested-with': 'tradingbot', ...(opts.body !== undefined ? { 'content-type': 'application/json' } : {}) },
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    credentials: 'same-origin',
  })
  if (!res.ok) {
    let msg = res.statusText
    try { const j = await res.json(); msg = typeof j.detail === 'string' ? j.detail : (j.detail?.[0]?.msg || msg) } catch { /* leer */ }
    if (res.status === 401 || res.status === 451) authListener(res.status)
    throw new ApiError(res.status, msg)
  }
  return res.json()
}

// ---- Live-Aktualisierung: ein WebSocket für die ganze App, Seiten abonnieren Themen
type Sub = (topic: string) => void
const subs = new Set<Sub>()
let ws: WebSocket | null = null
let retry = 1000
export function connectLive() {
  if (ws && ws.readyState <= 1) return
  ws = new WebSocket((location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/api/ws')
  ws.onopen = () => { retry = 1000; subs.forEach((s) => s('verbunden')) }
  ws.onmessage = (e) => { try { const t = JSON.parse(e.data).topic; subs.forEach((s) => s(t)) } catch { /* leer */ } }
  ws.onclose = (e) => { ws = null; if (e.code !== 4401) setTimeout(connectLive, retry = Math.min(retry * 2, 30000)) }
}
export function disconnectLive() { if (ws) { ws.onclose = null; ws.close(); ws = null } }
document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') { connectLive(); subs.forEach((s) => s('sichtbar')) } })

/** Lädt Daten und lädt bei Live-Meldungen (gedrosselt) sowie periodisch neu. */
export function useApi<T = any>(path: string | null, intervalMs = 15000) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string>('')
  const timer = useRef<number | undefined>(undefined)
  const load = useCallback(async () => {
    if (!path) return
    try { setData(await api<T>(path)); setError('') } catch (e: any) { setError(e.message) }
  }, [path])
  useEffect(() => {
    load()
    const sub: Sub = () => { clearTimeout(timer.current); timer.current = window.setTimeout(load, 400) }
    subs.add(sub)
    const iv = intervalMs ? window.setInterval(() => document.visibilityState === 'visible' && load(), intervalMs) : undefined
    return () => { subs.delete(sub); clearInterval(iv); clearTimeout(timer.current) }
  }, [load, intervalMs])
  return { data, error, reload: load, setData }
}

// ---- Formatierung (deutsch)
const nf = (d: number) => new Intl.NumberFormat('de-DE', { minimumFractionDigits: d, maximumFractionDigits: d })
export const eur = (v: number | null | undefined, sign = false) =>
  v == null ? '–' : (sign && v > 0 ? '+' : '') + nf(2).format(v) + ' €'
export const pct = (v: number | null | undefined, sign = false, d = 1) =>
  v == null ? '–' : (sign && v > 0 ? '+' : '') + nf(d).format(v) + ' %'
export const num = (v: number | null | undefined, d = 2) => (v == null ? '–' : nf(d).format(v))
export const qty = (v: number | null | undefined) =>
  v == null ? '–' : new Intl.NumberFormat('de-DE', { maximumSignificantDigits: 6 }).format(v)
export const price = (v: number | null | undefined) =>
  v == null ? '–' : new Intl.NumberFormat('de-DE', { minimumFractionDigits: 2, maximumFractionDigits: v < 10 ? 4 : 2 }).format(v)
export const dt = (s: string | null | undefined, withYear = false) => {
  if (!s) return '–'
  const d = new Date(s)
  return d.toLocaleString('de-DE', { day: '2-digit', month: '2-digit', ...(withYear ? { year: '2-digit' } : {}), hour: '2-digit', minute: '2-digit' })
}
export const ago = (s: string | null | undefined) => {
  if (!s) return '–'
  const sec = (Date.now() - new Date(s).getTime()) / 1000
  if (sec < 60) return 'gerade eben'
  if (sec < 3600) return `vor ${Math.round(sec / 60)} Min.`
  if (sec < 86400) return `vor ${Math.round(sec / 3600)} Std.`
  return `vor ${Math.round(sec / 86400)} Tagen`
}
export const cls = (v: number | null | undefined) => (v == null || v === 0 ? '' : v > 0 ? 'pos' : 'neg')
