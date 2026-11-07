"""Stratégie : cassure du range d'ouverture (ORB). Fonctions pures, testables sans Alpaca."""

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Sequence

from .config import Limits, Strategy


@dataclass(frozen=True)
class Bar:
    ts: datetime  # début de la bougie, heure de New York
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class OpeningRange:
    high: float
    low: float

    @property
    def mid(self) -> float:
        return (self.high + self.low) / 2

    @property
    def size(self) -> float:
        return self.high - self.low


@dataclass(frozen=True)
class Plan:
    symbol: str
    qty: int
    entry: float
    stop: float
    target: float

    @property
    def risk_per_share(self) -> float:
        return self.entry - self.stop

    @property
    def max_loss(self) -> float:
        return self.qty * self.risk_per_share

    @property
    def reward_risk(self) -> float:
        return (self.target - self.entry) / self.risk_per_share

    @property
    def notional(self) -> float:
        return self.qty * self.entry


def opening_range(bars: Sequence[Bar], session_open: datetime, minutes: int) -> Optional[OpeningRange]:
    """Plus haut / plus bas des `minutes` premières minutes. None si le range n'est pas terminé."""
    end = session_open + timedelta(minutes=minutes)
    inside = [b for b in bars if session_open <= b.ts < end]
    if not inside or not any(b.ts >= end for b in bars):
        return None
    return OpeningRange(high=max(b.high for b in inside), low=min(b.low for b in inside))


def breakout_plan(
    symbol: str,
    bars: Sequence[Bar],
    session_open: datetime,
    now: datetime,
    last_price: float,
    strat: Strategy,
) -> Optional[Plan]:
    """Renvoie un plan (quantité à 0) si la dernière bougie terminée casse le range. Sinon None."""
    rng = opening_range(bars, session_open, strat.opening_range_minutes)
    if rng is None or rng.low <= 0:
        return None
    pct = rng.size / rng.mid
    if pct < strat.min_range_pct or pct > strat.max_range_pct:
        return None
    done = [b for b in bars if b.ts + timedelta(minutes=1) <= now]
    if not done:
        return None
    last = done[-1]
    if last.close <= rng.high:
        return None
    # On mesure le risque depuis le prix le plus haut entre la clôture et le dernier prix.
    entry = max(last.close, last_price)
    if entry > rng.high + strat.max_chase_fraction * rng.size:
        return None
    stop = round(rng.mid, 2)
    risk = entry - stop
    if risk <= 0:
        return None
    target = round(entry + strat.target_r * risk, 2)
    return Plan(symbol=symbol, qty=0, entry=round(entry, 2), stop=stop, target=target)


def size_plan(plan: Plan, limits: Limits, equity: float, cash: float) -> Plan:
    """Calcule le nombre d'actions selon le risque max, la taille max et le cash disponible."""
    risk = plan.risk_per_share
    by_risk = math.floor(limits.max_loss_per_trade_usd / risk) if risk > 0 else 0
    cap = min(limits.max_order_usd, limits.max_position_pct * equity, cash - limits.cash_buffer_usd)
    by_size = math.floor(cap / plan.entry) if cap > 0 else 0
    qty = max(0, min(by_risk, by_size))
    return Plan(plan.symbol, qty, plan.entry, plan.stop, plan.target)
