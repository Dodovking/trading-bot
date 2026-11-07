import { useState } from 'react'
import { api } from './api'
import { useApp } from './App'
import { Dialog, toast } from './ui'

export async function command(action: string, extra: Record<string, unknown> = {}) {
  try {
    const r = await api('/command', { body: { action, ...extra } })
    if (r.message && r.message !== 'OK') toast(r.message)
    return true
  } catch (e: any) { toast(e.message); return false }
}

/** Start / Pause / Stopp / Freigabe – je nach Zustand. */
export function BotControls({ big }: { big?: boolean }) {
  const { dash, reloadDash } = useApp()
  const [notaus, setNotaus] = useState(false), [freigabe, setFreigabe] = useState(false)
  if (!dash) return null
  const s = dash.state
  const run = async (a: string, x = {}) => { await command(a, x); reloadDash() }
  const cls = big ? 'btn block' : 'btn'
  const locked = ['GESPERRT', 'NOT_AUS', 'FEHLER'].includes(s)
  return (
    <>
      <div className={big ? 'grid g2' : 'row'} style={big ? { gap: 10 } : undefined}>
        {locked ? <button className={cls + ' primary'} onClick={() => dash.lock_kind === 'tagesverlust' ? setFreigabe(true) : run('freigeben')}>Freigeben</button>
          : s === 'AKTIV' ? <button className={cls} onClick={() => run('pause')}>Pause</button>
          : <button className={cls + ' primary'} onClick={() => run('start')} disabled={s === 'SYNCHRONISIERUNG'}>Start</button>}
        {(s === 'AKTIV' || s === 'PAUSIERT') ? <button className={cls + ' danger'} onClick={() => run('stop')}>Stopp</button>
          : <button className={cls + ' danger'} onClick={() => setNotaus(true)} disabled={s === 'NOT_AUS'}>Not-Aus</button>}
      </div>
      {notaus && <NotAus onClose={() => { setNotaus(false); reloadDash() }} />}
      {freigabe && <Dialog title="Tagesverlustsperre aufheben?" onClose={() => setFreigabe(false)}>
        <p>Das tägliche Verlustlimit wurde erreicht. Normalerweise bleibt der Bot bis morgen gesperrt. Willst du die Sperre wirklich heute aufheben?</p>
        <div className="row" style={{ justifyContent: 'flex-end' }}><button className="btn" onClick={() => setFreigabe(false)}>Abbrechen</button>
          <button className="btn danger" onClick={async () => { await run('freigeben', { bestaetigt: true }); setFreigabe(false) }}>Trotzdem freigeben</button></div>
      </Dialog>}
    </>
  )
}

export function NotAus({ onClose }: { onClose: () => void }) {
  return <Dialog title="Notbremse ziehen?" onClose={onClose}>
    <p>Der Bot wird sofort gestoppt, alle offenen Orders werden storniert und (je nach Einstellung) alle Trading-Positionen zum Marktpreis geschlossen.
      Sparplan-Bestände bleiben unberührt.</p>
    <p className="muted">Danach ist eine manuelle Freigabe mit Abgleich nötig.</p>
    <div className="row" style={{ justifyContent: 'flex-end' }}><button className="btn" onClick={onClose}>Abbrechen</button>
      <button className="btn danger" onClick={async () => { await command('notaus'); onClose() }}>Not-Aus auslösen</button></div>
  </Dialog>
}
