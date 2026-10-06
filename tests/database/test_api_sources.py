"""Source attachment and provenance (checkpoint 15.3C-1, decision D-26, migration 134)."""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import DBAPIError

from dnd_ai.domain.data_classification import replay_body
from tests.authoring_support import AuthoringHarness, harness_fixture_factory
from tests.content_support import ContentSetup
from tests.database.test_api_routes_travel import place

pytestmark = pytest.mark.database


@pytest.fixture
def harness(db_connection: Connection) -> Iterator[AuthoringHarness]:
    yield from harness_fixture_factory()(db_connection)


@pytest.fixture
def s(harness: AuthoringHarness, db_connection: Connection) -> ContentSetup:
    return ContentSetup(harness, db_connection)


def code(response) -> str:  # type: ignore[no-untyped-def]
    return str(response.json()["error"]["code"])


def sources_url(s: ContentSetup, cid: str | None = None) -> str:
    return f"/campaigns/{cid or s.cid}/sources"


def entity_url(s: ContentSetup, entity: str, suffix: str, cid: str | None = None) -> str:
    return f"/campaigns/{cid or s.cid}/entities/{entity}{suffix}"


def new_source(s: ContentSetup, title: str = "Core book", **extra: object):  # type: ignore[no-untyped-def]
    return s.gm.post_raw(
        sources_url(s),
        {"source_type": "published_reference", "title": title, **extra},
        key=s.gm.fresh_key(),
    )


def attach(s: ContentSetup, entity: str, source: str):  # type: ignore[no-untyped-def]
    return s.gm.post_raw(
        entity_url(s, entity, "/sources/attach"), {"source_id": source}, key=s.gm.fresh_key()
    )


def detach(s: ContentSetup, entity: str, source: str):  # type: ignore[no-untyped-def]
    return s.gm.post_raw(
        entity_url(s, entity, "/sources/detach"), {"source_id": source}, key=s.gm.fresh_key()
    )


def provenance(s: ContentSetup, entity: str) -> dict:
    response = s.gm.get(entity_url(s, entity, "/provenance"))
    assert response.status_code == 200, response.text
    return dict(response.json())


def test_a_source_is_created_with_a_type_title_and_gm_only_reference(s: ContentSetup) -> None:
    made = new_source(s, "  Player's Handbook  ", reference="p. 123, the inn table")
    assert made.status_code == 201, made.text
    body = made.json()
    assert body["title"] == "Player's Handbook" and body["source_type"] == "published_reference"
    assert body["reference"] == "p. 123, the inn table" and body["attached_count"] == 0
    for bad in (
        {"source_type": "rulebook", "title": "X"},
        {"source_type": "published_reference", "title": "   "},
    ):
        response = s.gm.post_raw(sources_url(s), bad, key=s.gm.fresh_key())
        assert response.status_code in (400, 422), response.text
    (audit,) = s.audit("create_source")
    assert audit.action == "created"
    assert "Handbook" not in str(audit.changed_fields) and "inn table" not in str(
        audit.changed_fields
    )
    assert str(audit.changed_fields).count("published_reference") == 1


def test_the_list_shows_only_this_worlds_authored_sources(s: ContentSetup) -> None:
    place(s, "Stonebridge")  # creating an entity cites its own creation source
    mine = new_source(s, "Mine").json()
    s.stranger.post_raw(
        sources_url(s, s.other_cid),
        {"source_type": "session_notes", "title": "Theirs"},
        key=s.stranger.fresh_key(),
    )
    listed = s.gm.get(sources_url(s)).json()
    assert [i["title"] for i in listed["items"]] == ["Mine"]
    assert [t["value"] for t in listed["source_types"]] == [
        "gm_entry",
        "published_reference",
        "homebrew_document",
        "session_notes",
    ]
    assert mine["source_id"] == listed["items"][0]["source_id"]


def test_attaching_and_detaching_keep_the_history(s: ContentSetup) -> None:
    town = place(s, "Stonebridge")
    source = new_source(s, "Notes", reference="Session 3").json()["source_id"]
    before = s.connection.execute(
        text("SELECT row_version FROM core.entities WHERE entity_id = :e"), {"e": town}
    ).scalar()
    attached = attach(s, town, source)
    assert attached.status_code == 200, attached.text
    link = attached.json()["links"][0]
    assert (
        link["is_attached"] is True
        and link["title"] == "Notes"
        and link["reference"] == "Session 3"
    )
    again = attach(s, town, source)
    assert again.status_code == 409 and code(again) == "source_already_attached"
    gone = detach(s, town, source)
    assert gone.status_code == 200 and gone.json()["links"][0]["is_attached"] is False
    assert gone.json()["links"][0]["detached_by_name"] is not None
    nothing = detach(s, town, source)
    assert nothing.status_code == 409 and code(nothing) == "source_not_attached"
    reattached = attach(s, town, source)
    assert reattached.status_code == 200
    links = reattached.json()["links"]
    assert [link["is_attached"] for link in links] == [True, False]  # newest first
    after = s.connection.execute(
        text("SELECT row_version FROM core.entities WHERE entity_id = :e"), {"e": town}
    ).scalar()
    assert after == before  # provenance is not a definition edit
    listed = s.gm.get(sources_url(s)).json()["items"][0]
    assert listed["attached_count"] == 1
    assert len(s.audit("attach_source")) == 2 and len(s.audit("detach_source")) == 1


def test_a_source_of_another_world_cannot_be_attached(s: ContentSetup) -> None:
    town = place(s, "Stonebridge")
    foreign = s.stranger.post_raw(
        sources_url(s, s.other_cid),
        {"source_type": "session_notes", "title": "Theirs"},
        key=s.stranger.fresh_key(),
    ).json()["source_id"]
    refused = attach(s, town, foreign)
    assert refused.status_code == 400 and code(refused) == "source_invalid"
    missing = attach(s, town, str(uuid.uuid4()))
    assert missing.status_code == 400
    assert provenance(s, town)["links"] == []


def test_provenance_shows_the_creator_origin_and_transitions(s: ContentSetup) -> None:
    town = place(s, "Stonebridge")  # created and published by the GM
    view = provenance(s, town)
    assert view["name"] == "Stonebridge" and view["created_by_name"] is not None
    assert view["origin"]["source_type"] == "gm_entry" and view["origin"]["title"] == "GM entry"
    assert [t["label"] for t in view["transitions"]] == [
        "Submitted for review",
        "Approved",
        "Published as canon",
    ]
    assert view["transitions"][-1]["new_status"] == "canon"
    assert view["transitions"][0]["actor_name"] is not None
    assert view["superseded_by"] is None and view["supersedes"] == []
    for field in ("reason", "changed_fields", "correlation_id"):
        assert field not in str(view)


def test_provenance_names_supersession_links(s: ContentSetup) -> None:
    old, new = place(s, "Old Town"), place(s, "New Town")
    marked = s.gm.post(
        s.lifecycle(old, "/supersede"),
        {
            "expected_row_version": s.connection.execute(
                text("SELECT row_version FROM core.entities WHERE entity_id = :e"), {"e": old}
            ).scalar(),
            "replacement_entity_id": new,
            "replacement_expected_row_version": s.connection.execute(
                text("SELECT row_version FROM core.entities WHERE entity_id = :e"), {"e": new}
            ).scalar(),
        },
        key=s.gm.fresh_key(),
    )
    assert marked.status_code == 200, marked.text
    assert provenance(s, old)["superseded_by"]["name"] == "New Town"
    assert [r["name"] for r in provenance(s, new)["supersedes"]] == ["Old Town"]
    assert "Superseded" in [t["label"] for t in provenance(s, old)["transitions"]]


def test_players_and_other_worlds_are_refused(s: ContentSetup) -> None:
    town = place(s, "Stonebridge")
    source = new_source(s).json()["source_id"]
    assert s.player.get(sources_url(s)).status_code == 403
    assert s.player.get(entity_url(s, town, "/provenance")).status_code == 403
    assert (
        s.player.post_raw(
            entity_url(s, town, "/sources/attach"), {"source_id": source}, key=s.player.fresh_key()
        ).status_code
        == 403
    )
    assert s.stranger.get(entity_url(s, town, "/provenance", s.other_cid)).status_code == 404
    foreign_attach = s.stranger.post_raw(
        entity_url(s, town, "/sources/attach", s.other_cid),
        {"source_id": source},
        key=s.stranger.fresh_key(),
    )
    assert foreign_attach.status_code == 404


def test_replay_attaches_once(s: ContentSetup) -> None:
    town = place(s, "Stonebridge")
    source = new_source(s).json()["source_id"]
    key = s.gm.fresh_key()
    url = entity_url(s, town, "/sources/attach")
    first = s.gm.post_raw(url, {"source_id": source}, key=key)
    replay = s.gm.post_raw(url, {"source_id": source}, key=key)
    assert first.status_code == replay.status_code == 200 and replay.json() == replay_body(
        first.json()
    )
    assert len(provenance(s, town)["links"]) == 1


def test_the_database_guards_the_link_table(s: ContentSetup, db_connection: Connection) -> None:
    town = place(s, "Stonebridge")
    source = new_source(s).json()["source_id"]
    assert attach(s, town, source).status_code == 200
    with pytest.raises(DBAPIError), db_connection.begin_nested():
        db_connection.execute(
            text(
                "UPDATE core.entity_source_links SET attached_at = attached_at - interval '1 day' "
                "WHERE entity_id = :e"
            ),
            {"e": town},
        )
    assert detach(s, town, source).status_code == 200
    with pytest.raises(DBAPIError), db_connection.begin_nested():
        db_connection.execute(
            text(
                "UPDATE core.entity_source_links SET detached_at = now() + interval '1 day' "
                "WHERE entity_id = :e"
            ),
            {"e": town},
        )
    foreign = s.stranger.post_raw(
        sources_url(s, s.other_cid),
        {"source_type": "session_notes", "title": "Theirs"},
        key=s.stranger.fresh_key(),
    ).json()["source_id"]
    with pytest.raises(DBAPIError), db_connection.begin_nested():
        db_connection.execute(
            text("INSERT INTO core.entity_source_links (entity_id, source_id) VALUES (:e, :s)"),
            {"e": town, "s": foreign},
        )
