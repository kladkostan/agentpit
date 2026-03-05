from pydantic import field_validator, BaseModel


class TransferUsdcRequest(BaseModel):
    api_key: str
    destination_address: str
    amount: int

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, v: str) -> str:
        if not isinstance(v, str) or not v:
            raise ValueError("must be a non-empty string")
        return v

    @field_validator("destination_address")
    @classmethod
    def validate_destination_address(cls, v: str) -> str:
        if not isinstance(v, str) or not v:
            raise ValueError("must be a non-empty string")
        # Basic validation - should start with 0x and be 42 chars
        if not v.startswith("0x") or len(v) != 42:
            raise ValueError("must be a valid Ethereum address (0x + 40 hex chars)")
        return v

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, v: int) -> int:
        if not isinstance(v, int) or v <= 0:
            raise ValueError("must be a positive integer")
        if v >= (1 << 256):
            raise ValueError("amount exceeds u256 maximum")
        return v
