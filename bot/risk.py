"""Garde-fou : chaque entrée est vérifiée ici avant d'être envoyée. Fonction pure."""

from dataclasses import dataclass, field
from datetime import time
from typing import List

from .config import Limits
from .strategy import Plan


@dataclass
class DayState:
    trades_today: int = 0
    risk_used_today: float = 0.0     # somme des pertes max (aux stops) des entrées du jour
    pnl_today: float = 0.0           # equity - equity de la veille
    symbols_today: set = field(default_factory=set)
    open_symbols: set = field(default_factory=set)


@dataclass
class Verdict:
    ok: bool
    reasons: List[str]


def check_entry(plan: Plan, day: DayState, limits: Limits, now_ny: time,
                entries_until: time, equity: float, cash: float) -> Verdict:
    r: List[str] = []
    if plan.qty < 1:
        r.append("quantité nulle (risque ou taille trop grands)")
    if plan.stop >= plan.entry:
        r.append("stop au-dessus de l'entrée")
    if plan.target <= plan.entry:
        r.append("objectif sous l'entrée")
    if plan.qty >= 1 and plan.stop < plan.entry:
        if plan.max_loss > limits.max_loss_per_trade_usd + 1e-9:
            r.append(f"perte max {plan.max_loss:.2f} $ > {limits.max_loss_per_trade_usd} $")
        if plan.reward_risk < limits.min_reward_risk - 1e-9:
            r.append(f"reward:risk {plan.reward_risk:.2f} < {limits.min_reward_risk}")
        if day.risk_used_today + plan.max_loss > limits.max_daily_loss_usd + 1e-9:
            r.append("dépasserait la perte max du jour")
        if plan.notional < limits.min_order_usd:
            r.append(f"ordre trop petit ({plan.notional:.0f} $)")
        if plan.notional > limits.max_order_usd + 1e-9:
            r.append(f"ordre trop gros ({plan.notional:.0f} $)")
        if plan.notional > limits.max_position_pct * equity + 1e-9:
            r.append("position > 10 % du compte")
        if plan.notional > cash - limits.cash_buffer_usd:
            r.append("pas assez de cash (pas de marge)")
    if day.pnl_today <= -limits.max_daily_loss_usd:
        r.append("perte du jour atteinte")
    if day.trades_today >= limits.max_trades_per_day:
        r.append("nombre max de trades du jour atteint")
    if plan.symbol in day.symbols_today or plan.symbol in day.open_symbols:
        r.append("déjà tradé ou en position aujourd'hui")
    if not (limits.no_entries_before <= now_ny <= entries_until):
        r.append("hors de la fenêtre d'entrée")
    return Verdict(ok=not r, reasons=r)
