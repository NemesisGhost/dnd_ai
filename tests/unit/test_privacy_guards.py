"""Phase 16 prerequisites enforced in code (checkpoint 15.2A-5, ADR 0016).

No player-private feature exists; these tests pin the boundaries one would have
to cross to build one unsafely.
"""

import logging

import pytest
from fastapi.testclient import TestClient

from dnd_ai.api.app import create_app
from dnd_ai.api.preview import PREVIEW_ADAPTERS
from dnd_ai.domain.data_classification import (
    AUDIT_STRUCTURAL_FIELDS,
    COLUMN_CLASSES,
    DataClass,
    audit_diff,
    audit_initial,
)

pytestmark = pytest.mark.unit

SENTINEL = "ZQX-LOGGED-BODY-SENTINEL-5519"


def test_no_column_is_classified_player_private_or_secret_in_phase_15() -> None:
    classes = set(COLUMN_CLASSES.values())
    assert DataClass.PLAYER_PRIVATE not in classes
    assert DataClass.SECRET not in classes


def test_player_private_values_would_be_redacted_by_every_audit_builder() -> None:
    # Whatever a future private field is called, it is not structural, so the
    # default-deny builders record only that it changed.
    for field in ("private_note", "theory_text", "discussion_body", "shared_snapshot"):
        assert field not in AUDIT_STRUCTURAL_FIELDS
        assert SENTINEL not in str(audit_initial({field: SENTINEL}))
        assert SENTINEL not in str(audit_diff({}, {field: SENTINEL}))
        assert audit_initial({field: SENTINEL}) == {field: {"redacted": True}}


def test_no_preview_adapter_can_expose_private_data() -> None:
    for adapter in PREVIEW_ADAPTERS.values():
        assert DataClass.PLAYER_PRIVATE not in adapter.ceiling
        assert DataClass.SECRET not in adapter.ceiling


def test_a_rejected_request_body_is_never_logged_or_echoed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A validation failure on a body carrying a sentinel neither echoes it in
    the response nor writes it to any log record (errors log class, status,
    code, correlation id, and route template only)."""
    app = create_app()
    caplog.set_level(logging.DEBUG)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/auth/login",
            json={"login_name": SENTINEL, "unexpected_field": SENTINEL},
            headers={"Origin": "http://localhost:5173"},
        )
    # Reaches request validation (not an Origin/CSRF refusal), so the handler under
    # test is the one that ran.
    assert response.status_code in (400, 422), response.text
    assert SENTINEL not in response.text
    assert SENTINEL not in caplog.text
    assert all(SENTINEL not in record.getMessage() for record in caplog.records)
