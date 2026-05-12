import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict


class Deployment(BaseModel):
    """Frozen view of deployments/local.json — addresses for a single chain."""

    model_config = ConfigDict(frozen=True)

    chain_id: int
    rpc_url: str
    admin: str
    usd: str
    faucet: str
    ctf: str
    proxy_factory: str
    safe_factory: str
    exchange: str
    signup_grant_raw: int

    @classmethod
    def load(cls, path: Path) -> "Deployment":
        raw = json.loads(Path(path).read_text())
        # signup_grant_raw is written as a string from bash; coerce to int
        if isinstance(raw.get("signup_grant_raw"), str):
            raw["signup_grant_raw"] = int(raw["signup_grant_raw"])
        return cls.model_validate(raw)
