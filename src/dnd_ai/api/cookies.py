"""Browser-session cookie naming and attributes (docs/PLAN.md §23.4).

Production uses the `__Host-` prefixed cookie name, which browsers refuse
to set unless the response also carries `Secure`, `Path=/`, and no `Domain`
attribute — the prefix enforces its own contract structurally, not merely
by convention, so `session_cookie_set_kwargs()` setting those three
attributes together with that name is not optional configuration, it is
what makes the name usable at all.

Local/test uses a separate, unprefixed cookie name without `Secure`, so a
developer's plain-HTTP loopback session still works — docs/PLAN.md §23.4:
"A development-only cookie name/configuration may omit Secure strictly on
loopback." `dnd_ai.api.local_auth`/`dnd_ai.api.auth` both call
`session_cookie_name()` rather than hardcoding either literal, so the two
modules (setting the cookie at login/clearing it at logout, and reading it
on every authenticated request) can never drift onto different names.
"""

from dnd_ai.config import settings

PRODUCTION_SESSION_COOKIE_NAME = "__Host-dnd_ai_session"
DEV_SESSION_COOKIE_NAME = "dnd_ai_session"


def session_cookie_name() -> str:
    return (
        PRODUCTION_SESSION_COOKIE_NAME
        if settings.environment == "production"
        else DEV_SESSION_COOKIE_NAME
    )


def session_cookie_set_kwargs() -> dict[str, object]:
    """Keyword arguments for `Response.set_cookie(key=session_cookie_name(),
    value=..., **session_cookie_set_kwargs())`. Production sets `secure=True`
    and omits `domain` entirely (required by the `__Host-` prefix, which
    `session_cookie_name()` returns only in production); local/test omits
    `secure` so a plain-HTTP loopback session still works. `samesite="lax"`
    in both — docs/PLAN.md §23.4's own documented cookie attributes — is
    the first line of cross-site request defense; the CSRF double-submit
    check (`dnd_ai.api.local_auth.require_csrf`) is the second, since
    `SameSite=Lax` alone still permits a plain top-level-navigation GET."""
    return {
        "httponly": True,
        "samesite": "lax",
        "secure": settings.environment == "production",
        "path": "/",
    }
