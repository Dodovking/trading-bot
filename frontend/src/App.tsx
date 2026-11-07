import { createContext, useContext, useEffect, useState } from 'react'
import { api, connectLive, disconnectLive, eur, onAuthProblem, useApi } from './api'
import { Icon, Loading, Toaster } from './ui'
import { Login, Setup, Terms, Invite } from './pages/Auth'
import Dashboard from './pages/Dashboard'
import Strategien from './pages/Strategien'
import Ertrag from './pages/Ertrag'
import Risiko from './pages/Risiko'
import Verlauf from './pages/Verlauf'
import Backtest from './pages/Backtest'
import Einstellungen from './pages/Einstellungen'
import Konto from './pages/Konto'
import Benutzer from './pages/Benutzer'
import Mehr from './pages/Mehr'

export type Me = { id: number; username: string; display_name: string; email: string; role: string; totp_enabled: boolean; terms_accepted: boolean; terms_version: string }
type Ctx = { me: Me; setMe: (m: Me | null) => void; dash: any; reloadDash: () => void; go: (p: string) => void }
const AppCtx = createContext<Ctx>(null as any)
export const useApp = () => useContext(AppCtx)

function useRoute() {
  const get = () => location.hash.replace(/^#\/?/, '') || 'dashboard'
  const [r, setR] = useState(get())
  useEffect(() => { const h = () => { setR(get()); window.scrollTo(0, 0) }; window.addEventListener('hashchange', h); return () => window.removeEventListener('hashchange', h) }, [])
  return r
}
export const go = (p: string) => { location.hash = '#/' + p }

const NAV = [
  ['dashboard', 'Dashboard'], ['strategien', 'Strategien'], ['ertrag', 'Ertragsmodule'], ['risiko', 'Risiko'], ['verlauf', 'Verlauf'],
  ['backtest', 'Backtest'], ['einstellungen', 'Einstellungen'], ['konto', 'Konto'],
]
const TABS = [['dashboard', 'Dashboard'], ['strategien', 'Strategien'], ['verlauf', 'Verlauf'], ['einstellungen', 'Einstellungen'], ['mehr', 'Mehr']]

export default function App() {
  const route = useRoute()
  const [me, setMe] = useState<Me | null | undefined>(undefined)
  const [needsSetup, setNeedsSetup] = useState('')

  const refresh = async () => {
    try { setMe(await api<Me>('/auth/me')) } catch {
      setMe(null)
      try { const st = await api('/auth/status'); setNeedsSetup(st.needs_setup ? (st.setup_code_required ? 'code' : 'yes') : '') } catch { /* leer */ }
    }
  }
  useEffect(() => { refresh(); onAuthProblem((s) => { if (s === 401) setMe(null); else refresh() }) }, [])
  useEffect(() => { if (me?.terms_accepted) connectLive(); else disconnectLive() }, [me?.terms_accepted])
  useEffect(() => { if ('serviceWorker' in navigator && location.protocol === 'https:') navigator.serviceWorker.register('/sw.js').catch(() => {}) }, [])

  if (me === undefined) return <Loading />
  if (route.startsWith('einladung/') && !me) return <><Invite token={route.split('/')[1]} onDone={(m) => { setMe(m); go('dashboard') }} /><Toaster /></>
  if (!me) return <>{needsSetup ? <Setup onDone={setMe} needCode={needsSetup === 'code'} /> : <Login onDone={setMe} />}<Toaster /></>
  if (!me.terms_accepted) return <><Terms me={me} onDone={setMe} /><Toaster /></>
  return <Shell me={me} setMe={setMe} route={route} />
}

function Shell({ me, setMe, route }: { me: Me; setMe: (m: Me | null) => void; route: string }) {
  const { data: dash, reload } = useApi('/dashboard', 10000)
  const page = route.split('/')[0]
  const initials = me.display_name.split(/\s+/).map((s) => s[0]).join('').slice(0, 2).toUpperCase()
  const nav = me.role === 'admin' ? [...NAV, ['benutzer', 'Benutzer']] : NAV
  const P: Record<string, any> = { dashboard: Dashboard, strategien: Strategien, ertrag: Ertrag, risiko: Risiko, verlauf: Verlauf, backtest: Backtest,
    einstellungen: Einstellungen, konto: Konto, benutzer: Benutzer, mehr: Mehr }
  const Page = P[page] || Dashboard
  const live = dash?.mode === 'live'
  return (
    <AppCtx.Provider value={{ me, setMe, dash, reloadDash: reload, go }}>
      {dash && <div className={'modebar ' + (live ? 'live' : 'paper')}>{live ? 'ECHTGELD · LIVE-KONTO' : 'PAPER TRADING · SPIELGELD'}</div>}
      <div className="app">
        <aside className="side">
          <div className="brand"><img src="/icon.svg" alt="" />Trading-Bot</div>
          <nav className="nav">{nav.map(([id, label]) => <a key={id} href={'#/' + id} className={page === id ? 'on' : ''}><Icon name={id} />{label}</a>)}</nav>
          <div className="me" onClick={() => go('konto')}>
            <div className="avatar">{initials}</div>
            <div style={{ minWidth: 0 }}><div style={{ fontSize: 14, fontWeight: 600 }}>{me.display_name}</div>
              <small>{live ? 'Live-Konto' : 'Paper-Konto'} · {eur(dash?.equity)}</small></div>
          </div>
        </aside>
        <main className="main"><Page /></main>
        <nav className="tabbar">{TABS.map(([id, label]) => <a key={id} href={'#/' + id} className={page === id || (id === 'mehr' && !TABS.some((t) => t[0] === page)) ? 'on' : ''}><Icon name={id} />{label}</a>)}</nav>
      </div>
      <Toaster />
    </AppCtx.Provider>
  )
}
