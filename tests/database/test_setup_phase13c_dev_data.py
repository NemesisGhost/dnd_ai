"""scripts/setup_phase13c_dev_data.py apply/rerun behavior.

Exercises `_run()` directly against the ephemeral per-session test database
(`db_connection`, always rolled back — see tests/conftest.py), the same way
`--apply` runs it, without ever touching a real dev/prod database. Proves
the two invariants the task this script supports actually depends on:
running it twice does not duplicate campaigns/memberships/characters/
grants, and the real `get_session_bootstrap` query recognizes the result
(both campaigns, both character perspectives on the first one).

`pythonpath = ["scripts"]` (pyproject.toml) makes `setup_phase13c_dev_data`
importable here the same way `uv run python scripts/setup_phase13c_dev_data.py`
runs it directly — see that setting's own comment for why.
"""

import uuid

from setup_phase13c_dev_data import _run
from sqlalchemy import Connection, text

from dnd_ai.domain.passwords import hash_password
from dnd_ai.queries.bootstrap import get_session_bootstrap
from dnd_ai.queries.character import get_character_view
from tests.factories import make_user


def _make_local_account(connection: Connection, *, display_name: str = "Dev Tester") -> uuid.UUID:
    """A minimal `security.users` row with an active local (issuer='local')
    identity and password credential — the exact shape `setup_phase13c_dev_
    data._resolve_user` requires. Raw inserts, matching tests/factories.py's
    own documented "testing database enforcement" exception: this test is
    specifically exercising the setup script's own database logic, not the
    local-auth activation flow (already covered by
    tests/database/test_local_auth_commands.py)."""
    user_id = make_user(connection, display_name)
    connection.execute(
        text(
            "INSERT INTO security.external_identities (user_id, issuer, subject) "
            "VALUES (:user_id, 'local', 'dev-tester')"
        ),
        {"user_id": user_id},
    )
    connection.execute(
        text(
            "INSERT INTO security.local_credentials (user_id, password_hash) "
            "VALUES (:user_id, :password_hash)"
        ),
        {"user_id": user_id, "password_hash": hash_password("correct horse battery staple")},
    )
    return user_id


def test_run_is_idempotent_and_bootstrap_recognizes_the_result(db_connection: Connection) -> None:
    user_id = _make_local_account(db_connection)

    first = _run(db_connection, user_id=user_id)
    assert first.lines, "first run should have created every record"
    assert all("[created]" in line for line in first.lines), first.lines

    second = _run(db_connection, user_id=user_id)
    assert all("[reused" in line for line in second.lines), second.lines
    # Same number of records recognized both times — nothing duplicated.
    assert len(second.lines) == len(first.lines)

    view = get_session_bootstrap(db_connection, user_id=user_id)
    assert view.display_name == "Dev Tester"
    assert len(view.campaigns) == 2

    names = {c.campaign_name for c in view.campaigns}
    assert names == {"Phase13C Campaign A", "Phase13C Campaign B"}

    timeline_ids = {c.timeline_id for c in view.campaigns}
    assert len(timeline_ids) == 2, "the two campaigns must sit on two distinct timelines"

    campaign_a = next(c for c in view.campaigns if c.campaign_name == "Phase13C Campaign A")
    perspective_names = {p.character_name for p in campaign_a.character_perspectives}
    assert perspective_names == {"Phase13C Character A", "Phase13C Character B"}

    campaign_b = next(c for c in view.campaigns if c.campaign_name == "Phase13C Campaign B")
    assert campaign_b.character_perspectives == ()


def _resolve_campaign_a_characters(
    db_connection: Connection, *, user_id: uuid.UUID
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    """Returns (timeline_a_id, world_id, character_a_id, character_b_id) via
    the real `get_session_bootstrap` query plus one direct `core.entities`
    lookup for `world_id` — the same id `get_character_view`'s own
    `expected_world_id` parameter requires and that only a caller who has
    already resolved the character's timeline (as the portal API does) would
    have on hand."""
    view = get_session_bootstrap(db_connection, user_id=user_id)
    campaign_a = next(c for c in view.campaigns if c.campaign_name == "Phase13C Campaign A")
    assert campaign_a.timeline_id is not None

    character_a_id = next(
        p.character_id
        for p in campaign_a.character_perspectives
        if p.character_name == "Phase13C Character A"
    )
    character_b_id = next(
        p.character_id
        for p in campaign_a.character_perspectives
        if p.character_name == "Phase13C Character B"
    )

    world_id = db_connection.execute(
        text("SELECT world_id FROM core.entities WHERE entity_id = :character"),
        {"character": character_a_id},
    ).scalar()
    assert isinstance(world_id, uuid.UUID)

    return campaign_a.timeline_id, world_id, character_a_id, character_b_id


def test_character_a_and_b_current_state_matches_the_documented_fixture(
    db_connection: Connection,
) -> None:
    """Covers the Phase 13D Current State checkpoint this fixture now
    supports: Character A partially hurt with temporary HP, exhaustion, a
    death save, one condition, and one resource; Character B at a full,
    all-zero baseline with neither. Runs `_run()` twice first — proving the
    new state/condition/resource rows are exactly as idempotent as every
    other row this fixture creates — then reads both characters back through
    the real, tier-filtered `get_character_view()` query the portal's
    character-detail endpoint itself uses, not a re-implementation of it."""
    user_id = _make_local_account(db_connection)

    first = _run(db_connection, user_id=user_id)
    assert first.lines, "first run should have created every record"
    assert all("[created]" in line for line in first.lines), first.lines

    second = _run(db_connection, user_id=user_id)
    assert all("[reused" in line for line in second.lines), second.lines
    assert len(second.lines) == len(first.lines)

    timeline_a_id, world_id, character_a_id, character_b_id = _resolve_campaign_a_characters(
        db_connection, user_id=user_id
    )

    view_a = get_character_view(
        db_connection,
        character_id=character_a_id,
        timeline_id=timeline_a_id,
        expected_world_id=world_id,
        include_full=True,
    )
    assert view_a.current_hit_points == 6
    assert view_a.maximum_hit_points == 12
    assert view_a.temporary_hit_points == 2
    assert view_a.exhaustion_level == 1
    assert view_a.death_save_successes == 1
    assert view_a.death_save_failures == 0
    assert view_a.conditions is not None and len(view_a.conditions) == 1
    assert view_a.conditions[0].condition_code == "poisoned"
    assert view_a.conditions[0].source_description == "Phase 13D portal development fixture"
    assert view_a.resources is not None and len(view_a.resources) == 1
    assert view_a.resources[0].resource_code == "spell_slot"
    assert view_a.resources[0].current_amount == 2
    assert view_a.resources[0].maximum_amount == 3

    view_b = get_character_view(
        db_connection,
        character_id=character_b_id,
        timeline_id=timeline_a_id,
        expected_world_id=world_id,
        include_full=True,
    )
    assert view_b.current_hit_points == 20
    assert view_b.maximum_hit_points == 20
    assert view_b.temporary_hit_points == 0
    assert view_b.exhaustion_level == 0
    assert view_b.death_save_successes == 0
    assert view_b.death_save_failures == 0
    assert view_b.conditions == ()
    assert view_b.resources == ()


def test_rerun_reconciles_character_a_state_condition_and_resource_after_drift(
    db_connection: Connection,
) -> None:
    """The whole point of adding this state to the fixture is live-testing:
    the owner exercises the portal's HP/condition/resource adjustment
    commands by hand, which changes these exact rows. Simulates that drift
    directly (the same raw-SQL-for-setup convention `_make_local_account`
    already uses to build a fixture precondition, not a stand-in for the
    real adjustment commands) and asserts a second `_run()` resets every
    value back to the documented fixture state and reports each as
    "reconciled" rather than "reused"."""
    user_id = _make_local_account(db_connection, display_name="Dev Tester Two")
    _run(db_connection, user_id=user_id)

    timeline_a_id, world_id, character_a_id, _character_b_id = _resolve_campaign_a_characters(
        db_connection, user_id=user_id
    )

    db_connection.execute(
        text("""
            UPDATE campaign.character_state
            SET current_hit_points = 1, temporary_hit_points = 0, exhaustion_level = 3
            WHERE timeline_id = :timeline AND character_id = :character
        """),
        {"timeline": timeline_a_id, "character": character_a_id},
    )
    db_connection.execute(
        text("""
            UPDATE campaign.character_conditions
            SET source_description = 'Manually adjusted during live testing'
            WHERE timeline_id = :timeline AND character_id = :character
        """),
        {"timeline": timeline_a_id, "character": character_a_id},
    )
    db_connection.execute(
        text("""
            UPDATE campaign.character_resources
            SET current_amount = 0
            WHERE timeline_id = :timeline AND character_id = :character
        """),
        {"timeline": timeline_a_id, "character": character_a_id},
    )

    second = _run(db_connection, user_id=user_id)
    reconciled_lines = [line for line in second.lines if "[reconciled" in line]
    assert len(reconciled_lines) == 3, second.lines
    assert any("character state: Phase13C Character A" in line for line in reconciled_lines), (
        reconciled_lines
    )
    assert any("condition 'poisoned': Phase13C Character A" in line for line in reconciled_lines), (
        reconciled_lines
    )
    assert any(
        "resource 'spell_slot': Phase13C Character A" in line for line in reconciled_lines
    ), reconciled_lines

    view_a = get_character_view(
        db_connection,
        character_id=character_a_id,
        timeline_id=timeline_a_id,
        expected_world_id=world_id,
        include_full=True,
    )
    assert view_a.current_hit_points == 6
    assert view_a.temporary_hit_points == 2
    assert view_a.exhaustion_level == 1
    assert view_a.conditions is not None and view_a.conditions[0].source_description == (
        "Phase 13D portal development fixture"
    )
    assert view_a.resources is not None and view_a.resources[0].current_amount == 2
