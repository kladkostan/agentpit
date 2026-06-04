from pydantic import BaseModel, Field


class BalanceAllowanceResponse(BaseModel):
    """Raw CLOB BalanceAllowanceResponse (§8.12). `balance` is a base-unit
    integer string; agentpit tracks no allowances → empty map."""

    balance: str
    allowances: dict[str, str] = Field(default_factory=dict)
