"""R01 S5-C structural pins: nothing in production adopts the deferral mechanism yet, only
`begin_idempotent_request` records a reservation outcome, and the replay declaration is the one empty
declaration.

These pins move only with the reviewed slice that adopts the mechanism: a route must not opt in before S5-C
has passed its independent review (plan section 6.21.4, item 5). S5-C passed (plan section 6.25); S5-D, the
two invitation routes, is the only adopter so far.
"""

import re
from pathlib import Path

import pytest

from dnd_ai.domain.authorization_steps import (
    REPLAY_DECLARATION,
    DeclarationError,
    PreWriteDeclaration,
)

SRC = Path(__file__).resolve().parents[2] / "src" / "dnd_ai"

# The mechanism's own modules and the one recorder.
_MECHANISM = {
    SRC / "domain" / "authorization.py",
    SRC / "domain" / "authorization_steps.py",
    SRC / "domain" / "reservation_outcome.py",
}
_RECORDER = SRC / "api" / "idempotency.py"


def _sources() -> list[Path]:
    return [p for p in SRC.rglob("*.py") if "__pycache__" not in p.parts]


#: Who may use each entry point outside the mechanism. S5-C adopted nothing; S5-D (the two invitation
#: routes) is the first adopter and S5-E1 (the three campaign lifecycle routes) the second. A later slice
#: adds its files here, in a reviewed edit.
_S5D_ADOPTERS = {
    r"\.defer_reservation_campaign_fk\(": {"api/campaign_invitations.py", "api/campaigns.py"},
    r"\.bind_reservation\(": {"api/campaign_invitations.py", "api/campaigns.py"},
    r"\.bind_unkeyed\(": {"api/campaign_invitations.py", "api/campaigns.py"},
    r"\bby_outcome\s*=": {"api/r01_route_plans.py"},
    r"\bReservationDeclarations\(": {
        "commands/access_grant_plans.py",
        "commands/access_group_plans.py",
        "commands/campaign_invitation_plans.py",
        "commands/campaign_lifecycle_plans.py",
        "commands/membership_end_plans.py",
        "commands/membership_role_plans.py",
    },
    r"SET\s+CONSTRAINTS": set(),
}


@pytest.mark.parametrize("pattern", list(_S5D_ADOPTERS))
def test_no_production_code_outside_the_mechanism_and_the_reviewed_adopters_uses_it(
    pattern: str,
) -> None:
    regex = re.compile(pattern, re.IGNORECASE)
    users = {
        path.relative_to(SRC).as_posix()
        for path in _sources()
        if path not in _MECHANISM and regex.search(path.read_text(encoding="utf-8"))
    }
    assert users == _S5D_ADOPTERS[pattern], f"{pattern} is used outside the reviewed set: {users}"


def test_only_begin_idempotent_request_records_an_outcome() -> None:
    callers = [
        str(path.relative_to(SRC))
        for path in _sources()
        if re.search(r"\brecord_reservation_outcome\(", path.read_text(encoding="utf-8"))
        and path not in _MECHANISM
    ]
    assert callers == [str(_RECORDER.relative_to(SRC))]
    body = _RECORDER.read_text(encoding="utf-8")
    start = body.index("def begin_idempotent_request")
    end = body.index("def complete_idempotent_request")
    assert body[start:end].count("record_reservation_outcome(") == 2  # new reservation, replay
    assert body.count("record_reservation_outcome(") == 2  # and nowhere else in the module


def test_the_replay_declaration_is_the_only_empty_one() -> None:
    assert REPLAY_DECLARATION.replay
    assert REPLAY_DECLARATION.steps == () and REPLAY_DECLARATION.locks == ()
    with pytest.raises(DeclarationError):
        PreWriteDeclaration(locks=(), steps=())
