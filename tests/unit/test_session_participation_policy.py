"""The session participant role catalog (domain/session_participation.py)."""

import pytest

from dnd_ai.domain.session_authoring import PARTICIPATION_ROLES, ParticipantRoleMismatchError
from dnd_ai.domain.session_participation import (
    PARTICIPANT_KINDS,
    participant_role_options,
    participant_roles_for_kind,
)


def test_each_kind_takes_its_own_role_or_guest() -> None:
    assert participant_roles_for_kind("player_character") == ("player_character", "guest")
    assert participant_roles_for_kind("npc") == ("npc", "guest")


@pytest.mark.parametrize("kind", [None, "", "location", "organization", "monster"])
def test_unknown_kinds_have_no_roles(kind: str | None) -> None:
    assert participant_roles_for_kind(kind) == ()


def test_catalog_matches_the_policy_and_stays_inside_the_role_vocabulary() -> None:
    catalog = participant_role_options()
    assert set(catalog) == set(PARTICIPANT_KINDS)
    for kind, roles in catalog.items():
        assert tuple(roles) == participant_roles_for_kind(kind)
        assert set(roles) <= set(PARTICIPATION_ROLES)


def test_mismatch_is_distinct_from_an_unusable_character() -> None:
    assert ParticipantRoleMismatchError.safe_error_code == "session_participant_role_mismatch"
    assert ParticipantRoleMismatchError.safe_status_code == 400
