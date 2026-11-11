# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""Character public-profile drafts and releases over HTTP (P03-A A2a, decision D8).

A campaign's GMs author a draft; someone holding `character.reveal` publishes immutable, versioned
releases of it. Everything runs against committed data across real connections, on the `Gate`
fixture (owners `o1` and `o2`, a custom `access.manage` manager, a player) plus the A1 members
(`gm`, assistant GM, a `gm` look-alike). The read, edit and release rules, the whole-character and
`canon.edit` denies, idempotency across characters, audit and retry behaviour are pinned here; the
lock-order races are in test_character_public_profile_concurrency.py.
"""

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from dnd_ai.commands.character_reveal import (
    grant_character_reveal_delegation,
    revoke_character_reveal_delegation,
)
from dnd_ai.commands.memberships import revoke_membership_role
from tests.database.test_campaign_owner_gate import (  # noqa: F401 - fixtures used by name
    Gate,
    client_factory,
    g,
)
from tests.database.test_character_reveal_delegation import (  # noqa: F401 - fixtures used by name
    Members,
    m,
)
from tests.factories import (
    lookup_id,
    make_campaign,
    make_campaign_membership,
    make_character,
    make_entity,
    make_membership_role,
    make_resource_grant,
    make_user,
    make_world,
)

pytestmark = pytest.mark.database

APPEARANCE = "PUBLIC-APPEARANCE-MARKER-7391"
BACKGROUND = "PUBLIC-BACKGROUND-MARKER-4482"


@dataclass
class Prof:
    character_id: uuid.UUID
    other_character_id: uuid.UUID


@pytest.fixture
def prof(postgres_engine: Engine, g: Gate, m: Members) -> Prof:
    """Two canon, active characters of the Gate's world, and a live reveal delegation for `gm`."""
    with postgres_engine.begin() as connection:
        character = make_character(connection, g.world_id, name="Profile Subject")
        other = make_character(connection, g.world_id, name="Profile Bystander")
        grant_character_reveal_delegation(
            connection,
            campaign_id=g.campaign_id,
            actor_membership_id=g.o1,
            grantee_campaign_membership_id=m.gm,
            reason="Runs the reveals",
        )
    return Prof(character_id=character, other_character_id=other)


# --- helpers ----------------------------------------------------------------------------------


def url(g: Gate, character: uuid.UUID, suffix: str = "") -> str:
    return f"/campaigns/{g.campaign_id}/characters/{character}/public-profile{suffix}"


def save(
    client_factory: Callable[[uuid.UUID], TestClient],
    user: uuid.UUID,
    g: Gate,
    character: uuid.UUID,
    body: dict[str, object],
    *,
    key: str | None = None,
) -> object:
    headers = {"Idempotency-Key": key} if key else {}
    with client_factory(user) as client:
        return client.post(url(g, character, "/draft"), json=body, headers=headers)


def release(
    client_factory: Callable[[uuid.UUID], TestClient],
    user: uuid.UUID,
    g: Gate,
    character: uuid.UUID,
    version: int,
    *,
    key: str | None = None,
    note: str | None = None,
) -> object:
    headers = {"Idempotency-Key": key} if key else {}
    body: dict[str, object] = {"expected_draft_row_version": version}
    if note is not None:
        body["release_note"] = note
    with client_factory(user) as client:
        return client.post(url(g, character, "/releases"), json=body, headers=headers)


def read(
    client_factory: Callable[[uuid.UUID], TestClient],
    user: uuid.UUID,
    g: Gate,
    character: uuid.UUID,
    suffix: str = "",
) -> object:
    with client_factory(user) as client:
        return client.get(url(g, character, suffix))


def code(response: object) -> int:
    return response.status_code  # type: ignore[attr-defined,no-any-return]


def body(response: object) -> dict[str, object]:
    return response.json()  # type: ignore[attr-defined,no-any-return]


def error_code(response: object) -> str:
    return str(body(response)["error"]["code"])  # type: ignore[index]


def counts(engine: Engine, g: Gate) -> tuple[int, int, int, int]:
    """(drafts, releases, audit rows of the profile commands, entity revisions): a refusal changes
    none of them."""
    with engine.connect() as connection:
        row = connection.execute(
            text("""
                SELECT
                  (SELECT count(*) FROM campaign.character_public_profiles WHERE campaign_id = :c),
                  (SELECT count(*) FROM campaign.character_public_profile_releases
                     WHERE campaign_id = :c),
                  (SELECT count(*) FROM audit.change_log
                     WHERE world_id = :w AND command_name IN (
                        'save_character_public_profile_draft', 'release_character_public_profile')),
                  (SELECT count(*) FROM core.entity_revisions WHERE world_id = :w)
            """),
            {"c": g.campaign_id, "w": g.world_id},
        ).one()
    return (row[0], row[1], row[2], row[3])


def deny(
    engine: Engine,
    g: Gate,
    membership: uuid.UUID,
    capability: str,
    character: uuid.UUID,
    *,
    effect: str = "deny",
    key: str = "entity_id",
) -> uuid.UUID:
    """A resource grant naming the character's entity (the only key a `campaign.view` or
    `canon.edit` grant can sit under). `create_resource_grant` refuses a character through
    `entity_id`, so the row is written directly, as the inventory tests do."""
    with engine.begin() as connection:
        return make_resource_grant(
            connection,
            g.campaign_id,
            lookup_id(connection, "security", "capabilities", "capability_id", capability),
            timeline_id=g.timeline_id,
            grantee_campaign_membership_id=membership,
            effect=effect,
            **{key: character},  # type: ignore[arg-type]
        )


def release_rows(engine: Engine, g: Gate, character: uuid.UUID) -> list[dict[str, object]]:
    with engine.connect() as connection:
        rows = connection.execute(
            text("""
                SELECT version_number, from_draft_row_version, authority_source_code,
                       character_reveal_delegation_id, released_by_membership_id,
                       public_appearance, public_background, release_note
                FROM campaign.character_public_profile_releases
                WHERE campaign_id = :c AND character_id = :ch ORDER BY version_number
            """),
            {"c": g.campaign_id, "ch": character},
        ).mappings()
        return [dict(row) for row in rows]


def draft_row(engine: Engine, g: Gate, character: uuid.UUID) -> dict[str, object] | None:
    with engine.connect() as connection:
        row = (
            connection.execute(
                text("""
                SELECT row_version, public_appearance, public_background
                FROM campaign.character_public_profiles
                WHERE campaign_id = :c AND character_id = :ch
            """),
                {"c": g.campaign_id, "ch": character},
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else dict(row)


# --- saving the draft -------------------------------------------------------------------------


def test_a_first_save_creates_then_updates_and_a_repeat_writes_nothing(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate, prof: Prof
) -> None:
    c = prof.character_id
    created = save(
        client_factory, g.o1_user_id, g, c,
        {"expected_row_version": None, "public_appearance": APPEARANCE},
    )  # fmt: skip
    assert code(created) == 201, body(created)
    assert body(created)["row_version"] == 1 and body(created)["created"] is True
    assert draft_row(postgres_engine, g, c) == {
        "row_version": 1, "public_appearance": APPEARANCE, "public_background": None,
    }  # fmt: skip

    updated = save(
        client_factory, g.o1_user_id, g, c,
        {"expected_row_version": 1, "public_background": BACKGROUND},
    )  # fmt: skip
    assert code(updated) == 200 and body(updated)["row_version"] == 2
    assert body(updated)["changed"] is True
    # A field left out is untouched.
    assert draft_row(postgres_engine, g, c) == {
        "row_version": 2, "public_appearance": APPEARANCE, "public_background": BACKGROUND,
    }  # fmt: skip

    audited = counts(postgres_engine, g)
    repeat = save(
        client_factory, g.o1_user_id, g, c,
        {"expected_row_version": 2, "public_appearance": APPEARANCE, "public_background": BACKGROUND},
    )  # fmt: skip
    assert code(repeat) == 200 and body(repeat)["changed"] is False
    assert body(repeat)["row_version"] == 2
    assert counts(postgres_engine, g) == audited  # no bump, no audit row

    cleared = save(
        client_factory, g.o1_user_id, g, c, {"expected_row_version": 2, "public_appearance": None}
    )
    assert code(cleared) == 200 and body(cleared)["row_version"] == 3
    assert draft_row(postgres_engine, g, c) == {
        "row_version": 3, "public_appearance": None, "public_background": BACKGROUND,
    }  # fmt: skip


def test_stale_tokens_and_a_lost_first_save_race_are_409_and_write_nothing(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate, prof: Prof
) -> None:
    c = prof.character_id
    assert code(save(client_factory, g.o1_user_id, g, c, {"expected_row_version": None})) == 201
    before = counts(postgres_engine, g)
    first_again = save(
        client_factory, g.o1_user_id, g, c, {"expected_row_version": None, "public_appearance": "x"}
    )
    assert code(first_again) == 409 and error_code(first_again) == "stale_write"
    stale = save(
        client_factory, g.o1_user_id, g, c, {"expected_row_version": 7, "public_appearance": "x"}
    )
    assert code(stale) == 409 and error_code(stale) == "stale_write"
    missing = save(
        client_factory, g.o1_user_id, g, prof.other_character_id, {"expected_row_version": 1}
    )
    assert code(missing) == 409 and error_code(missing) == "public_profile_draft_missing"
    assert counts(postgres_engine, g) == before
    assert draft_row(postgres_engine, g, c)["public_appearance"] is None  # type: ignore[index]


def test_owner_gm_and_assistant_gm_can_save_but_a_player_and_a_manager_cannot(
    client_factory: Callable[[uuid.UUID], TestClient],
    postgres_engine: Engine,
    g: Gate,
    m: Members,
    prof: Prof,
) -> None:
    for index, user in enumerate((g.o1_user_id, m.gm_user_id, m.ast_user_id)):
        character = make_one_character(postgres_engine, g, f"Saved {index}")
        response = save(
            client_factory, user, g, character,
            {"expected_row_version": None, "public_appearance": "ok"},
        )  # fmt: skip
        assert code(response) == 201, body(response)
    before = counts(postgres_engine, g)
    for user in (g.player_user_id, g.manager_user_id):  # no role canon.edit
        refused = save(
            client_factory, user, g, prof.character_id,
            {"expected_row_version": None, "public_appearance": "no"},
        )  # fmt: skip
        assert code(refused) == 403
    outsider = make_outsider(postgres_engine)
    gone = save(
        client_factory, outsider, g, prof.character_id,
        {"expected_row_version": None, "public_appearance": "no"},
    )  # fmt: skip
    assert code(gone) == 404
    assert counts(postgres_engine, g) == before


def make_one_character(engine: Engine, g: Gate, name: str) -> uuid.UUID:
    with engine.begin() as connection:
        return make_character(connection, g.world_id, name=name)


def make_outsider(engine: Engine) -> uuid.UUID:
    with engine.begin() as connection:
        return make_user(connection, "Profile Outsider")


def test_characters_that_are_not_canon_active_characters_of_the_world_are_refused(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate, prof: Prof
) -> None:
    with postgres_engine.begin() as connection:
        drafted = make_entity(
            connection,
            g.world_id,
            lookup_id(connection, "core", "entity_types", "entity_type_id", "character"),
            name="Draft Character",
            canon_status_code="draft",
        )
        connection.execute(
            text(
                "INSERT INTO character.characters (character_id, species_id, size_category) "
                "SELECT :c, species_id, size_category FROM character.characters WHERE character_id = :o"
            ),
            {"c": drafted, "o": prof.character_id},
        )
        archived = make_character(connection, g.world_id, name="Archived Character")
        connection.execute(
            text(
                "UPDATE core.entities SET lifecycle_status_id = "
                "(SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'archived') "
                "WHERE entity_id = :c"
            ),
            {"c": archived},
        )
        foreign_world = make_world(connection, slug=f"profile-foreign-{uuid.uuid4().hex[:8]}")
        foreign = make_character(connection, foreign_world, name="Foreign Character")
    before = counts(postgres_engine, g)
    attempts = {
        "unknown": (uuid.uuid4(), 404, "not_found"),
        "draft": (drafted, 404, "not_found"),
        "foreign_world": (foreign, 404, "not_found"),
        "archived": (archived, 409, "public_profile_character_not_active"),
    }
    for name, (character, status, error) in attempts.items():
        response = save(
            client_factory, g.o1_user_id, g, character,
            {"expected_row_version": None, "public_appearance": "x"},
        )  # fmt: skip
        assert (code(response), error_code(response)) == (status, error), name
    assert counts(postgres_engine, g) == before
    with postgres_engine.begin() as connection:
        connection.execute(text("SET LOCAL session_replication_role = replica"))
        connection.execute(
            text("DELETE FROM core.entities WHERE world_id = :w"), {"w": foreign_world}
        )
        connection.execute(
            text("DELETE FROM core.worlds WHERE world_id = :w"), {"w": foreign_world}
        )


def test_a_second_campaign_has_its_own_independent_draft_and_cannot_reach_this_one(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate, prof: Prof
) -> None:
    with postgres_engine.begin() as connection:
        other_campaign = make_campaign(connection, g.timeline_id, "Campaign B")
        b_owner = make_user(connection, "Campaign B Owner")
        b_membership = make_campaign_membership(connection, other_campaign, b_owner)
        make_membership_role(connection, b_membership, g.owner_role_id)
    a = save(
        client_factory, g.o1_user_id, g, prof.character_id,
        {"expected_row_version": None, "public_appearance": APPEARANCE},
    )  # fmt: skip
    assert code(a) == 201
    # B's owner is not a member of A: A's routes find nothing; B's routes work independently.
    assert code(read(client_factory, b_owner, g, prof.character_id)) == 404
    path_b = f"/campaigns/{other_campaign}/characters/{prof.character_id}/public-profile"
    with client_factory(b_owner) as client:
        assert client.get(path_b).json()["draft"] is None
        created = client.post(
            path_b + "/draft", json={"expected_row_version": None, "public_appearance": "B text"}
        )
        assert created.status_code == 201, created.text
        assert client.get(path_b).json()["draft"]["public_appearance"] == "B text"
    assert draft_row(postgres_engine, g, prof.character_id)["public_appearance"] == APPEARANCE  # type: ignore[index]
    with postgres_engine.begin() as connection:
        connection.execute(text("SET LOCAL session_replication_role = replica"))
        for table in (
            "campaign.character_public_profile_releases",
            "campaign.character_public_profiles",
            "security.membership_roles",
        ):
            if table == "security.membership_roles":
                connection.execute(
                    text("DELETE FROM security.membership_roles WHERE campaign_membership_id = :m"),
                    {"m": b_membership},
                )
            else:
                connection.execute(
                    text(f"DELETE FROM {table} WHERE campaign_id = :c"),  # noqa: S608
                    {"c": other_campaign},
                )
        connection.execute(
            text("DELETE FROM security.campaign_memberships WHERE campaign_id = :c"),
            {"c": other_campaign},
        )
        connection.execute(
            text("DELETE FROM campaign.campaigns WHERE campaign_id = :c"), {"c": other_campaign}
        )


# --- D8: denies and reads ---------------------------------------------------------------------


def test_a_canon_edit_deny_blocks_editing_only_and_tells_a_reader_why(
    client_factory: Callable[[uuid.UUID], TestClient],
    postgres_engine: Engine,
    g: Gate,
    m: Members,
    prof: Prof,
) -> None:
    c = prof.character_id
    assert code(save(client_factory, g.o1_user_id, g, c, {"expected_row_version": None, "public_appearance": APPEARANCE})) == 201  # fmt: skip
    deny(postgres_engine, g, m.gm, "canon.edit", c)  # the delegated GM
    deny(postgres_engine, g, m.ast, "canon.edit", c)  # the assistant GM (no reveal authority)
    before = counts(postgres_engine, g)
    # A reveal holder can still read, so they are told editing is denied; the assistant GM has no
    # read path left and finds nothing.
    holder = save(client_factory, m.gm_user_id, g, c, {"expected_row_version": 1, "public_appearance": "x"})  # fmt: skip
    assert (code(holder), error_code(holder)) == (403, "public_profile_edit_denied")
    assistant = save(client_factory, m.ast_user_id, g, c, {"expected_row_version": 1, "public_appearance": "x"})  # fmt: skip
    assert code(assistant) == 404
    assert counts(postgres_engine, g) == before
    # The deny removes only the canon.edit read path: the reveal holder still reads and releases.
    view = read(client_factory, m.gm_user_id, g, c)
    assert code(view) == 200
    assert body(view)["can_edit"] is False and body(view)["can_release"] is True
    assert body(view)["draft"]["public_appearance"] == APPEARANCE  # type: ignore[index]
    assert code(read(client_factory, m.ast_user_id, g, c)) == 404
    released = release(client_factory, m.gm_user_id, g, c, 1)
    assert code(released) == 201, body(released)
    # The owner's own edit is unaffected by a deny aimed at others.
    assert code(save(client_factory, g.o1_user_id, g, c, {"expected_row_version": 1, "public_appearance": "owner edit"})) == 200  # fmt: skip


def test_a_whole_character_deny_blocks_reading_editing_and_releasing_for_everyone_it_names(
    client_factory: Callable[[uuid.UUID], TestClient],
    postgres_engine: Engine,
    g: Gate,
    m: Members,
    prof: Prof,
) -> None:
    c = prof.character_id
    assert code(save(client_factory, g.o1_user_id, g, c, {"expected_row_version": None, "public_appearance": APPEARANCE})) == 201  # fmt: skip
    first = release(client_factory, g.o1_user_id, g, c, 1)
    assert code(first) == 201
    deny(postgres_engine, g, g.o1, "campaign.view", c)  # the owner is denied the character
    before = counts(postgres_engine, g)
    for response in (
        read(client_factory, g.o1_user_id, g, c),
        read(client_factory, g.o1_user_id, g, c, "/releases/1"),
        save(
            client_factory,
            g.o1_user_id,
            g,
            c,
            {"expected_row_version": 1, "public_appearance": "x"},
        ),
        release(client_factory, g.o1_user_id, g, c, 1),  # an existing release is never handed back
        release(client_factory, g.o1_user_id, g, c, 1, key="retry-after-deny"),
    ):
        assert code(response) == 404, body(response)
    assert counts(postgres_engine, g) == before
    # Others are unaffected.
    assert code(read(client_factory, g.o2_user_id, g, c)) == 200
    assert code(read(client_factory, m.gm_user_id, g, c)) == 200


def test_a_release_still_succeeds_for_an_owner_with_a_canon_edit_deny(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate, prof: Prof
) -> None:
    c = prof.character_id
    assert code(save(client_factory, g.o1_user_id, g, c, {"expected_row_version": None, "public_appearance": APPEARANCE})) == 201  # fmt: skip
    deny(postgres_engine, g, g.o1, "canon.edit", c)
    assert code(release(client_factory, g.o1_user_id, g, c, 1)) == 201
    refused = save(client_factory, g.o1_user_id, g, c, {"expected_row_version": 1, "public_appearance": "y"})  # fmt: skip
    assert (code(refused), error_code(refused)) == (403, "public_profile_edit_denied")


def test_an_allow_grant_of_canon_edit_does_not_confer_editing_or_reading(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate, prof: Prof
) -> None:
    c = prof.character_id
    deny(postgres_engine, g, g.player, "canon.edit", c, effect="allow")
    before = counts(postgres_engine, g)
    refused = save(client_factory, g.player_user_id, g, c, {"expected_row_version": None, "public_appearance": "x"})  # fmt: skip
    assert code(refused) == 403  # the route needs the role, not a grant
    assert code(read(client_factory, g.player_user_id, g, c)) == 404
    assert counts(postgres_engine, g) == before


def test_reads_follow_d8_and_players_outsiders_and_other_campaigns_find_nothing(
    client_factory: Callable[[uuid.UUID], TestClient],
    postgres_engine: Engine,
    g: Gate,
    m: Members,
    prof: Prof,
) -> None:
    c = prof.character_id
    save(
        client_factory,
        g.o1_user_id,
        g,
        c,
        {"expected_row_version": None, "public_appearance": APPEARANCE},
    )
    for user, can_release in ((g.o1_user_id, True), (m.gm_user_id, True), (m.ast_user_id, False)):
        view = read(client_factory, user, g, c)
        assert code(view) == 200, user
        assert body(view)["can_edit"] is True and body(view)["can_release"] is can_release
        assert body(view)["label"]["name"] == "Profile Subject"  # type: ignore[index]
        assert body(view)["has_unreleased_changes"] is True
    for user in (g.player_user_id, g.manager_user_id, make_outsider(postgres_engine)):
        assert code(read(client_factory, user, g, c)) == 404
    assert code(read(client_factory, g.o1_user_id, g, uuid.uuid4())) == 404
    assert code(read(client_factory, g.o1_user_id, g, c, "/releases/1")) == 404  # none yet
    assert code(read(client_factory, g.o1_user_id, g, c, "/releases/not-a-number")) == 404


# --- releasing --------------------------------------------------------------------------------


def test_an_owner_release_snapshots_the_draft_and_versions_run_without_gaps(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate, prof: Prof
) -> None:
    c = prof.character_id
    save(client_factory, g.o1_user_id, g, c, {"expected_row_version": None, "public_appearance": APPEARANCE, "public_background": BACKGROUND})  # fmt: skip
    first = release(client_factory, g.o1_user_id, g, c, 1, note="First pass")
    assert code(first) == 201, body(first)
    assert body(first)["version_number"] == 1 and body(first)["authority_source"] == "owner"
    assert body(first)["created"] is True and body(first)["is_latest"] is True
    save(client_factory, g.o1_user_id, g, c, {"expected_row_version": 1, "public_appearance": "Second text"})  # fmt: skip
    second = release(client_factory, g.o1_user_id, g, c, 2)
    assert code(second) == 201 and body(second)["version_number"] == 2
    rows = release_rows(postgres_engine, g, c)
    assert [(r["version_number"], r["from_draft_row_version"]) for r in rows] == [(1, 1), (2, 2)]
    assert (
        rows[0]["public_appearance"] == APPEARANCE and rows[1]["public_appearance"] == "Second text"
    )
    assert rows[0]["public_background"] == rows[1]["public_background"] == BACKGROUND
    assert rows[0]["release_note"] == "First pass" and rows[1]["release_note"] is None
    assert all(r["authority_source_code"] == "owner" for r in rows)
    # A release leaves the draft's row_version alone.
    assert draft_row(postgres_engine, g, c)["row_version"] == 2  # type: ignore[index]
    view = read(client_factory, g.o1_user_id, g, c)
    assert [r["version_number"] for r in body(view)["releases"]] == [2, 1]  # type: ignore[union-attr]
    assert body(view)["latest_release"]["public_appearance"] == "Second text"  # type: ignore[index]
    assert body(view)["has_unreleased_changes"] is False
    one = read(client_factory, g.o1_user_id, g, c, "/releases/1")
    assert code(one) == 200 and body(one)["public_appearance"] == APPEARANCE


def test_a_release_may_have_both_fields_empty_and_needs_an_existing_current_draft(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate, prof: Prof
) -> None:
    c = prof.character_id
    missing = release(client_factory, g.o1_user_id, g, c, 1)
    assert (code(missing), error_code(missing)) == (409, "public_profile_draft_missing")
    save(client_factory, g.o1_user_id, g, c, {"expected_row_version": None})
    empty = release(client_factory, g.o1_user_id, g, c, 1)
    assert code(empty) == 201
    row = release_rows(postgres_engine, g, c)[0]
    assert row["public_appearance"] is None and row["public_background"] is None
    save(client_factory, g.o1_user_id, g, c, {"expected_row_version": 1, "public_appearance": "x"})
    stale = release(client_factory, g.o1_user_id, g, c, 5)
    assert (code(stale), error_code(stale)) == (409, "stale_write")
    assert len(release_rows(postgres_engine, g, c)) == 1


def test_a_retry_of_a_released_draft_version_is_200_not_a_false_stale_write(
    client_factory: Callable[[uuid.UUID], TestClient],
    postgres_engine: Engine,
    g: Gate,
    m: Members,
    prof: Prof,
) -> None:
    c = prof.character_id
    save(client_factory, g.o1_user_id, g, c, {"expected_row_version": None, "public_appearance": APPEARANCE})  # fmt: skip
    created = release(client_factory, g.o1_user_id, g, c, 1)
    assert code(created) == 201
    save(client_factory, g.o1_user_id, g, c, {"expected_row_version": 1, "public_appearance": "moved on"})  # fmt: skip
    before = counts(postgres_engine, g)
    retry = release(client_factory, g.o1_user_id, g, c, 1)  # no key: the draft has advanced
    assert code(retry) == 200, body(retry)
    assert body(retry)["created"] is False and body(retry)["version_number"] == 1
    assert body(retry)["is_latest"] is True
    assert (
        body(retry)["character_public_profile_release_id"]
        == body(created)["character_public_profile_release_id"]
    )
    # A later release makes the retry report is_latest false; the delegated GM retrying the owner's
    # release gets the same row, with the first releaser as provenance.
    assert code(release(client_factory, g.o1_user_id, g, c, 2)) == 201
    again = release(client_factory, m.gm_user_id, g, c, 1)
    assert (
        code(again) == 200 and body(again)["created"] is False and body(again)["is_latest"] is False
    )
    assert body(again)["authority_source"] == "owner"
    assert len(release_rows(postgres_engine, g, c)) == 2
    assert counts(postgres_engine, g)[2] == before[2] + 1  # only the second release was audited


def test_only_an_owner_or_a_delegated_gm_may_release(
    client_factory: Callable[[uuid.UUID], TestClient],
    postgres_engine: Engine,
    g: Gate,
    m: Members,
    prof: Prof,
) -> None:
    c = prof.character_id
    save(client_factory, g.o1_user_id, g, c, {"expected_row_version": None, "public_appearance": APPEARANCE})  # fmt: skip
    delegated = release(client_factory, m.gm_user_id, g, c, 1)
    assert code(delegated) == 201 and body(delegated)["authority_source"] == "delegation"
    row = release_rows(postgres_engine, g, c)[0]
    assert row["authority_source_code"] == "delegation" and row["released_by_membership_id"] == m.gm
    with postgres_engine.connect() as connection:
        live = connection.execute(
            text(
                "SELECT character_reveal_delegation_id FROM security.character_reveal_delegations "
                "WHERE grantee_campaign_membership_id = :m AND revoked_at IS NULL"
            ),
            {"m": m.gm},
        ).scalar_one()
    assert row["character_reveal_delegation_id"] == live
    save(client_factory, g.o1_user_id, g, c, {"expected_row_version": 1, "public_appearance": "next"})  # fmt: skip
    before = counts(postgres_engine, g)
    for user in (
        m.ast_user_id,  # assistant GM
        m.lookalike_user_id,  # a custom role that borrows the code `gm`
        g.manager_user_id,  # custom access.manage holder
        g.player_user_id,
    ):
        refused = release(client_factory, user, g, c, 2)
        # The look-alike's custom role has no capability at all, so the route filter stops it
        # first; the others reach the authority check.
        expected = "forbidden" if user == m.lookalike_user_id else "character_reveal_required"
        assert (code(refused), error_code(refused)) == (403, expected), user
    assert counts(postgres_engine, g) == before
    # An outsider (and another campaign's owner) finds nothing.
    assert code(release(client_factory, make_outsider(postgres_engine), g, c, 2)) == 404
    assert counts(postgres_engine, g) == before


def test_a_revoked_delegation_or_gm_role_ends_future_release_but_keeps_earlier_releases(
    client_factory: Callable[[uuid.UUID], TestClient],
    postgres_engine: Engine,
    g: Gate,
    m: Members,
    prof: Prof,
) -> None:
    c = prof.character_id
    save(client_factory, g.o1_user_id, g, c, {"expected_row_version": None, "public_appearance": APPEARANCE})  # fmt: skip
    assert code(release(client_factory, m.gm_user_id, g, c, 1)) == 201
    save(
        client_factory, g.o1_user_id, g, c, {"expected_row_version": 1, "public_appearance": "two"}
    )
    with postgres_engine.begin() as connection:
        revoke_character_reveal_delegation(
            connection,
            campaign_id=g.campaign_id,
            actor_membership_id=g.o1,
            grantee_campaign_membership_id=m.gm,
            reason="Done for now",
        )
    before = counts(postgres_engine, g)
    refused = release(client_factory, m.gm_user_id, g, c, 2)
    assert (code(refused), error_code(refused)) == (403, "character_reveal_required")
    assert counts(postgres_engine, g) == before
    # The earlier release is unchanged and still listed (the GM still holds canon.edit).
    view = read(client_factory, m.gm_user_id, g, c)
    assert [r["version_number"] for r in body(view)["releases"]] == [1]  # type: ignore[union-attr]
    assert body(view)["releases"][0]["authority_source"] == "delegation"  # type: ignore[index]
    assert body(view)["can_release"] is False
    # Re-delegate, then lose the gm role itself: the delegation closes and release is refused again.
    with postgres_engine.begin() as connection:
        grant_character_reveal_delegation(
            connection,
            campaign_id=g.campaign_id,
            actor_membership_id=g.o1,
            grantee_campaign_membership_id=m.gm,
            reason="Back again",
        )
    assert code(release(client_factory, m.gm_user_id, g, c, 2)) == 201
    with postgres_engine.begin() as connection:
        revoke_membership_role(connection, membership_role_id=m.gm_role, campaign_id=g.campaign_id)
    save(client_factory, g.o1_user_id, g, c, {"expected_row_version": 2, "public_appearance": "three"})  # fmt: skip
    assert code(release(client_factory, m.gm_user_id, g, c, 3)) in (403, 404)
    assert [r["version_number"] for r in release_rows(postgres_engine, g, c)] == [1, 2]


# --- idempotency ------------------------------------------------------------------------------


def test_a_save_replays_for_its_own_character_and_conflicts_for_another(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate, prof: Prof
) -> None:
    key = f"save-{uuid.uuid4().hex[:8]}"
    payload = {"expected_row_version": None, "public_appearance": APPEARANCE}
    first = save(client_factory, g.o1_user_id, g, prof.character_id, payload, key=key)
    assert code(first) == 201
    replay = save(client_factory, g.o1_user_id, g, prof.character_id, payload, key=key)
    assert code(replay) == 201 and body(replay)["row_version"] == body(first)["row_version"]
    assert draft_row(postgres_engine, g, prof.character_id)["row_version"] == 1  # type: ignore[index]
    other = save(client_factory, g.o1_user_id, g, prof.other_character_id, payload, key=key)
    assert code(other) == 409 and error_code(other) != "stale_write"
    assert draft_row(postgres_engine, g, prof.other_character_id) is None
    different = save(client_factory, g.o1_user_id, g, prof.character_id, {"expected_row_version": 1, "public_appearance": "z"}, key=key)  # fmt: skip
    assert code(different) == 409


def test_a_release_replays_for_its_own_character_conflicts_for_another_and_checks_authority_first(
    client_factory: Callable[[uuid.UUID], TestClient],
    postgres_engine: Engine,
    g: Gate,
    m: Members,
    prof: Prof,
) -> None:
    for character in (prof.character_id, prof.other_character_id):
        save(client_factory, g.o1_user_id, g, character, {"expected_row_version": None, "public_appearance": APPEARANCE})  # fmt: skip
    key = f"release-{uuid.uuid4().hex[:8]}"
    first = release(client_factory, g.o1_user_id, g, prof.character_id, 1, key=key)
    assert code(first) == 201
    replay = release(client_factory, g.o1_user_id, g, prof.character_id, 1, key=key)
    assert code(replay) == 201
    assert body(replay)["version_number"] == 1
    assert len(release_rows(postgres_engine, g, prof.character_id)) == 1
    # The same key and body on another character: the idempotency conflict, nothing for Y.
    other = release(client_factory, g.o1_user_id, g, prof.other_character_id, 1, key=key)
    assert code(other) == 409 and error_code(other) != "stale_write"
    assert release_rows(postgres_engine, g, prof.other_character_id) == []
    unchanged = read(client_factory, g.o1_user_id, g, prof.other_character_id)
    assert body(unchanged)["releases"] == []
    # Authority is judged before a stored response is returned: a GM who released under a key and
    # then lost the delegation cannot replay it.
    gm_key = f"gm-release-{uuid.uuid4().hex[:8]}"
    assert code(release(client_factory, m.gm_user_id, g, prof.other_character_id, 1, key=gm_key)) == 201  # fmt: skip
    with postgres_engine.begin() as connection:
        revoke_character_reveal_delegation(
            connection,
            campaign_id=g.campaign_id,
            actor_membership_id=g.o1,
            grantee_campaign_membership_id=m.gm,
            reason="Revoked before the retry",
        )
    lost = release(client_factory, m.gm_user_id, g, prof.other_character_id, 1, key=gm_key)
    assert (code(lost), error_code(lost)) == (403, "character_reveal_required")


# --- audit and revisions ----------------------------------------------------------------------


def test_audit_has_one_row_per_real_change_and_never_carries_profile_text(
    client_factory: Callable[[uuid.UUID], TestClient], postgres_engine: Engine, g: Gate, prof: Prof
) -> None:
    c = prof.character_id
    save(client_factory, g.o1_user_id, g, c, {"expected_row_version": None, "public_appearance": APPEARANCE, "public_background": BACKGROUND})  # fmt: skip
    save(client_factory, g.o1_user_id, g, c, {"expected_row_version": 1, "public_appearance": APPEARANCE})  # fmt: skip  # no-op
    release(client_factory, g.o1_user_id, g, c, 1, note="NOTE-MARKER-9921")
    release(client_factory, g.o1_user_id, g, c, 1)  # natural retry: no second row
    save(client_factory, g.player_user_id, g, c, {"expected_row_version": 1})  # refused
    drafts, releases, audit_rows, revisions = counts(postgres_engine, g)
    assert (drafts, releases, audit_rows, revisions) == (1, 1, 2, 0)
    with postgres_engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT command_name, changed_fields, reason FROM audit.change_log "
                "WHERE world_id = :w AND command_name IN ('save_character_public_profile_draft', "
                "'release_character_public_profile') ORDER BY command_name"
            ),
            {"w": g.world_id},
        ).all()
    dump = json.dumps([[r[0], r[1], r[2]] for r in rows], default=str)
    for marker in (APPEARANCE, BACKGROUND, "NOTE-MARKER-9921"):
        assert marker not in dump
    fields = {r[0]: r[1] for r in rows}
    assert fields["release_character_public_profile"]["version_number"] == 1
    assert fields["release_character_public_profile"]["authority_source"] == "owner"
    assert fields["save_character_public_profile_draft"]["row_version"] == 1
    assert sorted(fields["save_character_public_profile_draft"]["changed_field_names"]) == [
        "public_appearance",
        "public_background",
    ]
