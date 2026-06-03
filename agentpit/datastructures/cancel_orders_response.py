from pydantic import BaseModel, Field


class CancelOrdersResponse(BaseModel):
    """Uniform CLOB cancel result (§8.2). HTTP 200 always for valid auth.

    `canceled` (American spelling, single 'l') lists ids actually cancelled;
    `not_canceled` maps each un-cancelled id to a human reason string. Empty
    `{}` on full success. Reason strings are not a stable enum — a robust
    client checks presence in `not_canceled`, not the text.
    """

    canceled: list[str] = Field(default_factory=list)
    not_canceled: dict[str, str] = Field(default_factory=dict)
