import { useState } from 'react'
import { cls, dt, eur, pct, price, qty, useApi } from '../api'
import { Loading } from '../ui'

const TABS = [['trades', 'Trades'], ['signale', 'Signale'], ['orders', 'Orders'], ['meldungen', 'Meldungen']]
const SEV: Record<string, string> = { info: 'grey', warnung: 'amber', fehler: 'red', kritisch: 'red' }

export default function Verlauf() {
  const sub = location.hash.split('/')[2]
  const [tab, setTab] = useState(TABS.some((t) => t[0] === sub) ? sub : 'trades')
  return (
    <>
      <div className="head"><h1>Verlauf</h1>{tab !== 'meldungen' && <a className="btn" href={`/api/export/${tab === 'signale' ? 'trades' : tab}.csv`}>Export</a>}</div>
      <div className="tabs">{TABS.map(([id, l]) => <button key={id} className={tab === id ? 'on' : ''} onClick={() => setTab(id)}>{l}</button>)}</div>
      {tab === 'trades' && <Trades />}{tab === 'signale' && <Signale />}{tab === 'orders' && <Orders />}{tab === 'meldungen' && <Meldungen />}
    </>
  )
}

function Trades() {
  const { data } = useApi<any[]>('/trades?limit=500', 30000)
  const [range, setRange] = useState('alle')
  if (!data) return <Loading />
  const since = { heute: 1, woche: 7, monat: 31, alle: 1e5 }[range]!
  const rows = data.filter((t) => Date.now() - new Date(t.closed_at).getTime() < since * 86400000)
  const sum = rows.reduce((a, t) => a + (t.pnl || 0), 0)
  return <>
    <div className="row between wrap" style={{ marginBottom: 12 }}>
      <div className="seg">{['heute', 'woche', 'monat', 'alle'].map((r) => <button key={r} className={range === r ? 'on' : ''} onClick={() => setRange(r)}>{r[0].toUpperCase() + r.slice(1)}</button>)}</div>
      <span>{rows.length} Trades · <b className={cls(sum)}>{eur(sum, true)}</b></span></div>
    {rows.length === 0 ? <div className="card empty">Noch keine abgeschlossenen Trades in diesem Zeitraum</div> : <>
      <div className="card hide-m scroll"><table className="tbl"><thead><tr><th>Markt</th><th>Richtung</th><th>Strategie</th><th>Modus</th><th>Eröffnet</th><th>Geschlossen</th><th className="r">Einstieg</th><th className="r">Ausstieg</th><th>Grund</th><th className="r">Ergebnis</th></tr></thead>
        <tbody>{rows.map((t) => <tr key={t.id}><td><b>{t.symbol}</b></td><td>{t.kind === 'bestand' ? 'Bestand' : 'Long'}</td><td>{t.strategy}</td><td>{t.mode}</td><td>{dt(t.opened_at)}</td><td>{dt(t.closed_at)}</td>
          <td className="r">{price(t.entry)}</td><td className="r">{price(t.exit)}</td><td><small>{t.reason}</small></td><td className={'r ' + cls(t.pnl)}>{eur(t.pnl, true)}<br /><small>{pct(t.pnl_pct, true)}</small></td></tr>)}</tbody></table></div>
      <div className="card mobile-only list">{rows.map((t) => <div key={t.id}><div className="sp"><b>{t.symbol} · Long</b><br /><small>{dt(t.closed_at)} · {t.reason}</small></div><b className={cls(t.pnl)}>{eur(t.pnl, true)}</b></div>)}</div>
    </>}
  </>
}

function Signale() {
  const { data } = useApi<any[]>('/signals?limit=300', 30000)
  const [open, setOpen] = useState<number | null>(null)
  if (!data) return <Loading />
  if (!data.length) return <div className="card empty">Noch keine Signale. Hier siehst du später, warum der Bot gekauft hat – oder warum nicht.</div>
  return <div className="card list">{data.map((s) => <div key={s.id} style={{ display: 'block', cursor: 'pointer' }} onClick={() => setOpen(open === s.id ? null : s.id)}>
    <div className="row"><div className="sp"><b>{s.symbol}</b> · {s.strategy} · {s.timeframe}<br /><small>{dt(s.time)} · Kauf ~{price(s.price)}, Stop {price(s.stop)}</small></div>
      <span className={'pill nodot ' + (s.risk?.result === 'abgelehnt' ? 'red' : s.status === 'ausgefuehrt' ? 'green' : 'grey')}>{s.risk?.result === 'abgelehnt' ? 'abgelehnt' : s.status}</span></div>
    {open === s.id && <div style={{ marginTop: 8, fontSize: 13.5 }}>
      <p><b>Warum:</b> {s.reasoning?.grund}</p>
      {s.risk && <><p><b>Risikoprüfung:</b> {s.risk.result}{s.risk.rule ? ` – ${s.risk.rule} (Grenze ${s.risk.limit}, Ist ${s.risk.actual})` : ''}{s.risk.qty ? ` · Menge ${qty(s.risk.qty)}` : ''}</p>
        <div className="diff">{(s.risk.checks || []).map((c: any, i: number) => <div key={i}>{c.ok ? '✓' : '✗'} {c.nr}. {c.name}{c.note ? ': ' + c.note : ''}{!c.ok && c.rule ? ' – ' + c.rule : ''}</div>)}</div></>}
    </div>}
  </div>)}</div>
}

function Orders() {
  const { data } = useApi<any[]>('/orders?limit=300', 30000)
  if (!data) return <Loading />
  if (!data.length) return <div className="card empty">Noch keine Orders</div>
  return <div className="card scroll"><table className="tbl"><thead><tr><th>Zeit</th><th>Markt</th><th>Seite</th><th>Typ</th><th>Zweck</th><th className="r">Menge</th><th className="r">Kurs</th><th>Status</th><th className="hide-m">Client-Order-ID</th></tr></thead>
    <tbody>{data.map((o) => <tr key={o.id}><td>{dt(o.created_at)}</td><td>{o.symbol}</td><td>{o.side}</td><td>{o.type}</td><td>{o.purpose}</td><td className="r">{qty(o.qty)}</td>
      <td className="r">{price(o.avg_price ?? o.stop_price)}</td><td>{o.status}</td><td className="hide-m"><small className="mono">{o.client_order_id}</small></td></tr>)}</tbody></table></div>
}

function Meldungen() {
  const [sev, setSev] = useState('')
  const { data } = useApi<any[]>('/events?limit=300' + (sev ? '&severity=' + sev : ''), 20000)
  return <>
    <div className="seg" style={{ marginBottom: 12 }}>{[['', 'Alle'], ['warnung', 'Warnungen'], ['fehler', 'Fehler'], ['kritisch', 'Kritisch']].map(([k, l]) =>
      <button key={k} className={sev === k ? 'on' : ''} onClick={() => setSev(k)}>{l}</button>)}</div>
    {!data ? <Loading /> : <div className="card list">{data.length === 0 ? <div className="empty">Keine Meldungen</div> : data.map((e) => <div key={e.id}>
      <span className={'pill nodot ' + SEV[e.severity]} style={{ minWidth: 72, justifyContent: 'center' }}>{e.severity}</span>
      <span className="sp">{e.message}<br /><small>{e.module} · {dt(e.time)}</small></span></div>)}</div>}
  </>
}
