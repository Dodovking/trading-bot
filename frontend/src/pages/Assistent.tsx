import { Fragment, type ReactNode, useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { useApp } from '../App'
import { Loading, toast } from '../ui'

type Msg = { id: number; time: string; role: 'du' | 'bot'; text: string; state: string
  action: { title: string; changes: string[]; warnings: string[]; danger: boolean } | null }

const IDEEN = ['Wie läuft es?', 'Warum kauft der Bot nichts?', 'Wie viel Gewinn habe ich?', 'Welche Strategien habe ich?',
  'Stell Trendfolge auf Paper', 'Schalte Dogecoin aus', 'Pausiere den Bot', 'Was ist ein Stop-Loss?']
const STATE: Record<string, string> = { erledigt: 'Erledigt', abgebrochen: 'Abgebrochen', verworfen: 'Ersetzt durch neuen Auftrag',
  abgelaufen: 'Verfallen', fehler: 'Fehlgeschlagen' }

function Text({ t }: { t: string }) {
  // **fett** und Zeilenumbrüche; alles andere bleibt reiner Text
  const lines = t.split('\n')
  return <>{lines.map((l, i) => <Fragment key={i}>{l.split(/(\*\*[^*]+\*\*)/).map((p, j): ReactNode =>
    p.startsWith('**') && p.endsWith('**') ? <b key={j}>{p.slice(2, -2)}</b> : p)}{i < lines.length - 1 && <br />}</Fragment>)}</>
}

export default function Assistent() {
  const { reloadDash } = useApp()
  const [msgs, setMsgs] = useState<Msg[] | null>(null)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const end = useRef<HTMLDivElement>(null)
  useEffect(() => { api<Msg[]>('/assistent').then(setMsgs).catch((e) => { toast(e.message); setMsgs([]) }) }, [])
  useEffect(() => { end.current?.scrollIntoView({ block: 'end' }) }, [msgs])

  const merge = (r: { messages: Msg[]; changed: boolean }) => {
    setMsgs((m) => { const map = new Map((m || []).map((x) => [x.id, x])); r.messages.forEach((x) => map.set(x.id, x)); return [...map.values()].sort((a, b) => a.id - b.id) })
    if (r.changed) reloadDash()
  }
  const send = async (t: string) => {
    if (!t.trim() || busy) return
    setBusy(true); setText('')
    try {
      const r = await api('/assistent', { body: { text: t } })
      // ältere offene Vorschläge sind serverseitig ersetzt – neu laden, damit ihre Knöpfe verschwinden
      merge(r); if (r.messages[1]?.action) setMsgs(await api('/assistent'))
    } catch (e: any) { toast(e.message); setText(t) } finally { setBusy(false) }
  }
  const decide = async (m: Msg, d: 'bestaetigen' | 'abbrechen') => {
    setBusy(true)
    try { merge(await api(`/assistent/${m.id}/${d}`, { body: {} })) } catch (e: any) { toast(e.message); setMsgs(await api('/assistent')) } finally { setBusy(false) }
  }
  const clear = async () => { await api('/assistent', { method: 'DELETE' }); setMsgs([]) }

  if (!msgs) return <Loading />
  return <div className="chatpage">
    <div className="head"><h1>Assistent</h1>{msgs.length > 0 && <button className="btn small ghost" onClick={clear}>Verlauf leeren</button>}</div>
    <div className="chatlog">
      {msgs.length === 0 && <div className="card">
        <p>Frag mich alles zu deinem Bot oder sag mir, was ich einstellen soll. Bevor ich etwas ändere, zeige ich dir genau, was passiert, und du bestätigst.</p>
        <p className="muted" style={{ margin: 0 }}>Ich laufe komplett auf deinem eigenen Server – deine Nachrichten gehen an keine fremde Firma.</p>
      </div>}
      {msgs.map((m) => <div key={m.id} className={'bubble ' + (m.role === 'du' ? 'me' : 'bot')}>
        <Text t={m.text} />
        {m.action && <div className={'chataction' + (m.action.danger ? ' danger' : '')}>
          <b>{m.action.title}</b>
          <ul>{m.action.changes.map((c, i) => <li key={i}>{c}</li>)}</ul>
          {m.action.warnings.map((w, i) => <div key={i} className="warn">⚠ {w}</div>)}
          {m.state === 'offen'
            ? <div className="row" style={{ gap: 8, marginTop: 8 }}>
                <button className={'btn small ' + (m.action.danger ? 'danger' : 'primary')} disabled={busy} onClick={() => decide(m, 'bestaetigen')}>Ja, machen</button>
                <button className="btn small" disabled={busy} onClick={() => decide(m, 'abbrechen')}>Nein</button>
              </div>
            : <div className={'muted' + (m.state === 'erledigt' ? ' pos' : '')} style={{ marginTop: 6 }}>{STATE[m.state] || m.state}</div>}
        </div>}
      </div>)}
      {busy && <div className="bubble bot muted">…</div>}
      <div ref={end} className="chatend" />
    </div>
    <div className="chatbar">
    <div className="chips">{IDEEN.map((i) => <button key={i} className="btn small ghost" disabled={busy} onClick={() => send(i)}>{i}</button>)}</div>
    <form className="chatinput" onSubmit={(e) => { e.preventDefault(); send(text) }}>
      <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Frag mich etwas oder gib mir einen Auftrag …" maxLength={1000} enterKeyHint="send" />
      <button className="btn primary" disabled={busy || !text.trim()}>Senden</button>
    </form>
    </div>
  </div>
}
