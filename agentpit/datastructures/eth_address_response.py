from pydantic import BaseModel


class EthAddressResponse(BaseModel):
    api_key: str
    eth_address: str
