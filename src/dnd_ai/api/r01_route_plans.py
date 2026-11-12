"""R01 route plans: opening the plan of a write route (plan section 6.5, rule 1b).

S1 provides the mechanism and the inventory; no production route is migrated here. S2 plumbs
`begin_route_plan` into `require_campaign_capability`.

- A route in `R01_PENDING_ROUTES` gets a **pending** plan: the commit guard admits it unfinalized. It
  is **not protected** by the R01 final check, and nothing here presents it as protected.
- A route in `R01_FINALIZED_ROUTES` gets an ordinary plan, which must be finalized or the guard
  refuses the commit.
- A route in neither set is unclassified: opening its plan fails closed, so a new campaign write
  route cannot be added without being migrated or listed.
"""

import uuid

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
