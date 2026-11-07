# ruff: noqa: F811 - the imported `g` and `client_factory` are pytest fixtures used by parameter name
"""`character.reveal` and its delegation (P03-A A1,
docs/PHASE14_15_P03A_A1_OWNERSHIP_AUTHORITY_DESIGN_2026-11-06.md).

A live built-in campaign owner has reveal authority directly and is the only actor who can grant
or revoke it for a member holding the built-in `gm` role. A delegation is bound to that member's
specific `gm` assignment. Custom roles, `canon.edit`, `access.manage` and assistant-GM status
confer nothing.

Everything runs against committed data across real connections: the grant and revoke commands take
row locks that only mean something between sessions, and the races are made deterministic by
holding a row lock (or an uncommitted command) until PostgreSQL reports the other request waiting.
"""

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from dnd_ai.commands.character_reveal import (
    grant_character_reveal_delegation,
    revoke_character_reveal_delegation,
)
from dnd_ai.commands.memberships import (
    CampaignOwnerRequiredError,
    MembershipNotInCampaignError,
    assign_membership_role,
    change_membership_role,
    end_campaign_membership,
    revoke_membership_role,
)
from dnd_ai.domain.reveal_authority import RevealAuthority, resolve_reveal_authority
from tests.database.test_campaign_owner_gate import (  # noqa: F401 - fixtures used by name
    Gate,
    _template_role_id,
    client_factory,
    drop_gate,
    g,
)
from tests.database.test_campaign_owner_lock_order import (  # noqa: F401 - autouse fixture
    _Hold,
    _park_command,
    _post,
    _release_everything,
    _status,
    _urls,
    _wait_until_waiting,
)
from tests.factories import make_campaign_membership, make_membership_role, make_role, make_user

pytestmark = pytest.mark.database


@pytest.fixture(autouse=True)
def _generous_lock_order_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    """The lock-order harness gives a parked scenario 15 seconds. In a long full-suite process a
    request thread has been seen taking longer than that to reach the database (alive, waiting on
    no lock), which ended the parked command before the interleaving existed. These scenarios wait
    on PostgreSQL's own report, never on the clock, so a wider window costs nothing when the
    request is prompt."""
    from tests.database import test_campaign_owner_lock_order as lock_order

    monkeypatch.setattr(lock_order, "_WAIT_SECONDS", 90.0)


_REASON = "Trusted to run the table's reveals"


@dataclass
class Members:
    """GM (`gm`), an assistant GM (`ast`), and a custom-role GM look-alike (`lookalike`)."""

    gm_user_id: uuid.UUID
    gm: uuid.UUID
    gm_role: uuid.UUID
    ast_user_id: uuid.UUID
    ast: uuid.UUID
    lookalike_user_id: uuid.UUID
    lookalike: uuid.UUID
    gm_template_id: uuid.UUID


@pytest.fixture
def m(postgres_engine: Engine, g: Gate) -> Members:
    with postgres_engine.begin() as connection:
        gm_template = _template_role_id(connection, "gm")
        gm_user = make_user(connection, "Reveal GM")
        gm = make_campaign_membership(connection, g.campaign_id, gm_user)
        gm_role = make_membership_role(connection, gm, gm_template)
        ast_user = make_user(connection, "Reveal Assistant GM")
        ast = make_campaign_membership(connection, g.campaign_id, ast_user)
        make_membership_role(connection, ast, _template_role_id(connection, "assistant_gm"))
        # A campaign-scoped role that merely borrows the template's code: never the built-in gm.
        fake_gm = make_role(connection, campaign_id=g.campaign_id, code="gm")
        lookalike_user = make_user(connection, "Reveal Lookalike")
        lookalike = make_campaign_membership(connection, g.campaign_id, lookalike_user)
        make_membership_role(connection, lookalike, fake_gm)
    return Members(
        gm_user_id=gm_user,
        gm=gm,
        gm_role=gm_role,
        ast_user_id=ast_user,
        ast=ast,
        lookalike_user_id=lookalike_user,
        lookalike=lookalike,
        gm_template_id=gm_template,
    )


# --- helpers ----------------------------------------------------------------------------------


def _urls_for(g: Gate) -> dict[str, str]:
    base = f"/campaigns/{g.campaign_id}/reveal-delegations"
    return {"grant": base, "revoke": base + "/{}/revoke"}


def _grant_body(membership: uuid.UUID) -> dict[str, object]:
    return {"grantee_campaign_membership_id": str(membership), "reason": _REASON}


def _post_grant(
    client_factory: Callable[[uuid.UUID], TestClient],
    user_id: uuid.UUID,
    g: Gate,
    membership: uuid.UUID,
) -> object:
    with client_factory(user_id) as client:
        return client.post(_urls_for(g)["grant"], json=_grant_body(membership))


def _post_revoke(
    client_factory: Callable[[uuid.UUID], TestClient],
    user_id: uuid.UUID,
    g: Gate,
    membership: uuid.UUID,
) -> object:
    with client_factory(user_id) as client:
        return client.post(
            _urls_for(g)["revoke"].format(membership), json={"reason": "No longer needed"}
        )


def _authority(engine: Engine, g: Gate, membership: uuid.UUID) -> RevealAuthority:
    with engine.connect() as connection:
        return resolve_reveal_authority(
            connection, campaign_id=g.campaign_id, campaign_membership_id=membership
        )


def _delegations(engine: Engine, g: Gate) -> list[dict[str, object]]:
    with engine.connect() as connection:
        rows = connection.execute(
            text("""
                SELECT character_reveal_delegation_id AS id, grantee_campaign_membership_id AS grantee,
                       gm_membership_role_id AS gm_role, granted_by_membership_id AS granted_by,
                       revoked_at IS NULL AS live, end_reason,
                       revoked_by_membership_id AS revoked_by, revocation_reason, reason
                FROM security.character_reveal_delegations
                WHERE campaign_id = :c
                ORDER BY granted_at, character_reveal_delegation_id
            """),
            {"c": g.campaign_id},
        ).mappings()
        return [dict(row) for row in rows]


def _live_delegations(engine: Engine, g: Gate) -> list[dict[str, object]]:
    return [row for row in _delegations(engine, g) if row["live"]]


def _audit(engine: Engine, g: Gate) -> dict[str, int]:
    with engine.connect() as connection:
        rows = connection.execute(
            text("""
                SELECT command_name, count(*) FROM audit.change_log
                WHERE world_id = :w GROUP BY command_name
            """),
            {"w": g.world_id},
        ).all()
    return dict(rows)


def _state(engine: Engine, g: Gate) -> tuple[int, int, int]:
    """(delegation rows, membership_roles rows, audit rows): a refused call changes none."""
    with engine.connect() as connection:
        counts = connection.execute(
            text("""
                SELECT
                  (SELECT count(*) FROM security.character_reveal_delegations WHERE campaign_id = :c),
                  (SELECT count(*) FROM security.membership_roles mr
                     JOIN security.campaign_memberships cm
                       ON cm.campaign_membership_id = mr.campaign_membership_id
                     WHERE cm.campaign_id = :c),
                  (SELECT count(*) FROM audit.change_log WHERE world_id = :w)
            """),
            {"c": g.campaign_id, "w": g.world_id},
        ).one()
    return (counts[0], counts[1], counts[2])


def _body(response: object) -> dict[str, object]:
    return response.json()  # type: ignore[attr-defined,no-any-return]


# --- authority --------------------------------------------------------------------------------


def test_only_a_live_built_in_owner_has_reveal_authority_without_a_delegation(
    postgres_engine: Engine, g: Gate, m: Members
) -> None:
    assert _authority(postgres_engine, g, g.o1) == "owner"
    assert _authority(postgres_engine, g, g.o2) == "owner"
    # Nothing else supplies it: a custom access.manage holder (who also holds canon.edit via the
    # campaign's roles in other suites), a GM, an assistant GM, a GM look-alike and a player.
    for membership in (g.manager, m.gm, m.ast, m.lookalike, g.player):
        assert _authority(postgres_engine, g, membership) == "none"


def test_ordinary_roles_and_grants_cannot_carry_character_reveal(
    postgres_engine: Engine, g: Gate
) -> None:
    with postgres_engine.connect() as connection:
        capability = connection.execute(
            text("SELECT capability_id FROM security.capabilities WHERE code = 'character.reveal'")
        ).scalar_one()
        relationship_type = connection.execute(
            text(
                "SELECT character_relationship_type_id FROM security.character_relationship_types LIMIT 1"
            )
        ).scalar_one()
    attempts = {
        "role_capabilities": (
            "INSERT INTO security.role_capabilities (role_id, capability_id) VALUES (:role, :cap)",
            {"role": g.custom_manager_role_id, "cap": capability},
        ),
        "relationship_type_capabilities": (
            "INSERT INTO security.character_relationship_type_capabilities "
            "(character_relationship_type_id, capability_id) VALUES (:type, :cap)",
            {"type": relationship_type, "cap": capability},
        ),
    }
    for name, (statement, params) in attempts.items():
        with pytest.raises(DBAPIError, match="character.reveal"), postgres_engine.begin() as c:
            c.execute(text(statement), params)
        assert name


def test_a_resource_grant_naming_character_reveal_is_refused(
    postgres_engine: Engine, g: Gate
) -> None:
    from tests.factories import make_character, make_resource_grant

    with postgres_engine.connect() as connection:
        capability = connection.execute(
            text("SELECT capability_id FROM security.capabilities WHERE code = 'character.reveal'")
        ).scalar_one()
    with pytest.raises(DBAPIError, match="character.reveal"), postgres_engine.begin() as c:
        character = make_character(c, g.world_id)
        make_resource_grant(
            c,
            g.campaign_id,
            capability,
            timeline_id=g.timeline_id,
            grantee_campaign_membership_id=g.player,
            character_id=character,
        )


def test_the_resource_grant_catalog_does_not_offer_character_reveal() -> None:
    from dnd_ai.domain.access import RESOURCE_GRANT_CAPABILITY_CATALOG

    offered = {code for codes in RESOURCE_GRANT_CAPABILITY_CATALOG.values() for code in codes}
    assert "character.reveal" not in offered


# --- grant, revoke, regrant -------------------------------------------------------------------


def test_an_owner_grants_revokes_and_regrants_with_one_audit_row_each(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate, m: Members
) -> None:
    granted = _post_grant(client_factory, g.o1_user_id, g, m.gm)
    assert _status(granted) == 200, granted.text  # type: ignore[attr-defined]
    first_id = _body(granted)["character_reveal_delegation_id"]
    assert _body(granted)["granted"] is True
    assert _authority(postgres_engine, g, m.gm) == "delegation"
    (live,) = _live_delegations(postgres_engine, g)
    assert live["gm_role"] == m.gm_role and live["granted_by"] == g.o1
    assert _audit(postgres_engine, g) == {"grant_character_reveal_delegation": 1}

    # A repeat changes nothing and writes no second audit row.
    repeat = _post_grant(client_factory, g.o2_user_id, g, m.gm)
    assert _status(repeat) == 200 and _body(repeat)["granted"] is False
    assert str(_body(repeat)["character_reveal_delegation_id"]) == str(first_id)
    assert _audit(postgres_engine, g) == {"grant_character_reveal_delegation": 1}

    revoked = _post_revoke(client_factory, g.o2_user_id, g, m.gm)
    assert _status(revoked) == 200 and _body(revoked)["revoked"] is True
    assert _authority(postgres_engine, g, m.gm) == "none"
    (closed,) = _delegations(postgres_engine, g)
    assert closed["live"] is False and closed["end_reason"] == "revoked_by_owner"
    assert closed["revoked_by"] == g.o2 and closed["revocation_reason"] == "No longer needed"
    assert _audit(postgres_engine, g)["revoke_character_reveal_delegation"] == 1

    again = _post_revoke(client_factory, g.o1_user_id, g, m.gm)
    assert _status(again) == 200 and _body(again)["revoked"] is False
    assert _audit(postgres_engine, g)["revoke_character_reveal_delegation"] == 1

    regranted = _post_grant(client_factory, g.o1_user_id, g, m.gm)
    assert _status(regranted) == 200 and _body(regranted)["granted"] is True
    assert str(_body(regranted)["character_reveal_delegation_id"]) != str(first_id)
    assert _authority(postgres_engine, g, m.gm) == "delegation"
    assert [row["live"] for row in _delegations(postgres_engine, g)] == [False, True]
    assert _audit(postgres_engine, g) == {
        "grant_character_reveal_delegation": 2,
        "revoke_character_reveal_delegation": 1,
    }


def test_a_delegation_binds_to_the_gm_assignment_and_cannot_be_revived(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate, m: Members
) -> None:
    assert _status(_post_grant(client_factory, g.o1_user_id, g, m.gm)) == 200
    with postgres_engine.begin() as connection:
        revoke_membership_role(connection, membership_role_id=m.gm_role, campaign_id=g.campaign_id)
    (closed,) = _delegations(postgres_engine, g)
    assert closed["live"] is False and closed["end_reason"] == "gm_role_revoked"
    assert _authority(postgres_engine, g, m.gm) == "none"

    # Regaining GM status is a new assignment row; the old grant stays closed.
    with postgres_engine.begin() as connection:
        regained = assign_membership_role(
            connection,
            campaign_membership_id=m.gm,
            role_id=m.gm_template_id,
            campaign_id=g.campaign_id,
            granted_by_membership_id=g.o1,
        ).membership_role_id
    assert regained != m.gm_role
    assert _authority(postgres_engine, g, m.gm) == "none"
    assert _status(_post_grant(client_factory, g.o1_user_id, g, m.gm)) == 200
    assert _authority(postgres_engine, g, m.gm) == "delegation"
    assert [row["gm_role"] for row in _live_delegations(postgres_engine, g)] == [regained]


def test_changing_a_gm_to_another_role_ends_the_delegation(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate, m: Members
) -> None:
    assert _status(_post_grant(client_factory, g.o1_user_id, g, m.gm)) == 200
    with postgres_engine.begin() as connection:
        change_membership_role(
            connection,
            membership_role_id=m.gm_role,
            new_role_id=g.player_role_id,
            campaign_id=g.campaign_id,
            granted_by_membership_id=g.o1,
        )
    (closed,) = _delegations(postgres_engine, g)
    assert closed["end_reason"] == "gm_role_changed"
    assert _authority(postgres_engine, g, m.gm) == "none"


def test_ending_the_membership_ends_the_delegation_but_not_ones_it_granted(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate, m: Members
) -> None:
    """o2 ends their own... no: o1 grants the GM, then the GM's membership ends. A delegation the
    ended member had granted would stay (provenance); here the grantor o1 is not ended."""
    assert _status(_post_grant(client_factory, g.o1_user_id, g, m.gm)) == 200
    with postgres_engine.begin() as connection:
        end_campaign_membership(
            connection,
            campaign_membership_id=m.gm,
            campaign_id=g.campaign_id,
            ended_by_membership_id=g.o1,
        )
    (closed,) = _delegations(postgres_engine, g)
    assert closed["end_reason"] == "membership_ended" and closed["live"] is False
    assert _authority(postgres_engine, g, m.gm) == "none"


def test_a_delegation_outlives_its_grantor_losing_ownership(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate, m: Members
) -> None:
    assert _status(_post_grant(client_factory, g.o1_user_id, g, m.gm)) == 200
    with postgres_engine.begin() as connection:
        end_campaign_membership(
            connection,
            campaign_membership_id=g.o1,
            campaign_id=g.campaign_id,
            ended_by_membership_id=g.o2,
        )
    (still,) = _live_delegations(postgres_engine, g)
    assert still["granted_by"] == g.o1
    assert _authority(postgres_engine, g, m.gm) == "delegation"
    # The remaining owner may revoke what a former owner granted.
    assert _body(_post_revoke(client_factory, g.o2_user_id, g, m.gm))["revoked"] is True


def test_an_expired_gm_assignment_ends_authority_and_does_not_block_a_fresh_grant(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate, m: Members
) -> None:
    assert _status(_post_grant(client_factory, g.o1_user_id, g, m.gm)) == 200
    stale_id = _live_delegations(postgres_engine, g)[0]["id"]
    # The assignment lapses by time: no command runs, so the delegation row stays unrevoked.
    with postgres_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE security.membership_roles SET granted_at = now() - interval '2 hours', "
                "expires_at = now() - interval '1 hour' WHERE membership_role_id = :r"
            ),
            {"r": m.gm_role},
        )
    assert _authority(postgres_engine, g, m.gm) == "none"
    assert [row["id"] for row in _live_delegations(postgres_engine, g)] == [stale_id]
    refused = _post_grant(client_factory, g.o1_user_id, g, m.gm)
    assert _status(refused) == 409
    assert _body(refused)["error"]["code"] == "reveal_delegation_recipient_not_gm"  # type: ignore[index]

    # The member is made a GM again through a new assignment (the lapsed row is closed first, as
    # in DEF-011); the stale unrevoked delegation must not stand in the way of a fresh grant.
    with postgres_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE security.membership_roles SET revoked_at = now() WHERE membership_role_id = :r"
            ),
            {"r": m.gm_role},
        )
        new_row = assign_membership_role(
            connection,
            campaign_membership_id=m.gm,
            role_id=m.gm_template_id,
            campaign_id=g.campaign_id,
            granted_by_membership_id=g.o1,
        ).membership_role_id
    granted = _post_grant(client_factory, g.o1_user_id, g, m.gm)
    assert _status(granted) == 200 and _body(granted)["granted"] is True
    rows = _delegations(postgres_engine, g)
    assert [r["live"] for r in rows] == [False, True]
    assert rows[0]["id"] == stale_id and rows[0]["end_reason"] == "gm_assignment_lapsed"
    assert rows[1]["gm_role"] == new_row
    assert _authority(postgres_engine, g, m.gm) == "delegation"


# --- who may call, and who may receive --------------------------------------------------------


@pytest.mark.parametrize("caller", ["manager", "gm", "assistant", "player"])
def test_nobody_but_a_live_owner_can_grant_or_revoke(
    client_factory: Callable[[uuid.UUID], TestClient],
    postgres_engine: Engine,
    g: Gate,
    m: Members,
    caller: str,
) -> None:
    users = {
        "manager": g.manager_user_id,
        "gm": m.gm_user_id,
        "assistant": m.ast_user_id,
        "player": g.player_user_id,
    }
    assert _status(_post_grant(client_factory, g.o1_user_id, g, m.gm)) == 200
    before = _state(postgres_engine, g)
    delegations_before = _delegations(postgres_engine, g)

    granted = _post_grant(client_factory, users[caller], g, m.gm)
    revoked = _post_revoke(client_factory, users[caller], g, m.gm)
    assert _status(granted) == 403 and _status(revoked) == 403
    if caller == "manager":
        # Passes the route's access.manage filter; the command refuses it as a non-owner.
        assert _body(granted)["error"]["code"] == "campaign_owner_required"  # type: ignore[index]
        assert _body(revoked)["error"]["code"] == "campaign_owner_required"  # type: ignore[index]
    assert _state(postgres_engine, g) == before
    assert _delegations(postgres_engine, g) == delegations_before


@pytest.mark.parametrize("target", ["assistant", "player", "lookalike", "owner_only", "manager"])
def test_only_a_member_holding_the_builtin_gm_role_can_receive_a_delegation(
    client_factory: Callable[[uuid.UUID], TestClient],
    postgres_engine: Engine,
    g: Gate,
    m: Members,
    target: str,
) -> None:
    memberships = {
        "assistant": m.ast,
        "player": g.player,
        "lookalike": m.lookalike,
        "owner_only": g.o2,
        "manager": g.manager,
    }
    before = _state(postgres_engine, g)
    refused = _post_grant(client_factory, g.o1_user_id, g, memberships[target])
    assert _status(refused) == 409, refused.text  # type: ignore[attr-defined]
    assert _body(refused)["error"]["code"] == "reveal_delegation_recipient_not_gm"  # type: ignore[index]
    assert _state(postgres_engine, g) == before


def test_a_gm_whose_membership_ended_or_account_is_inactive_cannot_receive_one(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate, m: Members
) -> None:
    with postgres_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE security.users SET lifecycle_status_id = (SELECT lifecycle_status_id "
                "FROM core.lifecycle_statuses WHERE code = 'archived') WHERE user_id = :u"
            ),
            {"u": m.gm_user_id},
        )
    before = _state(postgres_engine, g)
    refused = _post_grant(client_factory, g.o1_user_id, g, m.gm)
    assert _status(refused) == 409
    assert _state(postgres_engine, g) == before


def test_an_owner_who_is_also_a_gm_can_delegate_to_themselves(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate
) -> None:
    with postgres_engine.begin() as connection:
        make_membership_role(connection, g.o1, g.gm_role_id)
    granted = _post_grant(client_factory, g.o1_user_id, g, g.o1)
    assert _status(granted) == 200 and _body(granted)["granted"] is True
    assert _authority(postgres_engine, g, g.o1) == "owner"


# --- cross-campaign binding -------------------------------------------------------------------


def test_a_membership_of_another_campaign_is_refused_at_the_command_and_the_database(
    client_factory: Callable[[uuid.UUID], TestClient],
    postgres_engine: Engine,
    g: Gate,
    m: Members,
) -> None:
    with postgres_engine.begin() as connection:
        other = Gate(connection, f"reveal-other-{uuid.uuid4().hex[:8]}")
        other_gm_user = make_user(connection, "Other Campaign GM")
        other_gm = make_campaign_membership(connection, other.campaign_id, other_gm_user)
        other_gm_row = make_membership_role(connection, other_gm, g.gm_role_id)
    try:
        before = _state(postgres_engine, g)
        other_before = _state(postgres_engine, other)

        refused = _post_grant(client_factory, g.o1_user_id, g, other_gm)
        assert _status(refused) == 404
        refused_revoke = _post_revoke(client_factory, g.o1_user_id, g, other_gm)
        assert _status(refused_revoke) == 404
        # An owner of the other campaign is an outsider here.
        outsider = _post_grant(client_factory, other.o1_user_id, g, m.gm)
        assert _status(outsider) == 404
        assert _state(postgres_engine, g) == before
        assert _state(postgres_engine, other) == other_before

        with (
            pytest.raises(MembershipNotInCampaignError),
            postgres_engine.begin() as connection,
        ):
            grant_character_reveal_delegation(
                connection,
                campaign_id=g.campaign_id,
                actor_membership_id=g.o1,
                grantee_campaign_membership_id=other_gm,
                reason=_REASON,
            )
        with (
            pytest.raises(MembershipNotInCampaignError),
            postgres_engine.begin() as connection,
        ):
            revoke_character_reveal_delegation(
                connection,
                campaign_id=g.campaign_id,
                actor_membership_id=g.o1,
                grantee_campaign_membership_id=other_gm,
                reason=_REASON,
            )

        # The database refuses the same mismatches on its own.
        insert = text("""
            INSERT INTO security.character_reveal_delegations
                (campaign_id, grantee_campaign_membership_id, gm_membership_role_id,
                 granted_by_membership_id, reason)
            VALUES (:campaign, :grantee, :gm_role, :actor, 'x')
        """)
        mismatches = {
            "grantee of another campaign": {
                "campaign": g.campaign_id,
                "grantee": other_gm,
                "gm_role": other_gm_row,
                "actor": g.o1,
            },
            "gm assignment of another member": {
                "campaign": g.campaign_id,
                "grantee": m.ast,
                "gm_role": m.gm_role,
                "actor": g.o1,
            },
            "granting member of another campaign": {
                "campaign": g.campaign_id,
                "grantee": m.gm,
                "gm_role": m.gm_role,
                "actor": other.o1,
            },
        }
        for label, params in mismatches.items():
            with pytest.raises(DBAPIError), postgres_engine.begin() as c:
                c.execute(insert, params)
            assert label
        # And bound to a role that is not the built-in gm template.
        with pytest.raises(DBAPIError, match="built-in gm"), postgres_engine.begin() as c:
            c.execute(
                insert,
                {"campaign": g.campaign_id, "grantee": g.o1, "gm_role": g.o1_role, "actor": g.o1},
            )
        assert _state(postgres_engine, g) == before
    finally:
        drop_gate(postgres_engine, other)


def test_delegation_columns_that_bind_it_cannot_be_rewritten(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate, m: Members
) -> None:
    assert _status(_post_grant(client_factory, g.o1_user_id, g, m.gm)) == 200
    for column, value in (
        ("campaign_id", uuid.uuid4()),
        ("grantee_campaign_membership_id", g.o1),
        ("gm_membership_role_id", g.o1_role),
        ("reason", "rewritten"),
    ):
        with pytest.raises(DBAPIError), postgres_engine.begin() as connection:
            connection.execute(
                text(f"UPDATE security.character_reveal_delegations SET {column} = :v"),  # noqa: S608
                {"v": value},
            )


# --- ownership transfer -----------------------------------------------------------------------


def test_delegations_survive_a_transfer_and_the_former_owner_keeps_only_a_gm_delegation(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate, m: Members
) -> None:
    with postgres_engine.begin() as connection:
        make_membership_role(connection, g.o1, g.gm_role_id)
    assert _status(_post_grant(client_factory, g.o1_user_id, g, m.gm)) == 200
    assert _status(_post_grant(client_factory, g.o1_user_id, g, g.o1)) == 200

    with client_factory(g.o1_user_id) as client:
        transferred = client.post(
            f"/campaigns/{g.campaign_id}/ownership-transfer",
            json={"target_campaign_membership_id": str(g.o2), "relinquish_own_ownership": True},
        )
    assert transferred.status_code == 200, transferred.text

    # Existing grants survive. The former owner lost owner-derived authority and keeps only the
    # separate GM delegation, which is still bound to their live gm assignment.
    assert _authority(postgres_engine, g, g.o2) == "owner"
    assert _authority(postgres_engine, g, m.gm) == "delegation"
    assert _authority(postgres_engine, g, g.o1) == "delegation"
    assert len(_live_delegations(postgres_engine, g)) == 2

    # The former owner can no longer grant or revoke; the new owner can revoke what they granted.
    before = _state(postgres_engine, g)
    assert _status(_post_grant(client_factory, g.o1_user_id, g, m.gm)) in (403, 404)
    assert _status(_post_revoke(client_factory, g.o1_user_id, g, m.gm)) in (403, 404)
    assert _state(postgres_engine, g) == before
    assert _body(_post_revoke(client_factory, g.o2_user_id, g, g.o1))["revoked"] is True
    assert _authority(postgres_engine, g, g.o1) == "none"
    assert _authority(postgres_engine, g, m.gm) == "delegation"


# --- races: lock order against GM role removal, membership end and ownership transfer ---------


def _wait_until_waiting_on(engine: Engine, request: object) -> None:
    """Waits until PostgreSQL reports a session waiting on a lock; if none does, says what the
    request was doing (a request that never waited is not the interleaving under test)."""
    import sys
    import traceback

    try:
        _wait_until_waiting(engine, 1)
    except AssertionError:
        thread = request.thread  # type: ignore[attr-defined]
        done = not thread.is_alive()
        answer = request.response.text if done and request.response is not None else None  # type: ignore[attr-defined]
        frame = sys._current_frames().get(thread.ident) if thread.ident else None
        where = "".join(traceback.format_stack(frame)[-8:]) if frame is not None else ""
        raise AssertionError(
            f"no session waited on a lock; finished={done} {answer}\n"
            f"pool: {engine.pool.status()}\n{where}"  # type: ignore[attr-defined]
        ) from None


def _grant_url(g: Gate) -> str:
    return _urls_for(g)["grant"]


def test_a_grant_that_waits_on_a_gm_role_revocation_is_refused(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate, m: Members
) -> None:
    revoking = _park_command(
        postgres_engine,
        lambda c: revoke_membership_role(
            c, membership_role_id=m.gm_role, campaign_id=g.campaign_id
        ),
    )
    assert revoking.error is None
    grant = _post(client_factory, g.o1_user_id, _grant_url(g), _grant_body(m.gm))
    _wait_until_waiting_on(postgres_engine, grant)
    revoking.end(commit=True)
    response = grant.join()
    assert _status(response) == 409, response.text  # type: ignore[attr-defined]
    assert _delegations(postgres_engine, g) == []
    assert _audit(postgres_engine, g) == {}


def test_a_gm_role_revocation_that_waits_on_a_grant_closes_the_new_delegation(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate, m: Members
) -> None:
    granting = _park_command(
        postgres_engine,
        lambda c: grant_character_reveal_delegation(
            c,
            campaign_id=g.campaign_id,
            actor_membership_id=g.o1,
            grantee_campaign_membership_id=m.gm,
            reason=_REASON,
        ),
    )
    assert granting.error is None
    revoke = _post(
        client_factory,
        g.o2_user_id,
        f"/campaigns/{g.campaign_id}/memberships/roles/{m.gm_role}/revoke",
        {},
    )
    _wait_until_waiting(postgres_engine, 1)
    granting.end(commit=True)
    assert _status(revoke.join()) == 200

    (row,) = _delegations(postgres_engine, g)
    assert row["live"] is False and row["end_reason"] == "gm_role_revoked"
    assert _authority(postgres_engine, g, m.gm) == "none"


def test_a_grant_that_waits_on_ending_the_gms_membership_is_refused(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate, m: Members
) -> None:
    ending = _park_command(
        postgres_engine,
        lambda c: end_campaign_membership(
            c,
            campaign_membership_id=m.gm,
            campaign_id=g.campaign_id,
            ended_by_membership_id=g.o2,
        ),
    )
    assert ending.error is None
    grant = _post(client_factory, g.o1_user_id, _grant_url(g), _grant_body(m.gm))
    _wait_until_waiting_on(postgres_engine, grant)
    ending.end(commit=True)
    assert _status(grant.join()) == 409
    assert _delegations(postgres_engine, g) == []
    assert _audit(postgres_engine, g) == {}


def test_ending_the_gms_membership_while_a_grant_is_in_flight_closes_the_delegation(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate, m: Members
) -> None:
    granting = _park_command(
        postgres_engine,
        lambda c: grant_character_reveal_delegation(
            c,
            campaign_id=g.campaign_id,
            actor_membership_id=g.o1,
            grantee_campaign_membership_id=m.gm,
            reason=_REASON,
        ),
    )
    assert granting.error is None
    end = _post(
        client_factory, g.o2_user_id, f"/campaigns/{g.campaign_id}/memberships/{m.gm}/end", {}
    )
    _wait_until_waiting(postgres_engine, 1)
    granting.end(commit=True)
    assert _status(end.join()) == 200
    (row,) = _delegations(postgres_engine, g)
    assert row["live"] is False and row["end_reason"] == "membership_ended"
    assert _authority(postgres_engine, g, m.gm) == "none"


def test_a_grant_that_waits_on_a_relinquishing_transfer_is_refused_afterwards(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate, m: Members
) -> None:
    """The transfer holds the caller's owner assignment, so the grant waits at the D3 gate and, once
    the transfer commits, finds a caller who is no longer an owner."""
    from dnd_ai.commands.memberships import transfer_campaign_ownership

    transferring = _park_command(
        postgres_engine,
        lambda c: transfer_campaign_ownership(
            c,
            campaign_id=g.campaign_id,
            actor_membership_id=g.o1,
            target_campaign_membership_id=g.o2,
            relinquish_own_ownership=True,
        ),
    )
    assert transferring.error is None
    grant = _post(client_factory, g.o1_user_id, _grant_url(g), _grant_body(m.gm))
    _wait_until_waiting_on(postgres_engine, grant)
    transferring.end(commit=True)
    response = grant.join()
    assert _status(response) == 403, response.text  # type: ignore[attr-defined]
    assert _delegations(postgres_engine, g) == []
    assert _audit(postgres_engine, g) == {}


def test_a_transfer_that_waits_on_an_in_flight_grant_leaves_the_delegation_in_force(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate, m: Members
) -> None:
    granting = _park_command(
        postgres_engine,
        lambda c: grant_character_reveal_delegation(
            c,
            campaign_id=g.campaign_id,
            actor_membership_id=g.o1,
            grantee_campaign_membership_id=m.gm,
            reason=_REASON,
        ),
    )
    assert granting.error is None
    transfer = _post(
        client_factory,
        g.o1_user_id,
        _urls(g)["transfer"],
        {"target_campaign_membership_id": str(g.o2), "relinquish_own_ownership": True},
    )
    _wait_until_waiting(postgres_engine, 1)
    granting.end(commit=True)
    assert _status(transfer.join()) == 200
    assert _authority(postgres_engine, g, m.gm) == "delegation"
    assert _authority(postgres_engine, g, g.o1) == "none"
    assert _authority(postgres_engine, g, g.o2) == "owner"


def test_a_delegation_revocation_and_a_gm_role_revocation_close_it_exactly_once(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate, m: Members
) -> None:
    assert _status(_post_grant(client_factory, g.o1_user_id, g, m.gm)) == 200
    revoking = _park_command(
        postgres_engine,
        lambda c: revoke_character_reveal_delegation(
            c,
            campaign_id=g.campaign_id,
            actor_membership_id=g.o1,
            grantee_campaign_membership_id=m.gm,
            reason="Stepping back",
        ),
    )
    assert revoking.error is None
    role_revoke = _post(
        client_factory,
        g.o2_user_id,
        f"/campaigns/{g.campaign_id}/memberships/roles/{m.gm_role}/revoke",
        {},
    )
    _wait_until_waiting(postgres_engine, 1)
    revoking.end(commit=True)
    assert _status(role_revoke.join()) == 200
    (row,) = _delegations(postgres_engine, g)
    # The explicit revocation committed first, so its reason stands and the lifecycle hook found
    # nothing left to close.
    assert row["end_reason"] == "revoked_by_owner" and row["revocation_reason"] == "Stepping back"


def test_a_caller_whose_owner_assignment_expires_during_the_wait_is_refused(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate, m: Members
) -> None:
    """DEF-013 at the new write boundary: the grant waits on the grantee's membership while the
    caller's finite owner assignment expires."""
    with postgres_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE security.membership_roles "
                "SET expires_at = clock_timestamp() + interval '4 seconds' "
                "WHERE membership_role_id = :r"
            ),
            {"r": g.o1_role},
        )
    hold = _Hold(
        postgres_engine,
        "SELECT 1 FROM security.campaign_memberships WHERE campaign_membership_id = :m FOR UPDATE",
        {"m": m.gm},
    )
    grant = _post(client_factory, g.o1_user_id, _grant_url(g), _grant_body(m.gm))
    _wait_until_waiting_on(postgres_engine, grant)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        with postgres_engine.connect() as connection:
            if connection.execute(
                text(
                    "SELECT clock_timestamp() > expires_at FROM security.membership_roles "
                    "WHERE membership_role_id = :r"
                ),
                {"r": g.o1_role},
            ).scalar_one():
                break
        time.sleep(0.05)
    hold.release()
    response = grant.join()
    assert _status(response) == 403, response.text  # type: ignore[attr-defined]
    assert _delegations(postgres_engine, g) == []
    assert _audit(postgres_engine, g) == {}


def test_an_unauthorized_command_call_writes_nothing(
    postgres_engine: Engine, g: Gate, m: Members
) -> None:
    before = _state(postgres_engine, g)
    for actor in (g.manager, m.gm, m.ast, g.player):
        with pytest.raises(CampaignOwnerRequiredError), postgres_engine.begin() as connection:
            grant_character_reveal_delegation(
                connection,
                campaign_id=g.campaign_id,
                actor_membership_id=actor,
                grantee_campaign_membership_id=m.gm,
                reason=_REASON,
            )
    assert _state(postgres_engine, g) == before
