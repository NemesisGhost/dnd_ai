"""Explicit, framework-free error classification for domain code that needs
to control how its failures reach an API client (docs/architecture/
SYSTEM_ARCHITECTURE.md §5.4 — no HTTP or framework types in `domain/`, so
this expresses the classification as plain attributes on the exception
itself; `dnd_ai.api.errors` is what turns those into an actual HTTP
response).

By default, an unclassified `ValueError` raised anywhere in the domain or
command layers gets a fixed, non-disclosing message at the API boundary —
`str(exc)` is never echoed to a client, only logged server-side. A domain
error opts into exposing something more specific by subclassing one of the
two below; that is a deliberate choice a caller makes per error type, not
something every future endpoint has to remember to configure.
"""


class SafeMessageError(ValueError):
    """A `ValueError` whose own message (`str(self)`) is safe to return to
    an API client as-is — built entirely from server-known, non-secret,
    non-input-echoing text (a lookup code, a resource kind, an internal
    identifier), never from arbitrary caller-supplied input. Maps to HTTP
    400 by default; a subclass may override `safe_status_code`/
    `safe_error_code` for a more specific case.
    """

    safe_status_code: int = 400
    safe_error_code: str = "validation_failed"

    @property
    def safe_message(self) -> str:
        return str(self)


class DomainAuthorizationError(SafeMessageError):
    """A `SafeMessageError` whose own message is *not* safe to return —
    typically because it names specific identifiers whose relationship
    (e.g. "this timeline is not this campaign's") an unauthorized caller
    should not be able to infer even exists. `safe_message` is a fixed,
    generic string instead of `str(self)`; the detailed message remains
    available via `str(self)`/`repr(self)` for server-side logging only.
    Maps to HTTP 404 by default — "not found" rather than "forbidden",
    since confirming a resource exists but is off-limits can itself be a
    disclosure (docs/architecture/DATABASE_MODEL.md §19.7: "Inaccessible
    resources must be indistinguishable from nonexistent resources to
    unauthorized callers").
    """

    safe_status_code: int = 404
    safe_error_code: str = "not_found"

    @property
    def safe_message(self) -> str:
        return "The requested resource does not exist or is not accessible."
