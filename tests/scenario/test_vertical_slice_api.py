"""The Phase 10 vertical-slice acceptance scenario (docs/PLAN.md §25),
end to end, through the application API — the phase's own primary
architectural and application acceptance test and exit criterion.

Every dynamic, play-time step a Phase 10 endpoint exists for (establishing
the campaign, memberships, roles, character relationships, resource
grants, party movement, search/discovery, hazard/mechanism interaction,
quest advancement, NPC conversation, ending the session, every read, every
revocation, the second campaign, and the branched timeline) goes through a
real HTTP call against the FastAPI app via `TestClient` — no direct client
write to PostgreSQL for any of it, matching §25's own "must run through
the application API without direct client database writes." This now
includes every role assignment: the campaign creator's own functional-
owner access (`campaign.view`/`canon.edit`/`access.manage`) is established
by `POST /campaigns` alone (migration 085's fix for the High authorization
defect where `campaign_owner` carried `access.manage` only), and player/
observer participants are assigned the seeded system-template `player`/
`observer` roles (migration 086's fix for the sibling gap — those two
roles, and `gm`/`assistant_gm`, previously carried zero `security.
role_capabilities` rows at all) through the ordinary `POST .../
memberships/{id}/roles` endpoint, with no direct `security.roles`/`.
role_capabilities` write anywhere in this file — see `dnd_ai.commands.
campaigns`'s own module docstring for the full defect/fix narrative
behind both migrations.

`POST /campaigns` itself, for both the original timeline and the branched
one (step 18), now depends on a positive first-campaign entitlement — a
`security.timeline_bootstrap_grants` row `dnd_ai.commands.campaigns.
grant_timeline_bootstrap()` issues, called directly in `Fixture.__init__`/
at the branch point below, the same trusted world-authoring-infrastructure
boundary this file's static-content authoring already has (see the next
paragraph). This establishes the scenario's own initial entitlement
through that supported infrastructure boundary explicitly, rather than
"no campaign exists yet" alone ever being treated as authorization — see
that function's own module docstring ("First-campaign entitlement") for
the second Critical defect this closes.

What does *not* go through the API is static world/campaign-content
*authoring*: the world, timeline, dungeon and its structural children, the
quest definition, the NPC, the two player characters, and the party
itself. No workstream in this phase ever built an authoring endpoint for
any of these — Phase 10's own endpoint-surface scoping (docs/PLAN.md §25's
"Keep the endpoint surface limited to what that scenario needs") built
command/query endpoints for the *dynamic* actions a session takes over
already-authored content, never for authoring that content in the first
place (that belongs to a future portal/import phase). This file follows
the identical convention every other `tests/database/test_api_*.py`
fixture in this codebase already uses for exactly this kind of setup:
direct factory helpers, not a "client" in the sense §3/§5 of CLAUDE.md
cares about.

Two further, narrower scope notes:

- "Directly grant a fact to more than one user" (step 4) is delivered as
  two `create_resource_grant` calls granting `character.view_knowledge`
  on the *shared* character to both players — the resource-grant target
  this codebase's query layer actually consumes (`dnd_ai.api.access.
  resolve_party_perspective`). A `knowledge_item_id`-targeted grant is
  also schema-supported (workstream 25) but has no consuming read path
  yet in `dnd_ai.queries.knowledge` — using the character-scoped form
  here proves the same "many users, one fact-bearing relationship" shape
  through a path this codebase's query layer genuinely enforces.
- "Receive restricted knowledge" (step 13) is verified via `knowledge.
  party_discoveries` (the fact that the party now possesses the NPC's
  secret) and the dungeon/character views that read from it — not via
  `GET /campaigns/{id}/knowledge/{knowledge_item_id}`, which additionally
  requires a `campaign.party_knowledge` belief-state row (docs/
  architecture/DATABASE_MODEL.md §15's separate "what a party currently
  believes" layer) that no discovery command in this codebase populates.
  Discovery and belief are deliberately different concerns (CLAUDE.md
  rule 5); this test proves the one the new commands actually deliver.
- Player/observer roles (step 3) are the seeded system-template `player`/
  `observer` roles (migration 086), assigned through the ordinary
  membership-role API — no campaign-scoped role of any kind is created by
  this file anymore. `import_reviewer`/`rules_curator` remain vocabulary-
  only system roles, deliberately: their own capabilities (`import.
  approve`, `rules_source.manage`) belong to later phases with no command
  layer yet to validate a default mapping against — migration 080's
  original "a later Phase 10 workstream owns the rest" note still applies
  to those two specifically.
"""

import uuid
from collections.abc import Callable, Iterator
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, text

from dnd_ai.api.app import create_app
from dnd_ai.api.auth import get_authenticated_user_id
from dnd_ai.api.deps import get_engine
from dnd_ai.commands.campaigns import grant_timeline_bootstrap
from tests.factories import (
    make_ability,
    make_area_connection,
    make_area_hazard,
    make_area_interactable,
    make_character,
    make_dungeon,
    make_dungeon_area,
    make_knowledge_item,
    make_party,
    make_party_membership,
    make_quest,
    make_quest_objective,
    make_quest_stage,
    make_ruleset_version_for_world,
    make_skill,
    make_timeline,
    make_user,
    make_world,
    make_world_time,
    oidc_principal,
)

pytestmark = pytest.mark.scenario


class Fixture:
    """World/campaign-independent content only — see this module's own
    docstring for why. Everything campaign-scoped (roles, memberships,
    sessions, party-campaign association) is created inside the test
    itself, through the API wherever an endpoint exists."""

    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        self.ruleset_version_id = make_ruleset_version_for_world(connection, self.world_id)
        self.ability_id = make_ability(connection, self.ruleset_version_id)
        self.skill_id = make_skill(connection, self.ruleset_version_id, self.ability_id)

        # Fictional-chronology checkpoints, strictly ordered. wt_branch
        # sits before the party ever enters the dungeon (wt_enter) — step
        # 18's own branch point.
        self.wt_before = make_world_time(connection, self.world_id, 10)
        self.wt_branch = make_world_time(connection, self.world_id, 20)
        self.wt_enter = make_world_time(connection, self.world_id, 30)
        self.wt_search = make_world_time(connection, self.world_id, 40)
        self.wt_discover_door = make_world_time(connection, self.world_id, 50)
        self.wt_disarm = make_world_time(connection, self.world_id, 60)
        self.wt_activate = make_world_time(connection, self.world_id, 70)
        self.wt_advance_quest = make_world_time(connection, self.world_id, 80)
        self.wt_talk_npc = make_world_time(connection, self.world_id, 90)
        self.wt_end_session = make_world_time(connection, self.world_id, 100)

        # Step 5: a dungeon with three connected areas (a-b-c).
        self.dungeon_id = make_dungeon(connection, self.world_id)
        self.area_a = make_dungeon_area(connection, self.dungeon_id, name="Entry Hall")
        self.area_b = make_dungeon_area(connection, self.dungeon_id, name="Guardroom")
        self.area_c = make_dungeon_area(connection, self.dungeon_id, name="Vault")
        # A plain, non-hidden connection completes the three-area chain.
        make_area_connection(connection, self.area_b, self.area_c, connection_type_code="door")

        # Step 6: a hidden door, a hidden trap, a (non-hidden) mechanism,
        # and a quest. The mechanism is deliberately not hidden — its
        # *activation* is the "altered dungeon state" step 17 needs a
        # non-GM, no-party observer in a second campaign to be able to see
        # at all (a hidden row is dropped from the result set entirely).
        self.hidden_door_id = make_area_connection(
            connection, self.area_a, self.area_b, connection_type_code="door", is_hidden=True
        )
        self.trap_id = make_area_hazard(connection, self.area_a, is_hidden=True)
        self.mechanism_id = make_area_interactable(connection, self.area_b, is_hidden=False)

        self.door_knowledge_item_id = make_knowledge_item(
            connection,
            self.world_id,
            statement="There is a hidden door to the guardroom.",
            subject_area_connection_id=self.hidden_door_id,
        )
        self.trap_knowledge_item_id = make_knowledge_item(
            connection,
            self.world_id,
            statement="A pressure-plate trap guards the entry hall.",
            subject_area_hazard_id=self.trap_id,
        )

        self.quest_id = make_quest(connection, self.world_id, name="Clear the Entry Hall")
        self.quest_stage_id = make_quest_stage(connection, self.quest_id)
        self.quest_objective_id = make_quest_objective(
            connection, self.quest_stage_id, name="Disarm the trap"
        )

        # An NPC with a restricted secret only a successful conversation
        # reveals (step 13).
        self.npc_id = make_character(connection, self.world_id, name="Old Caretaker")
        self.npc_knowledge_item_id = make_knowledge_item(
            connection,
            self.world_id,
            statement="The caretaker knows the vault combination.",
            subject_entity_id=self.npc_id,
        )

        # Step 2: two characters and a party. Party membership is
        # timeline-scoped (no campaign dependency), so it belongs here.
        self.character_shared_id = make_character(connection, self.world_id, name="Aria")
        self.character_second_id = make_character(connection, self.world_id, name="Borin")
        self.party_id = make_party(connection, self.world_id)
        make_party_membership(
            connection, self.timeline_id, self.party_id, self.character_shared_id, self.wt_before
        )
        make_party_membership(
            connection, self.timeline_id, self.party_id, self.character_second_id, self.wt_before
        )

        # Step 3: a GM and three prospective members, provisioned as
        # security.users (OIDC login/provisioning is a separate concern
        # this scenario doesn't exercise — see this module's docstring).
        self.gm_user_id = make_user(connection, "Vertical Slice GM")
        self.player1_user_id = make_user(connection, "Vertical Slice Player One")
        self.player2_user_id = make_user(connection, "Vertical Slice Player Two")
        self.observer_user_id = make_user(connection, "Vertical Slice Observer")

        # The positive, server-verifiable first-campaign entitlement (`dnd_
        # ai.commands.campaigns`'s own "First-campaign entitlement" module
        # docstring section) — issued here by this fixture acting as
        # trusted world-authoring infrastructure, the same trust boundary
        # every other piece of pre-campaign content above already has.
        # Establishes step 2's own initial entitlement through the
        # supported infrastructure boundary rather than relying on
        # "unclaimed" — this scenario's own step ordering (world/dungeon/
        # knowledge authored before any campaign exists) is exactly the
        # case that made "no campaign yet" alone an insufficient
        # authorization in the first place.
        grant_timeline_bootstrap(
            connection, timeline_id=self.timeline_id, granted_to_user_id=self.gm_user_id
        )


@pytest.fixture
def f(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as connection:
        fixture = Fixture(connection, f"vertical-slice-{uuid.uuid4().hex[:8]}")
    yield fixture
    with postgres_engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        cleanup.execute(
            text("""
                DELETE FROM security.membership_character_relationships
                WHERE campaign_membership_id IN (
                    SELECT campaign_membership_id FROM security.campaign_memberships
                    WHERE campaign_id IN (
                        SELECT campaign_id FROM campaign.campaigns WHERE timeline_id IN (
                            SELECT timeline_id FROM campaign.timelines
                            WHERE timeline_id = :t OR parent_timeline_id = :t
                        )
                    )
                )
            """),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM security.resource_grants WHERE campaign_id IN (
                    SELECT campaign_id FROM campaign.campaigns WHERE timeline_id IN (
                        SELECT timeline_id FROM campaign.timelines
                        WHERE timeline_id = :t OR parent_timeline_id = :t
                    )
                )
            """),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM security.idempotent_requests WHERE campaign_id IN (
                    SELECT campaign_id FROM campaign.campaigns WHERE timeline_id IN (
                        SELECT timeline_id FROM campaign.timelines
                        WHERE timeline_id = :t OR parent_timeline_id = :t
                    )
                )
            """),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM security.membership_roles WHERE campaign_membership_id IN (
                    SELECT campaign_membership_id FROM security.campaign_memberships
                    WHERE campaign_id IN (
                        SELECT campaign_id FROM campaign.campaigns WHERE timeline_id IN (
                            SELECT timeline_id FROM campaign.timelines
                            WHERE timeline_id = :t OR parent_timeline_id = :t
                        )
                    )
                )
            """),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM security.role_capabilities WHERE role_id IN (
                    SELECT role_id FROM security.roles WHERE campaign_id IN (
                        SELECT campaign_id FROM campaign.campaigns WHERE timeline_id IN (
                            SELECT timeline_id FROM campaign.timelines
                            WHERE timeline_id = :t OR parent_timeline_id = :t
                        )
                    )
                )
            """),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM security.roles WHERE campaign_id IN (
                    SELECT campaign_id FROM campaign.campaigns WHERE timeline_id IN (
                        SELECT timeline_id FROM campaign.timelines
                        WHERE timeline_id = :t OR parent_timeline_id = :t
                    )
                )
            """),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM security.campaign_memberships WHERE campaign_id IN (
                    SELECT campaign_id FROM campaign.campaigns WHERE timeline_id IN (
                        SELECT timeline_id FROM campaign.timelines
                        WHERE timeline_id = :t OR parent_timeline_id = :t
                    )
                )
            """),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM campaign.campaigns WHERE timeline_id IN (
                    SELECT timeline_id FROM campaign.timelines
                    WHERE timeline_id = :t OR parent_timeline_id = :t
                )
            """),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text("DELETE FROM campaign.timelines WHERE parent_timeline_id = :t"),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text("DELETE FROM security.users WHERE user_id = ANY(:users)"),
            {
                "users": [
                    fixture.gm_user_id,
                    fixture.player1_user_id,
                    fixture.player2_user_id,
                    fixture.observer_user_id,
                ]
            },
        )
        cleanup.execute(
            text("DELETE FROM core.entities WHERE world_id = :w"), {"w": fixture.world_id}
        )
        cleanup.execute(
            text("DELETE FROM core.worlds WHERE world_id = :w"), {"w": fixture.world_id}
        )


@pytest.fixture
def client_factory(postgres_engine: Engine) -> Callable[[uuid.UUID], TestClient]:
    def _make(user_id: uuid.UUID) -> TestClient:
        app = create_app()
        app.dependency_overrides[get_engine] = lambda: postgres_engine
        app.dependency_overrides[get_authenticated_user_id] = lambda: oidc_principal(user_id)
        return TestClient(app, raise_server_exceptions=False)

    return _make


def _system_role_id(connection: Connection, code: str) -> uuid.UUID:
    """Resolves a system-template `security.roles` row (`campaign_id IS
    NULL`) by its code — `campaign_owner`/`gm`/`assistant_gm`/`player`/
    `observer`/`import_reviewer`/`rules_curator`, migration 080's own
    seeded vocabulary. `dnd_ai.commands._shared.lookup_id` is not used
    here for the same reason `dnd_ai.commands.campaigns.create_campaign`
    itself avoids it for `campaign_owner`: `security.roles.code` is only
    guaranteed unique among system templates (`ux_roles_system_code`,
    `WHERE campaign_id IS NULL`), not globally."""
    role_id = connection.execute(
        text("SELECT role_id FROM security.roles WHERE code = :code AND campaign_id IS NULL"),
        {"code": code},
    ).scalar_one()
    assert isinstance(role_id, uuid.UUID)
    return role_id


def test_the_vertical_slice_scenario(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    gm = client_factory(f.gm_user_id)
    player1 = client_factory(f.player1_user_id)
    player2 = client_factory(f.player2_user_id)
    observer = client_factory(f.observer_user_id)

    # -- Step 2 (campaign) / Step 23's own workstream: establish the
    # campaign through the API. The creator becomes campaign_owner, which
    # migration 085 seeded with the full functional-owner capability set
    # (access.manage, campaign.view, canon.edit) — closing the High
    # authorization defect this scenario's own first cut had previously
    # masked with a hand-built, test-only "gm" role granted via direct
    # security.roles/.role_capabilities writes after the fact. The GM
    # participant below needs no role bootstrap of its own at all.
    create_campaign_response = gm.post(
        "/campaigns",
        json={
            "timeline_id": str(f.timeline_id),
            "ruleset_version_id": str(f.ruleset_version_id),
            "name": "The Sunken Keep",
        },
    )
    assert create_campaign_response.status_code == 201, create_campaign_response.text
    campaign_id = uuid.UUID(create_campaign_response.json()["campaign_id"])

    with postgres_engine.begin() as connection:
        connection.execute(
            text("INSERT INTO campaign.campaign_parties (campaign_id, party_id) VALUES (:c, :p)"),
            {"c": campaign_id, "p": f.party_id},
        )
        # Read-only resolution of the seeded system-template role_ids
        # (migration 086 gave both real capabilities) — not a security
        # write of any kind, the same "look up, don't create" shape
        # create_campaign itself uses for campaign_owner.
        player_role_id = _system_role_id(connection, "player")
        observer_role_id = _system_role_id(connection, "observer")

    # -- Step 3: two players and an observer, the seeded system-template
    # player/observer roles (migration 086), assigned through the ordinary
    # membership-role API — no campaign-scoped role is created here.
    def _add_member(user_id: uuid.UUID, role_id: uuid.UUID) -> uuid.UUID:
        create_response = gm.post(
            f"/campaigns/{campaign_id}/memberships", json={"user_id": str(user_id)}
        )
        assert create_response.status_code == 201, create_response.text
        membership_id = uuid.UUID(create_response.json()["campaign_membership_id"])
        role_response = gm.post(
            f"/campaigns/{campaign_id}/memberships/{membership_id}/roles",
            json={"role_id": str(role_id)},
        )
        assert role_response.status_code == 201, role_response.text
        return membership_id

    player1_membership_id = _add_member(f.player1_user_id, player_role_id)
    player2_membership_id = _add_member(f.player2_user_id, player_role_id)
    _add_member(f.observer_user_id, observer_role_id)

    # -- Step 4: both players relate to the shared character, one player
    # also controls a second character, and a fact (character.view_
    # knowledge on the shared character) is granted directly to both
    # players independently.
    for membership_id, relationship_type in (
        (player1_membership_id, "primary_controller"),
        (player2_membership_id, "co_controller"),
    ):
        relationship_response = gm.post(
            f"/campaigns/{campaign_id}/memberships/{membership_id}/character-relationships",
            json={
                "character_id": str(f.character_shared_id),
                "relationship_type_code": relationship_type,
            },
        )
        assert relationship_response.status_code == 201, relationship_response.text

    second_character_relationship_response = gm.post(
        f"/campaigns/{campaign_id}/memberships/{player2_membership_id}/character-relationships",
        json={
            "character_id": str(f.character_second_id),
            "relationship_type_code": "primary_controller",
        },
    )
    assert second_character_relationship_response.status_code == 201, (
        second_character_relationship_response.text
    )

    resource_grant_ids: dict[uuid.UUID, uuid.UUID] = {}
    for membership_id in (player1_membership_id, player2_membership_id):
        grant_response = gm.post(
            f"/campaigns/{campaign_id}/resource-grants",
            json={
                "character_id": str(f.character_shared_id),
                "capability_code": "character.view_knowledge",
                "grantee_campaign_membership_id": str(membership_id),
            },
        )
        assert grant_response.status_code == 201, grant_response.text
        resource_grant_ids[membership_id] = uuid.UUID(grant_response.json()["resource_grant_id"])

    # A session to attribute the coming actions to (step 14 ends it).
    with postgres_engine.begin() as connection:
        session_id = connection.execute(
            text("""
                INSERT INTO campaign.sessions
                    (campaign_id, session_number, lifecycle_status_id, start_world_time_id)
                VALUES (
                    :campaign, 1,
                    (SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'active'),
                    :start
                )
                RETURNING session_id
            """),
            {"campaign": campaign_id, "start": f.wt_before},
        ).scalar()

    # -- Step 7: move the party into the dungeon (both characters).
    for character_id in (f.character_shared_id, f.character_second_id):
        move_response = gm.post(
            f"/campaigns/{campaign_id}/characters/{character_id}/location",
            json={"world_time_id": str(f.wt_enter), "location_id": str(f.area_a)},
        )
        assert move_response.status_code == 200, move_response.text
        assert move_response.json()["moved"] is True

    character_view_response = gm.get(f"/campaigns/{campaign_id}/characters/{f.character_shared_id}")
    assert character_view_response.status_code == 200, character_view_response.text
    assert character_view_response.json()["current_location_id"] == str(f.area_a)

    def _perform_and_resolve(
        *,
        interaction_type_code: str,
        world_time_id: uuid.UUID,
        target_body: dict[str, object],
        actor_entity_id: uuid.UUID | None = None,
        degree_of_success: str = "success",
        party_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        perform_response = gm.post(
            f"/campaigns/{campaign_id}/interactions",
            json={
                "world_time_id": str(world_time_id),
                "actor_entity_id": str(actor_entity_id or f.character_shared_id),
                "interaction_type_code": interaction_type_code,
                "session_id": str(session_id),
                "targets": [target_body],
                "check_requests": [
                    {
                        "check_kind": "skill_check",
                        "difficulty": 10,
                        "skill_id": str(f.skill_id),
                        "target_index": 0,
                    }
                ],
            },
        )
        assert perform_response.status_code == 201, perform_response.text
        check_request_id = perform_response.json()["check_request_ids"][0]

        resolve_body: dict[str, object] = {
            "degree_of_success": degree_of_success,
            "roll": 18,
            "total_modifier": 2,
            "total": 20,
        }
        if party_id is not None:
            resolve_body["party_id"] = str(party_id)
        resolve_response = gm.post(
            f"/campaigns/{campaign_id}/checks/{check_request_id}/resolve", json=resolve_body
        )
        assert resolve_response.status_code == 201, resolve_response.text
        return cast(dict[str, Any], resolve_response.json())

    # -- Step 8: search discovers the trap but not the hidden door.
    search_result = _perform_and_resolve(
        interaction_type_code="search",
        world_time_id=f.wt_search,
        target_body={"target_area_hazard_id": str(f.trap_id)},
        party_id=f.party_id,
    )
    assert search_result["discovered_knowledge_item_id"] == str(f.trap_knowledge_item_id)

    dungeon_view_partial = player1.get(
        f"/campaigns/{campaign_id}/dungeon-areas/{f.area_a}",
        params={"character_id": str(f.character_shared_id), "party_id": str(f.party_id)},
    )
    assert dungeon_view_partial.status_code == 200, dungeon_view_partial.text
    partial_body = dungeon_view_partial.json()
    assert any(h["area_hazard_id"] == str(f.trap_id) for h in partial_body["hazards"])
    assert not any(
        c["area_connection_id"] == str(f.hidden_door_id) for c in partial_body["connections"]
    )

    # -- Step 9: resolve a check that discovers the hidden door.
    door_result = _perform_and_resolve(
        interaction_type_code="search",
        world_time_id=f.wt_discover_door,
        target_body={"target_area_connection_id": str(f.hidden_door_id)},
        party_id=f.party_id,
    )
    assert door_result["discovered_knowledge_item_id"] == str(f.door_knowledge_item_id)

    dungeon_view_full = player1.get(
        f"/campaigns/{campaign_id}/dungeon-areas/{f.area_a}",
        params={"character_id": str(f.character_shared_id), "party_id": str(f.party_id)},
    )
    assert dungeon_view_full.status_code == 200, dungeon_view_full.text
    assert any(
        c["area_connection_id"] == str(f.hidden_door_id)
        for c in dungeon_view_full.json()["connections"]
    )

    # -- Step 10: disarm the trap.
    disarm_result = _perform_and_resolve(
        interaction_type_code="disarm_trap",
        world_time_id=f.wt_disarm,
        target_body={"target_area_hazard_id": str(f.trap_id)},
    )
    assert disarm_result["hazard_status_code"] == "disarmed"

    # -- Step 11: activate the mechanism.
    activate_result = _perform_and_resolve(
        interaction_type_code="activate_mechanism",
        world_time_id=f.wt_activate,
        target_body={"target_area_interactable_id": str(f.mechanism_id)},
    )
    assert activate_result["interactable_activated"] is True

    # -- Step 12: advance the quest objective.
    advance_response = gm.post(
        f"/campaigns/{campaign_id}/quests/objectives/{f.quest_objective_id}/advance",
        json={
            "world_time_id": str(f.wt_advance_quest),
            "new_status_code": "completed",
            "party_id": str(f.party_id),
        },
    )
    assert advance_response.status_code == 200, advance_response.text

    # -- Step 13: talk to the NPC and receive restricted knowledge.
    npc_result = _perform_and_resolve(
        interaction_type_code="converse",
        world_time_id=f.wt_talk_npc,
        target_body={"target_entity_id": str(f.npc_id)},
        party_id=f.party_id,
    )
    assert npc_result["discovered_knowledge_item_id"] == str(f.npc_knowledge_item_id)

    # -- Step 14: end the session and generate a summary.
    end_session_response = gm.post(
        f"/campaigns/{campaign_id}/sessions/{session_id}/end",
        json={"end_world_time_id": str(f.wt_end_session), "summary": "The keep's entry is clear."},
    )
    assert end_session_response.status_code == 200, end_session_response.text
    assert end_session_response.json()["already_ended"] is False

    # -- Step 15: GM, player, and observer summaries — each succeeds, and
    # hidden content stays indistinguishable from nonexistent for the
    # observer, who has no party perspective at all.
    for client in (gm, player1, observer):
        summary_response = client.get(f"/campaigns/{campaign_id}/summary")
        assert summary_response.status_code == 200, summary_response.text

    observer_dungeon_view = observer.get(f"/campaigns/{campaign_id}/dungeon-areas/{f.area_a}")
    assert observer_dungeon_view.status_code == 200, observer_dungeon_view.text
    observer_body = observer_dungeon_view.json()
    assert observer_body["hazards"] == []
    assert observer_body["connections"] == []

    gm_dungeon_view = gm.get(f"/campaigns/{campaign_id}/dungeon-areas/{f.area_a}")
    assert gm_dungeon_view.status_code == 200, gm_dungeon_view.text
    gm_body = gm_dungeon_view.json()
    assert any(h["area_hazard_id"] == str(f.trap_id) for h in gm_body["hazards"])
    assert any(c["area_connection_id"] == str(f.hidden_door_id) for c in gm_body["connections"])

    # -- Step 16: revoke one grant and verify access disappears.
    revoke_response = gm.post(
        f"/campaigns/{campaign_id}/resource-grants/{resource_grant_ids[player2_membership_id]}/revoke"
    )
    assert revoke_response.status_code == 204, revoke_response.text

    player2_dungeon_view_after_revoke = player2.get(
        f"/campaigns/{campaign_id}/dungeon-areas/{f.area_a}",
        params={"character_id": str(f.character_shared_id), "party_id": str(f.party_id)},
    )
    # player2's player role grants no character.view_knowledge of its own
    # (only the now-revoked direct grant did), so supplying both
    # character_id/party_id now fails resolve_party_perspective's
    # authorization outright — a fixed 404, not a silent downgrade to
    # "no perspective" (dnd_ai.api.access.PartyPerspectiveNotAuthorizedError's
    # own documented contract). This *is* "access disappears": before the
    # revoke, the identical request returned 200 with the trap/door
    # present (proven by dungeon_view_full above via player1, who still
    # holds the capability).
    assert player2_dungeon_view_after_revoke.status_code == 404, (
        player2_dungeon_view_after_revoke.text
    )

    # -- Step 17: a second campaign on the same timeline sees altered
    # (non-hidden) dungeon state but not the first party's discoveries.
    create_campaign2_response = gm.post(
        "/campaigns",
        json={
            "timeline_id": str(f.timeline_id),
            "ruleset_version_id": str(f.ruleset_version_id),
            "name": "A Rival Expedition",
        },
    )
    assert create_campaign2_response.status_code == 201, create_campaign2_response.text
    campaign2_id = uuid.UUID(create_campaign2_response.json()["campaign_id"])
    # gm is campaign2's own creator — and, since campaign2 shares campaign_
    # id's own timeline, gm's access.manage membership there is exactly
    # what _authorize_timeline_reuse() requires to reuse that timeline at
    # all (dnd_ai.commands.campaigns's own module docstring). gm is
    # therefore already campaign_owner in campaign2 too (campaign.view/
    # canon.edit included, migration 085) with no separate role to
    # bootstrap — but an owner's canon.edit always bypasses hidden-content
    # filtering by design (the same property gm_dungeon_view proved above
    # for campaign_id itself), so proving "altered state visible, hidden
    # content not" needs a genuinely weaker, campaign.view-only
    # perspective. player1 joins campaign2 as an ordinary member holding
    # the seeded system-template `player` role (migration 086) instead.
    with postgres_engine.begin() as connection:
        campaign2_player_role_id = _system_role_id(connection, "player")
    add_campaign2_member_response = gm.post(
        f"/campaigns/{campaign2_id}/memberships", json={"user_id": str(f.player1_user_id)}
    )
    assert add_campaign2_member_response.status_code == 201, add_campaign2_member_response.text
    campaign2_player1_membership_id = uuid.UUID(
        add_campaign2_member_response.json()["campaign_membership_id"]
    )
    assign_campaign2_role_response = gm.post(
        f"/campaigns/{campaign2_id}/memberships/{campaign2_player1_membership_id}/roles",
        json={"role_id": str(campaign2_player_role_id)},
    )
    assert assign_campaign2_role_response.status_code == 201, assign_campaign2_role_response.text

    campaign2_view = player1.get(f"/campaigns/{campaign2_id}/dungeon-areas/{f.area_b}")
    assert campaign2_view.status_code == 200, campaign2_view.text
    campaign2_body = campaign2_view.json()
    mechanism_in_campaign2 = next(
        i
        for i in campaign2_body["interactables"]
        if i["area_interactable_id"] == str(f.mechanism_id)
    )
    assert mechanism_in_campaign2["interactable_status_code"] == "activated"

    campaign2_area_a_view = player1.get(f"/campaigns/{campaign2_id}/dungeon-areas/{f.area_a}")
    assert campaign2_area_a_view.status_code == 200, campaign2_area_a_view.text
    campaign2_area_a_body = campaign2_area_a_view.json()
    assert campaign2_area_a_body["hazards"] == []
    assert campaign2_area_a_body["connections"] == []

    # -- Step 18: branch a new timeline before the dungeon entry and
    # verify the dungeon remains untouched there.
    with postgres_engine.begin() as connection:
        branch_timeline_id = make_timeline(
            connection,
            f.world_id,
            "The Road Not Taken",
            parent_timeline_id=f.timeline_id,
            branch_world_time_id=f.wt_branch,
        )
        # branch_timeline_id has no campaign yet either — whoever branches
        # a new timeline also decides who is entitled to bootstrap its
        # first campaign, the same infrastructure boundary the original
        # timeline's own grant came from above.
        grant_timeline_bootstrap(
            connection, timeline_id=branch_timeline_id, granted_to_user_id=f.gm_user_id
        )
    create_campaign3_response = gm.post(
        "/campaigns",
        json={
            "timeline_id": str(branch_timeline_id),
            "ruleset_version_id": str(f.ruleset_version_id),
            "name": "The Branch Campaign",
        },
    )
    assert create_campaign3_response.status_code == 201, create_campaign3_response.text
    campaign3_id = uuid.UUID(create_campaign3_response.json()["campaign_id"])
    # Same reasoning as campaign2 above: branch_timeline_id has never been
    # used by any campaign before this call, so gm claims it unconditionally
    # (dnd_ai.commands.campaigns's own "unclaimed timeline" policy) and is
    # already campaign_owner (canon.edit included) there. observer joins as
    # an ordinary member holding the seeded system-template `observer` role
    # instead, to prove the branch's own dungeon view without an owner's
    # hidden-content bypass in the way.
    with postgres_engine.begin() as connection:
        campaign3_observer_role_id = _system_role_id(connection, "observer")
    add_campaign3_member_response = gm.post(
        f"/campaigns/{campaign3_id}/memberships", json={"user_id": str(f.observer_user_id)}
    )
    assert add_campaign3_member_response.status_code == 201, add_campaign3_member_response.text
    campaign3_observer_membership_id = uuid.UUID(
        add_campaign3_member_response.json()["campaign_membership_id"]
    )
    assign_campaign3_role_response = gm.post(
        f"/campaigns/{campaign3_id}/memberships/{campaign3_observer_membership_id}/roles",
        json={"role_id": str(campaign3_observer_role_id)},
    )
    assert assign_campaign3_role_response.status_code == 201, assign_campaign3_role_response.text

    campaign3_view = observer.get(f"/campaigns/{campaign3_id}/dungeon-areas/{f.area_b}")
    assert campaign3_view.status_code == 200, campaign3_view.text
    campaign3_body = campaign3_view.json()
    mechanism_in_branch = next(
        i
        for i in campaign3_body["interactables"]
        if i["area_interactable_id"] == str(f.mechanism_id)
    )
    assert mechanism_in_branch["interactable_status_code"] is None
