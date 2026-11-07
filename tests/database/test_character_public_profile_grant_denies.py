# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""The D8 denies, created through the normal grant routes (P03-A A2a-R, DEF-018).

`POST /campaigns/{id}/resource-grants` accepts a character as an `entity_id` target for a deny of
`campaign.view` (the whole-character deny) or `canon.edit` (the per-character `canon.edit` deny),
and refuses an allow. Every deny in this file is created and lifted through the HTTP routes by an
access manager, never with a raw INSERT; the profile reads, saves, releases and idempotent retries
are then exercised against them, including denies that reach a member through an access group.

The last test writes the raw `allow` rows the application cannot create and records what they do to
the existing readers (nothing), so the deny-only rule is not justified by an assumption.
"""

import re
import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from tests.database.test_campaign_owner_gate import (  # noqa: F401 - fixtures used by name
    Gate,
    client_factory,
    g,
)
from tests.database.test_character_public_profile_api import (  # noqa: F401 - fixtures by name
    APPEARANCE,
    Prof,
    body,
    code,
    counts,
    draft_row,
    error_code,
    make_outsider,
    prof,
    read,
    release,
    release_rows,
    save,
    url,
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

Factory = Callable[[uuid.UUID], TestClient]


# --- helpers ---------------------------------------------------------------------------------------


def post_grant(
    client_factory: Factory,
    user: uuid.UUID,
    g: Gate,
    capability: str,
    target: uuid.UUID,
    *,
    member: uuid.UUID | None = None,
    group: uuid.UUID | None = None,
    effect: str = "deny",
    target_field: str = "entity_id",
    key: str | None = None,
) -> Any:
    request: dict[str, object] = {
        "capability_code": capability,
        "effect": effect,
        target_field: str(target),
    }
    if member is not None:
        request["grantee_campaign_membership_id"] = str(member)
    if group is not None:
        request["grantee_access_group_id"] = str(group)
    headers = {"Idempotency-Key": key} if key else {}
    with client_factory(user) as client:
        return client.post(
            f"/campaigns/{g.campaign_id}/resource-grants", json=request, headers=headers
        )


def deny_via_route(
    client_factory: Factory,
    g: Gate,
    capability: str,
    target: uuid.UUID,
    *,
    member: uuid.UUID | None = None,
    group: uuid.UUID | None = None,
    by: uuid.UUID | None = None,
) -> uuid.UUID:
    response = post_grant(
        client_factory, by or g.o2_user_id, g, capability, target, member=member, group=group
    )
    assert code(response) == 201, body(response)
    return uuid.UUID(body(response)["resource_grant_id"])  # type: ignore[arg-type]


def revoke_via_route(
    client_factory: Factory, g: Gate, grant: uuid.UUID, *, by: uuid.UUID | None = None
) -> None:
    with client_factory(by or g.o2_user_id) as client:
        response = client.post(f"/campaigns/{g.campaign_id}/resource-grants/{grant}/revoke")
    assert response.status_code == 200, response.text


def make_group_via_route(client_factory: Factory, g: Gate, name: str) -> uuid.UUID:
    with client_factory(g.o2_user_id) as client:
        response = client.post(f"/campaigns/{g.campaign_id}/access-groups", json={"name": name})
    assert response.status_code == 201, response.text
    return uuid.UUID(response.json()["access_group_id"])


def add_to_group(
    client_factory: Factory, g: Gate, group: uuid.UUID, member: uuid.UUID
) -> uuid.UUID:
    with client_factory(g.o2_user_id) as client:
        response = client.post(
            f"/campaigns/{g.campaign_id}/access-groups/{group}/members",
            json={"campaign_membership_ids": [str(member)]},
        )
    assert response.status_code == 201, response.text
    return uuid.UUID(response.json()["access_group_membership_ids"][0])


def remove_from_group(client_factory: Factory, g: Gate, group_membership: uuid.UUID) -> None:
    with client_factory(g.o2_user_id) as client:
        response = client.post(
            f"/campaigns/{g.campaign_id}/access-group-memberships/{group_membership}/remove"
        )
    assert response.status_code == 200, response.text


def grant_rows(engine: Engine, g: Gate) -> list[dict[str, object]]:
    with engine.connect() as connection:
        rows = connection.execute(
            text("""
                SELECT resource_grant_id, grantee_campaign_membership_id, grantee_access_group_id,
                       entity_id, character_id, timeline_id, effect, revoked_at IS NULL AS live,
                       (SELECT code FROM security.capabilities c WHERE c.capability_id = rg.capability_id)
                         AS capability
                FROM security.resource_grants rg WHERE campaign_id = :c ORDER BY granted_at
            """),
            {"c": g.campaign_id},
        ).mappings()
        return [dict(row) for row in rows]


def grant_audits(engine: Engine, g: Gate) -> list[dict[str, object]]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT changed_fields FROM audit.change_log WHERE world_id = :w "
                "AND command_name = 'create_resource_grant' ORDER BY change_log_id"
            ),
            {"w": g.world_id},
        ).scalars()
        return [dict(row) for row in rows]


def replayed(replay: object, original: object) -> bool:
    """A stored response replays its ids, numbers and flags (`replay_body` drops free strings such
    as the authority source), so the replay is the original minus those strings."""
    stored = {
        k: v for k, v in body(original).items() if not isinstance(v, str) or k.endswith("_id")
    }
    return body(replay) == stored


def start_profile(client_factory: Factory, g: Gate, character: uuid.UUID) -> None:
    """A draft at version 1 (written by the owner `o1`)."""
    assert code(save(client_factory, g.o1_user_id, g, character, {"expected_row_version": None, "public_appearance": APPEARANCE})) == 201  # fmt: skip


# --- the grant route --------------------------------------------------------------------------------


def test_the_grant_route_creates_both_denies_and_refuses_allows_and_wrong_targets(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, prof: Prof
) -> None:
    c = prof.character_id
    whole = post_grant(client_factory, g.o2_user_id, g, "campaign.view", c, member=m.gm)
    assert code(whole) == 201, body(whole)
    edit = post_grant(client_factory, g.o2_user_id, g, "canon.edit", c, member=m.gm)
    assert code(edit) == 201, body(edit)
    rows = grant_rows(postgres_engine, g)
    assert {(r["capability"], r["effect"], r["live"]) for r in rows} == {
        ("campaign.view", "deny", True),
        ("canon.edit", "deny", True),
    }
    assert all(
        r["entity_id"] == c and r["character_id"] is None and r["timeline_id"] is None
        and r["grantee_campaign_membership_id"] == m.gm
        for r in rows
    )  # fmt: skip
    audits = grant_audits(postgres_engine, g)
    assert len(audits) == 2
    assert {a["capability_code"] for a in audits} == {"campaign.view", "canon.edit"}
    assert all(a["target_kind"] == "entity_id" and a["effect"] == "deny" for a in audits)
    assert all(a["target_id"] == str(c) for a in audits)

    # Refusals write nothing and are the same non-disclosing 404.
    before = (len(grant_rows(postgres_engine, g)), len(grant_audits(postgres_engine, g)))
    refused = {
        "allow campaign.view": post_grant(client_factory, g.o2_user_id, g, "campaign.view", c, member=m.ast, effect="allow"),  # noqa: E501
        "allow canon.edit": post_grant(client_factory, g.o2_user_id, g, "canon.edit", c, member=m.ast, effect="allow"),  # noqa: E501
        "character.* deny under entity_id": post_grant(client_factory, g.o2_user_id, g, "character.view_full", c, member=m.ast),  # noqa: E501
        "campaign.view deny under character_id": post_grant(client_factory, g.o2_user_id, g, "campaign.view", c, member=m.ast, target_field="character_id"),  # noqa: E501
        "canon.edit deny under character_id": post_grant(client_factory, g.o2_user_id, g, "canon.edit", c, member=m.ast, target_field="character_id"),  # noqa: E501
    }  # fmt: skip
    for name, response in refused.items():
        assert code(response) == 404, (name, body(response))
    assert (len(grant_rows(postgres_engine, g)), len(grant_audits(postgres_engine, g))) == before
    # A player cannot create one; the route filter is access.manage.
    assert code(post_grant(client_factory, g.player_user_id, g, "campaign.view", c, member=m.ast)) == 403  # fmt: skip


def test_the_grant_route_replays_a_key_and_refuses_a_duplicate(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, prof: Prof
) -> None:
    c = prof.character_id
    key = f"deny-{uuid.uuid4().hex[:8]}"
    first = post_grant(client_factory, g.o2_user_id, g, "campaign.view", c, member=m.gm, key=key)
    assert code(first) == 201
    replay = post_grant(client_factory, g.o2_user_id, g, "campaign.view", c, member=m.gm, key=key)
    assert code(replay) == 201 and body(replay) == body(first)
    assert len(grant_rows(postgres_engine, g)) == 1 and len(grant_audits(postgres_engine, g)) == 1
    other_body = post_grant(client_factory, g.o2_user_id, g, "canon.edit", c, member=m.gm, key=key)
    assert code(other_body) == 409
    duplicate = post_grant(client_factory, g.o2_user_id, g, "campaign.view", c, member=m.gm)
    assert code(duplicate) == 409
    assert len(grant_rows(postgres_engine, g)) == 1


def test_the_grant_route_refuses_an_archived_character_a_foreign_world_and_other_own_column_kinds(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, prof: Prof
) -> None:
    with postgres_engine.begin() as connection:
        archived = make_character(connection, g.world_id, name="Archived Target")
        connection.execute(
            text(
                "UPDATE core.entities SET lifecycle_status_id = "
                "(SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'archived') "
                "WHERE entity_id = :e"
            ),
            {"e": archived},
        )
        foreign_world = make_world(connection, slug=f"deny-foreign-{uuid.uuid4().hex[:8]}")
        foreign = make_character(connection, foreign_world, name="Foreign Target")
    try:
        for target in (archived, foreign, uuid.uuid4()):
            response = post_grant(
                client_factory, g.o2_user_id, g, "campaign.view", target, member=m.gm
            )  # noqa: E501
            assert code(response) == 404
        assert grant_rows(postgres_engine, g) == []
    finally:
        with postgres_engine.begin() as connection:
            connection.execute(text("SET LOCAL session_replication_role = replica"))
            connection.execute(
                text("DELETE FROM core.entities WHERE world_id = :w"), {"w": foreign_world}
            )  # noqa: E501
            connection.execute(
                text("DELETE FROM core.worlds WHERE world_id = :w"), {"w": foreign_world}
            )  # noqa: E501


# --- the whole-character deny -------------------------------------------------------------------------


def test_a_whole_character_deny_on_an_owner_blocks_every_profile_route_and_every_retry(
    client_factory: Factory, postgres_engine: Engine, g: Gate, prof: Prof
) -> None:
    c = prof.character_id
    start_profile(client_factory, g, c)
    key = f"release-{uuid.uuid4().hex[:8]}"
    first = release(client_factory, g.o1_user_id, g, c, 1, key=key)
    assert code(first) == 201
    grant = deny_via_route(client_factory, g, "campaign.view", c, member=g.o1)  # o2 denies o1
    before = counts(postgres_engine, g)
    blocked = {
        "read": read(client_factory, g.o1_user_id, g, c),
        "read release": read(client_factory, g.o1_user_id, g, c, "/releases/1"),
        "save": save(
            client_factory,
            g.o1_user_id,
            g,
            c,
            {"expected_row_version": 1, "public_appearance": "x"},
        ),  # noqa: E501
        "release": release(client_factory, g.o1_user_id, g, c, 1),
        "keyed release retry": release(client_factory, g.o1_user_id, g, c, 1, key=key),
    }
    for name, response in blocked.items():
        assert code(response) == 404, (name, body(response))
    assert counts(postgres_engine, g) == before
    assert code(read(client_factory, g.o2_user_id, g, c)) == 200  # the manager is not denied
    # Lifting it restores everything, and the earlier key replays its stored response.
    revoke_via_route(client_factory, g, grant)
    assert code(read(client_factory, g.o1_user_id, g, c)) == 200
    replay = release(client_factory, g.o1_user_id, g, c, 1, key=key)
    assert code(replay) == 201 and replayed(replay, first)
    assert len(release_rows(postgres_engine, g, c)) == 1
    assert code(save(client_factory, g.o1_user_id, g, c, {"expected_row_version": 1, "public_appearance": "again"})) == 200  # fmt: skip
    assert code(release(client_factory, g.o1_user_id, g, c, 2)) == 201


def test_a_whole_character_deny_binds_a_delegated_gm_and_an_owner_who_denies_themselves(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, prof: Prof
) -> None:
    c = prof.character_id
    start_profile(client_factory, g, c)
    gm_grant = deny_via_route(client_factory, g, "campaign.view", c, member=m.gm)
    for response in (
        read(client_factory, m.gm_user_id, g, c),
        save(
            client_factory,
            m.gm_user_id,
            g,
            c,
            {"expected_row_version": 1, "public_appearance": "x"},
        ),  # noqa: E501
        release(client_factory, m.gm_user_id, g, c, 1),
    ):
        assert code(response) == 404
    assert release_rows(postgres_engine, g, c) == []
    revoke_via_route(client_factory, g, gm_grant)
    assert code(release(client_factory, m.gm_user_id, g, c, 1)) == 201
    # An owner may deny themselves, and a denied owner keeps access.manage, so can lift it again.
    own = deny_via_route(client_factory, g, "campaign.view", c, member=g.o1, by=g.o1_user_id)
    assert code(read(client_factory, g.o1_user_id, g, c)) == 404
    revoke_via_route(client_factory, g, own, by=g.o1_user_id)
    assert code(read(client_factory, g.o1_user_id, g, c)) == 200


# --- the canon.edit deny ----------------------------------------------------------------------------------


def test_a_canon_edit_deny_on_an_owner_blocks_saving_not_reading_or_releasing(
    client_factory: Factory, postgres_engine: Engine, g: Gate, prof: Prof
) -> None:
    c = prof.character_id
    start_profile(client_factory, g, c)
    save_key = f"save-{uuid.uuid4().hex[:8]}"
    saved = save(client_factory, g.o1_user_id, g, c, {"expected_row_version": 1, "public_appearance": "two"}, key=save_key)  # fmt: skip
    assert code(saved) == 200
    grant = deny_via_route(client_factory, g, "canon.edit", c, member=g.o1)
    view = read(client_factory, g.o1_user_id, g, c)
    assert code(view) == 200
    assert body(view)["can_edit"] is False and body(view)["can_release"] is True
    before = counts(postgres_engine, g)
    refused = save(client_factory, g.o1_user_id, g, c, {"expected_row_version": 2, "public_appearance": "three"})  # fmt: skip
    assert (code(refused), error_code(refused)) == (403, "public_profile_edit_denied")
    retried = save(client_factory, g.o1_user_id, g, c, {"expected_row_version": 1, "public_appearance": "two"}, key=save_key)  # fmt: skip
    assert (code(retried), error_code(retried)) == (403, "public_profile_edit_denied")
    assert counts(postgres_engine, g) == before
    assert draft_row(postgres_engine, g, c)["row_version"] == 2  # type: ignore[index]
    assert code(release(client_factory, g.o1_user_id, g, c, 2)) == 201  # a different operation
    revoke_via_route(client_factory, g, grant)
    replay = save(client_factory, g.o1_user_id, g, c, {"expected_row_version": 1, "public_appearance": "two"}, key=save_key)  # fmt: skip
    assert code(replay) == 200 and body(replay)["row_version"] == 2


def test_a_canon_edit_deny_on_an_assistant_gm_leaves_them_nothing_to_read(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, prof: Prof
) -> None:
    c = prof.character_id
    start_profile(client_factory, g, c)
    deny_via_route(client_factory, g, "canon.edit", c, member=m.ast)
    before = counts(postgres_engine, g)
    assert code(read(client_factory, m.ast_user_id, g, c)) == 404
    assert (
        code(
            save(
                client_factory,
                m.ast_user_id,
                g,
                c,
                {"expected_row_version": 1, "public_appearance": "x"},
            )
        )
        == 404
    )  # noqa: E501
    assert counts(postgres_engine, g) == before


# --- isolation and the readers that already honour the key ------------------------------------------------------


def test_a_deny_is_campaign_scoped_and_character_detail_honours_the_same_key(
    client_factory: Factory, postgres_engine: Engine, g: Gate, prof: Prof
) -> None:
    c = prof.character_id
    with postgres_engine.begin() as connection:
        other_campaign = make_campaign(connection, g.timeline_id, "Deny Campaign B")
        b_owner = make_user(connection, "Deny B Owner")
        b_membership = make_campaign_membership(connection, other_campaign, b_owner)
        make_membership_role(connection, b_membership, g.owner_role_id)
    try:
        deny_via_route(client_factory, g, "campaign.view", c, member=g.o1)
        detail = f"/campaigns/{g.campaign_id}/characters/{c}"
        with client_factory(g.o1_user_id) as client:
            assert client.get(detail).status_code == 404  # the key an existing reader honours
        with client_factory(g.o2_user_id) as client:
            assert client.get(detail).status_code == 200
        # Campaign B is unaffected: its owner drafts and releases the same character.
        base = f"/campaigns/{other_campaign}/characters/{c}/public-profile"
        with client_factory(b_owner) as client:
            created = client.post(
                base + "/draft", json={"expected_row_version": None, "public_appearance": "B"}
            )  # noqa: E501
            assert created.status_code == 201, created.text
            assert client.get(base).status_code == 200
            released = client.post(base + "/releases", json={"expected_draft_row_version": 1})
            assert released.status_code == 201, released.text
    finally:
        with postgres_engine.begin() as connection:
            connection.execute(text("SET LOCAL session_replication_role = replica"))
            for table in (
                "campaign.character_public_profile_releases",
                "campaign.character_public_profiles",
            ):
                connection.execute(
                    text(f"DELETE FROM {table} WHERE campaign_id = :c"),  # noqa: S608
                    {"c": other_campaign},
                )
            connection.execute(
                text("DELETE FROM security.membership_roles WHERE campaign_membership_id = :m"),
                {"m": b_membership},
            )
            connection.execute(
                text("DELETE FROM security.campaign_memberships WHERE campaign_id = :c"),
                {"c": other_campaign},
            )
            connection.execute(
                text("DELETE FROM campaign.campaigns WHERE campaign_id = :c"), {"c": other_campaign}
            )


# --- explanations --------------------------------------------------------------------------------------------------


def test_the_overview_and_the_effective_access_explanation_name_the_denied_character(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, prof: Prof
) -> None:
    c = prof.character_id
    group = make_group_via_route(client_factory, g, "Explained Group")
    deny_via_route(client_factory, g, "campaign.view", c, member=m.gm)
    deny_via_route(client_factory, g, "canon.edit", c, member=m.gm)
    deny_via_route(client_factory, g, "campaign.view", c, group=group)
    with postgres_engine.begin() as connection:
        location = make_entity(
            connection,
            g.world_id,
            lookup_id(connection, "core", "entity_types", "entity_type_id", "location"),
            name="Plain Place",
        )
    deny_via_route(client_factory, g, "campaign.view", location, member=m.gm)

    with client_factory(g.o2_user_id) as client:
        overview = client.get(f"/campaigns/{g.campaign_id}/access-overview").json()
        effective = client.get(f"/campaigns/{g.campaign_id}/members/{m.gm}/effective-access").json()
    gm_row = next(row for row in overview["members"] if row["campaign_membership_id"] == str(m.gm))
    entity_grants = [x for x in gm_row["grants"] if x["target_type"] == "entity"]
    named = {x["capability_code"]: x for x in entity_grants if x["target_id"] == str(c)}
    assert set(named) == {"campaign.view", "canon.edit"}
    assert all(
        x["target_display_name"] == "Profile Subject" and x["effect"] == "deny"
        for x in named.values()
    )  # noqa: E501
    place = next(x for x in entity_grants if x["target_id"] == str(location))
    assert place["target_display_name"] is None  # a non-character entity target is still unnamed
    group_row = next(
        row for row in overview["access_groups"] if row["access_group_id"] == str(group)
    )  # noqa: E501
    assert [
        (x["capability_code"], x["target_type"], x["target_display_name"])
        for x in group_row["grants"]
    ] == [  # noqa: E501
        ("campaign.view", "entity", "Profile Subject")
    ]
    denials = {
        (d["capability_code"], d["target_type"], d["target_display_name"])
        for d in effective["denials"]
    }  # noqa: E501
    assert ("campaign.view", "entity", "Profile Subject") in denials
    assert ("canon.edit", "entity", "Profile Subject") in denials
    assert ("campaign.view", "entity", None) in denials  # the plain place


# --- access groups --------------------------------------------------------------------------------------------------


def test_a_group_deny_follows_membership_changes_on_the_next_request(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, prof: Prof
) -> None:
    c = prof.character_id
    start_profile(client_factory, g, c)
    key = f"gm-release-{uuid.uuid4().hex[:8]}"
    first = release(client_factory, m.gm_user_id, g, c, 1, key=key)
    assert code(first) == 201
    group = make_group_via_route(client_factory, g, "Denied Group")
    deny_via_route(client_factory, g, "campaign.view", c, group=group)
    assert code(read(client_factory, m.gm_user_id, g, c)) == 200  # outside the group: unaffected
    group_membership = add_to_group(client_factory, g, group, m.gm)
    before = counts(postgres_engine, g)
    for response in (
        read(client_factory, m.gm_user_id, g, c),
        save(
            client_factory,
            m.gm_user_id,
            g,
            c,
            {"expected_row_version": 1, "public_appearance": "x"},
        ),  # noqa: E501
        release(client_factory, m.gm_user_id, g, c, 1),
        release(client_factory, m.gm_user_id, g, c, 1, key=key),
    ):
        assert code(response) == 404
    assert counts(postgres_engine, g) == before
    remove_from_group(client_factory, g, group_membership)
    assert code(read(client_factory, m.gm_user_id, g, c)) == 200
    replay = release(client_factory, m.gm_user_id, g, c, 1, key=key)
    assert code(replay) == 201 and replayed(replay, first)
    save(client_factory, g.o1_user_id, g, c, {"expected_row_version": 1, "public_appearance": "next"})  # fmt: skip
    assert code(release(client_factory, m.gm_user_id, g, c, 2)) == 201


def test_deactivating_a_denying_group_lifts_it_and_reactivating_does_not_restore_it(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, prof: Prof
) -> None:
    c = prof.character_id
    start_profile(client_factory, g, c)
    group = make_group_via_route(client_factory, g, "Deactivated Group")
    deny_via_route(client_factory, g, "campaign.view", c, group=group)
    add_to_group(client_factory, g, group, m.gm)
    assert code(read(client_factory, m.gm_user_id, g, c)) == 404
    with client_factory(g.o2_user_id) as client:
        off = client.post(f"/campaigns/{g.campaign_id}/access-groups/{group}/deactivate")
        assert off.status_code == 200, off.text
    assert code(read(client_factory, m.gm_user_id, g, c)) == 200  # the group's grants are revoked
    with client_factory(g.o2_user_id) as client:
        on = client.post(f"/campaigns/{g.campaign_id}/access-groups/{group}/reactivate")
        assert on.status_code == 200, on.text
    assert code(read(client_factory, m.gm_user_id, g, c)) == 200  # reactivation restores nothing
    deny_via_route(client_factory, g, "campaign.view", c, group=group)  # a new grant does...
    add_to_group(client_factory, g, group, m.gm)  # ...for a member added again
    assert code(read(client_factory, m.gm_user_id, g, c)) == 404


def test_a_group_canon_edit_deny_blocks_saving_for_an_owner_added_to_it(
    client_factory: Factory, postgres_engine: Engine, g: Gate, prof: Prof
) -> None:
    c = prof.character_id
    start_profile(client_factory, g, c)
    group = make_group_via_route(client_factory, g, "Edit Denied Group")
    deny_via_route(client_factory, g, "canon.edit", c, group=group)
    group_membership = add_to_group(client_factory, g, group, g.o1)
    refused = save(client_factory, g.o1_user_id, g, c, {"expected_row_version": 1, "public_appearance": "x"})  # fmt: skip
    assert (code(refused), error_code(refused)) == (403, "public_profile_edit_denied")
    assert code(release(client_factory, g.o1_user_id, g, c, 1)) == 201
    remove_from_group(client_factory, g, group_membership)
    assert code(save(client_factory, g.o1_user_id, g, c, {"expected_row_version": 1, "public_appearance": "x"})) == 200  # fmt: skip


# --- existing raw allow rows --------------------------------------------------------------------------------------------


def _snapshot(
    client_factory: Factory, g: Gate, c: uuid.UUID, user: uuid.UUID
) -> dict[str, tuple[int, str]]:
    paths = {
        "profile": url(g, c),
        "detail": f"/campaigns/{g.campaign_id}/characters/{c}",
        "sheet": f"/campaigns/{g.campaign_id}/characters/{c}/sheet",
        "inventory": f"/campaigns/{g.campaign_id}/characters/{c}/inventory",
        "relationships": f"/campaigns/{g.campaign_id}/characters/{c}/relationships",
        "parties": f"/campaigns/{g.campaign_id}/characters/{c}/parties",
        "search": f"/campaigns/{g.campaign_id}/world/search?q=Profile&limit=50",
        "counts": f"/campaigns/{g.campaign_id}/world/search/counts?q=Profile",
    }
    result: dict[str, tuple[int, str]] = {}
    with client_factory(user) as client:
        for name, path in paths.items():
            response = client.get(path)
            # The correlation id is per request; everything else must match exactly.
            result[name] = (
                response.status_code,
                re.sub(r'"correlation_id":"[^"]*"', '"correlation_id":"-"', response.text),
            )
    return result


def test_raw_allow_rows_under_entity_id_change_no_current_reader(
    client_factory: Factory, postgres_engine: Engine, g: Gate, prof: Prof
) -> None:
    """The application cannot create these rows (and now still cannot); rows written directly
    before the guard existed, or by SQL, are measured here rather than assumed inert. For a member
    who lacks the role capability and for one who holds it, an `allow` of `campaign.view` or
    `canon.edit` under `entity_id` on a character leaves every response byte-for-byte unchanged:
    no reader consults an entity-keyed allow for a character, the profile edit rule ignores allows
    (D8 item 2), and `campaign.view` is already held through the role by every route."""
    c = prof.character_id
    start_profile(client_factory, g, c)
    subjects = {"player": (g.player_user_id, g.player), "owner": (g.o2_user_id, g.o2)}
    before = {name: _snapshot(client_factory, g, c, user) for name, (user, _m) in subjects.items()}
    with postgres_engine.begin() as connection:
        for _name, (_user, membership) in subjects.items():
            for capability in ("campaign.view", "canon.edit"):
                make_resource_grant(
                    connection,
                    g.campaign_id,
                    lookup_id(connection, "security", "capabilities", "capability_id", capability),
                    timeline_id=g.timeline_id,
                    grantee_campaign_membership_id=membership,
                    entity_id=c,
                    effect="allow",
                )
    after = {name: _snapshot(client_factory, g, c, user) for name, (user, _m) in subjects.items()}
    assert after == before
    # And a raw allow of canon.edit still confers neither editing nor reading on the player.
    assert before["player"]["profile"][0] == 404
    refused = save(client_factory, g.player_user_id, g, c, {"expected_row_version": 1, "public_appearance": "p"})  # fmt: skip
    assert code(refused) == 403
