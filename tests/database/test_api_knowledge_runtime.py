"""Knowledge runtime: learn, reveal, transfer, change belief, make public (checkpoint 15.2E-3)."""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, text

from tests.authoring_support import AuthoringHarness, harness_fixture_factory
from tests.content_support import ContentSetup
from tests.database.test_api_campaign_clock import Times, _advance, _branch_campaign
from tests.factories import make_campaign_party, make_party

pytestmark = pytest.mark.database


@pytest.fixture
def harness(db_connection: Connection) -> Iterator[AuthoringHarness]:
    yield from harness_fixture_factory()(db_connection)


@pytest.fixture
def s(harness: AuthoringHarness, db_connection: Connection) -> ContentSetup:
    return ContentSetup(harness, db_connection)


def published_claim(s: ContentSetup, statement: str = "The duke is a vampire.") -> str:
    created = s.gm.post(
        s.url("knowledge"),
        {
            "statement": statement,
            "knowledge_type": "secret",
            "truth_status": "true",
            "sensitivity": "secret",
        },
        key=s.gm.fresh_key(),
    ).json()
    s.publish(created["knowledge_item_id"], created["row_version"])
    return str(created["knowledge_item_id"])


def published_npc(s: ContentSetup, name: str = "Mira") -> str:
    species = s.gm.get(s.url("npcs/options")).json()["species"][0]["species_id"]
    created = s.gm.post(
        s.url("npcs"),
        {"name": name, "species_id": species, "size_category": "medium"},
        key=s.gm.fresh_key(),
    ).json()
    s.publish(created["npc_id"], created["row_version"])
    return str(created["npc_id"])


def published_place(s: ContentSetup, name: str = "Stonebridge") -> str:
    created = s.gm.post(
        s.url("locations"), {"category": "settlement", "name": name}, key=s.gm.fresh_key()
    ).json()
    s.publish(created["location_id"], created["row_version"])
    return str(created["location_id"])


def set_clock(s: ContentSetup) -> str:
    time_id = Times(s).at(1)
    assert _advance(s, time_id, 0).status_code == 200
    return time_id


def post(s: ContentSetup, claim: str, action: str, body: dict, cid: str | None = None):  # type: ignore[no-untyped-def]
    return s.gm.post_raw(
        f"/campaigns/{cid or s.cid}/knowledge/{claim}/{action}", body, key=s.gm.fresh_key()
    )


def learn(s: ContentSetup, claim: str, knower: str, **extra: object):  # type: ignore[no-untyped-def]
    return post(s, claim, "learn", {"knower_entity_id": knower, **extra})


def audience(s: ContentSetup, claim: str, cid: str | None = None) -> dict:
    response = s.gm.get(f"/campaigns/{cid or s.cid}/knowledge/{claim}/audience")
    assert response.status_code == 200, response.text
    return response.json()


def code(response) -> str:  # type: ignore[no-untyped-def]
    return str(response.json()["error"]["code"])


def void(s: ContentSetup, event_id: str, reason: str = "Recorded by mistake"):  # type: ignore[no-untyped-def]
    return s.gm.post_raw(
        f"/campaigns/{s.cid}/events/{event_id}/void", {"reason": reason}, key=s.gm.fresh_key()
    )


def event_types(s: ContentSetup) -> list[str]:
    return list(
        s.connection.execute(
            text("""
                SELECT et.code FROM narrative.events ev
                JOIN narrative.event_types et ON et.event_type_id = ev.event_type_id
                JOIN audit.change_log cl ON cl.event_id = ev.event_id
                WHERE ev.campaign_id = :c AND et.code <> 'time_advanced'
                ORDER BY cl.change_log_id
            """),
            {"c": s.cid},
        ).scalars()
    )


def test_a_character_learns_a_claim_with_its_own_belief(s: ContentSetup) -> None:
    claim, npc = published_claim(s), published_npc(s)
    clock = set_clock(s)
    response = learn(
        s,
        claim,
        npc,
        awareness_level="suspected",
        confidence=60,
        interpretation="She thinks the duke only seems pale.",
        note="GM only: she saw him at noon",
    )
    assert response.status_code == 201, response.text
    receipt = response.json()
    assert receipt["knower_entity_id"] == npc and receipt["event_id"]
    [knower] = audience(s, claim)["knowers"]
    assert knower["knower_name"] == "Mira" and knower["awareness_level"] == "suspected"
    assert knower["confidence"] == 60 and "pale" in knower["interpretation"]
    assert knower["last_event_id"] == receipt["event_id"]
    row = s.connection.execute(
        text(
            "SELECT learned_at_world_time_id, learned_via_event_id FROM knowledge.entity_knowledge "
            "WHERE knowledge_item_id = :k"
        ),
        {"k": claim},
    ).one()
    assert str(row.learned_at_world_time_id) == clock
    assert str(row.learned_via_event_id) == receipt["event_id"]
    assert event_types(s) == ["knowledge_learned"]
    [audit] = s.audit("record_character_knowledge")
    assert audit.action == "created" and audit.changed_fields["awareness_level"] == "suspected"
    assert "pale" not in str(audit.changed_fields)
    # The claim itself is unchanged: its truth is the GM's, not the belief's.
    assert s.gm.get(s.url(f"knowledge/{claim}")).json()["truth_status"] == "true"


def test_learning_freezes_the_statement(s: ContentSetup) -> None:
    claim, npc = published_claim(s), published_npc(s)
    set_clock(s)
    assert learn(s, claim, npc).status_code == 201
    view = s.gm.get(s.url(f"knowledge/{claim}")).json()
    rewritten = s.gm.post(
        s.url(f"knowledge/{claim}/update"),
        {
            "expected_row_version": view["row_version"],
            "statement": "Rewritten.",
            "knowledge_type": view["knowledge_type"],
            "truth_status": view["truth_status"],
            "sensitivity": view["sensitivity"],
            "subject_entity_id": None,
        },
        key=s.gm.fresh_key(),
    )
    assert rewritten.status_code == 409 and code(rewritten) == "knowledge_already_known"


def test_only_published_knowers_and_claims_take_part(s: ContentSetup) -> None:
    claim, npc = published_claim(s), published_npc(s)
    place = published_place(s)
    set_clock(s)
    species = s.gm.get(s.url("npcs/options")).json()["species"][0]["species_id"]
    draft = s.gm.post(
        s.url("npcs"),
        {"name": "Unpublished", "species_id": species, "size_category": "medium"},
        key=s.gm.fresh_key(),
    ).json()["npc_id"]
    for knower in (draft, place, str(uuid.uuid4()), claim):
        refused = learn(s, claim, knower)
        assert refused.status_code == 400 and code(refused) == "knower_invalid", knower
    draft_claim = s.gm.post(
        s.url("knowledge"),
        {
            "statement": "Unfinished.",
            "knowledge_type": "secret",
            "truth_status": "true",
            "sensitivity": "secret",
        },
        key=s.gm.fresh_key(),
    ).json()["knowledge_item_id"]
    assert learn(s, draft_claim, npc).status_code == 404
    assert learn(s, str(uuid.uuid4()), npc).status_code == 404
    assert learn(s, claim, npc, confidence=101).status_code == 422
    assert learn(s, claim, npc, awareness_level="certain").status_code == 422
    assert event_types(s) == []
    assert audience(s, claim)["knowers"] == []


def test_a_knower_has_one_belief_and_needs_a_time(s: ContentSetup) -> None:
    claim, npc = published_claim(s), published_npc(s)
    needs = learn(s, claim, npc)
    assert needs.status_code == 409 and code(needs) == "clock_required"
    set_clock(s)
    assert learn(s, claim, npc).status_code == 201
    again = learn(s, claim, npc)
    assert again.status_code == 409 and code(again) == "knower_already_knows"
    assert len(audience(s, claim)["knowers"]) == 1


def test_a_transfer_gives_the_recipient_what_was_conveyed(s: ContentSetup) -> None:
    claim = published_claim(s)
    mira, tom = published_npc(s, "Mira"), published_npc(s, "Tom")
    set_clock(s)
    unknown = post(s, claim, "transfer", {"source_entity_id": mira, "recipient_entity_id": tom})
    assert unknown.status_code == 409 and code(unknown) == "source_does_not_know"
    assert learn(s, claim, mira, interpretation="The duke is ill.").status_code == 201
    sent = post(
        s,
        claim,
        "transfer",
        {
            "source_entity_id": mira,
            "recipient_entity_id": tom,
            "transfer_method": "rumor",
            "awareness_level": "rumored",
            "modified_interpretation": "They say the duke drinks blood.",
        },
    )
    assert sent.status_code == 201, sent.text
    by_name = {k["knower_name"]: k for k in audience(s, claim)["knowers"]}
    assert by_name["Tom"]["awareness_level"] == "rumored"
    assert by_name["Tom"]["interpretation"] == "They say the duke drinks blood."
    assert by_name["Mira"]["interpretation"] == "The duke is ill."
    transfer = s.connection.execute(
        text(
            "SELECT transfer_method, modified_interpretation FROM knowledge.information_transfers"
            " WHERE caused_by_event_id = :e"
        ),
        {"e": sent.json()["event_id"]},
    ).one()
    assert transfer.transfer_method == "rumor" and "blood" in transfer.modified_interpretation
    assert event_types(s) == ["knowledge_learned", "knowledge_transferred"]
    # Without a conveyed change the recipient hears the source's own interpretation.
    ann = published_npc(s, "Ann")
    plain = post(s, claim, "transfer", {"source_entity_id": mira, "recipient_entity_id": ann})
    assert plain.status_code == 201
    heard = {k["knower_name"]: k for k in audience(s, claim)["knowers"]}["Ann"]
    assert heard["interpretation"] == "The duke is ill."
    # Telling someone who already knows, or yourself, or by an unknown method, is refused.
    again = post(s, claim, "transfer", {"source_entity_id": mira, "recipient_entity_id": tom})
    assert again.status_code == 409 and code(again) == "knower_already_knows"
    selfie = post(s, claim, "transfer", {"source_entity_id": mira, "recipient_entity_id": mira})
    assert selfie.status_code == 400
    bad = post(
        s,
        claim,
        "transfer",
        {
            "source_entity_id": mira,
            "recipient_entity_id": published_npc(s, "Bo"),
            "transfer_method": "x",
        },
    )
    assert bad.status_code == 422


def test_a_belief_changes_without_touching_the_truth(s: ContentSetup) -> None:
    claim, npc = published_claim(s), published_npc(s)
    set_clock(s)
    learned = learn(s, claim, npc, interpretation="He is ill.").json()
    [knower] = audience(s, claim)["knowers"]

    def change(token: str | None, **fields: object):  # type: ignore[no-untyped-def]
        return s.gm.post_raw(
            f"/campaigns/{s.cid}/knowledge/knowers/{knower['entity_knowledge_id']}/belief",
            {"expected_last_event_id": token, **fields},
            key=s.gm.fresh_key(),
        )

    changed = change(learned["event_id"], awareness_level="rumored", interpretation="He is undead.")
    assert changed.status_code == 200, changed.text
    after = audience(s, claim)["knowers"][0]
    assert after["awareness_level"] == "rumored" and after["interpretation"] == "He is undead."
    assert after["last_event_id"] == changed.json()["event_id"]
    stale = change(learned["event_id"], confidence=10)
    assert stale.status_code == 409 and code(stale) == "stale_write"
    noop = change(after["last_event_id"], awareness_level="rumored")
    assert noop.status_code == 200 and noop.json()["changed"] is False
    assert "event_id" not in noop.json()
    empty = change(after["last_event_id"])
    assert empty.status_code == 400
    cleared = change(after["last_event_id"], confidence=None)
    assert cleared.status_code == 200  # confidence was already empty: a no-op, not an error
    assert event_types(s) == ["knowledge_learned", "belief_changed"]
    [audit] = s.audit("change_belief")
    assert audit.changed_fields["awareness_level"] == {"from": "aware", "to": "rumored"}
    assert "undead" not in str(audit.changed_fields)
    assert s.gm.get(s.url(f"knowledge/{claim}")).json()["truth_status"] == "true"


def test_a_claim_becomes_public_at_a_location(s: ContentSetup) -> None:
    claim, place = published_claim(s), published_place(s)
    set_clock(s)
    seen = s.player.get(f"/campaigns/{s.cid}/knowledge", view="public")
    assert seen.status_code == 200 and seen.json()["items"] == []
    made = post(s, claim, "make-public", {"location_id": place, "awareness_level": "rumored"})
    assert made.status_code == 201, made.text
    [row] = audience(s, claim)["public"]
    assert row["location_name"] == "Stonebridge" and row["awareness_level"] == "rumored"
    visible = s.player.get(f"/campaigns/{s.cid}/knowledge", view="public").json()["items"]
    assert [i["knowledge_item_id"] for i in visible] == [claim]
    again = post(s, claim, "make-public", {"location_id": place})
    assert again.status_code == 409 and code(again) == "knowledge_already_public"
    elsewhere = post(s, claim, "make-public", {"location_id": published_npc(s)})
    assert elsewhere.status_code == 400 and code(elsewhere) == "location_invalid"
    assert event_types(s) == ["knowledge_made_public"]


def test_a_party_is_told_through_the_same_event_trail(s: ContentSetup) -> None:
    claim = published_claim(s)
    set_clock(s)
    party = make_party(s.connection, s.world_id, "Red")
    outsider = make_party(s.connection, s.world_id, "Elsewhere")
    make_campaign_party(s.connection, uuid.UUID(s.cid), party)
    told = post(s, claim, "reveal-to-party", {"party_id": str(party), "awareness_level": "rumored"})
    assert told.status_code == 201, told.text
    [row] = audience(s, claim)["parties"]
    assert row["party_name"] == "Red" and row["awareness_level"] == "rumored"
    repeat = post(s, claim, "reveal-to-party", {"party_id": str(party)})
    assert repeat.status_code == 200 and repeat.json()["changed"] is False
    assert post(s, claim, "reveal-to-party", {"party_id": str(outsider)}).status_code == 404
    assert event_types(s) == ["knowledge_revealed"]
    discoveries = s.connection.execute(
        text("SELECT count(*) FROM knowledge.party_discoveries WHERE knowledge_item_id = :k"),
        {"k": claim},
    ).scalar()
    assert discoveries == 1


def test_corrections_remove_what_an_event_added(s: ContentSetup) -> None:
    claim = published_claim(s)
    mira, tom = published_npc(s, "Mira"), published_npc(s, "Tom")
    place = published_place(s)
    set_clock(s)
    learned = learn(s, claim, mira).json()["event_id"]
    sent = post(
        s,
        claim,
        "transfer",
        {"source_entity_id": mira, "recipient_entity_id": tom},
    ).json()["event_id"]
    public = post(s, claim, "make-public", {"location_id": place}).json()["event_id"]
    # The transfer can be undone: it removes Tom's belief and the transfer row.
    assert void(s, sent).status_code == 200
    names = {k["knower_name"] for k in audience(s, claim)["knowers"]}
    assert names == {"Mira"}
    assert (
        s.connection.execute(text("SELECT count(*) FROM knowledge.information_transfers")).scalar()
        == 0
    )
    assert void(s, public).status_code == 200 and audience(s, claim)["public"] == []
    assert void(s, learned).status_code == 200 and audience(s, claim)["knowers"] == []
    # Everything can be recorded afresh after a correction.
    assert learn(s, claim, mira).status_code == 201


def test_a_belief_change_is_undone_and_blocks_undoing_the_learning(s: ContentSetup) -> None:
    claim, npc = published_claim(s), published_npc(s)
    set_clock(s)
    learned = learn(s, claim, npc, interpretation="Before.", confidence=40).json()
    [knower] = audience(s, claim)["knowers"]
    changed = s.gm.post_raw(
        f"/campaigns/{s.cid}/knowledge/knowers/{knower['entity_knowledge_id']}/belief",
        {
            "expected_last_event_id": learned["event_id"],
            "interpretation": "After.",
            "confidence": 90,
        },
        key=s.gm.fresh_key(),
    ).json()
    blocked = void(s, learned["event_id"])
    assert blocked.status_code == 409 and code(blocked) == "correction_not_reversible"
    assert void(s, changed["event_id"]).status_code == 200
    [restored] = audience(s, claim)["knowers"]
    assert restored["interpretation"] == "Before." and restored["confidence"] == 40
    # The restoring event now wrote the row, so the original learning stays history.
    still = void(s, learned["event_id"])
    assert still.status_code == 409 and code(still) == "correction_not_reversible"


def test_voiding_a_party_reveal_forgets_the_discovery(s: ContentSetup) -> None:
    claim = published_claim(s)
    set_clock(s)
    party = make_party(s.connection, s.world_id, "Red")
    make_campaign_party(s.connection, uuid.UUID(s.cid), party)
    told = post(s, claim, "reveal-to-party", {"party_id": str(party)}).json()["event_id"]
    assert void(s, told).status_code == 200
    assert audience(s, claim)["parties"] == []
    assert (
        s.connection.execute(
            text("SELECT count(*) FROM knowledge.party_discoveries WHERE knowledge_item_id = :k"),
            {"k": claim},
        ).scalar()
        == 0
    )
    assert post(s, claim, "reveal-to-party", {"party_id": str(party)}).status_code == 201


def test_a_branch_keeps_its_own_audience(s: ContentSetup) -> None:
    claim, npc = published_claim(s), published_npc(s)
    clock = set_clock(s)
    assert learn(s, claim, npc).status_code == 201
    branch_cid = _branch_campaign(s, clock)
    on_branch = post(
        s, claim, "learn", {"knower_entity_id": npc, "world_time_id": clock}, cid=branch_cid
    )
    assert on_branch.status_code == 201, on_branch.text
    assert len(audience(s, claim, branch_cid)["knowers"]) == 1
    # Changing the branch leaves the parent as it was.
    assert audience(s, claim)["knowers"][0]["awareness_level"] == "aware"
    assert (
        s.connection.execute(
            text("SELECT count(*) FROM knowledge.entity_knowledge WHERE knowledge_item_id = :k"),
            {"k": claim},
        ).scalar()
        == 2
    )


def test_authority_replay_and_foreign_claims(s: ContentSetup) -> None:
    claim, npc = published_claim(s), published_npc(s)
    set_clock(s)
    path = f"/campaigns/{s.cid}/knowledge/{claim}/learn"
    denied = s.player.post_raw(path, {"knower_entity_id": npc}, key=s.player.fresh_key())
    assert denied.status_code == 403
    assert s.player.get(f"/campaigns/{s.cid}/knowledge/{claim}/audience").status_code == 403
    key = s.gm.fresh_key()
    first = s.gm.post_raw(path, {"knower_entity_id": npc}, key=key)
    replay = s.gm.post_raw(path, {"knower_entity_id": npc}, key=key)
    assert first.status_code == replay.status_code == 201 and first.json() == replay.json()
    assert (
        event_types(s) == ["knowledge_learned"] and len(s.audit("record_character_knowledge")) == 1
    )
    other = s.stranger.post(
        s.url("knowledge", s.other_cid),
        {
            "statement": "Elsewhere.",
            "knowledge_type": "secret",
            "truth_status": "true",
            "sensitivity": "secret",
        },
        key=s.stranger.fresh_key(),
    ).json()["knowledge_item_id"]
    assert learn(s, other, npc).status_code == 404
    assert s.gm.get(f"/campaigns/{s.cid}/knowledge/{other}/audience").status_code == 404
