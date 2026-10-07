"""Request-scoped world-capability enforcement for `/worlds/{world_id}/…`.

The world analogue of `dnd_ai.api.access.require_campaign_capability`: it
turns a path-supplied `world_id` plus the authenticated caller into a
`WorldAuthority` (or a mapped `ApiError`), so no router re-derives the join.

Rules (docs/PLAN.md Phase 14, §8):

- **Humans only.** The dependency builds on `require_human_user_id`, so a
  Foundry device principal gets 403 and a machine principal never reaches it.
  Principal separation is not weakened anywhere: world authority is held by
  `security.users` rows through `security.world_memberships`, never by
  `AuthenticatedPrincipal` kind.
- **Non-disclosing.** No authority — including a nonexistent world and an
  unclaimed legacy world — is a 404, identical in every case. A caller who
  *has* authority but lacks the capability gets 403 — a `world_viewer`
  calling any `world.manage`/`timeline.manage` route.
- **Re-checked at mutation time.** The returned `WorldAuthority` is a
  presentation-grade snapshot; commands re-resolve and re-check lifecycle
  under their own row locks, so nothing trusts this lookup for a write.
- Archived worlds remain readable and restorable by their owners.
"""

import uuid
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends
from sqlalchemy import Connection

from dnd_ai.domain.world_authority import WorldAuthority
from dnd_ai.queries.world_authority import resolve_world_authority

from .auth import require_human_user_id
from .deps import get_connection
from .errors import ForbiddenError, NotFoundError


def require_world_capability(
    capability_code: str,
) -> Callable[[uuid.UUID, uuid.UUID, Connection], WorldAuthority]:
    """Returns a FastAPI dependency requiring `capability_code` on the world
    named by the route's `world_id` path parameter."""

    def _dependency(
        world_id: uuid.UUID,
        user_id: Annotated[uuid.UUID, Depends(require_human_user_id)],
        connection: Annotated[Connection, Depends(get_connection)],
    ) -> WorldAuthority:
        authority = resolve_world_authority(connection, user_id=user_id, world_id=world_id)
        if authority is None:
            raise NotFoundError()
        if not authority.has_capability(capability_code):
            raise ForbiddenError()
        return authority

    _dependency.capability_code = capability_code  # type: ignore[attr-defined]
    return _dependency
