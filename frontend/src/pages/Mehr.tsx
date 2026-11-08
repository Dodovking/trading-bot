import { useApp } from '../App'
import { Icon } from '../ui'

export default function Mehr() {
  const { me } = useApp()
  const items = [['verlauf', 'Verlauf'], ['ertrag', 'Ertragsmodule'], ['risiko', 'Risiko'], ['backtest', 'Backtest'], ['konto', 'Konto'], ...(me.role === 'admin' ? [['benutzer', 'Benutzer']] : [])]
  return <>
    <div className="head"><h1>Mehr</h1></div>
    <div className="card nav">{items.map(([id, l]) => <a key={id} href={'#/' + id} style={{ padding: '14px 8px' }}><Icon name={id} />{l}</a>)}</div>
  </>
}
