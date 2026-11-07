import { type FormEvent, type ReactNode, useEffect, useState } from 'react'
import { api } from '../api'
import type { Me } from '../App'
import { Markdown } from '../ui'

function AuthFrame({ children }: { children: ReactNode }) {
  return (
    <div className="auth">
      <div className="hero">
        <div className="brand" style={{ padding: 0 }}><img src="/icon.svg" alt="" style={{ width: 30, height: 30, borderRadius: 8 }} />Trading-Bot</div>
        <h1>Handeln nach Regeln statt nach Bauchgefühl. Alles einstellbar, auf PC und iPhone.</h1>
        <p className="muted">Jede Person hat ein eigenes Konto mit eigenen Einstellungen.</p>
      </div>
      <div className="form"><div>{children}
        <p className="muted" style={{ fontSize: 12.5, marginTop: 24, textAlign: 'center' }}>
          <a href="/legal/impressum" target="_blank">Impressum</a> · <a href="/legal/datenschutz" target="_blank">Datenschutz</a> · <a href="/legal/agb" target="_blank">AGB</a>
        </p>
      </div></div>
    </div>
  )
}

export function Login({ onDone }: { onDone: (m: Me) => void }) {
  const [u, setU] = useState(''), [p, setP] = useState(''), [code, setCode] = useState('')
  const [needCode, setNeedCode] = useState(false), [err, setErr] = useState(''), [busy, setBusy] = useState(false)
  const [forgot, setForgot] = useState(false)
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setBusy(true); setErr('')
    try {
      const r = await api('/auth/login', { body: { username: u, password: p, code: code || null } })
      if (r.needs_code) setNeedCode(true); else onDone(r)
    } catch (e: any) { setErr(e.message) } finally { setBusy(false) }
  }
  return (
    <AuthFrame>
      <h1 style={{ marginBottom: 6 }}>Anmelden</h1>
      <p className="muted" style={{ marginBottom: 20 }}>Melde dich mit deinem Konto an.</p>
      {err && <div className="err">{err}</div>}
      <form onSubmit={submit}>
        <label className="f"><span>Benutzername</span><input autoComplete="username" autoCapitalize="none" value={u} onChange={(e) => setU(e.target.value)} required /></label>
        <label className="f"><span>Passwort</span><input type="password" autoComplete="current-password" value={p} onChange={(e) => setP(e.target.value)} required /></label>
        <label className="f"><span>Zwei-Faktor-Code {needCode ? '' : '(optional)'}</span>
          <input inputMode="numeric" autoComplete="one-time-code" placeholder="123 456" value={code} onChange={(e) => setCode(e.target.value)} autoFocus={needCode} /></label>
        {needCode && <div className="info">Bitte den 6-stelligen Code aus deiner Authenticator-App eingeben.</div>}
        <button className="btn primary block" disabled={busy}>{busy ? 'Anmelden …' : 'Anmelden'}</button>
      </form>
      <p style={{ textAlign: 'center', marginTop: 14 }}><a href="#" onClick={(e) => { e.preventDefault(); setForgot(!forgot) }}>Passwort vergessen?</a></p>
      {forgot && <div className="info">Aus Sicherheitsgründen setzt der Administrator das Passwort zurück: Er erstellt dir unter „Benutzer“ einen neuen Einladungslink.</div>}
    </AuthFrame>
  )
}

export function Setup({ onDone, needCode }: { onDone: (m: Me) => void; needCode: boolean }) {
  const [f, setF] = useState({ username: '', display_name: '', email: '', password: '', code: '' }), [p2, setP2] = useState('')
  const [err, setErr] = useState('')
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setErr('')
    if (f.password !== p2) return setErr('Passwörter stimmen nicht überein')
    try { onDone(await api('/auth/setup', { body: f })) } catch (e: any) { setErr(e.message) }
  }
  const set = (k: string) => (e: any) => setF({ ...f, [k]: e.target.value })
  return (
    <AuthFrame>
      <h1 style={{ marginBottom: 6 }}>Einrichtung</h1>
      <p className="muted" style={{ marginBottom: 20 }}>Lege das erste Konto an. Es wird Administrator und kann weitere Personen einladen.</p>
      {err && <div className="err">{err}</div>}
      <form onSubmit={submit}>
        <label className="f"><span>Name</span><input value={f.display_name} onChange={set('display_name')} required /></label>
        <label className="f"><span>Benutzername</span><input autoCapitalize="none" autoComplete="username" value={f.username} onChange={set('username')} required /></label>
        <label className="f"><span>E-Mail</span><input type="email" value={f.email} onChange={set('email')} required /></label>
        <label className="f"><span>Passwort (mind. 10 Zeichen, Groß-/Kleinbuchstaben, Ziffer)</span><input type="password" autoComplete="new-password" value={f.password} onChange={set('password')} required /></label>
        <label className="f"><span>Passwort wiederholen</span><input type="password" autoComplete="new-password" value={p2} onChange={(e) => setP2(e.target.value)} required /></label>
        {needCode && <label className="f"><span>Einrichtungscode (vom Server-Betreiber)</span><input autoCapitalize="none" autoComplete="off" value={f.code} onChange={set('code')} required /></label>}
        <button className="btn primary block">Konto anlegen</button>
      </form>
    </AuthFrame>
  )
}

export function Invite({ token, onDone }: { token: string; onDone: (m: Me) => void }) {
  const [info, setInfo] = useState<any>(null), [err, setErr] = useState('')
  const [u, setU] = useState(''), [p, setP] = useState(''), [p2, setP2] = useState('')
  useEffect(() => { api('/auth/invite/' + token).then(setInfo).catch((e) => setErr(e.message)) }, [token])
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setErr('')
    if (p !== p2) return setErr('Passwörter stimmen nicht überein')
    try { onDone(await api('/auth/invite', { body: { token, username: u, password: p } })) } catch (e: any) { setErr(e.message) }
  }
  return (
    <AuthFrame>
      <h1 style={{ marginBottom: 6 }}>Einladung annehmen</h1>
      {info && <p className="muted" style={{ marginBottom: 20 }}>Hallo {info.display_name}, lege deinen Benutzernamen und dein Passwort fest.</p>}
      {err && <div className="err">{err}</div>}
      {info && <form onSubmit={submit}>
        <label className="f"><span>Benutzername</span><input autoCapitalize="none" autoComplete="username" value={u} onChange={(e) => setU(e.target.value)} required /></label>
        <label className="f"><span>Passwort (mind. 10 Zeichen, Groß-/Kleinbuchstaben, Ziffer)</span><input type="password" autoComplete="new-password" value={p} onChange={(e) => setP(e.target.value)} required /></label>
        <label className="f"><span>Passwort wiederholen</span><input type="password" autoComplete="new-password" value={p2} onChange={(e) => setP2(e.target.value)} required /></label>
        <button className="btn primary block">Konto aktivieren</button>
      </form>}
    </AuthFrame>
  )
}

export function Terms({ me, onDone }: { me: Me; onDone: (m: Me) => void }) {
  const [t, setT] = useState<any>(null), [tab, setTab] = useState<'agb' | 'datenschutz'>('agb')
  const [c, setC] = useState({ agb: false, datenschutz: false, risiko: false }), [err, setErr] = useState('')
  useEffect(() => { api('/auth/terms').then(setT) }, [])
  const accept = async () => {
    setErr('')
    try { onDone(await api('/auth/terms/accept', { body: { version: t.version, ...c } })) } catch (e: any) { setErr(e.message) }
  }
  const logout = async () => { await api('/auth/logout', { body: {} }).catch(() => {}); location.reload() }
  return (
    <div className="main" style={{ maxWidth: 820, margin: '0 auto' }}>
      <div className="head"><h1>Nutzungsbedingungen</h1><button className="btn ghost small" onClick={logout}>Abmelden</button></div>
      <p className="muted">Hallo {me.display_name}, bevor du den Trading-Bot nutzen kannst, lies und bestätige bitte die AGB (Version {t?.version}).
        {me.terms_version && ' Wenn sich die AGB ändern, wirst du erneut gefragt.'}</p>
      <div className="tabs"><button className={tab === 'agb' ? 'on' : ''} onClick={() => setTab('agb')}>AGB</button>
        <button className={tab === 'datenschutz' ? 'on' : ''} onClick={() => setTab('datenschutz')}>Datenschutz</button></div>
      {t ? <Markdown text={t[tab]} /> : <div className="spinner" />}
      <div className="card" style={{ marginTop: 16 }}>
        <label className="check"><input type="checkbox" checked={c.agb} onChange={(e) => setC({ ...c, agb: e.target.checked })} />Ich habe die AGB gelesen und stimme ihnen zu.</label>
        <label className="check"><input type="checkbox" checked={c.datenschutz} onChange={(e) => setC({ ...c, datenschutz: e.target.checked })} />Ich habe die Datenschutzerklärung zur Kenntnis genommen.</label>
        <label className="check"><input type="checkbox" checked={c.risiko} onChange={(e) => setC({ ...c, risiko: e.target.checked })} />Mir ist bewusst, dass Trading zum Totalverlust führen kann, es keine Gewinnzusage gibt und ich alle Entscheidungen selbst verantworte.</label>
        {err && <div className="err">{err}</div>}
        <button className="btn primary block" style={{ marginTop: 8 }} disabled={!t || !(c.agb && c.datenschutz && c.risiko)} onClick={accept}>Zustimmen und fortfahren</button>
      </div>
    </div>
  )
}
