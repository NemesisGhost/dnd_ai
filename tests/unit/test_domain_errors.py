"""Tests for dnd_ai.domain.errors — the SafeMessageError contract itself
(finding 4): raising SafeMessageError does not, by itself, make the
constructor's text safe to return to a client — only a subclass that
explicitly defines its own fixed `safe_message` exposes something more
specific than the base class's generic default.
"""

import pytest

from dnd_ai.domain.errors import DomainAuthorizationError, SafeMessageError

pytestmark = pytest.mark.unit


def test_bare_safe_message_error_never_echoes_constructor_text() -> None:
    secret_looking_text = "token=SUPER_SECRET_ABC123"
    exc = SafeMessageError(secret_looking_text)
    assert exc.safe_message == "The request could not be processed."
    assert secret_looking_text not in exc.safe_message


def test_bare_safe_message_error_retains_constructor_text_for_local_debugging_only() -> None:
    """str(exc) still carries whatever the constructor was given — but
    dnd_ai.api.errors never reads it for a response or a log line (see
    tests/unit/test_api_app.py's logging regressions); it exists purely
    for interactive/local debugging."""
    secret_looking_text = "token=SUPER_SECRET_ABC123"
    exc = SafeMessageError(secret_looking_text)
    assert str(exc) == secret_looking_text
    assert str(exc) != exc.safe_message


def test_bare_safe_message_error_defaults_to_400_validation_failed() -> None:
    exc = SafeMessageError("anything")
    assert exc.safe_status_code == 400
    assert exc.safe_error_code == "validation_failed"


def test_domain_authorization_error_never_echoes_constructor_text_either() -> None:
    secret_looking_text = "campaign 11111111-1111-1111-1111-111111111111 is forbidden"
    exc = DomainAuthorizationError(secret_looking_text)
    assert exc.safe_message == "The requested resource does not exist or is not accessible."
    assert secret_looking_text not in exc.safe_message


def test_domain_authorization_error_defaults_to_404_not_found() -> None:
    exc = DomainAuthorizationError("anything")
    assert exc.safe_status_code == 404
    assert exc.safe_error_code == "not_found"


def test_a_subclass_may_define_its_own_fixed_safe_message() -> None:
    """The deliberate opt-in path: a subclass fixes its own safe_message at
    the type level, independent of whatever the constructor argument was —
    proving the contract still supports exposing something specific once an
    author has vetted it, without reintroducing str(self) as the default."""

    class _KnownSafeError(SafeMessageError):
        safe_message = "no matching lookup row for a recognized code"
        safe_error_code = "not_found"
        safe_status_code = 404

    exc = _KnownSafeError("raw diagnostic text a client never sees")
    assert exc.safe_message == "no matching lookup row for a recognized code"
    assert exc.safe_message != str(exc)


def test_a_subclass_may_compute_safe_message_from_a_closed_vocabulary() -> None:
    """safe_message may also be computed, as long as it draws only from a
    closed, server-owned vocabulary — never from the constructor argument
    itself. resource_kind here is restricted to a fixed set of internal
    literals, never arbitrary caller-supplied text."""

    class _KnownResourceKindError(SafeMessageError):
        def __init__(self, message: str, *, resource_kind: str) -> None:
            super().__init__(message)
            if resource_kind not in {"quest", "character", "session"}:
                raise ValueError("resource_kind must be a recognized internal literal")
            self._resource_kind = resource_kind

        @property
        def safe_message(self) -> str:
            return f"No matching {self._resource_kind} was found."

    exc = _KnownResourceKindError(
        "raw diagnostic text with an internal id, never shown to a client",
        resource_kind="quest",
    )
    assert exc.safe_message == "No matching quest was found."
