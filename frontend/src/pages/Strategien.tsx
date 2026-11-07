import { useState } from 'react'
import { dt, num, pct, useApi } from '../api'
import { useApp } from '../App'
import { clone, useConfig } from '../config'
import { command } from '../controls'
import { Dialog, Loading, Switch } from '../ui'

const LC_COLOR: Record<string, string> = { entwurf: 'grey', backtest: 'blue', paper: 'blue', live_klein: 'amber', live: 'green', pausiert: 'amber', ausgemustert: 'red' }

export default function Strategien() {
  const { data, reload } = useApi('/strategies', 30000)
  const { meta, cfg, save, dialog } = useConfig()
  const { go } = useApp()
  const [edit, setEdit] = useState<any>(null), [add, setAdd] = useState(false)
  if (!data || !cfg) return <Loading />
  const lib: Record<string, any> = Object.fromEntries(data.library.filter((l: any) => l.type).map((l: any) => [l.type, l]))
  const batch = data.last_batch as any[]
  const pendingProposal = batch.length > 0 && !batch[0].applied
  const setStatus = (id: string, status: string) => {
    const c = clone(cfg); c.strategies.find((s: any) => s.id === id).status = status; save(c)
  }
  return (
    <>
      <div className="head"><h1>Strategien</h1><button className="btn primary" onClick={() => setAdd(true)}>Neue Strategie</button></div>
      <div className="grid g3">
        {cfg.strategies.map((s: any) => {
          const l = lib[s.type] || {}, sc = data.scorecards[s.id], w = data.weights[s.id]
          return <div className="card" key={s.id}>
            <div className="row between"><h3 style={{ margin: 0 }}>{s.name}</h3><span className={'pill nodot ' + LC_COLOR[s.status]}>{meta.lifecycle[s.status]}</span></div>
            <p className="muted" style={{ fontSize: 13.5, marginTop: 6, minHeight: 40 }}>{l.description}</p>
            <div className="grid g2" style={{ gap: 8, margin: '10px 0' }}>
              <div><small>Erwartungswert</small><div className="mono">{sc?.expectancy_r != null ? num(sc.expectancy_r) + ' R' : '–'}</div></div>
              <div><small>Trefferquote</small><div className="mono">{sc?.win_rate != null ? pct(sc.win_rate, false, 0) : '–'}</div></div>
              <div><small>Profit Factor</small><div className="mono">{num(sc?.profit_factor)}</div></div>
              <div><small>Trades (Schatten)</small><div className="mono">{sc?.trades ?? 0}</div></div>
            </div>
            <small>{s.timeframe} · {(s.markets.length ? s.markets : cfg.markets).join(', ')} · Gewicht {w ? Math.round(w * 100) + ' %' : '0 %'}</small>
            <div className="row" style={{ marginTop: 12 }}>
              <select value={s.status} onChange={(e) => setStatus(s.id, e.target.value)} style={{ flex: 1 }}>
                {Object.entries(meta.lifecycle).map(([k, v]: any) => <option key={k} value={k}>{v}</option>)}
              </select>
              <button className="btn" onClick={() => setEdit(clone(s))}>Bearbeiten</button>
            </div>
          </div>
        })}
      </div>

      <div className="card" style={{ marginTop: 14 }}>
        <div className="row between wrap"><h2 style={{ margin: 0 }}>Strategieauswahl (Meta-Controller)</h2>
          <div className="row"><button className="btn small" onClick={async () => { await command('auswahl_neu'); reload() }}>Neu bewerten</button>
            {pendingProposal && <button className="btn small primary" onClick={async () => { await command('auswahl_bestaetigen'); reload() }}>Vorschlag übernehmen</button>}</div></div>
        <p className="muted" style={{ fontSize: 13.5, marginTop: 8 }}>
          Bewertet die Strategien {cfg.selection.rhythm === 'taeglich' ? 'täglich' : 'wöchentlich'} nach Marktlage und Scorecard. Modus: <b>{cfg.selection.mode === 'automatisch' ? 'automatisch' : 'nur Vorschlag (du bestätigst)'}</b>.
          Der Meta-Controller gibt nie selbst Orders auf. „Keine Strategie“ ist ein gültiges Ergebnis.</p>
        {batch.length === 0 ? <div className="empty">Noch keine Bewertung</div> :
          <div className="scroll"><table className="tbl"><thead><tr><th>Strategie</th><th>Gewicht</th><th>Status</th><th>Begründung</th></tr></thead>
            <tbody>{batch.map((a) => <tr key={a.strategy_id}><td>{cfg.strategies.find((s: any) => s.id === a.strategy_id)?.name || a.strategy_id}</td>
              <td className="mono">{Math.round(a.weight * 100)} %</td><td>{a.status}</td><td><small>{a.reasoning.grund}{a.reasoning.hysterese ? ' · ' + a.reasoning.hysterese : ''}</small></td></tr>)}</tbody></table>
            <small>{pendingProposal ? 'Vorschlag vom ' : 'Übernommen am '}{dt(batch[0].time)}</small></div>}
      </div>

      <div className="card" style={{ marginTop: 14 }}>
        <div className="row between wrap"><div><h2 style={{ marginBottom: 4 }}>Backtest</h2><p className="muted" style={{ margin: 0 }}>Teste eine Strategie mit historischen Daten, bevor sie live läuft.</p></div>
          <button className="btn primary" onClick={() => go('backtest')}>Backtest starten</button></div>
      </div>

      <div className="card" style={{ marginTop: 14 }}>
        <h2>Strategiebibliothek</h2>
        <div className="scroll"><table className="tbl"><thead><tr><th>Familie</th><th>Prinzip</th><th>Passt zu</th><th>Risiko</th><th>Status</th></tr></thead>
          <tbody>{data.library.map((l: any) => <tr key={l.family}><td><b>{l.name}</b></td><td><small>{l.principle}</small></td><td><small>{l.fits}</small></td><td><small>{l.risk}</small></td>
            <td>{l.available ? <span className="pill green nodot">verfügbar</span> : <small className="warn">{l.blocked_reason}</small>}</td></tr>)}</tbody></table></div>
      </div>

      {edit && <EditStrategy s={edit} lib={lib[edit.type]} markets={meta.markets.map((m: any) => m.symbol)} onClose={() => setEdit(null)}
        onSave={(ns, remove) => { const c = clone(cfg); c.strategies = remove ? c.strategies.filter((x: any) => x.id !== ns.id) : c.strategies.map((x: any) => (x.id === ns.id ? ns : x)); setEdit(null); save(c) }} />}
      {add && <AddStrategy lib={data.library.filter((l: any) => l.available)} onClose={() => setAdd(false)} onAdd={(type, name) => {
        const c = clone(cfg); let id = type, i = 2
        while (c.strategies.some((x: any) => x.id === id)) id = `${type}_${i++}`
        c.strategies.push({ id, type, name, status: 'entwurf', timeframe: '1h', markets: [], params: {} }); setAdd(false); save(c)
      }} />}
      {dialog}
    </>
  )
}

function EditStrategy({ s, lib, markets, onClose, onSave }: { s: any; lib: any; markets: string[]; onClose: () => void; onSave: (s: any, remove?: boolean) => void }) {
  const [x, setX] = useState(s)
  const setP = (k: string, v: any) => setX({ ...x, params: { ...x.params, [k]: v } })
  return <Dialog title={`${s.name} bearbeiten`} onClose={onClose}>
    <label className="f"><span>Name</span><input value={x.name} onChange={(e) => setX({ ...x, name: e.target.value })} /></label>
    <label className="f"><span>Zeitrahmen</span><select value={x.timeframe} onChange={(e) => setX({ ...x, timeframe: e.target.value })}>
      {['15m', '1h', '4h', '1d'].map((t) => <option key={t}>{t}</option>)}</select></label>
    <div className="f"><span className="muted" style={{ fontSize: 13 }}>Märkte (leer = alle aktiven Märkte)</span>
      <div className="row wrap" style={{ marginTop: 6 }}>{markets.map((m) => <label key={m} className="check" style={{ margin: 0 }}>
        <input type="checkbox" checked={x.markets.includes(m)} onChange={(e) => setX({ ...x, markets: e.target.checked ? [...x.markets, m] : x.markets.filter((y: string) => y !== m) })} />{m}</label>)}</div></div>
    <h3 style={{ marginTop: 14 }}>Parameter</h3>
    {lib?.params.map((p: any) => <div className="setting" key={p.key}>
      <div className="t">{p.label}<small>Standard: {String(p.default)}{p.help ? ' · ' + p.help : ''}</small></div>
      {typeof p.default === 'boolean' ? <Switch checked={x.params[p.key] ?? p.default} onChange={(v) => setP(p.key, v)} />
        : <input type="number" step={p.step} min={p.min} max={p.max} value={x.params[p.key] ?? p.default} onChange={(e) => setP(p.key, e.target.value === '' ? undefined : Number(e.target.value))} />}
    </div>)}
    <div className="row" style={{ marginTop: 14 }}>
      <button className="btn ghost neg" onClick={() => confirm('Strategie entfernen?') && onSave(x, true)}>Entfernen</button>
      <span className="sp" /><button className="btn" onClick={() => setX({ ...x, params: {} })}>Standardwerte</button>
      <button className="btn primary" onClick={() => onSave(x)}>Weiter</button>
    </div>
  </Dialog>
}

function AddStrategy({ lib, onClose, onAdd }: { lib: any[]; onClose: () => void; onAdd: (type: string, name: string) => void }) {
  return <Dialog title="Neue Strategie" onClose={onClose}>
    <p className="muted">Neue Strategien starten als „Entwurf“. Danach Backtest → Paper → Live-klein → Live.</p>
    <div className="list">{lib.map((l) => <div key={l.type}><div className="sp"><b>{l.name}</b><br /><small>{l.description}</small></div>
      <button className="btn small primary" onClick={() => onAdd(l.type, l.name)}>Hinzufügen</button></div>)}</div>
  </Dialog>
}
