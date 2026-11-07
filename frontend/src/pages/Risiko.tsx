import { useState } from 'react'
import { pct, useApi } from '../api'
import { useApp } from '../App'
import { NotAus } from '../controls'
import { Bar, Loading } from '../ui'

export default function Risiko() {
  const { dash: d, go, reloadDash } = useApp()
  const { data: c } = useApi('/config', 0)
  const [na, setNa] = useState(false)
  if (!d || !c) return <Loading />
  const r = c.config.risk
  const dayLoss = d.day_pnl < 0 && d.equity ? (-d.day_pnl / (d.equity - d.day_pnl)) * 100 : 0
  const load = d.equity ? (d.exposure / d.equity) * 100 : 0
  const trading = d.positions.filter((p: any) => p.kind !== 'bestand').length
  const items = [
    ['Tagesverlust', dayLoss, r.daily_loss_limit_pct, `${pct(dayLoss)} von ${pct(r.daily_loss_limit_pct, false, 0)}`],
    ['Offene Positionen', trading, r.max_positions, `${trading} von ${r.max_positions}`],
    ['Risiko-Auslastung (investiert)', load, r.max_exposure_pct ?? 100, pct(load, false, 0) + (r.max_exposure_pct ? ` von ${pct(r.max_exposure_pct, false, 0)}` : '')],
    ['Drawdown', d.drawdown_pct || 0, r.max_drawdown_pct, `${pct(d.drawdown_pct || 0)} von ${pct(r.max_drawdown_pct, false, 0)}`],
    ['Verlustserie', d.loss_streak, r.loss_streak_limit, `${d.loss_streak} von ${r.loss_streak_limit}`],
  ] as [string, number, number, string][]
  const worst = Math.max(...items.map(([, v, m]) => (m ? v / m : 0)))
  return (
    <>
      <div className="head"><h1>Risiko</h1>
        <span className={'pill ' + (worst >= 1 ? 'red' : worst >= 0.7 ? 'amber' : 'green')}>{worst >= 1 ? 'Limit erreicht' : worst >= 0.7 ? 'Achtung' : 'Alles im grünen Bereich'}</span></div>
      <div className="card">
        {items.map(([label, v, m, txt]) => <div key={label} style={{ padding: '10px 0' }}>
          <div className="row between"><span>{label}</span><span className="mono muted">{txt}</span></div><Bar value={v} max={m} /></div>)}
      </div>
      <div className="card">
        <div className="row between wrap"><div><h2 style={{ marginBottom: 4 }}>Regeln</h2>
          <p className="muted" style={{ margin: 0 }}>Risiko pro Trade {pct(r.risk_per_trade_pct)} · max. {pct(r.strategy_budget_pct, false, 0)} Budget je Strategie · Gesamtrisiko max. {pct(r.max_total_risk_pct)} · Liquiditätsreserve {pct(r.liquidity_reserve_pct, false, 0)}.
            Jede Position bekommt sofort einen Stop-Loss beim Broker. Kein Hebel, keine Leerverkäufe.</p></div>
          <button className="btn" onClick={() => go('einstellungen/risiko')}>Ändern</button></div>
      </div>
      <div className="card" style={{ borderColor: 'rgba(255,123,114,.4)' }}>
        <div className="row between wrap"><div><h2 style={{ marginBottom: 4 }}>Notbremse</h2><p className="muted" style={{ margin: 0 }}>Schließt alle offenen Positionen und stoppt den Bot sofort.</p></div>
          <button className="btn danger" onClick={() => setNa(true)}>Alles schließen</button></div>
      </div>
      {na && <NotAus onClose={() => { setNa(false); reloadDash() }} />}
    </>
  )
}
