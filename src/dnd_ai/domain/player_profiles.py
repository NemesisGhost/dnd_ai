"""Campaign-scoped character player profiles: the field vocabulary and the read rule
(P03-A slice A5a, docs/PHASE15_P03A_A5_PLAYER_PROFILE_DESIGN_2026-11-11.md, decisions D13-D18).

A *player profile* is narrative a character's controllers write, per campaign, for the campaign's
GMs and for the character's eligible controllers. It is not world canon and not a GM-private store.
A5 is infrastructure: nothing in `src/` writes the profile tables (D18); the writer arrives with
P03-B.

**The read rule** (`may_read_player_profile`) is a disjunction of *independent* branches. A5 has one:
the GM branch, which is exactly `has_effective_character_canon_edit` (D15): the role `canon.edit`
in the route's campaign, with no whole-character deny and no `canon.edit` deny on the character.
Reveal authority confers nothing here, and neither does an `allow` grant of `canon.edit`.

P03-B adds the character's eligible, live, in-effect controllers as a **second, independent branch**
(`character.view_player_profile`, conferred by control). That branch must **not** require
`canon.edit`; it is OR-ed in beside the GM branch and never nested inside it. A5 adds no such
vocabulary, matrix entry or grant path.

The rule never consults the character's kind, a relationship type or a world role. Classification
(`CHARACTER_VISIBLE`) describes the content and grants no permission.

`boundaries` and `profile_notes` are not copy-eligible: no structured publication may carry them.
Nothing here prevents an authorized reader from retyping what they read into a public field.
"""

import uuid
from typing import Final

from .access import AccessContext
from .public_profiles import (
    LEGACY_ORIGINS,
    ORIGIN_PLAYER_PROFILE,
    PUBLIC_PROFILE_TEXT_MAX_LENGTH,
    has_effective_character_canon_edit,
)

PLAYER_PROFILE_TEXT_MAX_LENGTH: Final = PUBLIC_PROFILE_TEXT_MAX_LENGTH

# (internal code, label, copy eligible), in sort order. Pinned against migration 147's lookup by a
# unit test and a database test.
_FIELD_TABLE: Final = (
    ("portrayal_guidance", "Portrayal guidance", True),
    ("personality", "Personality", True),
    ("ideals", "Ideals", True),
    ("bonds", "Bonds", True),
    ("flaws", "Flaws", True),
    ("goals", "Goals", True),
    ("fears", "Fears", True),
    ("loyalties", "Loyalties", True),
    ("boundaries", "Boundaries", False),
    ("speech_patterns", "Speech patterns", True),
    ("profile_notes", "Notes for the GM and controllers", False),
)

PLAYER_PROFILE_FIELDS: Final = tuple(code for code, _label, _eligible in _FIELD_TABLE)
PLAYER_PROFILE_FIELD_LABELS: Final = {code: label for code, label, _eligible in _FIELD_TABLE}
COPY_ELIGIBLE_PLAYER_PROFILE_FIELDS: Final = tuple(
    code for code, _label, eligible in _FIELD_TABLE if eligible
)


def may_read_player_profile_as_gm(access: AccessContext, character_id: uuid.UUID) -> bool:
    """The GM branch (D15): effective character-scoped `canon.edit`, nothing else."""
    return has_effective_character_canon_edit(access, character_id)


def may_read_player_profile(access: AccessContext, character_id: uuid.UUID) -> bool:
    """Whether the caller may read the character's player profile in the access context's campaign.

    A disjunction of independent branches. P03-B's controller branch is added as a separate `or`;
    it must not require `canon.edit`."""
    return may_read_player_profile_as_gm(access, character_id)


# --- the per-origin source rule (A5b, decision D16) ---------------------------------------------------

SOURCE_RULE_LEGACY = "legacy"
SOURCE_RULE_PLAYER_PROFILE = "player_profile"


def source_rule_for_origin(origin_code: str) -> str | None:
    """Which source-read rule governs a restricted draft field of this origin, or `None` when the
    origin is not restricted (`authored`). Legacy origins keep `may_read_legacy_source` (by kind,
    D7-e); `player_profile` uses `may_read_player_profile`. A field is judged by its own origin, so a
    draft holding one of each is evaluated per field."""
    if origin_code in LEGACY_ORIGINS:
        return SOURCE_RULE_LEGACY
    if origin_code == ORIGIN_PLAYER_PROFILE:
        return SOURCE_RULE_PLAYER_PROFILE
    return None
