import { useState } from 'react'
import { api, cls, dt, eur, num, pct, price, useApi } from '../api'
import { LineChart, Loading } from '../ui'

const K = ({ l, v, c: cl }: { l: string; v: string; c?: string }) => <div className="card kpi"><small>{l}</small><div className={'v ' + (cl || '')} style={{ fontSize: 21 }}>{v}</div></div>

export default function Backtest() {
  const { data: c } = useApi('/config', 0)
  const [f, setF] = useState({ strategy_type: 'trendfolge', symbol: 'BTC/EUR', timeframe: '4h', days: 730, capital: 10000, risk_pct: 1 })
  const [res, setRes] = useState<any>(null), [busy, setBusy] = useState(false), [err, setErr] = useState('')
  if (!c) return <Loading />
  const run = async () => {
    setBusy(true); setErr(''); setRes(null)
    try { setRes(await api('/backtest', { body: f })) } catch (e: any) { setErr(e.message) } finally { setBusy(false) }
  }
  const set = (k: string, num = false) => (e: any) => setF({ ...f, [k]: num ? Number(e.target.value) : e.target.value })
  return (
    <>
      <div className="head"><h1>Backtest</h1></div>
      <div className="card">
        <div className="grid g3" style={{ gap: 12 }}>
          <label className="f"><span>Strategie</span><select value={f.strategy_type} onChange={set('strategy_type')}>{Object.entries(c.strategy_types).map(([k, v]: any) => <option key={k} value={k}>{v.name}</option>)}</select></label>
          <label className="f"><span>Markt</span><select value={f.symbol} onChange={set('symbol')}>{c.markets.filter((m: any) => (m.market === 'krypto' || m.market === 'aktie') && m.data_ok).map((m: any) => <option key={m.symbol} value={m.symbol}>{m.name ? `${m.name} (${m.symbol})` : m.symbol}</option>)}</select></label>
          <label className="f"><span>Zeitrahmen</span><select value={f.timeframe} onChange={set('timeframe')}>{['15m', '1h', '4h', '1d'].map((t) => <option key={t}>{t}</option>)}</select></label>
          <label className="f"><span>Zeitraum (Tage)</span><input type="number" min={30} max={1500} value={f.days} onChange={set('days', true)} /></label>
          <label className="f"><span>Startkapital (€)</span><input type="number" min={100} value={f.capital} onChange={set('capital', true)} /></label>
          <label className="f"><span>Risiko pro Trade (%)</span><input type="number" min={0.1} max={5} step={0.1} value={f.risk_pct} onChange={set('risk_pct', true)} /></label>
        </div>
        <div className="row"><small className="sp">Kosten aus deinen Einstellungen (Gebühr {c.config.costs.fee_pct} %, Slippage {c.config.costs.slippage_pct} %). Stop wird innerhalb der Kerze zuerst geprüft (vorsichtig).</small>
          <button className="btn primary" disabled={busy} onClick={run}>{busy ? 'Läuft …' : 'Backtest starten'}</button></div>
      </div>
      {err && <div className="err" style={{ marginTop: 14 }}>{err}</div>}
      {busy && <Loading />}
      {res && <>
        <div className="grid g4" style={{ marginTop: 14 }}>
          <K l="Rendite" v={pct(res.gesamt.rendite_prozent, true)} c={cls(res.gesamt.rendite_prozent)} />
          <K l="Kaufen & Halten" v={pct(res.gesamt.kaufen_halten_prozent, true)} c={cls(res.gesamt.kaufen_halten_prozent)} />
          <K l="Max. Drawdown" v={pct(res.gesamt.max_drawdown_prozent)} />
          <K l="Trades / Trefferquote" v={`${res.gesamt.trades} / ${pct(res.gesamt.trefferquote_prozent, false, 0)}`} />
          <K l="Profit Factor" v={num(res.gesamt.profit_factor)} />
          <K l="Erwartungswert" v={num(res.gesamt.erwartungswert_r) + ' R'} c={cls(res.gesamt.erwartungswert_r)} />
          <K l="Sharpe" v={num(res.gesamt.sharpe)} />
          <K l="Endkapital" v={eur(res.gesamt.endkapital)} />
        </div>
        <div className="card" style={{ marginTop: 14 }}><small>Kapitalkurve</small>
          <LineChart points={res.kapitalkurve.map((p: any) => [new Date(p[0]).getTime(), p[1]])} base={f.capital} height={220} /></div>
        <div className="grid g2" style={{ marginTop: 14 }}>
          {[['In-Sample (Entwicklung)', res.in_sample], ['Out-of-Sample (Prüfung)', res.out_of_sample]].map(([l, m]: any) => <div className="card" key={l}><h3>{l}</h3>
            <small>Rendite <b className={cls(m.rendite_prozent)}>{pct(m.rendite_prozent, true)}</b> · Trades {m.trades} · Trefferquote {pct(m.trefferquote_prozent, false, 0)} · PF {num(m.profit_factor)} · Drawdown {pct(m.max_drawdown_prozent)}</small></div>)}
        </div>
        <div className="info" style={{ marginTop: 14 }}>{res.hinweis} Wichtig ist vor allem, dass das Out-of-Sample-Ergebnis nicht deutlich schlechter ist als In-Sample (sonst Überanpassung).</div>
        <div className="card scroll"><h2>Trades</h2><table className="tbl"><thead><tr><th>Eröffnet</th><th>Geschlossen</th><th className="r">Einstieg</th><th className="r">Ausstieg</th><th>Grund</th><th>Regime</th><th className="r">R</th><th className="r">Ergebnis</th></tr></thead>
          <tbody>{res.trades_liste.slice().reverse().map((t: any, i: number) => <tr key={i}><td>{dt(t.eroeffnet, true)}</td><td>{dt(t.geschlossen, true)}</td><td className="r">{price(t.einstieg)}</td><td className="r">{price(t.ausstieg)}</td>
            <td><small>{t.grund}</small></td><td><small>{t.regime}</small></td><td className="r">{num(t.r)}</td><td className={'r ' + cls(t.pnl)}>{eur(t.pnl, true)}</td></tr>)}</tbody></table></div>
      </>}
    </>
  )
}
