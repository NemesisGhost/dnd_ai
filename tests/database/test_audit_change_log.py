"""Constraint tests for revision 007 — audit.change_log.

Positive and negative per docs/DATABASE_CONVENTIONS.md §32.1. Everything runs
inside the fixture's transaction and rolls back.

The append-only property (§24.2) gets its own tests: it is enforced by grants
rather than by a trigger, which means the usual "insert and see it fail" shape
does not apply — the admin connection these tests run on is allowed to do
everything. So the grants themselves are asserted instead.
"""

import uuid

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError

from tests.factories import lookup_id, make_user, make_world_entity

pytestmark = pytest.mark.database

APPEND_ONLY_ROLES = ["app_read_write", "integration_worker"]


def _action_id(connection: Connection, code: str) -> uuid.UUID:
    return lookup_id(connection, "audit", "change_actions", "change_action_id", code)


def _log(connection: Connection, **kwargs: object) -> None:
    params: dict[str, object] = {
        "action": _action_id(connection, "created"),
        "schema_name": "core",
        "table_name": "entities",
        "record_id": None,
        "entity_id": None,
        "world_id": None,
        "previous_status": None,
        "new_status": None,
        "actor_user_id": None,
        "actor_service": "test-suite",
        "source_id": None,
        "reason": None,
        "correlation_id": None,
        "causation_id": None,
        "command_name": None,
        "event_id": None,
        "ai_proposal_id": None,
        "changed_fields": None,
    }
    params.update(kwargs)
    connection.execute(
        text("""
            INSERT INTO audit.change_log
                (change_action_id, schema_name, table_name, record_id, entity_id, world_id,
                 previous_status, new_status, actor_user_id, actor_service, source_id, reason,
                 correlation_id, causation_id, command_name, event_id, ai_proposal_id,
                 changed_fields)
            VALUES (:action, :schema_name, :table_name, :record_id, :entity_id, :world_id,
                    :previous_status, :new_status, :actor_user_id, :actor_service, :source_id,
                    :reason, :correlation_id, :causation_id, :command_name, :event_id,
                    :ai_proposal_id, CAST(:changed_fields AS JSONB))
        """),
        params,
    )


# ---------------------------------------------------------------------------
# audit.change_actions
# ---------------------------------------------------------------------------


def test_seeded_change_actions_cover_the_lifecycle(db_connection: Connection) -> None:
    codes = {r[0] for r in db_connection.execute(text("SELECT code FROM audit.change_actions"))}
    # "denied" (migration 103, Phase 13B blocker 3): the one action-code gap
    # the original six left — an attempted action that did not succeed and
    # produced no data change (e.g. a failed login), which none of the other
    # six (all of which describe a completed data change) can represent.
    assert codes == {
        "created",
        "updated",
        "status_changed",
        "archived",
        "restored",
        "deleted",
        "denied",
    }


# ---------------------------------------------------------------------------
# audit.change_log
# ---------------------------------------------------------------------------


def test_change_log_records_a_creation(db_connection: Connection) -> None:
    entity = make_world_entity(db_connection, "audit-create")
    user = make_user(db_connection, "auditor")
    _log(db_connection, record_id=entity, entity_id=entity, actor_user_id=user)

    row = db_connection.execute(
        text("SELECT change_log_id, recorded_at FROM audit.change_log WHERE entity_id = :e"),
        {"e": entity},
    ).one()
    assert row.change_log_id is not None
    assert row.recorded_at is not None


def test_change_log_records_a_status_transition(db_connection: Connection) -> None:
    """ENTITY_LIFECYCLE.md §19 wants previous and new status on a transition."""
    entity = make_world_entity(db_connection, "audit-transition")
    _log(
        db_connection,
        action=_action_id(db_connection, "status_changed"),
        entity_id=entity,
        previous_status="draft",
        new_status="canon",
        reason="approved at session review",
    )
    row = db_connection.execute(
        text("SELECT previous_status, new_status FROM audit.change_log WHERE entity_id = :e"),
        {"e": entity},
    ).one()
    assert (row.previous_status, row.new_status) == ("draft", "canon")


def test_change_log_requires_an_actor(db_connection: Connection) -> None:
    """A change with no attributable actor is not auditable (§24.3)."""
    with pytest.raises(IntegrityError):
        _log(db_connection, actor_user_id=None, actor_service=None)


def test_change_log_accepts_a_service_actor_without_a_user(
    db_connection: Connection,
) -> None:
    _log(db_connection, actor_user_id=None, actor_service="foundry-sync")


def test_change_log_accepts_a_user_actor_without_a_service(
    db_connection: Connection,
) -> None:
    user = make_user(db_connection, "human")
    _log(db_connection, actor_user_id=user, actor_service=None)


@pytest.mark.parametrize("bad", ["Core", "core-schema", "9core", ""])
def test_change_log_rejects_malformed_schema_name(db_connection: Connection, bad: str) -> None:
    with pytest.raises(IntegrityError):
        _log(db_connection, schema_name=bad)


def test_change_log_survives_deletion_of_what_it_describes(
    db_connection: Connection,
) -> None:
    """The whole point of an audit log: history outlives the record.

    entity_id deliberately carries no foreign key, so deleting the entity leaves
    the audit row intact and still pointing at the id that used to exist.
    """
    entity = make_world_entity(db_connection, "audit-outlives")
    _log(db_connection, entity_id=entity, record_id=entity)

    db_connection.execute(text("DELETE FROM core.entities WHERE entity_id = :e"), {"e": entity})

    surviving = db_connection.execute(
        text("SELECT count(*) FROM audit.change_log WHERE entity_id = :e"), {"e": entity}
    ).scalar()
    assert surviving == 1, "audit history must outlive the record it describes"


def test_change_log_accepts_a_field_diff(db_connection: Connection) -> None:
    entity = make_world_entity(db_connection, "audit-diff")
    _log(
        db_connection,
        action=_action_id(db_connection, "updated"),
        entity_id=entity,
        changed_fields='{"canonical_name": {"from": "Old", "to": "New"}}',
    )
    stored = db_connection.execute(
        text("SELECT changed_fields FROM audit.change_log WHERE entity_id = :e"),
        {"e": entity},
    ).scalar()
    assert stored == {"canonical_name": {"from": "Old", "to": "New"}}


def test_change_log_ids_are_monotonic(db_connection: Connection) -> None:
    """GENERATED ALWAYS AS IDENTITY — callers cannot supply their own id."""
    entity = make_world_entity(db_connection, "audit-monotonic")
    _log(db_connection, entity_id=entity)
    _log(db_connection, entity_id=entity)
    ids = [
        r[0]
        for r in db_connection.execute(
            text(
                "SELECT change_log_id FROM audit.change_log WHERE entity_id = :e "
                "ORDER BY change_log_id"
            ),
            {"e": entity},
        )
    ]
    assert len(ids) == 2
    assert ids[1] > ids[0]


# ---------------------------------------------------------------------------
# Append-only enforcement (§24.2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("role", APPEND_ONLY_ROLES)
@pytest.mark.parametrize("privilege", ["UPDATE", "DELETE", "TRUNCATE"])
def test_application_roles_cannot_rewrite_audit_history(
    db_connection: Connection, role: str, privilege: str
) -> None:
    """Enforced by grants rather than a trigger, so the grant is what is asserted.

    These tests run on an admin connection that is allowed to do anything, so
    attempting the write here would prove nothing about what app_read_write can do.
    """
    held = db_connection.execute(
        text("""
            SELECT count(*) FROM information_schema.role_table_grants
            WHERE table_schema = 'audit' AND table_name = 'change_log'
              AND grantee = :role AND privilege_type = :priv
        """),
        {"role": role, "priv": privilege},
    ).scalar()
    assert held == 0, (
        f"{role} still holds {privilege} on audit.change_log — audit tables are "
        "append-only to application roles (conventions §24.2)"
    )


@pytest.mark.parametrize("role", APPEND_ONLY_ROLES)
def test_application_roles_can_still_append(db_connection: Connection, role: str) -> None:
    """Append-only means append is still allowed — the positive half."""
    held = {
        r[0]
        for r in db_connection.execute(
            text("""
                SELECT privilege_type FROM information_schema.role_table_grants
                WHERE table_schema = 'audit' AND table_name = 'change_log' AND grantee = :role
            """),
            {"role": role},
        )
    }
    assert "INSERT" in held
    assert "SELECT" in held
