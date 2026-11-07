import { useState } from 'react'
import { api, useApi } from './api'
import { useApp } from './App'
import { Dialog, toast } from './ui'

/** Einstellungen ändern: erst Vorschau mit allen Änderungen, dann ausdrücklich bestätigen (PDF: Änderungen nur nach Bestätigung). */
export function useConfig() {
  const { data, reload } = useApi('/config', 0)
  const { reloadDash } = useApp()
  const [preview, setPreview] = useState<{ cfg: any; changes: string[]; warnings: string[] } | null>(null)
  const [busy, setBusy] = useState(false)
  const save = async (cfg: any) => {
    try {
      const r = await api('/config', { body: { config: cfg, base_version_id: data.version_id } })
      if (!r.changes.length) return toast('Keine Änderungen')
      setPreview({ cfg, changes: r.changes, warnings: r.warnings })
    } catch (e: any) { toast(e.message) }
  }
  const confirm = async () => {
    if (!preview) return
    setBusy(true)
    try {
      await api('/config', { body: { config: preview.cfg, base_version_id: data.version_id, confirm: true } })
      toast('Gespeichert'); setPreview(null); await reload(); reloadDash()
    } catch (e: any) { toast(e.message); if (e.status === 409) { setPreview(null); reload() } } finally { setBusy(false) }
  }
  const dialog = preview && (
    <Dialog title="Änderungen bestätigen" onClose={() => setPreview(null)}>
      {preview.warnings.map((w) => <div key={w} className="note">{w}</div>)}
      <p className="muted">Folgende Einstellungen werden geändert:</p>
      <div className="diff">{preview.changes.map((c) => <div key={c}>{c}</div>)}</div>
      <div className="row" style={{ justifyContent: 'flex-end', marginTop: 14 }}>
        <button className="btn" onClick={() => setPreview(null)}>Abbrechen</button>
        <button className="btn primary" disabled={busy} onClick={confirm}>Bestätigen und speichern</button>
      </div>
    </Dialog>
  )
  return { meta: data, cfg: data?.config, save, dialog, reload }
}

export const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x))
