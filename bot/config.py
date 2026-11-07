"""Réglages du bot. Les limites de risque sont ici, en un seul endroit."""

import os
from dataclasses import dataclass, field
from datetime import time


@dataclass(frozen=True)
class Limits:
    # Mêmes limites que le skill trader-risk.
    max_loss_per_trade_usd: float = 50.0
    max_daily_loss_usd: float = 150.0
    max_trades_per_day: int = 2
    min_reward_risk: float = 1.5
    min_order_usd: float = 100.0
    max_order_usd: float = 10_000.0
    max_position_pct: float = 0.10
    cash_buffer_usd: float = 1_000.0
    # Heures de New York.
    no_entries_before: time = time(9, 45)
    no_entries_after: time = time(15, 30)
    flatten_at: time = time(15, 55)


@dataclass(frozen=True)
class Strategy:
    # Cassure du range d'ouverture (Opening Range Breakout), achat seulement.
    watchlist: tuple = (
        "SPY", "QQQ", "AAPL", "MSFT", "NVDA",
        "AMD", "TSLA", "META", "AMZN", "GOOGL",
    )
    opening_range_minutes: int = 15
    target_r: float = 2.0            # objectif = 2 x le risque
    min_range_pct: float = 0.002     # range d'ouverture trop petit = bruit
    max_range_pct: float = 0.03      # range trop grand = stop trop loin
    max_chase_fraction: float = 0.5  # ne pas acheter si déjà trop au-dessus du range


@dataclass(frozen=True)
class Settings:
    api_key: str = field(default_factory=lambda: os.environ.get("ALPACA_API_KEY", ""))
    secret_key: str = field(default_factory=lambda: os.environ.get("ALPACA_SECRET_KEY", ""))
    poll_seconds: int = int(os.environ.get("BOT_POLL_SECONDS", "20"))
    log_dir: str = os.environ.get("BOT_LOG_DIR", "logs")
    stop_file: str = os.environ.get("BOT_STOP_FILE", "STOP")
    stop_watchlist: str = "STOP"   # watchlist Alpaca qui sert de bouton d'arrêt
    order_prefix: str = "orb-"
    limits: Limits = field(default_factory=Limits)
    strategy: Strategy = field(default_factory=Strategy)
