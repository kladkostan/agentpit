import json
import sqlite3


class TableUtils:
    @staticmethod
    def ensure_row(db: sqlite3.Connection, addr: str) -> None:
        db.execute(
            """
            INSERT INTO token_ownership (ETH_ADDRESS, OWNERSHIP)
            VALUES (?, ?)
            ON CONFLICT(ETH_ADDRESS) DO NOTHING
            """,
            (addr, "{}"),
        )

    @staticmethod
    def load_map(db: sqlite3.Connection, addr: str) -> dict[str, str]:
        row = db.execute(
            "SELECT OWNERSHIP FROM token_ownership WHERE ETH_ADDRESS = ? LIMIT 1",
            (addr,),
        ).fetchone()
        raw: str = "{}" if row is None or row[0] is None else row[0]
        try:
            m_obj: object = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            m_obj = {}

        if not isinstance(m_obj, dict):
            return {}

        return {
            k: v
            for k, v in m_obj.items()
            if isinstance(k, str) and isinstance(v, str)
        }

    @staticmethod
    def store_map(db: sqlite3.Connection, addr: str, m: dict[str, str]) -> None:
        db.execute(
            "UPDATE token_ownership SET OWNERSHIP = ? WHERE ETH_ADDRESS = ?",
            (json.dumps(m, separators=(",", ":")), addr),
        )
