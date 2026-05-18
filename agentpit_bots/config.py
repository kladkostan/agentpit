"""Bot service configuration. Defaults tuned for the v1 dead-book problem.

All knobs live here so operators can tune by editing one file. None of
these are exposed via env vars yet — keep it simple for v1.
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class BotConfig:
    # --- cadence ---------------------------------------------------------
    tick_interval_sec: int = 30
    noise_tick_base_sec: int = 60
    noise_tick_jitter_sec: int = 20

    # --- pool sizing -----------------------------------------------------
    noise_pool_size: int = 3
    anchor_pool_size: int = 1   # one anchor MM per market is enough

    # --- anchor MM strategy ---------------------------------------------
    mm_half_spread_usd: float = 0.005       # $0.005 → ¢1 spread total
    mm_quote_size_shares: int = 100         # display shares; multiplied by 10^6 raw
    mm_rebalance_every_ticks: int = 10
    mm_rebalance_floor_shares: int = 200

    # --- noise strategy --------------------------------------------------
    noise_min_size_shares: int = 5
    noise_max_size_shares: int = 50
    noise_aggressive_prob: float = 0.3

    # --- oracle ----------------------------------------------------------
    oracle_stale_after_sec: int = 300

    # --- service ---------------------------------------------------------
    base_url: str = "http://localhost:8000"
    polymarket_clob_host: str = "https://clob.polymarket.com"
    admin_token: str = "dev-admin-token"
    creds_path: str = "agentpit_bots/creds.json"

    # --- per-market on/off ----------------------------------------------
    disabled_market_ids: frozenset[int] = field(default_factory=frozenset)

    # --- starting capital ----------------------------------------------
    # The faucet drip at /register sets initial USDC. We don't top up.
    inventory_split_shares: int = 500


DEFAULT = BotConfig()

SHARES_SCALE = 1_000_000   # raw outcome-token units per display share
