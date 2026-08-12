"""Explicit, framework-free error classification for domain code that needs
to control how its failures reach an API client (docs/architecture/
SYSTEM_ARCHITECTURE.md §5.4 — no HTTP or framework types in `domain/`, so
this expresses the classification as plain attributes on the exception
itself; `dnd_ai.api.errors` is what turns those into an actual HTTP
response).

By default, an unclassified `ValueError` raised anywhere in the domain or
command layers gets a fixed, non-disclosing message at the API boundary —
`str(exc)` is never echoed to a client, and never logged, only available
for interactive/local debugging. A domain error opts into exposing
something more specific by subclassing `SafeMessageError` below; that is a
deliberate choice a caller makes per error *type*, not something every
future endpoint has to remember to configure, and — critically — not
something a caller can do just by choosing what string to pass to the
constructor. See `SafeMessageError`'s own docstring for why.
"""


class SafeMessageError(ValueError):
    """A `ValueError` that can define a `safe_message` fixed to the
    exception *type*, safe to return to an API client and to log, instead
    of the base API-error handling's generic fallback.

    `safe_message` here is a plain, fixed class attribute — deliberately
    **not** derived from `str(self)`/the constructor argument. Passing
    text to the constructor never makes that text "safe" by itself: a call
    site could pass anything, including caller-influenced content, and
    nothing about merely raising `SafeMessageError` vets it. A subclass
    that has something genuinely safe and specific to say sets its own
    `safe_message` — either a fixed literal (as `DomainAuthorizationError`
    does below) or a message *computed* from a closed, server-owned
    vocabulary (e.g. one of a handful of internal literal resource-kind
    names — never from arbitrary caller-supplied input) by overriding
    `safe_message` as a `@property`. The constructor argument remains
    available via `str(self)`/`repr(self)` purely for local, interactive
    debugging; `dnd_ai.api.errors` never reads it for a response or a log
    line (see that module's `_log_error`).

    Maps to HTTP 400 by default; a subclass may override
    `safe_status_code`/`safe_error_code` for a more specific case.
    """

    safe_status_code: int = 400
    safe_error_code: str = "validation_failed"
    safe_message: str = "The request could not be processed."


class DomainAuthorizationError(SafeMessageError):
    """A `SafeMessageError` for a case where even confirming *why* a
    request was rejected — the specific identifiers or relationship
    involved — would itself be a disclosure to an unauthorized caller.
    `safe_message` is a fixed, generic string; the constructor argument
    remains available via `str(self)`/`repr(self)` for local debugging
    only, same as the base class. Maps to HTTP 404 by default — "not
    found" rather than "forbidden", since confirming a resource exists but
    is off-limits can itself be a disclosure (docs/architecture/
    DATABASE_MODEL.md §19.7: "Inaccessible resources must be
    indistinguishable from nonexistent resources to unauthorized
    callers").
    """

    safe_status_code: int = 404
    safe_error_code: str = "not_found"
    safe_message: str = "The requested resource does not exist or is not accessible."
