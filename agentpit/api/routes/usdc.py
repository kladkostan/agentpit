from fastapi import APIRouter

from agentpit.api.deps import UsdcServiceDep
from agentpit.datastructures.get_usdc_balance_response import GetUsdcBalanceResponse
from agentpit.datastructures.mint_usdc_request import MintUsdcRequest
from agentpit.datastructures.mint_usdc_response import MintUsdcResponse
from agentpit.datastructures.transfer_usdc_request import TransferUsdcRequest
from agentpit.datastructures.transfer_usdc_response import TransferUsdcResponse

router = APIRouter(tags=["usdc"])


@router.post("/mint_usdc", response_model=MintUsdcResponse)
def mint_usdc(payload: MintUsdcRequest, service: UsdcServiceDep) -> MintUsdcResponse:
    return service.mint(payload)


@router.get("/usdc_balance/{api_key}", response_model=GetUsdcBalanceResponse)
def get_usdc_balance(api_key: str, service: UsdcServiceDep) -> GetUsdcBalanceResponse:
    return service.get_balance(api_key)


@router.post("/transfer_usdc", response_model=TransferUsdcResponse)
def transfer_usdc(payload: TransferUsdcRequest, service: UsdcServiceDep) -> TransferUsdcResponse:
    return service.transfer(payload)
