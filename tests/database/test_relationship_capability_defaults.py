"""Production relationship-capability defaults (migration 114, checkpoint 15.2A-1).

The shared test database is already at head, so the clean-install and resolver
checks run against it and roll back. The upgrade-reconciliation checks need a
database paused at revision 113, so they provision a throwaway one (the same
pattern as test_organization_hierarchy_migration.py).

These tests use the real relationship policy: `real_relationship_policy` turns
off the permissive relaxation the legacy access tests run under.
"""

import importlib.util
import uuid
from pathlib import Path

import pytest
from sqlalchemy import Connection, create_engine, text

from dnd_ai.domain.access import (
    ADMITTED_RELATIONSHIP_TYPES,
    BUILTIN_RELATIONSHIP_CAPABILITIES,
    relationship_capability_permitted,
    resolve_access_context,
)
from dnd_ai.queries.bootstrap import get_session_bootstrap
from tests.database.test_organization_hierarchy_migration import _alembic
from tests.database.test_phase8_populated_upgrade import (
    _alembic_upgrade,
    _connect_args,
    _drop_database,
    _provision_database,
)
from tests.factories import (
    make_campaign,
    make_campaign_membership,
    make_capability,
    make_character,
    make_character_relationship_type,
    make_membership_character_relationship,
    make_membership_role,
    make_relationship_type_capability,
    make_timeline,
    make_user,
    make_world,
    system_role_id,
)

pytestmark = [pytest.mark.database, pytest.mark.real_relationship_policy]

_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "migrations"
    / "versions"
    / "114_relationship_defaults.py"
)

_PERSPECTIVE_TYPES = ("owner", "primary_controller", "co_controller", "portrayer")
_VIEW_ONLY_TYPES = ("viewer", "observer_approved_viewer")
_WITHHELD = (
    "character.edit_narrative",
    "character.edit_mechanical_state",
    "character.control",
    "character.interact",
)


def _type_id(connection: Connection, code: str) -> uuid.UUID:
    value = connection.execute(
        text(
            "SELECT character_relationship_type_id FROM security.character_relationship_types "
            "WHERE code = :c"
        ),
        {"c": code},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def _mapping_pairs(connection: Connection) -> set[tuple[str, str]]:
    rows = connection.execute(
        text("""
            SELECT rt.code, cap.code
            FROM security.character_relationship_type_capabilities rtc
            JOIN security.character_relationship_types rt
              ON rt.character_relationship_type_id = rtc.character_relationship_type_id
            JOIN security.capabilities cap ON cap.capability_id = rtc.capability_id
        """)
    ).all()
    return {(str(t), str(c)) for t, c in rows}


class Setup:
    """A campaign with one player membership and one active character."""

    def __init__(self, connection: Connection) -> None:
        self.connection = connection
        self.world_id = make_world(connection, slug=f"rel-{uuid.uuid4().hex[:8]}")
        timeline_id = make_timeline(connection, self.world_id, "Primary", is_primary=True)
        self.campaign_id = make_campaign(connection, timeline_id)
        self.user_id = make_user(connection, "Player")
        self.membership_id = make_campaign_membership(connection, self.campaign_id, self.user_id)
        make_membership_role(connection, self.membership_id, system_role_id(connection, "player"))
        self.character_id = make_character(connection, self.world_id, name="Hero")

    def relate(self, type_id: uuid.UUID, *, revoked: bool = False) -> None:
        make_membership_character_relationship(
            self.connection,
            self.membership_id,
            self.character_id,
            type_id,
            revoked=revoked,
        )

    def capabilities(self) -> set[str]:
        context = resolve_access_context(
            self.connection, user_id=self.user_id, campaign_id=self.campaign_id
        )
        assert context is not None
        return set(context.character_capabilities.get(self.character_id, set()))


# --- production reference data ------------------------------------------------------------


def test_a_clean_install_holds_exactly_the_approved_matrix(db_connection: Connection) -> None:
    expected = {
        (type_code, capability)
        for type_code, capabilities in BUILTIN_RELATIONSHIP_CAPABILITIES.items()
        for capability in capabilities
    }
    assert _mapping_pairs(db_connection) == expected


def test_the_migration_matrix_and_the_code_matrix_agree() -> None:
    spec = importlib.util.spec_from_file_location("rel_defaults_migration", _MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert {k: frozenset(v) for k, v in module._MATRIX.items()} == BUILTIN_RELATIONSHIP_CAPABILITIES


def test_every_seeded_relationship_type_is_admitted_and_phase16_capabilities_are_withheld(
    db_connection: Connection,
) -> None:
    codes = {
        str(c)
        for c in db_connection.execute(
            text("SELECT code FROM security.character_relationship_types")
        ).scalars()
    }
    assert codes == set(ADMITTED_RELATIONSHIP_TYPES)
    for capabilities in BUILTIN_RELATIONSHIP_CAPABILITIES.values():
        assert not capabilities & set(_WITHHELD)


def test_re_applying_the_defaults_is_idempotent(db_connection: Connection) -> None:
    before = _mapping_pairs(db_connection)
    spec = importlib.util.spec_from_file_location("rel_defaults_migration", _MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # The insert half of the migration alone (ON CONFLICT DO NOTHING).
    db_connection.execute(
        text(f"""
            INSERT INTO security.character_relationship_type_capabilities
                (character_relationship_type_id, capability_id)
            SELECT rt.character_relationship_type_id, cap.capability_id
            FROM (VALUES {module._allowed_values()}) AS allowed(type_code, cap_code)
            JOIN security.character_relationship_types rt ON rt.code = allowed.type_code
            JOIN security.capabilities cap ON cap.code = allowed.cap_code
            ON CONFLICT DO NOTHING
        """)
    )
    assert _mapping_pairs(db_connection) == before


# --- resolver: per built-in type ----------------------------------------------------------


@pytest.mark.parametrize("type_code", sorted(BUILTIN_RELATIONSHIP_CAPABILITIES))
def test_each_built_in_type_confers_exactly_its_matrix_entry(
    db_connection: Connection, type_code: str
) -> None:
    setup = Setup(db_connection)
    setup.relate(_type_id(db_connection, type_code))
    assert setup.capabilities() == set(BUILTIN_RELATIONSHIP_CAPABILITIES[type_code])


@pytest.mark.parametrize("type_code", _PERSPECTIVE_TYPES)
def test_perspective_types_hold_view_knowledge_and_the_full_read_tier(
    db_connection: Connection, type_code: str
) -> None:
    setup = Setup(db_connection)
    setup.relate(_type_id(db_connection, type_code))
    capabilities = setup.capabilities()
    assert {"character.view_knowledge", "character.view_full", "character.view_summary"} <= (
        capabilities
    )


@pytest.mark.parametrize("type_code", _VIEW_ONLY_TYPES)
def test_view_only_types_hold_the_summary_tier_and_no_perspective(
    db_connection: Connection, type_code: str
) -> None:
    setup = Setup(db_connection)
    setup.relate(_type_id(db_connection, type_code))
    capabilities = setup.capabilities()
    assert capabilities == {"character.discover", "character.view_summary"}
    assert "character.view_full" not in capabilities
    assert "character.view_knowledge" not in capabilities


def test_former_controller_confers_nothing(db_connection: Connection) -> None:
    setup = Setup(db_connection)
    setup.relate(_type_id(db_connection, "former_controller"))
    assert setup.capabilities() == set()


def test_only_owner_and_primary_controller_hold_view_private(db_connection: Connection) -> None:
    holders = {
        code
        for code, capabilities in BUILTIN_RELATIONSHIP_CAPABILITIES.items()
        if "character.view_private" in capabilities
    }
    assert holders == {"owner", "primary_controller"}


# --- resolver: default deny ---------------------------------------------------------------


def test_a_custom_type_with_mapped_rows_confers_nothing(db_connection: Connection) -> None:
    setup = Setup(db_connection)
    custom = make_character_relationship_type(db_connection, "guild_mentor")
    make_relationship_type_capability(
        db_connection, custom, make_capability(db_connection, "character.view_full_custom")
    )
    for code in ("character.view_full", "character.view_knowledge"):
        capability_id = db_connection.execute(
            text("SELECT capability_id FROM security.capabilities WHERE code = :c"), {"c": code}
        ).scalar()
        assert isinstance(capability_id, uuid.UUID)
        make_relationship_type_capability(db_connection, custom, capability_id)
    setup.relate(custom)
    assert setup.capabilities() == set()


def test_a_stray_row_outside_the_matrix_is_not_effective(db_connection: Connection) -> None:
    setup = Setup(db_connection)
    owner = _type_id(db_connection, "owner")
    control = db_connection.execute(
        text("SELECT capability_id FROM security.capabilities WHERE code = 'character.control'")
    ).scalar()
    assert isinstance(control, uuid.UUID)
    make_relationship_type_capability(db_connection, owner, control)
    setup.relate(owner)
    assert "character.control" not in setup.capabilities()
    assert setup.capabilities() == set(BUILTIN_RELATIONSHIP_CAPABILITIES["owner"])


def test_an_inactive_type_confers_nothing_on_the_next_request(db_connection: Connection) -> None:
    setup = Setup(db_connection)
    owner = _type_id(db_connection, "owner")
    setup.relate(owner)
    assert setup.capabilities()
    db_connection.execute(
        text(
            "UPDATE security.character_relationship_types SET is_active = false "
            "WHERE character_relationship_type_id = :t"
        ),
        {"t": owner},
    )
    assert setup.capabilities() == set()


def test_a_revoked_relationship_confers_nothing(db_connection: Connection) -> None:
    setup = Setup(db_connection)
    setup.relate(_type_id(db_connection, "owner"), revoked=True)
    assert setup.capabilities() == set()


def test_the_policy_function_refuses_unknown_types_and_unlisted_capabilities() -> None:
    assert relationship_capability_permitted("owner", "character.view_full")
    assert not relationship_capability_permitted("owner", "character.control")
    assert not relationship_capability_permitted("former_controller", "character.discover")
    assert not relationship_capability_permitted("custom", "character.view_summary")


# --- independent authority is not removed ------------------------------------------------


def test_the_relationship_matrix_does_not_remove_role_derived_grants(
    db_connection: Connection,
) -> None:
    """A `viewer` relationship limits only what the relationship itself confers;
    a role capability is an independent source and is untouched."""
    setup = Setup(db_connection)
    setup.relate(_type_id(db_connection, "viewer"))
    role_capability = db_connection.execute(
        text("""
            SELECT 1 FROM security.role_capabilities rc
            JOIN security.roles r ON r.role_id = rc.role_id
            JOIN security.capabilities cap ON cap.capability_id = rc.capability_id
            WHERE r.code = 'gm' AND r.campaign_id IS NULL AND cap.code = 'canon.edit'
        """)
    ).scalar()
    assert role_capability == 1


# --- bootstrap perspectives --------------------------------------------------------------


@pytest.mark.parametrize(
    ("type_code", "selectable"),
    [
        ("owner", True),
        ("primary_controller", True),
        ("co_controller", True),
        ("portrayer", True),
        ("viewer", False),
        ("observer_approved_viewer", False),
        ("former_controller", False),
    ],
)
def test_only_the_four_controller_types_make_a_character_selectable(
    db_connection: Connection, type_code: str, selectable: bool
) -> None:
    setup = Setup(db_connection)
    setup.relate(_type_id(db_connection, type_code))
    campaign = get_session_bootstrap(db_connection, user_id=setup.user_id).campaigns[0]
    assert (len(campaign.character_perspectives) == 1) is selectable


def test_revoking_the_relationship_removes_the_perspective_on_the_next_call(
    db_connection: Connection,
) -> None:
    setup = Setup(db_connection)
    setup.relate(_type_id(db_connection, "owner"))
    assert (
        get_session_bootstrap(db_connection, user_id=setup.user_id)
        .campaigns[0]
        .character_perspectives
    )
    db_connection.execute(
        text("UPDATE security.membership_character_relationships SET revoked_at = now()")
    )
    assert (
        get_session_bootstrap(db_connection, user_id=setup.user_id)
        .campaigns[0]
        .character_perspectives
        == ()
    )


# --- upgrade reconciliation (throwaway database) -----------------------------------------


def test_upgrade_reconciles_a_database_holding_development_rows_and_round_trips() -> None:
    admin_url, test_url = _provision_database()
    try:
        _alembic_upgrade(test_url, "113_organization_cycle_guard")
        engine = create_engine(test_url, connect_args=_connect_args())
        with engine.begin() as connection:
            owner = _type_id(connection, "owner")
            custom = make_character_relationship_type(connection, "guild_mentor")
            # What the old dev-data script did: every character.* capability for owner,
            # plus an extra pair on a non-matrix built-in type, plus a custom-type row.
            connection.execute(
                text("""
                    INSERT INTO security.character_relationship_type_capabilities
                        (character_relationship_type_id, capability_id)
                    SELECT :owner, capability_id FROM security.capabilities
                    WHERE code LIKE 'character.%'
                """),
                {"owner": owner},
            )
            former = _type_id(connection, "former_controller")
            connection.execute(
                text("""
                    INSERT INTO security.character_relationship_type_capabilities
                        (character_relationship_type_id, capability_id)
                    SELECT :t, capability_id FROM security.capabilities
                    WHERE code = 'character.view_summary'
                """),
                {"t": former},
            )
            connection.execute(
                text("""
                    INSERT INTO security.character_relationship_type_capabilities
                        (character_relationship_type_id, capability_id)
                    SELECT :t, capability_id FROM security.capabilities
                    WHERE code = 'character.view_full'
                """),
                {"t": custom},
            )

        _alembic_upgrade(test_url, "114_relationship_defaults")

        with engine.connect() as connection:
            pairs = _mapping_pairs(connection)
            builtin_pairs = {p for p in pairs if p[0] in BUILTIN_RELATIONSHIP_CAPABILITIES}
            assert builtin_pairs == {
                (t, c) for t, caps in BUILTIN_RELATIONSHIP_CAPABILITIES.items() for c in caps
            }
            # The custom-type row is left in place (ineffective, not deleted).
            assert ("guild_mentor", "character.view_full") in pairs
            audit = connection.execute(
                text("""
                    SELECT actor_service, command_name, changed_fields
                    FROM audit.change_log
                    WHERE command_name = 'reconcile_relationship_capability_defaults'
                """)
            ).one()
            assert audit.actor_service == "migration"
            removed = {(r["type"], r["capability"]) for r in audit.changed_fields["removed"]}
            assert ("owner", "character.control") in removed
            assert ("former_controller", "character.view_summary") in removed
            assert ("owner", "character.view_full") not in removed

        downgraded = _alembic(test_url, "downgrade", "113_organization_cycle_guard")
        assert downgraded.returncode == 0, downgraded.stderr
        with engine.connect() as connection:
            assert _mapping_pairs(connection) == {("guild_mentor", "character.view_full")}

        _alembic_upgrade(test_url, "head")
        with engine.connect() as connection:
            assert {
                p for p in _mapping_pairs(connection) if p[0] in ADMITTED_RELATIONSHIP_TYPES
            } == {(t, c) for t, caps in BUILTIN_RELATIONSHIP_CAPABILITIES.items() for c in caps}
        checked = _alembic(test_url, "check")
        assert checked.returncode == 0, checked.stdout + checked.stderr
        engine.dispose()
    finally:
        _drop_database(admin_url, test_url)


def test_a_clean_upgrade_writes_no_maintenance_audit_row(db_connection: Connection) -> None:
    count = db_connection.execute(
        text(
            "SELECT count(*) FROM audit.change_log "
            "WHERE command_name = 'reconcile_relationship_capability_defaults'"
        )
    ).scalar()
    assert count == 0
