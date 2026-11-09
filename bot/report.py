"""Rapport de la semaine, construit à partir des ordres réels du compte Alpaca Paper."""

import json
import os
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")


@dataclass
class Fill:
    symbol: str
    side: str        # "buy" ou "sell"
    qty: float
    price: float
    time: datetime   # heure de New York
    kind: str        # "entree", "objectif", "stop", "fermeture"


@dataclass
class Trade:
    symbol: str
    day: str
    qty: float
    entry: float
    exit: Optional[float]
    pnl: Optional[float]
    exit_kind: str


def build_trades(fills: List[Fill]) -> List[Trade]:
    """Regroupe les exécutions par action et par jour : une entrée du bot = un trade."""
    groups = defaultdict(list)
    for f in fills:
        groups[(f.symbol, f.time.date().isoformat())].append(f)
    trades = []
    for (sym, day), fs in sorted(groups.items(), key=lambda kv: kv[0][1]):
        buys = [f for f in fs if f.side == "buy" and f.kind == "entree"]
        if not buys:
            continue
        sells = [f for f in fs if f.side == "sell"]
        qty = sum(f.qty for f in buys)
        entry = sum(f.qty * f.price for f in buys) / qty
        if not sells:
            trades.append(Trade(sym, day, qty, round(entry, 2), None, None, "encore ouvert"))
            continue
        sold = sum(f.qty for f in sells)
        exit_ = sum(f.qty * f.price for f in sells) / sold
        last = max(sells, key=lambda f: f.time)
        pnl = sum(f.qty * f.price for f in sells) - entry * sold
        trades.append(Trade(sym, day, qty, round(entry, 2), round(exit_, 2), round(pnl, 2), last.kind))
    return trades


def summarize(trades: List[Trade]) -> dict:
    closed = [t for t in trades if t.pnl is not None]
    wins = [t.pnl for t in closed if t.pnl > 0]
    losses = [t.pnl for t in closed if t.pnl <= 0]
    return {
        "trades": len(trades),
        "fermes": len(closed),
        "gagnants": len(wins),
        "perdants": len(losses),
        "taux_reussite": round(100 * len(wins) / len(closed), 1) if closed else None,
        "pnl_total": round(sum(t.pnl for t in closed), 2),
        "gain_moyen": round(sum(wins) / len(wins), 2) if wins else None,
        "perte_moyenne": round(sum(losses) / len(losses), 2) if losses else None,
        "meilleur": max((t.pnl for t in closed), default=None),
        "pire": min((t.pnl for t in closed), default=None),
    }


def journal_counts(path: Path, since: datetime) -> dict:
    counts = defaultdict(int)
    if not path.exists():
        return counts
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(line)
            if datetime.fromisoformat(e["time"]) >= since:
                counts[e["event"]] += 1
        except (ValueError, KeyError):
            continue
    return counts


def render(week_start: datetime, trades: List[Trade], s: dict, eq_start, eq_end, journal: dict) -> str:
    out = [f"# Rapport de la semaine du {week_start:%d/%m/%Y} (Alpaca Paper)", ""]
    if eq_start is not None and eq_end is not None:
        out.append(f"- Valeur du compte : {eq_start:,.2f} $ -> {eq_end:,.2f} $ ({eq_end - eq_start:+,.2f} $)")
    out += [
        f"- Trades : {s['trades']} (gagnants {s['gagnants']}, perdants {s['perdants']})",
        f"- Taux de réussite : {s['taux_reussite']} %" if s["taux_reussite"] is not None else "- Taux de réussite : -",
        f"- Résultat des trades : {s['pnl_total']:+,.2f} $",
        f"- Gain moyen : {s['gain_moyen']} $ / perte moyenne : {s['perte_moyenne']} $",
        f"- Meilleur trade : {s['meilleur']} $ / pire trade : {s['pire']} $",
        f"- Signaux bloqués par les limites : {journal.get('bloque', 0)}"
        f" / arrêts d'urgence : {journal.get('stop_demande', 0)}",
        "",
        "| Jour | Action | Qté | Entrée | Sortie | Résultat | Sortie par |",
        "|---|---|---|---|---|---|---|",
    ]
    for t in trades:
        out.append(f"| {t.day} | {t.symbol} | {t.qty:g} | {t.entry} | {t.exit if t.exit is not None else '-'} "
                   f"| {f'{t.pnl:+.2f} $' if t.pnl is not None else '-'} | {t.exit_kind} |")
    if not trades:
        out.append("| - | aucun trade cette semaine | | | | | |")
    return "\n".join(out) + "\n"


def fetch_fills(client, since: datetime, prefix: str) -> List[Fill]:
    from alpaca.trading.enums import QueryOrderStatus
    from alpaca.trading.requests import GetOrdersRequest
    orders = client.get_orders(GetOrdersRequest(status=QueryOrderStatus.CLOSED, after=since,
                                                limit=500, nested=True))
    fills = []

    def add(o, kind):
        if o.filled_at and float(o.filled_qty or 0) > 0:
            fills.append(Fill(o.symbol, o.side.value, float(o.filled_qty), float(o.filled_avg_price),
                              o.filled_at.astimezone(NY), kind))

    for o in orders:
        if (o.client_order_id or "").startswith(prefix):
            add(o, "entree")
            for leg in o.legs or []:
                add(leg, "objectif" if leg.order_type.value == "limit" else "stop")
        elif o.side.value == "sell":
            add(o, "fermeture")
    return fills


def main():
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import GetPortfolioHistoryRequest
    from .config import Settings

    s = Settings()
    client = TradingClient(s.api_key, s.secret_key, paper=True)
    now = datetime.now(NY)
    week_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    trades = build_trades(fetch_fills(client, week_start, s.order_prefix))
    hist = client.get_portfolio_history(GetPortfolioHistoryRequest(period="1W", timeframe="1D"))
    eq = [e for e in (hist.equity or []) if e]
    journal = journal_counts(Path(s.log_dir) / "journal.jsonl", week_start)
    text = render(week_start, trades, summarize(trades), eq[0] if eq else None, eq[-1] if eq else None, journal)
    out_dir = Path(os.environ.get("BOT_REPORT_DIR", "reports"))
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{week_start:%Y-%m-%d}.md").write_text(text, encoding="utf-8")
    sys.stdout.write(text)


if __name__ == "__main__":
    main()
