import { useEffect, useState } from 'react'
import { api, ago, dt, useApi } from '../api'
import { useApp } from '../App'
import { Dialog, Loading, Switch, toast } from '../ui'

export default function Benutzer() {
  const { me } = useApp()
  const { data: users, reload } = useApi<any[]>('/admin/users', 0)
  const { data: st, reload: reloadSt } = useApi('/admin/settings', 0)
  const [inv, setInv] = useState(false), [link, setLink] = useState(''), [a, setA] = useState<any>(null), [fl, setFl] = useState(false)
  useEffect(() => { if (st) setA(st.anbieter) }, [st])
  if (!users || !st || !a) return <Loading />
  const patch = async (id: number, body: any) => { try { await api('/admin/users/' + id, { method: 'PATCH', body }); reload() } catch (e: any) { toast(e.message) } }
  return (
    <>
      <div className="head"><h1>Benutzer</h1><button className="btn primary" onClick={() => setInv(true)}>Person einladen</button></div>
      <div className="card scroll"><table className="tbl"><thead><tr><th>Name</th><th>Benutzername</th><th>Rolle</th><th>Status</th><th>2FA</th><th>AGB</th><th>Bot</th><th>Letzte Anmeldung</th><th /></tr></thead>
        <tbody>{users.map((u) => <tr key={u.id}><td><b>{u.display_name}</b><br /><small>{u.email}</small></td><td>{u.username || '–'}</td><td>{u.role === 'admin' ? 'Admin' : 'Benutzer'}</td>
          <td><span className={'pill nodot ' + (u.status === 'aktiv' ? 'green' : u.status === 'gesperrt' ? 'red' : 'amber')}>{u.status}</span></td><td>{u.totp ? 'ja' : 'nein'}</td>
          <td>{u.terms ? <small>v{u.terms.version} · {dt(u.terms.time)}</small> : <small className="warn">offen</small>}</td><td><small>{u.bot_state || '–'}</small></td><td><small>{ago(u.last_login_at)}</small></td>
          <td>{u.id !== me.id && <div className="row">{u.status === 'eingeladen' ? null : <button className="btn small" onClick={() => patch(u.id, { status: u.status === 'gesperrt' ? 'aktiv' : 'gesperrt' })}>{u.status === 'gesperrt' ? 'Entsperren' : 'Sperren'}</button>}
            <button className="btn small" onClick={() => patch(u.id, { role: u.role === 'admin' ? 'benutzer' : 'admin' })}>{u.role === 'admin' ? 'Zu Benutzer' : 'Zu Admin'}</button></div>}</td></tr>)}</tbody></table></div>
      <div className="card">
        <h2>Echtgeld für andere Nutzer</h2>
        <div className="setting"><div className="t">Andere Nutzer dürfen Echtgeld-Konten verbinden<small>Standardmäßig aus. Erst nach rechtlicher Prüfung einschalten (mögliche Erlaubnispflicht nach KWG/WpIG/MiCA).</small></div>
          <Switch checked={st.fremd_live} onChange={async (v) => { if (v) return setFl(true); await api('/admin/settings', { body: { fremd_live: false } }); reloadSt() }} /></div>
      </div>
      <div className="card">
        <h2>Anbieterangaben (Impressum, AGB, Datenschutz)</h2>
        <div className="note">AGB und Datenschutzerklärung sind Entwürfe – bitte vor der Nutzung durch andere anwaltlich prüfen lassen.</div>
        {st.felder.map((k: string) => <label className="f" key={k}><span>{({ name: 'Name', anschrift: 'Anschrift', email: 'E-Mail', telefon: 'Telefon (optional)' } as any)[k]}</span>
          <input value={a[k] && !a[k].startsWith('[') ? a[k] : ''} placeholder={a[k]?.startsWith('[') ? a[k] : ''} onChange={(e) => setA({ ...a, [k]: e.target.value })} /></label>)}
        <div className="row"><button className="btn primary" onClick={async () => { await api('/admin/settings', { body: { anbieter: a } }); toast('Gespeichert'); reloadSt() }}>Speichern</button>
          <a className="btn" href="/legal/impressum" target="_blank">Impressum ansehen</a></div>
      </div>
      {inv && <Invite onClose={() => { setInv(false); reload() }} onLink={(l) => { setLink(l); reload() }} />}
      {link && <Dialog title="Einladungslink" onClose={() => setLink('')}>
        <p>Schicke diesen Link an die Person (7 Tage gültig). Er wird nur jetzt angezeigt.</p>
        <div className="diff" style={{ wordBreak: 'break-all' }}>{link}</div>
        <button className="btn primary block" style={{ marginTop: 12 }} onClick={() => { navigator.clipboard?.writeText(link); toast('Kopiert') }}>Kopieren</button>
      </Dialog>}
      {fl && <Dialog title="Echtgeld für andere freigeben?" onClose={() => setFl(false)}>
        <p>Wenn andere Personen über deinen Server mit echtem Geld handeln, kann das eine erlaubnispflichtige Finanzdienstleistung sein. Bitte nur einschalten, wenn das rechtlich geprüft ist.</p>
        <div className="row" style={{ justifyContent: 'flex-end' }}><button className="btn" onClick={() => setFl(false)}>Abbrechen</button>
          <button className="btn danger" onClick={async () => { await api('/admin/settings', { body: { fremd_live: true, fremd_live_bestaetigt: true } }); setFl(false); reloadSt() }}>Geprüft – freigeben</button></div>
      </Dialog>}
    </>
  )
}

function Invite({ onClose, onLink }: { onClose: () => void; onLink: (l: string) => void }) {
  const [n, setN] = useState(''), [e, setE] = useState(''), [err, setErr] = useState('')
  return <Dialog title="Person einladen" onClose={onClose}>
    {err && <div className="err">{err}</div>}
    <label className="f"><span>Name</span><input value={n} onChange={(x) => setN(x.target.value)} /></label>
    <label className="f"><span>E-Mail</span><input type="email" value={e} onChange={(x) => setE(x.target.value)} /></label>
    <p className="muted" style={{ fontSize: 13.5 }}>Die Person legt Benutzername und Passwort selbst fest und muss vor der Nutzung die AGB bestätigen. Sie startet im Paper-Modus.</p>
    <button className="btn primary block" onClick={async () => { try { const r = await api('/admin/invite', { body: { display_name: n, email: e } }); onClose(); onLink(r.link) } catch (x: any) { setErr(x.message) } }}>Einladungslink erstellen</button>
  </Dialog>
}
