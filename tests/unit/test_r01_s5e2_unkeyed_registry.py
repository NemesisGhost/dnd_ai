"""R01 S5-E2 ownership-transfer amendment, T4: the unkeyed pre-write route registry (plan 6.27.4).

`R01_UNKEYED_PRE_WRITE_ROUTES` maps a finalized route to the one declaration its plan opens with. It is disjoint
from the keyed registry, and `begin_route_plan` refuses a route that is in both or is not finalized (fail closed,
the fixed 5xx), exactly as it refuses an unclassified route. The runtime proof (a real plan opens `PRE_WRITE` with
the declaration; an `Idempotency-Key` header is ignored) is in `tests/database/test_r01_s5e2_transfer_route.py`.
"""

from typing import Any

import pytest

from dnd_ai.api import r01_route_plans
from dnd_ai.api.r01_pending_routes import R01_FINALIZED_ROUTES, R01_PENDING_ROUTES
from dnd_ai.api.r01_pre_write_routes import (
    R01_KEYED_PRE_WRITE_ROUTES,
    R01_UNKEYED_PRE_WRITE_ROUTES,
)
from dnd_ai.api.r01_route_plans import UnclassifiedRouteError, begin_route_plan
from dnd_ai.commands import membership_role_plans as plans
from dnd_ai.domain.authorization_steps import PreWriteDeclaration
from tests.r01_manifest import _S5E6_ROUTES

pytestmark = pytest.mark.unit

TRANSFER = ("POST", "/campaigns/{campaign_id}/ownership-transfer")
UUID = "00000000-0000-0000-0000-000000000000"


def test_the_registry_holds_exactly_the_transfer_route_and_the_two_reveal_delegation_routes() -> (
    None
):
    assert set(R01_UNKEYED_PRE_WRITE_ROUTES) == {TRANSFER, *_S5E6_ROUTES}
    declaration = R01_UNKEYED_PRE_WRITE_ROUTES[TRANSFER]
    assert declaration is plans.TRANSFER_DECLARATION
    assert isinstance(declaration, PreWriteDeclaration) and not declaration.replay


def test_the_two_registries_are_disjoint_and_hold_finalized_routes_only() -> None:
    assert not set(R01_UNKEYED_PRE_WRITE_ROUTES) & set(R01_KEYED_PRE_WRITE_ROUTES)
    assert set(R01_UNKEYED_PRE_WRITE_ROUTES) <= set(R01_FINALIZED_ROUTES)
    assert not set(R01_UNKEYED_PRE_WRITE_ROUTES) & set(R01_PENDING_ROUTES)


def _begin(key: tuple[str, str]) -> Any:
    return begin_route_plan(
        None,  # type: ignore[arg-type] - refused before the connection is used
        method=key[0],
        route_path=key[1],
        actor_user_id=UUID,  # type: ignore[arg-type]
        campaign_id=UUID,  # type: ignore[arg-type]
    )


def test_a_route_in_both_registries_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    both = dict(R01_KEYED_PRE_WRITE_ROUTES)
    both[TRANSFER] = next(iter(R01_KEYED_PRE_WRITE_ROUTES.values()))
    monkeypatch.setattr(r01_route_plans, "R01_KEYED_PRE_WRITE_ROUTES", both)
    with pytest.raises(UnclassifiedRouteError):
        _begin(TRANSFER)


def test_an_unkeyed_route_that_is_pending_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        r01_route_plans,
        "R01_PENDING_ROUTES",
        {**R01_PENDING_ROUTES, TRANSFER: "access_management"},
    )
    monkeypatch.setattr(
        r01_route_plans, "R01_FINALIZED_ROUTES", set(R01_FINALIZED_ROUTES) - {TRANSFER}
    )
    with pytest.raises(UnclassifiedRouteError):
        _begin(TRANSFER)


def test_an_unclassified_route_is_still_refused() -> None:
    with pytest.raises(UnclassifiedRouteError):
        _begin(("POST", "/campaigns/{campaign_id}/not-a-route"))
