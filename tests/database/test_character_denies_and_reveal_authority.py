# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""P15-C02-S04: the two character denies against reveal authority (cases BD6 to BD9 of the plan).

S03's `GET /campaigns/{id}/reveal-delegations` and the S04 denies meet here for the first time. Every
deny is created and lifted through `POST /campaigns/{id}/resource-grants` and its revoke route, and
every read and write is real HTTP, so the portal's copy ("editing only" versus "everything") is pinned
to what the server does:

- the `canon.edit` deny stops saving, hides the player's own profile and (for a GM with no reveal
  authority) the public profile, but not reading, releasing or revealing for a reveal holder;
- the whole-character deny removes the character for everyone it names, delegated GMs included, and
  does not revoke a delegation;
- the DEF-016 limit stands: neither deny changes character detail for a GM who holds the role.
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
    deny_via_route,
    revoke_via_route,
)
from tests.database.test_character_reveal_delegation import (  # noqa: F401 - fixtures used by name
    Members,
    m,
)
from tests.database.test_character_revelations import (  # noqa: F401 - fixtures used by name
    Rev,
    create,
    listing,
    member_body,
    rev,
)
from tests.factories import make_character
from tests.player_profile_support import markers, seed_player_profile
from tests.r01_support import fixture_plan

pytestmark = pytest.mark.database

Factory = Callable[[uuid.UUID], TestClient]


def delegations(factory: Factory, user: uuid.UUID, g: Gate) -> Any:
    with factory(user) as client:
        return client.get(f"/campaigns/{g.campaign_id}/reveal-delegations")


def delegated(factory: Factory, g: Gate, who: uuid.UUID) -> bool:
    """Whether the S03 read lists `who` as holding an effective delegation."""
    response = delegations(factory, g.o1_user_id, g)
    assert code(response) == 200, response.text
    member = next(m for m in response.json()["members"] if m["campaign_membership_id"] == str(who))
    return member["delegation"] is not None


def detail(factory: Factory, user: uuid.UUID, g: Gate, character: uuid.UUID) -> Any:
    with factory(user) as client:
        return client.get(f"/campaigns/{g.campaign_id}/characters/{character}")


def player_profile(factory: Factory, user: uuid.UUID, g: Gate, character: uuid.UUID) -> Any:
    with factory(user) as client:
        return client.get(f"/campaigns/{g.campaign_id}/characters/{character}/player-profile")


def a_new_draft_version(factory: Factory, g: Gate, character: uuid.UUID, version: int) -> int:
    """The owner saves another draft, so a release is a new snapshot (a retry would be a 200)."""
    response = save(
        factory,
        g.o1_user_id,
        g,
        character,
        {"expected_row_version": version, "public_appearance": f"Changed {version}"},
    )
    assert code(response) == 200, body(response)
    return version + 1


def another_released_character(engine: Engine, g: Gate, name: str) -> uuid.UUID:
    with engine.begin() as connection:
        character = make_character(connection, g.world_id, name=name)
        save_character_public_profile_draft(
            connection,
            campaign_id=g.campaign_id,
            character_id=character,
            actor_user_id=g.o1_user_id,
            expected_row_version=None,
            fields={"public_appearance": "Another face"},
            plan=fixture_plan(connection, g.campaign_id),
        )
    with engine.begin() as connection:
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


def test_bd6_reveal_authority_survives_the_edit_only_deny(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, rev: Rev
) -> None:
    c = rev.character_id
    before = read(client_factory, m.gm_user_id, g, c)
    assert code(before) == 200 and body(before)["can_edit"] is True
    version = a_new_draft_version(client_factory, g, c, 1)
    assert delegated(client_factory, g, m.gm)

    deny_via_route(client_factory, g, "canon.edit", c, member=m.gm)

    # The S03 read is a read of assignments: the delegation is still effective.
    assert delegated(client_factory, g, m.gm)
    assert listing(client_factory, m.gm_user_id, g, c).json()["can_reveal"] is True
    profile = read(client_factory, m.gm_user_id, g, c)
    assert code(profile) == 200, body(profile)
    assert body(profile)["can_edit"] is False and body(profile)["can_release"] is True
    refused = save(
        client_factory,
        m.gm_user_id,
        g,
        c,
        {"expected_row_version": version, "public_appearance": "Edited"},
    )
    assert (code(refused), error_code(refused)) == (403, "public_profile_edit_denied")
    revealed = create(client_factory, m.gm_user_id, g, c, member_body(g.player))
    assert revealed.status_code == 201, revealed.text
    released = release(client_factory, m.gm_user_id, g, c, version)
    assert code(released) == 201, body(released)


def test_bd7_the_whole_character_deny_is_narrower_than_the_delegation(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, rev: Rev
) -> None:
    c = rev.character_id
    other = another_released_character(postgres_engine, g, "Not Denied")
    deny_via_route(client_factory, g, "campaign.view", c, member=m.gm)

    assert listing(client_factory, m.gm_user_id, g, c).status_code == 404
    assert code(read(client_factory, m.gm_user_id, g, c)) == 404
    assert detail(client_factory, m.gm_user_id, g, c).status_code == 404
    assert create(client_factory, m.gm_user_id, g, c, member_body(g.player)).status_code == 404
    assert code(release(client_factory, m.gm_user_id, g, c, 1)) == 404
    # Nothing revoked the delegation, so the S03 read still lists it, and another character works.
    assert delegated(client_factory, g, m.gm)
    ok = create(client_factory, m.gm_user_id, g, other, member_body(g.player))
    assert ok.status_code == 201, ok.text
    # The owner, who is not named, still reads the denied character.
    assert code(read(client_factory, g.o1_user_id, g, c)) == 200


def test_bd8_removing_the_edit_only_deny_restores_editing_and_leaves_the_delegation(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, rev: Rev
) -> None:
    c = rev.character_id
    grant = deny_via_route(client_factory, g, "canon.edit", c, member=m.gm)
    assert body(read(client_factory, m.gm_user_id, g, c))["can_edit"] is False
    revoke_via_route(client_factory, g, grant)
    restored = read(client_factory, m.gm_user_id, g, c)
    assert code(restored) == 200 and body(restored)["can_edit"] is True
    assert delegated(client_factory, g, m.gm)
    saved = save(
        client_factory,
        m.gm_user_id,
        g,
        c,
        {"expected_row_version": 1, "public_appearance": "Edited again"},
    )
    assert code(saved) == 200, body(saved)


def test_bd9_what_the_edit_only_deny_takes_away_besides_saving(
    client_factory: Factory, postgres_engine: Engine, g: Gate, m: Members, rev: Rev
) -> None:
    """The facts the portal's hint states: the public profile (for a GM with no reveal authority)
    and the player's own profile are removed, the character page is not (DEF-016), and another
    character is unaffected."""
    c = rev.character_id
    other = rev.unreleased_id
    for character in (c, other):
        seed_player_profile(
            postgres_engine,
            campaign_id=g.campaign_id,
            character_id=character,
            editor_membership_id=g.o1,
            fields=markers("B"),
        )
    # m.ast is a GM with canon.edit and no reveal authority.
    assert code(read(client_factory, m.ast_user_id, g, c)) == 200
    assert player_profile(client_factory, m.ast_user_id, g, c).status_code == 200
    assert player_profile(client_factory, m.gm_user_id, g, c).status_code == 200

    deny_via_route(client_factory, g, "canon.edit", c, member=m.ast)
    deny_via_route(client_factory, g, "canon.edit", c, member=m.gm)

    assert code(read(client_factory, m.ast_user_id, g, c)) == 404
    assert player_profile(client_factory, m.ast_user_id, g, c).status_code == 404
    # A delegated GM keeps the public profile through reveal authority but loses the player's own.
    assert code(read(client_factory, m.gm_user_id, g, c)) == 200
    assert player_profile(client_factory, m.gm_user_id, g, c).status_code == 404
    # DEF-016: the character page is unchanged for both.
    assert detail(client_factory, m.ast_user_id, g, c).status_code == 200
    assert detail(client_factory, m.gm_user_id, g, c).status_code == 200
    # Another character is unaffected.
    assert player_profile(client_factory, m.ast_user_id, g, other).status_code == 200
