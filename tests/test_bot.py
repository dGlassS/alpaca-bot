from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from bot.config import Limits, Strategy
from bot.risk import DayState, check_entry
from bot.strategy import Bar, Plan, breakout_plan, opening_range, size_plan

NY = ZoneInfo("America/New_York")
OPEN = datetime(2026, 11, 9, 9, 30, tzinfo=NY)


def bars_with_breakout(close_after=101.5):
    bars = [Bar(OPEN + timedelta(minutes=i), 100, 101, 99.5, 100.5) for i in range(15)]
    bars.append(Bar(OPEN + timedelta(minutes=15), 100.8, 101.6, 100.7, close_after))
    return bars


def test_opening_range_needs_15_minutes():
    bars = bars_with_breakout()
    assert opening_range(bars[:15], OPEN, 15) is None
    rng = opening_range(bars, OPEN, 15)
    assert (rng.high, rng.low, rng.mid) == (101, 99.5, 100.25)


def test_breakout_plan_and_sizing():
    now = OPEN + timedelta(minutes=16, seconds=5)
    plan = breakout_plan("AAPL", bars_with_breakout(), OPEN, now, 101.4, Strategy())
    assert plan.entry == 101.5 and plan.stop == 100.25 and plan.target == 104.0
    sized = size_plan(plan, Limits(), equity=100_000, cash=100_000)
    assert sized.qty == 40               # 50 $ / 1.25 de risque par action
    assert sized.max_loss <= 50


def test_no_breakout_when_close_inside_range():
    now = OPEN + timedelta(minutes=16, seconds=5)
    assert breakout_plan("AAPL", bars_with_breakout(100.9), OPEN, now, 100.9, Strategy()) is None


def test_no_chasing():
    now = OPEN + timedelta(minutes=16, seconds=5)
    # dernier prix trop loin au-dessus du range (> high + 0.5 x range)
    assert breakout_plan("AAPL", bars_with_breakout(), OPEN, now, 102.0, Strategy()) is None


def test_size_capped_by_order_size():
    plan = Plan("X", 0, 500.0, 499.9, 500.2)
    assert size_plan(plan, Limits(), 100_000, 100_000).qty == 20  # 10 000 $ / 500


def _ok_plan():
    return Plan("AAPL", 40, 101.5, 100.25, 104.0)


def test_risk_passes():
    v = check_entry(_ok_plan(), DayState(), Limits(), time(10, 0), time(15, 30), 100_000, 100_000)
    assert v.ok, v.reasons


def test_risk_blocks():
    lim = Limits()
    big = Plan("AAPL", 41, 101.5, 100.25, 104.0)
    assert not check_entry(big, DayState(), lim, time(10), time(15, 30), 1e5, 1e5).ok
    assert not check_entry(_ok_plan(), DayState(trades_today=2), lim, time(10), time(15, 30), 1e5, 1e5).ok
    assert not check_entry(_ok_plan(), DayState(pnl_today=-150), lim, time(10), time(15, 30), 1e5, 1e5).ok
    assert not check_entry(_ok_plan(), DayState(risk_used_today=120), lim, time(10), time(15, 30), 1e5, 1e5).ok
    assert not check_entry(_ok_plan(), DayState(), lim, time(9, 40), time(15, 30), 1e5, 1e5).ok
    assert not check_entry(_ok_plan(), DayState(), lim, time(15, 31), time(15, 30), 1e5, 1e5).ok
    assert not check_entry(_ok_plan(), DayState(symbols_today={"AAPL"}), lim, time(10), time(15, 30), 1e5, 1e5).ok
    low_rr = Plan("AAPL", 40, 101.5, 100.25, 102.0)
    assert not check_entry(low_rr, DayState(), lim, time(10), time(15, 30), 1e5, 1e5).ok


def test_report_pairs_entries_and_exits():
    from bot.report import Fill, build_trades, summarize
    t0 = datetime(2026, 11, 9, 10, 0, tzinfo=NY)
    fills = [
        Fill("AAPL", "buy", 40, 101.5, t0, "entree"),
        Fill("AAPL", "sell", 40, 104.0, t0 + timedelta(hours=1), "objectif"),
        Fill("TSLA", "buy", 10, 300.0, t0, "entree"),
        Fill("TSLA", "sell", 10, 296.0, t0 + timedelta(hours=2), "stop"),
        Fill("MSFT", "sell", 5, 400.0, t0, "fermeture"),  # pas une entrée du bot : ignoré
    ]
    trades = build_trades(fills)
    assert [(t.symbol, t.pnl, t.exit_kind) for t in trades] == [("AAPL", 100.0, "objectif"), ("TSLA", -40.0, "stop")]
    s = summarize(trades)
    assert s["pnl_total"] == 60.0 and s["taux_reussite"] == 50.0
