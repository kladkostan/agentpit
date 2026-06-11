"""The pinned-series fast re-quote loop re-mirrors only the current live
window(s) each tick, independent of the shared reconciler — so a window that
is live for ~5 min tracks the upstream book instead of freezing at its open
snapshot."""

import asyncio

import agentpit.api.app as app_module


class _FakeMirror:
    """Records the ids passed to fill_markets; returns 2 orders per market."""

    def __init__(self) -> None:
        self.calls: list[list[int]] = []

    async def fill_markets(self, ids: list[int]) -> int:
        self.calls.append(list(ids))
        return len(ids) * 2


def test_pin_requote_once_fills_current_window(monkeypatch):
    # db/settings are consumed only by the (monkeypatched) window lookup.
    monkeypatch.setattr(app_module, "_current_window_ids", lambda *_: [304, 305])
    mirror = _FakeMirror()
    placed = asyncio.run(
        app_module._pin_requote_once(db=None, settings=None, mirror=mirror)  # type: ignore[arg-type]
    )
    assert mirror.calls == [[304, 305]]  # exactly the live windows, re-quoted
    assert placed == 4


def test_pin_requote_once_noop_when_no_live_window(monkeypatch):
    monkeypatch.setattr(app_module, "_current_window_ids", lambda *_: [])
    mirror = _FakeMirror()
    placed = asyncio.run(
        app_module._pin_requote_once(db=None, settings=None, mirror=mirror)  # type: ignore[arg-type]
    )
    assert mirror.calls == []  # nothing live -> mirror left untouched
    assert placed == 0
