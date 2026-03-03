import json
import sqlite3


class TableUtils:
    @staticmethod
    def ensure_ownership_row(db: sqlite3.Connection, addr: str) -> None:
        db.execute(
            """
            INSERT INTO token_ownership (ETH_ADDRESS, OWNERSHIP)
            VALUES (?, ?)
            ON CONFLICT(ETH_ADDRESS) DO NOTHING
            """,
            (addr, "{}"),
        )

    @staticmethod
    def load_ownership_map(db: sqlite3.Connection, addr: str) -> dict[str, str]:
        row = db.execute(
            "SELECT OWNERSHIP FROM token_ownership WHERE ETH_ADDRESS = ? LIMIT 1",
            (addr,),
        ).fetchone()
        raw: str = "{}" if row is None or row[0] is None else row[0]
        try:
            m_obj: object = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as e:
            raise ValueError(
                f"Corrupted OWNERSHIP JSON for {addr}: {raw!r}"
            ) from e

        if not isinstance(m_obj, dict):
            raise ValueError(
                f"Corrupted OWNERSHIP data for {addr}: expected dict, got {type(m_obj)}"
            )

        m: dict[str, str] = {}
        for k, v in m_obj.items():
            if not isinstance(k, str) or not isinstance(v, str):
                raise ValueError(
                    f"Corrupted OWNERSHIP map for {addr}: non-str entry {k!r}: {v!r}"
                )
            m[k] = v
        return m

    @staticmethod
    def store_ownership_map(
        db: sqlite3.Connection, addr: str, m: dict[str, str]
    ) -> None:
        # Validate map shape before writing
        for k, v in m.items():
            if not isinstance(k, str) or not isinstance(v, str):
                raise TypeError(
                    f"OWNERSHIP map must be dict[str, str], got entry {k!r}: {v!r}"
                )
        db.execute(
            "UPDATE token_ownership SET OWNERSHIP = ? WHERE ETH_ADDRESS = ?",
            (json.dumps(m, separators=(",", ":")), addr),
        )
