"""Structure and pure-policy pins for P03-A A4a (decision D6): the draft flags stay out of every text
path, and the commands-layer view-tier predicate cannot drift from the API's."""

import itertools
import uuid

import pytest

from dnd_ai.api.access import CharacterViewNotAuthorizedError, resolve_character_view_tier
from dnd_ai.domain.access import AccessContext
from dnd_ai.domain.public_profiles import (
    PUBLIC_PROFILE_IDENTITY_FLAGS,
    PUBLIC_PROFILE_SAVEABLE_FIELDS,
    holds_character_view_tier,
)


def test_the_flags_are_booleans_held_apart_from_every_text_field() -> None:
    assert set(PUBLIC_PROFILE_IDENTITY_FLAGS) == {"publish_species", "publish_size"}
    assert set(PUBLIC_PROFILE_IDENTITY_FLAGS.values()) == {
        "should_publish_species",
        "should_publish_size",
    }
    assert not set(PUBLIC_PROFILE_IDENTITY_FLAGS) & set(PUBLIC_PROFILE_SAVEABLE_FIELDS)
    assert PUBLIC_PROFILE_SAVEABLE_FIELDS == (
        "public_appearance",
        "public_background",
        "public_summary",
    )


def _access(character_id: uuid.UUID, *capabilities: str) -> AccessContext:
    return AccessContext(
        user_id=uuid.uuid4(),
        campaign_id=uuid.uuid4(),
        campaign_membership_id=uuid.uuid4(),
        timeline_id=uuid.uuid4(),
        role_capabilities=frozenset(c for c in capabilities if c == "canon.edit"),
        character_capabilities={
            character_id: frozenset(c for c in capabilities if c != "canon.edit")
        },
        grant_effects={},
    )


@pytest.mark.parametrize(
    "held",
    [
        combo
        for size in range(4)
        for combo in itertools.combinations(
            ("canon.edit", "character.view_full", "character.view_summary"), size
        )
    ],
)
def test_holds_character_view_tier_agrees_with_resolve_character_view_tier(
    held: tuple[str, ...],
) -> None:
    """The commands and queries layers cannot import `api.access`, so the predicate mirrors it; if
    one changes, this fails."""
    character = uuid.uuid4()
    access = _access(character, *held)
    try:
        resolve_character_view_tier(access, character_id=character)
        resolved = True
    except CharacterViewNotAuthorizedError:
        resolved = False
    assert holds_character_view_tier(access, character) is resolved is bool(held)
