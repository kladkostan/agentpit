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

    # Liquidity Engine
    liquidity_engine_enabled: bool = Field(
        default=False, validation_alias="LIQUIDITY_ENGINE"
    )
    liquidity_interval_seconds: float = Field(
        default=2.0, validation_alias="AGENTPIT_LIQUIDITY_INTERVAL_SECONDS"
    )
    liquidity_house_account_count: int = Field(
        default=100, validation_alias="AGENTPIT_LIQUIDITY_HOUSE_ACCOUNTS"
    )
    liquidity_wallet_funding_usdc: int = Field(
        default=1_000_000_000, validation_alias="AGENTPIT_LIQUIDITY_WALLET_FUNDING_USDC"
    )
    liquidity_split_per_market_usdc: int = Field(
        default=10_000, validation_alias="AGENTPIT_LIQUIDITY_SPLIT_PER_MARKET_USDC"
    )
    liquidity_makers_per_market: int = Field(
        default=16, validation_alias="AGENTPIT_LIQUIDITY_MAKERS_PER_MARKET"
    )
    liquidity_ladder_rungs_per_side: int = Field(
        default=8, validation_alias="AGENTPIT_LIQUIDITY_LADDER_RUNGS"
    )
    liquidity_wall_fraction: float = Field(
        default=0.6, validation_alias="AGENTPIT_LIQUIDITY_WALL_FRACTION"
    )
    liquidity_requote_threshold_micro: int = Field(
        default=2_000, validation_alias="AGENTPIT_LIQUIDITY_REQUOTE_THRESHOLD"
    )
