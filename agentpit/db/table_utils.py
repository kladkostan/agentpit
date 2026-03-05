import json
import sqlite3


class TableUtils:
    @staticmethod
    def ensure_erc20_ownership_row(db: sqlite3.Connection, eth_address: str) -> None:
        db.execute(
            """
            INSERT INTO erc20_token_ownership (ETH_ADDRESS, OWNERSHIP)
            VALUES (?, ?)
            ON CONFLICT(ETH_ADDRESS) DO NOTHING
            """,
            (eth_address, "{}"),
        )

    @staticmethod
    def load_erc20_ownership_map(
        db: sqlite3.Connection, eth_address: str
    ) -> dict[str, str]:
        # errors propagate; no exception handling here
        row = db.execute(
            "SELECT OWNERSHIP FROM erc20_token_ownership WHERE ETH_ADDRESS = ? LIMIT 1",
            (eth_address,),
        ).fetchone()
        raw: str = "{}" if row is None or row[0] is None else row[0]
        m_obj: object = json.loads(raw)

        if not isinstance(m_obj, dict):
            raise ValueError(
                f"Corrupted OWNERSHIP data for {eth_address}: expected dict, got {type(m_obj)}"
            )

        m: dict[str, str] = {}
        for k, v in m_obj.items():
            if not isinstance(k, str) or not isinstance(v, str):
                raise ValueError(
                    f"Corrupted OWNERSHIP map for {eth_address}: non-str entry {k!r}: {v!r}"
                )
            m[k] = v
        return m

    @staticmethod
    def store_erc20_ownership_map(
        db: sqlite3.Connection, eth_address: str, m: dict[str, str]
    ) -> None:
        db.execute(
            "UPDATE erc20_token_ownership SET OWNERSHIP = ? WHERE ETH_ADDRESS = ?",
            (json.dumps(m, separators=(",", ":")), eth_address),
        )

    @staticmethod
    def ensure_erc1155_ownership_row(db: sqlite3.Connection, eth_address: str) -> None:
        db.execute(
            """
            INSERT INTO erc1155_token_ownership (ETH_ADDRESS, OWNERSHIP)
            VALUES (?, ?)
            ON CONFLICT(ETH_ADDRESS) DO NOTHING
            """,
            (eth_address, "{}"),
        )

    @staticmethod
    def load_erc1155_ownership_map(
        db: sqlite3.Connection, eth_address: str
    ) -> dict[str, str]:
        # errors propagate; no exception handling here
        row = db.execute(
            "SELECT OWNERSHIP FROM erc1155_token_ownership WHERE ETH_ADDRESS = ? LIMIT 1",
            (eth_address,),
        ).fetchone()
        raw: str = "{}" if row is None or row[0] is None else row[0]
        m_obj: object = json.loads(raw)

        if not isinstance(m_obj, dict):
            raise ValueError(
                f"Corrupted OWNERSHIP data for {eth_address}: expected dict, got {type(m_obj)}"
            )

        m: dict[str, str] = {}
        for k, v in m_obj.items():
            if not isinstance(k, str) or not isinstance(v, str):
                raise ValueError(
                    f"Corrupted OWNERSHIP map for {eth_address}: non-str entry {k!r}: {v!r}"
                )
            m[k] = v
        return m

    @staticmethod
    def store_erc1155_ownership_map(
        db: sqlite3.Connection, eth_address: str, m: dict[str, str]
    ) -> None:
        db.execute(
            "UPDATE erc1155_token_ownership SET OWNERSHIP = ? WHERE ETH_ADDRESS = ?",
            (json.dumps(m, separators=(",", ":")), eth_address),
        )
