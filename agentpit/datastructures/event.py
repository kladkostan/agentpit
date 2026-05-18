from typing import Optional
from pydantic import BaseModel

from agentpit.common import check_state


class Event(BaseModel):
    event_id: int
    slug: str
    title: str
    description: str = ""
    icon_url: Optional[str] = None
    category: Optional[str] = None
    start_date: Optional[int] = None
    end_date: Optional[int] = None
    polymarket_event_id: Optional[str] = None

    def model_post_init(self, _context):
        check_state(len(self.title) > 0, "Event title must not be empty")
        check_state(len(self.slug) > 0, "Event slug must not be empty")
