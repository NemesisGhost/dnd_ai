# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""P15-C02 checkpoint integration: scripted cross-slice cases over real HTTP routes.

Each slice of C02 (S01 draft/release, S02 revelations, S03 reveal delegations, S04 character denies)
has its own cases. These tests chain them the way the checkpoint's acceptance text does, with every
write made through the public route (never a command call or a seeded row) so that what one slice
writes is what the next slice's reads and writes see:

- the owner grants reveal authority through `POST /reveal-delegations`, that GM's *next* reveal and
  release succeed, a delegated GM cannot redelegate, and after the owner revokes (or the GM's role
  ends) the GM's next reveal is refused;
- a character deny, made and lifted through the resource-grant routes, has the documented effect on
  an owner, a delegated GM, an editor with no reveal authority and a revealed-to player, for a member
  source and a group source, and revoking one source leaves the others.

They are scripted checks on a disposable database. They are not browser, assistive-technology, human or
owner evidence, and they establish nothing about the portal's rendering.
"""

import uuid
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from dnd_ai.commands.character_public_profile import (
    release_character_public_profile,
    save_character_public_profile_draft,
)
from dnd_ai.commands.memberships import revoke_membership_role
from tests.database.test_campaign_owner_gate import (  # noqa: F401 - fixtures used by name
    Gate,
    client_factory,
    g,
)
from tests.database.test_character_public_profile_api import (
    body,
    code,
    error_code,
    read,
    release,
    save,
)
from tests.database.test_character_public_profile_grant_denies import (
    add_to_group,
    deny_via_route,
    make_group_via_route,
    remove_from_group,
    revoke_via_route,
)
from tests.database.test_character_reveal_delegation import (  # noqa: F401 - fixtures used by name
    Members,
    m,
)
from tests.database.test_character_revelations import (
    create,
    listing,
    member_body,
    revelations,
    revoke,
)
from tests.factories import make_character
from tests.r01_support import fixture_plan

pytestmark = pytest.mark.database

Factory = Callable[[uuid.UUID], TestClient]


@pytest.fixture
def subject(postgres_engine: Engine, g: Gate, m: Members) -> uuid.UUID:
    """A character with a released public profile and no reveal delegation for anyone."""
    with postgres_engine.begin() as connection:
        character = make_character(connection, g.world_id, name="Checkpoint Subject")
        save_character_public_profile_draft(
            connection,
            campaign_id=g.campaign_id,
            character_id=character,
            actor_user_id=g.o1_user_id,
            expected_row_version=None,
            fields={"public_appearance": "A weathered face"},
            plan=fixture_plan(connection, g.campaign_id),
        )
    with postgres_engine.begin() as connection:
        release_character_public_profile(
            connection,
            campaign_id=g.campaign_id,
            character_id=character,
            actor_membership_id=g.o1,
            expected_draft_row_version=1,
            release_note=None,
            plan=fixture_plan(connection, g.campaign_id),
        )
    return character


def grant(factory: Factory, g: Gate, who: uuid.UUID, by: uuid.UUID | None = None) -> Any:
    with factory(by or g.o1_user_id) as client:
        return client.post(
            f"/campaigns/{g.campaign_id}/reveal-delegations",
            json={"grantee_campaign_membership_id": str(who), "reason": "Runs the reveals"},
        )


def revoke_delegation(
    factory: Factory, g: Gate, who: uuid.UUID, by: uuid.UUID | None = None
) -> Any:
    with factory(by or g.o1_user_id) as client:
        return client.post(
            f"/campaigns/{g.campaign_id}/reveal-delegations/{who}/revoke",
            json={"reason": "Handed back"},
        )


def detail(factory: Factory, user: uuid.UUID, g: Gate, character: uuid.UUID) -> int:
    with factory(user) as client:
        return int(client.get(f"/campaigns/{g.campaign_id}/characters/{character}").status_code)


def next_draft(factory: Factory, g: Gate, character: uuid.UUID, version: int, text_: str) -> int:
    response = save(
        factory,
        g.o1_user_id,
        g,
        character,
        {"expected_row_version": version, "public_appearance": text_},
    )
    assert code(response) == 200, body(response)
    return version + 1


# --- owner grants reveal authority, then that GM's next reveal -------------------------------------------------------


def test_the_owner_grants_reveal_authority_and_that_gms_next_reveal_succeeds_until_revoked(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, subject: uuid.UUID
) -> None:
    c = subject
    # Before any grant the GM can read and edit the draft but neither reveal nor release.
    assert listing(client_factory, m.gm_user_id, g, c).json()["can_reveal"] is False
    before = read(client_factory, m.gm_user_id, g, c)
    assert code(before) == 200 and body(before)["can_edit"] is True
    assert body(before)["can_release"] is False
    refused = create(client_factory, m.gm_user_id, g, c, member_body(g.player))
    assert refused.status_code == 403, refused.text
    assert revelations(postgres_engine, g, c) == []
    version = next_draft(client_factory, g, c, 1, "Changed once")
    assert code(release(client_factory, m.gm_user_id, g, c, version)) == 403

    # The owner grants through the route; the GM's next calls succeed.
    granted = grant(client_factory, g, m.gm)
    assert granted.status_code == 200 and granted.json()["granted"] is True, granted.text
    assert listing(client_factory, m.gm_user_id, g, c).json()["can_reveal"] is True
    revealed = create(client_factory, m.gm_user_id, g, c, member_body(g.player))
    assert revealed.status_code == 201, revealed.text
    assert code(release(client_factory, m.gm_user_id, g, c, version)) == 201
    rows = revelations(postgres_engine, g, c)
    assert len(rows) == 1 and rows[0]["authority_source_code"] == "delegation"
    assert rows[0]["created_by_membership_id"] == m.gm and rows[0]["ended_at"] is None
    assert detail(client_factory, g.player_user_id, g, c) == 200  # the revealed-to player

    # A delegated GM cannot redelegate; the assistant has no standing to receive from them either.
    assert grant(client_factory, g, m.ast, by=m.gm_user_id).status_code == 403

    # The owner revokes: the GM's next reveal and release are refused, the earlier revelation stands.
    revoked = revoke_delegation(client_factory, g, m.gm)
    assert revoked.status_code == 200 and revoked.json()["revoked"] is True, revoked.text
    assert listing(client_factory, m.gm_user_id, g, c).json()["can_reveal"] is False
    version = next_draft(client_factory, g, c, version, "Changed twice")
    again = create(client_factory, m.gm_user_id, g, c, member_body(m.ast))
    assert again.status_code == 403, again.text
    assert code(release(client_factory, m.gm_user_id, g, c, version)) == 403
    rows = revelations(postgres_engine, g, c)
    assert len(rows) == 1 and rows[0]["ended_at"] is None
    # Only an owner revokes what remains; the GM, no longer delegated, cannot.
    assert (
        revoke(client_factory, m.gm_user_id, g, c, rows[0]["character_revelation_id"]).status_code
        == 403
    )
    ended = revoke(client_factory, g.o1_user_id, g, c, rows[0]["character_revelation_id"])
    assert ended.status_code == 200, ended.text
    assert detail(client_factory, g.player_user_id, g, c) == 404


def test_a_delegation_ends_with_the_gm_role_and_the_next_reveal_is_refused(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, subject: uuid.UUID
) -> None:
    c = subject
    assert grant(client_factory, g, m.gm).status_code == 200
    assert create(client_factory, m.gm_user_id, g, c, member_body(g.player)).status_code == 201
    with postgres_engine.begin() as connection:
        revoke_membership_role(
            connection,
            membership_role_id=m.gm_role,
            campaign_id=g.campaign_id,
        )
    after = create(client_factory, m.gm_user_id, g, c, member_body(m.ast))
    assert after.status_code in (403, 404), after.text
    # A regrant needs a live built-in GM assignment, which the member no longer has.
    assert grant(client_factory, g, m.gm).status_code in (403, 404, 409, 422)
    assert [r["ended_at"] is None for r in revelations(postgres_engine, g, c)] == [True]


def test_a_stale_owner_and_a_non_owner_cannot_grant_or_revoke(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, subject: uuid.UUID
) -> None:
    for caller in (m.ast_user_id, m.lookalike_user_id, g.manager_user_id, g.player_user_id):
        assert grant(client_factory, g, m.gm, by=caller).status_code == 403
    assert grant(client_factory, g, m.gm).status_code == 200
    for caller in (m.ast_user_id, g.manager_user_id, g.player_user_id):
        assert revoke_delegation(client_factory, g, m.gm, by=caller).status_code == 403
    assert listing(client_factory, m.gm_user_id, g, subject).json()["can_reveal"] is True


# --- character denies across personas and access sources -------------------------------------------------------------


def test_character_denies_and_their_revocation_across_personas_and_sources(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, subject: uuid.UUID
) -> None:
    c = subject
    assert grant(client_factory, g, m.gm).status_code == 200
    assert create(client_factory, m.gm_user_id, g, c, member_body(g.player)).status_code == 201
    group = make_group_via_route(client_factory, g, "Checkpoint Group")
    membership = add_to_group(client_factory, g, group, g.player)

    def view(user: uuid.UUID) -> int:
        return code(read(client_factory, user, g, c))

    # Baseline: owner, delegated GM and editor read; the revealed-to player has the public view.
    assert [view(u) for u in (g.o1_user_id, m.gm_user_id, m.ast_user_id)] == [200, 200, 200]
    assert detail(client_factory, g.player_user_id, g, c) == 200

    # Edit-only deny on the delegated GM: edit gone, reveal and release stay (S04 + S03).
    edit_deny = deny_via_route(client_factory, g, "canon.edit", c, member=m.gm)
    profile = read(client_factory, m.gm_user_id, g, c)
    assert code(profile) == 200 and body(profile)["can_edit"] is False
    assert body(profile)["can_release"] is True
    saved = save(
        client_factory, m.gm_user_id, g, c, {"expected_row_version": 1, "public_appearance": "x"}
    )
    assert (code(saved), error_code(saved)) == (403, "public_profile_edit_denied")
    assert listing(client_factory, m.gm_user_id, g, c).json()["can_reveal"] is True
    assert create(client_factory, m.gm_user_id, g, c, member_body(m.ast)).status_code == 201

    # Whole-character deny, member source, on the delegated GM: the character is gone for them only.
    whole = deny_via_route(client_factory, g, "campaign.view", c, member=m.gm)
    assert view(m.gm_user_id) == 404 and detail(client_factory, m.gm_user_id, g, c) == 404
    assert listing(client_factory, m.gm_user_id, g, c).status_code == 404
    assert create(client_factory, m.gm_user_id, g, c, member_body(g.player)).status_code == 404
    assert view(g.o1_user_id) == 200 and view(m.ast_user_id) == 200

    # Group-source whole-character deny names the revealed-to player through membership.
    group_deny = deny_via_route(client_factory, g, "campaign.view", c, group=group)
    assert detail(client_factory, g.player_user_id, g, c) == 404
    # Revoking the member deny leaves the group one in force for the player and lifts the GM's view deny.
    revoke_via_route(client_factory, g, whole)
    assert view(m.gm_user_id) == 200
    assert detail(client_factory, g.player_user_id, g, c) == 404
    # The group deny follows membership: removal lifts it, re-adding restores it.
    remove_from_group(client_factory, g, membership)
    assert detail(client_factory, g.player_user_id, g, c) == 200
    membership = add_to_group(client_factory, g, group, g.player)
    assert detail(client_factory, g.player_user_id, g, c) == 404
    revoke_via_route(client_factory, g, group_deny)
    assert detail(client_factory, g.player_user_id, g, c) == 200

    # The remaining edit-only deny is what the explanation still names; lifting it restores editing.
    with client_factory(g.o1_user_id) as client:
        effective = client.get(f"/campaigns/{g.campaign_id}/members/{m.gm}/effective-access").json()
    assert ("canon.edit", "entity") in {
        (d["capability_code"], d["target_type"]) for d in effective["denials"]
    }
    assert ("campaign.view", "entity") not in {
        (d["capability_code"], d["target_type"]) for d in effective["denials"]
    }
    revoke_via_route(client_factory, g, edit_deny)
    assert body(read(client_factory, m.gm_user_id, g, c))["can_edit"] is True
    with client_factory(g.o1_user_id) as client:
        effective = client.get(f"/campaigns/{g.campaign_id}/members/{m.gm}/effective-access").json()
    assert not [d for d in effective["denials"] if d["target_type"] == "entity"]
    # The delegation was never touched by any of it.
    assert listing(client_factory, m.gm_user_id, g, c).json()["can_reveal"] is True


def test_a_self_deny_is_removable_by_an_owner_and_names_nobody_else(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, subject: uuid.UUID
) -> None:
    c = subject
    own = deny_via_route(client_factory, g, "campaign.view", c, member=g.o2, by=g.o2_user_id)
    assert code(read(client_factory, g.o2_user_id, g, c)) == 404
    assert code(read(client_factory, g.o1_user_id, g, c)) == 200
    # The denied owner can still manage access, so they can lift their own deny.
    revoke_via_route(client_factory, g, own, by=g.o2_user_id)
    assert code(read(client_factory, g.o2_user_id, g, c)) == 200


def test_a_player_without_a_revelation_sees_nothing_new(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, subject: uuid.UUID
) -> None:
    c = subject
    assert detail(client_factory, g.player_user_id, g, c) == 404
    assert code(read(client_factory, g.player_user_id, g, c)) in (403, 404)
    assert listing(client_factory, g.player_user_id, g, c).status_code in (403, 404)
    deny_via_route(client_factory, g, "canon.edit", c, member=g.player)
    assert detail(client_factory, g.player_user_id, g, c) == 404
