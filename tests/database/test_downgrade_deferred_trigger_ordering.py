"""Regression tests for a High-severity multi-revision downgrade defect:
revisions `085_campaign_owner_capabilities` and `086_system_role_
capabilities` each `DELETE` rows from `security.role_capabilities` as part
of their own `downgrade()`, queuing one pending firing of that table's
`DEFERRABLE INITIALLY DEFERRED` `tr_role_capabilities_retain_access_
manager` constraint trigger (migration 080) per row deleted. A single
`alembic downgrade base` runs every revision's `downgrade()` inside one
continuous transaction (`database/migrations/env.py`'s `context.
begin_transaction()` spans the whole run), so those pending firings were
still queued when `080_security_identity_and_access`'s own `downgrade()`
— reached later in that same transaction — tried to `DROP TABLE security.
role_capabilities`, and PostgreSQL refuses to drop a table with pending
trigger events against it (`psycopg.errors.ObjectInUse: cannot DROP TABLE
"role_capabilities" because it has pending trigger events`).

The fix (see 085/086's own "Rollback" docstring sections) adds one `SET
CONSTRAINTS security.tr_role_capabilities_retain_access_manager IMMEDIATE`
statement to each migration's own `downgrade()`, immediately after the
`DELETE`s that queue the pending firings — draining them right there,
where the trigger function itself always no-ops for these specific rows
(neither migration ever deletes an `access.manage` row), rather than
depending on a later, unrelated revision's `downgrade()` to compensate for
what an earlier one queued.

Every test here provisions its own disposable, throwaway database (never
the developer's own working database, and never the shared session-scoped
`postgres_engine` every other test in this suite reuses, since running
`alembic downgrade`/`upgrade` as a subprocess against a URL mutates that
database's actual migration state) — the same pattern `tests/database/
test_phase8_populated_upgrade.py` already established for populated-
upgrade proofs, adapted here for a populated *downgrade*.
"""

import os
import subprocess
import uuid
from pathlib import Path

import pytest
from sqlalchemy import Connection, Engine, create_engine, make_url, text
from sqlalchemy.exc import IntegrityError, InternalError, ProgrammingError

from dnd_ai.api.idempotency import (
    CampaignCreationReservation,
    begin_campaign_creation_request,
    complete_campaign_creation_request,
)
from dnd_ai.commands.campaigns import create_campaign, grant_timeline_bootstrap
from tests.factories import (
    make_campaign,
    make_campaign_membership,
    make_membership_role,
    make_ruleset_version_for_world,
    make_timeline,
    make_user,
    make_world,
)

pytestmark = pytest.mark.database

CONSTRAINT_ERRORS = (IntegrityError, InternalError, ProgrammingError)

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "database" / "alembic.ini"

_SYSTEM_ROLE_CODES = ("gm", "assistant_gm", "player", "observer")


# ---------------------------------------------------------------------------
# Disposable-database provisioning (mirrors test_phase8_populated_upgrade.py)
# ---------------------------------------------------------------------------


def _require_admin_url() -> str:
    admin_url_raw = os.environ.get("DATABASE_URL")
    if not admin_url_raw:
        pytest.skip(
            "DATABASE_URL is not set — these tests provision their own throwaway "
            "database and need an admin/bootstrap connection, same precondition as "
            "tests/conftest.py::postgres_engine."
        )
    return admin_url_raw


def _provision_database(label: str) -> tuple[str, str]:
    """Creates a fresh, unmigrated throwaway database. Returns (admin_url, test_url)."""
    admin_url = make_url(_require_admin_url())
    db_name = f"dnd_ai_downgrade_{label}_{uuid.uuid4().hex[:12]}"
    test_url = admin_url.set(database=db_name)

    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    admin_engine.dispose()

    return (
        admin_url.render_as_string(hide_password=False),
        test_url.render_as_string(hide_password=False),
    )


def _drop_database(admin_url: str, test_url: str) -> None:
    db_name = make_url(test_url).database
    admin_engine = create_engine(make_url(admin_url), isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))
    admin_engine.dispose()


def _alembic(
    database_url: str, *args: str, env_extra: dict[str, str] | None = None
) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(
        ["alembic", "-c", str(ALEMBIC_INI), *args],
        cwd=REPO_ROOT,
        env={**os.environ, "DATABASE_URL": database_url, **(env_extra or {})},
        capture_output=True,
        text=True,
    )


def _alembic_upgrade(database_url: str, target: str) -> None:
    result = _alembic(database_url, "upgrade", target)
    assert result.returncode == 0, result.stdout + result.stderr


def _current_revision(database_url: str) -> str:
    result = _alembic(database_url, "current")
    assert result.returncode == 0, result.stdout + result.stderr
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    assert lines, f"alembic current produced no output: {result.stdout!r}"
    # For example, "e3f791aca64d (head)" or "088_precampaign_idempotency".
    return lines[-1].split()[0]


# ---------------------------------------------------------------------------
# Population helpers — raw SQL/factory-based, never through the HTTP layer,
# so each can be used against a database stopped at any specific revision.
# ---------------------------------------------------------------------------


def _system_role_id(connection: Connection, code: str) -> uuid.UUID:
    value = connection.execute(
        text("SELECT role_id FROM security.roles WHERE code = :c AND campaign_id IS NULL"),
        {"c": code},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def _populate_campaign_with_system_role_assignments(connection: Connection) -> uuid.UUID:
    """An active campaign with a campaign_owner membership (satisfying the
    access-manager retention invariant at commit) plus one membership per
    gm/assistant_gm/player/observer system-template role — real
    security.campaign_memberships/.membership_roles rows exercising every
    role revisions 085/086 grant capabilities to, not merely their shared
    security.role_capabilities rows in isolation. Uses only tests.factories
    helpers and direct SQL, never dnd_ai.commands.campaigns.create_campaign
    (which requires revision 087's security.timeline_bootstrap_grants
    table, not always present at the revision this is called against)."""
    slug = f"downgrade-{uuid.uuid4().hex[:8]}"
    world_id = make_world(connection, slug=slug)
    timeline_id = make_timeline(connection, world_id, is_primary=True)
    ruleset_version_id = make_ruleset_version_for_world(connection, world_id)
    campaign_id = make_campaign(
        connection,
        timeline_id,
        f"{slug} campaign",
        ruleset_version_id=ruleset_version_id,
        lifecycle_status_code="active",
    )

    owner_user_id = make_user(connection, f"{slug} owner")
    owner_membership_id = make_campaign_membership(connection, campaign_id, owner_user_id)
    make_membership_role(
        connection, owner_membership_id, _system_role_id(connection, "campaign_owner")
    )

    for role_code in _SYSTEM_ROLE_CODES:
        user_id = make_user(connection, f"{slug} {role_code}")
        membership_id = make_campaign_membership(connection, campaign_id, user_id)
        make_membership_role(connection, membership_id, _system_role_id(connection, role_code))

    return campaign_id


def _populate_full_head_state(connection: Connection) -> None:
    """Head-schema population exercising every table revisions 085-088
    touch with real data: an active campaign with owner/gm/assistant_gm/
    player/observer role assignments (085/086), one still-live bootstrap
    grant nobody has claimed yet (087), and one completed campaign-
    creation reservation (088) — proving the full downgrade chain
    tolerates real rows in every one of them, not just empty tables."""
    campaign_id = _populate_campaign_with_system_role_assignments(connection)

    world_id = connection.execute(
        text(
            "SELECT world_id FROM campaign.timelines WHERE timeline_id IN "
            "(SELECT timeline_id FROM campaign.campaigns WHERE campaign_id = :c)"
        ),
        {"c": campaign_id},
    ).scalar()
    assert isinstance(world_id, uuid.UUID)
    other_timeline_id = make_timeline(connection, world_id)
    unclaimed_grant_user_id = make_user(connection, "downgrade unclaimed grant holder")
    grant_timeline_bootstrap(
        connection, timeline_id=other_timeline_id, granted_to_user_id=unclaimed_grant_user_id
    )

    reservation_timeline_id = make_timeline(connection, world_id)
    ruleset_version_id = make_ruleset_version_for_world(connection, world_id)
    reservation_creator_id = make_user(connection, "downgrade reservation creator")
    grant_timeline_bootstrap(
        connection, timeline_id=reservation_timeline_id, granted_to_user_id=reservation_creator_id
    )
    key = f"downgrade-populate-{uuid.uuid4().hex[:8]}"
    payload = {
        "timeline_id": str(reservation_timeline_id),
        "ruleset_version_id": str(ruleset_version_id),
        "name": "Downgrade Populated Reservation Campaign",
    }
    reservation = begin_campaign_creation_request(
        connection,
        actor_user_id=reservation_creator_id,
        idempotency_key=key,
        payload=payload,
        correlation_id=None,
    )
    assert isinstance(reservation, CampaignCreationReservation)
    result = create_campaign(
        connection,
        timeline_id=reservation_timeline_id,
        ruleset_version_id=ruleset_version_id,
        name="Downgrade Populated Reservation Campaign",
        creator_user_id=reservation_creator_id,
    )
    complete_campaign_creation_request(
        connection,
        campaign_creation_reservation_id=reservation.campaign_creation_reservation_id,
        response_status_code=201,
        response_body={"campaign_id": str(result.campaign_id)},
        campaign_id=result.campaign_id,
    )


# ---------------------------------------------------------------------------
# 1-2. Single-step downgrades with populated data
# ---------------------------------------------------------------------------


def test_downgrading_from_086_to_085_succeeds_with_populated_system_role_assignments() -> None:
    admin_url, test_url = _provision_database("086_to_085")
    try:
        _alembic_upgrade(test_url, "086_system_role_capabilities")

        engine = create_engine(test_url)
        try:
            with engine.begin() as conn:
                _populate_campaign_with_system_role_assignments(conn)
        finally:
            engine.dispose()

        result = _alembic(test_url, "downgrade", "085_campaign_owner_capabilities")
        assert result.returncode == 0, result.stdout + result.stderr
        assert _current_revision(test_url) == "085_campaign_owner_capabilities"

        engine = create_engine(test_url)
        try:
            with engine.connect() as conn:
                remaining_system_role_caps = conn.execute(
                    text("""
                        SELECT count(*)
                        FROM security.role_capabilities rc
                        JOIN security.roles r ON r.role_id = rc.role_id
                        WHERE r.campaign_id IS NULL AND r.code = ANY(:codes)
                    """),
                    {"codes": list(_SYSTEM_ROLE_CODES)},
                ).scalar_one()
                assert remaining_system_role_caps == 0

                owner_cap_count = conn.execute(
                    text("""
                        SELECT count(*) FROM security.role_capabilities rc
                        JOIN security.roles r ON r.role_id = rc.role_id
                        WHERE r.code = 'campaign_owner' AND r.campaign_id IS NULL
                    """)
                ).scalar_one()
                assert owner_cap_count == 3  # access.manage, campaign.view, canon.edit (085)
        finally:
            engine.dispose()
    finally:
        _drop_database(admin_url, test_url)


def test_downgrading_from_085_to_084_succeeds_with_active_campaigns_and_owner_assignments() -> None:
    admin_url, test_url = _provision_database("085_to_084")
    try:
        _alembic_upgrade(test_url, "085_campaign_owner_capabilities")

        engine = create_engine(test_url)
        campaign_id: uuid.UUID
        try:
            with engine.begin() as conn:
                slug = f"downgrade-085-{uuid.uuid4().hex[:8]}"
                world_id = make_world(conn, slug=slug)
                timeline_id = make_timeline(conn, world_id, is_primary=True)
                ruleset_version_id = make_ruleset_version_for_world(conn, world_id)
                campaign_id = make_campaign(
                    conn,
                    timeline_id,
                    f"{slug} campaign",
                    ruleset_version_id=ruleset_version_id,
                    lifecycle_status_code="active",
                )
                owner_user_id = make_user(conn, f"{slug} owner")
                owner_membership_id = make_campaign_membership(conn, campaign_id, owner_user_id)
                make_membership_role(
                    conn, owner_membership_id, _system_role_id(conn, "campaign_owner")
                )
        finally:
            engine.dispose()

        result = _alembic(test_url, "downgrade", "084_hazard_interaction_types")
        assert result.returncode == 0, result.stdout + result.stderr
        assert _current_revision(test_url) == "084_hazard_interaction_types"

        engine = create_engine(test_url)
        try:
            with engine.connect() as conn:
                owner_cap_count = conn.execute(
                    text("""
                        SELECT count(*) FROM security.role_capabilities rc
                        JOIN security.roles r ON r.role_id = rc.role_id
                        WHERE r.code = 'campaign_owner' AND r.campaign_id IS NULL
                    """)
                ).scalar_one()
                assert owner_cap_count == 1  # access.manage only (migration 080's original seed)

                campaign_status = conn.execute(
                    text("""
                        SELECT ls.code FROM campaign.campaigns c
                        JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = c.lifecycle_status_id
                        WHERE c.campaign_id = :c
                    """),
                    {"c": campaign_id},
                ).scalar_one()
                assert campaign_status == "active"
        finally:
            engine.dispose()
    finally:
        _drop_database(admin_url, test_url)


# ---------------------------------------------------------------------------
# 3, 5, 6. A single `downgrade base` from head, fresh and populated, then
# re-upgrading to head and re-proving the retention invariant.
# ---------------------------------------------------------------------------


def _assert_retention_invariant_still_enforced(engine: Engine) -> None:
    """Creates a fresh campaign at head and proves the access-manager
    retention invariant (security.assert_campaign_retains_access_manager,
    enforced by the DEFERRABLE constraint triggers migration 080 created)
    still rejects revoking a sole owner's access.manage-holding role —
    i.e. that those triggers/functions came back intact from a full
    downgrade/upgrade round trip, not merely that the tables did."""
    with engine.connect() as conn, conn.begin():
        slug = f"retention-{uuid.uuid4().hex[:8]}"
        world_id = make_world(conn, slug=slug)
        timeline_id = make_timeline(conn, world_id, is_primary=True)
        ruleset_version_id = make_ruleset_version_for_world(conn, world_id)
        creator_user_id = make_user(conn, f"{slug} creator")
        grant_timeline_bootstrap(conn, timeline_id=timeline_id, granted_to_user_id=creator_user_id)
        result = create_campaign(
            conn,
            timeline_id=timeline_id,
            ruleset_version_id=ruleset_version_id,
            name=f"{slug} campaign",
            creator_user_id=creator_user_id,
        )
        membership_role_id = conn.execute(
            text(
                "SELECT membership_role_id FROM security.membership_roles "
                "WHERE campaign_membership_id = :m"
            ),
            {"m": result.campaign_membership_id},
        ).scalar_one()

        conn.execute(
            text(
                "UPDATE security.membership_roles SET revoked_at = now() "
                "WHERE membership_role_id = :id"
            ),
            {"id": membership_role_id},
        )
        with pytest.raises(CONSTRAINT_ERRORS) as exc:
            conn.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        assert "would be left with no membership" in str(exc.value)
        # Exiting `conn.begin()` on the raised exception rolls the whole
        # transaction back automatically.


def test_a_fresh_migrated_database_survives_a_full_downgrade_to_base_and_reupgrades_to_head() -> (
    None
):
    admin_url, test_url = _provision_database("fresh_base")
    try:
        _alembic_upgrade(test_url, "head")
        head_revision = _current_revision(test_url)

        result = _alembic(test_url, "downgrade", "base")
        assert result.returncode == 0, result.stdout + result.stderr

        _alembic_upgrade(test_url, "head")
        assert _current_revision(test_url) == head_revision

        engine = create_engine(test_url)
        try:
            _assert_retention_invariant_still_enforced(engine)
        finally:
            engine.dispose()
    finally:
        _drop_database(admin_url, test_url)


def test_a_realistically_populated_database_survives_a_full_downgrade_to_base_and_reupgrades_to_head() -> (
    None
):
    admin_url, test_url = _provision_database("populated_base")
    try:
        _alembic_upgrade(test_url, "head")
        head_revision = _current_revision(test_url)

        engine = create_engine(test_url)
        try:
            with engine.begin() as conn:
                _populate_full_head_state(conn)
        finally:
            engine.dispose()

        result = _alembic(test_url, "downgrade", "base")
        assert result.returncode == 0, result.stdout + result.stderr

        _alembic_upgrade(test_url, "head")
        assert _current_revision(test_url) == head_revision

        engine = create_engine(test_url)
        try:
            _assert_retention_invariant_still_enforced(engine)
        finally:
            engine.dispose()
    finally:
        _drop_database(admin_url, test_url)


# ---------------------------------------------------------------------------
# 4. A failed downgrade rolls back fully — no partial schema loss.
# ---------------------------------------------------------------------------


def test_a_failed_downgrade_rolls_back_leaving_the_original_revision_and_full_schema_intact() -> (
    None
):
    """Forces a downgrade failure for a reason unrelated to the deferred-
    trigger defect this file otherwise regression-tests — an ACCESS
    EXCLUSIVE lock held on security.role_capabilities from a second
    connection, with a short lock_timeout on the alembic subprocess itself
    (via PGOPTIONS) so the attempt fails deterministically rather than
    hanging. `alembic downgrade base` runs the whole chain inside one
    transaction (this file's own module docstring), so a failure at
    086_system_role_capabilities's own DELETE — the first statement in the
    chain that touches the locked table — must roll back everything,
    including 088/087's own already-executed DROP TABLEs, leaving the
    database exactly at head with every table still present."""
    admin_url, test_url = _provision_database("failed_downgrade")
    try:
        _alembic_upgrade(test_url, "head")
        head_revision = _current_revision(test_url)

        lock_engine = create_engine(test_url)
        lock_conn = lock_engine.connect()
        lock_conn.execute(text("BEGIN"))
        lock_conn.execute(text("LOCK TABLE security.role_capabilities IN ACCESS EXCLUSIVE MODE"))
        try:
            result = _alembic(
                test_url, "downgrade", "base", env_extra={"PGOPTIONS": "-c lock_timeout=2000"}
            )
            assert result.returncode != 0, (
                "expected the downgrade to fail while the conflicting lock was held:\n"
                + result.stdout
                + result.stderr
            )
        finally:
            lock_conn.rollback()
            lock_conn.close()
            lock_engine.dispose()

        assert _current_revision(test_url) == head_revision

        engine = create_engine(test_url)
        try:
            with engine.connect() as conn:
                for schema, table in [
                    ("security", "role_capabilities"),
                    ("security", "roles"),
                    ("security", "campaign_memberships"),
                    ("security", "membership_roles"),
                    ("security", "timeline_bootstrap_grants"),
                    ("security", "campaign_creation_reservations"),
                    ("campaign", "campaigns"),
                ]:
                    exists = conn.execute(
                        text(
                            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                            "WHERE table_schema = :s AND table_name = :t)"
                        ),
                        {"s": schema, "t": table},
                    ).scalar_one()
                    assert exists, (
                        f"{schema}.{table} should still exist after a rolled-back downgrade"
                    )
        finally:
            engine.dispose()
    finally:
        _drop_database(admin_url, test_url)
