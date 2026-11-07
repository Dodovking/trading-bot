import { useState } from 'react'
import { api, eur, useApi } from '../api'
import { useApp } from '../App'
import { clone } from '../config'
import { Dialog, Loading, toast } from '../ui'

const MK: Record<string, string> = { krypto: 'Krypto', aktien: 'Aktien/ETFs' }

export function KontoBoerse({ cfg, save }: { cfg: any; save: (c: any) => void }) {
  const { data, reload } = useApi('/providers', 0)
  const { reloadDash } = useApp()
  const [sel, setSel] = useState<string | null>(null), [filter, setFilter] = useState('alle')
  const [reset, setReset] = useState(false), [cap, setCap] = useState(10000)
  if (!data) return <Loading />
  const live = data.accounts.find((a: any) => a.kind === 'live'), paper = data.accounts.find((a: any) => a.kind === 'paper')
  const p = data.providers.find((x: any) => x.id === sel)
  const list = data.providers.filter((x: any) => filter === 'alle' || x.markets.includes(filter))
  return <>
    <div className="grid g2">
      <div className="card"><div className="row between"><h2 style={{ margin: 0 }}>Paper-Konto</h2>{cfg.account === 'paper' && <span className="pill blue">aktiv</span>}</div>
        <p className="muted" style={{ fontSize: 13.5, marginTop: 8 }}>Spielgeld mit echten Kursen · Startkapital {eur(paper?.start_capital)}</p>
        <button className="btn small" onClick={() => setReset(true)}>Zurücksetzen</button></div>
      <div className="card"><div className="row between"><h2 style={{ margin: 0 }}>Echtgeld-Konto</h2>{cfg.account === 'live' && <span className="pill red">aktiv</span>}</div>
        {live?.key_hint ? <>
          <p style={{ fontSize: 13.5, marginTop: 8 }}>{data.providers.find((x: any) => x.id === live.broker)?.name} · Schlüssel <span className="mono">{live.key_hint}</span> ·{' '}
            <span className={live.connected ? 'pos' : 'neg'}>{live.connected ? 'Verbunden' : 'Nicht verbunden'}</span><br /><small>{live.note}</small></p>
          <div className="row wrap">
            <button className="btn small" onClick={async () => { const r = await api('/accounts/live/test', { body: {} }); toast(r.note); reload() }}>Verbindung testen</button>
            <button className="btn small" onClick={() => setSel(live.broker)}>Neu verbinden</button>
            {cfg.account === 'paper' && live.connected && <button className="btn small danger" onClick={() => { const c = clone(cfg); c.account = 'live'; save(c) }}>Auf Echtgeld umstellen</button>}
            {cfg.account === 'live' && <button className="btn small" onClick={() => { const c = clone(cfg); c.account = 'paper'; save(c) }}>Zurück zu Paper</button>}
            {cfg.account === 'paper' && <button className="btn small ghost neg" onClick={async () => { if (confirm('Schlüssel löschen?')) { await api('/accounts/live', { method: 'DELETE' }); reload() } }}>Schlüssel löschen</button>}
          </div></> : <p className="muted" style={{ fontSize: 13.5, marginTop: 8 }}>Noch kein Anbieter verbunden. Wähle unten deinen Anbieter und folge der Anleitung.</p>}
        {!data.live_allowed && <div className="note" style={{ marginTop: 10, marginBottom: 0 }}>Echtgeld-Handel ist für dein Konto noch nicht freigegeben (Administrator).</div>}
      </div>
    </div>
    <div className="card">
      <div className="row between wrap"><h2 style={{ margin: 0 }}>Anbieter</h2>
        <div className="seg">{[['alle', 'Alle'], ['krypto', 'Krypto'], ['aktien', 'Aktien']].map(([k, l]) => <button key={k} className={filter === k ? 'on' : ''} onClick={() => setFilter(k)}>{l}</button>)}</div></div>
      <div className="list wrap-m" style={{ marginTop: 8 }}>{list.map((x: any) => <div key={x.id}>
        <div className="sp"><b>{x.name}</b> <small>{x.markets.map((m: string) => MK[m]).join(', ')}{x.region ? ' · ' + x.region : ''}</small><br /><small>{x.beschreibung}</small></div>
        <span className={'pill nodot ' + (x.status === 'verfuegbar' ? 'green' : 'grey')}>{x.status === 'verfuegbar' ? 'verfügbar' : 'in Vorbereitung'}</span>
        <button className="btn small" onClick={() => setSel(x.id)}>Anleitung</button></div>)}</div>
    </div>
    {p && <Guide p={p} rules={data.rules} allowed={data.live_allowed} onClose={() => setSel(null)} onDone={() => { setSel(null); reload(); reloadDash() }} />}
    {reset && <Dialog title="Paper-Konto zurücksetzen" onClose={() => setReset(false)}>
      <p>Alle Paper-Positionen und offenen Paper-Orders werden verworfen. Der Verlauf bleibt erhalten.</p>
      <label className="f"><span>Neues Startkapital (€)</span><input type="number" min={100} value={cap} onChange={(e) => setCap(Number(e.target.value))} /></label>
      <div className="row" style={{ justifyContent: 'flex-end' }}><button className="btn" onClick={() => setReset(false)}>Abbrechen</button>
        <button className="btn primary" onClick={async () => { try { await api('/accounts/paper/reset', { body: { capital: cap } }); toast('Zurückgesetzt'); setReset(false); reload(); reloadDash() } catch (e: any) { toast(e.message) } }}>Zurücksetzen</button></div>
    </Dialog>}
  </>
}

function Guide({ p, rules, allowed, onClose, onDone }: any) {
  const [key, setKey] = useState(''), [secret, setSecret] = useState(''), [ok, setOk] = useState(false)
  const [res, setRes] = useState<any>(null), [busy, setBusy] = useState(false)
  const connect = async () => {
    setBusy(true); setRes(null)
    try { const r = await api('/accounts/live', { body: { broker: p.id, key, secret } }); setRes(r); if (r.connected) { setKey(''); setSecret('') } }
    catch (e: any) { setRes({ connected: false, note: e.message }) } finally { setBusy(false) }
  }
  return <Dialog title={`${p.name} verbinden`} onClose={res?.connected ? onDone : onClose} wide>
    <div className="guide">
      <p className="muted">{p.beschreibung}</p>
      {p.status !== 'verfuegbar' && p.id !== 'paper' && <div className="info">Die direkte Anbindung ist in Vorbereitung. Du kannst die Schlüssel schon so vorbereiten – eintragen geht, sobald die Anbindung freigeschaltet ist.</div>}
      <h3>So geht's</h3>
      <ol>{p.schritte.map((s: string, i: number) => <li key={i}>{s}</li>)}</ol>
      {p.rechte.length > 0 && <p><b>Benötigte Rechte:</b> {p.rechte.join(' · ')}</p>}
      {p.id !== 'paper' && <div className="note"><b>Sicherheitsregeln</b><ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>{rules.map((r: string) => <li key={r}>{r}</li>)}</ul></div>}
      {p.links.map((l: any) => <p key={l.url}><a href={l.url} target="_blank" rel="noreferrer">{l.label} ↗</a></p>)}
      {p.status === 'verfuegbar' && p.felder.length > 0 && (allowed ? <div className="card" style={{ background: 'var(--bg)' }}>
        {p.felder.map((f: any) => <label className="f" key={f.id}><span>{f.label}</span>
          <input type="password" autoComplete="off" spellCheck={false} value={f.id === 'key' ? key : secret} onChange={(e) => (f.id === 'key' ? setKey : setSecret)(e.target.value)} /></label>)}
        <label className="check"><input type="checkbox" checked={ok} onChange={(e) => setOk(e.target.checked)} />Ich bestätige: Der Schlüssel hat <b>keine</b> Auszahlungs- oder Überweisungsrechte.</label>
        {res && <div className={res.connected ? 'ok' : 'err'}>{res.connected ? '✓ ' : ''}{res.note}</div>}
        <button className="btn primary block" disabled={!ok || busy || key.length < 10 || secret.length < 10} onClick={connect}>{busy ? 'Prüfe …' : 'Speichern und Verbindung testen'}</button>
        <small>Schlüssel werden verschlüsselt gespeichert und nie wieder im Klartext angezeigt.</small>
      </div> : <div className="note">Echtgeld-Handel ist für dein Konto noch nicht freigegeben.</div>)}
    </div>
  </Dialog>
}
