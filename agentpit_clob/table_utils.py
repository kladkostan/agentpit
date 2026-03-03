import json
import sqlite3


class TableUtils:
    @staticmethod
    def ensure_ownership_row(db: sqlite3.Connection, token_id: str) -> None:
        db.execute(
            """
            INSERT INTO token_ownership (TOKEN_ID, OWNERSHIP)
            VALUES (?, ?)
            ON CONFLICT(TOKEN_ID) DO NOTHING
            """,
            (token_id, "{}"),
        )

    @staticmethod
    def load_ownership_map(db: sqlite3.Connection, token_id: str) -> dict[str, str]:
        row = db.execute(
            "SELECT OWNERSHIP FROM token_ownership WHERE TOKEN_ID = ? LIMIT 1",
            (token_id,),
        ).fetchone()
        raw: str = "{}" if row is None or row[0] is None else row[0]
        try:
            m_obj: object = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as e:
            raise ValueError(
                f"Corrupted OWNERSHIP JSON for {token_id}: {raw!r}"
            ) from e

        if not isinstance(m_obj, dict):
            raise ValueError(
                f"Corrupted OWNERSHIP data for {token_id}: expected dict, got {type(m_obj)}"
            )

        m: dict[str, str] = {}
        for k, v in m_obj.items():
            if not isinstance(k, str) or not isinstance(v, str):
                raise ValueError(
                    f"Corrupted OWNERSHIP map for {token_id}: non-str entry {k!r}: {v!r}"
                )
            m[k] = v
        return m

    @staticmethod
    def store_ownership_map(
        db: sqlite3.Connection, token_id: str, m: dict[str, str]
    ) -> None:
        # Validate map shape before writing
        for k, v in m.items():
            if not isinstance(k, str) or not isinstance(v, str):
                raise TypeError(
                    f"OWNERSHIP map must be dict[str, str], got entry {k!r}: {v!r}"
                )
        db.execute(
            "UPDATE token_ownership SET OWNERSHIP = ? WHERE TOKEN_ID = ?",
            (json.dumps(m, separators=(",", ":")), token_id),
        )
