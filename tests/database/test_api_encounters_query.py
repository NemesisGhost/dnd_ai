"""Tests for `dnd_ai.api.encounters`'s read endpoint — Phase 10 workstream
17's query over `dnd_ai.queries.encounter.get_encounter_view` (docs/
PLAN.md Phase 10 "query services for the effective dungeon, character,
quest, relationship, inventory, encounter, and knowledge state required by
the vertical slice"). Mirrors `tests/database/test_api_dungeon.py`'s
shape: `get_authenticated_user_id` is overridden directly, since these
tests exercise campaign-capability enforcement and cross-campaign
ownership, not OIDC token verification.

Covers: access control (non-member 404, capless-member 403), cross-campaign
rejection (`narrative.encounters.campaign_id` is a direct column, unlike the
world-scoped domains every earlier query workstream checked), and the
audience projection (ADR 0016, defect DEF-009 / ENC-01): a `canon.edit`
holder reads the full record, while any other member gets only started
encounters, no GM_ONLY `summary`/turn `notes`, only the participants, turns
and location/event/item references the World Explorer's discoverability rule
admits, and dense per-round `turn_order`. Earlier versions of this module
asserted that a `campaign.view`-only caller saw turn notes; that contract was
wrong (notes are GM_ONLY) and is replaced here.
"""

import uuid
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, text

from dnd_ai.api.app import create_app
from dnd_ai.api.auth import get_authenticated_user_id
from dnd_ai.api.deps import get_engine
from tests.factories import (
    lookup_id,
    make_action,
    make_campaign,
    make_campaign_membership,
    make_character,
    make_combat_action,
    make_encounter,
    make_encounter_participant,
    make_encounter_round,
    make_encounter_turn,
    make_event,
    make_interaction,
    make_item_definition,
    make_item_instance,
    make_location,
    make_membership_role,
    make_resource_grant,
    make_role,
    make_role_capability,
    make_ruleset_version_for_world,
    make_timeline,
    make_user,
    make_world,
    make_world_time,
    oidc_principal,
)

pytestmark = pytest.mark.database

SUMMARY_MARKER = "GM-ENC-SUMMARY-ONLY"
NOTE_A = "GM-ENC-NOTE-ONLY-A"
NOTE_B = "GM-ENC-NOTE-ONLY-B"
NOTE_C = "GM-ENC-NOTE-ONLY-C"
NOTE_R2 = "GM-ENC-NOTE-ONLY-R2"


class Fixture:
    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        self.world_time_id = make_world_time(connection, self.world_id, 100)
        self.campaign_id = make_campaign(
            connection, self.timeline_id, lifecycle_status_code="pending"
        )
        self.other_campaign_id = make_campaign(
            connection, self.timeline_id, "Other Campaign", lifecycle_status_code="pending"
        )

        self.character_a_id = make_character(connection, self.world_id, name="Aria")
        self.character_b_id = make_character(connection, self.world_id, name="Goblin")
        self.character_c_id = make_character(connection, self.world_id, name="Hooded Stranger")

        item_definition_id = make_item_definition(
            connection, make_ruleset_version_for_world(connection, self.world_id)
        )
        self.item_shown_id = make_item_instance(
            connection, self.world_id, item_definition_id, name="Aria's Blade"
        )
        self.item_hidden_id = make_item_instance(
            connection, self.world_id, item_definition_id, name="Stranger's Dagger"
        )
        self.location_shown_id = make_location(connection, self.world_id, name="Old Bridge")
        self.location_hidden_id = make_location(connection, self.world_id, name="Smugglers' Cellar")

        self.encounter_id = make_encounter(
            connection,
            self.timeline_id,
            self.world_time_id,
            campaign_id=self.campaign_id,
            location_id=self.location_shown_id,
            status="active",
            current_round=2,
            summary=SUMMARY_MARKER,
        )
        self.participant_a_id = make_encounter_participant(
            connection, self.encounter_id, self.character_a_id, side="party", initiative=15
        )
        self.participant_b_id = make_encounter_participant(
            connection,
            self.encounter_id,
            self.character_b_id,
            side="enemy",
            initiative=10,
            outcome="defeated",
        )
        self.participant_c_id = make_encounter_participant(
            connection,
            self.encounter_id,
            self.character_c_id,
            side="enemy",
            initiative=5,
            outcome="escaped",
        )
        round_1_id = make_encounter_round(connection, self.encounter_id, 1)
        round_2_id = make_encounter_round(connection, self.encounter_id, 2)

        interaction_id = make_interaction(connection, self.timeline_id, self.world_time_id)
        action_a_id = make_action(connection, interaction_id, self.character_a_id)
        combat_action_a_id = make_combat_action(
            connection,
            action_a_id,
            action_kind="attack",
            item_instance_id=self.item_shown_id,
            hit=True,
            damage_amount=8,
        )
        action_c_id = make_action(
            connection, interaction_id, self.character_c_id, sequence_number=1
        )
        combat_action_c_id = make_combat_action(
            connection,
            action_c_id,
            action_kind="attack",
            item_instance_id=self.item_hidden_id,
            hit=False,
            damage_amount=0,
        )
        # Round 1: A(0), C(1), B(2). Round 2: C(0), A(1).
        self.turn_id = make_encounter_turn(
            connection,
            round_1_id,
            self.participant_a_id,
            0,
            combat_action_id=combat_action_a_id,
            notes=NOTE_A,
        )
        self.turn_c1_id = make_encounter_turn(
            connection,
            round_1_id,
            self.participant_c_id,
            1,
            combat_action_id=combat_action_c_id,
            notes=NOTE_C,
        )
        self.turn_b_id = make_encounter_turn(
            connection, round_1_id, self.participant_b_id, 2, notes=NOTE_B
        )
        self.turn_c2_id = make_encounter_turn(
            connection, round_2_id, self.participant_c_id, 0, notes=NOTE_R2
        )
        self.turn_a2_id = make_encounter_turn(connection, round_2_id, self.participant_a_id, 1)

        # An encounter belonging only to the *other* campaign on the same
        # timeline — proves campaign_id is checked specifically, not just
        # timeline/world agreement.
        self.foreign_encounter_id = make_encounter(
            connection, self.timeline_id, self.world_time_id, campaign_id=self.other_campaign_id
        )

        view_capability_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "campaign.view"
        )

        self.player_user_id = make_user(connection, "Encounter Query Player")
        player_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.player_user_id
        )
        player_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"player_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, player_role_id, view_capability_id)
        make_membership_role(connection, player_membership_id, player_role_id)

        # A GM: campaign.view plus canon.edit, the editor test for GM_ONLY fields.
        self.editor_user_id = make_user(connection, "Encounter Query Editor")
        editor_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.editor_user_id
        )
        editor_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"gm_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, editor_role_id, view_capability_id)
        make_role_capability(
            connection,
            editor_role_id,
            lookup_id(connection, "security", "capabilities", "capability_id", "canon.edit"),
        )
        make_membership_role(connection, editor_membership_id, editor_role_id)

        # A member whose role carries the baseline character discover tier.
        self.view_capability_id = view_capability_id
        self.discoverer_user_id = make_user(connection, "Encounter Query Discoverer")
        self.discoverer_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.discoverer_user_id
        )
        discoverer_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"seer_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, discoverer_role_id, view_capability_id)
        make_role_capability(
            connection,
            discoverer_role_id,
            lookup_id(
                connection, "security", "capabilities", "capability_id", "character.discover"
            ),
        )
        make_membership_role(connection, self.discoverer_membership_id, discoverer_role_id)

        # A member with no role/capability at all — proves ForbiddenError,
        # distinct from a non-member's NotFoundError.
        self.capless_user_id = make_user(connection, "Encounter Query Capless Member")
        make_campaign_membership(connection, self.campaign_id, self.capless_user_id)

        # Never given a membership at all.
        self.outsider_user_id = make_user(connection, "Encounter Query Outsider")


@pytest.fixture
def f(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as connection:
        fixture = Fixture(connection, f"encounter-query-{uuid.uuid4().hex[:8]}")
    yield fixture
    with postgres_engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        # See tests/database/test_api_dungeon.py's identical cleanup
        # comment for why session_replication_role = replica and explicit,
        # dependency-ordered deletes are used here.
        cleanup.execute(
            text("""
                DELETE FROM security.membership_roles WHERE role_id IN (
                    SELECT role_id FROM security.roles WHERE campaign_id IN (
                        SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t
                    )
                )
            """),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM security.role_capabilities WHERE role_id IN (
                    SELECT role_id FROM security.roles WHERE campaign_id IN (
                        SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t
                    )
                )
            """),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text(
                "DELETE FROM security.roles WHERE campaign_id IN "
                "(SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t)"
            ),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text(
                "DELETE FROM security.campaign_memberships WHERE campaign_id IN "
                "(SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t)"
            ),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text("DELETE FROM campaign.campaigns WHERE timeline_id = :t"),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text("DELETE FROM campaign.timelines WHERE world_id = :w"), {"w": fixture.world_id}
        )
        cleanup.execute(
            text("DELETE FROM core.entities WHERE world_id = :w"), {"w": fixture.world_id}
        )
        cleanup.execute(
            text("DELETE FROM core.worlds WHERE world_id = :w"), {"w": fixture.world_id}
        )
        cleanup.execute(
            text("DELETE FROM security.users WHERE user_id = ANY(:users)"),
            {
                "users": [
                    fixture.player_user_id,
                    fixture.capless_user_id,
                    fixture.outsider_user_id,
                    fixture.editor_user_id,
                    fixture.discoverer_user_id,
                ]
            },
        )


@pytest.fixture
def client_factory(postgres_engine: Engine) -> Callable[[uuid.UUID], TestClient]:
    def _make(user_id: uuid.UUID) -> TestClient:
        app = create_app()
        app.dependency_overrides[get_engine] = lambda: postgres_engine
        app.dependency_overrides[get_authenticated_user_id] = lambda: oidc_principal(user_id)
        return TestClient(app, raise_server_exceptions=False)

    return _make


def _encounter_url(
    f: Fixture, campaign_id: uuid.UUID | None = None, encounter_id: uuid.UUID | None = None
) -> str:
    return f"/campaigns/{campaign_id or f.campaign_id}/encounters/{encounter_id or f.encounter_id}"


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


def test_a_non_member_gets_not_found(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.outsider_user_id) as client:
        response = client.get(_encounter_url(f))
    assert response.status_code == 404


def test_a_member_without_campaign_view_gets_forbidden(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.capless_user_id) as client:
        response = client.get(_encounter_url(f))
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Editor: the unfiltered record
# ---------------------------------------------------------------------------


def _get(
    client_factory: Callable[[uuid.UUID], TestClient],
    user_id: uuid.UUID,
    f: Fixture,
    encounter_id: uuid.UUID | None = None,
    campaign_id: uuid.UUID | None = None,
) -> Any:
    with client_factory(user_id) as client:
        return client.get(_encounter_url(f, campaign_id, encounter_id))


def _turn_orders(body: dict[str, Any]) -> list[list[tuple[str, int]]]:
    return [[(t["encounter_turn_id"], t["turn_order"]) for t in r["turns"]] for r in body["rounds"]]


def test_an_editor_sees_the_full_unfiltered_record(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    response = _get(client_factory, f.editor_user_id, f)
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["status"] == "active"
    assert body["current_round"] == 2
    assert body["summary"] == SUMMARY_MARKER
    assert body["location_id"] == str(f.location_shown_id)
    assert body["resulting_event_id"] is None
    assert body["participants"] == sorted(
        [
            {
                "encounter_participant_id": str(f.participant_a_id),
                "participant_entity_id": str(f.character_a_id),
                "side": "party",
                "initiative": 15,
                "outcome": None,
            },
            {
                "encounter_participant_id": str(f.participant_b_id),
                "participant_entity_id": str(f.character_b_id),
                "side": "enemy",
                "initiative": 10,
                "outcome": "defeated",
            },
            {
                "encounter_participant_id": str(f.participant_c_id),
                "participant_entity_id": str(f.character_c_id),
                "side": "enemy",
                "initiative": 5,
                "outcome": "escaped",
            },
        ],
        key=lambda p: p["encounter_participant_id"],
    )

    # Raw ordering and values, including the GM-only notes and every item id.
    assert _turn_orders(body) == [
        [(str(f.turn_id), 0), (str(f.turn_c1_id), 1), (str(f.turn_b_id), 2)],
        [(str(f.turn_c2_id), 0), (str(f.turn_a2_id), 1)],
    ]
    round_1, round_2 = body["rounds"]
    assert [t["notes"] for t in round_1["turns"]] == [NOTE_A, NOTE_C, NOTE_B]
    assert [t["notes"] for t in round_2["turns"]] == [NOTE_R2, None]
    assert round_1["turns"][0]["combat_action"] == {
        "action_kind": "attack",
        "item_instance_id": str(f.item_shown_id),
        "spell_id": None,
        "hit": True,
        "damage_amount": 8,
        "damage_type_code": None,
        "resulting_condition_code": None,
    }
    assert round_1["turns"][1]["combat_action"]["item_instance_id"] == str(f.item_hidden_id)
    assert round_1["turns"][2]["combat_action"] is None


def test_an_editor_reads_every_status(
    client_factory: Callable[[uuid.UUID], TestClient],
    postgres_engine: Engine,
    f: Fixture,
) -> None:
    for status in ("pending", "aborted"):
        encounter_id = _encounter(postgres_engine, f, status=status, actors=(f.character_a_id,))
        response = _get(client_factory, f.editor_user_id, f, encounter_id)
        assert response.status_code == 200, (status, response.text)
        assert response.json()["status"] == status


# ---------------------------------------------------------------------------
# Member projection
# ---------------------------------------------------------------------------


def test_a_discovering_member_sees_participants_and_turns_but_no_gm_only_prose(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    response = _get(client_factory, f.discoverer_user_id, f)
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["summary"] is None
    assert body["status"] == "active" and body["current_round"] == 2
    assert body["location_id"] == str(f.location_shown_id)
    assert {p["participant_entity_id"] for p in body["participants"]} == {
        str(f.character_a_id),
        str(f.character_b_id),
        str(f.character_c_id),
    }
    defeated = next(
        p for p in body["participants"] if p["participant_entity_id"] == str(f.character_b_id)
    )
    assert (defeated["outcome"], defeated["side"], defeated["initiative"]) == (
        "defeated",
        "enemy",
        10,
    )

    assert all(t["notes"] is None for r in body["rounds"] for t in r["turns"])
    assert _turn_orders(body) == [
        [(str(f.turn_id), 0), (str(f.turn_c1_id), 1), (str(f.turn_b_id), 2)],
        [(str(f.turn_c2_id), 0), (str(f.turn_a2_id), 1)],
    ]
    first = body["rounds"][0]["turns"][0]["combat_action"]
    assert (first["action_kind"], first["hit"], first["damage_amount"]) == ("attack", True, 8)
    assert first["item_instance_id"] == str(f.item_shown_id)
    for marker in (SUMMARY_MARKER, NOTE_A, NOTE_B, NOTE_C, NOTE_R2):
        assert marker not in response.text


def test_a_member_without_a_discover_tier_sees_no_participants_or_turns(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    response = _get(client_factory, f.player_user_id, f)
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["status"] == "active" and body["current_round"] == 2
    assert body["summary"] is None
    assert body["participants"] == []
    assert [r["round_number"] for r in body["rounds"]] == [1, 2]
    assert all(r["turns"] == [] for r in body["rounds"])
    _assert_absent(
        response.text,
        f.character_a_id,
        f.character_b_id,
        f.character_c_id,
        f.participant_a_id,
        f.participant_b_id,
        f.participant_c_id,
        f.turn_id,
        f.turn_c1_id,
        f.turn_b_id,
        f.turn_c2_id,
        f.turn_a2_id,
        f.item_shown_id,
        f.item_hidden_id,
        SUMMARY_MARKER,
        NOTE_A,
        NOTE_B,
        NOTE_C,
        NOTE_R2,
    )


def _assert_absent(text_body: str, *hidden: object) -> None:
    for value in hidden:
        assert str(value) not in text_body, f"{value} leaked into the response body"


def _deny(engine: Engine, f: Fixture, entity_id: uuid.UUID) -> None:
    with engine.begin() as connection:
        make_resource_grant(
            connection,
            f.campaign_id,
            f.view_capability_id,
            timeline_id=f.timeline_id,
            grantee_campaign_membership_id=f.discoverer_membership_id,
            entity_id=entity_id,
            effect="deny",
        )


def test_an_explicitly_denied_participant_is_removed_with_its_turns_and_ranks_stay_dense(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, f: Fixture
) -> None:
    _deny(postgres_engine, f, f.character_c_id)

    response = _get(client_factory, f.discoverer_user_id, f)
    assert response.status_code == 200, response.text
    body = response.json()

    assert {p["participant_entity_id"] for p in body["participants"]} == {
        str(f.character_a_id),
        str(f.character_b_id),
    }
    # C's turns vanish; B (raw order 2) closes the gap, and round 2 restarts at 0.
    assert _turn_orders(body) == [
        [(str(f.turn_id), 0), (str(f.turn_b_id), 1)],
        [(str(f.turn_a2_id), 0)],
    ]
    # The hidden participant's turn carried the other item; it leaves with the turn.
    _assert_absent(
        response.text,
        f.character_c_id,
        f.participant_c_id,
        f.turn_c1_id,
        f.turn_c2_id,
        f.item_hidden_id,
        SUMMARY_MARKER,
        NOTE_A,
        NOTE_B,
        NOTE_C,
        NOTE_R2,
    )
    assert "escaped" not in response.text and '"initiative":5' not in response.text.replace(" ", "")

    # The editor, with no deny, still reads all of it.
    editor = _get(client_factory, f.editor_user_id, f).json()
    assert len(editor["participants"]) == 3


# ---------------------------------------------------------------------------
# Ad-hoc encounters
# ---------------------------------------------------------------------------


def _encounter(
    engine: Engine,
    f: Fixture,
    *,
    status: str = "active",
    actors: tuple[uuid.UUID, ...] = (),
    resulting_event_id: uuid.UUID | None = None,
    location_id: uuid.UUID | None = None,
    item_instance_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """A committed encounter in the fixture's campaign, one participant per actor and (when
    `item_instance_id` is given) a turn for the first actor whose action names that item."""
    with engine.begin() as connection:
        encounter_id = make_encounter(
            connection,
            f.timeline_id,
            f.world_time_id,
            campaign_id=f.campaign_id,
            location_id=location_id,
            status=status,
            current_round=1 if status != "pending" else 0,
            summary=SUMMARY_MARKER,
            resulting_event_id=resulting_event_id,
        )
        participants = [
            make_encounter_participant(connection, encounter_id, actor) for actor in actors
        ]
        if item_instance_id is not None:
            round_id = make_encounter_round(connection, encounter_id, 1)
            interaction_id = make_interaction(connection, f.timeline_id, f.world_time_id)
            action_id = make_action(connection, interaction_id, actors[0])
            combat_action_id = make_combat_action(
                connection, action_id, item_instance_id=item_instance_id, hit=True
            )
            make_encounter_turn(
                connection, round_id, participants[0], 0, combat_action_id=combat_action_id
            )
    return encounter_id


def _npc(engine: Engine, f: Fixture, name: str, *, canon: str, lifecycle: str) -> uuid.UUID:
    with engine.begin() as connection:
        npc = make_character(connection, f.world_id, name=name, entity_type_code="npc")
        connection.execute(text("INSERT INTO character.npcs (npc_id) VALUES (:i)"), {"i": npc})
        connection.execute(
            text("""
                UPDATE core.entities
                SET canon_status_id = (SELECT canon_status_id FROM core.canon_statuses
                                       WHERE code = :canon),
                    lifecycle_status_id = (SELECT lifecycle_status_id FROM core.lifecycle_statuses
                                           WHERE code = :lifecycle)
                WHERE entity_id = :i
            """),
            {"canon": canon, "lifecycle": lifecycle, "i": npc},
        )
    return npc


def test_a_draft_actor_is_hidden_from_a_member_but_an_archived_one_stays_visible(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, f: Fixture
) -> None:
    draft = _npc(postgres_engine, f, "Unpublished Villain", canon="draft", lifecycle="active")
    archived = _npc(postgres_engine, f, "Retired Guard", canon="canon", lifecycle="archived")
    encounter_id = _encounter(
        postgres_engine, f, actors=(f.character_a_id, draft, archived), status="completed"
    )

    member = _get(client_factory, f.discoverer_user_id, f, encounter_id)
    assert member.status_code == 200, member.text
    assert {p["participant_entity_id"] for p in member.json()["participants"]} == {
        str(f.character_a_id),
        str(archived),
    }
    _assert_absent(member.text, draft)

    editor = _get(client_factory, f.editor_user_id, f, encounter_id).json()
    assert {p["participant_entity_id"] for p in editor["participants"]} == {
        str(f.character_a_id),
        str(draft),
        str(archived),
    }


def test_status_decides_what_a_member_may_read(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, f: Fixture
) -> None:
    with postgres_engine.begin() as connection:
        abort_event = make_event(
            connection, f.world_id, f.timeline_id, f.world_time_id, name="Encounter aborted"
        )
    cases = {
        "pending": (
            _encounter(postgres_engine, f, status="pending", actors=(f.character_a_id,)),
            404,
        ),
        "aborted before start": (
            _encounter(postgres_engine, f, status="aborted", actors=(f.character_a_id,)),
            404,
        ),
        "aborted after start": (
            _encounter(
                postgres_engine,
                f,
                status="aborted",
                actors=(f.character_a_id,),
                resulting_event_id=abort_event,
            ),
            200,
        ),
        "active": (f.encounter_id, 200),
        "completed": (
            _encounter(postgres_engine, f, status="completed", actors=(f.character_a_id,)),
            200,
        ),
    }
    for label, (encounter_id, expected) in cases.items():
        for user_id in (f.discoverer_user_id, f.player_user_id):
            response = _get(client_factory, user_id, f, encounter_id)
            assert response.status_code == expected, (label, response.text)
            if expected == 404:
                # The fixed, non-disclosing body: identical to a nonexistent encounter.
                missing = _get(client_factory, user_id, f, uuid.uuid4())
                got, want = response.json()["error"], missing.json()["error"]
                got.pop("correlation_id"), want.pop("correlation_id")
                assert got == want, label
                _assert_absent(response.text, SUMMARY_MARKER, f.character_a_id)


def test_unavailable_references_are_withheld_from_a_member_but_not_an_editor(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, f: Fixture
) -> None:
    _deny(postgres_engine, f, f.location_hidden_id)
    _deny(postgres_engine, f, f.item_hidden_id)
    with postgres_engine.begin() as connection:
        draft_event = make_event(
            connection,
            f.world_id,
            f.timeline_id,
            f.world_time_id,
            event_status_code="draft",
            name="Draft ending",
        )
        voided_event = make_event(
            connection,
            f.world_id,
            f.timeline_id,
            f.world_time_id,
            event_status_code="voided",
            name="Voided ending",
        )
        shown_event = make_event(
            connection, f.world_id, f.timeline_id, f.world_time_id, name="Recorded ending"
        )

    def read(
        user_id: uuid.UUID, *, location: uuid.UUID, event: uuid.UUID | None, item: uuid.UUID
    ) -> dict[str, Any]:
        encounter_id = _encounter(
            postgres_engine,
            f,
            status="completed",
            actors=(f.character_a_id,),
            location_id=location,
            resulting_event_id=event,
            item_instance_id=item,
        )
        response = _get(client_factory, user_id, f, encounter_id)
        assert response.status_code == 200, response.text
        body: dict[str, Any] = response.json()
        return body

    # Hidden location, hidden item, draft event: null for the member, present for the editor.
    for event in (draft_event, voided_event):
        member = read(
            f.discoverer_user_id,
            location=f.location_hidden_id,
            event=event,
            item=f.item_hidden_id,
        )
        assert member["location_id"] is None
        assert member["resulting_event_id"] is None
        action = member["rounds"][0]["turns"][0]["combat_action"]
        assert action["item_instance_id"] is None
        assert action["hit"] is True  # the witnessed outcome itself is retained
        editor = read(
            f.editor_user_id, location=f.location_hidden_id, event=event, item=f.item_hidden_id
        )
        assert editor["location_id"] == str(f.location_hidden_id)
        assert editor["resulting_event_id"] == str(event)
        assert editor["rounds"][0]["turns"][0]["combat_action"]["item_instance_id"] == str(
            f.item_hidden_id
        )

    # Positive case: discoverable references stay.
    shown = read(
        f.discoverer_user_id, location=f.location_shown_id, event=shown_event, item=f.item_shown_id
    )
    assert shown["location_id"] == str(f.location_shown_id)
    assert shown["resulting_event_id"] == str(shown_event)
    assert shown["rounds"][0]["turns"][0]["combat_action"]["item_instance_id"] == str(
        f.item_shown_id
    )


# ---------------------------------------------------------------------------
# Route boundaries
# ---------------------------------------------------------------------------


def test_an_editor_cannot_read_an_encounter_through_another_campaign(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    # The editor is a member of the fixture campaign only: the other campaign is a 404, and the
    # other campaign's encounter is a 404 under the editor's own campaign.
    assert (
        _get(client_factory, f.editor_user_id, f, campaign_id=f.other_campaign_id).status_code
        == 404
    )
    assert (
        _get(client_factory, f.editor_user_id, f, encounter_id=f.foreign_encounter_id).status_code
        == 404
    )


# ---------------------------------------------------------------------------
# Cross-campaign ownership
# ---------------------------------------------------------------------------


def test_an_encounter_belonging_to_a_different_campaign_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.player_user_id) as client:
        response = client.get(_encounter_url(f, encounter_id=f.foreign_encounter_id))
    assert response.status_code == 404


def test_a_nonexistent_encounter_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.player_user_id) as client:
        response = client.get(_encounter_url(f, encounter_id=uuid.uuid4()))
    assert response.status_code == 404
