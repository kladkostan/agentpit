"""Generated handles: the 15-character ceiling is the binding constraint."""
import random
import re

from agentpit.db.table_write import TableWrite
from agentpit.db.table_read import TableRead
from agentpit.domain.handles import (
    ADJECTIVES,
    MAX_ATTEMPTS,
    NOUNS,
    PLAIN_ATTEMPTS,
    generate_handle,
    pick_handle,
)
from tests.db_helpers import fresh_test_conn

HANDLE_RE = re.compile(r"[a-zA-Z0-9_]{1,15}")


def test_every_possible_pair_is_a_valid_handle():
    """Asserted over the WHOLE cross product, not a sample: a single overlong
    word would otherwise sit in the list for months and surface as a 422 on
    somebody's signup. 120 x 120 is 14,400 pairs and runs in milliseconds."""
    assert len(ADJECTIVES) >= 100 and len(NOUNS) >= 100
    for a in ADJECTIVES:
        for n in NOUNS:
            pair = a + n
            assert HANDLE_RE.fullmatch(pair), pair


def test_every_suffixed_pair_is_also_a_valid_handle():
    """The suffix tier is the part that can overflow 15 characters, so it gets
    the same exhaustive treatment. The longest suffix is four digits."""
    rng = random.Random(7)
    for a in ADJECTIVES:
        for n in NOUNS:
            longest = (a + n)[: 15 - 4] + "9999"
            assert HANDLE_RE.fullmatch(longest), longest
    # And the real generator, on a suffix-tier attempt, agrees.
    handle = generate_handle(rng, attempt=PLAIN_ATTEMPTS)
    assert HANDLE_RE.fullmatch(handle)
    assert handle[-4:].isdigit()


def test_plain_attempts_are_two_words_with_no_digits():
    rng = random.Random(1)
    handle = generate_handle(rng, attempt=0)
    assert HANDLE_RE.fullmatch(handle)
    assert not any(c.isdigit() for c in handle)
    assert any(handle.startswith(a) for a in ADJECTIVES)


def test_pick_handle_returns_a_free_name():
    assert pick_handle(taken=lambda h: False, rng=random.Random(3))


def test_pick_handle_skips_taken_names():
    """A collision must not surface to the user. The first two candidates are
    claimed; the third is free and is what comes back."""
    seen: list[str] = []

    def taken(h: str) -> bool:
        seen.append(h)
        return len(seen) <= 2

    result = pick_handle(taken=taken, rng=random.Random(5))
    assert result == seen[-1]
    assert len(seen) == 3


def test_pick_handle_falls_back_to_a_numeric_suffix():
    """Once the plain space is exhausted the suffix tier takes over, which is
    what stops a busy instance from failing registrations outright."""
    result = pick_handle(
        taken=lambda h: not any(c.isdigit() for c in h),
        rng=random.Random(11),
    )
    assert result[-4:].isdigit()
    assert HANDLE_RE.fullmatch(result)


def test_pick_handle_gives_up_rather_than_looping_forever():
    attempts: list[str] = []

    def taken(h: str) -> bool:
        attempts.append(h)
        return True

    try:
        pick_handle(taken=taken, rng=random.Random(13))
        raise AssertionError("expected pick_handle to raise")
    except RuntimeError:
        pass
    assert len(attempts) == MAX_ATTEMPTS


def test_handle_taken_reads_the_unique_column():
    conn = fresh_test_conn()
    TableWrite.create_user(
        conn, email="taken@example.com", password_hash="x", handle="BoldRiver"
    )
    assert TableRead.handle_taken(conn, "BoldRiver") is True
    assert TableRead.handle_taken(conn, "MistyCove") is False
    conn.close()
