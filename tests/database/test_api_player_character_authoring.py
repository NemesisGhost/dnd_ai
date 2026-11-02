"""HTTP contract and behavior for player-character identity authoring (Phase 15.2B-1).

Uses the real relationship policy for the perspective tests: a relationship confers
nothing for a draft character, and the built-in `owner` type confers a perspective
once the character is published.
"""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, text

from dnd_ai.queries.bootstrap import get_session_bootstrap
from tests.authoring_support import AuthoringHarness, harness_fixture_factory
from tests.content_support import ContentSetup
from tests.factories import (
    make_character,
    make_character_relationship_type,
    make_membership_character_relationship,
    make_relationship_type_capability,
)

pytestmark = pytest.mark.database


@pytest.fixture
def harness(db_connection: Connection) -> Iterator[AuthoringHarness]:
    yield from harness_fixture_factory()(db_connection)


@pytest.fixture
def s(harness: AuthoringHarness, db_connection: Connection) -> ContentSetup:
    return ContentSetup(harness, db_connection)


def species(s: ContentSetup) -> str:
    options = s.gm.get(s.url("player-characters/options")).json()
    return next(o["species_id"] for o in options["species"] if o["name"].lower() == "human")


def create(s: ContentSetup, name: str = "Aldric", **extra: object) -> dict:
    body: dict[str, object] = {
        "name": name,
        "species_id": species(s),
        "size_category": "medium",
        **extra,
    }
    response = s.gm.post(s.url("player-characters"), body, key=s.gm.fresh_key())
    assert response.status_code == 201, response.text
    return response.json()


def membership_of(s: ContentSetup, user_id: uuid.UUID) -> uuid.UUID:
    value = s.connection.execute(
        text(
            "SELECT campaign_membership_id FROM security.campaign_memberships "
            "WHERE campaign_id = :c AND user_id = :u"
        ),
        {"c": s.cid, "u": user_id},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def builtin_type(s: ContentSetup, code: str) -> uuid.UUID:
    value = s.connection.execute(
        text(
            "SELECT character_relationship_type_id FROM security.character_relationship_types "
            "WHERE code = :c"
        ),
        {"c": code},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def test_create_makes_a_complete_draft_player_character_and_leaves_player_user_unset(
    s: ContentSetup,
) -> None:
    pc = create(s, "Aldric", background="Raised by wolves", notes="GM SECRET")
    assert set(pc) >= {"player_character_id", "row_version", "created", "changed"}
    pc_id = pc["player_character_id"]
    row = s.connection.execute(
        text("""
            SELECT et.code AS type_code, cs.code AS canon, ls.code AS lifecycle,
                   (SELECT count(*) FROM character.npcs WHERE npc_id = e.entity_id) AS npcs,
                   pc.player_user_id, d.background, d.notes
            FROM core.entities e
            JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id
            JOIN core.canon_statuses cs ON cs.canon_status_id = e.canon_status_id
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = e.lifecycle_status_id
            JOIN character.characters c ON c.character_id = e.entity_id
            JOIN character.player_characters pc ON pc.player_character_id = e.entity_id
            JOIN character.character_descriptions d ON d.character_id = e.entity_id
            WHERE e.entity_id = :e
        """),
        {"e": pc_id},
    ).one()
    assert (row.type_code, row.canon, row.lifecycle, row.npcs) == (
        "player_character",
        "draft",
        "active",
        0,
    )
    assert row.player_user_id is None
    assert (row.background, row.notes) == ("Raised by wolves", "GM SECRET")
    (audit,) = s.audit("create_player_character")
    assert audit.entity_id == uuid.UUID(pc_id)
    assert "GM SECRET" not in str(audit.changed_fields)
    revision = s.connection.execute(
        text("SELECT revision_kind, snapshot FROM core.entity_revisions WHERE entity_id = :e"),
        {"e": pc_id},
    ).one()
    assert revision.revision_kind == "created"
    assert revision.snapshot["notes"] == "GM SECRET"


def test_get_and_update_round_trip_with_a_bounded_audit_diff(s: ContentSetup) -> None:
    pc = create(s)
    view = s.gm.get(s.url(f"player-characters/{pc['player_character_id']}")).json()
    assert view["canon_status"] == "draft"
    assert "update" in view["available_actions"]
    body = {
        "expected_row_version": view["row_version"],
        "name": "Aldric the Bold",
        "summary": view["summary"],
        "species_id": view["species"]["species_id"],
        "size_category": "large",
        "origin_location_id": None,
        "background": "NEW SECRET BACKGROUND",
        "appearance": None,
        "notes": None,
    }
    response = s.gm.post(
        s.url(f"player-characters/{pc['player_character_id']}/update"), body, key=s.gm.fresh_key()
    )
    assert response.status_code == 200, response.text
    assert response.json()["changed"] is True
    (audit,) = s.audit("update_player_character")
    assert "NEW SECRET BACKGROUND" not in str(audit.changed_fields)
    versions = (
        s.connection.execute(
            text(
                "SELECT revision_kind FROM core.entity_revisions WHERE entity_id = :e ORDER BY row_version"
            ),
            {"e": pc["player_character_id"]},
        )
        .scalars()
        .all()
    )
    assert versions == ["created", "updated"]


def test_a_player_character_and_an_npc_are_not_each_others_route_targets(s: ContentSetup) -> None:
    pc = create(s)
    npc = s.gm.post(
        s.url("npcs"),
        {"name": "Mira", "species_id": species(s), "size_category": "medium"},
        key=s.gm.fresh_key(),
    ).json()
    assert s.gm.get(s.url(f"npcs/{pc['player_character_id']}")).status_code == 404
    assert s.gm.get(s.url(f"player-characters/{npc['npc_id']}")).status_code == 404
    body = {
        "expected_row_version": 1,
        "name": "x",
        "species_id": species(s),
        "size_category": "medium",
    }
    assert (
        s.gm.post(
            s.url(f"player-characters/{npc['npc_id']}/update"), body, key=s.gm.fresh_key()
        ).status_code
        == 404
    )
    assert (
        s.gm.post(
            s.url(f"npcs/{pc['player_character_id']}/update"), body, key=s.gm.fresh_key()
        ).status_code
        == 404
    )
    bare = make_character(s.connection, s.world_id, name="Bare")
    assert s.gm.get(s.url(f"player-characters/{bare}")).status_code == 404


def test_players_and_strangers_cannot_author(s: ContentSetup) -> None:
    body = {"name": "x", "species_id": species(s), "size_category": "medium"}
    assert (
        s.player.post(s.url("player-characters"), body, key=s.player.fresh_key()).status_code == 403
    )
    assert s.stranger.post(
        s.url("player-characters"), body, key=s.stranger.fresh_key()
    ).status_code in (403, 404)


def test_publishing_waits_for_a_published_origin(s: ContentSetup) -> None:
    place = s.gm.post(
        s.url("locations"), {"category": "settlement", "name": "Hearth"}, key=s.gm.fresh_key()
    ).json()
    pc = create(s, origin_location_id=place["location_id"])
    view = s.gm.get(s.url(f"player-characters/{pc['player_character_id']}")).json()
    assert {"action": "publish", "reason": "reference_not_published"} in view[
        "blocked_actions"
    ] or ("publish" not in view["available_actions"])
    s.publish(place["location_id"], place["row_version"])
    version = pc["row_version"]
    assert s.publish(pc["player_character_id"], version) >= version


def test_a_player_character_linked_to_a_user_cannot_be_archived(s: ContentSetup) -> None:
    pc = create(s)
    version = s.publish(pc["player_character_id"], pc["row_version"])
    relationship = make_membership_character_relationship(
        s.connection,
        membership_of(s, s.player.user_id),
        uuid.UUID(pc["player_character_id"]),
        make_character_relationship_type(s.connection),
    )
    refused = s.gm.post(
        s.lifecycle(pc["player_character_id"], "/archive"),
        {"expected_row_version": version},
        key=s.gm.fresh_key(),
    )
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "character_has_user_relationships"
    s.connection.execute(
        text(
            "UPDATE security.membership_character_relationships SET revoked_at = now() "
            "WHERE membership_character_relationship_id = :r"
        ),
        {"r": relationship},
    )
    assert (
        s.transition(pc["player_character_id"], "archive", version)["lifecycle_status"]
        == "archived"
    )


def test_a_draft_player_character_with_no_references_can_be_deleted(s: ContentSetup) -> None:
    pc = create(s, "Mistake")
    response = s.gm.post(
        s.lifecycle(pc["player_character_id"], "/delete-draft"),
        {"expected_row_version": pc["row_version"], "reason": "created by mistake"},
        key=s.gm.fresh_key(),
    )
    assert response.status_code == 200 and response.json()["deleted"] is True
    for table, column in (
        ("character.characters", "character_id"),
        ("character.player_characters", "player_character_id"),
        ("character.character_descriptions", "character_id"),
    ):
        count = s.connection.execute(
            text(f"SELECT count(*) FROM {table} WHERE {column} = :e"),
            {"e": pc["player_character_id"]},
        ).scalar()
        assert count == 0


def grant_player_sight(s: ContentSetup, character_id: str) -> None:
    """A relationship granting discovery and the summary tier, so only the
    lifecycle gate can still hide a draft."""
    relationship_type = make_character_relationship_type(s.connection)
    for code in ("character.discover", "character.view_summary", "campaign.view"):
        capability = s.connection.execute(
            text("SELECT capability_id FROM security.capabilities WHERE code = :c"), {"c": code}
        ).scalar()
        make_relationship_type_capability(s.connection, relationship_type, capability)
    make_membership_character_relationship(
        s.connection,
        membership_of(s, s.player.user_id),
        uuid.UUID(character_id),
        relationship_type,
    )


def test_a_draft_player_character_is_invisible_to_players_on_every_character_read(
    s: ContentSetup,
) -> None:
    pc = create(s, "Hidden Aldric", notes="GM ONLY SECRET")
    node = pc["player_character_id"]
    grant_player_sight(s, node)
    for path in (
        f"/campaigns/{s.cid}/characters/{node}",
        f"/campaigns/{s.cid}/characters/{node}/sheet",
        f"/campaigns/{s.cid}/characters/{node}/inventory",
    ):
        assert s.player.get(path).status_code == 404, path
    search = s.player.get(f"/campaigns/{s.cid}/world/search", q="Hidden", category="character")
    assert all(item["name"] != "Hidden Aldric" for item in search.json()["items"])
    assert s.player.get(f"/campaigns/{s.cid}/world/characters/{node}").status_code in (403, 404)
    gm_search = s.gm.get(
        f"/campaigns/{s.cid}/world/search",
        q="Hidden",
        category="character",
        include_noncanon="true",
    )
    assert any(item["name"] == "Hidden Aldric" for item in gm_search.json()["items"])
    assert s.gm.get(f"/campaigns/{s.cid}/characters/{node}").status_code == 200

    # Once published, the player sees the identity but never the GM notes.
    s.publish(node, pc["row_version"])
    assert s.player.get(f"/campaigns/{s.cid}/characters/{node}").status_code == 200
    assert "GM ONLY SECRET" not in s.player.get(f"/campaigns/{s.cid}/characters/{node}").text


@pytest.mark.real_relationship_policy
def test_the_perspective_appears_after_publish_and_grant_and_disappears_after_archive(
    s: ContentSetup,
) -> None:
    pc = create(s, "Aldric")
    node = uuid.UUID(pc["player_character_id"])
    membership = membership_of(s, s.player.user_id)
    relationship = make_membership_character_relationship(
        s.connection, membership, node, builtin_type(s, "owner")
    )

    def perspectives() -> list[uuid.UUID]:
        bootstrap = get_session_bootstrap(s.connection, user_id=s.player.user_id)
        campaign = next(c for c in bootstrap.campaigns if str(c.campaign_id) == s.cid)
        return [p.character_id for p in campaign.character_perspectives]

    # A draft confers nothing, even with a relationship in place.
    assert perspectives() == []
    version = s.publish(pc["player_character_id"], pc["row_version"])
    assert perspectives() == [node]
    # Revoking the relationship removes it; restoring it and archiving the
    # character (after revoke) keeps it gone.
    s.connection.execute(
        text(
            "UPDATE security.membership_character_relationships SET revoked_at = now() "
            "WHERE membership_character_relationship_id = :r"
        ),
        {"r": relationship},
    )
    assert perspectives() == []
    s.transition(pc["player_character_id"], "archive", version)
    make_membership_character_relationship(s.connection, membership, node, builtin_type(s, "owner"))
    assert perspectives() == []


def test_replay_and_conflict(s: ContentSetup) -> None:
    body = {"name": "Aldric", "species_id": species(s), "size_category": "medium"}
    key = s.gm.fresh_key()
    first = s.gm.post_raw(s.url("player-characters"), body, key=key)
    again = s.gm.post_raw(s.url("player-characters"), body, key=key)
    assert first.status_code == again.status_code == 201
    assert first.json() == again.json()
    changed = s.gm.post_raw(s.url("player-characters"), {**body, "name": "Other"}, key=key)
    assert changed.status_code == 409
    in_world = s.connection.execute(
        text(
            "SELECT count(*) FROM character.player_characters pc "
            "JOIN core.entities e ON e.entity_id = pc.player_character_id WHERE e.world_id = :w"
        ),
        {"w": s.world_id},
    ).scalar()
    assert in_world == 1


def test_a_failure_after_the_character_row_leaves_nothing(
    s: ContentSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy import Connection as Conn

    real_execute = Conn.execute

    def failing(self: Conn, statement: object, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        if "INSERT INTO character.character_descriptions" in str(statement):
            raise RuntimeError("injected failure before the descriptions row")
        return real_execute(self, statement, *args, **kwargs)  # type: ignore[arg-type]

    tables = (
        "core.entities",
        "core.sources",
        "character.characters",
        "character.player_characters",
        "audit.change_log",
        "core.entity_revisions",
        "security.idempotent_requests",
    )
    before = {t: s.count(t) for t in tables}
    body = {"name": "Doomed", "species_id": species(s), "size_category": "small"}
    key = s.gm.fresh_key()
    monkeypatch.setattr(Conn, "execute", failing)
    response = s.gm.post_raw(s.url("player-characters"), body, key=key)
    monkeypatch.undo()
    assert response.status_code == 500
    assert before == {t: s.count(t) for t in tables}
