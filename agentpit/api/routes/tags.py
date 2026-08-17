import time

from fastapi import APIRouter

from agentpit.api.deps import EventServiceDep
from agentpit.datastructures.tag import ListTagsResponse

router = APIRouter(tags=["tags"])

# The taxonomy only moves when a sync runs, an hour apart, while the markets
# page requests this on every mount. The endpoint takes no parameters, so one
# slot is the whole cache — no key, no eviction policy, no unbounded growth.
_TAGS_TTL_S = 30.0
_tags_cache: tuple[float, ListTagsResponse] | None = None


@router.get("/tags", response_model=ListTagsResponse)
def list_tags(service: EventServiceDep) -> ListTagsResponse:
    global _tags_cache
    now = time.monotonic()
    hit = _tags_cache
    if hit is not None and now - hit[0] < _TAGS_TTL_S:
        return hit[1]
    result = service.list_tags()
    _tags_cache = (now, result)
    return result
