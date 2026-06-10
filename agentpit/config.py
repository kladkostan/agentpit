from pathlib import Path

from pydantic import Field
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
    # 1 faucet drip = $1B apUSD. 4 drips cover splits + bids across all markets.
    liquidity_funding_drips: int = Field(
        default=4, validation_alias="AGENTPIT_LIQUIDITY_FUNDING_DRIPS"
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
    mirror_target_refresh_seconds: float = Field(
        default=60.0, validation_alias="AGENTPIT_MIRROR_TARGET_REFRESH_SECONDS"
    )
