from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        populate_by_name=True,
    )

    db_path: str = Field(default=":memory:", validation_alias="AGENTPIT_DB_PATH")
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
