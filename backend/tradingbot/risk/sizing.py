"""Positionsgröße (Abschnitt 4.2): Menge = (Kontowert × Risiko je Trade) ÷ |Einstieg − Stop|."""
from __future__ import annotations

from decimal import Decimal

from ..data.quality import round_step


def position_size(equity: Decimal, risk_pct: Decimal, entry: Decimal, stop: Decimal, step: Decimal,
                  slippage_pct: Decimal = Decimal(0)) -> Decimal:
    """Slippage-Puffer: Einstieg wird ungünstiger, Stop-Ausführung ebenfalls angenommen."""
    slip = Decimal(str(slippage_pct)) / 100
    eff_entry = entry * (1 + slip)
    eff_stop = stop * (1 - slip)
    dist = abs(eff_entry - eff_stop)
    if dist <= 0:
        return Decimal(0)
    qty = equity * Decimal(str(risk_pct)) / 100 / dist
    return round_step(qty, step)
