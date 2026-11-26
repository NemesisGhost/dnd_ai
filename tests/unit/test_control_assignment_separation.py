"""P15-C11-S01-T02: control assignments never reach a campaign capability check (E31).

Plan section 3.2 item 3a, "What is exempted, precisely". The final check of the three clock routes judges
`route.canon.edit` and `campaign.canon.edit`. Both read the role capabilities only: the closed matrix, the
`control_assignments` source and the clock key a decision used feed nothing a targetless capability check reads.
"""

import itertools
import uuid
from datetime import UTC, datetime

import pytest

from dnd_ai.api.access import route_capability_requirement
from dnd_ai.commands._content import canon_edit_requirement
from dnd_ai.domain.access import (
    BUILTIN_RELATIONSHIP_CAPABILITIES,
    CONTROL_ASSIGNMENT_CAPABILITIES,
    AccessContext,
    AuthoritySnapshot,
    ControlAssignmentSource,
)

pytestmark = pytest.mark.unit

_USER = uuid.uuid4()
_CAMPAIGN = uuid.uuid4()
_CHARACTER = uuid.uuid4()
_EVERY_CHARACTER_CODE = frozenset().union(
    *CONTROL_ASSIGNMENT_CAPABILITIES.values(), *BUILTIN_RELATIONSHIP_CAPABILITIES.values()
)


def _snapshot(
    *,
    roles: frozenset[str],
    character_codes: frozenset[str],
    assignments: bool,
    key: int | None,
) -> AuthoritySnapshot:
    access = AccessContext(
        user_id=_USER,
        campaign_id=_CAMPAIGN,
        campaign_membership_id=uuid.uuid4(),
        timeline_id=uuid.uuid4(),
        role_capabilities=roles,
        character_capabilities={_CHARACTER: character_codes} if character_codes else {},
        grant_effects={},
        control_assignments=(
            {_CHARACTER: ControlAssignmentSource(uuid.uuid4(), "primary_controller", "ongoing")}
            if assignments
            else {}
        ),
        control_clock_key=key,
    )
    return AuthoritySnapshot(
        t_auth=datetime(2031, 1, 1, tzinfo=UTC), isolation="read committed", access=access
    )


def _requirements() -> list[object]:
    return [
        route_capability_requirement(
            capability_code="canon.edit",
            allow_archived_campaign=False,
            world_capability=None,
            world_id=None,
            actor_user_id=_USER,
        ),
        canon_edit_requirement(_USER, _CAMPAIGN),
    ]


_COMBINATIONS = list(
    itertools.product((frozenset(), _EVERY_CHARACTER_CODE), (False, True), (None, 144000))
)


@pytest.mark.parametrize(("character_codes", "assignments", "key"), _COMBINATIONS)
def test_canon_edit_is_refused_whatever_the_control_fields_hold(
    character_codes: frozenset[str], assignments: bool, key: int | None
) -> None:
    snapshot = _snapshot(
        roles=frozenset(), character_codes=character_codes, assignments=assignments, key=key
    )
    for requirement in _requirements():
        assert requirement.predicate(snapshot) is False  # type: ignore[attr-defined]
    assert snapshot.access is not None
    for code in CONTROL_ASSIGNMENT_CAPABILITIES["primary_controller"]:
        assert snapshot.access.has_capability(code) is False


@pytest.mark.parametrize(("character_codes", "assignments", "key"), _COMBINATIONS)
def test_canon_edit_from_the_role_holds_whatever_the_control_fields_hold(
    character_codes: frozenset[str], assignments: bool, key: int | None
) -> None:
    snapshot = _snapshot(
        roles=frozenset({"canon.edit"}),
        character_codes=character_codes,
        assignments=assignments,
        key=key,
    )
    for requirement in _requirements():
        assert requirement.predicate(snapshot) is True  # type: ignore[attr-defined]
