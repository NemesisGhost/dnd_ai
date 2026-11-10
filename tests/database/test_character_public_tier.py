# ruff: noqa: F811 - the imported fixtures are used by parameter name
"""The public-profile tier of the character detail (P03-A A4b, plan sections 12.2 to 12.4).

A revelation confers the latest release of a character, and nothing else: the detail answers with a
distinct, allowlisted `PublicCharacterResponse`. Readers with a summary or full tier keep their tier
and gain the released section (D11), unless a `character.view_public_profile` deny nulls it (D12).
Everything runs against the production routes and committed data:

- the reader matrix (12.2), with the exact status, `view_tier`, `sections` and section object;
- disclosure: drafts, flags, legacy text, the canonical summary, the release note, live species and
  size, a relabelled species, species ids and the revelation never reach an audience;
- snapshot stability, campaign isolation, revocation and lifecycle, independent sources;
- the sheet, builds, relationships, inventory, parties and perspectives unchanged;
- a paired Foundry credential, which is never served the public tier.
"""

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from dnd_ai.api.app import create_app
from dnd_ai.api.auth import get_authenticated_user_id
from dnd_ai.api.deps import get_engine
from dnd_ai.commands.character_public_profile import (
    release_character_public_profile,
    save_character_public_profile_draft,
)
from dnd_ai.domain.access import FOUNDRY_ACCESS_AUTH_METHOD, AuthenticatedPrincipal
from tests.database.test_campaign_owner_gate import (  # noqa: F401 - fixtures used by name
    Gate,
    _template_role_id,
    client_factory,
    g,
)
from tests.database.test_character_public_profile_api import deny
from tests.database.test_character_reveal_delegation import (  # noqa: F401 - fixtures used by name
    Members,
    m,
)
from tests.database.test_character_revelations import (  # noqa: F401 - fixtures used by name
    REASON_MARKER,
    SUMMARY_MARKER,
    Rev,
    campaign_body,
    create,
    group_body,
    member_body,
    rev,
)
from tests.database.test_character_revelations_discovery import (  # noqa: F401 - fixtures by name
    CANON_MARKER,
    People,
    end_membership,
    make_id,
    people,
    revealed,
    revoke_ok,
    sees,
)
from tests.database.test_public_profile_identity_api import (
    change_identity,
    entity_row_version,
    live_identity,
    relabel_species,
)
from tests.factories import (
    lookup_id,
    make_campaign_membership,
    make_character,
    make_membership_role,
    make_resource_grant,
    make_user,
)

pytestmark = pytest.mark.database

Factory = Callable[[uuid.UUID], TestClient]

BACKGROUND = "RELEASED-BACKGROUND-MARKER-3321"
NOTE = "RELEASE-NOTE-MARKER-4432"
DRAFT_MARKER = "UNRELEASED-DRAFT-MARKER-5543"
LEGACY_MARKER = "LEGACY-DESCRIPTION-MARKER-6654"
APPEARANCE = "A weathered face"  # the `rev` fixture's released appearance

PUBLIC_KEYS = {"view_tier", "character_id", "name", "character_kind", "sections", "public_profile"}
SECTION_KEYS = {"summary", "appearance", "background", "species", "size"}
PUBLIC_SECTIONS = {
    "details": True,
    "sheet": False,
    "relationships": False,
    "inventory": False,
    "parties": False,
    "public_profile": True,
}
# The keys of the pre-A4 `CharacterResponse`; a summary or full body adds exactly the two new ones.
LEGACY_KEYS = {
    "authoring", "sections", "character_id", "name", "character_kind", "canon_status",
    "lifecycle_status", "species_code", "size_category", "current_hit_points",
    "maximum_hit_points", "temporary_hit_points", "exhaustion_level", "death_save_successes",
    "death_save_failures", "current_location_id", "active_encounter_id", "conditions", "resources",
}  # fmt: skip
MECHANICAL = (
    "active_encounter_id", "current_hit_points", "maximum_hit_points", "temporary_hit_points",
    "exhaustion_level", "death_save", "current_location_id", "conditions", "resources",
    "species_code", "size_category", "canon_status", "lifecycle_status", "authoring",
)  # fmt: skip


@dataclass
class Tier:
    character: uuid.UUID
    section: dict[str, Any]  # the exact object a reader of the latest release sees
    released_species_id: uuid.UUID
    live_species_id: uuid.UUID
    live_code: str
    markers: tuple[str, ...]


def detail_url(g: Gate, character: uuid.UUID, suffix: str = "") -> str:
    return f"/campaigns/{g.campaign_id}/characters/{character}{suffix}"


def get(factory: Factory, user: uuid.UUID, g: Gate, character: uuid.UUID, suffix: str = "") -> Any:
    with factory(user) as client:
        return client.get(detail_url(g, character, suffix))


@pytest.fixture
def tier(postgres_engine: Engine, g: Gate, m: Members, rev: Rev, people: People) -> Tier:
    """`rev`'s character with a v2 release that publishes species and size and carries a
    background and a note, then every kind of later change an audience must never see: an unreleased
    draft edit and flag, legacy description text, a changed and relabelled live species and size."""
    c = rev.character_id
    with postgres_engine.begin() as connection:
        save_character_public_profile_draft(
            connection,
            campaign_id=g.campaign_id,
            character_id=c,
            actor_user_id=g.o1_user_id,
            expected_row_version=1,
            fields={"public_background": BACKGROUND},
            identity_flags={"publish_species": True, "publish_size": True},
        )
    live = live_identity(postgres_engine, c)
    with postgres_engine.begin() as connection:
        release_character_public_profile(
            connection,
            campaign_id=g.campaign_id,
            character_id=c,
            actor_membership_id=g.o1,
            expected_draft_row_version=2,
            release_note=NOTE,
            expected_character_row_version=entity_row_version(postgres_engine, c),
        )
    with postgres_engine.begin() as connection:
        save_character_public_profile_draft(
            connection,
            campaign_id=g.campaign_id,
            character_id=c,
            actor_user_id=g.o1_user_id,
            expected_row_version=2,
            fields={"public_appearance": DRAFT_MARKER},
            identity_flags={"publish_size": False},
        )
        connection.execute(
            text("""
                INSERT INTO character.character_descriptions (character_id, background, appearance, notes)
                VALUES (:c, :m, :m, :m)
                ON CONFLICT (character_id) DO UPDATE SET background = EXCLUDED.background,
                    appearance = EXCLUDED.appearance, notes = EXCLUDED.notes
            """),
            {"c": c, "m": LEGACY_MARKER},
        )
    new_species = change_identity(postgres_engine, c, size="tiny", species_code="newspecies")
    relabel_species(postgres_engine, live["species_id"], "Old Label Changed")
    relabel_species(postgres_engine, new_species, "Brand New Species")
    return Tier(
        character=c,
        section={
            "summary": SUMMARY_MARKER,
            "appearance": APPEARANCE,
            "background": BACKGROUND,
            "species": {"code": live["code"], "label": live["label"]},
            "size": {"code": live["size"], "label": live["size"].title()},
        },
        released_species_id=live["species_id"],
        live_species_id=new_species,
        live_code="brand_new_species",
        markers=(
            DRAFT_MARKER, LEGACY_MARKER, CANON_MARKER, NOTE, REASON_MARKER,
            str(live["species_id"]), str(new_species), "Brand New Species", "Old Label Changed",
            "brand_new_species", "tiny",
        ),
    )  # fmt: skip


def grant(
    engine: Engine, g: Gate, membership: uuid.UUID, capability: str, c: uuid.UUID
) -> uuid.UUID:
    with engine.begin() as connection:
        return make_resource_grant(
            connection,
            g.campaign_id,
            lookup_id(connection, "security", "capabilities", "capability_id", capability),
            timeline_id=g.timeline_id,
            grantee_campaign_membership_id=membership,
            character_id=c,
        )


def ungrant(engine: Engine, grant_id: uuid.UUID) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE security.resource_grants SET revoked_at = now() WHERE resource_grant_id = :g"
            ),
            {"g": grant_id},
        )


def public_body(t: Tier, g: Gate) -> dict[str, Any]:
    return {
        "view_tier": "public_profile",
        "character_id": str(t.character),
        "name": "Revealed Subject",
        "character_kind": "character",
        "sections": PUBLIC_SECTIONS,
        "public_profile": t.section,
    }


# --- the reader matrix (12.2) ----------------------------------------------------------------------


def test_a_revelation_only_reader_gets_exactly_the_public_tier(
    client_factory: Factory, g: Gate, tier: Tier
) -> None:
    c, f = tier.character, client_factory
    assert get(f, g.player_user_id, g, c).status_code == 404  # no revelation yet
    revealed(f, g, c, campaign_body("campaign_current_and_future"))
    response = get(f, g.player_user_id, g, c)
    assert response.status_code == 200, response.text
    assert response.json() == public_body(tier, g)
    assert (
        set(response.json()) == PUBLIC_KEYS
        and set(response.json()["public_profile"]) == SECTION_KEYS
    )


@pytest.mark.parametrize("key", ["entity_id", "character_id"])
def test_a_view_public_profile_deny_removes_the_detail_but_not_the_listing(
    client_factory: Factory, postgres_engine: Engine, g: Gate, tier: Tier, key: str
) -> None:
    c, f = tier.character, client_factory
    revealed(f, g, c, campaign_body("campaign_current_and_future"))
    deny(postgres_engine, g, g.player, "character.view_public_profile", c, key=key)
    assert get(f, g.player_user_id, g, c).status_code == 404
    assert sees(f, g.player_user_id, g, c)  # listed, but not a link (12.4)


def test_a_discover_deny_hides_the_listing_and_leaves_the_public_tier_by_direct_url(
    client_factory: Factory, postgres_engine: Engine, g: Gate, tier: Tier
) -> None:
    c, f = tier.character, client_factory
    revealed(f, g, c, campaign_body("campaign_current_and_future"))
    # Discovery reads the `character_id` key (as the A3b tests do), so that is the key used here.
    deny(postgres_engine, g, g.player, "character.discover", c, key="character_id")
    assert not sees(f, g.player_user_id, g, c)
    response = get(f, g.player_user_id, g, c)
    assert response.status_code == 200 and response.json() == public_body(tier, g)


def test_a_whole_character_deny_removes_the_detail_and_the_listing(
    client_factory: Factory, postgres_engine: Engine, g: Gate, tier: Tier
) -> None:
    c, f = tier.character, client_factory
    revealed(f, g, c, campaign_body("campaign_current_and_future"))
    deny(postgres_engine, g, g.player, "campaign.view", c)
    assert get(f, g.player_user_id, g, c).status_code == 404
    assert not sees(f, g.player_user_id, g, c)


def test_a_summary_reader_keeps_the_tier_and_gains_the_section_unless_denied(
    client_factory: Factory, postgres_engine: Engine, g: Gate, tier: Tier, people: People
) -> None:
    c, f, p2 = tier.character, client_factory, people.p2
    grant(postgres_engine, g, p2.membership, "character.view_summary", c)
    response = get(f, p2.user, g, c)
    body = response.json()
    assert response.status_code == 200 and body["view_tier"] == "summary"
    assert set(body) == LEGACY_KEYS | {"view_tier", "public_profile"}
    assert body["public_profile"] == tier.section
    assert body["sections"]["public_profile"] is True and body["sections"]["relationships"] is True
    assert body["sections"]["sheet"] is False
    # The summary reader's own top-level fields stay the live definition; the section is what
    # audiences were told (12.3).
    assert body["species_code"] == tier.live_code and body["size_category"] == "tiny"
    assert tier.section["species"]["code"] != tier.live_code
    assert body["name"] == "Revealed Subject"

    # A `view_public_profile` deny (either key) nulls the section only.
    for key in ("entity_id", "character_id"):
        deny(postgres_engine, g, p2.membership, "character.view_public_profile", c, key=key)
        denied = get(f, p2.user, g, c)
        assert denied.status_code == 200 and denied.json()["view_tier"] == "summary"
        assert denied.json()["public_profile"] is None
        assert denied.json()["sections"]["public_profile"] is False
        assert denied.json()["sections"]["relationships"] is True  # no other tier removed


def test_a_gm_gets_the_full_tier_with_the_section_and_a_character_without_a_release_gets_none(
    client_factory: Factory, g: Gate, tier: Tier, rev: Rev
) -> None:
    f = client_factory
    body = get(f, g.o1_user_id, g, tier.character).json()
    assert body["view_tier"] == "full" and body["public_profile"] == tier.section
    assert body["sections"]["public_profile"] is True and body["sections"]["sheet"] is True
    assert set(body) == LEGACY_KEYS | {"view_tier", "public_profile"}
    unreleased = get(f, g.o1_user_id, g, rev.unreleased_id).json()
    assert unreleased["view_tier"] == "full" and unreleased["public_profile"] is None
    assert unreleased["sections"]["public_profile"] is False


def test_bare_discover_lists_a_character_and_opens_nothing(
    client_factory: Factory, postgres_engine: Engine, g: Gate, tier: Tier, people: People
) -> None:
    c, f, p2 = tier.character, client_factory, people.p2
    grant(postgres_engine, g, p2.membership, "character.discover", c)
    assert sees(f, p2.user, g, c)  # discovery lists it...
    assert get(f, p2.user, g, c).status_code == 404  # ...publication is not revelation


def test_a_release_without_a_revelation_opens_nothing_for_a_plain_player(
    client_factory: Factory, g: Gate, tier: Tier
) -> None:
    assert get(client_factory, g.player_user_id, g, tier.character).status_code == 404


# --- disclosure (8) ---------------------------------------------------------------------------------


def test_the_public_tier_discloses_the_release_content_and_nothing_else(
    client_factory: Factory, g: Gate, tier: Tier, rev: Rev
) -> None:
    c, f = tier.character, client_factory
    revelation = revealed(f, g, c, campaign_body("campaign_current_and_future"))
    response = get(f, g.player_user_id, g, c)
    assert response.status_code == 200
    for marker in (*tier.markers, str(revelation)):
        assert marker not in response.text, marker
    body = response.json()
    assert set(body) == PUBLIC_KEYS and set(body["public_profile"]) == SECTION_KEYS
    assert set(body["public_profile"]["species"]) == {"code", "label"}
    assert set(body["public_profile"]["size"]) == {"code", "label"}
    for key in MECHANICAL:
        assert key not in response.text, key
    assert body["name"] == "Revealed Subject" and body["public_profile"] == tier.section
    # The same holds for a member reveal, and an unreleased sibling stays a plain 404.
    assert get(f, g.player_user_id, g, rev.unreleased_id).status_code == 404


def test_a_summary_or_full_body_adds_only_the_section_to_its_existing_keys(
    client_factory: Factory, postgres_engine: Engine, g: Gate, tier: Tier, people: People, rev: Rev
) -> None:
    f = client_factory
    grant(postgres_engine, g, people.p2.membership, "character.view_summary", rev.unreleased_id)
    body = get(f, people.p2.user, g, rev.unreleased_id).json()
    assert set(body) == LEGACY_KEYS | {"view_tier", "public_profile"}
    assert body["view_tier"] == "summary" and body["public_profile"] is None
    assert body["sections"] == {
        "details": True, "sheet": False, "relationships": True, "inventory": False,
        "parties": False, "public_profile": False,
    }  # fmt: skip
    assert get(f, g.o1_user_id, g, tier.character).json()["view_tier"] == "full"


# --- snapshot stability (9) -------------------------------------------------------------------------


def test_a_later_definition_change_never_alters_the_section_and_a_new_release_shows_the_new_values(
    client_factory: Factory, postgres_engine: Engine, g: Gate, tier: Tier, people: People
) -> None:
    c, f = tier.character, client_factory
    revealed(f, g, c, campaign_body("campaign_current_and_future"))
    grant(postgres_engine, g, people.p2.membership, "character.view_summary", c)
    assert get(f, g.player_user_id, g, c).json()["public_profile"] == tier.section
    summary = get(f, people.p2.user, g, c).json()
    assert summary["public_profile"] == tier.section  # the released values
    assert summary["species_code"] == tier.live_code  # beside the live one
    # A new flagged release: the section now shows the changed definition.
    with postgres_engine.begin() as connection:
        save_character_public_profile_draft(
            connection,
            campaign_id=g.campaign_id,
            character_id=c,
            actor_user_id=g.o1_user_id,
            expected_row_version=3,
            fields={},
            identity_flags={"publish_species": True, "publish_size": True},
        )
    with postgres_engine.begin() as connection:
        release_character_public_profile(
            connection,
            campaign_id=g.campaign_id,
            character_id=c,
            actor_membership_id=g.o1,
            expected_draft_row_version=4,
            release_note=None,
            expected_character_row_version=entity_row_version(postgres_engine, c),
        )
    new = get(f, g.player_user_id, g, c).json()["public_profile"]
    assert new["species"] == {"code": tier.live_code, "label": "Brand New Species"}
    assert new["size"] == {"code": "tiny", "label": "Tiny"}
    assert new["appearance"] == DRAFT_MARKER  # the latest release wins as a whole snapshot
    assert get(f, people.p2.user, g, c).json()["public_profile"] == new


# --- campaign isolation (10) -----------------------------------------------------------------------


def test_releases_and_revelations_are_per_campaign(
    client_factory: Factory, postgres_engine: Engine, g: Gate, tier: Tier, people: People
) -> None:
    c, f = tier.character, client_factory
    b = people.campaign_b
    with postgres_engine.begin() as connection:
        shared = make_user(connection, "Both Campaigns")
        in_a = make_campaign_membership(connection, g.campaign_id, shared)
        make_membership_role(connection, in_a, _template_role_id(connection, "player"))
        in_b = make_campaign_membership(connection, b, shared)
        make_membership_role(connection, in_b, _template_role_id(connection, "player"))
        only_b = make_character(connection, g.world_id, name="Only In B")
        save_character_public_profile_draft(
            connection,
            campaign_id=b,
            character_id=only_b,
            actor_user_id=people.b_owner.user,
            expected_row_version=None,
            fields={"public_appearance": "B-ONLY-APPEARANCE"},
        )
        save_character_public_profile_draft(
            connection,
            campaign_id=b,
            character_id=c,
            actor_user_id=people.b_owner.user,
            expected_row_version=None,
            fields={"public_appearance": "B-VERSION-OF-APPEARANCE"},
        )
    for character in (only_b, c):
        with postgres_engine.begin() as connection:
            release_character_public_profile(
                connection,
                campaign_id=b,
                character_id=character,
                actor_membership_id=people.b_owner.membership,
                expected_draft_row_version=1,
                release_note=None,
            )
        with f(people.b_owner.user) as client:
            made = client.post(
                f"/campaigns/{b}/characters/{character}/revelations",
                json=campaign_body("campaign_current_and_future"),
            )
        assert made.status_code == 201, made.text
    revealed(f, g, c, member_body(in_a))

    def read(campaign: uuid.UUID, character: uuid.UUID) -> Any:
        with f(shared) as client:
            return client.get(f"/campaigns/{campaign}/characters/{character}")

    # Released and revealed only in B: nothing in A.
    assert read(g.campaign_id, only_b).status_code == 404
    assert read(b, only_b).status_code == 200
    # Both campaigns: each reader sees their own campaign's release.
    in_campaign_a = read(g.campaign_id, c).json()["public_profile"]
    in_campaign_b = read(b, c).json()["public_profile"]
    assert in_campaign_a == tier.section
    assert (
        in_campaign_b["appearance"] == "B-VERSION-OF-APPEARANCE"
        and in_campaign_b["species"] is None
    )
    assert "B-VERSION" not in json.dumps(in_campaign_a) and APPEARANCE not in json.dumps(
        in_campaign_b
    )
    # Campaign B's GM reads nothing of A.
    with f(people.b_owner.user) as client:
        assert client.get(detail_url(g, c)).status_code in (403, 404)


# --- revocation and lifecycle (11) -------------------------------------------------------------------


@pytest.mark.parametrize(
    "kind", ["member", "access_group", "campaign_current", "campaign_current_and_future"]
)
def test_revoking_each_audience_kind_takes_effect_on_the_next_request(
    client_factory: Factory, g: Gate, tier: Tier, rev: Rev, kind: str
) -> None:
    c, f = tier.character, client_factory
    payload = {
        "member": member_body(g.player),
        "access_group": group_body(rev.group_id),
        "campaign_current": campaign_body("campaign_current"),
        "campaign_current_and_future": campaign_body("campaign_current_and_future"),
    }[kind]
    revelation = revealed(f, g, c, payload)
    assert get(f, g.player_user_id, g, c).status_code == 200
    revoke_ok(f, g, c, revelation)
    assert get(f, g.player_user_id, g, c).status_code == 404


def test_ending_the_membership_deactivating_the_group_and_archiving_each_close_the_detail(
    client_factory: Factory, postgres_engine: Engine, g: Gate, tier: Tier, rev: Rev, people: People
) -> None:
    c, f = tier.character, client_factory
    # Archiving the character is inert, and restoring it applies the revelation again (D9-g).
    revealed(f, g, c, campaign_body("campaign_current_and_future"))

    def set_status(code: str) -> None:
        with postgres_engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE core.entities SET lifecycle_status_id = (SELECT lifecycle_status_id "
                    "FROM core.lifecycle_statuses WHERE code = :code) WHERE entity_id = :c"
                ),
                {"code": code, "c": c},
            )

    assert get(f, g.player_user_id, g, c).status_code == 200
    set_status("archived")
    assert get(f, g.player_user_id, g, c).status_code == 404
    set_status("active")
    assert get(f, g.player_user_id, g, c).status_code == 200
    # Ending the member's membership.
    end_membership(f, g, people.x.membership)
    # Deactivating a group closes a group revelation.
    other = revealed(f, g, c, group_body(rev.group_id))
    assert other
    with f(g.o1_user_id) as client:
        done = client.post(
            f"/campaigns/{g.campaign_id}/access-groups/{rev.group_id}/deactivate", json={}
        )
    assert done.status_code == 200, done.text
    # The player still holds the campaign-wide revelation; the group one no longer reaches anyone.
    assert get(f, g.player_user_id, g, c).status_code == 200
    end_membership(f, g, g.player)
    assert get(f, g.player_user_id, g, c).status_code in (403, 404)


# --- independent sources (12) ------------------------------------------------------------------------


def test_a_revelation_and_a_summary_grant_are_independent_in_both_orders(
    client_factory: Factory, postgres_engine: Engine, g: Gate, tier: Tier, people: People
) -> None:
    c, f, p2 = tier.character, client_factory, people.p2
    revelation = revealed(f, g, c, member_body(p2.membership))
    assert get(f, p2.user, g, c).json()["view_tier"] == "public_profile"
    summary = grant(postgres_engine, g, p2.membership, "character.view_summary", c)
    both = get(f, p2.user, g, c).json()
    assert both["view_tier"] == "summary" and both["public_profile"] == tier.section
    # Order one: revoke the revelation first; the summary tier and its section stay (D11).
    revoke_ok(f, g, c, revelation)
    kept = get(f, p2.user, g, c).json()
    assert kept["view_tier"] == "summary" and kept["public_profile"] == tier.section
    # Order two: a revelation again, then revoke the grant; the public tier is what is left.
    again = revealed(f, g, c, member_body(p2.membership))
    ungrant(postgres_engine, summary)
    left = get(f, p2.user, g, c)
    assert left.status_code == 200 and left.json() == public_body(tier, g)
    revoke_ok(f, g, c, again)
    assert get(f, p2.user, g, c).status_code == 404


def test_two_revelations_are_two_sources_and_either_alone_suffices(
    client_factory: Factory, g: Gate, tier: Tier, rev: Rev
) -> None:
    c, f = tier.character, client_factory
    first = revealed(f, g, c, member_body(g.player))
    second = revealed(f, g, c, campaign_body("campaign_current_and_future"))
    revoke_ok(f, g, c, first)
    assert get(f, g.player_user_id, g, c).status_code == 200
    revoke_ok(f, g, c, second)
    assert get(f, g.player_user_id, g, c).status_code == 404


# --- existing tiers unchanged (13) --------------------------------------------------------------------


def test_a_revelation_still_opens_no_sheet_builds_inventory_relationships_or_profile_edit(
    client_factory: Factory, postgres_engine: Engine, g: Gate, tier: Tier
) -> None:
    c, f = tier.character, client_factory
    paths = ("/sheet", "/builds", "/inventory", "/relationships", "/public-profile", "/parties")
    before = {p: get(f, g.player_user_id, g, c, p).status_code for p in paths}
    revealed(f, g, c, campaign_body("campaign_current_and_future"))
    after = {p: get(f, g.player_user_id, g, c, p) for p in paths}
    assert {p: r.status_code for p, r in after.items()} == before
    for path, response in after.items():
        assert response.status_code in (403, 404), path
        assert "Revealed Subject" not in response.text and CANON_MARKER not in response.text, path


def test_inventory_only_plus_a_revelation_gives_the_restricted_projection_as_before(
    client_factory: Factory, postgres_engine: Engine, g: Gate, tier: Tier
) -> None:
    c, f = tier.character, client_factory
    grant(postgres_engine, g, g.player, "character.view_inventory", c)
    before = get(f, g.player_user_id, g, c, "/inventory")
    revealed(f, g, c, campaign_body("campaign_current_and_future"))
    after = get(f, g.player_user_id, g, c, "/inventory")
    assert after.status_code == before.status_code and after.json() == before.json()
    public = get(f, g.player_user_id, g, c).json()
    assert public["view_tier"] == "public_profile" and public["sections"]["inventory"] is True
    assert public["sections"]["sheet"] is False and public["sections"]["relationships"] is False


# --- Foundry (15) -------------------------------------------------------------------------------------


def foundry_client(engine: Engine, user: uuid.UUID, g: Gate) -> TestClient:
    principal = AuthenticatedPrincipal(
        user_id=user,
        auth_method=FOUNDRY_ACCESS_AUTH_METHOD,
        foundry_external_system_id=uuid.uuid4(),
        foundry_world_id=g.world_id,
        campaign_id=g.campaign_id,
        foundry_connection_id=uuid.uuid4(),
        foundry_device_id=uuid.uuid4(),
        foundry_scopes=frozenset({"encounter_read"}),
    )
    app = create_app()
    app.dependency_overrides[get_engine] = lambda: engine
    app.dependency_overrides[get_authenticated_user_id] = lambda: principal
    return TestClient(app, raise_server_exceptions=False)


def test_a_paired_foundry_credential_is_never_served_the_public_tier(
    client_factory: Factory, postgres_engine: Engine, g: Gate, tier: Tier
) -> None:
    c, f = tier.character, client_factory
    revealed(f, g, c, campaign_body("campaign_current_and_future"))
    assert get(f, g.player_user_id, g, c).status_code == 200  # the portal reader is served it
    with foundry_client(postgres_engine, g.player_user_id, g) as client:
        assert client.get(detail_url(g, c)).status_code == 404
    # A paired GM credential is served `CharacterResponse`, with the additive fields.
    with foundry_client(postgres_engine, g.o1_user_id, g) as client:
        response = client.get(detail_url(g, c))
    body = response.json()
    assert response.status_code == 200 and body["view_tier"] == "full"
    assert set(body) == LEGACY_KEYS | {"view_tier", "public_profile"}
    assert body["public_profile"] == tier.section
