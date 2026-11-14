"""R01 S5-C structural pins: nothing in production adopts the deferral mechanism yet, only
`begin_idempotent_request` records a reservation outcome, and the replay declaration is the one empty
declaration.

These pins move only with the reviewed slice that adopts the mechanism (S5-D onward): a route must not
opt in before S5-C has passed its independent review (plan section 6.21.4, item 5).
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


@pytest.mark.parametrize(
    "pattern",
    [
        r"\.defer_reservation_campaign_fk\(",
        r"\.bind_reservation\(",
        r"\.bind_unkeyed\(",
        r"\bby_outcome\s*=",
        r"\bReservationDeclarations\(",
        r"SET\s+CONSTRAINTS",
    ],
)
def test_no_production_code_outside_the_mechanism_uses_it(pattern: str) -> None:
    regex = re.compile(pattern, re.IGNORECASE)
    users = [
        str(path.relative_to(SRC))
        for path in _sources()
        if path not in _MECHANISM and regex.search(path.read_text(encoding="utf-8"))
    ]
    assert users == [], f"{pattern} is used outside the S5-C mechanism: {users}"


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
