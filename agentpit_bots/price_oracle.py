"""Polymarket midpoint oracle — batched, cached, graceful on failure.

Wraps ``py_clob_client.ClobClient``. Stores the most recent successful
fetch per token in an in-memory snapshot; on upstream failure, returns
the stale snapshot rather than raising — callers check ``is_stale`` to
decide whether to act.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable, Protocol

log = logging.getLogger(__name__)


class _ClobLike(Protocol):
    def get_midpoints(self, params: list) -> dict[str, float | None]: ...


@dataclass
class OracleSnapshot:
    """An immutable view of the latest cached midpoints."""

    data: dict[str, float] = field(default_factory=dict)
    fetched_at: dict[str, float] = field(default_factory=dict)

    def midpoint(self, token_id: str) -> float | None:
        return self.data.get(token_id)

    def is_stale(
        self, token_id: str, *, stale_after_sec: int, now: float | None = None
    ) -> bool:
        ts = self.fetched_at.get(token_id)
        if ts is None:
            return True
        current = now if now is not None else time.time()
        return (current - ts) > stale_after_sec


class PriceOracle:
    def __init__(
        self,
        clob: _ClobLike,
        *,
        now_fn: Callable[[], float] = time.time,
    ):
        self._clob = clob
        self._now = now_fn
        self._snap = OracleSnapshot()

    def refresh(self, token_ids: Iterable[str]) -> OracleSnapshot:
        """Fetch midpoints for ``token_ids`` in one batched call.

        On HTTP/connection failure: log + return the current snapshot
        unchanged. Callers check ``OracleSnapshot.is_stale(...)`` to decide
        whether to act on values from the snapshot.
        """
        # Import locally so unit tests don't need py_clob_client installed.
        from py_clob_client.clob_types import BookParams

        token_id_list = list(token_ids)
        if not token_id_list:
            return self._snap
        params = [BookParams(token_id=tid) for tid in token_id_list]
        try:
            response = self._clob.get_midpoints(params)
        except Exception:
            log.warning(
                "oracle_fetch_failed tokens=%d serving_stale=%d",
                len(token_id_list), len(self._snap.data),
            )
            return self._snap
        now = self._now()
        new_data = dict(self._snap.data)
        new_fetched = dict(self._snap.fetched_at)
        for tid in token_id_list:
            value = response.get(tid)
            if value is None:
                continue
            new_data[tid] = float(value)
            new_fetched[tid] = now
        self._snap = OracleSnapshot(data=new_data, fetched_at=new_fetched)
        return self._snap

    @property
    def snapshot(self) -> OracleSnapshot:
        return self._snap
