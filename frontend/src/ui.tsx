import { type ReactNode, useEffect, useState } from 'react'

const P: Record<string, string> = {
  dashboard: 'M3 13h8V3H3zm0 8h8v-6H3zm10 0h8V11h-8zm0-18v6h8V3z',
  strategien: 'M3 17l6-6 4 4 8-8M15 7h6v6',
  ertrag: 'M12 2v20M17 6H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6',
  risiko: 'M12 2l8 4v6c0 5-3.4 8.7-8 10-4.6-1.3-8-5-8-10V6z',
  verlauf: 'M12 8v5l3 2M3 12a9 9 0 109-9 9 9 0 00-7 3.4M3 4v4h4',
  backtest: 'M4 19V5M4 19h16M8 15l3-4 3 2 5-6',
  einstellungen: 'M12 15a3 3 0 100-6 3 3 0 000 6zM19.4 15a1.6 1.6 0 00.3 1.8l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.6 1.6 0 00-1.8-.3 1.6 1.6 0 00-1 1.5V21a2 2 0 11-4 0v-.1a1.6 1.6 0 00-1-1.5 1.6 1.6 0 00-1.8.3l-.1.1a2 2 0 11-2.8-2.8l.1-.1a1.6 1.6 0 00.3-1.8 1.6 1.6 0 00-1.5-1H3a2 2 0 110-4h.1a1.6 1.6 0 001.5-1 1.6 1.6 0 00-.3-1.8l-.1-.1a2 2 0 112.8-2.8l.1.1a1.6 1.6 0 001.8.3H9a1.6 1.6 0 001-1.5V3a2 2 0 114 0v.1a1.6 1.6 0 001 1.5 1.6 1.6 0 001.8-.3l.1-.1a2 2 0 112.8 2.8l-.1.1a1.6 1.6 0 00-.3 1.8V9a1.6 1.6 0 001.5 1H21a2 2 0 110 4h-.1a1.6 1.6 0 00-1.5 1z',
  benutzer: 'M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2M9 11a4 4 0 100-8 4 4 0 000 8zM23 21v-2a4 4 0 00-3-3.9M16 3.1a4 4 0 010 7.8',
  mehr: 'M4 6h16M4 12h16M4 18h16',
  hilfe: 'M12 22a10 10 0 100-20 10 10 0 000 20zM9.1 9a3 3 0 015.8 1c0 2-3 3-3 3M12 17h.01',
  konto: 'M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2M12 11a4 4 0 100-8 4 4 0 000 8z',
}
export function Icon({ name }: { name: string }) {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d={P[name] || P.mehr} /></svg>
}

export function LineChart({ points, height = 200, color = 'var(--green)', base }: { points: [number, number][]; height?: number; color?: string; base?: number }) {
  if (points.length < 2) return <div className="empty" style={{ height }}>Noch keine Daten – der Verlauf entsteht, sobald der Bot läuft.</div>
  const W = 800, H = height, pad = 6
  const xs = points.map((p) => p[0]), ys = points.map((p) => p[1])
  const x0 = Math.min(...xs), x1 = Math.max(...xs)
  let y0 = Math.min(...ys, base ?? Infinity), y1 = Math.max(...ys, base ?? -Infinity)
  if (y1 - y0 < 1e-9) { y0 -= 1; y1 += 1 }
  const sx = (x: number) => pad + ((x - x0) / (x1 - x0 || 1)) * (W - 2 * pad)
  const sy = (y: number) => H - pad - ((y - y0) / (y1 - y0)) * (H - 2 * pad)
  const d = points.map((p, i) => `${i ? 'L' : 'M'}${sx(p[0]).toFixed(1)},${sy(p[1]).toFixed(1)}`).join('')
  const area = `${d}L${sx(x1)},${H}L${sx(x0)},${H}Z`
  return (
    <svg className="chart" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ height }}>
      <defs><linearGradient id="lg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor={color} stopOpacity=".22" /><stop offset="1" stopColor={color} stopOpacity="0" /></linearGradient></defs>
      {base != null && <line x1="0" x2={W} y1={sy(base)} y2={sy(base)} stroke="var(--line)" strokeDasharray="4 4" vectorEffect="non-scaling-stroke" />}
      <path d={area} fill="url(#lg)" />
      <path d={d} fill="none" stroke={color} strokeWidth="2.2" vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
    </svg>
  )
}

export function Dialog({ title, children, onClose, wide }: { title: string; children: ReactNode; onClose: () => void; wide?: boolean }) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', k); return () => window.removeEventListener('keydown', k)
  }, [onClose])
  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="dialog" style={wide ? { maxWidth: 820 } : undefined}>
        <div className="row between" style={{ marginBottom: 12 }}><h2 style={{ margin: 0 }}>{title}</h2><button className="btn ghost small" onClick={onClose} aria-label="Schließen">✕</button></div>
        {children}
      </div>
    </div>
  )
}

let toastFn: (m: string) => void = () => {}
export const toast = (m: string) => toastFn(m)
export function Toaster() {
  const [m, setM] = useState('')
  useEffect(() => { let t: number; toastFn = (x) => { setM(x); clearTimeout(t); t = window.setTimeout(() => setM(''), 3500) } }, [])
  return m ? <div className="toast">{m}</div> : null
}

export function Switch({ checked, onChange, disabled }: { checked: boolean; onChange: (v: boolean) => void; disabled?: boolean }) {
  return <label className="switch"><input type="checkbox" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} /><span /></label>
}

export const STATE_COLOR: Record<string, string> = {
  AKTIV: 'green', BEREIT: 'blue', PAUSIERT: 'amber', SYNCHRONISIERUNG: 'blue', INITIALISIERUNG: 'grey', GESPERRT: 'red', NOT_AUS: 'red', FEHLER: 'red',
}
export function StatePill({ state, label }: { state: string; label: string }) {
  return <span className={'pill ' + (STATE_COLOR[state] || 'grey')}>{label}</span>
}

export function Loading() { return <div className="spinner" /> }

export function Bar({ value, max, warnAt = 0.7 }: { value: number; max: number; warnAt?: number }) {
  const r = max > 0 ? Math.min(1, Math.max(0, value / max)) : 0
  return <div className={'bar ' + (r >= 1 ? 'red' : r >= warnAt ? 'amber' : '')}><i style={{ width: `${r * 100}%` }} /></div>
}

export function Markdown({ text }: { text: string }) {
  // Sehr einfache Darstellung der Rechtstexte (Überschriften, fett)
  return <div className="legal">{text.split('\n').map((l, i) => {
    if (l.startsWith('# ')) return <h1 key={i}>{l.slice(2)}</h1>
    if (l.startsWith('## ')) return <h2 key={i}>{l.slice(3)}</h2>
    const parts = l.split('**')
    return <div key={i}>{parts.map((p, j) => (j % 2 ? <b key={j}>{p}</b> : p))}{l === '' ? '\u00a0' : ''}</div>
  })}</div>
}
