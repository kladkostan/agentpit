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
    # Cap how many price levels per side the mirror replicates onto the local
    # book. Each level is ~4 on-chain/DB order ops, so a deep book is the main
    # cost when re-quoting a fast-moving window. The top levels carry the price
    # the user sees; deeper levels rarely matter. 0 = unbounded (full 1:1).
    mirror_book_depth: int = Field(
        default=8, validation_alias="AGENTPIT_MIRROR_BOOK_DEPTH"
    )
