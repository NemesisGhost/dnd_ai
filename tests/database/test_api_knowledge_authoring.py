"""HTTP contract and command behavior for Knowledge-item definition authoring
(Phase 15.1)."""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, text

from tests.authoring_support import AuthoringHarness, harness_fixture_factory
from tests.builders import dnd5e_ids
from tests.content_support import ContentSetup
from tests.factories import make_character, make_entity_knowledge

pytestmark = pytest.mark.database


@pytest.fixture
def harness(db_connection: Connection) -> Iterator[AuthoringHarness]:
    yield from harness_fixture_factory()(db_connection)


@pytest.fixture
def s(harness: AuthoringHarness, db_connection: Connection) -> ContentSetup:
    return ContentSetup(harness, db_connection)


def create(s: ContentSetup, statement: str = "The duke is a vampire.", **extra: object) -> dict:
    body: dict[str, object] = {
        "statement": statement,
        "knowledge_type": "secret",
        "truth_status": "true",
        "sensitivity": "secret",
        **extra,
    }
    response = s.gm.post(s.url("knowledge"), body, key=s.gm.fresh_key())
    assert response.status_code == 201, response.text
    return response.json()


def update(s: ContentSetup, item: dict, **fields: object) -> object:
    body: dict[str, object] = {
        "expected_row_version": item["row_version"],
        "statement": item["statement"],
        "knowledge_type": item["knowledge_type"],
        "truth_status": item["truth_status"],
        "sensitivity": item["sensitivity"],
        "subject_entity_id": item["subject"] and item["subject"]["entity_id"],
        **fields,
    }
    return s.gm.post(
        s.url(f"knowledge/{item['knowledge_item_id']}/update"), body, key=s.gm.fresh_key()
    )


def location(s: ContentSetup, name: str = "Keep") -> dict:
    response = s.gm.post(
        s.url("locations"), {"category": "settlement", "name": name}, key=s.gm.fresh_key()
    )
    assert response.status_code == 201
    return response.json()


def mark_known(s: ContentSetup, item: dict) -> None:
    timeline_id = s.connection.execute(
        text("SELECT timeline_id FROM campaign.campaigns WHERE campaign_id = :c"), {"c": s.cid}
    ).scalar()
    knower = make_character(s.connection, s.world_id, name="Knower")
    make_entity_knowledge(s.connection, timeline_id, uuid.UUID(item["knowledge_item_id"]), knower)


# --- options ------------------------------------------------------------------------------------


def test_options_come_from_the_lookup_tables(s: ContentSetup) -> None:
    body = s.gm.get(s.url("knowledge/options")).json()
    assert {"secret", "rumor", "claim"} <= {o["value"] for o in body["knowledge_types"]}
    assert {"true", "false"} <= {o["value"] for o in body["truth_statuses"]}
    assert [o["value"] for o in body["sensitivities"]] == [
        "public",
        "restricted",
        "secret",
        "dangerous",
    ]
    assert body["can_create"] is True and body["limits"]["statement_max_length"] == 4000


def test_subject_options_offer_only_usable_subjects(s: ContentSetup) -> None:
    keep = location(s)
    gone = location(s, "Gone")
    s.transition(gone["location_id"], "archive", gone["row_version"])
    names = {o["name"] for o in s.gm.get(s.url("knowledge/subject-options")).json()["items"]}
    assert "Keep" in names and "Gone" not in names
    assert keep["location_id"]


# --- create -------------------------------------------------------------------------------------


def test_create_makes_a_draft_claim_named_from_its_statement(s: ContentSetup) -> None:
    place = location(s)
    view = create(s, "  The duke   is a vampire.  ", subject_entity_id=place["location_id"])
    assert (view["canon_status"], view["lifecycle_status"], view["changed"]) == (
        "draft",
        "active",
        True,
    )
    assert view["statement"] == "The duke   is a vampire."
    assert view["subject"]["name"] == "Keep" and view["in_use"] is False
    row = s.connection.execute(
        text("""
            SELECT e.canonical_name, et.code, st.code AS source_type, e.created_by_user_id
            FROM core.entities e
            JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id
            JOIN core.sources src ON src.source_id = e.source_id
            JOIN core.source_types st ON st.source_type_id = src.source_type_id
            WHERE e.entity_id = :e
        """),
        {"e": view["knowledge_item_id"]},
    ).one()
    assert (row.canonical_name, row.code, row.source_type) == (
        "The duke is a vampire.",
        "knowledge_item",
        "gm_entry",
    )
    assert row.created_by_user_id == s.gm.user_id
    audit = s.audit("create_knowledge_item")
    assert len(audit) == 1 and audit[0].action == "created"


def test_create_writes_no_knower_rows(s: ContentSetup) -> None:
    tables = (
        "knowledge.entity_knowledge",
        "campaign.party_knowledge",
        "knowledge.party_discoveries",
        "knowledge.public_knowledge",
        "narrative.events",
    )
    before = {t: s.count(t) for t in tables}
    create(s)
    assert before == {t: s.count(t) for t in tables}


@pytest.mark.parametrize(
    "body",
    [
        {"statement": ""},
        {"statement": "   "},
        {"statement": "x" * 4001},
        {"knowledge_type": "gossip"},
        {"truth_status": "maybe"},
        {"sensitivity": "top-secret"},
        {"world_id": str(uuid.uuid4())},
        {"is_player_known": True},
    ],
)
def test_invalid_bodies_are_refused_and_write_nothing(s: ContentSetup, body: dict) -> None:
    before = s.count("core.entities")
    full = {
        "statement": "A claim.",
        "knowledge_type": "secret",
        "truth_status": "true",
        "sensitivity": "secret",
        **body,
    }
    response = s.gm.post(s.url("knowledge"), full, key=s.gm.fresh_key())
    assert response.status_code in (400, 422)
    assert s.count("core.entities") == before


def test_subject_references_share_one_code(s: ContentSetup) -> None:
    gone = location(s, "Gone")
    s.transition(gone["location_id"], "archive", gone["row_version"])
    other = create(s, "Another claim.")
    foreign = s.stranger.post(
        s.url("locations", s.other_cid),
        {"category": "region", "name": "Foreign"},
        key=s.stranger.fresh_key(),
    ).json()
    codes = set()
    for subject in (
        gone["location_id"],
        foreign["location_id"],
        other["knowledge_item_id"],
        str(uuid.uuid4()),
    ):
        response = s.gm.post(
            s.url("knowledge"),
            {
                "statement": "About something.",
                "knowledge_type": "secret",
                "truth_status": "true",
                "sensitivity": "secret",
                "subject_entity_id": subject,
            },
            key=s.gm.fresh_key(),
        )
        assert response.status_code == 400
        codes.add(response.json()["error"]["code"])
    assert codes == {"knowledge_subject_invalid"}


# --- update -------------------------------------------------------------------------------------


def test_update_changes_the_claim_and_keeps_the_name_in_step(s: ContentSetup) -> None:
    item = create(s)
    view = update(
        s, item, statement="The duke is a lich.", truth_status="false", sensitivity="dangerous"
    ).json()
    assert (view["statement"], view["truth_status"], view["sensitivity"]) == (
        "The duke is a lich.",
        "false",
        "dangerous",
    )
    name = s.connection.execute(
        text("SELECT canonical_name FROM core.entities WHERE entity_id = :e"),
        {"e": item["knowledge_item_id"]},
    ).scalar()
    assert name == "The duke is a lich."
    diff = s.audit("update_knowledge_item")[0].changed_fields
    assert diff["statement"] == {"from": {"redacted": True}, "to": {"redacted": True}}
    assert "duke" not in str(diff)
    assert diff["truth_status"] == {"from": "true", "to": "false"}


def test_no_op_stale_and_review_states(s: ContentSetup) -> None:
    item = create(s)
    again = update(s, item).json()
    assert again["changed"] is False and again["row_version"] == item["row_version"]
    assert s.audit("update_knowledge_item") == []
    assert update(s, item, sensitivity="public").status_code == 200
    stale = update(s, item, sensitivity="restricted")
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "stale_write"
    s.set_status(item["knowledge_item_id"], canon="approved")
    current = s.gm.get(s.url(f"knowledge/{item['knowledge_item_id']}")).json()
    locked = update(s, current, sensitivity="secret")
    assert locked.status_code == 409 and locked.json()["error"]["code"] == "content_not_editable"


def test_a_known_claim_freezes_statement_type_and_subject_but_not_truth_or_sensitivity(
    s: ContentSetup,
) -> None:
    item = create(s)
    mark_known(s, item)
    view = s.gm.get(s.url(f"knowledge/{item['knowledge_item_id']}")).json()
    assert view["in_use"] is True and set(view["field_locks"]) == {
        "statement",
        "knowledge_type",
        "subject",
    }
    for change in (
        {"statement": "Rewritten."},
        {"knowledge_type": "rumor"},
        {"subject_entity_id": location(s)["location_id"]},
    ):
        response = update(s, view, **change)
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "knowledge_already_known"
    ok = update(s, view, truth_status="partially_true", sensitivity="public")
    assert ok.status_code == 200 and ok.json()["truth_status"] == "partially_true"


def test_another_worlds_claim_and_non_claims_are_not_found(s: ContentSetup) -> None:
    place = location(s)
    assert s.gm.get(s.url(f"knowledge/{place['location_id']}")).status_code == 404
    foreign = s.stranger.post(
        s.url("knowledge", s.other_cid),
        {
            "statement": "Foreign.",
            "knowledge_type": "secret",
            "truth_status": "true",
            "sensitivity": "secret",
        },
        key=s.stranger.fresh_key(),
    ).json()
    assert s.gm.get(s.url(f"knowledge/{foreign['knowledge_item_id']}")).status_code == 404


def test_a_claim_is_opened_and_edited_in_each_campaign_that_shares_its_world(
    s: ContentSetup,
) -> None:
    """Claims belong to the world, not to a timeline or campaign: a second campaign on another
    timeline of the same world reaches the same claim, by its own id, under its own campaign id —
    and only for someone who may edit canon *there*. A campaign that is not the caller's, or is
    in another world, stays the non-disclosing 404."""
    item = create(s)
    kid = item["knowledge_item_id"]
    side = s.gm.post(f"/worlds/{s.world_id}/timelines", {"name": "Side", "description": None})
    assert side.status_code == 201, side.text
    _, version_id = dnd5e_ids(s.connection)
    second = s.gm.post(
        "/campaigns",
        {
            "timeline_id": side.json()["timeline_id"],
            "ruleset_version_id": str(version_id),
            "name": "Second",
            "description": None,
        },
        key=s.gm.fresh_key(),
    )
    assert second.status_code == 201, second.text
    second_cid = second.json()["campaign_id"]

    # The same claim opens in both campaigns the GM edits in, and an edit through the second
    # campaign's own address lands on the one claim the first campaign sees.
    opened = s.gm.get(s.url(f"knowledge/{kid}", second_cid))
    assert opened.status_code == 200, opened.text
    assert opened.json()["statement"] == item["statement"]
    edited = s.gm.post(
        s.url(f"knowledge/{kid}/update", second_cid),
        {
            "expected_row_version": opened.json()["row_version"],
            "statement": "Edited from the second campaign.",
            "knowledge_type": item["knowledge_type"],
            "truth_status": item["truth_status"],
            "sensitivity": item["sensitivity"],
            "subject_entity_id": None,
        },
        key=s.gm.fresh_key(),
    )
    assert edited.status_code == 200, edited.text
    assert (
        s.gm.get(s.url(f"knowledge/{kid}")).json()["statement"]
        == "Edited from the second campaign."
    )

    # Not a member of the second campaign: the same answer as a claim that does not exist.
    assert s.player.get(s.url(f"knowledge/{kid}", second_cid)).status_code == 404
    # Someone who edits only in another world cannot reach it through either campaign.
    for cid in (s.cid, second_cid):
        assert s.stranger.get(s.url(f"knowledge/{kid}", cid)).status_code == 404
    # A claim id that exists nowhere in this world is the identical 404.
    assert s.gm.get(s.url(f"knowledge/{uuid.uuid4()}", second_cid)).status_code == 404


def test_players_cannot_author(s: ContentSetup) -> None:
    for path in ("knowledge/options", "knowledge/subject-options"):
        assert s.player.get(s.url(path)).status_code == 403
    response = s.player.post(
        s.url("knowledge"),
        {
            "statement": "Sneaky.",
            "knowledge_type": "secret",
            "truth_status": "true",
            "sensitivity": "secret",
        },
        key=s.player.fresh_key(),
    )
    assert response.status_code == 403


# --- lifecycle and read gating --------------------------------------------------------------------


def test_a_draft_claim_is_listed_for_editors_only_until_published(s: ContentSetup) -> None:
    item = create(s)
    kid = item["knowledge_item_id"]
    list_url = f"/campaigns/{s.cid}/knowledge?view=known"

    def ids(actor: object) -> set[str]:
        response = actor.get(list_url)  # type: ignore[attr-defined]
        assert response.status_code == 200
        return {i["knowledge_item_id"] for i in response.json()["items"]}

    gm_rows = {i["knowledge_item_id"]: i for i in s.gm.get(list_url).json()["items"]}
    assert kid in gm_rows and gm_rows[kid]["canon_status"] == "draft"
    assert kid not in ids(s.player)
    assert s.player.get(f"/campaigns/{s.cid}/knowledge/{kid}").status_code == 404
    assert s.gm.get(f"/campaigns/{s.cid}/knowledge/{kid}").status_code == 200

    s.publish(kid, item["row_version"])
    rows = s.player.get(list_url).json()["items"]
    published = [i for i in rows if i["knowledge_item_id"] == kid]
    assert not published or published[0].get("canon_status") is None


def test_publish_requires_a_published_subject_and_delete_is_blocked_once_known(
    s: ContentSetup,
) -> None:
    place = location(s)
    item = create(s, subject_entity_id=place["location_id"])
    kid = item["knowledge_item_id"]
    for action in ("submit-for-review", "approve"):
        item = s.transition(kid, action, item["row_version"])
    blocked = s.gm.post(
        s.lifecycle(kid, "/publish"),
        {"expected_row_version": item["row_version"]},
        key=s.gm.fresh_key(),
    )
    assert blocked.status_code == 409, blocked.text
    s.publish(place["location_id"], place["row_version"])
    published = s.transition(kid, "publish", item["row_version"])
    assert published["canon_status"] == "canon"


def test_deleting_a_known_draft_is_blocked(s: ContentSetup) -> None:
    item = create(s)
    mark_known(s, item)
    response = s.gm.post(
        s.lifecycle(item["knowledge_item_id"], "/delete-draft"),
        {"expected_row_version": item["row_version"], "reason": "created by mistake"},
        key=s.gm.fresh_key(),
    )
    assert response.status_code == 409, response.text
    assert s.count("knowledge.knowledge_items") >= 1


def test_deleting_an_unknown_draft_removes_the_claim_row(s: ContentSetup) -> None:
    item = create(s)
    before = s.count("knowledge.knowledge_items")
    response = s.gm.post(
        s.lifecycle(item["knowledge_item_id"], "/delete-draft"),
        {"expected_row_version": item["row_version"], "reason": "created by mistake"},
        key=s.gm.fresh_key(),
    )
    assert response.status_code == 200, response.text
    assert s.count("knowledge.knowledge_items") == before - 1


def test_responses_are_not_cacheable_and_idempotent_replays_match(s: ContentSetup) -> None:
    body = {
        "statement": "Replayed.",
        "knowledge_type": "secret",
        "truth_status": "true",
        "sensitivity": "secret",
    }
    key = s.gm.fresh_key()
    first = s.gm.post(s.url("knowledge"), body, key=key)
    second = s.gm.post(s.url("knowledge"), body, key=key)
    assert first.status_code == second.status_code == 201
    assert first.json()["knowledge_item_id"] == second.json()["knowledge_item_id"]
    assert first.headers["cache-control"] == "no-store"
    assert len(s.audit("create_knowledge_item")) == 1


def test_an_approved_claim_with_an_unpublished_subject_offers_only_return_to_draft(
    s: ContentSetup,
) -> None:
    """The input the portal's "Publish its subject first" guidance is derived from."""
    place = location(s)
    item = create(s, subject_entity_id=place["location_id"])
    kid = item["knowledge_item_id"]
    for action in ("submit-for-review", "approve"):
        item = s.transition(kid, action, item["row_version"])

    lifecycle = s.gm.get(s.lifecycle(kid)).json()
    assert lifecycle["canon_status"] == "approved"
    assert lifecycle["available_actions"] == ["return_to_draft"]
    assert {"action": "publish", "reason": "reference_not_published"} in lifecycle[
        "blocked_actions"
    ]
    authoring = s.gm.get(s.url(f"knowledge/{kid}")).json()
    assert "publish" not in authoring["available_actions"]
    assert {"action": "publish", "reason": "reference_not_published"} in authoring[
        "blocked_actions"
    ]
