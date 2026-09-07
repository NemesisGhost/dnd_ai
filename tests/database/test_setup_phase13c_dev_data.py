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

import pytest
import setup_phase13c_dev_data
from setup_phase13c_dev_data import _run
from sqlalchemy import Connection, text

from dnd_ai.domain.passwords import hash_password
from dnd_ai.queries.bootstrap import CampaignBootstrapView, get_session_bootstrap
from dnd_ai.queries.character import get_character_view
from dnd_ai.queries.quest import (
    QuestNotFoundError,
    get_quest_view,
    list_campaign_quests,
)
from dnd_ai.queries.session import (
    SessionNotFoundError,
    get_session_view,
    list_campaign_sessions,
)
from tests.factories import (
    lookup_id,
    make_campaign,
    make_entity,
    make_event,
    make_session,
    make_timeline,
    make_user,
    make_world,
    make_world_time,
)


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


# ---------------------------------------------------------------------------
# Phase 13D Sessions list/detail fixture
# ---------------------------------------------------------------------------

_SESSION_WT_LABEL_PREFIX = "Phase13D session fixture"
_CAMPAIGN_A = "Phase13C Campaign A"
_CAMPAIGN_B = "Phase13C Campaign B"


def _campaigns(
    db_connection: Connection, *, user_id: uuid.UUID
) -> dict[str, CampaignBootstrapView]:
    view = get_session_bootstrap(db_connection, user_id=user_id)
    return {c.campaign_name: c for c in view.campaigns}


def test_preview_mode_rolls_back_all_new_session_world_time_and_event_rows(
    db_connection: Connection,
) -> None:
    """Item 1: a preview (the identical SQL path, then a rollback) leaves no
    session, world-time, or event row behind. Simulated with a SAVEPOINT so
    the rollback is observable mid-test, the same shape `main()`'s
    transaction rollback has in real preview mode."""
    user_id = _make_local_account(db_connection, display_name="Preview Tester")

    savepoint = db_connection.begin_nested()
    _run(db_connection, user_id=user_id)

    campaigns = _campaigns(db_connection, user_id=user_id)
    assert (
        len(list_campaign_sessions(db_connection, campaign_id=campaigns[_CAMPAIGN_A].campaign_id))
        == 3
    )
    world_times_during = db_connection.execute(
        text("SELECT count(*) FROM core.world_times WHERE label LIKE :p"),
        {"p": f"{_SESSION_WT_LABEL_PREFIX}%"},
    ).scalar()
    assert world_times_during == 11

    savepoint.rollback()

    assert (
        db_connection.execute(
            text("SELECT count(*) FROM core.world_times WHERE label LIKE :p"),
            {"p": f"{_SESSION_WT_LABEL_PREFIX}%"},
        ).scalar()
        == 0
    )
    assert (
        db_connection.execute(
            text("""
                SELECT count(*) FROM campaign.sessions s
                JOIN campaign.campaigns c ON c.campaign_id = s.campaign_id
                WHERE c.name LIKE 'Phase13C Campaign %'
            """)
        ).scalar()
        == 0
    )
    assert (
        db_connection.execute(
            text("""
                SELECT count(*) FROM core.entities
                WHERE canonical_name IN (
                    'Tolek''s Warning Unheeded', 'Lantern Chamber Breached',
                    'Vault Antechamber Mapped', 'Ambush at the Third Vault', 'Beacon Fire Answered'
                )
            """)
        ).scalar()
        == 0
    )


def test_apply_creates_the_expected_campaign_a_and_campaign_b_sessions(
    db_connection: Connection,
) -> None:
    """Items 2, 3, 4: apply mode creates three Campaign A sessions (two
    timestamped/completed, one timestamp-free) and one Campaign B session,
    and the list data supports the portal's newest-first, nulls-last
    ordering."""
    user_id = _make_local_account(db_connection, display_name="Apply Tester")
    _run(db_connection, user_id=user_id)
    campaigns = _campaigns(db_connection, user_id=user_id)

    a_sessions = list_campaign_sessions(
        db_connection, campaign_id=campaigns[_CAMPAIGN_A].campaign_id
    )
    assert [s.session_number for s in a_sessions] == [3, 2, 1]
    by_number = {s.session_number: s for s in a_sessions}

    assert by_number[1].title == "The Sealed Descent"
    assert by_number[2].title == "The Warden's Bargain"
    assert by_number[3].title is None

    assert by_number[1].started_at is not None and by_number[1].ended_at is not None
    assert by_number[2].started_at is not None and by_number[2].ended_at is not None
    assert by_number[2].started_at > by_number[1].started_at
    assert by_number[3].started_at is None and by_number[3].ended_at is None
    assert by_number[3].status_code == "pending"

    b_sessions = list_campaign_sessions(
        db_connection, campaign_id=campaigns[_CAMPAIGN_B].campaign_id
    )
    assert [s.title for s in b_sessions] == ["Smoke Over Hollowmere"]


def test_session_detail_carries_the_recap_and_its_linked_events_in_backend_order(
    db_connection: Connection,
) -> None:
    """Items 5, 6: session detail returns the recap and linked events, and
    the events come back in deliberate world-time chronological order —
    which for Session 1 is the reverse of their alphabetical name order."""
    user_id = _make_local_account(db_connection, display_name="Detail Tester")
    _run(db_connection, user_id=user_id)
    campaigns = _campaigns(db_connection, user_id=user_id)
    campaign_a_id = campaigns[_CAMPAIGN_A].campaign_id

    session_1 = next(
        s
        for s in list_campaign_sessions(db_connection, campaign_id=campaign_a_id)
        if s.session_number == 1
    )
    view = get_session_view(
        db_connection,
        session_id=session_1.session_id,
        campaign_id=campaign_a_id,
        include_draft_events=True,
    )
    assert view.summary is not None and "warden" in view.summary
    assert len(view.events) == 2
    assert all(e.summary is not None and e.details is not None for e in view.events)

    names = [e.name for e in view.events]
    assert names == ["Tolek's Warning Unheeded", "Lantern Chamber Breached"]
    assert names != sorted(names), "chronological order must differ from alphabetical"


def test_the_nullable_session_has_no_title_timestamps_summary_or_events(
    db_connection: Connection,
) -> None:
    """Item 7: Session 3 exercises every empty state at once."""
    user_id = _make_local_account(db_connection, display_name="Nullable Tester")
    _run(db_connection, user_id=user_id)
    campaigns = _campaigns(db_connection, user_id=user_id)
    campaign_a_id = campaigns[_CAMPAIGN_A].campaign_id

    session_3 = next(
        s
        for s in list_campaign_sessions(db_connection, campaign_id=campaign_a_id)
        if s.session_number == 3
    )
    view = get_session_view(
        db_connection,
        session_id=session_3.session_id,
        campaign_id=campaign_a_id,
        include_draft_events=True,
    )
    assert view.title is None
    assert view.started_at is None and view.ended_at is None
    assert view.summary is None
    assert view.start_world_time_id is None and view.end_world_time_id is None
    assert view.events == ()


def test_the_campaign_b_session_belongs_only_to_campaign_b(
    db_connection: Connection,
) -> None:
    """Item 8: the Campaign B session is rejected under Campaign A's id
    (the same non-disclosing `SessionNotFoundError` a nonexistent session
    raises), and resolves normally under Campaign B's id."""
    user_id = _make_local_account(db_connection, display_name="Cross Campaign Tester")
    _run(db_connection, user_id=user_id)
    campaigns = _campaigns(db_connection, user_id=user_id)
    campaign_a_id = campaigns[_CAMPAIGN_A].campaign_id
    campaign_b_id = campaigns[_CAMPAIGN_B].campaign_id

    b_session = list_campaign_sessions(db_connection, campaign_id=campaign_b_id)[0]

    with pytest.raises(SessionNotFoundError):
        get_session_view(
            db_connection,
            session_id=b_session.session_id,
            campaign_id=campaign_a_id,
            include_draft_events=True,
        )

    ok = get_session_view(
        db_connection,
        session_id=b_session.session_id,
        campaign_id=campaign_b_id,
        include_draft_events=True,
    )
    assert ok.title == "Smoke Over Hollowmere"
    assert len(ok.events) == 1


def test_running_apply_twice_creates_no_duplicate_sessions_world_times_or_events(
    db_connection: Connection,
) -> None:
    """Item 9: the session/world-time/event rows are as idempotent as every
    other row this fixture creates."""
    user_id = _make_local_account(db_connection, display_name="Idempotent Sessions Tester")

    first = _run(db_connection, user_id=user_id)
    second = _run(db_connection, user_id=user_id)
    assert all("[created]" in line for line in first.lines), first.lines
    assert all("[reused" in line for line in second.lines), second.lines
    assert len(first.lines) == len(second.lines)

    campaigns = _campaigns(db_connection, user_id=user_id)
    a_id = campaigns[_CAMPAIGN_A].campaign_id
    b_id = campaigns[_CAMPAIGN_B].campaign_id
    assert len(list_campaign_sessions(db_connection, campaign_id=a_id)) == 3
    assert len(list_campaign_sessions(db_connection, campaign_id=b_id)) == 1

    assert (
        db_connection.execute(
            text("SELECT count(*) FROM core.world_times WHERE label LIKE :p"),
            {"p": f"{_SESSION_WT_LABEL_PREFIX}%"},
        ).scalar()
        == 11
    )
    session_ids = [
        s.session_id
        for cid in (a_id, b_id)
        for s in list_campaign_sessions(db_connection, campaign_id=cid)
    ]
    assert (
        db_connection.execute(
            text("SELECT count(*) FROM narrative.events WHERE session_id = ANY(:ids)"),
            {"ids": session_ids},
        ).scalar()
        == 5
    )


def test_rerun_reconciles_session_fields_and_event_ordering_after_drift(
    db_connection: Connection,
) -> None:
    """Item 10: a live-testing session that renamed a session, revised its
    recap, moved its end time, and reactivated a pending session is reset by
    a second apply — each reported as "reconciled" — and the real
    session-detail query then shows the restored values and event order.
    (The linked events and their world times are schema-immutable, so those
    are covered by the idempotency test, not here.)"""
    user_id = _make_local_account(db_connection, display_name="Reconcile Sessions Tester")
    _run(db_connection, user_id=user_id)
    campaigns = _campaigns(db_connection, user_id=user_id)
    campaign_a_id = campaigns[_CAMPAIGN_A].campaign_id

    by_number = {
        s.session_number: s
        for s in list_campaign_sessions(db_connection, campaign_id=campaign_a_id)
    }
    db_connection.execute(
        text("""
            UPDATE campaign.sessions
            SET title = 'Renamed during live testing',
                summary = 'A recap edited during testing.',
                ended_at = ended_at + interval '90 minutes'
            WHERE session_id = :session
        """),
        {"session": by_number[1].session_id},
    )
    db_connection.execute(
        text("""
            UPDATE campaign.sessions
            SET lifecycle_status_id = (
                SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'active'
            )
            WHERE session_id = :session
        """),
        {"session": by_number[3].session_id},
    )

    second = _run(db_connection, user_id=user_id)
    reconciled = [line for line in second.lines if "[reconciled" in line]
    assert any(f"session {_CAMPAIGN_A} #1" in line for line in reconciled), reconciled
    assert any(f"session {_CAMPAIGN_A} #3" in line for line in reconciled), reconciled

    view = get_session_view(
        db_connection,
        session_id=by_number[1].session_id,
        campaign_id=campaign_a_id,
        include_draft_events=True,
    )
    assert view.title == "The Sealed Descent"
    assert view.summary is not None and view.summary.startswith("The party forced")
    assert [e.name for e in view.events] == [
        "Tolek's Warning Unheeded",
        "Lantern Chamber Breached",
    ]

    v3 = get_session_view(
        db_connection,
        session_id=by_number[3].session_id,
        campaign_id=campaign_a_id,
        include_draft_events=True,
    )
    assert v3.status_code == "pending"


def test_unrelated_pre_existing_session_and_event_records_remain_unchanged(
    db_connection: Connection,
) -> None:
    """Item 11: the script only ever touches its own campaigns, so a
    wholly separate campaign's session/world-time/event are untouched
    across two applies."""
    user_id = _make_local_account(db_connection, display_name="Unrelated Guard Tester")

    other_world_id = make_world(db_connection, slug="unrelated-sessions-world")
    other_timeline_id = make_timeline(db_connection, other_world_id, is_primary=True)
    other_campaign_id = make_campaign(
        db_connection, other_timeline_id, lifecycle_status_code="pending"
    )
    other_session_id = make_session(
        db_connection,
        other_campaign_id,
        1,
        title="Not a fixture session",
        summary="Untouched recap.",
    )
    other_world_time_id = make_world_time(db_connection, other_world_id, 500)
    other_event_id = make_event(
        db_connection,
        other_world_id,
        other_timeline_id,
        other_world_time_id,
        campaign_id=other_campaign_id,
        session_id=other_session_id,
        event_status_code="recorded",
        name="Not a fixture event",
    )

    _run(db_connection, user_id=user_id)
    _run(db_connection, user_id=user_id)

    session_row = db_connection.execute(
        text("SELECT title, summary FROM campaign.sessions WHERE session_id = :s"),
        {"s": other_session_id},
    ).one()
    assert session_row.title == "Not a fixture session"
    assert session_row.summary == "Untouched recap."
    assert (
        db_connection.execute(
            text("SELECT sort_key FROM core.world_times WHERE world_time_id = :w"),
            {"w": other_world_time_id},
        ).scalar()
        == 500
    )
    assert (
        db_connection.execute(
            text("SELECT canonical_name FROM core.entities WHERE entity_id = :e"),
            {"e": other_event_id},
        ).scalar()
        == "Not a fixture event"
    )


def test_production_environment_refusal_is_enforced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Item 12: the production guard still refuses, unchanged."""
    monkeypatch.setattr(setup_phase13c_dev_data.settings, "environment", "production")
    with pytest.raises(SystemExit):
        setup_phase13c_dev_data._require_non_production()


# ---------------------------------------------------------------------------
# Phase 13D Quest list/detail fixture
# ---------------------------------------------------------------------------

_QUEST_A_ACTIVE = "Restore the Glass Ossuary"
_QUEST_A_COMPLETED = "Gather the Hollow Verses"
_QUEST_A_NULL_STATUS = "Wake the Tide Beneath Vheil"
_QUEST_B = "Chart the Sunken Marches"
_EXPECTED_A_QUEST_NAMES = {_QUEST_A_ACTIVE, _QUEST_A_COMPLETED, _QUEST_A_NULL_STATUS}


def _quest_context(
    db_connection: Connection, *, user_id: uuid.UUID
) -> tuple[CampaignBootstrapView, CampaignBootstrapView, uuid.UUID, bool]:
    """(campaign_a, campaign_b, world_a_id, account_is_gm) — the inputs the
    portal's quest route resolves before calling the production queries."""
    campaigns = _campaigns(db_connection, user_id=user_id)
    campaign_a = campaigns[_CAMPAIGN_A]
    campaign_b = campaigns[_CAMPAIGN_B]
    assert campaign_a.timeline_id is not None
    world_a = db_connection.execute(
        text("SELECT world_id FROM campaign.timelines WHERE timeline_id = :t"),
        {"t": campaign_a.timeline_id},
    ).scalar()
    assert isinstance(world_a, uuid.UUID)
    return campaign_a, campaign_b, world_a, "canon.edit" in campaign_a.capabilities


def _list_a(db_connection: Connection, campaign_a: CampaignBootstrapView, *, is_gm: bool) -> list:
    assert campaign_a.timeline_id is not None
    return list(
        list_campaign_quests(
            db_connection,
            timeline_id=campaign_a.timeline_id,
            party_id=None,
            include_all_parties=is_gm,
        )
    )


def test_preview_mode_rolls_back_all_new_quest_rows(db_connection: Connection) -> None:
    """Item 1: a preview (the identical SQL path, then a rollback) leaves no
    quest, stage, objective, party, or quest/objective-state row behind."""
    user_id = _make_local_account(db_connection, display_name="Quest Preview Tester")

    savepoint = db_connection.begin_nested()
    _run(db_connection, user_id=user_id)

    campaign_a, campaign_b, world_a, is_gm = _quest_context(db_connection, user_id=user_id)
    assert {
        i.name for i in _list_a(db_connection, campaign_a, is_gm=is_gm)
    } == _EXPECTED_A_QUEST_NAMES
    assert (
        db_connection.execute(
            text(
                "SELECT count(*) FROM narrative.quest_objectives qo "
                "JOIN narrative.quest_stages qs ON qs.quest_stage_id = qo.quest_stage_id "
                "JOIN core.entities e ON e.entity_id = qs.quest_id "
                "WHERE e.world_id = :w"
            ),
            {"w": world_a},
        ).scalar()
        == 7
    )

    savepoint.rollback()

    for name in (*_EXPECTED_A_QUEST_NAMES, _QUEST_B):
        assert (
            db_connection.execute(
                text("SELECT count(*) FROM core.entities WHERE canonical_name = :n"),
                {"n": name},
            ).scalar()
            == 0
        ), name
    assert (
        db_connection.execute(
            text("SELECT count(*) FROM campaign.parties WHERE name = 'The Ashen Vigil'")
        ).scalar()
        == 0
    )


def test_apply_creates_the_expected_quests_stages_and_objectives(
    db_connection: Connection,
) -> None:
    """Item 2: apply mode creates three Campaign A quests (active, completed,
    null-status), the detailed quest's three ordered stages, and its six
    objectives with the documented lookup codes."""
    user_id = _make_local_account(db_connection, display_name="Quest Apply Tester")
    _run(db_connection, user_id=user_id)

    campaign_a, campaign_b, world_a, is_gm = _quest_context(db_connection, user_id=user_id)
    items = {i.name: i for i in _list_a(db_connection, campaign_a, is_gm=is_gm)}
    assert set(items) == _EXPECTED_A_QUEST_NAMES
    assert items[_QUEST_A_ACTIVE].status_code == "active"
    assert items[_QUEST_A_COMPLETED].status_code == "completed"
    assert items[_QUEST_A_NULL_STATUS].status_code is None

    assert campaign_a.timeline_id is not None
    detail = get_quest_view(
        db_connection,
        quest_id=items[_QUEST_A_ACTIVE].quest_id,
        timeline_id=campaign_a.timeline_id,
        expected_world_id=world_a,
        party_id=None,
        include_hidden=True,
    )
    assert [s.name for s in detail.stages] == [
        "The Warden's Vigil",
        "Reassemble the Reliquary",
        "Aftermath in the Nave",
    ]
    assert [s.stage_type for s in detail.stages] == ["sequential", "sequential", "optional"]
    assert detail.stages[2].objectives == ()

    objectives = {o.name: o for s in detail.stages for o in s.objectives}
    assert len(objectives) == 6
    lanterns = objectives["Light the three vigil lanterns"]
    assert lanterns.requirement_level == "required"
    assert lanterns.completion_mode == "automatic"
    assert lanterns.quantity_required == 3
    assert lanterns.description is not None
    assert lanterns.status_code == "completed"

    challenge = objectives["Answer the warden's challenge"]
    assert challenge.completion_mode == "gm_confirmed"
    assert challenge.description is None
    assert challenge.quantity_required is None
    assert challenge.status_code == "active"

    assert objectives["Recover the sexton's iron key"].requirement_level == "optional"
    assert objectives["Recover the sexton's iron key"].status_code is None
    assert (
        objectives["Catalogue the recovered relics"].visibility_policy == "hidden_until_discovered"
    )
    assert objectives["Brief Archivist Vell in private"].visibility_policy == "gm_only"

    empty = get_quest_view(
        db_connection,
        quest_id=items[_QUEST_A_COMPLETED].quest_id,
        timeline_id=campaign_a.timeline_id,
        expected_world_id=world_a,
        party_id=None,
        include_hidden=True,
    )
    assert empty.stages == ()
    assert empty.status_code == "completed"


def test_running_apply_twice_creates_no_duplicate_quest_rows(db_connection: Connection) -> None:
    """Item 3: quest/stage/objective/state rows are as idempotent as every
    other row this fixture creates."""
    user_id = _make_local_account(db_connection, display_name="Quest Idempotent Tester")

    first = _run(db_connection, user_id=user_id)
    second = _run(db_connection, user_id=user_id)
    assert all("[created]" in line for line in first.lines), first.lines
    assert all("[reused" in line for line in second.lines), second.lines
    assert len(first.lines) == len(second.lines)

    campaign_a, campaign_b, world_a, is_gm = _quest_context(db_connection, user_id=user_id)
    assert len(_list_a(db_connection, campaign_a, is_gm=is_gm)) == 3
    assert (
        db_connection.execute(
            text(
                "SELECT count(*) FROM narrative.quest_stages qs "
                "JOIN core.entities e ON e.entity_id = qs.quest_id WHERE e.world_id = :w"
            ),
            {"w": world_a},
        ).scalar()
        == 4
    )
    assert (
        db_connection.execute(
            text("SELECT count(*) FROM campaign.parties WHERE name = 'The Ashen Vigil'")
        ).scalar()
        == 1
    )


def test_rerun_reconciles_mutable_quest_rows_after_drift(db_connection: Connection) -> None:
    """Item 4: a live-testing session that advanced an objective, re-statused
    a quest, and renumbered a stage is reset by a second apply — each
    reported as "reconciled" — and the real queries then show the restored
    values."""
    user_id = _make_local_account(db_connection, display_name="Quest Reconcile Tester")
    _run(db_connection, user_id=user_id)
    campaign_a, campaign_b, world_a, is_gm = _quest_context(db_connection, user_id=user_id)
    assert campaign_a.timeline_id is not None
    glass_id = {i.name: i.quest_id for i in _list_a(db_connection, campaign_a, is_gm=is_gm)}[
        _QUEST_A_ACTIVE
    ]

    db_connection.execute(
        text("""
            UPDATE campaign.quest_state
            SET quest_status_id = (
                SELECT quest_status_id FROM campaign.quest_statuses WHERE code = 'completed'
            )
            WHERE quest_id = :q AND party_id IS NULL
        """),
        {"q": glass_id},
    )
    db_connection.execute(
        text("""
            UPDATE campaign.objective_state os
            SET objective_status_id = (
                SELECT objective_status_id FROM campaign.objective_statuses WHERE code = 'failed'
            )
            FROM narrative.quest_objectives qo
            JOIN narrative.quest_stages qs ON qs.quest_stage_id = qo.quest_stage_id
            WHERE os.quest_objective_id = qo.quest_objective_id
              AND qs.quest_id = :q AND qo.name = 'Light the three vigil lanterns'
        """),
        {"q": glass_id},
    )
    db_connection.execute(
        text("""
            UPDATE narrative.quest_stages SET sequence_number = 99, stage_type = 'optional'
            WHERE quest_id = :q AND name = 'The Warden''s Vigil'
        """),
        {"q": glass_id},
    )

    second = _run(db_connection, user_id=user_id)
    reconciled = [line for line in second.lines if "[reconciled" in line]
    assert any(f"quest state {_QUEST_A_ACTIVE!r} (campaign-wide)" in line for line in reconciled), (
        reconciled
    )
    assert any("Light the three vigil lanterns" in line for line in reconciled), reconciled
    assert any("The Warden's Vigil" in line for line in reconciled), reconciled

    detail = get_quest_view(
        db_connection,
        quest_id=glass_id,
        timeline_id=campaign_a.timeline_id,
        expected_world_id=world_a,
        party_id=None,
        include_hidden=True,
    )
    assert detail.status_code == "active"
    assert [s.name for s in detail.stages][0] == "The Warden's Vigil"
    assert detail.stages[0].stage_type == "sequential"
    lanterns = next(
        o for s in detail.stages for o in s.objectives if o.name == "Light the three vigil lanterns"
    )
    assert lanterns.status_code == "completed"


def test_a_name_collision_with_non_fixture_data_fails_safely(db_connection: Connection) -> None:
    """Item 5: a second entity taking a fixture quest's name is treated as a
    collision — the re-run aborts with guidance rather than guessing which
    row is the fixture's."""
    user_id = _make_local_account(db_connection, display_name="Quest Collision Tester")
    _run(db_connection, user_id=user_id)

    world_a = db_connection.execute(
        text("SELECT world_id FROM core.entities WHERE canonical_name = :n"),
        {"n": _QUEST_A_ACTIVE},
    ).scalar()
    assert isinstance(world_a, uuid.UUID)
    continent_type_id = lookup_id(
        db_connection, "core", "entity_types", "entity_type_id", "continent"
    )
    make_entity(db_connection, world_a, continent_type_id, name=_QUEST_A_ACTIVE)

    with pytest.raises(SystemExit, match="collision"):
        _run(db_connection, user_id=user_id)


def test_campaign_a_and_b_quests_remain_isolated(db_connection: Connection) -> None:
    """Item 6: Campaign B's quest is tracked only on Timeline B and never
    appears in Campaign A's list, and vice versa."""
    user_id = _make_local_account(db_connection, display_name="Quest Isolation Tester")
    _run(db_connection, user_id=user_id)
    campaign_a, campaign_b, world_a, is_gm = _quest_context(db_connection, user_id=user_id)
    assert campaign_b.timeline_id is not None

    a_names = {i.name for i in _list_a(db_connection, campaign_a, is_gm=is_gm)}
    b_names = {
        i.name
        for i in list_campaign_quests(
            db_connection,
            timeline_id=campaign_b.timeline_id,
            party_id=None,
            include_all_parties=is_gm,
        )
    }
    assert a_names == _EXPECTED_A_QUEST_NAMES
    assert b_names == {_QUEST_B}
    assert not (a_names & b_names)


def test_production_list_query_returns_the_expected_campaign_a_quests(
    db_connection: Connection,
) -> None:
    """Item 7: the real `list_campaign_quests` returns exactly the three
    Campaign A fixture quests, ordered by canonical_name (the production
    contract), with the documented statuses."""
    user_id = _make_local_account(db_connection, display_name="Quest List Query Tester")
    _run(db_connection, user_id=user_id)
    campaign_a, campaign_b, world_a, is_gm = _quest_context(db_connection, user_id=user_id)

    items = _list_a(db_connection, campaign_a, is_gm=is_gm)
    assert [i.name for i in items] == sorted(i.name for i in items)
    assert [(i.name, i.status_code) for i in items] == [
        (_QUEST_A_COMPLETED, "completed"),
        (_QUEST_A_ACTIVE, "active"),
        (_QUEST_A_NULL_STATUS, None),
    ]


def test_production_detail_query_preserves_stage_sequence_order(db_connection: Connection) -> None:
    """Item 8: `get_quest_view` returns "Restore the Glass Ossuary"'s stages
    in sequence order, which is deliberately the reverse of alphabetical."""
    user_id = _make_local_account(db_connection, display_name="Quest Detail Query Tester")
    _run(db_connection, user_id=user_id)
    campaign_a, campaign_b, world_a, is_gm = _quest_context(db_connection, user_id=user_id)
    assert campaign_a.timeline_id is not None
    glass_id = {i.name: i.quest_id for i in _list_a(db_connection, campaign_a, is_gm=is_gm)}[
        _QUEST_A_ACTIVE
    ]

    detail = get_quest_view(
        db_connection,
        quest_id=glass_id,
        timeline_id=campaign_a.timeline_id,
        expected_world_id=world_a,
        party_id=None,
        include_hidden=True,
    )
    names = [s.name for s in detail.stages]
    seqs = [s.sequence_number for s in detail.stages]
    assert seqs == sorted(seqs)
    assert names == ["The Warden's Vigil", "Reassemble the Reliquary", "Aftermath in the Nave"]
    assert names != sorted(names), "sequence order must differ from alphabetical"


def test_production_visibility_filtering_is_preserved(db_connection: Connection) -> None:
    """Item 9: `get_quest_view` still filters objectives by
    `visibility_policy` — a non-GM audience (`include_hidden=False`) sees
    only the four `visible` objectives; the `gm_only` and stateless
    `hidden_until_discovered` objectives are returned only with
    `include_hidden=True`."""
    user_id = _make_local_account(db_connection, display_name="Quest Visibility Tester")
    _run(db_connection, user_id=user_id)
    campaign_a, campaign_b, world_a, is_gm = _quest_context(db_connection, user_id=user_id)
    assert campaign_a.timeline_id is not None
    glass_id = {i.name: i.quest_id for i in _list_a(db_connection, campaign_a, is_gm=is_gm)}[
        _QUEST_A_ACTIVE
    ]

    def _objective_names(*, include_hidden: bool) -> set[str]:
        view = get_quest_view(
            db_connection,
            quest_id=glass_id,
            timeline_id=campaign_a.timeline_id,  # type: ignore[arg-type]
            expected_world_id=world_a,
            party_id=None,
            include_hidden=include_hidden,
        )
        return {o.name for s in view.stages for o in s.objectives}

    non_gm = _objective_names(include_hidden=False)
    gm = _objective_names(include_hidden=True)
    assert non_gm == {
        "Light the three vigil lanterns",
        "Answer the warden's challenge",
        "Recover the sexton's iron key",
        "Set the ossuary keystone",
    }
    assert gm - non_gm == {"Catalogue the recovered relics", "Brief Archivist Vell in private"}


def test_the_campaign_b_quest_is_not_disclosed_through_campaign_a_list(
    db_connection: Connection,
) -> None:
    """Item 10: the quest LIST endpoint is timeline-scoped, so Campaign B's
    quest never appears in Campaign A's list — the disclosure path the
    portal actually uses (it only ever has quest ids the list gave it).

    The DETAIL query (`get_quest_view`) currently gates only on world, and
    both fixture campaigns share one world, so requesting Campaign B's quest
    id under Campaign A's timeline returns the quest definition rather than
    the `QuestNotFoundError` a nonexistent id raises. That is asserted here
    as the *documented current behavior*, not endorsed — see the script
    module docstring and the completion report: full parity would need a
    second world for Campaign B (unreconcilable onto an existing dev
    database) or a quest-API change (out of scope)."""
    user_id = _make_local_account(db_connection, display_name="Quest Cross Campaign Tester")
    _run(db_connection, user_id=user_id)
    campaign_a, campaign_b, world_a, is_gm = _quest_context(db_connection, user_id=user_id)
    assert campaign_a.timeline_id is not None and campaign_b.timeline_id is not None

    b_quest_id = list_campaign_quests(
        db_connection,
        timeline_id=campaign_b.timeline_id,
        party_id=None,
        include_all_parties=is_gm,
    )[0].quest_id

    a_list = _list_a(db_connection, campaign_a, is_gm=is_gm)
    assert b_quest_id not in {i.quest_id for i in a_list}

    # Baseline: a truly nonexistent id is non-disclosing.
    with pytest.raises(QuestNotFoundError):
        get_quest_view(
            db_connection,
            quest_id=uuid.uuid4(),
            timeline_id=campaign_a.timeline_id,
            expected_world_id=world_a,
            party_id=None,
            include_hidden=True,
        )

    # Documented current behavior: the same-world detail query still returns it.
    cross = get_quest_view(
        db_connection,
        quest_id=b_quest_id,
        timeline_id=campaign_a.timeline_id,
        expected_world_id=world_a,
        party_id=None,
        include_hidden=True,
    )
    assert cross.name == _QUEST_B
    assert cross.status_code is None  # no quest_state on Campaign A's timeline
