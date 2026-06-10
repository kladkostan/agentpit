"""Pure in-memory replica of one Polymarket order book (one asset_id).

Fed by CLOB WSS market-channel events. No I/O. All prices/sizes are integer
micro units (1_000_000 == $1.00 == 1 share), parsed from the feed's decimal
STRINGS via Decimal — never through float.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, Overflow

MICRO = 1_000_000
TICK = 1_000  # 0.001 — the local book's price grid


def to_micro(value) -> int | None:
    """Decimal string -> integer micro units; None on garbage/non-finite."""
    if value is None:
        return None
    try:
        d = Decimal(str(value))
        if not d.is_finite():  # NaN / sNaN / ±Infinity
            return None
        if d.adjusted() > 18:  # pathological magnitude (> 1e18); reject
            return None
        return int((d * MICRO).to_integral_value())
    except (InvalidOperation, ValueError, TypeError, Overflow):
        return None


@dataclass(frozen=True)
class BookSnapshot:
    """Immutable, validated view: levels sorted best-first."""
    asset_id: str
    bids: tuple[tuple[int, int], ...]  # (price_micro, size_micro), best (highest) first
    asks: tuple[tuple[int, int], ...]  # best (lowest) first


def _clean_levels(levels) -> dict[int, int]:
    out: dict[int, int] = {}
    for lvl in levels or []:
        if not isinstance(lvl, dict):
            continue
        p, s = to_micro(lvl.get("price")), to_micro(lvl.get("size"))
        if p is None or s is None:
            continue
        s -= s % TICK  # snap size DOWN to the 0.001-share grid: the order
        # service re-derives PRICE from HALF_UP-rounded amounts, so off-grid
        # sizes drift off the desired tick and churn cancel/replace forever
        if s <= 0:
            continue
        if not (0 < p < MICRO) or p % TICK:
            continue  # outside (0,1) or off the local 0.001 grid
        out[p] = s
    return out


class BookReplica:
    def __init__(self, asset_id: str):
        self.asset_id = asset_id
        self.bids: dict[int, int] = {}  # price_micro -> size_micro
        self.asks: dict[int, int] = {}
        self.seeded = False
        self.stale = False  # tick_size_change / watchdog: drop deltas, await snapshot

    def apply_book(self, msg: dict) -> bool:
        """Full snapshot: REPLACES the book atomically. Returns True if applied."""
        if msg.get("asset_id") != self.asset_id:
            return False
        bids = _clean_levels(msg.get("bids"))
        asks = _clean_levels(msg.get("asks"))
        self.bids, self.asks = bids, asks
        self.seeded = True
        self.stale = False
        return True

    def apply_price_change_entry(self, entry: dict) -> bool:
        """One price_changes[] entry. size is the NEW TOTAL at that level
        (replace semantics); size 0 removes the level. Returns True if applied."""
        if entry.get("asset_id") != self.asset_id or not self.seeded or self.stale:
            return False
        side = entry.get("side")
        p, s = to_micro(entry.get("price")), to_micro(entry.get("size"))
        if side not in ("BUY", "SELL") or p is None or s is None or s < 0:
            return False
        if not (0 < p < MICRO) or p % TICK:
            return False
        s -= s % TICK  # same 0.001-share size snap as _clean_levels; a
        # dust-only level snaps to 0 and is removed
        book = self.bids if side == "BUY" else self.asks
        if s == 0:
            book.pop(p, None)
        else:
            book[p] = s
        return True

    def mark_stale(self) -> None:
        """Epoch reset (tick_size_change / watchdog): drop state, await snapshot."""
        self.bids.clear()
        self.asks.clear()
        self.seeded = False
        self.stale = True

    def snapshot(self) -> BookSnapshot | None:
        """Validated frozen view, or None when unusable (unseeded/stale/crossed)."""
        if not self.seeded or self.stale:
            return None
        if self.bids and self.asks and max(self.bids) >= min(self.asks):
            return None  # crossed upstream data — never reconcile from this
        return BookSnapshot(
            asset_id=self.asset_id,
            bids=tuple(sorted(self.bids.items(), key=lambda kv: -kv[0])),
            asks=tuple(sorted(self.asks.items())),
        )
