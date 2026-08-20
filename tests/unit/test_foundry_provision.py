"""Pure unit tests for `scripts/foundry_provision.py`'s response
classification (`_raise_for_envelope`) — no database, no HTTP client.
`httpx.Response` can be constructed directly from a status code and JSON
body with no real request behind it, so these exercise every status
branch precisely without needing `tests/database/test_foundry_
provision.py`'s real `TestClient`+PostgreSQL setup, which instead covers
the request-construction/end-to-end side of the same script.
"""

import httpx
import pytest
from foundry_provision import ProvisioningError, _raise_for_envelope, _validate_api_base_url

pytestmark = pytest.mark.unit


def _response(status_code: int, code: str, message: str) -> httpx.Response:
    return httpx.Response(status_code, json={"error": {"code": code, "message": message}})


def test_a_2xx_response_raises_nothing() -> None:
    _raise_for_envelope(httpx.Response(200, json={"ok": True}))
    _raise_for_envelope(httpx.Response(201, json={"ok": True}))


def test_401_mentions_the_token() -> None:
    with pytest.raises(ProvisioningError, match=r"401.*[Tt]oken"):
        _raise_for_envelope(_response(401, "unauthorized", "Authentication is required."))


def test_403_mentions_the_required_capability() -> None:
    with pytest.raises(ProvisioningError, match=r"403.*(canon\.edit|access\.manage)"):
        _raise_for_envelope(
            _response(403, "forbidden", "You do not have permission to perform this action.")
        )


def test_404_mentions_the_campaign_or_system_id() -> None:
    with pytest.raises(ProvisioningError, match=r"404.*(campaign|external system)"):
        _raise_for_envelope(
            _response(
                404, "not_found", "The requested resource does not exist or is not accessible."
            )
        )


def test_a_conflict_falls_through_to_the_generic_message() -> None:
    with pytest.raises(ProvisioningError, match=r"409.*conflict"):
        _raise_for_envelope(_response(409, "conflict", "conflict"))


def test_a_response_with_no_json_body_still_raises_a_readable_error() -> None:
    response = httpx.Response(500, content=b"not json")
    with pytest.raises(ProvisioningError, match=r"500"):
        _raise_for_envelope(response)


# ---------------------------------------------------------------------------
# _validate_api_base_url — Issue 2 (transport security): a FoundrySystem
# credential or OIDC bearer token must never be sent to a plain-HTTP,
# non-loopback host.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "https://dnd-ai.example.com",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://[::1]:8000",
    ],
)
def test_validate_api_base_url_accepts_https_or_loopback_http(value: str) -> None:
    _validate_api_base_url(value)  # must not raise


@pytest.mark.parametrize(
    "value",
    [
        "http://dnd-ai.example.com",
        "http://192.168.1.50:8000",
        "http://10.0.0.5:8000",
    ],
)
def test_validate_api_base_url_rejects_remote_or_lan_http(value: str) -> None:
    with pytest.raises(ProvisioningError, match=r"https://"):
        _validate_api_base_url(value)
