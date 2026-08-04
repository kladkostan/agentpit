"""The public board. Served from memory; the chain work happens on a timer."""
import time

from fastapi import APIRouter, Query
from pydantic import BaseModel

from agentpit.api.deps import LeaderboardServiceDep
from agentpit.services.leaderboard_service import SORTS, rank_rows

router = APIRouter(tags=["leaderboard"])

# Same shape as routes/events.py's listing cache: the board only changes when
# the valuation pass runs, and the Arena polls every four seconds.
_CACHE_TTL_SECONDS = 30.0
_board_cache: "dict[str, tuple[float, list[dict]]]" = {}


class LeaderboardEntry(BaseModel):
    rank: int
    name: str
    address: str
    capital: str
    earned: str
    returnPct: float
    trades: int
    isHouseAgent: bool


class LeaderboardResponse(BaseModel):
    sort: str
    entries: "list[LeaderboardEntry]"


@router.get("/leaderboard", response_model=LeaderboardResponse)
def get_leaderboard(
    service: LeaderboardServiceDep,
    sort: str = Query(default="return"),
) -> LeaderboardResponse:
    """Rank every account that has traded.

    `sort` is one of return, earned, capital, trades; anything else falls back
    to return. Amounts are base-unit integer strings, matching the rest of the
    API. No email address appears in this payload under any sort.
    """
    key = sort if sort in SORTS else "return"
    now = time.monotonic()
    hit = _board_cache.get(key)
    if hit is not None and now - hit[0] < _CACHE_TTL_SECONDS:
        return LeaderboardResponse(sort=key, entries=hit[1])

    ranked = rank_rows(service.build_board(), key)
    entries = [
        LeaderboardEntry(
            rank=i + 1,
            name=row.name,
            address=row.address,
            capital=str(row.capital_raw),
            earned=str(row.earned_raw),
            returnPct=round(row.return_pct, 2),
            trades=row.trades,
            isHouseAgent=row.is_house_agent,
        ).model_dump()
        for i, row in enumerate(ranked)
    ]
    _board_cache[key] = (now, entries)
    return LeaderboardResponse(sort=key, entries=entries)
