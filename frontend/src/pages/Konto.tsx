import { useState } from 'react'
import { api, ago, eur, useApi } from '../api'
import { useApp } from '../App'
import { Dialog, Loading, toast } from '../ui'

export default function Konto() {
  const { me, setMe, dash, go, showIntro } = useApp()
  const { data: sessions, reload } = useApi<any[]>('/auth/sessions', 0)
  const { data: prov } = useApi('/providers', 0)
  const [pw, setPw] = useState(false), [tfa, setTfa] = useState<any>(null), [off, setOff] = useState(false)
  const initials = me.display_name.split(/\s+/).map((s) => s[0]).join('').slice(0, 2).toUpperCase()
  const live = prov?.accounts.find((a: any) => a.kind === 'live')
  const logout = async () => { await api('/auth/logout', { body: {} }).catch(() => {}); setMe(null) }
  return (
    <>
      <div className="head"><h1>Konto</h1><button className="btn" onClick={showIntro}>Einführung ansehen</button><button className="btn" onClick={logout}>Abmelden</button></div>
      <div className="grid g2">
        <div className="card">
          <div className="row" style={{ marginBottom: 12 }}><div className="avatar" style={{ width: 48, height: 48, fontSize: 16 }}>{initials}</div>
            <div><b>{me.display_name}</b><br /><small>{me.email}</small></div></div>
          <div className="setting"><div className="t">Benutzername</div><span>{me.username}</span></div>
          <div className="setting"><div className="t">Rolle</div><span>{me.role === 'admin' ? 'Administrator' : 'Benutzer'}</span></div>
          <div className="setting"><div className="t">Sprache</div><span>Deutsch</span></div>
          <button className="btn" style={{ marginTop: 10 }} onClick={() => setPw(true)}>Passwort ändern</button>
        </div>
        <div className="card">
          <h2>Sicherheit</h2>
          <div className="setting"><div className="t">Zwei-Faktor-Anmeldung<small>Zusätzlicher Schutz mit Authenticator-App</small></div>
            {me.totp_enabled ? <button className="btn small" onClick={() => setOff(true)}>Deaktivieren</button>
              : <button className="btn small primary" onClick={async () => setTfa(await api('/auth/2fa/setup', { body: {} }))}>Einrichten</button>}</div>
          <h3 style={{ marginTop: 12 }}>Angemeldet auf</h3>
          {!sessions ? <Loading /> : <div className="list">{sessions.map((s) => <div key={s.id}><div className="sp">{s.device}{s.current && <small className="pos"> · dieses Gerät</small>}<br /><small>{s.ip} · zuletzt {ago(s.last_seen_at)}</small></div>
            {!s.current && <button className="btn small" onClick={async () => { await api('/auth/sessions/' + s.id, { method: 'DELETE' }); reload() }}>Abmelden</button>}</div>)}</div>}
        </div>
      </div>
      <div className="card">
        <h2>Handelskonto</h2>
        <div className="grid g3">
          <div><small>Kontostand ({dash?.mode === 'live' ? 'Live' : 'Paper'})</small><div className="kpi"><div className="v">{eur(dash?.equity)}</div></div></div>
          <div><small>Börse</small><div style={{ marginTop: 6 }}>{live ? <>{prov.providers.find((p: any) => p.id === live.broker)?.name} · <span className={live.connected ? 'pos' : 'neg'}>{live.connected ? 'Verbunden' : 'Nicht verbunden'}</span></> : 'Nur Paper'}</div></div>
          <div><small>API-Schlüssel</small><div className="mono" style={{ marginTop: 6 }}>{live?.key_hint || '–'}</div></div>
        </div>
        <button className="btn" style={{ marginTop: 12 }} onClick={() => go('einstellungen/boerse')}>Konto & Börse verwalten</button>
      </div>
      <div className="card">
        <h2>App installieren</h2>
        <div className="grid g3" style={{ fontSize: 13.5 }}>
          <div><b>iPhone</b><ol style={{ paddingLeft: 18, margin: '6px 0' }}><li>Diese Seite in <b>Safari</b> öffnen</li><li>Teilen-Symbol tippen</li><li>„Zum Home-Bildschirm“</li><li>App vom Home-Bildschirm öffnen und unter Einstellungen → Meldungen Push aktivieren</li></ol></div>
          <div><b>Windows</b><ol style={{ paddingLeft: 18, margin: '6px 0' }}><li>PowerShell öffnen</li><li>Befehl einfügen und Enter drücken:</li></ol>
            <div className="diff" style={{ wordBreak: 'break-all', fontSize: 12 }}>irm {location.origin}/windows-installieren.ps1 | iex</div>
            <small>Oder in Edge/Chrome: Menü → „Apps“ → „Diese Website als App installieren“.</small></div>
          <div><b>Mac</b><ol style={{ paddingLeft: 18, margin: '6px 0' }}><li>Safari: Ablage → „Zum Dock hinzufügen“</li><li>oder Chrome: Menü → „Streamen, speichern und teilen“ → „Seite als App installieren“</li></ol></div>
        </div>
        <small>Alle Geräte nutzen denselben Server – überall der gleiche Stand.</small>
      </div>
      <p className="muted" style={{ fontSize: 12.5 }}><a href="/legal/agb" target="_blank">AGB</a> · <a href="/legal/datenschutz" target="_blank">Datenschutz</a> · <a href="/legal/impressum" target="_blank">Impressum</a></p>
      {pw && <Password onClose={() => setPw(false)} />}
      {tfa && <TwoFa setup={tfa} onClose={() => setTfa(null)} onDone={(m: any) => { setMe(m); setTfa(null) }} />}
      {off && <TwoFaOff onClose={() => setOff(false)} onDone={(m: any) => { setMe(m); setOff(false) }} />}
    </>
  )
}

function Password({ onClose }: { onClose: () => void }) {
  const [o, setO] = useState(''), [n, setN] = useState(''), [n2, setN2] = useState(''), [err, setErr] = useState('')
  const go = async () => {
    if (n !== n2) return setErr('Passwörter stimmen nicht überein')
    try { await api('/auth/password', { body: { old: o, new: n } }); toast('Passwort geändert – andere Geräte wurden abgemeldet'); onClose() } catch (e: any) { setErr(e.message) }
  }
  return <Dialog title="Passwort ändern" onClose={onClose}>
    {err && <div className="err">{err}</div>}
    <label className="f"><span>Aktuelles Passwort</span><input type="password" autoComplete="current-password" value={o} onChange={(e) => setO(e.target.value)} /></label>
    <label className="f"><span>Neues Passwort</span><input type="password" autoComplete="new-password" value={n} onChange={(e) => setN(e.target.value)} /></label>
    <label className="f"><span>Wiederholen</span><input type="password" autoComplete="new-password" value={n2} onChange={(e) => setN2(e.target.value)} /></label>
    <button className="btn primary block" onClick={go}>Speichern</button>
  </Dialog>
}

function TwoFa({ setup, onClose, onDone }: any) {
  const [code, setCode] = useState(''), [err, setErr] = useState('')
  return <Dialog title="Zwei-Faktor-Anmeldung einrichten" onClose={onClose}>
    <ol style={{ paddingLeft: 18 }}><li>Authenticator-App öffnen (z. B. Google Authenticator, Microsoft Authenticator oder iPhone-Passwörter).</li>
      <li>QR-Code scannen – auf dem iPhone kannst du auch <a href={setup.uri}>hier tippen</a>.</li><li>Den angezeigten 6-stelligen Code eingeben.</li></ol>
    <div style={{ background: '#fff', borderRadius: 10, padding: 10, width: 200, margin: '10px auto' }} dangerouslySetInnerHTML={{ __html: setup.qr_svg }} />
    <p style={{ textAlign: 'center' }}><small>Manuell: <span className="mono">{setup.secret}</span></small></p>
    {err && <div className="err">{err}</div>}
    <label className="f"><span>Code</span><input inputMode="numeric" autoComplete="one-time-code" value={code} onChange={(e) => setCode(e.target.value)} /></label>
    <button className="btn primary block" onClick={async () => { try { onDone(await api('/auth/2fa/enable', { body: { code } })); toast('2FA aktiviert') } catch (e: any) { setErr(e.message) } }}>Aktivieren</button>
  </Dialog>
}

function TwoFaOff({ onClose, onDone }: any) {
  const [code, setCode] = useState(''), [pw, setPw] = useState(''), [err, setErr] = useState('')
  return <Dialog title="2FA deaktivieren" onClose={onClose}>
    {err && <div className="err">{err}</div>}
    <label className="f"><span>Passwort</span><input type="password" value={pw} onChange={(e) => setPw(e.target.value)} /></label>
    <label className="f"><span>Aktueller Code</span><input inputMode="numeric" value={code} onChange={(e) => setCode(e.target.value)} /></label>
    <button className="btn danger block" onClick={async () => { try { onDone(await api('/auth/2fa/disable', { body: { code, password: pw } })) } catch (e: any) { setErr(e.message) } }}>Deaktivieren</button>
  </Dialog>
}
