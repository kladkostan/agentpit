"""High-level on-chain operations executed with the admin/operator key."""

from eth_account.signers.local import LocalAccount
from web3 import Web3
from web3.types import TxReceipt

from agentpit.onchain.contracts import Contracts
from agentpit.onchain.user_wallet import (
    fund_user_with_native,
    send_admin_tx,
    send_user_tx,
)
from agentpit.onchain.web3_client import Web3Client

# How many token ids go into one balanceOfBatch. Large enough that an ordinary
# account is a single call, small enough that a heavy one does not ask a public
# node for a reply it may cap.
_BALANCE_BATCH = 200

_MAX_UINT256 = 2**256 - 1


class OnchainAdmin:
    def __init__(self, client: Web3Client, contracts: Contracts):
        self._client = client
        self._contracts = contracts

    # --- onboarding -------------------------------------------------

    def faucet_drip(self, recipient: str, *, timeout: int = 30) -> TxReceipt:
        fn = self._contracts.faucet.functions.drip(Web3.to_checksum_address(recipient))
        return send_admin_tx(self._client, fn, timeout=timeout)

    def mint_to(
        self, recipient: str, amount_raw: int, *, timeout: int = 30
    ) -> TxReceipt:
        """Mint an arbitrary amount of apUSD — house funding and top-ups.

        `faucet_drip` mints the fixed signup grant; this is the same faucet's
        unrestricted entry point, and like drip it is operator-only on chain.
        """
        fn = self._contracts.faucet.functions.mintTo(
            Web3.to_checksum_address(recipient), amount_raw
        )
        return send_admin_tx(self._client, fn, timeout=timeout)

    def fund_gas(
        self, user_address: str, value_wei: int, *, timeout: int = 30
    ) -> TxReceipt:
        return fund_user_with_native(
            self._client, user_address, value_wei, timeout=timeout
        )

    def grant_user_approvals(
        self, user_account: LocalAccount, *, timeout: int = 30
    ) -> tuple[TxReceipt, TxReceipt, TxReceipt]:
        """Send the three one-time approvals on behalf of `user_account`.

        1. usd.approve(exchange, max)         — collateral movement during fills
        2. usd.approve(ctf, max)              — splitPosition during MINT matches
        3. ctf.setApprovalForAll(exchange,1)  — outcome-token movement
        """
        usd = self._contracts.usd
        ctf = self._contracts.ctf
        exch = self._contracts.exchange.address

        rcpt_a = send_user_tx(
            self._client,
            user_account,
            usd.functions.approve(exch, _MAX_UINT256),
            timeout=timeout,
        )
        rcpt_b = send_user_tx(
            self._client,
            user_account,
            usd.functions.approve(ctf.address, _MAX_UINT256),
            timeout=timeout,
        )
        rcpt_c = send_user_tx(
            self._client,
            user_account,
            ctf.functions.setApprovalForAll(exch, True),
            timeout=timeout,
        )
        return rcpt_a, rcpt_b, rcpt_c

    # --- markets ----------------------------------------------------

    def prepare_condition(
        self,
        oracle: str,
        question_id: bytes,
        outcome_slot_count: int,
        *,
        timeout: int = 30,
    ) -> TxReceipt:
        fn = self._contracts.ctf.functions.prepareCondition(
            Web3.to_checksum_address(oracle), question_id, outcome_slot_count
        )
        return send_admin_tx(self._client, fn, timeout=timeout)

    def register_token(
        self, token_a: int, token_b: int, condition_id: bytes, *, timeout: int = 30
    ) -> TxReceipt:
        fn = self._contracts.exchange.functions.registerToken(
            token_a, token_b, condition_id
        )
        return send_admin_tx(self._client, fn, timeout=timeout)

    def report_payouts(
        self, question_id: bytes, payouts: list[int], *, timeout: int = 30
    ) -> TxReceipt:
        """Admin (= local oracle) reports the resolved payout vector.

        For binary YES/NO markets `payouts` is `[1, 0]` if YES won, `[0, 1]`
        if NO won. The CTF rejects re-reporting (custom error) — callers
        wanting idempotency should pre-check `payoutDenominator` or catch.
        """
        fn = self._contracts.ctf.functions.reportPayouts(question_id, payouts)
        return send_admin_tx(self._client, fn, timeout=timeout)

    def user_split_position(
        self,
        user_account: LocalAccount,
        condition_id: bytes,
        amount: int,
        *,
        timeout: int = 30,
    ) -> TxReceipt:
        """User-signed splitPosition: lock `amount` apUSD, get equal YES+NO tokens.

        Useful for tests / first-time SELL flows before any orders have settled.
        """
        usd_address = self._contracts.usd.address
        fn = self._contracts.ctf.functions.splitPosition(
            usd_address, b"\x00" * 32, condition_id, [1, 2], amount
        )
        return send_user_tx(self._client, user_account, fn, timeout=timeout)

    # --- read-only --------------------------------------------------

    @property
    def deployment_id(self) -> str:
        """Identity of the chain deployment these contracts belong to.

        The CTF address: a redeploy always produces a new one, because the
        contracts themselves are new. Callers compare it against what they
        recorded to tell "the chain was replaced" from "nothing happened",
        without an RPC round-trip.
        """
        return self._client.deployment.ctf

    def usd_balance(self, address: str) -> int:
        return self._contracts.usd.functions.balanceOf(
            Web3.to_checksum_address(address)
        ).call()

    def native_balance(self, address: str) -> int:
        return self._client.web3.eth.get_balance(Web3.to_checksum_address(address))

    def ctf_balance(self, address: str, token_id: int) -> int:
        return self._contracts.ctf.functions.balanceOf(
            Web3.to_checksum_address(address), token_id
        ).call()

    def ctf_balances(self, address: str, token_ids: list[int]) -> list[int]:
        """Every token's balance for one holder, in as few calls as possible.

        `ctf_balance` per token is what made the profile page slow: a chain
        read costs ~0.5s on a remote node, and a position scan asks for two
        tokens per market the account has ever touched, so a 500-trade
        account paid over twenty seconds of round trips for a page of
        fourteen rows. ERC-1155 answers the whole list in one call.

        Chunked because the list grows with the account: an eth_call
        returning a thousand words is a different proposition from one
        returning a few dozen, and the node is entitled to refuse it.
        """
        if not token_ids:
            return []
        owner = Web3.to_checksum_address(address)
        out: list[int] = []
        for start in range(0, len(token_ids), _BALANCE_BATCH):
            chunk = token_ids[start : start + _BALANCE_BATCH]
            out.extend(
                self._contracts.ctf.functions.balanceOfBatch(
                    [owner] * len(chunk), chunk
                ).call()
            )
        return out
