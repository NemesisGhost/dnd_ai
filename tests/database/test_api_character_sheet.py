"""Tests for `dnd_ai.api.characters.get_character_sheet_endpoint` —
`GET /campaigns/{campaign_id}/characters/{character_id}/sheet`
(docs/PHASE13D_CHARACTER_SHEET_BACKEND.md).

Mirrors `tests/database/test_api_characters.py`'s access-control shape
(`get_authenticated_user_id` overridden directly, since these tests
exercise campaign-capability enforcement and the character-view-tier
split, not OIDC token verification). Response-content correctness (raw
vs. derived fields, ordering, empty-build behavior, ruleset gating) is
covered separately and exhaustively at the query layer in
`tests/database/test_query_character_sheet.py` — these tests prove only
the HTTP authorization contract and that the route wires the query through
correctly, not every field shape again.
"""

import uuid
from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, text

from dnd_ai.api.app import create_app
from dnd_ai.api.auth import get_authenticated_user_id
from dnd_ai.api.deps import get_engine
from tests.factories import (
    lookup_id,
    make_campaign,
    make_campaign_membership,
    make_character,
    make_character_ability_score,
    make_character_build,
    make_character_class_level,
    make_character_proficiency,
    make_character_relationship_type,
    make_character_state,
    make_membership_character_relationship,
    make_membership_role,
    make_relationship_type_capability,
    make_resource_grant,
    make_role,
    make_role_capability,
    make_ruleset_version_for_world,
    make_species,
    make_timeline,
    make_user,
    make_world,
    make_world_time,
    oidc_principal,
    ruleset_content_id,
    use_dnd5e_ruleset,
)

pytestmark = pytest.mark.database


class Fixture:
    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        self.world_time_id = make_world_time(connection, self.world_id, 100)
        self.campaign_id = make_campaign(
            connection, self.timeline_id, lifecycle_status_code="pending"
        )

        # The real, already-seeded dnd5e/2024 ruleset (migration 022) —
        # dnd_ai.domain.character_calculations.supports_ruleset() gates every
        # derived field on this exact ruleset code. This fixture commits
        # (postgres_engine.begin(), not the rolled-back db_connection), so it
        # must never *insert* new rules.* content for this shared ruleset
        # version — tests/database/test_seed_idempotency.py asserts every
        # dnd5e-scoped rules.* table matches its YAML seed file exactly, for
        # the whole pytest session. Every rules-content id below is a lookup
        # of already-seeded content (ruleset_content_id), never a new row.
        ruleset_version_id = use_dnd5e_ruleset(connection, self.world_id)
        self.species_code = "elf"
        self.athletics_skill_code = "athletics"
        species_id = ruleset_content_id(
            connection, "rules", "species", "species_id", ruleset_version_id, self.species_code
        )
        self.character_id = make_character(
            connection, self.world_id, species_id=species_id, name="Aria", size_category="medium"
        )

        str_id = ruleset_content_id(
            connection, "rules", "abilities", "ability_id", ruleset_version_id, "strength"
        )
        athletics_id = ruleset_content_id(
            connection,
            "rules",
            "skills",
            "skill_id",
            ruleset_version_id,
            self.athletics_skill_code,
        )
        skill_proficiency_type_id = ruleset_content_id(
            connection,
            "rules",
            "proficiency_types",
            "proficiency_type_id",
            ruleset_version_id,
            "skill",
        )
        fighter_id = ruleset_content_id(
            connection, "rules", "classes", "class_id", ruleset_version_id, "fighter"
        )

        self.build_id = make_character_build(connection, self.character_id, ruleset_version_id)
        make_character_ability_score(connection, self.build_id, str_id, 16)
        make_character_class_level(connection, self.build_id, fighter_id, 2)
        make_character_proficiency(
            connection, self.build_id, skill_proficiency_type_id, skill_id=athletics_id
        )
        make_character_state(
            connection, self.timeline_id, self.character_id, character_build_id=self.build_id
        )

        # A second, unrelated world — its character proves the cross-world
        # ownership check (character.characters carries no campaign_id at
        # all, so world agreement stands in for it).
        self.other_world_id = make_world(connection, slug=f"{slug}-other-world")
        other_ruleset_version_id = make_ruleset_version_for_world(connection, self.other_world_id)
        other_species_id = make_species(connection, other_ruleset_version_id, code="dwarf")
        self.other_world_character_id = make_character(
            connection, self.other_world_id, species_id=other_species_id, name="Borin"
        )

        self.view_capability_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "campaign.view"
        )
        self.canon_edit_capability_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "canon.edit"
        )
        self.view_full_capability_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "character.view_full"
        )
        self.view_summary_capability_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "character.view_summary"
        )

        base_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"viewer_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, base_role_id, self.view_capability_id)

        self.gm_user_id = make_user(connection, "Sheet API GM")
        self.gm_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.gm_user_id
        )
        gm_role_id = make_role(
            connection, campaign_id=self.campaign_id, code=f"gm_{uuid.uuid4().hex[:8]}"
        )
        make_role_capability(connection, gm_role_id, self.view_capability_id)
        make_role_capability(connection, gm_role_id, self.canon_edit_capability_id)
        make_membership_role(connection, self.gm_membership_id, gm_role_id)

        self.full_view_relationship_type_id = make_character_relationship_type(connection)
        make_relationship_type_capability(
            connection, self.full_view_relationship_type_id, self.view_full_capability_id
        )
        self.summary_view_relationship_type_id = make_character_relationship_type(connection)
        make_relationship_type_capability(
            connection, self.summary_view_relationship_type_id, self.view_summary_capability_id
        )

        self.full_view_user_id = make_user(connection, "Sheet API Full Viewer")
        self.full_view_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.full_view_user_id
        )
        make_membership_role(connection, self.full_view_membership_id, base_role_id)
        make_membership_character_relationship(
            connection,
            self.full_view_membership_id,
            self.character_id,
            self.full_view_relationship_type_id,
            timeline_id=self.timeline_id,
        )

        self.summary_view_user_id = make_user(connection, "Sheet API Summary Viewer")
        summary_view_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.summary_view_user_id
        )
        make_membership_role(connection, summary_view_membership_id, base_role_id)
        make_membership_character_relationship(
            connection,
            summary_view_membership_id,
            self.character_id,
            self.summary_view_relationship_type_id,
            timeline_id=self.timeline_id,
        )

        self.no_character_capability_user_id = make_user(
            connection, "Sheet API No Character Capability"
        )
        no_character_capability_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.no_character_capability_user_id
        )
        make_membership_role(connection, no_character_capability_membership_id, base_role_id)

        self.capless_user_id = make_user(connection, "Sheet API Capless Member")
        make_campaign_membership(connection, self.campaign_id, self.capless_user_id)

        self.outsider_user_id = make_user(connection, "Sheet API Outsider")


@pytest.fixture
def f(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as connection:
        fixture = Fixture(connection, f"character-sheet-api-{uuid.uuid4().hex[:8]}")
    yield fixture
    with postgres_engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        for world_id in (fixture.world_id, fixture.other_world_id):
            cleanup.execute(
                text("""
                    DELETE FROM security.membership_character_relationships
                    WHERE campaign_membership_id IN (
                        SELECT campaign_membership_id FROM security.campaign_memberships
                        WHERE campaign_id IN (
                            SELECT campaign_id FROM campaign.campaigns WHERE timeline_id IN (
                                SELECT timeline_id FROM campaign.timelines WHERE world_id = :w
                            )
                        )
                    )
                """),
                {"w": world_id},
            )
            cleanup.execute(
                text("""
                    DELETE FROM security.membership_roles WHERE role_id IN (
                        SELECT role_id FROM security.roles WHERE campaign_id IN (
                            SELECT campaign_id FROM campaign.campaigns WHERE timeline_id IN (
                                SELECT timeline_id FROM campaign.timelines WHERE world_id = :w
                            )
                        )
                    )
                """),
                {"w": world_id},
            )
            cleanup.execute(
                text("""
                    DELETE FROM security.role_capabilities WHERE role_id IN (
                        SELECT role_id FROM security.roles WHERE campaign_id IN (
                            SELECT campaign_id FROM campaign.campaigns WHERE timeline_id IN (
                                SELECT timeline_id FROM campaign.timelines WHERE world_id = :w
                            )
                        )
                    )
                """),
                {"w": world_id},
            )
            cleanup.execute(
                text("""
                    DELETE FROM security.roles WHERE campaign_id IN (
                        SELECT campaign_id FROM campaign.campaigns WHERE timeline_id IN (
                            SELECT timeline_id FROM campaign.timelines WHERE world_id = :w
                        )
                    )
                """),
                {"w": world_id},
            )
            cleanup.execute(
                text("""
                    DELETE FROM security.resource_grants WHERE campaign_id IN (
                        SELECT campaign_id FROM campaign.campaigns WHERE timeline_id IN (
                            SELECT timeline_id FROM campaign.timelines WHERE world_id = :w
                        )
                    )
                """),
                {"w": world_id},
            )
            cleanup.execute(
                text("""
                    DELETE FROM security.campaign_memberships WHERE campaign_id IN (
                        SELECT campaign_id FROM campaign.campaigns WHERE timeline_id IN (
                            SELECT timeline_id FROM campaign.timelines WHERE world_id = :w
                        )
                    )
                """),
                {"w": world_id},
            )
            cleanup.execute(
                text(
                    "DELETE FROM campaign.character_state WHERE timeline_id IN "
                    "(SELECT timeline_id FROM campaign.timelines WHERE world_id = :w)"
                ),
                {"w": world_id},
            )
            cleanup.execute(
                text("""
                    DELETE FROM campaign.campaigns WHERE timeline_id IN (
                        SELECT timeline_id FROM campaign.timelines WHERE world_id = :w
                    )
                """),
                {"w": world_id},
            )
            cleanup.execute(
                text("DELETE FROM campaign.timelines WHERE world_id = :w"), {"w": world_id}
            )
            cleanup.execute(text("DELETE FROM core.entities WHERE world_id = :w"), {"w": world_id})
            cleanup.execute(text("DELETE FROM core.worlds WHERE world_id = :w"), {"w": world_id})
        for relationship_type_id in (
            fixture.full_view_relationship_type_id,
            fixture.summary_view_relationship_type_id,
        ):
            cleanup.execute(
                text(
                    "DELETE FROM security.character_relationship_type_capabilities "
                    "WHERE character_relationship_type_id = :rt"
                ),
                {"rt": relationship_type_id},
            )
            cleanup.execute(
                text(
                    "DELETE FROM security.character_relationship_types "
                    "WHERE character_relationship_type_id = :rt"
                ),
                {"rt": relationship_type_id},
            )
        cleanup.execute(
            text("DELETE FROM security.users WHERE user_id = ANY(:users)"),
            {
                "users": [
                    fixture.gm_user_id,
                    fixture.full_view_user_id,
                    fixture.summary_view_user_id,
                    fixture.no_character_capability_user_id,
                    fixture.capless_user_id,
                    fixture.outsider_user_id,
                ]
            },
        )


@pytest.fixture
def client_factory(postgres_engine: Engine) -> Callable[[uuid.UUID], TestClient]:
    def _make(user_id: uuid.UUID) -> TestClient:
        app = create_app()
        app.dependency_overrides[get_engine] = lambda: postgres_engine
        app.dependency_overrides[get_authenticated_user_id] = lambda: oidc_principal(user_id)
        return TestClient(app, raise_server_exceptions=False)

    return _make


def _sheet_url(f: Fixture, character_id: uuid.UUID | None = None) -> str:
    return f"/campaigns/{f.campaign_id}/characters/{character_id or f.character_id}/sheet"


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


def test_a_non_member_gets_not_found(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.outsider_user_id) as client:
        response = client.get(_sheet_url(f))
    assert response.status_code == 404


def test_a_member_without_campaign_view_gets_forbidden(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.capless_user_id) as client:
        response = client.get(_sheet_url(f))
    assert response.status_code == 403


def test_a_member_with_campaign_view_but_no_character_capability_gets_not_found(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.no_character_capability_user_id) as client:
        response = client.get(_sheet_url(f))
    assert response.status_code == 404


def test_summary_tier_alone_is_insufficient_and_gets_the_fixed_not_found(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.summary_view_user_id) as client:
        response = client.get(_sheet_url(f))
    assert response.status_code == 404


def test_full_tier_returns_the_active_build_sheet(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.full_view_user_id) as client:
        response = client.get(_sheet_url(f))
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["character_id"] == str(f.character_id)
    assert body["name"] == "Aria"
    assert body["species_code"] == f.species_code
    assert body["character_build_id"] == str(f.build_id)
    assert body["total_level"] == 2
    assert body["proficiency_bonus"] == 2
    assert any(c["level"] == 2 for c in body["class_levels"])
    assert any(a["score"] == 16 for a in body["ability_scores"])
    athletics = next(s for s in body["skills"] if s["code"] == f.athletics_skill_code)
    assert athletics["is_proficient"] is True


def test_a_gm_gets_the_sheet_without_any_character_specific_relationship(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.get(_sheet_url(f))
    assert response.status_code == 200, response.text
    assert response.json()["character_id"] == str(f.character_id)


def test_a_valid_character_with_no_active_build_returns_the_empty_sheet(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with postgres_engine.begin() as setup:
        ruleset_version_id = make_ruleset_version_for_world(setup, f.world_id)
        species_id = make_species(setup, ruleset_version_id, code="human")
        no_build_character_id = make_character(
            setup, f.world_id, species_id=species_id, name="Bram"
        )
        make_character_state(setup, f.timeline_id, no_build_character_id)
        make_membership_character_relationship(
            setup,
            f.full_view_membership_id,
            no_build_character_id,
            f.full_view_relationship_type_id,
            timeline_id=f.timeline_id,
        )

    with client_factory(f.full_view_user_id) as client:
        response = client.get(_sheet_url(f, no_build_character_id))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["character_id"] == str(no_build_character_id)
    assert body["character_build_id"] is None
    assert body["total_level"] == 0
    assert body["class_levels"] == []
    assert body["ability_scores"] == []


# ---------------------------------------------------------------------------
# Resource-grant overrides — the character-scoped canon.edit denial the
# task explicitly calls out. dnd_ai.api.access.resolve_character_view_tier
# is reused verbatim from the existing character-detail endpoint, so this
# is one regression proving the sheet route wires it through, not a
# re-derivation of the full deny/allow-precedence matrix already exhaustively
# covered by tests/database/test_api_characters.py.
# ---------------------------------------------------------------------------


def test_a_character_targeted_canon_edit_deny_overrides_a_role_derived_gm(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture, postgres_engine: Engine
) -> None:
    with postgres_engine.begin() as setup:
        make_resource_grant(
            setup,
            f.campaign_id,
            f.canon_edit_capability_id,
            character_id=f.character_id,
            grantee_campaign_membership_id=f.gm_membership_id,
            effect="deny",
        )

    with client_factory(f.gm_user_id) as client:
        response = client.get(_sheet_url(f))
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


# ---------------------------------------------------------------------------
# Cross-world ownership and existence
# ---------------------------------------------------------------------------


def test_a_character_in_a_different_world_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.get(_sheet_url(f, f.other_world_character_id))
    assert response.status_code == 404


def test_a_nonexistent_character_is_rejected(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        response = client.get(_sheet_url(f, uuid.uuid4()))
    assert response.status_code == 404


def test_nonexistent_and_cross_world_characters_are_indistinguishable(
    client_factory: Callable[[uuid.UUID], TestClient], f: Fixture
) -> None:
    with client_factory(f.gm_user_id) as client:
        nonexistent_response = client.get(_sheet_url(f, uuid.uuid4()))
        cross_world_response = client.get(_sheet_url(f, f.other_world_character_id))
    assert nonexistent_response.status_code == cross_world_response.status_code == 404
    # correlation_id legitimately differs per request; the disclosure-
    # relevant fields (code, message) must not.
    assert (
        nonexistent_response.json()["error"]["code"] == cross_world_response.json()["error"]["code"]
    )
    assert (
        nonexistent_response.json()["error"]["message"]
        == cross_world_response.json()["error"]["message"]
    )
