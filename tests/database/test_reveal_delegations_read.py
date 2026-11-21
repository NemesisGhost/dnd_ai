# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""P15-C02-S03 read contract: `GET /campaigns/{campaign_id}/reveal-delegations` (cases BD1 to BD11 of the plan).

A pure read over real HTTP. It reports, on the server and with the commands' own predicates, who may grant or revoke
(`can_manage`), who is eligible (`members`: live built-in `gm` assignments) and which delegation is effective, and
lists open delegations of members with no live `gm` assignment (`lapsed_delegations`) so they can be found and closed.
The write routes and the oracle `resolve_reveal_authority` are the existing ones; the fixtures are those of
`test_r01_s5e6_reveal_delegation_routes.py`.
"""

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from dnd_ai.commands.memberships import end_campaign_membership, revoke_membership_role
from dnd_ai.domain.reveal_authority import resolve_reveal_authority
from tests.database.test_r01_s2_profile_routes import (  # noqa: F401 - fixtures used by name
    pooled,
    pooled_factory,
)
from tests.database.test_r01_s3_authoring_routes import (  # noqa: F401 - fixtures used by name
    World,
    code,
    w,
)
from tests.database.test_r01_s5e6_reveal_delegation_routes import (  # noqa: F401 - fixtures used by name
    D,
    _tidy,
    d,
    delegations,
    grant,
    lapse_gm_row_keeping_delegation,
    revoke,
    snapshot,
)
from tests.factories import (
    make_campaign_membership,
    make_membership_role,
    make_role,
    make_user,
    system_role_id,
)

pytestmark = pytest.mark.database

Factory = Callable[[uuid.UUID], TestClient]


def read(factory: Factory, d: D, *, actor: uuid.UUID | None = None) -> Any:
    with factory(actor or d.a_user) as client:
        return client.get(f"{d.w.base}/reveal-delegations")


def members_of(response: Any) -> dict[str, dict[str, Any]]:
    return {m["campaign_membership_id"]: m for m in response.json()["members"]}


def lapsed_of(response: Any) -> dict[str, dict[str, Any]]:
    return {m["campaign_membership_id"]: m for m in response.json()["lapsed_delegations"]}


def expire_role(d: D, role: uuid.UUID) -> None:
    """An assignment that lapsed by expiry: nothing closes a delegation bound to it."""
    with d.w.engine.begin() as c:
        c.execute(text("SET LOCAL session_replication_role = replica"))
        c.execute(
            text(
                "UPDATE security.membership_roles SET granted_at = now() - interval '2 hours', "
                "expires_at = now() - interval '1 hour' WHERE membership_role_id = :r"
            ),
            {"r": role},
        )


def test_bd1_a_live_owner_reads_can_manage_and_exactly_the_live_builtin_gms(
    d: D, pooled: Engine, pooled_factory: Factory
) -> None:
    response = read(pooled_factory, d)
    assert code(response) == 200, response.text
    body = response.json()
    assert body["can_manage"] is True
    assert set(body) == {"can_manage", "members", "lapsed_delegations"}
    gms = {str(d.x_membership), str(d.y_membership), str(d.w.gm_membership)}
    listed = members_of(response)
    assert gms <= set(listed)
    # the campaign's creator also holds the built-in gm role; nobody else does
    assert {listed[m]["display_name"] for m in set(listed) - gms} == {"S3 Owner"}
    # ordered by display name, then membership id, and each carries a name
    names = [m["display_name"] for m in body["members"]]
    assert names == sorted(names) and all(names)
    assert body["lapsed_delegations"] == []
    # owners and players are not members of the list
    assert str(d.a_membership) not in members_of(response)
    assert str(d.p_membership) not in members_of(response)


def test_bd2_a_custom_access_manager_who_is_not_an_owner_reads_but_cannot_manage(
    d: D, pooled: Engine, pooled_factory: Factory
) -> None:
    owner = read(pooled_factory, d)
    manager = read(pooled_factory, d, actor=d.m.manager_user)
    assert code(manager) == 200, manager.text
    assert manager.json()["can_manage"] is False
    assert set(members_of(manager)) == set(members_of(owner))


def test_bd3_the_gate_is_the_writes_access_manage_requirement(
    d: D, pooled: Engine, pooled_factory: Factory
) -> None:
    before = snapshot(d)
    player = read(pooled_factory, d, actor=d.p_user)
    assert code(player) == 403, player.text
    with d.w.engine.begin() as c:
        stranger = make_user(c, "RD Stranger")
    outsider = read(pooled_factory, d, actor=stranger)
    assert code(outsider) in (403, 404), outsider.text
    assert snapshot(d) == before
    for refused in (player, outsider):
        text_of = refused.text
        assert str(d.x_membership) not in text_of and "RD X" not in text_of


def test_bd4_only_a_live_builtin_gm_assignment_makes_a_member_eligible(
    d: D, pooled: Engine, pooled_factory: Factory
) -> None:
    with d.w.engine.begin() as c:
        made: dict[str, uuid.UUID] = {}
        for label in ("assistant", "scoped-gm", "revoked", "expired", "ended", "inactive"):
            user = make_user(c, f"RD E {label}")
            membership = make_campaign_membership(c, d.w.campaign_id, user)
            made[label] = membership
            if label == "assistant":
                make_membership_role(c, membership, system_role_id(c, "assistant_gm"))
            elif label == "scoped-gm":
                make_membership_role(
                    c, membership, make_role(c, campaign_id=d.w.campaign_id, code="gm")
                )
            elif label == "revoked":
                make_membership_role(c, membership, d.gm, revoked=True)
            elif label == "expired":
                made["expired-role"] = make_membership_role(c, membership, d.gm)
            elif label == "ended":
                make_membership_role(c, membership, d.gm)
            else:
                make_membership_role(c, membership, d.gm)
                c.execute(
                    text(
                        "UPDATE security.users SET lifecycle_status_id = (SELECT lifecycle_status_id FROM "
                        "core.lifecycle_statuses WHERE code = 'inactive') WHERE user_id = "
                        "(SELECT user_id FROM security.campaign_memberships WHERE campaign_membership_id = :m)"
                    ),
                    {"m": membership},
                )
        c.execute(
            text(
                "UPDATE security.campaign_memberships SET ended_at = now() + interval '1 microsecond' "
                "WHERE campaign_membership_id = :m"
            ),
            {"m": made["ended"]},
        )
    expire_role(d, made["expired-role"])
    listed = set(members_of(read(pooled_factory, d)))
    for label in ("assistant", "scoped-gm", "revoked", "expired", "ended", "inactive"):
        assert str(made[label]) not in listed, label
    assert {str(d.x_membership), str(d.y_membership)} <= listed


def test_bd5_a_delegation_is_shown_only_when_it_is_effective(
    d: D, pooled: Engine, pooled_factory: Factory
) -> None:
    assert code(grant(pooled_factory, d)) == 200
    response = read(pooled_factory, d)
    members = members_of(response)
    x = members[str(d.x_membership)]
    assert x["delegation"] is not None
    assert set(x["delegation"]) == {"granted_at", "granted_by_name"}
    assert x["delegation"]["granted_by_name"] == "RD A"
    assert members[str(d.y_membership)]["delegation"] is None
    # the oracle: for a non-owner, a shown delegation is exactly `resolve_reveal_authority == "delegation"`
    with d.w.engine.connect() as c:
        for membership, shown in ((d.x_membership, True), (d.y_membership, False)):
            authority = resolve_reveal_authority(
                c, campaign_id=d.w.campaign_id, campaign_membership_id=membership
            )
            assert (authority == "delegation") is shown
    # the bound assignment expires: the member is not listed, the open row is lapsed and authorizes nothing
    expire_role(d, d.x_role)
    after = read(pooled_factory, d)
    assert str(d.x_membership) not in members_of(after)
    assert set(lapsed_of(after)) == {str(d.x_membership)}
    with d.w.engine.connect() as c:
        assert (
            resolve_reveal_authority(
                c, campaign_id=d.w.campaign_id, campaign_membership_id=d.x_membership
            )
            == "none"
        )
    # a new live assignment: listed with no delegation, and the old open row is NOT reported as lapsed
    lapse_gm_row_keeping_delegation(d, d.x_membership, d.x_role)
    regained = read(pooled_factory, d)
    assert members_of(regained)[str(d.x_membership)]["delegation"] is None
    assert lapsed_of(regained) == {}
    assert [r["live"] for r in delegations(d)] == [
        True
    ]  # the stale row is still open, untouched by the read


def test_bd6_endings_remove_the_delegation_or_the_member(
    d: D, pooled: Engine, pooled_factory: Factory
) -> None:
    assert code(grant(pooled_factory, d)) == 200
    assert code(grant(pooled_factory, d, grantee=d.y_membership)) == 200
    assert code(revoke(pooled_factory, d)) == 200
    after_revoke = read(pooled_factory, d)
    assert members_of(after_revoke)[str(d.x_membership)]["delegation"] is None
    assert lapsed_of(after_revoke) == {}
    with d.w.engine.begin() as c:
        revoke_membership_role(c, membership_role_id=d.y_role, campaign_id=d.w.campaign_id)
    after_role = read(pooled_factory, d)
    assert str(d.y_membership) not in members_of(after_role)
    assert (
        lapsed_of(after_role) == {}
    )  # the role revocation closed the delegation, so there is nothing open
    # regaining the role needs a fresh grant: listed with no delegation
    with d.w.engine.begin() as c:
        make_membership_role(c, d.y_membership, d.gm)
    assert members_of(read(pooled_factory, d))[str(d.y_membership)]["delegation"] is None
    # the membership end
    assert code(grant(pooled_factory, d, grantee=d.y_membership)) == 200
    with d.w.engine.begin() as c:
        end_campaign_membership(
            c,
            campaign_membership_id=d.y_membership,
            campaign_id=d.w.campaign_id,
            ended_by_membership_id=d.a_membership,
        )
    after_end = read(pooled_factory, d)
    assert str(d.y_membership) not in members_of(after_end) and lapsed_of(after_end) == {}


def test_bd7_a_delegation_survives_an_ownership_change_and_reads_follow_the_current_owner(
    d: D, pooled: Engine, pooled_factory: Factory
) -> None:
    assert code(grant(pooled_factory, d)) == 200  # granted by A
    # B (also an owner) reads the same state; A's removal as owner is simulated by revoking A's owner assignment
    with d.w.engine.begin() as c:
        c.execute(
            text(
                "UPDATE security.membership_roles SET revoked_at = now() WHERE membership_role_id = :r"
            ),
            {"r": d.a_role},
        )
        make_membership_role(c, d.a_membership, system_role_id(c, "player"))
    as_b = read(pooled_factory, d, actor=d.b_user)
    assert code(as_b) == 200 and as_b.json()["can_manage"] is True
    x = members_of(as_b)[str(d.x_membership)]
    assert x["delegation"] is not None and x["delegation"]["granted_by_name"] == "RD A"
    as_a = read(pooled_factory, d, actor=d.a_user)
    # A no longer holds access.manage as an owner; whatever the gate says, A can never read can_manage: true
    assert code(as_a) in (200, 403)
    if code(as_a) == 200:
        assert as_a.json()["can_manage"] is False


def test_bd8_the_response_discloses_only_the_contracts_keys(
    d: D, pooled: Engine, pooled_factory: Factory
) -> None:
    assert code(grant(pooled_factory, d)) == 200
    expire_role(d, d.x_role)
    assert (
        code(grant(pooled_factory, d, grantee=d.y_membership, reason="SECRET REASON TEXT")) == 200
    )
    body = read(pooled_factory, d).json()
    assert set(body) == {"can_manage", "members", "lapsed_delegations"}
    for member in body["members"]:
        assert set(member) == {"campaign_membership_id", "display_name", "delegation"}
        if member["delegation"] is not None:
            assert set(member["delegation"]) == {"granted_at", "granted_by_name"}
    for entry in body["lapsed_delegations"]:
        assert set(entry) == {
            "campaign_membership_id",
            "display_name",
            "granted_at",
            "granted_by_name",
        }
    raw = str(body)
    assert "SECRET REASON TEXT" not in raw and "Trusted to run" not in raw
    for fragment in (
        str(d.x_role),
        str(d.x_user),
        str(d.a_user),
        "gm_membership_role_id",
        "reason",
    ):
        assert fragment not in raw


def test_bd9_another_campaigns_members_and_delegations_never_appear(
    d: D, pooled: Engine, pooled_factory: Factory
) -> None:
    from tests.builders import make_authored_campaign, make_authored_world

    with d.w.engine.begin() as c:
        owner = make_user(c, "RD Iso Owner")
        authored = make_authored_world(c, owner_user_id=owner, name="RD Iso World")
        other = make_authored_campaign(c, authored, name="RD Iso Campaign")
        foreign = make_campaign_membership(c, other, make_user(c, "RD Iso GM"))
        make_membership_role(c, foreign, d.gm)
    try:
        assert code(grant(pooled_factory, d)) == 200
        body = read(pooled_factory, d).json()
        assert str(foreign) not in str(body) and "RD Iso GM" not in str(body)
    finally:
        from tests.database.test_authoring_concurrency import _purge_user_worlds

        _purge_user_worlds(d.w.engine, owner)


def test_bd10_the_read_writes_nothing_and_takes_no_row_lock(
    d: D, pooled: Engine, pooled_factory: Factory
) -> None:
    assert code(grant(pooled_factory, d)) == 200
    before = snapshot(d)
    # an exclusive lock on every relevant row does not delay or fail the read (it takes no row lock)
    with d.w.engine.connect() as holder:
        transaction = holder.begin()
        holder.execute(
            text(
                "SELECT 1 FROM security.membership_roles mr JOIN security.campaign_memberships cm USING "
                "(campaign_membership_id) WHERE cm.campaign_id = :c FOR UPDATE"
            ),
            {"c": d.w.campaign_id},
        )
        holder.execute(
            text(
                "SELECT 1 FROM security.character_reveal_delegations WHERE campaign_id = :c FOR UPDATE"
            ),
            {"c": d.w.campaign_id},
        )
        with d.w.engine.connect() as probe:
            probe.execute(text("SET lock_timeout = '1500ms'"))
        response = read(pooled_factory, d)
        assert code(response) == 200, response.text
        transaction.rollback()
    assert snapshot(d) == before


def test_bd11_open_delegations_with_no_live_gm_assignment_are_listed_as_lapsed_and_can_be_closed(
    d: D, pooled: Engine, pooled_factory: Factory
) -> None:
    assert code(grant(pooled_factory, d)) == 200
    assert code(grant(pooled_factory, d, grantee=d.y_membership)) == 200
    expire_role(d, d.x_role)
    with d.w.engine.begin() as c:
        c.execute(
            text(
                "UPDATE security.users SET lifecycle_status_id = (SELECT lifecycle_status_id FROM "
                "core.lifecycle_statuses WHERE code = 'inactive') WHERE user_id = :u"
            ),
            {"u": d.y_user},
        )
    body = read(pooled_factory, d).json()
    lapsed = {e["campaign_membership_id"]: e for e in body["lapsed_delegations"]}
    assert set(lapsed) == {str(d.x_membership), str(d.y_membership)}
    entry = lapsed[str(d.x_membership)]
    assert (
        entry["display_name"] == "RD X"
        and entry["granted_by_name"] == "RD A"
        and entry["granted_at"]
    )
    members = {m["campaign_membership_id"] for m in body["members"]}
    assert not members & set(lapsed)
    # the existing revoke route closes it (no new lifecycle rule), and the next read omits it
    closed = revoke(pooled_factory, d)
    assert code(closed) == 200 and closed.json()["revoked"] is True
    assert set(lapsed_of(read(pooled_factory, d))) == {str(d.y_membership)}
    ended = [r for r in delegations(d) if not r["live"]]
    assert [r["end_reason"] for r in ended] == ["revoked_by_owner"]
    # a closed row never appears, and a stale row of a member who holds a live assignment is not lapsed
    assert str(d.x_membership) not in lapsed_of(read(pooled_factory, d))
    with d.w.engine.begin() as c:
        c.execute(
            text(
                "UPDATE security.users SET lifecycle_status_id = (SELECT lifecycle_status_id FROM "
                "core.lifecycle_statuses WHERE code = 'active') WHERE user_id = :u"
            ),
            {"u": d.y_user},
        )
    final = read(pooled_factory, d)
    assert lapsed_of(final) == {}
    assert (
        members_of(final)[str(d.y_membership)]["delegation"] is not None
    )  # the original assignment is live again
