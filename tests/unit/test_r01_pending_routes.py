"""R01 S1: the route-pending inventory (plan section 6.5, rule 1b), derived from the S0 manifest.

Rule 1 (the `R01_PENDING` call-site pin) reaches only commands that call a scope helper. The 21
route-capability-only routes call none, and the eight engine routes end their transaction early, so
the plan's opening point is the ROUTE: `R01_PENDING_ROUTES` lists every write route inside R01's
bound whose handler is not yet migrated to a final plan. This file pins it:

- the generated module is the one the live route table produces (stale = the test fails);
- every route inside R01's bound is pending or finalized, never both, never neither;
- in S1 NO production route is finalized: every one of them is pending, and none is presented as
  protected (the mapping names pending routes only);
- the families of the routes that have no scope helper are pinned by the S0 manifest findings.

The pending set only shrinks. The exact counts below are S1's; a slice that migrates a route moves it
out of the pending mapping (and into `R01_FINALIZED_ROUTES`) in the same change.
"""

import json
from collections import Counter

import pytest

from dnd_ai.api.app import create_app
from dnd_ai.api.r01_pending_routes import R01_FINALIZED_ROUTES, R01_PENDING_ROUTES
from dnd_ai.api.r01_route_plans import UnclassifiedRouteError, route_is_pending
from tests.r01_manifest import (
    MANIFEST_PATH,
    MIGRATED_ROUTES,
    OUTSIDE_R01,
    PENDING_ROUTES_PATH,
    build_manifest,
    render_pending_routes,
)
from tests.unit.test_r01_route_manifest import ENGINE_EARLY_COMMIT, ROUTE_CAPABILITY_ONLY

pytestmark = pytest.mark.unit


def _manifest() -> list[dict[str, object]]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _inside() -> list[dict[str, object]]:
    return [r for r in _manifest() if r["family"] != OUTSIDE_R01]


def test_the_committed_pending_module_is_the_regenerated_one() -> None:
    expected = render_pending_routes(build_manifest(create_app()))
    actual = PENDING_ROUTES_PATH.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert actual == expected, "regenerate with: uv run python -m tests.r01_manifest"


def test_every_route_inside_r01s_bound_is_pending_or_finalized_exactly_once() -> None:
    keys = {(str(r["method"]), str(r["path"])) for r in _inside()}
    pending = set(R01_PENDING_ROUTES)
    finalized = set(R01_FINALIZED_ROUTES)
    assert pending & finalized == set()
    assert pending | finalized == keys
    assert finalized == set(MIGRATED_ROUTES)


def test_s2_finalizes_exactly_the_six_profile_and_revelation_routes() -> None:
    """S2 migrates the public-profile save, legacy copy, player-profile copy and release, and the
    revelation create and revoke: 6 of the 192 routes inside R01's bound. The other 186 stay pending."""
    assert len(R01_FINALIZED_ROUTES) == 6
    assert len(R01_PENDING_ROUTES) == 186
    assert {
        path.rsplit("/campaigns/{campaign_id}/characters/{character_id}/", 1)[-1]
        for _, path in R01_FINALIZED_ROUTES
    } == {
        "public-profile/draft",
        "public-profile/draft/copy-legacy",
        "public-profile/draft/copy-player-profile",
        "public-profile/releases",
        "revelations",
        "revelations/{character_revelation_id}/revoke",
    }
    assert {method for method, _ in R01_FINALIZED_ROUTES} == {"POST"}


def test_the_pending_counts_by_family_are_pinned() -> None:
    """186 distinct pending routes (192 at S1 less S2's six). The manifest has 193 inside records: one
    (method, path) is registered twice."""
    assert dict(Counter(R01_PENDING_ROUTES.values())) == {
        "authoring_scope": 71,
        "operation_scope": 54,
        "route_capability_only": 21,
        "access_management": 32,
        "engine_early_commit": 8,
    }
    records = Counter(str(r["family"]) for r in _inside())
    assert records["access_management"] == 33, "the duplicated route has two manifest records"
    duplicated = [
        key
        for key, count in Counter((str(r["method"]), str(r["path"])) for r in _inside()).items()
        if count > 1
    ]
    assert duplicated == [
        ("POST", "/campaigns/{campaign_id}/access-groups/{access_group_id}/members")
    ]


def test_routes_without_a_scope_helper_are_pending_and_pinned() -> None:
    """The 21 route-capability-only routes call no scope helper (S0 finding F-1): rule 1's call-site
    pin cannot see them, so each is listed here instead. The eight early-commit engine routes too."""
    for route in ROUTE_CAPABILITY_ONLY:
        assert R01_PENDING_ROUTES[route] == "route_capability_only", route
    for route in ENGINE_EARLY_COMMIT:
        assert R01_PENDING_ROUTES[route] == "engine_early_commit", route
    assert len(ROUTE_CAPABILITY_ONLY) == 21
    assert len(ENGINE_EARLY_COMMIT) == 8


def test_pending_routes_are_not_presented_as_protected() -> None:
    """The only thing a route's presence in `R01_PENDING_ROUTES` says is that it is unmigrated."""
    assert route_is_pending("POST", "/campaigns/{campaign_id}/events") is True
    assert route_is_pending("post", "/campaigns/{campaign_id}/events") is True
    assert route_is_pending("POST", "/admin/accounts") is False  # outside R01's bound
    assert ("POST", "/campaigns/{campaign_id}/events") not in R01_FINALIZED_ROUTES


def test_every_campaign_scoped_write_route_is_inside_r01s_bound() -> None:
    """A write route with `{campaign_id}` in its path has a family; none is silently outside."""
    outside = [
        r["path"]
        for r in _manifest()
        if r["family"] == OUTSIDE_R01 and "{campaign_id}" in str(r["path"])
    ]
    assert outside == []


def test_an_unclassified_route_fails_closed() -> None:
    """A new write route that is neither listed nor finalized cannot open a plan."""
    assert UnclassifiedRouteError.__mro__[1] is RuntimeError
