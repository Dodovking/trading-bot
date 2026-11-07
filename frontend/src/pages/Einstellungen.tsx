import { useEffect, useState } from 'react'
import { api } from '../api'
import { clone, useConfig } from '../config'
import { Loading, Switch, toast } from '../ui'
import { KontoBoerse } from './KontoBoerse'

const S = ({ t, h, children }: any) => <div className="setting"><div className="t">{t}{h && <small>{h}</small>}</div>{children}</div>
const TABS = [['strategie', 'Strategie'], ['risiko', 'Risiko'], ['maerkte', 'Märkte'], ['meldungen', 'Meldungen'], ['boerse', 'Konto & Börse']]

export default function Einstellungen() {
  const sub = location.hash.split('/')[2]
  const [tab, setTab] = useState(TABS.some((t) => t[0] === sub) ? sub : 'strategie')
  const { meta, cfg, save, dialog } = useConfig()
  const [c, setC] = useState<any>(null)
  useEffect(() => { if (cfg) setC(clone(cfg)) }, [cfg])
  if (!c || !meta) return <Loading />
  const dirty = JSON.stringify(c) !== JSON.stringify(cfg)
  const set = (path: string, v: any) => { const n = clone(c); const ks = path.split('.'); let o = n; ks.slice(0, -1).forEach((k) => (o = o[k])); o[ks[ks.length - 1]] = v; setC(n) }
  return (
    <>
      <div className="head"><h1>Einstellungen</h1></div>
      <div className="tabs">{TABS.map(([id, l]) => <button key={id} className={tab === id ? 'on' : ''} onClick={() => setTab(id)}>{l}</button>)}</div>
      {tab === 'boerse' ? <KontoBoerse cfg={cfg} save={save} /> : <div className="card">
        {tab === 'strategie' && <>
          <S t="Automatischer Handel" h="Bot darf selbstständig Orders setzen"><Switch checked={c.automation === 'automatisch'} onChange={(v) => set('automation', v ? 'automatisch' : 'halbautomatisch')} /></S>
          <S t="Handelsmodus" h="Signale = nur Hinweise · Halbautomatisch = du bestätigst jede Order · Automatisch">
            <select value={c.automation} onChange={(e) => set('automation', e.target.value)}><option value="signale">Nur Signale</option><option value="halbautomatisch">Halbautomatisch</option><option value="automatisch">Automatisch</option></select></S>
          <S t="Konto" h={c.account === 'live' ? 'ECHTGELD – Orders gehen an deine Börse' : 'Paper Trading mit Spielgeld'}>
            <select value={c.account} onChange={(e) => set('account', e.target.value)}><option value="paper">Paper</option><option value="live" disabled={!meta.foreign_live_allowed}>Live (Echtgeld)</option></select></S>
          <S t="Strategieauswahl" h="Vorschlag = du bestätigst die Gewichte · Automatisch = Meta-Controller übernimmt selbst">
            <select value={c.selection.mode} onChange={(e) => set('selection.mode', e.target.value)}><option value="vorschlag">Vorschlag</option><option value="automatisch">Automatisch</option></select></S>
          <S t="Neubewertung"><select value={c.selection.rhythm} onChange={(e) => set('selection.rhythm', e.target.value)}><option value="taeglich">täglich</option><option value="woechentlich">wöchentlich</option></select></S>
          <S t="Mindestanzahl Trades" h="Bevor eine Strategie nach Leistung gewichtet wird"><input type="number" min={5} value={c.selection.min_trades} onChange={(e) => set('selection.min_trades', Number(e.target.value))} /></S>
          <S t="Mindestdauer (Tage)"><input type="number" min={1} value={c.selection.min_days} onChange={(e) => set('selection.min_days', Number(e.target.value))} /></S>
          <S t="Mindesthaltedauer einer Auswahl (Tage)"><input type="number" min={0} value={c.selection.min_hold_days} onChange={(e) => set('selection.min_hold_days', Number(e.target.value))} /></S>
          <S t="Gebühr je Order (%)" h="Für Risiko- und Backtest-Berechnung"><input type="number" step={0.01} value={c.costs.fee_pct} onChange={(e) => set('costs.fee_pct', Number(e.target.value))} /></S>
          <S t="Slippage (%)"><input type="number" step={0.01} value={c.costs.slippage_pct} onChange={(e) => set('costs.slippage_pct', Number(e.target.value))} /></S>
        </>}
        {tab === 'risiko' && <>
          {Object.entries(meta.risk_fields).map(([k, f]: any) => <S key={k} t={f.label} h={f.help}>
            <input type="number" min={f.min} max={f.max} step={f.step} value={c.risk[k]} onChange={(e) => set('risk.' + k, Number(e.target.value))} /></S>)}
          <S t="Bei erreichtem Limit" h="Offene Positionen halten (mit Stop) oder schließen"><select value={c.risk.on_limit} onChange={(e) => set('risk.on_limit', e.target.value)}><option value="halten">halten</option><option value="schliessen">schließen</option></select></S>
          <S t="Bei Not-Aus"><select value={c.risk.on_emergency} onChange={(e) => set('risk.on_emergency', e.target.value)}><option value="schliessen">alles schließen</option><option value="halten">halten (mit Stop)</option></select></S>
        </>}
        {tab === 'maerkte' && <>
          <p className="muted">Märkte, die der Bot beobachtet und handelt. Kein Hebel, keine Leerverkäufe.</p>
          {meta.markets.map((m: any) => <S key={m.symbol} t={m.symbol} h={m.market + (m.tradable ? '' : ' · nicht handelbar: ' + m.note)}>
            <Switch checked={c.markets.includes(m.symbol)} disabled={!m.tradable} onChange={(v) => set('markets', v ? [...c.markets, m.symbol] : c.markets.filter((x: string) => x !== m.symbol))} /></S>)}
        </>}
        {tab === 'meldungen' && <Meldungen c={c} set={set} />}
        <div className="row" style={{ marginTop: 16 }}>
          <button className="btn primary" disabled={!dirty} onClick={() => save(c)}>Speichern</button>
          <button className="btn" disabled={!dirty} onClick={() => setC(clone(cfg))}>Zurücksetzen</button>
        </div>
      </div>}
      {dialog}
    </>
  )
}

function Meldungen({ c, set }: any) {
  const [perm, setPerm] = useState(typeof Notification !== 'undefined' ? Notification.permission : 'unsupported')
  const enablePush = async () => {
    try {
      if (!('serviceWorker' in navigator) || !('PushManager' in window)) return toast('Push wird hier nicht unterstützt. iPhone: erst „Zum Home-Bildschirm“ hinzufügen und die App von dort öffnen.')
      const { key } = await api('/push/key')
      if (!key) return toast('Push ist auf dem Server noch nicht eingerichtet')
      const reg = await navigator.serviceWorker.register('/sw.js'); await navigator.serviceWorker.ready
      const p = await Notification.requestPermission(); setPerm(p)
      if (p !== 'granted') return toast('Meldungen wurden nicht erlaubt')
      const pad = '='.repeat((4 - (key.length % 4)) % 4), raw = atob((key + pad).replace(/-/g, '+').replace(/_/g, '/'))
      const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: Uint8Array.from(raw, (ch) => ch.charCodeAt(0)) })
      const j = sub.toJSON(); await api('/push/subscribe', { body: { endpoint: j.endpoint, keys: j.keys } })
      toast('Push-Meldungen auf diesem Gerät aktiviert')
    } catch (e: any) { toast(e.message) }
  }
  return <>
    <S t="Push-Meldungen" h="Bei Trades und Warnungen"><Switch checked={c.notifications.push} onChange={(v: boolean) => set('notifications.push', v)} /></S>
    <S t="Dieses Gerät" h={perm === 'granted' ? 'Meldungen erlaubt' : 'Noch nicht aktiviert'}><button className="btn small" onClick={enablePush}>Aktivieren</button></S>
    <S t="Bei Trades"><Switch checked={c.notifications.on_trade} onChange={(v: boolean) => set('notifications.on_trade', v)} /></S>
    <S t="Bei Warnungen" h="Fehler und kritische Meldungen kommen immer"><Switch checked={c.notifications.on_warning} onChange={(v: boolean) => set('notifications.on_warning', v)} /></S>
    <S t="Tagesbericht"><Switch checked={c.notifications.daily_report} onChange={(v: boolean) => set('notifications.daily_report', v)} /></S>
    <S t="Wochenbericht"><Switch checked={c.notifications.weekly_report} onChange={(v: boolean) => set('notifications.weekly_report', v)} /></S>
    <S t="Zweiter Kanal: ntfy-Thema" h="App „ntfy“ installieren und dieses Thema abonnieren (geheim halten, z. B. tb-ab12cd34)">
      <input style={{ textAlign: 'left' }} value={c.notifications.ntfy_topic} onChange={(e) => set('notifications.ntfy_topic', e.target.value.trim())} placeholder="tb-…" /></S>
    <S t="Test" h="Sendet eine Testmeldung über alle Kanäle"><button className="btn small" onClick={async () => { await api('/push/test', { body: {} }); toast('Testmeldung gesendet') }}>Senden</button></S>
  </>
}
