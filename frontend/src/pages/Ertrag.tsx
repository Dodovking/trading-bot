import { useState } from 'react'
import { dt, eur, useApi } from '../api'
import { clone, useConfig } from '../config'
import { Loading } from '../ui'

const ST: Record<string, [string, string]> = { verfuegbar: ['green', 'nutzbar'], vergleich: ['blue', 'nur Vergleich'], spaeter: ['grey', 'später'], nicht_empfohlen: ['red', 'nicht empfohlen'] }
const MLC: Record<string, string> = { entwurf: 'Entwurf (aus)', paper: 'Paper', live_klein: 'Live-klein', live: 'Live', pausiert: 'Pausiert' }

export default function Ertrag() {
  const { data } = useApi('/earn', 30000)
  const { cfg, save, dialog } = useConfig()
  const [m, setM] = useState<any>(null)
  if (!data || !cfg) return <Loading />
  const mod = m || clone(cfg.modules)
  const sp = mod.sparplan, rb = mod.rebalancing
  const setSp = (k: string, v: any) => setM({ ...mod, sparplan: { ...sp, [k]: v } })
  const setRb = (k: string, v: any) => setM({ ...mod, rebalancing: { ...rb, [k]: v } })
  const wsum = Object.values(sp.weights as Record<string, number>).reduce((a, b) => a + Number(b || 0), 0)
  return (
    <>
      <div className="head"><h1>Ertragsmodule</h1></div>
      <p className="muted">Neben den Strategien kann der Bot weitere Ertragswege nutzen. Alle Module laufen über dieselbe Risikoprüfung, dasselbe Protokoll und denselben Not-Aus.</p>
      <div className="note">{data.warning}</div>
      <div className="grid g2">
        <div className="card">
          <div className="row between"><h2 style={{ margin: 0 }}>Sparplan</h2>
            <select style={{ width: 150 }} value={sp.status} onChange={(e) => setSp('status', e.target.value)}>{Object.entries(MLC).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></div>
          <p className="muted" style={{ fontSize: 13.5, marginTop: 8 }}>Kauft regelmäßig für einen festen Betrag nach deinen Zielgewichten. Bestände bekommen keinen Stop-Loss (langfristig).</p>
          <div className="setting"><div className="t">Betrag je Ausführung</div><input type="number" min={10} step={10} value={sp.amount} onChange={(e) => setSp('amount', Number(e.target.value))} /></div>
          <div className="setting"><div className="t">Rhythmus</div><select value={sp.rhythm} onChange={(e) => setSp('rhythm', e.target.value)}><option value="woechentlich">wöchentlich</option><option value="monatlich">monatlich</option></select></div>
          <div className="setting"><div className="t">{sp.rhythm === 'monatlich' ? 'Tag im Monat' : 'Wochentag (0 = Montag … 6 = Sonntag)'}</div><input type="number" min={sp.rhythm === 'monatlich' ? 1 : 0} max={sp.rhythm === 'monatlich' ? 28 : 6} value={sp.day} onChange={(e) => setSp('day', Number(e.target.value))} /></div>
          <h3 style={{ marginTop: 12 }}>Zielgewichte <small className={Math.abs(wsum - 100) > 0.01 ? 'neg' : 'muted'}>(Summe {wsum} %)</small></h3>
          {cfg.markets.map((sym: string) => <div className="setting" key={sym}><div className="t">{sym}</div>
            <input type="number" min={0} max={100} step={5} value={sp.weights[sym] ?? 0} onChange={(e) => setSp('weights', { ...sp.weights, [sym]: Number(e.target.value) })} /></div>)}
        </div>
        <div className="card">
          <div className="row between"><h2 style={{ margin: 0 }}>Rebalancing</h2>
            <select style={{ width: 150 }} value={rb.status} onChange={(e) => setRb('status', e.target.value)}>{Object.entries(MLC).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></div>
          <p className="muted" style={{ fontSize: 13.5, marginTop: 8 }}>Stellt die Zielgewichte des Sparplan-Bestands wieder her: erst übergewichtete Werte verkaufen, dann untergewichtete kaufen.</p>
          <div className="setting"><div className="t">Rhythmus</div><select value={rb.rhythm} onChange={(e) => setRb('rhythm', e.target.value)}><option value="woechentlich">wöchentlich</option><option value="monatlich">monatlich</option></select></div>
          <div className="setting"><div className="t">Schwelle<small>Nur umschichten, wenn ein Wert mehr als so viele Prozentpunkte abweicht</small></div>
            <input type="number" min={1} max={50} step={0.5} value={rb.threshold_pct} onChange={(e) => setRb('threshold_pct', Number(e.target.value))} /></div>
          <div className="info" style={{ marginTop: 12 }}>Risikoregeln für Module: Modulbudget {cfg.risk.module_budget_pct} %, Liquiditätsreserve {cfg.risk.liquidity_reserve_pct} %, Gegenparteilimit {cfg.risk.counterparty_limit_pct} % (unter Einstellungen → Risiko).</div>
          <div className="row" style={{ justifyContent: 'flex-end', marginTop: 12 }}>
            <button className="btn" disabled={!m} onClick={() => setM(null)}>Zurücksetzen</button>
            <button className="btn primary" disabled={!m} onClick={() => { const c = clone(cfg); c.modules = mod; save(c); setM(null) }}>Speichern</button></div>
        </div>
      </div>

      <div className="card" style={{ marginTop: 14 }}>
        <div className="row between"><h2 style={{ margin: 0 }}>Erträge und Modul-Aktionen</h2><a className="btn small" href="/api/export/ertraege.csv">CSV-Export (Steuer)</a></div>
        {data.income.length === 0 ? <div className="empty">Noch keine Einträge</div> :
          <div className="scroll"><table className="tbl" style={{ marginTop: 8 }}><thead><tr><th>Zeit</th><th>Modus</th><th>Quelle</th><th>Art</th><th>Wert</th><th className="r">Betrag</th><th>Notiz</th></tr></thead>
            <tbody>{data.income.map((i: any, k: number) => <tr key={k}><td>{dt(i.time)}</td><td>{i.mode}</td><td>{i.source}</td><td>{i.kind}</td><td>{i.asset}</td><td className="r mono">{eur(i.amount)}</td><td><small>{i.note}</small></td></tr>)}</tbody></table></div>}
      </div>

      <div className="card" style={{ marginTop: 14 }}>
        <h2>Alle Ertragswege</h2>
        <div className="scroll"><table className="tbl"><thead><tr><th>Ertragsweg</th><th>Funktion</th><th>Risiken</th><th>Status</th></tr></thead>
          <tbody>{data.catalog.map((c: any) => <tr key={c.id}><td><b>{c.name}</b><br /><small>{c.einsatz}</small></td><td><small>{c.funktion}</small></td><td><small>{c.risiken}</small></td>
            <td><span className={'pill nodot ' + ST[c.status][0]}>{ST[c.status][1]}</span>{c.grund && <><br /><small className="muted">{c.grund}</small></>}</td></tr>)}</tbody></table></div>
      </div>
      {dialog}
    </>
  )
}
