"""Request-scoped campaign-capability enforcement for command endpoints
(docs/architecture/DATABASE_MODEL.md §19.7, docs/PLAN.md Phase 10 deliverable
"command endpoints over the existing command/application services").

`dnd_ai.domain.access.resolve_access_context` already centralizes role,
character-relationship, and resource-grant resolution into one
`AccessContext`; this module is the thin FastAPI-specific wiring that turns
a path-supplied `campaign_id` plus the authenticated caller into that
context (or a mapped `ApiError`), so individual routers never re-derive the
same `security.*` joins or invent their own authorization shape.

A missing/non-authorizing membership and an unrecognized capability are
deliberately mapped differently, per `dnd_ai.api.errors.ForbiddenError`'s
own docstring ("prefer NotFoundError when revealing that a resource exists
at all would itself be a disclosure"): no active membership resolves to
`NotFoundError` (a non-member cannot distinguish "this campaign doesn't
exist" from "you have no access to it"), while an authenticated member who
simply lacks the required capability — membership itself is already not in
question — gets `ForbiddenError`.
"""

import uuid
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends
from sqlalchemy import Connection

from dnd_ai.domain.access import AccessContext, resolve_access_context

from .auth import get_authenticated_user_id
from .deps import get_connection
from .errors import ForbiddenError, NotFoundError


def require_campaign_capability(
    capability_code: str,
) -> Callable[[uuid.UUID, uuid.UUID, Connection], AccessContext]:
    """Returns a FastAPI dependency requiring `capability_code` (role- or
    character-relationship-derived, per `AccessContext.has_capability`) in
    the campaign named by the route's own `campaign_id` path parameter.

    Resolves access against the campaign's own pinned timeline only — never
    a caller-supplied timeline — matching `resolve_access_context`'s own
    scope rule; no route built on this dependency accepts a `timeline_id`
    from the request."""

    def _dependency(
        campaign_id: uuid.UUID,
        user_id: Annotated[uuid.UUID, Depends(get_authenticated_user_id)],
        connection: Annotated[Connection, Depends(get_connection)],
    ) -> AccessContext:
        access = resolve_access_context(connection, user_id=user_id, campaign_id=campaign_id)
        if access is None:
            raise NotFoundError()
        if not access.has_capability(capability_code):
            raise ForbiddenError()
        return access

    return _dependency
