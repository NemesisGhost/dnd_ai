"""R01 route plans: opening the plan of a write route (plan section 6.5, rule 1b).

S1 provides the mechanism and the inventory. From S2, `require_campaign_capability` opens the plan of
every non-GET route through `open_request_plan` (rule 1b) and a migrated handler receives it through
`get_authorization_plan`.

- A route in `R01_PENDING_ROUTES` gets a **pending** plan: the commit guard admits it unfinalized. It
  is **not protected** by the R01 final check, and nothing here presents it as protected.
- A route in `R01_FINALIZED_ROUTES` gets an ordinary plan, which must be finalized or the guard
  refuses the commit.
- A route in neither set is unclassified: opening its plan fails closed, so a new campaign write
  route cannot be added without being migrated or listed.
"""

import uuid

from fastapi import Request
from sqlalchemy import Connection

from dnd_ai.domain.authorization import AuthorizationPlan

from .r01_pending_routes import R01_FINALIZED_ROUTES, R01_PENDING_ROUTES


class UnclassifiedRouteError(RuntimeError):
    """A write route is in neither `R01_PENDING_ROUTES` nor `R01_FINALIZED_ROUTES`. A direct
    `RuntimeError` subclass: a programming error, the fixed 5xx."""

    def __init__(self) -> None:
        super().__init__("a write route has no R01 classification")


def route_is_pending(method: str, route_path: str) -> bool:
    """Whether the route is listed as pending (not yet migrated to a final plan)."""
    return (method.upper(), route_path) in R01_PENDING_ROUTES


def begin_route_plan(
    connection: Connection,
    *,
    method: str,
    route_path: str,
    actor_user_id: uuid.UUID,
    campaign_id: uuid.UUID,
) -> AuthorizationPlan:
    """Open the request's plan for the route. Pending routes get a pending plan; finalized routes an
    ordinary one; an unclassified route raises `UnclassifiedRouteError`."""
    key = (method.upper(), route_path)
    if key in R01_PENDING_ROUTES:
        pending = True
    elif key in R01_FINALIZED_ROUTES:
        pending = False
    else:
        raise UnclassifiedRouteError()
    return AuthorizationPlan.begin(
        connection, actor_user_id=actor_user_id, campaign_id=campaign_id, pending=pending
    )


_STATE_NAME = "authorization_plan"


def open_request_plan(
    request: Request,
    connection: Connection,
    *,
    actor_user_id: uuid.UUID,
    campaign_id: uuid.UUID,
) -> AuthorizationPlan | None:
    """The plan of this request's write route, opened once. A read (`GET`, `HEAD`, `OPTIONS`) has
    none and returns `None`. A second protected dependency of the same request reuses the plan, so
    every requirement of the request lands in one plan. A route's identity is its template path, the
    key of the inventory; a route the inventory does not know fails closed."""
    if request.method.upper() in _READ_METHODS:
        return None
    existing = getattr(request.state, _STATE_NAME, None)
    if isinstance(existing, AuthorizationPlan):
        return existing
    route = request.scope.get("route")
    route_path = getattr(route, "path", None)
    if not isinstance(route_path, str):
        raise UnclassifiedRouteError()
    plan = begin_route_plan(
        connection,
        method=request.method,
        route_path=route_path,
        actor_user_id=actor_user_id,
        campaign_id=campaign_id,
    )
    setattr(request.state, _STATE_NAME, plan)
    return plan


def get_authorization_plan(request: Request) -> AuthorizationPlan:
    """The FastAPI dependency a migrated handler declares **after** its capability dependency. A
    request whose route opened no plan is a wiring error (the fixed 5xx), never a skipped check."""
    plan = getattr(request.state, _STATE_NAME, None)
    if not isinstance(plan, AuthorizationPlan):
        raise UnclassifiedRouteError()
    return plan


_READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
