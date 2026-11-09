"""Boucle principale du bot. Compte Paper uniquement (paper=True est écrit en dur)."""

import json
import logging
import os
import time as _time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from alpaca.data.enums import DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, StockLatestTradeRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderClass, OrderSide, OrderStatus, QueryOrderStatus, TimeInForce
from alpaca.trading.requests import (
    GetOrdersRequest, MarketOrderRequest, StopLossRequest, TakeProfitRequest,
)

from .config import Settings
from .risk import DayState, check_entry
from .strategy import Bar, breakout_plan, size_plan

NY = ZoneInfo("America/New_York")
log = logging.getLogger("bot")
DEAD = {OrderStatus.CANCELED, OrderStatus.REJECTED, OrderStatus.EXPIRED}


class Bot:
    def __init__(self, s: Settings):
        if not s.api_key or not s.secret_key:
            raise SystemExit("ALPACA_API_KEY et ALPACA_SECRET_KEY doivent être définis.")
        self.s = s
        self.trading = TradingClient(s.api_key, s.secret_key, paper=True)
        self.data = StockHistoricalDataClient(s.api_key, s.secret_key)
        Path(s.log_dir).mkdir(parents=True, exist_ok=True)
        self.journal = Path(s.log_dir) / "journal.jsonl"
        self._flattened_for = None
        self._stopped_logged = False

    # ---------- journal ----------
    def record(self, event: str, **data):
        line = {"time": datetime.now(NY).isoformat(timespec="seconds"), "event": event, **data}
        with self.journal.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
        log.info("%s %s", event, data)

    # ---------- état du jour, relu depuis Alpaca (survit aux redémarrages) ----------
    def day_state(self, session_open: datetime) -> DayState:
        acct = self.trading.get_account()
        orders = self.trading.get_orders(GetOrdersRequest(
            status=QueryOrderStatus.ALL, after=session_open, limit=500))
        st = DayState(pnl_today=float(acct.equity) - float(acct.last_equity))
        for o in orders:
            cid = o.client_order_id or ""
            if not cid.startswith(self.s.order_prefix) or o.status in DEAD:
                continue
            st.trades_today += 1
            st.symbols_today.add(o.symbol)
            try:
                st.risk_used_today += int(cid.rsplit("-", 1)[1]) / 100
            except (IndexError, ValueError):
                st.risk_used_today += self.s.limits.max_loss_per_trade_usd
        st.open_symbols = {p.symbol for p in self.trading.get_all_positions()}
        return st

    def stop_requested(self) -> bool:
        if os.path.exists(self.s.stop_file):
            return True
        try:
            return any(w.name.strip().upper() == self.s.stop_watchlist
                       for w in self.trading.get_watchlists())
        except Exception:
            log.exception("lecture des watchlists impossible")
            return False

    def flatten(self, why: str):
        positions = self.trading.get_all_positions()
        open_orders = self.trading.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN))
        if positions or open_orders:
            self.trading.close_all_positions(cancel_orders=True)
            self.record("flatten", reason=why, positions=[p.symbol for p in positions])

    def bars(self, symbols, start: datetime) -> dict:
        req = StockBarsRequest(symbol_or_symbols=list(symbols), timeframe=TimeFrame.Minute,
                               start=start, feed=DataFeed.IEX)
        out = {}
        for sym, rows in self.data.get_stock_bars(req).data.items():
            out[sym] = [Bar(r.timestamp.astimezone(NY), r.open, r.high, r.low, r.close) for r in rows]
        return out

    def last_prices(self, symbols) -> dict:
        req = StockLatestTradeRequest(symbol_or_symbols=list(symbols), feed=DataFeed.IEX)
        return {k: float(v.price) for k, v in self.data.get_stock_latest_trade(req).items()}

    # ---------- un tour de boucle ----------
    def tick(self) -> int:
        lim, strat = self.s.limits, self.s.strategy
        clock = self.trading.get_clock()
        if not clock.is_open:
            return 60
        now = clock.timestamp.astimezone(NY)
        session_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
        close = clock.next_close.astimezone(NY)
        flatten_at = min(now.replace(hour=lim.flatten_at.hour, minute=lim.flatten_at.minute, second=0,
                                     microsecond=0), close - timedelta(minutes=5))
        entries_until = min(lim.no_entries_after, (close - timedelta(minutes=30)).time())

        if self.stop_requested():
            if not self._stopped_logged:
                self.record("stop_demande", detail="fichier STOP ou watchlist STOP")
                self._stopped_logged = True
            self.flatten("arrêt demandé")
            return self.s.poll_seconds
        self._stopped_logged = False

        if now >= flatten_at:
            if self._flattened_for != now.date():
                self.flatten("fin de séance")
                self._flattened_for = now.date()
            return self.s.poll_seconds

        if not (lim.no_entries_before <= now.time() <= entries_until):
            return self.s.poll_seconds

        day = self.day_state(session_open)
        if day.trades_today >= lim.max_trades_per_day or day.pnl_today <= -lim.max_daily_loss_usd:
            return self.s.poll_seconds

        candidates = [s for s in strat.watchlist if s not in day.symbols_today | day.open_symbols]
        if not candidates:
            return self.s.poll_seconds
        all_bars = self.bars(candidates, session_open)
        prices = self.last_prices(candidates)
        acct = self.trading.get_account()
        equity, cash = float(acct.equity), float(acct.cash)

        for sym in candidates:
            plan = breakout_plan(sym, all_bars.get(sym, []), session_open, now,
                                 prices.get(sym, 0.0), strat)
            if plan is None:
                continue
            plan = size_plan(plan, lim, equity, cash)
            verdict = check_entry(plan, day, lim, now.time(), entries_until, equity, cash)
            info = dict(symbol=sym, qty=plan.qty, entry=plan.entry, stop=plan.stop,
                        target=plan.target, max_loss=round(plan.max_loss, 2),
                        reward_risk=round(plan.reward_risk, 2))
            if not verdict.ok:
                self.record("bloque", **info, raisons=verdict.reasons)
                day.symbols_today.add(sym)  # on ne réessaie pas ce symbole aujourd'hui
                continue
            cid = f"{self.s.order_prefix}{now:%Y%m%d}-{sym}-{int(round(plan.max_loss * 100))}"
            order = self.trading.submit_order(MarketOrderRequest(
                symbol=sym, qty=plan.qty, side=OrderSide.BUY, time_in_force=TimeInForce.GTC,
                order_class=OrderClass.BRACKET, client_order_id=cid,
                take_profit=TakeProfitRequest(limit_price=plan.target),
                stop_loss=StopLossRequest(stop_price=plan.stop)))
            self.record("achat", **info, order_id=str(order.id))
            day.trades_today += 1
            day.risk_used_today += plan.max_loss
            day.symbols_today.add(sym)
            cash -= plan.notional
            if day.trades_today >= lim.max_trades_per_day:
                break
        return self.s.poll_seconds

    def run(self, max_minutes: float = 0):
        """Tourne en boucle. Avec max_minutes > 0, s'arrête après ce temps (GitHub Actions)."""
        deadline = _time.monotonic() + max_minutes * 60 if max_minutes > 0 else None
        if deadline is not None:
            clock = self.trading.get_clock()
            if not clock.is_open and clock.next_open - clock.timestamp > timedelta(minutes=max_minutes):
                log.info("marché fermé jusqu'à %s : rien à faire pour ce créneau", clock.next_open)
                return
        self.record("demarrage", mode="paper", watchlist=list(self.s.strategy.watchlist))
        while deadline is None or _time.monotonic() < deadline:
            try:
                wait = self.tick()
            except Exception:
                log.exception("erreur pendant le tour de boucle")
                wait = 60
            if deadline is not None:
                wait = min(wait, max(0, deadline - _time.monotonic()))
            _time.sleep(wait)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    Bot(Settings()).run(max_minutes=float(os.environ.get("BOT_MAX_MINUTES", "0")))


if __name__ == "__main__":
    main()
