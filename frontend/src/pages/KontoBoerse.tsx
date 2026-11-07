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
  const [reset, setReset] = useState(false), [cap, setCap] = useState(10000), [goLive, setGoLive] = useState(false)
  if (!data) return <Loading />
  const paper = data.accounts.find((a: any) => a.kind === 'paper')
  const links: any[] = data.links || [], liveLinks = links.filter((lk) => lk.trades_live)
  const covers = (m: string) => liveLinks.some((lk) => lk.markets.includes(m))
  const p = data.providers.find((x: any) => x.id === sel)
  const list = data.providers.filter((x: any) => filter === 'alle' || x.markets.includes(filter))
  return <>
    <div className="grid g2">
      <div className="card"><div className="row between"><h2 style={{ margin: 0 }}>Paper-Konto</h2>{cfg.account === 'paper' && <span className="pill blue">aktiv</span>}</div>
        <p className="muted" style={{ fontSize: 13.5, marginTop: 8 }}>Spielgeld mit echten Kursen · Startkapital {eur(paper?.start_capital)}</p>
        <button className="btn small" onClick={() => setReset(true)}>Zurücksetzen</button></div>
      <div className="card"><div className="row between"><h2 style={{ margin: 0 }}>Echtgeld-Konto</h2>{cfg.account === 'live' && <span className="pill red">aktiv</span>}</div>
        {links.length > 0 ? <>
          <p className="muted" style={{ fontSize: 13, marginTop: 8 }}>Du kannst mehrere Anbieter gleichzeitig verbinden. Im Echtgeld-Modus läuft jeder Markt automatisch über den passenden Anbieter (z. B. Krypto über Kraken, Aktien über Alpaca).</p>
          <div className="list">{links.map((lk: any) => <div key={lk.broker}>
            <div className="sp"><b>{lk.name}</b> <small>{lk.markets.map((m: string) => MK[m]).join(', ')} · Schlüssel <span className="mono">{lk.key_hint}</span></small><br />
              <small className={lk.connected ? 'pos' : 'neg'}>{lk.connected ? 'Verbunden' : 'Nicht verbunden'}</small>{' '}
              <small>{lk.environment === 'paper' ? '· Spielgeld-Konto beim Anbieter (nur Kurse, kein Echtgeld)' : '· Echtgeld'}</small><br /><small className="muted">{lk.note}</small></div>
            <div className="row wrap" style={{ gap: 6 }}>
              <button className="btn small" onClick={async () => { try { const r = await api('/accounts/live/test', { body: { broker: lk.broker } }); toast(r.note) } catch (e: any) { toast(e.message) } reload() }}>Testen</button>
              <button className="btn small" onClick={() => setSel(lk.broker)}>Neu verbinden</button>
              <button className="btn small ghost neg" onClick={async () => { if (confirm(`Schlüssel für ${lk.name} löschen?`)) { try { await api('/accounts/live?broker=' + lk.broker, { method: 'DELETE' }) } catch (e: any) { toast(e.message) } reload(); reloadDash() } }}>Löschen</button>
            </div></div>)}</div>
          {liveLinks.length > 0 ? <div className="row wrap" style={{ marginTop: 10 }}>
            {cfg.account === 'paper' && <button className="btn small danger" onClick={() => setGoLive(true)}>Auf Echtgeld umstellen</button>}
            {cfg.account === 'live' && <button className="btn small" onClick={() => { const c = clone(cfg); c.account = 'paper'; save(c) }}>Zurück zu Paper</button>}
            {!covers('krypto') && <small className="muted">Für Krypto ist kein Echtgeld-Anbieter verbunden – Krypto-Märkte werden dann nicht gehandelt.</small>}
            {!covers('aktien') && <small className="muted">Für Aktien ist kein Echtgeld-Anbieter verbunden – Aktien werden dann nicht gehandelt.</small>}
          </div> : <p className="muted" style={{ fontSize: 13, marginTop: 10, marginBottom: 0 }}>Für Echtgeld brauchst du mindestens einen Anbieter mit Umgebung „Live“.</p>}
        </> : <p className="muted" style={{ fontSize: 13.5, marginTop: 8 }}>Noch kein Anbieter verbunden. Wähle unten deinen Anbieter und folge der Anleitung.</p>}
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
    {goLive && <Dialog title="Auf Echtgeld umstellen" onClose={() => setGoLive(false)}>
      <p>Ab jetzt kauft und verkauft der Bot mit <b>echtem Geld</b> über: {liveLinks.map((lk) => lk.name).join(' + ')}.</p>
      <ul style={{ paddingLeft: 18 }}>{liveLinks.map((lk) => <li key={lk.broker}>{lk.markets.map((m: string) => MK[m]).join(', ')} → {lk.name}</li>)}</ul>
      <p className="muted" style={{ fontSize: 13 }}>Gewinn/Verlust, Tagesstart und Sicherheitsgrenzen zählen ab jetzt getrennt für das Echtgeld-Konto – das Spielgeld wird nicht mitgerechnet. Für jeden Kauf zählt nur das Guthaben beim jeweiligen Anbieter. Verluste sind möglich.</p>
      <div className="row" style={{ justifyContent: 'flex-end' }}><button className="btn" onClick={() => setGoLive(false)}>Abbrechen</button>
        <button className="btn danger" onClick={() => { setGoLive(false); const c = clone(cfg); c.account = 'live'; save(c) }}>Ja, mit Echtgeld handeln</button></div>
    </Dialog>}
    {reset && <Dialog title="Paper-Konto zurücksetzen" onClose={() => setReset(false)}>
      <p>Alle Paper-Positionen und offenen Paper-Orders werden verworfen. Der Verlauf bleibt erhalten.</p>
      <label className="f"><span>Neues Startkapital (€)</span><input type="number" min={100} value={cap} onChange={(e) => setCap(Number(e.target.value))} /></label>
      <div className="row" style={{ justifyContent: 'flex-end' }}><button className="btn" onClick={() => setReset(false)}>Abbrechen</button>
        <button className="btn primary" onClick={async () => { try { await api('/accounts/paper/reset', { body: { capital: cap } }); toast('Zurückgesetzt'); setReset(false); reload(); reloadDash() } catch (e: any) { toast(e.message) } }}>Zurücksetzen</button></div>
    </Dialog>}
  </>
}

function Guide({ p, rules, allowed, onClose, onDone }: any) {
  const [key, setKey] = useState(''), [secret, setSecret] = useState(''), [ok, setOk] = useState(false), [env, setEnv] = useState('paper')
  const [res, setRes] = useState<any>(null), [busy, setBusy] = useState(false)
  const connect = async () => {
    setBusy(true); setRes(null)
    try { const r = await api('/accounts/live', { body: { broker: p.id, key, secret, umgebung: env } }); setRes(r); if (r.connected) { setKey(''); setSecret('') } }
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
      {p.status === 'verfuegbar' && p.felder.length > 0 && (allowed || p.id === 'alpaca' ? <div className="card" style={{ background: 'var(--bg)' }}>
        {p.felder.map((f: any) => f.optionen ? <label className="f" key={f.id}><span>{f.label}</span>
          <select value={env} onChange={(e) => setEnv(e.target.value)}>
            <option value="paper">Paper (Spielgeld-Konto bei Alpaca)</option>
            <option value="live" disabled={!allowed}>Live (Echtgeld)</option></select></label>
          : <label className="f" key={f.id}><span>{f.label}</span>
          <input type="password" autoComplete="off" spellCheck={false} value={f.id === 'key' ? key : secret} onChange={(e) => (f.id === 'key' ? setKey : setSecret)(e.target.value)} /></label>)}
        {p.id === 'alpaca' && <small className="muted">Die Schlüssel liefern dem Bot die Aktienkurse. Gehandelt wird weiter mit dem Paper-Konto hier in der App, solange du nicht selbst umstellst.</small>}
        <label className="check"><input type="checkbox" checked={ok} onChange={(e) => setOk(e.target.checked)} />Ich bestätige: Der Schlüssel hat <b>keine</b> Auszahlungs- oder Überweisungsrechte.</label>
        {res && <div className={res.connected ? 'ok' : 'err'}>{res.connected ? '✓ ' : ''}{res.note}</div>}
        <button className="btn primary block" disabled={!ok || busy || key.length < 10 || secret.length < 10} onClick={connect}>{busy ? 'Prüfe …' : 'Speichern und Verbindung testen'}</button>
        <small>Schlüssel werden verschlüsselt gespeichert und nie wieder im Klartext angezeigt.</small>
      </div> : <div className="note">Echtgeld-Handel ist für dein Konto noch nicht freigegeben.</div>)}
    </div>
  </Dialog>
}
