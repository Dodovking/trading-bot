import { ago, cls, dt, eur, pct, price, qty } from '../api'
import { useState } from 'react'
import { useApp } from '../App'
import { command, BotControls } from '../controls'
import { Dialog, LineChart, Loading, StatePill } from '../ui'

export const REG: Record<string, string> = { trend_auf: 'green', trend_ab: 'red', hohe_volatilitaet: 'amber', ruhig: 'blue', seitwaerts: 'grey', unklar: 'grey' }
const SEV: Record<string, string> = { info: 'grey', warnung: 'amber', fehler: 'red', kritisch: 'red' }

export default function Dashboard() {
  const { dash: d, reloadDash, go } = useApp()
  if (!d) return <Loading />
  const curve: [number, number][] = d.curve.map((c: [string, number]) => [new Date(c[0]).getTime(), c[1]])
  const load = d.equity ? (d.exposure / d.equity) * 100 : 0
  return (
    <>
      <div className="head">
        <h1>Dashboard</h1>
        <StatePill state={d.state} label={d.state === 'AKTIV' ? 'Bot läuft' : d.state_label} />
        <div className="hide-m"><BotControls /></div>
      </div>
      {d.state !== 'AKTIV' && d.state_reason && <div className={['GESPERRT', 'NOT_AUS', 'FEHLER'].includes(d.state) ? 'err' : 'note'}>{d.state_label}: {d.state_reason}</div>}
      {d.engine_error && <div className="err">Störung: {d.engine_error}</div>}
      {d.pending_signals.length > 0 && <div className="card" style={{ marginBottom: 14, borderColor: 'var(--amber)' }}>
        <h2>Signale warten auf deine Bestätigung</h2>
        <div className="list">{d.pending_signals.map((s: any) => <div key={s.id}>
          <div className="sp"><b>{s.symbol}</b> · {s.strategy} · Kauf zu ~{price(s.price)}, Stop {price(s.stop)}<br /><small>{s.reason} · {ago(s.time)}</small></div>
          <button className="btn small" onClick={async () => { await command('signal_verwerfen', { signal_id: s.id }); reloadDash() }}>Verwerfen</button>
          <button className="btn small primary" onClick={async () => { await command('signal_bestaetigen', { signal_id: s.id }); reloadDash() }}>Bestätigen</button>
        </div>)}</div>
      </div>}
      {d.proposal_open && <div className="info row wrap" style={{ marginBottom: 14 }}>
        <span className="sp">Der Meta-Controller hat eine neue Strategieauswahl vorgeschlagen.</span>
        <button className="btn small" onClick={() => go('strategien')}>Ansehen</button>
      </div>}
      <div className="grid g4">
        <div className="card kpi wide-m"><small>Gewinn heute</small><div className={'v ' + cls(d.day_pnl)}>{eur(d.day_pnl, true)}</div></div>
        <div className="card kpi"><small>Offene Positionen</small><div className="v">{d.positions.length}</div></div>
        <div className="card kpi"><small>Trefferquote</small><div className="v">{d.win_rate == null ? '–' : pct(d.win_rate, false, 0)}</div></div>
        <div className="card kpi hide-m"><small>Risiko-Auslastung</small><div className="v">{pct(load, false, 0)}</div></div>
      </div>
      <div className="card" style={{ marginTop: 14 }}>
        <div className="row between"><small>Kontoverlauf</small><span className="mono">{eur(d.equity)} <small className={cls(d.equity - d.start_capital)}>({pct(d.start_capital ? (d.equity / d.start_capital - 1) * 100 : 0, true)})</small></span></div>
        <LineChart points={curve} base={d.start_capital} />
      </div>
      <div className="mobile-only ctl" style={{ marginTop: 14 }}><BotControls big /></div>
      <div className="grid g2" style={{ marginTop: 14 }}>
        <div className="card">
          <h2>Offene Positionen</h2>
          {d.positions.length === 0 ? <div className="empty">Keine offenen Positionen</div> :
            <div className="list">{d.positions.map((p: any) => <div key={p.id}>
              <div className="sp"><b>{p.symbol}</b> <small>{p.kind === 'bestand' ? 'Bestand' : 'Long'} · {p.strategy}</small><br />
                <small className="mono">{qty(p.qty)} @ {price(p.entry)} → {price(p.price)}{p.stop ? ` · Stop ${price(p.stop)}` : ''}</small>
                {!p.protected && <small className="neg"> · ohne Stop!</small>}</div>
              <div style={{ textAlign: 'right' }} className={'mono ' + cls(p.pnl)}>{eur(p.pnl, true)}<br /><small>{pct(p.pnl_pct, true)}</small></div>
            </div>)}</div>}
        </div>
        <div className="card">
          <h2>Marktlage</h2>
          <div className="list">{d.regimes.map((r: any) => <div key={r.symbol}>
            <b style={{ width: 80 }}>{r.symbol}</b>
            <div className="sp"><span className={'pill nodot ' + (REG[r.regime] || 'grey')}>{r.label}</span><br /><small>{r.hint}</small></div>
            <span className="mono">{price(d.tickers[r.symbol]?.last)}</span>
          </div>)}</div>
          <small>Aktive Gewichte: {Object.keys(d.weights).length ? Object.entries(d.weights).map(([k, v]: any) => `${k} ${Math.round(v * 100)} %`).join(', ') : 'keine Strategie aktiv'}</small>
        </div>
      </div>
      {d.external?.length > 0 && <ExternalHoldings items={d.external} onDone={reloadDash} />}
      <div className="card" style={{ marginTop: 14 }}>
        <div className="row between"><h2>Meldungen</h2><a href="#/verlauf/meldungen">Alle</a></div>
        <div className="list">{d.events.slice(0, 8).map((e: any) => <div key={e.id}>
          <span className={'pill nodot ' + SEV[e.severity]} style={{ minWidth: 70, justifyContent: 'center' }}>{e.severity}</span>
          <span className="sp">{e.message}</span><small className="hide-m">{dt(e.time)}</small></div>)}</div>
      </div>
      <p className="muted" style={{ fontSize: 12.5, marginTop: 14 }}>
        Broker {d.broker_ok ? 'verbunden' : 'getrennt'} · Abgleich {d.reconcile_ok ? 'ok' : 'offen'} {d.last_reconcile_at ? ago(d.last_reconcile_at) : ''} · Herzschlag {d.heartbeat_age_s != null ? `vor ${Math.round(d.heartbeat_age_s)} s` : '–'}
      </p>
    </>
  )
}

function ExternalHoldings({ items, onDone }: { items: any[], onDone: () => void }) {
  const [pick, setPick] = useState<any>(null), [busy, setBusy] = useState(false)
  return <div className="card" style={{ marginTop: 14 }}>
    <div className="row between"><h2>Weitere Bestände bei deinen Anbietern</h2>
      <span className="mono">{eur(items.reduce((a: number, x: any) => a + (x.eur ? Number(x.eur) : 0), 0))}</span></div>
    <div className="list">{items.map((x: any) => <div key={x.asset + (x.staking ? 's' : '')}>
      <b style={{ width: 80 }}>{x.asset}</b>
      <span className="sp mono">{qty(x.qty)}{x.staking ? <small> · gestaked/gebunden</small> : null}</span>
      <span className="mono">{x.eur != null ? eur(Number(x.eur)) : <small>Kurs unbekannt</small>}</span>
      {x.symbol && <button className="btn small" style={{ marginLeft: 8 }} onClick={() => setPick(x)}>Dem Bot übergeben</button>}
    </div>)}</div>
    <small className="muted">Diese Coins und Aktien hast du selbst gekauft. Der Bot rührt sie nicht an, solange du sie ihm nicht mit
      „Dem Bot übergeben“ anvertraust. Gestakte Coins musst du dafür zuerst beim Anbieter freigeben.</small>
    {pick && <Dialog title={`${pick.asset} dem Bot übergeben?`} onClose={() => setPick(null)}>
      <p>Der Bot verwaltet dann deine {qty(pick.qty)} {pick.asset}{pick.eur != null ? ` (≈ ${eur(Number(pick.eur))})` : ''} wie einen eigenen Kauf:</p>
      <ul>
        <li>Er setzt sofort einen <b>Stop-Loss</b> beim Anbieter. Fällt der Kurs darunter, wird automatisch verkauft.</li>
        <li>Er <b>verkauft</b>, wenn seine Strategie ein Verkaufssignal gibt. Den Erlös in Euro nutzt er danach für neue Käufe.</li>
        <li>Gewinn und Verlust zählen ab dem heutigen Kurs, nicht ab deinem damaligen Kaufpreis.</li>
        <li>Die Grenze „max. Anteil einer Position“ gilt dabei nicht – du übergibst den Bestand bewusst.</li>
      </ul>
      <p className="muted">Danach steht {pick.asset} bei den offenen Positionen. Schließt du die Position dort, verkauft der Bot sie sofort gegen Euro.</p>
      <div className="row" style={{ justifyContent: 'flex-end' }}><button className="btn" onClick={() => setPick(null)}>Abbrechen</button>
        <button className="btn primary" disabled={busy} onClick={async () => {
          setBusy(true); const ok = await command('bestand_uebernehmen', { asset: pick.asset }); setBusy(false)
          if (ok) { setPick(null); onDone() }
        }}>Ja, übergeben</button></div>
    </Dialog>}
  </div>
}
