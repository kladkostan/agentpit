"""The tick prunes as well as writes.

`prune_account_snapshots` shipped tested and uncalled -- the loop that writes
288 rows per account per day had no caller for the one that deletes them. A
unit test of the pruning function would have stayed green through all of that,
so this asserts the wiring instead: that the tick calls it, and with a cutoff
derived from the configured retention rather than some other number.
"""
from agentpit.api.app import _run_leaderboard_tick


class _SpyService:
    def __init__(self):
        self.snapshot_at: int | None = None
        self.pruned_before: int | None = None

    def take_snapshot(self, now: int) -> int:
        self.snapshot_at = now
        return 3

    def prune_old(self, older_than: int) -> int:
        self.pruned_before = older_than
        return 7


def test_the_tick_writes_and_prunes():
    service = _SpyService()
    written, deleted = _run_leaderboard_tick(service, retention_seconds=86_400)

    assert (written, deleted) == (3, 7)
    assert service.snapshot_at is not None
    assert service.pruned_before == service.snapshot_at - 86_400
