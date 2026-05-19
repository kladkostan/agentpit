"""Bot service configuration. Defaults tuned for the v1 dead-book problem.

All knobs live here so operators can tune by editing one file. None of
these are exposed via env vars yet — keep it simple for v1.
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class BotConfig:
    # --- cadence ---------------------------------------------------------
    tick_interval_sec: int = 30
    noise_tick_base_sec: int = 6
    noise_tick_jitter_sec: int = 20

    # --- pool sizing -----------------------------------------------------
    noise_pool_size: int = 30
    anchor_pool_size: int = 1   # one anchor MM per market is enough

    # --- anchor MM strategy ---------------------------------------------
    mm_half_spread_usd: float = 0.005       # $0.005 → ¢1 spread total
    mm_quote_size_shares: int = 100         # display shares; multiplied by 10^6 raw
    mm_rebalance_every_ticks: int = 10
    # Match inventory_split_shares so the first rebalance after bootstrap is a
    # no-op — otherwise we burn one on-chain merge per market just to drop
    # bootstrapped inventory down to the floor without ever trading.
    mm_rebalance_floor_shares: int = 500

    # --- noise strategy --------------------------------------------------
    # Distance d (in USD) of each noise order from the outcome's anchor mid,
    # sampled from a triangular distribution over [min, max] peaked at `mode`.
    # Default mode = max → density ramps from 0 at the spread to peak at the
    # far edge; combined with size growing in distance the book accumulates a
    # fat tail of resting depth far from mid while staying thin near the
    # anchor's tight quote. Drop `mode` toward `min` for a more central peak.
    noise_dist_min_usd: float = 0.005   # never inside the anchor's quote
    noise_dist_max_usd: float = 0.30
    noise_dist_mode_usd: float = 0.30   # peak of the triangular distribution
    # Size grows linearly with distance (in cents): size = base + per_cent * d¢
    noise_size_base_shares: int = 5
    noise_size_per_cent: int = 10

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
    # Anchor gets a deep float so it can quote both sides on every market.
    inventory_split_shares: int = 500
    # Noise gets a small float so its SELL picks can fire — without this its
    # resting BUYs never cross the anchor's SELL and the ask side of every
    # market shows only the anchor's lone quote. Set to 0 to opt out.
    noise_inventory_split_shares: int = 100


DEFAULT = BotConfig()

SHARES_SCALE = 1_000_000   # raw outcome-token units per display share
PRICE_SCALE = 1_000_000    # USDC micro-units per dollar (price * 10^6)
