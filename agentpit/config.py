from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        populate_by_name=True,
    )

    database_url: str = Field(
        default="postgresql:///agentpit",
        validation_alias="AGENTPIT_DATABASE_URL",
    )
    # Pool floor. 2 keeps warm connections in prod; tests set 0 so the many
    # short-lived create_app() pools don't each pin idle connections.
    pool_min_size: int = Field(default=2, validation_alias="AGENTPIT_POOL_MIN_SIZE")
    pool_max_idle: float = Field(
        default=600.0, validation_alias="AGENTPIT_POOL_MAX_IDLE"
    )
    sync_enabled: bool = Field(default=False, validation_alias="SYNC")
    sync_interval_seconds: int = Field(
        default=60 * 60, validation_alias="AGENTPIT_SYNC_INTERVAL_SECONDS"
    )
    # Trending sync (top-N by 24h volume) + decoupled resolution/redeem loop
    sync_max_markets: int = Field(
        default=300, validation_alias="SYNC_MAX_MARKETS"
    )
    sync_liquidity_min: float = Field(
        default=0.0, validation_alias="SYNC_LIQUIDITY_MIN"
    )
    resolution_mirror_enabled: bool | None = Field(
        default=None, validation_alias="RESOLUTION_MIRROR_ENABLED"
    )
    resolution_mirror_interval_seconds: int = Field(
        default=300, validation_alias="RESOLUTION_MIRROR_INTERVAL_SECONDS"
    )
    auto_redeem_enabled: bool = Field(
        default=True, validation_alias="AUTO_REDEEM_ENABLED"
    )

    # Pinned-series sync (force-sync the current window of recurring markets).
    pinned_series_raw: str = Field(
        default="btc-updown-5m:300", validation_alias="PINNED_SERIES"
    )
    pin_sync_enabled: bool | None = Field(
        default=None, validation_alias="PIN_SYNC_ENABLED"
    )
    pin_sync_offset_seconds: int = Field(
        default=10, validation_alias="PIN_SYNC_OFFSET_SECONDS"
    )
    # How often the live window of each pinned series is re-mirrored from the
    # real Polymarket book. The shared reconciler can take minutes for a full
    # pass over hundreds of markets — far longer than a window's ~5-min life —
    # so the live windows get their own fast loop. With batched placement a
    # re-quote is ~1s, so a 1s interval tracks upstream within ~2s.
    pin_requote_seconds: float = Field(
        default=1.0, validation_alias="AGENTPIT_PIN_REQUOTE_SECONDS"
    )
    # How often just-ended pinned windows are checked for upstream resolution +
    # auto-redeem. The full resolution loop runs every few minutes (fine for
    # long-dated markets), but a 5-min window's winner should be paid within
    # seconds of the upstream market closing, so its windows get their own fast
    # poll. Cheap: scoped to the few most-recently-ended pinned windows.
    pin_resolve_seconds: float = Field(
        default=20.0, validation_alias="AGENTPIT_PIN_RESOLVE_SECONDS"
    )
    # Fast re-quoting cancels + re-places the whole book every second, so the
    # orders table fills with dead 'cancelled' rows. They never slow the live
    # queries (a partial index covers only live rows), but unbounded growth eats
    # disk, so purge cancelled rows older than the retention on a slow loop.
    order_cleanup_interval_seconds: float = Field(
        default=60.0, validation_alias="AGENTPIT_ORDER_CLEANUP_INTERVAL_SECONDS"
    )
    order_cancelled_retention_seconds: int = Field(
        default=600, validation_alias="AGENTPIT_ORDER_CANCELLED_RETENTION_SECONDS"
    )
    idempotency_key_retention_seconds: int = Field(
        default=86400, validation_alias="AGENTPIT_IDEMPOTENCY_KEY_RETENTION_SECONDS"
    )

    @model_validator(mode="after")
    def _default_resolution_mirror_enabled(self) -> "Settings":
        # When RESOLUTION_MIRROR_ENABLED is unset, follow SYNC.
        if self.resolution_mirror_enabled is None:
            self.resolution_mirror_enabled = self.sync_enabled
        return self

    @model_validator(mode="after")
    def _default_pin_sync_enabled(self) -> "Settings":
        # When PIN_SYNC_ENABLED is unset, follow SYNC.
        if self.pin_sync_enabled is None:
            self.pin_sync_enabled = self.sync_enabled
        return self

    @property
    def pinned_series(self) -> list[tuple[str, int]]:
        """Parsed ``[(base, interval), ...]`` from ``PINNED_SERIES``.

        Imported lazily to avoid a config<->polymarket import cycle.
        """
        from agentpit.polymarket.pinned import parse_pinned_series

        return parse_pinned_series(self.pinned_series_raw)

    snapshot_enabled: bool = Field(default=False, validation_alias="SNAPSHOT_ENABLED")
    snapshot_interval_seconds: int = Field(
        default=15 * 60, validation_alias="AGENTPIT_SNAPSHOT_INTERVAL_SECONDS"
    )
    snapshot_retention_days: int = Field(
        default=30, validation_alias="AGENTPIT_SNAPSHOT_RETENTION_DAYS"
    )
    cors_origins: list[str] = Field(
        default=["http://localhost:5173"], validation_alias="AGENTPIT_CORS_ORIGINS"
    )

    # Auth
    jwt_secret: str = Field(
        default="dev-only-insecure-secret-change-me",
        validation_alias="JWT_SECRET",
    )
    jwt_algorithm: str = Field(default="HS256", validation_alias="JWT_ALGORITHM")
    jwt_expires_seconds: int = Field(
        default=60 * 60 * 24, validation_alias="JWT_EXPIRES_SECONDS"
    )

    # On-chain stack
    deployment_path: Path = Field(
        default=Path("deployments/local.json"),
        validation_alias="AGENTPIT_DEPLOYMENT_PATH",
    )
    operator_private_key: str | None = Field(default=None, validation_alias="PK")
    rpc_url_override: str | None = Field(default=None, validation_alias="RPC_URL")
    signup_gas_grant_wei: int = Field(
        default=10**18, validation_alias="AGENTPIT_SIGNUP_GAS_GRANT_WEI"
    )
    tx_confirmations_timeout_s: int = Field(
        default=30, validation_alias="AGENTPIT_TX_TIMEOUT_S"
    )

    # Admin
    admin_token: str = Field(
        default="dev-admin-token",
        validation_alias="AGENTPIT_ADMIN_TOKEN",
    )

    # Liquidity Engine (Phase 5c: Polymarket book mirror)
    liquidity_engine_enabled: bool = Field(
        default=False, validation_alias="LIQUIDITY_ENGINE"
    )
    liquidity_interval_seconds: float = Field(
        default=2.0, validation_alias="AGENTPIT_LIQUIDITY_INTERVAL_SECONDS"
    )
    # ONE mirror account owns every mirror order (spec §6). >1 is unused but
    # kept for provisioning flexibility.
    liquidity_house_account_count: int = Field(
        default=1, validation_alias="AGENTPIT_LIQUIDITY_HOUSE_ACCOUNTS"
    )
    # 1 faucet drip = the deploy's SIGNUP_GRANT_RAW, set to $1 quadrillion apUSD
    # (scripts/deploy_exchange.sh), so a single drip funds the house far beyond
    # any market set's notional.
    liquidity_funding_drips: int = Field(
        default=1, validation_alias="AGENTPIT_LIQUIDITY_FUNDING_DRIPS"
    )
    # House gas. The mirror signs its own split transactions, so the account
    # spends gas continuously and its signup grant is not a lifetime supply:
    # production burned it in ~82 minutes and the mirror then failed silently.
    # A floor of 5 ETH is ~45 hours of headroom at the observed post-fix rate
    # (0.111 ETH/h), so a refill is never urgent. Topping up is gas ONLY --
    # the zero-balance path in HouseAccountProvisioner means "the chain was
    # reset, re-onboard from scratch" and must stay distinct from this.
    liquidity_gas_floor_wei: int = Field(
        default=5 * 10**18, validation_alias="AGENTPIT_LIQUIDITY_GAS_FLOOR_WEI"
    )
    liquidity_gas_target_wei: int = Field(
        default=100 * 10**18, validation_alias="AGENTPIT_LIQUIDITY_GAS_TARGET_WEI"
    )
    liquidity_gas_check_interval_seconds: float = Field(
        default=300.0,
        validation_alias="AGENTPIT_LIQUIDITY_GAS_CHECK_INTERVAL_SECONDS",
    )
    mirror_assets_per_connection: int = Field(
        default=200, validation_alias="AGENTPIT_MIRROR_ASSETS_PER_CONNECTION"
    )
    mirror_reconcile_min_interval_seconds: float = Field(
        default=0.5, validation_alias="AGENTPIT_MIRROR_RECONCILE_MIN_INTERVAL_SECONDS"
    )
    mirror_watchdog_seconds: float = Field(
        default=120.0, validation_alias="AGENTPIT_MIRROR_WATCHDOG_SECONDS"
    )
    mirror_inventory_buffer: float = Field(
        default=1.2, validation_alias="AGENTPIT_MIRROR_INVENTORY_BUFFER"
    )
    # Headroom minted above the requirement whenever the house is short, in
    # micro-apUSD. The requirement only ever grows, so exact top-ups cost a
    # transaction per upstream depth record; one generous block instead lets a
    # market converge in a single split. 1e14 micro = 100M apUSD, comfortably
    # above the largest requirement observed in production (39M). Collateral is
    # minted freely on the simulated chain, so the block can be this generous —
    # lower it on a chain where collateral costs real money. 0 restores exact
    # top-ups.
    mirror_inventory_seed_micro: int = Field(
        default=100_000_000_000_000,
        validation_alias="AGENTPIT_MIRROR_INVENTORY_SEED_MICRO",
    )
    mirror_max_settlements_per_cycle: int = Field(
        default=1, validation_alias="AGENTPIT_MIRROR_MAX_SETTLEMENTS_PER_CYCLE"
    )
    mirror_tape_enabled: bool = Field(
        default=True, validation_alias="AGENTPIT_MIRROR_TAPE_ENABLED"
    )
    # How often the mirror re-scans the active-market set. Kept short so a new
    # rotating-series window (live for only ~5 min) is picked up and quoted
    # promptly; a no-change scan is a cheap DB read (resubscribe fires only when
    # the set actually changes).
    mirror_target_refresh_seconds: float = Field(
        default=15.0, validation_alias="AGENTPIT_MIRROR_TARGET_REFRESH_SECONDS"
    )
    # Total depth cap per side. The cold sweep converges the local book to this
    # many levels; 0 = unbounded (full 1:1). This is a convergence target, not
    # a hard ceiling: a hot pass never cancels a cold-classified order, so the
    # live count between sweeps can exceed it on a fast-moving market. Each
    # level is ~4 DB order ops, and reconcile_market reads ALL house levels
    # for the market on every hot pass, so hot-path cost tracks that
    # accumulated live set, not mirror_hot_depth.
    mirror_book_depth: int = Field(
        default=8, validation_alias="AGENTPIT_MIRROR_BOOK_DEPTH"
    )
    # Levels per side reconciled on EVERY book update. These carry the price the
    # user sees and the spread a bot trades against, so they must stay live.
    # Everything between this and mirror_book_depth is the cold band, refreshed
    # only by the sweep below. hot == book depth means no cold band at all,
    # which is byte-identical to the pre-two-tier behaviour.
    mirror_hot_depth: int = Field(
        default=8, validation_alias="AGENTPIT_MIRROR_HOT_DEPTH"
    )
    # How often each market's deep levels are reconciled. Deep levels move
    # rarely and nobody trades against them, so this is deliberately slow — it
    # is what keeps a 50-level book from multiplying the hot path.
    mirror_cold_interval_seconds: float = Field(
        default=1800.0, validation_alias="AGENTPIT_MIRROR_COLD_INTERVAL_SECONDS"
    )
