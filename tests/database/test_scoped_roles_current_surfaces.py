"""Scoped roles against the surfaces built after the roles branch diverged
(docs/adr/0020-scoped-system-world-and-campaign-roles.md; checkpoints CP-4b and CP-4c of the
Phase 14/15 integration).

Two campaigns share one world. Campaign A belongs to the world's Owner. Campaign B is hosted by a
second GM (a world-use grant, no world role); other accounts hold a world role and a campaign role
in B. The tests pin, on the readers and writers the roles branch never saw:

- the server-computed per-record eligibility (`authoring`) for every role union;
- that eligibility agrees with the command it previews, using otherwise valid requests so a
  validation failure is never mistaken for agreement;
- the lifecycle read model offering only the actions the caller holds;
- the campaign-originated exceptions (player-character identity) staying campaign-authorized;
- organization members/offices splitting shared-definition edits (world Editor) from campaign
  state (the operational status);
- the GM-only `origin_notes` of an item instance not crossing campaigns on one world;
- published member reads needing no world role, and nothing private appearing because a runtime
  GM is present.
"""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, text

from tests.authoring_support import Actor, AuthoringHarness, harness_fixture_factory
from tests.content_support import add_member
from tests.database.test_world_canon_boundary import CALENDAR, Shared
from tests.factories import make_item_definition, make_item_instance, make_item_state

pytestmark = pytest.mark.database


@pytest.fixture
def harness(db_connection: Connection) -> Iterator[AuthoringHarness]:
    yield from harness_fixture_factory()(db_connection)


class Roles(Shared):
    """The shared world plus one account per role union, all GMs (or a player) in campaign B."""

    def __init__(self, harness: AuthoringHarness, connection: Connection) -> None:
        super().__init__(harness, connection)
        self.editor = self._member("Editor", "gm", world_role="world_editor")
        self.reviewer = self._member("Reviewer", "gm", world_role="world_reviewer")
        self.both = self._member("Both", "gm", world_role="world_editor", second="world_reviewer")
        self.reader = self._member("Reader", "gm", world_role="world_reader")
        self.player = self._member("Player", "player")

    def _member(
        self,
        name: str,
        campaign_role: str,
        *,
        world_role: str | None = None,
        second: str | None = None,
    ) -> Actor:
        who = self.harness.new_actor(name)
        add_member(self.connection, self.cid_b, who.user_id, campaign_role)
        for code in (world_role, second):
            if code is not None:
                self.role(who, code)
        return who

    @property
    def base_b(self) -> str:
        return f"/campaigns/{self.cid_b}"

    def published_location(self, name: str = "Founders Hall") -> dict:
        created = self.location(name)
        self.s.publish(created["location_id"], created["row_version"])
        return created

    def draft_location(self, name: str) -> dict:
        return self.location(name)

    def proposed_location(self, name: str) -> dict:
        created = self.location(name)
        version = self.s.transition(
            created["location_id"], "submit-for-review", created["row_version"]
        )
        return {**created, "row_version": version["row_version"]}

    def lifecycle_b(self, entity_id: str, action: str = "") -> str:
        return f"{self.base_b}/entities/{entity_id}/lifecycle{action}"


@pytest.fixture
def x(harness: AuthoringHarness, db_connection: Connection) -> Roles:
    return Roles(harness, db_connection)


def _denied(response) -> bool:  # type: ignore[no-untyped-def]
    return (
        response.status_code == 403
        and response.json()["error"]["code"] == "world_authority_required"
    )


FLAGS = ("campaign_originated", "can_read_private", "can_edit", "can_review")


def _flags(response) -> tuple[bool, bool, bool, bool]:  # type: ignore[no-untyped-def]
    assert response.status_code == 200, response.text
    authoring = response.json()["authoring"]
    assert set(authoring) == set(FLAGS)
    return tuple(authoring[name] for name in FLAGS)  # type: ignore[return-value]


# --- per-record eligibility ---------------------------------------------------------------


def test_record_eligibility_follows_each_role_union(x: Roles) -> None:
    location = x.published_location()
    path = f"{x.base_b}/world/locations/{location['location_id']}"
    # campaign_originated, can_read_private, can_edit, can_review
    expected = {
        "campaign-only GM": (x.b, (False, False, False, False)),
        "Editor": (x.editor, (False, True, True, False)),
        "Reviewer": (x.reviewer, (False, True, False, True)),
        "Editor and Reviewer": (x.both, (False, True, True, True)),
        # Reader reads published canon; it never reaches the private side or any action.
        "Reader": (x.reader, (False, False, False, False)),
        # A campaign Player holds nothing here whatever their world roles are.
        "Player": (x.player, (False, False, False, False)),
    }
    for label, (who, flags) in expected.items():
        assert _flags(who.get(path)) == flags, label


def test_a_world_editor_who_is_only_a_player_in_the_campaign_holds_nothing(
    x: Roles, harness: AuthoringHarness, db_connection: Connection
) -> None:
    world_editor_player = harness.new_actor("World Editor and campaign Player")
    add_member(db_connection, x.cid_b, world_editor_player.user_id, "player")
    x.role(world_editor_player, "world_editor")
    location = x.published_location()
    response = world_editor_player.get(f"{x.base_b}/world/locations/{location['location_id']}")
    assert _flags(response) == (False, False, False, False)


def test_the_owner_holds_every_flag(x: Roles) -> None:
    location = x.published_location()
    response = x.a.get(f"/campaigns/{x.cid_a}/world/locations/{location['location_id']}")
    assert _flags(response) == (False, True, True, True)


def test_every_explorer_detail_carries_the_flags(x: Roles) -> None:
    species = next(
        o["species_id"]
        for o in x.a.get(x.s.url("npcs/options")).json()["species"]
        if o["name"].lower() == "human"
    )
    npc = x.a.post(
        x.s.url("npcs"),
        {"name": "Mira", "species_id": species, "size_category": "medium"},
        key=x.a.fresh_key(),
    ).json()
    x.s.publish(npc["npc_id"], npc["row_version"])
    org = x.a.post(
        x.s.url("organizations"),
        {"kind": "organization", "organization_type": "guild", "name": "The Guild"},
        key=x.a.fresh_key(),
    ).json()
    x.s.publish(org["organization_id"], org["row_version"])
    religion = x.a.post(
        x.s.url("religions"),
        {"name": "The Light", "summary": None, "pantheon_structure": "None"},
        key=x.a.fresh_key(),
    ).json()
    x.s.publish(religion["religion_id"], religion["row_version"])
    for path in (
        f"{x.base_b}/characters/{npc['npc_id']}",
        f"{x.base_b}/world/organizations/{org['organization_id']}",
        f"{x.base_b}/world/religions/{religion['religion_id']}",
    ):
        assert _flags(x.b.get(path)) == (False, False, False, False), path
        assert _flags(x.editor.get(path)) == (False, True, True, False), path


def test_player_character_identity_is_campaign_originated(x: Roles) -> None:
    species = next(
        o["species_id"]
        for o in x.b.get(f"{x.base_b}/authoring/player-characters/options").json()["species"]
        if o["name"].lower() == "human"
    )
    pc = x.b.post(
        f"{x.base_b}/authoring/player-characters",
        {"name": "Hero", "species_id": species, "size_category": "medium"},
        key=x.b.fresh_key(),
    )
    assert pc.status_code == 201, pc.text
    entity = pc.json()["player_character_id"]
    # The campaign-only GM holds every flag for the exception, with no world role.
    detail = x.b.get(f"{x.base_b}/characters/{entity}")
    assert _flags(detail) == (True, True, True, True)
    # The exception covers the whole lifecycle, and the lifecycle read model offers it.
    lifecycle = x.b.get(x.lifecycle_b(entity))
    assert lifecycle.status_code == 200, lifecycle.text
    body = lifecycle.json()
    assert body["authoring"]["campaign_originated"] is True
    assert "submit_for_review" in body["available_actions"]
    published = x.s.transition  # the owner's helper acts through campaign A
    del published
    submitted = x.b.post(
        x.lifecycle_b(entity, "/submit-for-review"),
        {"expected_row_version": body["row_version"]},
        key=x.b.fresh_key(),
    )
    assert submitted.status_code == 200, submitted.text


# --- eligibility agrees with the command it previews -------------------------------------


def _can(response) -> bool:  # type: ignore[no-untyped-def]
    """The command authorized: it did not answer `world_authority_required`. The requests below are
    otherwise valid, so any other outcome means the world gate was passed."""
    assert not (response.status_code == 403 and not _denied(response)), response.text
    return not _denied(response)


def test_can_edit_agrees_with_the_edit_commands(x: Roles) -> None:
    published = x.published_location()
    path = f"{x.base_b}/world/locations/{published['location_id']}"
    for label, who in (
        ("campaign-only GM", x.b),
        ("Editor", x.editor),
        ("Reviewer", x.reviewer),
        ("both", x.both),
        ("Reader", x.reader),
    ):
        _, _, can_edit, _ = _flags(who.get(path))
        draft = x.draft_location(f"Draft for {label}")
        # Submit-for-review is an edit action; creating a definition is another.
        submit = who.post(
            x.lifecycle_b(draft["location_id"], "/submit-for-review"),
            {"expected_row_version": draft["row_version"]},
            key=who.fresh_key(),
        )
        create = who.post(
            f"{x.base_b}/authoring/locations",
            {"category": "region", "name": f"By {label}", "summary": None},
            key=who.fresh_key(),
        )
        assert _can(submit) is can_edit, (label, "submit", submit.text)
        assert _can(create) is can_edit, (label, "create", create.text)
        if can_edit:
            assert submit.status_code == 200 and create.status_code == 201


def test_can_review_agrees_with_the_review_commands(x: Roles) -> None:
    published = x.published_location()
    path = f"{x.base_b}/world/locations/{published['location_id']}"
    for label, who in (
        ("campaign-only GM", x.b),
        ("Editor", x.editor),
        ("Reviewer", x.reviewer),
        ("both", x.both),
        ("Reader", x.reader),
    ):
        _, _, _, can_review = _flags(who.get(path))
        proposed = x.proposed_location(f"Proposed for {label}")
        approve = who.post(
            x.lifecycle_b(proposed["location_id"], "/approve"),
            {"expected_row_version": proposed["row_version"]},
            key=who.fresh_key(),
        )
        assert _can(approve) is can_review, (label, approve.text)
        if can_review:
            assert approve.status_code == 200


def test_the_lifecycle_read_model_offers_only_the_actions_the_caller_holds(x: Roles) -> None:
    proposed = x.proposed_location("Awaiting Review")
    path = x.lifecycle_b(proposed["location_id"])

    edit_actions = {"submit_for_review", "return_to_draft", "delete_draft"}
    editor = x.editor.get(path).json()
    assert editor["authoring"] == {
        "campaign_originated": False,
        "can_read_private": True,
        "can_edit": True,
        "can_review": False,
    }
    # A proposed record can be withdrawn by an editor, never approved or published by one.
    assert set(editor["available_actions"]) == {"return_to_draft"}
    assert not {a["action"] for a in editor["blocked_actions"]} - edit_actions

    reviewer = x.reviewer.get(path).json()
    assert {"approve", "reject"} <= set(reviewer["available_actions"])
    assert not set(reviewer["available_actions"]) & edit_actions

    both = x.both.get(path).json()
    assert {"return_to_draft", "approve", "reject"} <= set(both["available_actions"])

    # The private side is not readable at all without the capability.
    assert _denied(x.b.get(path))
    assert _denied(x.reader.get(path))


# --- organization members and offices ----------------------------------------------------


def _published_org(x: Roles, name: str = "The Guild") -> str:
    org = x.a.post(
        x.s.url("organizations"),
        {"kind": "organization", "organization_type": "guild", "name": name},
        key=x.a.fresh_key(),
    ).json()
    x.s.publish(org["organization_id"], org["row_version"])
    return str(org["organization_id"])


def _published_npc(x: Roles, name: str) -> str:
    species = next(
        o["species_id"]
        for o in x.a.get(x.s.url("npcs/options")).json()["species"]
        if o["name"].lower() == "human"
    )
    npc = x.a.post(
        x.s.url("npcs"),
        {"name": name, "species_id": species, "size_category": "medium"},
        key=x.a.fresh_key(),
    ).json()
    x.s.publish(npc["npc_id"], npc["row_version"])
    return str(npc["npc_id"])


def test_org_roster_separates_definition_edits_from_campaign_status(x: Roles) -> None:
    org = _published_org(x)
    path = f"{x.base_b}/organizations/{org}/members"
    roster_b = x.b.get(path).json()
    # The runtime GM sets the status (campaign state) but is not offered stint changes.
    assert roster_b["can_edit"] is False
    assert roster_b["can_set_status"] is True
    assert roster_b["status_choices"], "the campaign GM keeps the operational status choices"
    assert roster_b["authoring"]["can_edit"] is False

    roster_editor = x.editor.get(path).json()
    assert roster_editor["can_edit"] is True and roster_editor["can_set_status"] is True

    roster_reviewer = x.reviewer.get(path).json()
    assert roster_reviewer["can_edit"] is False and roster_reviewer["can_set_status"] is True

    # A plain player reads the published roster with no world role and no editor affordances.
    roster_player = x.player.get(path).json()
    assert roster_player["can_edit"] is False
    assert roster_player["can_set_status"] is False
    assert roster_player["status_choices"] == []
    assert roster_player["authoring"] == dict.fromkeys(FLAGS, False)


def test_org_membership_definition_needs_the_world_editor_but_status_does_not(x: Roles) -> None:
    org = _published_org(x)
    member = _published_npc(x, "Mira")
    calendar = x.a.post(f"/worlds/{x.world_id}/calendars", CALENDAR, key=x.a.fresh_key()).json()
    start = x.b.post(
        f"{x.base_b}/world-times",
        {"calendar_id": calendar["calendar_id"], "year": 1},
        key=x.b.fresh_key(),
    )
    assert start.status_code == 201, start.text
    start_id = start.json()["world_time_id"]

    join = {
        "kind": "membership",
        "relationship_type": "membership",
        "participants": [
            {"entity_id": member, "role": "member"},
            {"entity_id": org, "role": "organization"},
        ],
        "started_world_time_id": start_id,
        "role": "Captain",
    }
    denied = x.b.post(f"{x.base_b}/authoring/relationships", join, key=x.b.fresh_key())
    assert _denied(denied), denied.text
    assert _denied(
        x.reviewer.post(f"{x.base_b}/authoring/relationships", join, key=x.reviewer.fresh_key())
    )
    created = x.editor.post(f"{x.base_b}/authoring/relationships", join, key=x.editor.fresh_key())
    assert created.status_code == 201, created.text
    relationship = created.json()

    # A relationship's definition is shared canon (world Editor); its status and reactions in this
    # timeline are campaign state, which the campaign-only GM records.
    edited = x.b.post(
        f"{x.base_b}/authoring/relationships/{relationship['relationship_id']}/update",
        {
            "expected_row_version": relationship["row_version"],
            "description": "Rewritten by B",
            "started_world_time_id": None,
        },
        key=x.b.fresh_key(),
    )
    assert _denied(edited), edited.text
    evolved = x.b.post(
        f"{x.base_b}/relationships/{relationship['relationship_id']}/evolve",
        {"world_time_id": start_id, "new_status_code": "active"},
        key=x.b.fresh_key(),
    )
    assert evolved.status_code == 200, evolved.text

    # The operational status is campaign state: the campaign-only GM sets it, with no world role.
    clock = x.b.get(f"{x.base_b}/clock").json()
    advanced = x.b.post(
        f"{x.base_b}/clock/advance",
        {"world_time_id": start_id, "expected_row_version": clock["row_version"]},
        key=x.b.fresh_key(),
    )
    assert advanced.status_code == 200, advanced.text
    status = x.b.post(
        f"{x.base_b}/organizations/{org}/status",
        {"world_time_id": start_id, "new_status_code": "dormant", "expected_status": None},
        key=x.b.fresh_key(),
    )
    assert status.status_code == 200, status.text


# --- item instances: GM-only notes do not cross campaigns --------------------------------


def test_item_origin_notes_stay_with_the_campaign_that_holds_the_item(x: Roles) -> None:
    connection = x.connection
    version_id = connection.execute(
        text("SELECT ruleset_version_id FROM campaign.campaigns WHERE campaign_id = :c"),
        {"c": x.cid_a},
    ).scalar_one()
    definition = make_item_definition(connection, version_id)
    item = make_item_instance(
        connection, x.world_id, definition, name="Moonblade", origin_notes="Cursed by the duke"
    )
    timeline_a = connection.execute(
        text("SELECT timeline_id FROM campaign.campaigns WHERE campaign_id = :c"), {"c": x.cid_a}
    ).scalar_one()
    make_item_state(connection, timeline_a, item)

    own = x.a.get(f"/campaigns/{x.cid_a}/world/items/{item}")
    assert own.status_code == 200, own.text
    assert own.json()["origin_notes"] == "Cursed by the duke"

    # Campaign B shares the world but the item is not in B's context: the shared fact is
    # readable, A's GM-only note is not, for a campaign-only GM...
    foreign = x.b.get(f"{x.base_b}/world/items/{item}")
    assert foreign.status_code == 200, foreign.text
    assert foreign.json()["origin_notes"] is None
    assert "Cursed by the duke" not in foreign.text
    # ... nor through the item authoring read, nor after an edit that cannot have seen it.
    authoring = x.b.get(f"{x.base_b}/authoring/items/{item}")
    assert authoring.status_code == 200, authoring.text
    assert authoring.json()["origin_notes"] is None
    assert "Cursed by the duke" not in authoring.text
    renamed = x.b.post(
        f"{x.base_b}/authoring/items/{item}/update",
        {
            "expected_row_version": authoring.json()["row_version"],
            "name": "Moonblade (B's name)",
            "summary": None,
            "origin_notes": None,
        },
        key=x.b.fresh_key(),
    )
    assert renamed.status_code == 200, renamed.text
    stored = connection.execute(
        text("SELECT origin_notes FROM world.item_instances WHERE item_instance_id = :i"),
        {"i": item},
    ).scalar_one()
    assert stored == "Cursed by the duke", (
        "an edit that could not read the notes must not clear them"
    )

    # A world role that reads the private side may read them from any campaign on the world.
    assert x.editor.get(f"{x.base_b}/world/items/{item}").json()["origin_notes"] == (
        "Cursed by the duke"
    )
    # A player never receives GM-only notes.
    assert x.player.get(f"{x.base_b}/world/items/{item}").json()["origin_notes"] is None


# --- published member reads need no world role; drafts stay private ------------------------


def test_published_reads_need_no_world_role_and_drafts_stay_private(x: Roles) -> None:
    draft = x.draft_location("Secret Vault")
    published = x.published_location("Public Square")
    for who in (x.b, x.reader, x.player):
        assert who.get(f"{x.base_b}/world/locations/{published['location_id']}").status_code == 200
        assert who.get(f"{x.base_b}/world/locations/{draft['location_id']}").status_code == 404
        found = who.get(f"{x.base_b}/world/search", q="Secret")
        assert found.status_code == 200
        assert draft["location_id"] not in found.text
    # An Editor does see the draft: the private side is theirs.
    assert x.editor.get(f"{x.base_b}/world/locations/{draft['location_id']}").status_code == 200


def test_world_category_counts_share_the_list_filter(x: Roles) -> None:
    x.draft_location("Hidden Annex")
    x.published_location("Visible Tower")
    for who, sees_hidden in ((x.b, False), (x.player, False), (x.editor, True)):
        listed = who.get(f"{x.base_b}/world/search", include_noncanon="true", limit=100)
        counts = who.get(f"{x.base_b}/world/search/counts", include_noncanon="true")
        assert listed.status_code == 200 and counts.status_code == 200, (listed.text, counts.text)
        names = [item["name"] for item in listed.json()["items"]]
        assert ("Hidden Annex" in names) is sees_hidden
        assert counts.json()["total"] == len(names), (names, counts.json())


def test_unused_uuid_is_unreachable(x: Roles) -> None:
    # Guards the helpers above against a silent no-op: a random id is never an authoring record.
    assert x.editor.get(f"{x.base_b}/world/locations/{uuid.uuid4()}").status_code == 404


def test_knowledge_reads_show_published_claims_to_a_campaign_only_gm_and_hide_drafts(
    x: Roles,
) -> None:
    npc = _published_npc(x, "Mira")
    published = x.a.post(
        x.s.url("knowledge"),
        {
            "statement": "Mira keeps the ledger.",
            "knowledge_type": "secret",
            "truth_status": "true",
            "sensitivity": "secret",
            "subject_entity_id": npc,
        },
        key=x.a.fresh_key(),
    ).json()
    x.s.publish(published["knowledge_item_id"], published["row_version"])
    draft = x.a.post(
        x.s.url("knowledge"),
        {
            "statement": "Mira is the duke's daughter.",
            "knowledge_type": "secret",
            "truth_status": "true",
            "sensitivity": "secret",
            "subject_entity_id": npc,
        },
        key=x.a.fresh_key(),
    ).json()

    # A runtime GM with no world role reads the published claim, GM-only fields included, and the
    # draft is not theirs to read: neither listed nor addressable.
    for who in (x.b, x.reader):
        listed = who.get(f"{x.base_b}/knowledge")
        assert listed.status_code == 200, listed.text
        assert "Mira keeps the ledger." in listed.text
        assert "duke's daughter" not in listed.text
        assert who.get(f"{x.base_b}/knowledge/{published['knowledge_item_id']}").status_code == 200
        assert who.get(f"{x.base_b}/knowledge/{draft['knowledge_item_id']}").status_code == 404

    # The private side belongs to the world Editor.
    assert x.editor.get(f"{x.base_b}/knowledge/{draft['knowledge_item_id']}").status_code == 200


def test_authoring_option_catalogs_offer_creation_only_to_a_world_editor(x: Roles) -> None:
    for path in (
        "authoring/locations/options",
        "authoring/organizations/options",
        "authoring/religions/options",
        "authoring/npcs/options",
        "authoring/knowledge/options",
        "authoring/quests/options",
        "authoring/dungeons/options",
        "authoring/relationships/options",
    ):
        url = f"{x.base_b}/{path}"
        # The catalogs are the private side: a Reviewer reads them but is not offered creation, an
        # Editor is, and a campaign-only GM or a Reader is refused the read outright.
        assert x.editor.get(url).json()["can_create"] is True, path
        assert x.both.get(url).json()["can_create"] is True, path
        assert x.reviewer.get(url).json()["can_create"] is False, path
        assert _denied(x.b.get(url)), path
        assert _denied(x.reader.get(url)), path


def test_authoring_reads_offer_only_the_actions_the_caller_holds(x: Roles) -> None:
    draft = x.location("Under Review")
    proposed = x.s.transition(draft["location_id"], "submit-for-review", draft["row_version"])
    assert proposed["canon_status"] == "proposed"
    path = f"{x.base_b}/authoring/locations/{draft['location_id']}"

    def offered(who: Actor) -> set[str]:
        body = who.get(path).json()
        return set(body["available_actions"]) | {b["action"] for b in body["blocked_actions"]}

    # An Editor can withdraw a proposal but not decide it; a Reviewer decides but never edits.
    editor = offered(x.editor)
    reviewer = offered(x.reviewer)
    both = offered(x.both)
    assert "return_to_draft" in editor and not editor & {"approve", "reject", "publish", "archive"}
    assert {"approve", "reject"} <= reviewer
    assert not reviewer & {"update", "return_to_draft", "submit_for_review", "delete_draft"}
    assert {"return_to_draft", "approve", "reject"} <= both
    # The same holds for a draft that is editable: the Reviewer is not offered `update`.
    other = x.location("Editable Draft")
    other_path = f"{x.base_b}/authoring/locations/{other['location_id']}"
    assert "update" in x.editor.get(other_path).json()["available_actions"]
    assert "update" not in x.reviewer.get(other_path).json()["available_actions"]


def test_provenance_tells_a_reviewer_it_cannot_change_sources(x: Roles) -> None:
    location = x.location("Sourced")
    path = f"{x.base_b}/entities/{location['location_id']}/provenance"
    assert x.editor.get(path).json()["can_edit"] is True
    assert x.reviewer.get(path).json()["can_edit"] is False
    attach = x.reviewer.post(
        f"{x.base_b}/entities/{location['location_id']}/sources/attach",
        {"source_id": str(uuid.uuid4())},
        key=x.reviewer.fresh_key(),
    )
    assert _denied(attach), attach.text
