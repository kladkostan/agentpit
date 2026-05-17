"""Helpers for sending transactions signed by a user's private key."""

from eth_account.signers.local import LocalAccount
from web3 import Web3
from web3.contract.contract import ContractFunction
from web3.types import TxReceipt

from agentpit.onchain.web3_client import Web3Client


def send_user_tx(
    client: Web3Client,
    user_account: LocalAccount,
    fn: ContractFunction,
    *,
    timeout: int = 30,
    gas_buffer_pct: int = 20,
) -> TxReceipt:
    """Build, sign and broadcast `fn(...)` from the user's account; wait for receipt.

    Each user has their own nonce stream so we don't need the admin send_lock.
    """
    web3 = client.web3
    nonce = web3.eth.get_transaction_count(user_account.address, "pending")
    tx = fn.build_transaction(
        {
            "from": user_account.address,
            "nonce": nonce,
            "chainId": client.deployment.chain_id,
        }
    )
    if "gas" not in tx:
        gas_estimate = fn.estimate_gas({"from": user_account.address})
        tx["gas"] = gas_estimate * (100 + gas_buffer_pct) // 100

    signed = user_account.sign_transaction(tx)
    tx_hash = web3.eth.send_raw_transaction(signed.raw_transaction)
    return web3.eth.wait_for_transaction_receipt(tx_hash, timeout=timeout)


def send_admin_tx(
    client: Web3Client,
    fn: ContractFunction,
    *,
    timeout: int = 30,
    gas_buffer_pct: int = 20,
) -> TxReceipt:
    """Build, sign and broadcast `fn(...)` from the admin account.

    Serialised by the client.send_lock so concurrent admin sends don't collide
    on nonce.
    """
    web3 = client.web3
    with client.send_lock:
        nonce = web3.eth.get_transaction_count(client.admin.address, "pending")
        tx = fn.build_transaction(
            {
                "from": client.admin.address,
                "nonce": nonce,
                "chainId": client.deployment.chain_id,
            }
        )
        if "gas" not in tx:
            gas_estimate = fn.estimate_gas({"from": client.admin.address})
            tx["gas"] = gas_estimate * (100 + gas_buffer_pct) // 100

        signed = client.admin.sign_transaction(tx)
        tx_hash = web3.eth.send_raw_transaction(signed.raw_transaction)
        return web3.eth.wait_for_transaction_receipt(tx_hash, timeout=timeout)


def fund_user_with_native(
    client: Web3Client, user_address: str, value_wei: int, *, timeout: int = 30
) -> TxReceipt:
    """Send `value_wei` native tokens from admin to user_address.

    Used at signup so the new user can pay gas for their three approval txns.
    """
    web3 = client.web3
    with client.send_lock:
        nonce = web3.eth.get_transaction_count(client.admin.address, "pending")
        base_fee = web3.eth.get_block("latest").get("baseFeePerGas") or 0
        priority_fee = web3.to_wei("2", "gwei")
        tx = {
            "to": Web3.to_checksum_address(user_address),
            "value": value_wei,
            "nonce": nonce,
            "chainId": client.deployment.chain_id,
            "gas": 21_000,
            "maxFeePerGas": base_fee * 2 + priority_fee,
            "maxPriorityFeePerGas": priority_fee,
            "type": 2,
        }
        signed = client.admin.sign_transaction(tx)
        tx_hash = web3.eth.send_raw_transaction(signed.raw_transaction)
        return web3.eth.wait_for_transaction_receipt(tx_hash, timeout=timeout)
