# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""Migration 145's constraints and triggers, exercised directly in SQL (P03-A A3a, plan 10.9).

Each refusal comes from the database itself (a CHECK, a trigger, a unique index or a foreign key),
not from the application commands.
"""

import uuid
from typing import Any

import pytest
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from tests.database.test_campaign_owner_gate import Gate, g  # noqa: F401 - fixture used by name
from tests.database.test_character_reveal_delegation import (  # noqa: F401 - fixtures used by name
    Members,
    m,
)
from tests.database.test_character_revelations import Rev, rev  # noqa: F401 - fixtures used by name
from tests.factories import (
    lookup_id,
    make_access_group,
    make_campaign,
    make_campaign_membership,
    make_character,
    make_resource_grant,
    make_timeline,
    make_user,
    make_world,
)

pytestmark = pytest.mark.database


def _kind(connection: Connection, code: str) -> uuid.UUID:
    return connection.execute(
        text(
            "SELECT revelation_audience_kind_id FROM security.revelation_audience_kinds "
            "WHERE code = :c"
        ),
        {"c": code},
    ).scalar_one()


def insert(
    connection: Connection,
    g: Gate,
    character: uuid.UUID,
    kind: str,
    *,
    member: uuid.UUID | None = None,
    group: uuid.UUID | None = None,
    creator: uuid.UUID | None = None,
    campaign: uuid.UUID | None = None,
    source: str = "owner",
    delegation: uuid.UUID | None = None,
    reason: str = "Because",
) -> uuid.UUID:
    return connection.execute(
        text("""
            INSERT INTO security.character_revelations (
                campaign_id, character_id, revelation_audience_kind_id,
                target_campaign_membership_id, target_access_group_id,
                created_by_membership_id, authority_source_code, character_reveal_delegation_id,
                reason)
            VALUES (:campaign, :character, :kind, :member, :group, :creator, :source,
                    :delegation, :reason)
            RETURNING character_revelation_id
        """),
        {
            "campaign": campaign or g.campaign_id,
            "character": character,
            "kind": _kind(connection, kind),
            "member": member,
            "group": group,
            "creator": creator or g.o1,
            "source": source,
            "delegation": delegation,
            "reason": reason,
        },
    ).scalar_one()


def refused(engine: Engine, operation: Any, *, containing: str | None = None) -> None:
    """The operation, in its own transaction, is refused by the database."""
    with pytest.raises(DBAPIError) as raised, engine.begin() as connection:
        operation(connection)
    if containing is not None:
        assert containing in str(raised.value)


# --- target shape and scope -------------------------------------------------------------------


def test_the_target_shape_must_match_the_audience_kind(
    postgres_engine: Engine, g: Gate, rev: Rev
) -> None:
    c = rev.character_id
    refused(postgres_engine, lambda cn: insert(cn, g, c, "member"), containing="membership target")
    refused(
        postgres_engine,
        lambda cn: insert(cn, g, c, "member", member=g.player, group=rev.group_id),
        containing="membership target",
    )
    refused(postgres_engine, lambda cn: insert(cn, g, c, "access_group"), containing="group target")
    refused(
        postgres_engine,
        lambda cn: insert(cn, g, c, "access_group", member=g.player),
        containing="group target",
    )
    refused(
        postgres_engine,
        lambda cn: insert(cn, g, c, "campaign_current", member=g.player),
        containing="no target",
    )
    refused(
        postgres_engine,
        lambda cn: insert(cn, g, c, "campaign_current_and_future", group=rev.group_id),
        containing="no target",
    )


def test_every_reference_must_belong_to_the_revelations_campaign_and_world(
    postgres_engine: Engine, g: Gate, m: Members, rev: Rev
) -> None:
    with postgres_engine.begin() as connection:
        timeline = make_timeline(connection, g.world_id, name="Elsewhere")
        other_campaign = make_campaign(
            connection, timeline, "Elsewhere", lifecycle_status_code="pending"
        )
        stranger = make_user(connection, "Schema Stranger")
        foreign_member = make_campaign_membership(connection, other_campaign, stranger)
        foreign_group = make_access_group(connection, other_campaign, name="Foreign Group")
        other_world = make_world(connection, slug=f"other-{uuid.uuid4().hex[:8]}")
        foreign_character = make_character(connection, other_world, name="Foreign Character")
    c = rev.character_id
    refused(
        postgres_engine,
        lambda cn: insert(cn, g, c, "member", member=foreign_member),
        containing="does not belong to campaign",
    )
    refused(
        postgres_engine,
        lambda cn: insert(cn, g, c, "access_group", group=foreign_group),
        containing="does not belong to campaign",
    )
    refused(
        postgres_engine,
        lambda cn: insert(cn, g, c, "campaign_current", creator=foreign_member),
        containing="Creating membership",
    )
    refused(
        postgres_engine,
        lambda cn: insert(cn, g, foreign_character, "campaign_current"),
        containing="not in the world",
    )
    # A delegation must be the creator's own: the GM's delegation cannot back the owner's row.
    refused(
        postgres_engine,
        lambda cn: insert(
            cn, g, c, "campaign_current", source="delegation", delegation=rev.delegation_id
        ),
        containing="not a delegation of campaign",
    )
    # And the provenance pair must agree.
    refused(postgres_engine, lambda cn: insert(cn, g, c, "campaign_current", source="delegation"))
    refused(
        postgres_engine,
        lambda cn: insert(
            cn, g, c, "campaign_current", creator=m.gm, source="owner", delegation=rev.delegation_id
        ),
    )


def test_a_revelation_needs_a_release_in_its_own_campaign(
    postgres_engine: Engine, g: Gate, rev: Rev
) -> None:
    refused(
        postgres_engine,
        lambda cn: insert(cn, g, rev.unreleased_id, "campaign_current"),
        containing="has no release",
    )
    with postgres_engine.begin() as connection:  # the released character is fine
        insert(connection, g, rev.character_id, "campaign_current")


# --- closure and immutability -----------------------------------------------------------------


def _live(
    engine: Engine, g: Gate, rev: Rev, kind: str = "campaign_current", **kw: Any
) -> uuid.UUID:
    with engine.begin() as connection:
        return insert(connection, g, rev.character_id, kind, **kw)


def test_a_row_is_closed_at_most_once_and_structural_columns_never_change(
    postgres_engine: Engine, g: Gate, rev: Rev
) -> None:
    row = _live(postgres_engine, g, rev)
    for column, value in (
        ("reason", "'Rewritten'"),
        ("character_id", f"'{rev.unreleased_id}'"),
        ("created_by_membership_id", f"'{g.o2}'"),
        ("authority_source_code", "'delegation'"),
        ("created_at", "now() + interval '1 day'"),
    ):
        refused(
            postgres_engine,
            lambda cn, col=column, val=value: cn.execute(  # type: ignore[misc]
                text(
                    f"UPDATE security.character_revelations SET {col} = {val} "  # noqa: S608
                    "WHERE character_revelation_id = :r"
                ),
                {"r": row},
            ),
        )
    with postgres_engine.begin() as connection:
        connection.execute(
            text("""
                UPDATE security.character_revelations
                SET ended_at = clock_timestamp(), end_reason = 'target_membership_ended'
                WHERE character_revelation_id = :r
            """),
            {"r": row},
        )
    # Closed: it can neither be reopened nor closed again for another reason.
    refused(
        postgres_engine,
        lambda cn: cn.execute(
            text(
                "UPDATE security.character_revelations SET ended_at = NULL, end_reason = NULL "
                "WHERE character_revelation_id = :r"
            ),
            {"r": row},
        ),
        containing="is closed",
    )
    refused(
        postgres_engine,
        lambda cn: cn.execute(
            text(
                "UPDATE security.character_revelations SET end_reason = 'access_group_deactivated' "
                "WHERE character_revelation_id = :r"
            ),
            {"r": row},
        ),
        containing="is closed",
    )


@pytest.mark.parametrize(
    "assignment",
    [
        "end_reason = 'revoked'",  # a reason without a time
        "ended_at = clock_timestamp()",  # a time without a reason
        "ended_at = clock_timestamp(), end_reason = 'because'",  # an unknown reason
        "ended_at = clock_timestamp(), end_reason = 'target_membership_ended', "
        "revocation_reason = 'x'",  # a revocation reason on a system closure
        "ended_at = clock_timestamp(), end_reason = 'revoked'",  # a revocation with no revoker
        "ended_at = created_at - interval '1 second', end_reason = 'target_membership_ended'",
    ],
)
def test_closure_checks_refuse_inconsistent_closures(
    postgres_engine: Engine, g: Gate, rev: Rev, assignment: str
) -> None:
    row = _live(postgres_engine, g, rev)
    refused(
        postgres_engine,
        lambda cn: cn.execute(
            text(
                f"UPDATE security.character_revelations SET {assignment} "  # noqa: S608
                "WHERE character_revelation_id = :r"
            ),
            {"r": row},
        ),
    )


def test_only_one_live_row_exists_per_audience_and_a_closed_one_can_be_replaced(
    postgres_engine: Engine, g: Gate, rev: Rev
) -> None:
    c = rev.character_id
    first = _live(postgres_engine, g, rev, "member", member=g.player)
    with pytest.raises(IntegrityError):
        _live(postgres_engine, g, rev, "member", member=g.player)
    _live(postgres_engine, g, rev, "member", member=g.manager)  # another audience
    _live(postgres_engine, g, rev, "campaign_current")
    with pytest.raises(IntegrityError):
        _live(postgres_engine, g, rev, "campaign_current")  # NULL targets still collide
    with postgres_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE security.character_revelations SET ended_at = clock_timestamp(), "
                "end_reason = 'target_membership_ended' WHERE character_revelation_id = :r"
            ),
            {"r": first},
        )
        insert(connection, g, c, "member", member=g.player)  # the closed row is history


def test_a_character_with_a_revelation_cannot_be_physically_deleted(
    postgres_engine: Engine, g: Gate, rev: Rev
) -> None:
    _live(postgres_engine, g, rev)
    refused(
        postgres_engine,
        lambda cn: cn.execute(
            text("DELETE FROM character.characters WHERE character_id = :c"),
            {"c": rev.character_id},
        ),
    )


# --- the snapshot -----------------------------------------------------------------------------


def _snapshot_row(
    connection: Connection, g: Gate, revelation: uuid.UUID, member: uuid.UUID
) -> None:
    connection.execute(
        text(
            "INSERT INTO security.character_revelation_members "
            "(character_revelation_id, campaign_id, campaign_membership_id) "
            "VALUES (:r, :c, :m)"
        ),
        {"r": revelation, "c": g.campaign_id, "m": member},
    )


def test_snapshot_rows_belong_to_a_campaign_current_revelation_and_its_own_transaction(
    postgres_engine: Engine, g: Gate, rev: Rev
) -> None:
    c = rev.character_id
    with postgres_engine.begin() as connection:
        current = insert(connection, g, c, "campaign_current")
        _snapshot_row(connection, g, current, g.player)  # the creating transaction may add
        member_kind = insert(connection, g, c, "member", member=g.manager)
        with pytest.raises(IntegrityError), connection.begin_nested():
            _snapshot_row(connection, g, member_kind, g.player)  # not campaign_current
    # A later transaction cannot add to the fixed snapshot.
    refused(
        postgres_engine,
        lambda cn: _snapshot_row(cn, g, current, g.o2),
        containing="fixed when the revelation is created",
    )
    # Nor can a member twice, or a foreign campaign's membership.
    with postgres_engine.begin() as connection:
        timeline = make_timeline(connection, g.world_id, name="Snapshot Elsewhere")
        other_campaign = make_campaign(
            connection, timeline, "Snapshot Elsewhere", lifecycle_status_code="pending"
        )
        foreign = make_campaign_membership(
            connection, other_campaign, make_user(connection, "Snapshot Stranger")
        )
        fresh = insert(connection, g, c, "campaign_current_and_future")
        assert fresh  # (a different audience: the live row per audience is not the point here)
    with postgres_engine.begin() as connection:
        closing = connection.execute(
            text(
                "SELECT character_revelation_id FROM security.character_revelations "
                "WHERE character_revelation_id = :r"
            ),
            {"r": current},
        ).scalar_one()
        connection.execute(
            text(
                "UPDATE security.character_revelations SET ended_at = clock_timestamp(), "
                "end_reason = 'target_membership_ended' WHERE character_revelation_id = :r"
            ),
            {"r": closing},
        )
        second = insert(connection, g, c, "campaign_current", creator=g.o2)
        _snapshot_row(connection, g, second, g.player)
        with pytest.raises(IntegrityError), connection.begin_nested():
            _snapshot_row(connection, g, second, g.player)
        with pytest.raises(IntegrityError), connection.begin_nested():
            _snapshot_row(connection, g, second, foreign)


def test_a_snapshot_row_can_only_be_removed_once_and_never_deleted(
    postgres_engine: Engine, g: Gate, rev: Rev
) -> None:
    with postgres_engine.begin() as connection:
        current = insert(connection, g, rev.character_id, "campaign_current")
        _snapshot_row(connection, g, current, g.player)
    update = (
        "UPDATE security.character_revelation_members SET {} WHERE character_revelation_id = :r"
    )
    for assignment in (
        "removed_at = NULL",
        "removed_at = now()",  # without a reason
        "removal_reason = 'membership_ended'",  # without a time
        "removed_at = now(), removal_reason = 'revoked'",  # an unknown reason
        f"campaign_membership_id = '{g.o2}', removed_at = now(), removal_reason = 'membership_ended'",
    ):
        refused(
            postgres_engine,
            lambda cn, a=assignment: cn.execute(text(update.format(a)), {"r": current}),  # type: ignore[misc]
        )
    with postgres_engine.begin() as connection:
        connection.execute(
            text(update.format("removed_at = now(), removal_reason = 'membership_ended'")),
            {"r": current},
        )
    refused(
        postgres_engine,
        lambda cn: cn.execute(
            text(
                update.format(
                    "removed_at = now() + interval '1 day', removal_reason = 'membership_ended'"
                )
            ),
            {"r": current},
        ),
        containing="removed, once",
    )
    refused(
        postgres_engine,
        lambda cn: cn.execute(
            text(
                "DELETE FROM security.character_revelation_members "
                "WHERE character_revelation_id = :r"
            ),
            {"r": current},
        ),
        containing="never deleted",
    )
    refused(
        postgres_engine,
        lambda cn: cn.execute(text("TRUNCATE security.character_revelation_members")),
        containing="never deleted",
    )


# --- the new capability -----------------------------------------------------------------------


def test_character_view_public_profile_has_no_role_relationship_or_allow_grant_source(
    postgres_engine: Engine, g: Gate, rev: Rev
) -> None:
    with postgres_engine.connect() as connection:
        capability = lookup_id(
            connection, "security", "capabilities", "capability_id", "character.view_public_profile"
        )
        relationship_type = connection.execute(
            text(
                "SELECT character_relationship_type_id FROM security.character_relationship_types "
                "LIMIT 1"
            )
        ).scalar_one()
    refused(
        postgres_engine,
        lambda cn: cn.execute(
            text("INSERT INTO security.role_capabilities (role_id, capability_id) VALUES (:r, :c)"),
            {"r": g.player_role_id, "c": capability},
        ),
        containing="comes only from a character revelation",
    )
    refused(
        postgres_engine,
        lambda cn: cn.execute(
            text(
                "INSERT INTO security.character_relationship_type_capabilities "
                "(character_relationship_type_id, capability_id) VALUES (:t, :c)"
            ),
            {"t": relationship_type, "c": capability},
        ),
        containing="comes only from a character revelation",
    )
    refused(
        postgres_engine,
        lambda cn: make_resource_grant(
            cn, g.campaign_id, capability, timeline_id=g.timeline_id,
            grantee_campaign_membership_id=g.player, effect="allow",
            entity_id=rev.character_id,
        ),
        containing="comes only from a character revelation",
    )  # fmt: skip
    # A deny is accepted and honoured (decision D12).
    with postgres_engine.begin() as connection:
        make_resource_grant(
            connection, g.campaign_id, capability, timeline_id=g.timeline_id,
            grantee_campaign_membership_id=g.player, effect="deny",
            entity_id=rev.character_id,
        )  # fmt: skip


def test_the_application_roles_can_only_close_rows_and_the_reporting_role_reads_nothing(
    postgres_engine: Engine,
) -> None:
    with postgres_engine.connect() as connection:

        def has(role: str, table: str, privilege: str, column: str | None = None) -> bool:
            if column is None:
                sql = "SELECT has_table_privilege(:r, :t, :p)"
            else:
                sql = "SELECT has_column_privilege(:r, :t, :col, :p)"
            return bool(
                connection.execute(
                    text(sql), {"r": role, "t": table, "p": privilege, "col": column}
                ).scalar_one()
            )

        for role in ("app_read_write", "integration_worker"):
            for table in (
                "security.character_revelations",
                "security.character_revelation_members",
            ):
                assert not has(role, table, "UPDATE")  # table-wide; columns are granted singly
                if role == "app_read_write":
                    assert has(role, table, "SELECT") and has(role, table, "INSERT")
                assert not has(role, table, "DELETE") and not has(role, table, "TRUNCATE")
            assert not has(role, "security.character_revelations", "UPDATE", "reason")
            assert not has(
                role, "security.character_revelation_members", "UPDATE", "campaign_membership_id"
            )
        assert has("app_read_write", "security.character_revelations", "UPDATE", "ended_at")
        assert has(
            "app_read_write", "security.character_revelation_members", "UPDATE", "removed_at"
        )
        for table in ("security.character_revelations", "security.character_revelation_members"):
            assert not has("app_read_only", table, "SELECT")
