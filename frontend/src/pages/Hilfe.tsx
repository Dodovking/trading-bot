import { useState } from 'react'
import { Dialog, Icon } from '../ui'

const STEPS: [string, string, string][] = [
  ['strategien', 'Willkommen!', 'Das ist dein Trading-Bot. Er beobachtet rund um die Uhr Kurse von Kryptowährungen (z. B. Bitcoin) und Aktien (z. B. Apple) und kauft oder verkauft nach festen Regeln – auch wenn dein PC oder iPhone aus ist.'],
  ['ertrag', 'Erst mal nur Spielgeld', 'Der Bot startet im Paper-Modus: Er handelt mit 10.000 € Spielgeld zu echten Kursen. Du kannst nichts verlieren. Echtes Geld kommt nur ins Spiel, wenn du selbst ein Konto verbindest und ausdrücklich umstellst.'],
  ['dashboard', 'Dashboard', 'Hier siehst du auf einen Blick: Läuft der Bot? Wie viel Gewinn oder Verlust? Welche Käufe sind gerade offen? Mit „Pausieren“ und „Stoppen“ hältst du ihn jederzeit an.'],
  ['einstellungen', 'Strategien', 'Strategien sind die „Rezepte“, nach denen der Bot kauft – z. B. „kaufen, wenn ein Kurs dauerhaft steigt“. Er probiert alle im Hintergrund aus und schlägt die passenden vor. Du musst hier nichts einstellen.'],
  ['risiko', 'Risiko & Sicherheit', 'Jeder Kauf wird vorher geprüft: höchstens 1 % Risiko pro Kauf, immer mit Stop-Loss (automatischer Verkauf bei Verlust), Pause ab 3 % Tagesverlust. Kein Hebel, keine Wetten auf fallende Kurse.'],
  ['backtest', 'Kryptos & Aktien', 'Unter Einstellungen → Märkte schaltest du ein, was der Bot handeln darf: Bitcoin, Ethereum, XRP, Dogecoin & Co. sowie Aktien wie Apple, Nvidia oder den S&P-500-ETF. Für Aktienkurse brauchst du ein kostenloses Alpaca-Konto (Einstellungen → Konto & Börse → Alpaca). Aktien handelt er nur zu US-Börsenzeiten (Mo–Fr 15:30–22:00 Uhr).'],
  ['verlauf', 'Geduld', 'Der Bot kauft nicht ständig. Fallen die Kurse oder ist die Lage unklar, wartet er – das ist Absicht. Unter „Verlauf“ steht bei jeder Entscheidung, warum er gekauft hat oder nicht.'],
  ['hilfe', 'Hilfe auf jeder Seite', 'Oben rechts findest du auf jeder Seite ein „?“ mit einer kurzen Erklärung. Diese Einführung kannst du unter „Konto“ jederzeit wieder ansehen. Viel Spaß!'],
]

const HELP: Record<string, [string, string[]]> = {
  dashboard: ['Dashboard', ['Oben siehst du den Zustand des Bots (z. B. „Bot läuft“) und ob gerade Spielgeld (Paper) oder Echtgeld genutzt wird.',
    'Kontowert und Gewinn/Verlust: Wie viel dein Konto gerade wert ist und wie viel heute dazugekommen oder weggefallen ist.',
    'Offene Positionen: Was der Bot gerade gekauft hat und hält. Jede Position hat einen Stop-Loss – fällt der Kurs darunter, verkauft er automatisch.',
    'Pausieren: keine neuen Käufe, offene Positionen bleiben geschützt. Stoppen: Bot hält an. Not-Aus: sofort alles anhalten.']],
  strategien: ['Strategien', ['Eine Strategie ist ein festes Regelwerk, wann gekauft und verkauft wird – z. B. Trendfolge: kaufen, wenn der Kurs dauerhaft steigt.',
    'Alle Strategien laufen im „Schattenbetrieb“ mit: Der Bot rechnet aus, wie gut sie wären, ohne echt zu handeln.',
    'Der Meta-Controller schlägt anhand dieser Ergebnisse und der Marktlage vor, welche Strategien wie viel Budget bekommen. Erscheint „Neue Strategieauswahl vorgeschlagen“, kannst du sie ansehen und übernehmen.',
    'Gesperrte Strategien brauchen Hebel, Leerverkäufe oder Ähnliches – das ist in dieser Version bewusst ausgeschlossen.']],
  ertrag: ['Ertragsmodule', ['Zusätzliche Wege neben dem Traden, z. B. ein Sparplan (regelmäßig einen festen Betrag kaufen) oder Rebalancing (Zielgewichte wiederherstellen).',
    'Auch Module laufen über dieselbe Risikoprüfung und denselben Not-Aus.']],
  risiko: ['Risiko', ['Hier siehst du, wie nah der Bot an seinen Sicherheitsgrenzen ist – z. B. Tagesverlust, Verlustserie oder maximale Anzahl offener Käufe.',
    'Ist ein Balken voll, macht der Bot automatisch Pause. Das schützt dein Konto.',
    'Die Grenzen änderst du unter Einstellungen → Risiko.']],
  verlauf: ['Verlauf', ['Alles, was der Bot gekauft und verkauft hat – mit Preis, Gewinn/Verlust und Begründung.',
    'Unter „Signale“ siehst du auch, warum er etwas NICHT gekauft hat (z. B. „Abwärtstrend“ oder „US-Börse geschlossen“).',
    'Mit dem Export bekommst du eine CSV-Datei, z. B. für die Steuer.']],
  backtest: ['Backtest', ['Testet eine Strategie mit Kursen aus der Vergangenheit: „Was wäre passiert, wenn der Bot in den letzten 2 Jahren so gehandelt hätte?“',
    'Zum Vergleich steht „Kaufen und Halten“ daneben. Vergangene Ergebnisse sind keine Garantie für die Zukunft.']],
  einstellungen: ['Einstellungen', ['Strategie: Modus (nur Signale, halbautomatisch, automatisch) und Spielgeld- oder Echtgeld-Konto.',
    'Risiko: Wie viel pro Kauf riskiert werden darf und wann der Bot Pause macht.',
    'Märkte: Welche Kryptos und Aktien der Bot handeln darf. Aktien brauchen ein verbundenes Alpaca-Konto.',
    'Konto & Börse: Anbieter verbinden (Anleitung bei jedem Anbieter). Vor dem Speichern zeigt die App immer an, was sich ändert.']],
  konto: ['Konto', ['Dein Benutzerkonto: Passwort, Zwei-Faktor-Anmeldung, angemeldete Geräte und App-Installation für iPhone, Windows und Mac.']],
  benutzer: ['Benutzer', ['Nur für Admins: weitere Personen einladen, Rollen vergeben und deine Anbieterdaten für AGB/Impressum pflegen.']],
  mehr: ['Mehr', ['Weitere Bereiche der App, die nicht in die untere Leiste passen.']],
}

export const introKey = (uid: number) => `tb-intro-v1-${uid}`

export function Intro({ onClose }: { onClose: () => void }) {
  const [i, setI] = useState(0)
  const [icon, title, text] = STEPS[i]
  const last = i === STEPS.length - 1
  return <Dialog title="Einführung" onClose={onClose}>
    <div style={{ textAlign: 'center', padding: '6px 4px 2px' }}>
      <div className="introicon"><Icon name={icon} /></div>
      <h2 style={{ margin: '10px 0 8px' }}>{title}</h2>
      <p style={{ fontSize: 15.5, minHeight: 96 }}>{text}</p>
      <div className="dots" style={{ display: 'flex', gap: 6, justifyContent: 'center', margin: '8px 0 16px' }}>
        {STEPS.map((_, k) => <span key={k} onClick={() => setI(k)} style={{ width: 8, height: 8, borderRadius: 4, cursor: 'pointer', background: k === i ? 'var(--green)' : 'var(--line)' }} />)}
      </div>
    </div>
    <div className="row between">
      {last ? <span /> : <button className="btn ghost" onClick={onClose}>Überspringen</button>}
      <div className="row">
        {i > 0 && <button className="btn" onClick={() => setI(i - 1)}>Zurück</button>}
        <button className="btn primary" onClick={() => (last ? onClose() : setI(i + 1))}>{last ? 'Los geht’s' : 'Weiter'}</button>
      </div>
    </div>
  </Dialog>
}

export function HelpButton({ page, onIntro }: { page: string; onIntro: () => void }) {
  const [open, setOpen] = useState(false)
  const h = HELP[page] || HELP.dashboard
  return <>
    <button className="helpbtn" aria-label="Hilfe zu dieser Seite" title="Hilfe" onClick={() => setOpen(true)}>?</button>
    {open && <Dialog title={'Hilfe: ' + h[0]} onClose={() => setOpen(false)}>
      <ul style={{ paddingLeft: 18, margin: '0 0 14px' }}>{h[1].map((t) => <li key={t} style={{ marginBottom: 8 }}>{t}</li>)}</ul>
      <div className="row between"><button className="btn" onClick={() => { setOpen(false); onIntro() }}>Einführung ansehen</button>
        <button className="btn primary" onClick={() => setOpen(false)}>Verstanden</button></div>
    </Dialog>}
  </>
}
