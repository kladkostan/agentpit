"""Pure U-shaped, non-crossing ladder construction. No DB / chain / RNG."""
from dataclasses import dataclass

MICRO = 1_000_000          # $1.00 / 1 share
TICK = 1_000              # 0.001 = 0.1 cent

# Wall band: outermost rung sits this far from the 0 / 1 edge.
_WALL_BID_PRICE = 20_000          # ~2 cents
_WALL_ASK_PRICE = MICRO - 20_000  # ~98 cents


@dataclass(frozen=True)
class Rung:
    side: str          # "BUY" | "SELL"
    price_micro: int   # on TICK grid, 0 < p < MICRO
    size_micro: int    # outcome-token micro units


def _snap(price_micro: int) -> int:
    snapped = round(price_micro / TICK) * TICK
    return max(TICK, min(MICRO - TICK, snapped))


def _side_rungs(side, *, ceiling, wall_price, rungs_per_side, wall_size, spread_size):
    """Build one side. `ceiling` is the price closest to mid (inclusive);
    rungs march away from mid toward `wall_price`. The wall rung carries
    `wall_size`; the remaining near-spread rungs split `spread_size` evenly.

    The wall is placed just beyond the furthest near-spread rung (clamped into
    the valid band), so it is always strictly on the correct side of mid even
    when mid is near the 0/1 edge.
    """
    near_count = rungs_per_side - 1
    sign = -1 if side == "BUY" else 1
    prices = [ceiling]
    if near_count > 1:
        step = max(TICK, abs(ceiling - wall_price) // (rungs_per_side * 2))
        for k in range(1, near_count):
            prices.append(_snap(ceiling + sign * step * k))
    each = spread_size // max(1, near_count)
    rungs = [Rung(side, _snap(p), each) for p in prices[:near_count]]

    # Clamp the wall so it is always beyond the furthest near-spread rung.
    furthest_near = prices[near_count - 1]
    if side == "BUY":
        clamped_wall = max(TICK, min(wall_price, furthest_near - TICK))
    else:
        clamped_wall = min(MICRO - TICK, max(wall_price, furthest_near + TICK))
    rungs.append(Rung(side, _snap(clamped_wall), wall_size))
    return rungs


def build_ladder(
    mid_micro: int,
    *,
    rungs_per_side: int,
    wall_fraction: float,
    size_per_side_micro: int,
    best_bid_micro: int | None = None,
    best_ask_micro: int | None = None,
) -> list[Rung]:
    """U-shaped, strictly non-crossing ladder straddling `mid_micro`.

    Bids occupy (0, bid_ceiling], asks [ask_floor, MICRO); bid_ceiling is one
    tick below the lower of mid and any existing best_ask, ask_floor one tick
    above the higher of mid and any existing best_bid. `wall_fraction` of each
    side's size piles into the outer wall rung; the rest spreads near the touch.
    """
    wall_size = round(wall_fraction * size_per_side_micro)
    spread_size = size_per_side_micro - wall_size

    bid_ceiling = _snap(min(mid_micro, best_ask_micro or mid_micro) - TICK)
    ask_floor = _snap(max(mid_micro, best_bid_micro or mid_micro) + TICK)

    bids = _side_rungs(
        "BUY", ceiling=bid_ceiling, wall_price=_WALL_BID_PRICE,
        rungs_per_side=rungs_per_side, wall_size=wall_size, spread_size=spread_size,
    )
    asks = _side_rungs(
        "SELL", ceiling=ask_floor, wall_price=_WALL_ASK_PRICE,
        rungs_per_side=rungs_per_side, wall_size=wall_size, spread_size=spread_size,
    )
    return bids + asks
