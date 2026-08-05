"""Two-word display handles, generated at registration.

Almost nobody sets a handle, and `display_name` falls back to a truncated
address -- so a leaderboard of accounts that never touched the field renders
as a column of hex strings. Every account gets a name it can change instead
of a blank it has to notice.

The 15-character limit that `RegisterRequest` and `UpdateHandleRequest`
enforce is the binding constraint. The lists are curated to seven characters
and under rather than filtered at generation time, so a pair that would not
validate cannot be produced in the first place -- and the test asserts that
over the whole cross product rather than a sample.

Two lists of 120 give 14,400 pairs with no dependency and no
`/usr/share/dict`, which the API's container image does not reliably have.
"""
import random
from typing import Callable

MAX_HANDLE_LEN = 15
"""Ceiling from the `[a-zA-Z0-9_]{1,15}` validator on both handle requests."""

PLAIN_ATTEMPTS = 4
"""Tries before falling back to a numeric suffix."""

MAX_ATTEMPTS = 6
"""Total tries. Bounded so a saturated name space fails loudly, not forever."""

_SUFFIX_DIGITS = 4

ADJECTIVES: tuple[str, ...] = (
    "Amber", "Ample", "Arctic", "Ashen", "Autumn", "Azure", "Balmy", "Bold",
    "Brave", "Brief", "Bright", "Brisk", "Calm", "Candid", "Chief", "Civic",
    "Clear", "Clever", "Copper", "Coral", "Cosmic", "Crisp", "Curious",
    "Daring", "Deep", "Dense", "Dewy", "Dizzy", "Dusty", "Eager", "Early",
    "Easy", "Eerie", "Elder", "Empty", "Even", "Exact", "Fair", "Fancy",
    "Fast", "Fine", "First", "Fleet", "Fluid", "Fond", "Frank", "Free",
    "Fresh", "Full", "Gentle", "Giant", "Glad", "Golden", "Grand", "Grave",
    "Great", "Green", "Grey", "Happy", "Hardy", "Hazy", "Hidden", "High",
    "Hollow", "Honest", "Humble", "Icy", "Idle", "Ivory", "Jolly", "Keen",
    "Kind", "Late", "Lean", "Light", "Little", "Live", "Lively", "Lone",
    "Long", "Loud", "Loyal", "Lucid", "Lucky", "Main", "Major", "Mellow",
    "Merry", "Mighty", "Mild", "Minor", "Misty", "Modest", "Mute", "Neat",
    "New", "Next", "Nimble", "Noble", "North", "Odd", "Olive", "Open",
    "Pale", "Patient", "Plain", "Polar", "Prime", "Proud", "Pure", "Quick",
    "Quiet", "Rapid", "Rare", "Ready", "Real", "Rich", "Right", "Rosy",
    "Round",
)

NOUNS: tuple[str, ...] = (
    "Anchor", "Apex", "Arbor", "Arrow", "Atlas", "Aurora", "Badge", "Basin",
    "Beacon", "Birch", "Bloom", "Bolt", "Bridge", "Brook", "Cable", "Cactus",
    "Canyon", "Cedar", "Chart", "Cliff", "Cloud", "Coast", "Comet", "Cove",
    "Crane", "Crest", "Crown", "Dawn", "Delta", "Dune", "Eagle", "Ember",
    "Falcon", "Fern", "Field", "Flame", "Flint", "Forest", "Fox", "Gale",
    "Garden", "Gate", "Glade", "Globe", "Grove", "Gulf", "Harbor", "Haven",
    "Hawk", "Hedge", "Heron", "Hill", "Ibex", "Inlet", "Iris", "Island",
    "Ivy", "Jade", "Jetty", "Key", "Lake", "Ledge", "Lemur", "Lily", "Lynx",
    "Maple", "Marsh", "Meadow", "Mesa", "Mint", "Moss", "Nest", "Nova",
    "Oak", "Oasis", "Ocean", "Onyx", "Orbit", "Orchid", "Otter", "Palm",
    "Peak", "Pearl", "Pebble", "Pine", "Plume", "Pond", "Quarry", "Quartz",
    "Quill", "Raven", "Reef", "Ridge", "River", "Robin", "Rock", "Sand",
    "Shore", "Signal", "Slate", "Snow", "Spark", "Spire", "Spring", "Spruce",
    "Star", "Stone", "Storm", "Stream", "Summit", "Swan", "Tide", "Timber",
    "Torch", "Trail", "Tulip", "Tundra", "Valley", "Vine", "Vista",
)


def generate_handle(rng, attempt: int = 0) -> str:
    """One candidate. `attempt` selects the tier, not the words.

    The first `PLAIN_ATTEMPTS` are a bare pair -- at most 13 characters, since
    the longest adjective is 7 and the longest noun 6. Later attempts append
    four digits and slice the pair to fit, which widens the space from 14,400
    to 144 million. The slice is what keeps the result inside 15 characters no
    matter which pair came up; it costs at most two characters off the noun
    and only on a tier reached after four collisions.
    """
    pair = rng.choice(ADJECTIVES) + rng.choice(NOUNS)
    if attempt < PLAIN_ATTEMPTS:
        return pair
    suffix = f"{rng.randrange(10**_SUFFIX_DIGITS):0{_SUFFIX_DIGITS}d}"
    return pair[: MAX_HANDLE_LEN - len(suffix)] + suffix


def pick_handle(taken: Callable[[str], bool], rng=random) -> str:
    """A handle nobody holds, or `RuntimeError` after `MAX_ATTEMPTS` tries.

    `taken` is a predicate rather than a connection so the retry logic can be
    tested without a database. Raising beats looping: a name space this large
    cannot exhaust six draws by chance, so six failures mean something else is
    wrong and a hung registration would hide it.
    """
    for attempt in range(MAX_ATTEMPTS):
        candidate = generate_handle(rng, attempt)
        if not taken(candidate):
            return candidate
    raise RuntimeError(
        f"no free handle after {MAX_ATTEMPTS} attempts"
    )
