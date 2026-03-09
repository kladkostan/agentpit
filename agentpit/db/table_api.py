import sqlite3

import fasteners
from eth_account.signers.local import LocalAccount

from agentpit.db.implementation.table_create import TableCreate
from agentpit.db.implementation.table_read import TableRead
from agentpit.db.implementation.table_write import TableWrite
from agentpit.datastructures.condition_id import ConditionId
from agentpit.datastructures.create_market_request import CreateMarketRequest
from agentpit.datastructures.market import Market
from agentpit.datastructures.market_state import MarketState


class TableAPI:
    # Class-level reader/writer lock shared by all instances/calls.
    # Readers may run concurrently; writers are exclusive.
    _rw_lock = fasteners.ReaderWriterLock()

    @staticmethod
    def create_all_tables_thread_safe(db: sqlite3.Connection) -> None:
        with TableAPI._rw_lock.write_lock():
            with db:
                TableCreate.create_all_tables(db)

    # -----------------
    # Thread-safe TableRead wrappers (read lock)
    # -----------------

    @staticmethod
    def read_condition_id_by_polymarket_id_thread_safe(
        db: sqlite3.Connection, polymarket_id: int
    ) -> ConditionId | None:
        with TableAPI._rw_lock.read_lock():
            return TableRead.read_condition_id_by_polymarket_id(db, polymarket_id)

    @staticmethod
    def market_exists_by_polymarket_id_thread_safe(
        db: sqlite3.Connection, polymarket_id: int
    ) -> bool:
        with TableAPI._rw_lock.read_lock():
            exists = TableRead.market_exists_by_polymarket_id(db, polymarket_id)
            return bool(exists)

    @staticmethod
    def get_market_status_by_condition_id_thread_safe(
        db: sqlite3.Connection, condition_id: str
    ) -> tuple[MarketState, int | None] | None:
        with TableAPI._rw_lock.read_lock():
            return TableRead.get_market_status_by_condition_id(db, condition_id)

    @staticmethod
    def get_erc20_asset_ownership_thread_safe(
        db: sqlite3.Connection, eth_address: str, asset_address: str
    ) -> int:
        with TableAPI._rw_lock.read_lock():
            value = TableRead.get_erc20_asset_ownership(db, eth_address, asset_address)
            return int(value)

    @staticmethod
    def get_erc1155_asset_ownership_thread_safe(
        db: sqlite3.Connection, eth_address: str, token_id: str
    ) -> int:
        with TableAPI._rw_lock.read_lock():
            value = TableRead.get_erc1155_asset_ownership(db, eth_address, token_id)
            return int(value)

    @staticmethod
    def get_private_key_for_api_key_thread_safe(
        db: sqlite3.Connection, api_key: str
    ) -> LocalAccount:
        # This can create+insert a key row if missing -> treat as write.
        with TableAPI._rw_lock.write_lock():
            with db:
                return TableRead.get_private_key_for_api_key(db, api_key)

    @staticmethod
    def get_eth_address_for_api_key_thread_safe(
        db: sqlite3.Connection, api_key: str
    ) -> str:
        # Delegates to get_private_key_for_api_key; keep as write.
        with TableAPI._rw_lock.write_lock():
            with db:
                return TableRead.get_eth_address_for_api_key(db, api_key)

    @staticmethod
    def read_market_thread_safe(db: sqlite3.Connection, market_id: int) -> Market | None:
        with TableAPI._rw_lock.read_lock():
            return TableRead.read_market(db, market_id)

    @staticmethod
    def read_market_by_condition_id_thread_safe(
        db: sqlite3.Connection, condition_id: ConditionId
    ) -> Market | None:
        with TableAPI._rw_lock.read_lock():
            return TableRead.read_market_by_condition_id(db, condition_id)

    @staticmethod
    def list_all_markets_thread_safe(db: sqlite3.Connection) -> list[Market]:
        with TableAPI._rw_lock.read_lock():
            markets = TableRead.list_all_markets(db)
            return list(markets)

    @staticmethod
    def list_markets_thread_safe(
        db: sqlite3.Connection, limit: int = 100, offset: int = 0
    ) -> tuple[list[Market], int]:
        with TableAPI._rw_lock.read_lock():
            markets, total = TableRead.list_markets(db, limit=limit, offset=offset)
            return list(markets), int(total)

    @staticmethod
    def get_transaction_history_thread_safe(db: sqlite3.Connection, api_key: str) -> list:
        with TableAPI._rw_lock.read_lock():
            hist = TableRead.get_transaction_history(db, api_key)
            return list(hist)

    # -----------------
    # Thread-safe TableWrite wrappers (write lock)
    # -----------------

    @staticmethod
    def create_market_thread_safe(
        db: sqlite3.Connection,
        request: CreateMarketRequest,
        is_polygon_market: bool,
    ) -> Market:
        with TableAPI._rw_lock.write_lock():
            with db:
                return TableWrite.create_market(db, request, is_polygon_market)

    @staticmethod
    def update_market_state_if_needed_thread_safe(
        db: sqlite3.Connection,
        request: CreateMarketRequest,
    ) -> Market:
        with TableAPI._rw_lock.write_lock():
            with db:
                return TableWrite.update_market_state_if_needed(db, request)

    @staticmethod
    def log_transaction_thread_safe(
        db: sqlite3.Connection,
        api_key: str,
        transaction_type: str,
        market_id: int | None = None,
        details: dict | None = None,
    ) -> None:
        with TableAPI._rw_lock.write_lock():
            with db:
                TableWrite.log_transaction(
                    db,
                    api_key=api_key,
                    transaction_type=transaction_type,
                    market_id=market_id,
                    details=details,
                )
        return None

    @staticmethod
    def activate_market_thread_safe(db: sqlite3.Connection, market_id: int) -> Market:
        with TableAPI._rw_lock.write_lock():
            with db:
                return TableWrite.activate_market(db, market_id)

    @staticmethod
    def close_market_thread_safe(db: sqlite3.Connection, market_id: int) -> Market:
        with TableAPI._rw_lock.write_lock():
            with db:
                return TableWrite.close_market(db, market_id)

    @staticmethod
    def resolve_market_thread_safe(
        db: sqlite3.Connection, market_id: int, winning_outcome_index: int
    ) -> Market:
        with TableAPI._rw_lock.write_lock():
            with db:
                return TableWrite.resolve_market(db, market_id, winning_outcome_index)

    @staticmethod
    def cancel_market_thread_safe(
        db: sqlite3.Connection, market_id: int
    ) -> tuple[Market, int]:
        with TableAPI._rw_lock.write_lock():
            with db:
                return TableWrite.cancel_market(db, market_id)

    @staticmethod
    def update_market_state_to_closed_if_needed_thread_safe(
        db: sqlite3.Connection, condition_id: ConditionId
    ) -> None:
        with TableAPI._rw_lock.write_lock():
            with db:
                TableWrite.update_market_state_to_closed_if_needed(db, condition_id)
        return None

    @staticmethod
    def update_market_state_to_resolved_if_needed_thread_safe(
        db: sqlite3.Connection, condition_id: ConditionId, winning_outcome_index: int
    ) -> None:
        with TableAPI._rw_lock.write_lock():
            with db:
                TableWrite.update_market_state_to_resolved_if_needed(
                    db, condition_id, winning_outcome_index
                )
        return None
