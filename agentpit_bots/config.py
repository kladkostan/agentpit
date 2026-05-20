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
    anchor_pool_size: int = 1  # one anchor MM per market is enough
    # Max bots provisioned at once at bootstrap. Each split is an on-chain tx
    # and the dev API is a single worker, so a thread per bot (30+) overwhelms
    # it and the client times out; keep the in-flight on-chain work bounded.
    provision_concurrency: int = 4

    # --- anchor MM strategy ---------------------------------------------
    mm_half_spread_usd: float = 0.005  # $0.005 → ¢1 spread total
    mm_quote_size_shares: int = 100  # display shares; multiplied by 10^6 raw
    # Refill cadence: at 30s ticks, every 4 ticks = ~2 min. Kept tight so a
    # market drained below the quote size is restocked before a run of fills
    # can strand its SELL quote for long; the refill restores the full
    # per-market target (see anchor_inventory_budget_usd), not a flat top-up.
    mm_rebalance_every_ticks: int = 4
    # Active drift correction: each tick the anchor reads each token's local
    # book and, when its local price has drifted past this tolerance from the
    # Polymarket target, places a taker order that eats the offending resting
    # orders back to the target (SELL when local is too high, BUY when too low).
    # This is what actually pulls the local price to Polymarket and keeps
    # YES+NO≈1; passive quoting alone leaves extreme/skewed markets adrift.
    mm_correction_tolerance_usd: float = 0.02  # only correct drift beyond ¢2
    mm_correction_max_shares: int = 2000  # cap per corrective order

    # --- noise strategy --------------------------------------------------
    # Each noise order rests at distance d from the outcome's anchor mid, drawn
    # UNIFORMLY across the room between the mid and the price bound (0.01/0.99)
    # on its side. Uniform count + size growing in distance gives heavy
    # share-depth in the tails and thin depth at the spread — an inverted-
    # gaussian book that fills evenly out to the edge regardless of mid.
    noise_dist_min_usd: float = 0.005  # min gap from mid — never inside the quote
    # Distance (USD) at which order size saturates: beyond this the far tail
    # plateaus instead of growing without bound, which also caps the largest
    # SELL so it stays within the noise inventory seed.
    noise_dist_max_usd: float = 0.30
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
    # The faucet drip at /register sets initial USDC (1,000,000 apUSD). We
    # don't top up, so this budget is the standing inventory the anchor
    # deploys as complete sets (equal YES+NO), spread evenly across markets:
    # per-market target = anchor_inventory_budget_usd // num_markets. Splitting
    # locks apUSD reversibly (merge returns it), so this is a float, not a
    # spend. Default 500k = half the faucet drip, leaving the other half liquid
    # for fills. This same per-market target drives both bootstrap provisioning
    # and the rebalance refill — a depleted market is topped back up to it
    # rather than to a flat quote size, so the anchor never runs dry mid-drift.
    anchor_inventory_budget_usd: int = 500_000
    # Noise gets a per-market float so its SELL picks can fire. This MUST clear
    # the largest SELL a noise bot can draw — base + per_cent * (max_dist¢) =
    # 5 + 10*30 = 305 shares by default — because the distance distribution
    # peaks at the max and size grows with distance, so most SELLs are large.
    # At the old 100 nearly every SELL tripped the bal < size guard and was
    # dropped, leaving the ask side with only the anchor's lone quote while
    # bids (which need no tokens) stacked deep. 1000 covers ~3 max SELLs before
    # a bot must reacquire via fills; with 30 bots that's deep two-sided depth.
    # Note: noise is seeded once at bootstrap and not refilled (the rebalance
    # tick is anchor-only), so it leans on this seed plus MINT-match fills.
    # Set to 0 to opt out.
    noise_inventory_split_shares: int = 1000


DEFAULT = BotConfig()

SHARES_SCALE = 1_000_000  # raw outcome-token units per display share
PRICE_SCALE = 1_000_000  # USDC micro-units per dollar (price * 10^6)
