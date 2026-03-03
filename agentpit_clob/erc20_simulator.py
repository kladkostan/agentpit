import sqlite3

from agentpit_clob.tables_create import TablesCreate


class ERC20Simulator:
    @staticmethod
    def mint(
        db: sqlite3.Connection, eth_address: str, asset_address: str, value: int
    ) -> None:
        # Delegate to TablesCreate.mint, which validates and raises on any error.
        TablesCreate.mint(db, eth_address, asset_address, value)

    @staticmethod
    def transfer(
        db: sqlite3.Connection,
        src_address: str,
        destination_address: str,
        value: int,
        asset_address: str,
    ) -> None:
        # Delegate to TablesCreate.transfer, which validates and raises on any error.
        TablesCreate.transfer(db, src_address, destination_address, value, asset_address)
