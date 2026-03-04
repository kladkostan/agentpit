import sqlite3


from web3 import Web3  # pip install web3
from pydantic import ConfigDict, StrictStr, conint, validate_call

from agentpit.utils.parse import normalize_eth_address, hex_u256_to_int
from agentpit.db.table_utils import TableUtils

_STRICT = ConfigDict(strict=True, arbitrary_types_allowed=True)


class ERC20Simulator:
    @staticmethod
    @validate_call(config=_STRICT)
    def mint(
        db: sqlite3.Connection,
        eth_address: StrictStr,
        asset_address: StrictStr,
        value: conint(ge=0, lt=1 << 256),
    ) -> None:
        norm_eth = normalize_eth_address(eth_address)
        norm_asset = normalize_eth_address(asset_address)

        if value == 0:
            return

        # errors propagate; no exception handling here
        with db:
            TableUtils.ensure_erc20_ownership_row(db, norm_eth)
            ownership_map = TableUtils.load_erc20_ownership_map(db, norm_eth)

            current = 0
            if norm_asset in ownership_map:
                current = hex_u256_to_int(ownership_map[norm_asset])

            new_value = current + value
            if new_value >= (1 << 256):
                raise OverflowError("u256 overflow")

            ownership_map[norm_asset] = Web3.to_hex(new_value).lower()

            TableUtils.store_erc20_ownership_map(db, norm_eth, ownership_map)

    @staticmethod
    @validate_call(config=_STRICT)
    def transfer(
        db: sqlite3.Connection,
        src_address: StrictStr,
        destination_address: StrictStr,
        value: conint(ge=0, lt=1 << 256),
        asset_address: StrictStr,
    ) -> None:
        norm_src = normalize_eth_address(src_address)
        norm_dst = normalize_eth_address(destination_address)
        norm_asset = normalize_eth_address(asset_address)

        if value == 0 or norm_src == norm_dst:
            return

        # errors propagate; no exception handling here
        with db:
            TableUtils.ensure_erc20_ownership_row(db, norm_src)
            TableUtils.ensure_erc20_ownership_row(db, norm_dst)
            src_map = TableUtils.load_erc20_ownership_map(db, norm_src)
            dst_map = TableUtils.load_erc20_ownership_map(db, norm_dst)

            raw_src_bal = src_map.get(norm_asset)
            src_bal = 0 if raw_src_bal is None else hex_u256_to_int(raw_src_bal)

            if src_bal < value:
                raise ValueError(f"Insufficient balance: {src_bal} < {value}")

            raw_dst_bal = dst_map.get(norm_asset)
            dst_bal = 0 if raw_dst_bal is None else hex_u256_to_int(raw_dst_bal)

            new_src = src_bal - value
            new_dst = dst_bal + value
            if new_dst >= (1 << 256):
                raise OverflowError("u256 overflow")

            src_map[norm_asset] = Web3.to_hex(new_src).lower()
            dst_map[norm_asset] = Web3.to_hex(new_dst).lower()

            TableUtils.store_erc20_ownership_map(db, norm_src, src_map)
            TableUtils.store_erc20_ownership_map(db, norm_dst, dst_map)

    @staticmethod
    @validate_call(config=_STRICT)
    def get_balance(
        db: sqlite3.Connection,
        eth_address: StrictStr,
        asset_address: StrictStr,
    ) -> int:
        norm_eth = normalize_eth_address(eth_address)
        norm_asset = normalize_eth_address(asset_address)

        with db:
            TableUtils.ensure_erc20_ownership_row(db, norm_eth)
            ownership_map = TableUtils.load_erc20_ownership_map(db, norm_eth)
            raw = ownership_map.get(norm_asset)
            return 0 if raw is None else hex_u256_to_int(raw)

    @staticmethod
    @validate_call(config=_STRICT)
    def burn(
        db: sqlite3.Connection,
        eth_address: StrictStr,
        asset_address: StrictStr,
        value: conint(ge=0, lt=1 << 256),
    ) -> None:
        norm_eth = normalize_eth_address(eth_address)
        norm_asset = normalize_eth_address(asset_address)

        if value == 0:
            return

        with db:
            TableUtils.ensure_erc20_ownership_row(db, norm_eth)
            ownership_map = TableUtils.load_erc20_ownership_map(db, norm_eth)

            raw_bal = ownership_map.get(norm_asset)
            bal = 0 if raw_bal is None else hex_u256_to_int(raw_bal)

            if bal < value:
                raise ValueError(f"Insufficient balance: {bal} < {value}")

            new_bal = bal - value
            ownership_map[norm_asset] = Web3.to_hex(new_bal).lower()

            TableUtils.store_erc20_ownership_map(db, norm_eth, ownership_map)
