import json
from pathlib import Path

from web3 import Web3
from web3.contract import Contract

from agentpit.onchain.deployment import Deployment

_ABI_DIR = Path(__file__).resolve().parent / "abi"


def _load_abi(name: str) -> list:
    with (_ABI_DIR / f"{name}.json").open() as f:
        return json.load(f)


class Contracts:
    """Typed handles to the deployed contracts. Built once per Web3Client."""

    def __init__(self, web3: Web3, deployment: Deployment):
        self.web3 = web3
        self.usd: Contract = web3.eth.contract(
            address=Web3.to_checksum_address(deployment.usd),
            abi=_load_abi("usd"),
        )
        self.faucet: Contract = web3.eth.contract(
            address=Web3.to_checksum_address(deployment.faucet),
            abi=_load_abi("faucet"),
        )
        self.ctf: Contract = web3.eth.contract(
            address=Web3.to_checksum_address(deployment.ctf),
            abi=_load_abi("ctf"),
        )
        self.exchange: Contract = web3.eth.contract(
            address=Web3.to_checksum_address(deployment.exchange),
            abi=_load_abi("exchange"),
        )
