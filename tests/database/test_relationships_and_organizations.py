"""world.relationships/.relationship_participants/.relationship_perspectives,
world.organizations and its CTI subtypes, world.religions/
.religious_organizations, character.character_religious_affiliations, the
specialized relationships (organization_memberships/employment_relationships/
ownership_relationships/family_relationships/political_relationships), and
campaign.organization_state/.relationship_state (revision 076).

Covers: organization/religion entity CTI and subtype enforcement, same-world
guards across the new domain, the relationship-perspective/relationship-state
"holder must be a participant" rule, organization_memberships' ADR 0010
exclusion constraint, one-current-row-per-(timeline, relationship[, holder])
on campaign.relationship_state, one-current-row-per-(timeline, organization)
on campaign.organization_state, and the event_effects/consequences
forward-reference columns this revision closes.
"""

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError, InternalError, ProgrammingError

from tests.factories import (
    make_business,
    make_character,
    make_character_religious_affiliation,
    make_consequence,
    make_employment_relationship,
    make_event,
    make_event_effect,
    make_family_relationship,
    make_government,
    make_interaction,
    make_military_unit,
    make_organization,
    make_organization_membership,
    make_organization_state,
    make_ownership_relationship,
    make_political_faction,
    make_political_relationship,
    make_relationship,
    make_relationship_participant,
    make_relationship_perspective,
    make_relationship_state,
    make_religion,
    make_religious_organization,
    make_timeline,
    make_world,
    make_world_time,
)

pytestmark = pytest.mark.database

CONSTRAINT_ERRORS = (IntegrityError, InternalError, ProgrammingError)


class Fixture:
    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        self.t0 = make_world_time(connection, self.world_id, 100)
        self.t1 = make_world_time(connection, self.world_id, 200)
        self.t2 = make_world_time(connection, self.world_id, 300)
        self.npc_a = make_character(connection, self.world_id, entity_type_code="npc", name="Alara")
        self.npc_b = make_character(
            connection, self.world_id, entity_type_code="npc", name="Borrin"
        )


@pytest.fixture
def f(db_connection: Connection) -> Fixture:
    return Fixture(db_connection, "relationships-domain-world")


# ---------------------------------------------------------------------------
# world.relationships / world.relationship_participants
# ---------------------------------------------------------------------------


def test_a_relationship_can_be_created_with_participants(
    db_connection: Connection, f: Fixture
) -> None:
    relationship_id = make_relationship(db_connection, f.world_id, relationship_type_code="rivalry")
    make_relationship_participant(db_connection, relationship_id, f.npc_a, role_code="subject")
    make_relationship_participant(db_connection, relationship_id, f.npc_b, role_code="rival")
    assert relationship_id is not None


def test_a_relationship_participant_must_share_its_relationships_world(
    db_connection: Connection, f: Fixture
) -> None:
    relationship_id = make_relationship(db_connection, f.world_id)
    other_world = make_world(db_connection, slug="relationships-other-world")
    foreign_npc = make_character(db_connection, other_world, entity_type_code="npc")

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_relationship_participant(db_connection, relationship_id, foreign_npc)
    assert "belongs to world" in str(exc.value)


def test_a_relationship_ended_time_requires_a_started_time(
    db_connection: Connection, f: Fixture
) -> None:
    with pytest.raises(IntegrityError) as exc:
        make_relationship(db_connection, f.world_id, ended_world_time_id=f.t1)
    assert "ck_relationships_ended_requires_started" in str(exc.value)


def test_a_relationships_ended_time_must_be_after_its_started_time(
    db_connection: Connection, f: Fixture
) -> None:
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_relationship(
            db_connection, f.world_id, started_world_time_id=f.t1, ended_world_time_id=f.t0
        )
    assert "strictly after" in str(exc.value)


def test_a_relationships_started_time_must_share_its_world(
    db_connection: Connection, f: Fixture
) -> None:
    other_world = make_world(db_connection, slug="relationships-time-other-world")
    foreign_time = make_world_time(db_connection, other_world, 50)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_relationship(db_connection, f.world_id, started_world_time_id=foreign_time)
    assert "belongs to world" in str(exc.value)


# ---------------------------------------------------------------------------
# world.relationship_perspectives
# ---------------------------------------------------------------------------


def test_a_perspective_holder_must_be_a_participant(db_connection: Connection, f: Fixture) -> None:
    relationship_id = make_relationship(db_connection, f.world_id)
    make_relationship_participant(db_connection, relationship_id, f.npc_a)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_relationship_perspective(db_connection, relationship_id, f.npc_b, affinity=10)
    assert "is not a participant" in str(exc.value)


def test_a_participant_can_hold_a_perspective(db_connection: Connection, f: Fixture) -> None:
    relationship_id = make_relationship(db_connection, f.world_id)
    make_relationship_participant(db_connection, relationship_id, f.npc_a)
    make_relationship_perspective(
        db_connection, relationship_id, f.npc_a, affinity=40, trust=20, emotional_tone="wary"
    )


def test_a_perspectives_affinity_is_bounded(db_connection: Connection, f: Fixture) -> None:
    relationship_id = make_relationship(db_connection, f.world_id)
    make_relationship_participant(db_connection, relationship_id, f.npc_a)

    with pytest.raises(IntegrityError) as exc:
        make_relationship_perspective(db_connection, relationship_id, f.npc_a, affinity=500)
    assert "ck_relationship_perspectives_affinity_range" in str(exc.value)


# ---------------------------------------------------------------------------
# world.organizations and CTI subtypes
# ---------------------------------------------------------------------------


def test_an_organization_can_be_created(db_connection: Connection, f: Fixture) -> None:
    organization_id = make_organization(db_connection, f.world_id, organization_type_code="guild")
    assert organization_id is not None


def test_a_business_subtype_requires_the_business_entity_type(
    db_connection: Connection, f: Fixture
) -> None:
    """core.enforce_entity_subtype() rejects a world.businesses row for an
    organization whose core.entities.entity_type_id is the bare
    'organization' type rather than 'business' — the same rule
    character.npcs enforces against a bare 'character'-typed entity."""
    bare_organization_id = make_organization(
        db_connection, f.world_id, organization_type_code="guild"
    )

    with pytest.raises(CONSTRAINT_ERRORS):
        db_connection.execute(
            text(
                "INSERT INTO world.businesses (business_id, operating_status) VALUES (:id, 'operating')"
            ),
            {"id": bare_organization_id},
        )


def test_a_business_can_be_created(db_connection: Connection, f: Fixture) -> None:
    organization_id = make_organization(
        db_connection, f.world_id, organization_type_code="business"
    )
    make_business(db_connection, organization_id, business_type="tavern", reputation=10)


def test_a_government_can_be_created(db_connection: Connection, f: Fixture) -> None:
    organization_id = make_organization(
        db_connection, f.world_id, organization_type_code="government"
    )
    make_government(db_connection, organization_id, government_form="monarchy")


def test_a_military_unit_can_be_created(db_connection: Connection, f: Fixture) -> None:
    organization_id = make_organization(
        db_connection, f.world_id, organization_type_code="military_unit"
    )
    make_military_unit(db_connection, organization_id, unit_type="militia")


def test_a_political_faction_can_be_created(db_connection: Connection, f: Fixture) -> None:
    organization_id = make_organization(
        db_connection, f.world_id, organization_type_code="political_faction"
    )
    make_political_faction(db_connection, organization_id, ideology="reformist")


def test_an_organizations_parent_must_share_its_world(
    db_connection: Connection, f: Fixture
) -> None:
    other_world = make_world(db_connection, slug="organizations-other-world")
    foreign_parent = make_organization(db_connection, other_world)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_organization(db_connection, f.world_id, parent_organization_id=foreign_parent)
    assert "belongs to world" in str(exc.value)


def test_an_organization_cannot_be_its_own_parent(db_connection: Connection, f: Fixture) -> None:
    organization_id = make_organization(db_connection, f.world_id)

    with pytest.raises(IntegrityError) as exc:
        db_connection.execute(
            text(
                "UPDATE world.organizations SET parent_organization_id = :id WHERE organization_id = :id"
            ),
            {"id": organization_id},
        )
    assert "ck_organizations_parent_not_self" in str(exc.value)


def test_an_organizations_dissolved_time_requires_a_founded_time(
    db_connection: Connection, f: Fixture
) -> None:
    with pytest.raises(IntegrityError) as exc:
        make_organization(db_connection, f.world_id, dissolved_world_time_id=f.t1)
    assert "ck_organizations_dissolved_requires_founded" in str(exc.value)


def test_an_organizations_dissolved_time_must_be_after_its_founded_time(
    db_connection: Connection, f: Fixture
) -> None:
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_organization(
            db_connection, f.world_id, founded_world_time_id=f.t1, dissolved_world_time_id=f.t0
        )
    assert "strictly after" in str(exc.value)


# ---------------------------------------------------------------------------
# world.religions / world.religious_organizations /
# character.character_religious_affiliations
# ---------------------------------------------------------------------------


def test_a_religion_can_be_created(db_connection: Connection, f: Fixture) -> None:
    religion_id = make_religion(db_connection, f.world_id, pantheon_structure="polytheistic")
    assert religion_id is not None


def test_a_religious_organization_can_be_created(db_connection: Connection, f: Fixture) -> None:
    religion_id = make_religion(db_connection, f.world_id)
    organization_id = make_organization(
        db_connection, f.world_id, organization_type_code="religious_organization"
    )
    make_religious_organization(db_connection, organization_id, religion_id)


def test_a_religious_organizations_religion_must_share_its_world(
    db_connection: Connection, f: Fixture
) -> None:
    other_world = make_world(db_connection, slug="religion-other-world")
    foreign_religion = make_religion(db_connection, other_world)
    organization_id = make_organization(
        db_connection, f.world_id, organization_type_code="religious_organization"
    )

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_religious_organization(db_connection, organization_id, foreign_religion)
    assert "belongs to world" in str(exc.value)


def test_a_character_can_have_a_religious_affiliation(
    db_connection: Connection, f: Fixture
) -> None:
    character_id = make_character(db_connection, f.world_id)
    religion_id = make_religion(db_connection, f.world_id)
    make_character_religious_affiliation(
        db_connection, character_id, religion_id, devotion=80, belief_status="believer"
    )


def test_a_character_cannot_have_two_affiliations_with_the_same_religion(
    db_connection: Connection, f: Fixture
) -> None:
    character_id = make_character(db_connection, f.world_id)
    religion_id = make_religion(db_connection, f.world_id)
    make_character_religious_affiliation(db_connection, character_id, religion_id)

    with pytest.raises(IntegrityError) as exc:
        make_character_religious_affiliation(db_connection, character_id, religion_id)
    assert "ux_character_religious_affiliations_character_religion" in str(exc.value)


def test_a_religious_affiliations_religion_must_share_the_characters_world(
    db_connection: Connection, f: Fixture
) -> None:
    character_id = make_character(db_connection, f.world_id)
    other_world = make_world(db_connection, slug="affiliation-other-world")
    foreign_religion = make_religion(db_connection, other_world)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_character_religious_affiliation(db_connection, character_id, foreign_religion)
    assert "belongs to world" in str(exc.value)


# ---------------------------------------------------------------------------
# world.organization_memberships (ADR 0010 exclusion constraint)
# ---------------------------------------------------------------------------


def test_a_membership_can_be_created(db_connection: Connection, f: Fixture) -> None:
    organization_id = make_organization(db_connection, f.world_id)
    relationship_id = make_relationship(
        db_connection, f.world_id, relationship_type_code="membership"
    )
    make_organization_membership(
        db_connection, relationship_id, organization_id, f.npc_a, f.t0, role="member"
    )


def test_a_member_can_rejoin_after_leaving(db_connection: Connection, f: Fixture) -> None:
    organization_id = make_organization(db_connection, f.world_id)

    first = make_relationship(db_connection, f.world_id, relationship_type_code="membership")
    make_organization_membership(
        db_connection, first, organization_id, f.npc_a, f.t0, effective_to_world_time_id=f.t1
    )

    second = make_relationship(db_connection, f.world_id, relationship_type_code="membership")
    make_organization_membership(db_connection, second, organization_id, f.npc_a, f.t1)


def test_a_member_cannot_have_overlapping_memberships_in_the_same_organization(
    db_connection: Connection, f: Fixture
) -> None:
    organization_id = make_organization(db_connection, f.world_id)

    first = make_relationship(db_connection, f.world_id, relationship_type_code="membership")
    make_organization_membership(db_connection, first, organization_id, f.npc_a, f.t0)

    second = make_relationship(db_connection, f.world_id, relationship_type_code="membership")
    with pytest.raises(IntegrityError) as exc:
        make_organization_membership(db_connection, second, organization_id, f.npc_a, f.t1)
    assert "ex_organization_memberships_no_overlap" in str(exc.value)


def test_a_memberships_organization_must_share_its_relationships_world(
    db_connection: Connection, f: Fixture
) -> None:
    other_world = make_world(db_connection, slug="membership-other-world")
    foreign_organization = make_organization(db_connection, other_world)
    relationship_id = make_relationship(
        db_connection, f.world_id, relationship_type_code="membership"
    )

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_organization_membership(
            db_connection, relationship_id, foreign_organization, f.npc_a, f.t0
        )
    assert "belongs to world" in str(exc.value)


# ---------------------------------------------------------------------------
# world.employment_relationships / world.ownership_relationships /
# world.family_relationships / world.political_relationships
# ---------------------------------------------------------------------------


def test_an_employment_relationship_can_be_created(db_connection: Connection, f: Fixture) -> None:
    organization_id = make_organization(
        db_connection, f.world_id, organization_type_code="business"
    )
    relationship_id = make_relationship(
        db_connection, f.world_id, relationship_type_code="employment"
    )
    make_employment_relationship(
        db_connection, relationship_id, organization_id, f.npc_a, job_title="Bartender"
    )


def test_an_employer_cannot_employ_itself(db_connection: Connection, f: Fixture) -> None:
    relationship_id = make_relationship(
        db_connection, f.world_id, relationship_type_code="employment"
    )

    with pytest.raises(IntegrityError) as exc:
        make_employment_relationship(db_connection, relationship_id, f.npc_a, f.npc_a)
    assert "ck_employment_relationships_not_self" in str(exc.value)


def test_an_employees_world_must_match_the_relationships_world(
    db_connection: Connection, f: Fixture
) -> None:
    other_world = make_world(db_connection, slug="employment-other-world")
    foreign_npc = make_character(db_connection, other_world, entity_type_code="npc")
    relationship_id = make_relationship(
        db_connection, f.world_id, relationship_type_code="employment"
    )

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_employment_relationship(db_connection, relationship_id, f.npc_a, foreign_npc)
    assert "belongs to world" in str(exc.value)


def test_an_employment_relationships_chronology_can_be_valid(
    db_connection: Connection, f: Fixture
) -> None:
    relationship_id = make_relationship(
        db_connection, f.world_id, relationship_type_code="employment"
    )
    make_employment_relationship(
        db_connection,
        relationship_id,
        f.npc_a,
        f.npc_b,
        effective_from_world_time_id=f.t0,
        effective_to_world_time_id=f.t1,
    )


def test_an_employment_relationships_start_must_share_its_world(
    db_connection: Connection, f: Fixture
) -> None:
    other_world = make_world(db_connection, slug="employment-start-other-world")
    foreign_time = make_world_time(db_connection, other_world, 100)
    relationship_id = make_relationship(
        db_connection, f.world_id, relationship_type_code="employment"
    )

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_employment_relationship(
            db_connection,
            relationship_id,
            f.npc_a,
            f.npc_b,
            effective_from_world_time_id=foreign_time,
        )
    assert "belongs to world" in str(exc.value)


def test_an_employment_relationships_end_must_share_its_world(
    db_connection: Connection, f: Fixture
) -> None:
    other_world = make_world(db_connection, slug="employment-end-other-world")
    foreign_time = make_world_time(db_connection, other_world, 100)
    relationship_id = make_relationship(
        db_connection, f.world_id, relationship_type_code="employment"
    )

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_employment_relationship(
            db_connection,
            relationship_id,
            f.npc_a,
            f.npc_b,
            effective_from_world_time_id=f.t0,
            effective_to_world_time_id=foreign_time,
        )
    assert "belongs to world" in str(exc.value)


def test_an_employment_relationships_end_requires_a_start(
    db_connection: Connection, f: Fixture
) -> None:
    relationship_id = make_relationship(
        db_connection, f.world_id, relationship_type_code="employment"
    )

    with pytest.raises(IntegrityError) as exc:
        make_employment_relationship(
            db_connection, relationship_id, f.npc_a, f.npc_b, effective_to_world_time_id=f.t0
        )
    assert "ck_employment_relationships_end_requires_start" in str(exc.value)


def test_an_employment_relationships_end_cannot_equal_its_start(
    db_connection: Connection, f: Fixture
) -> None:
    relationship_id = make_relationship(
        db_connection, f.world_id, relationship_type_code="employment"
    )

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_employment_relationship(
            db_connection,
            relationship_id,
            f.npc_a,
            f.npc_b,
            effective_from_world_time_id=f.t0,
            effective_to_world_time_id=f.t0,
        )
    assert "strictly after" in str(exc.value)


def test_an_employment_relationships_end_cannot_precede_its_start(
    db_connection: Connection, f: Fixture
) -> None:
    relationship_id = make_relationship(
        db_connection, f.world_id, relationship_type_code="employment"
    )

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_employment_relationship(
            db_connection,
            relationship_id,
            f.npc_a,
            f.npc_b,
            effective_from_world_time_id=f.t1,
            effective_to_world_time_id=f.t0,
        )
    assert "strictly after" in str(exc.value)


def test_an_employment_relationships_currentness_is_defined_by_a_null_end(
    db_connection: Connection, f: Fixture
) -> None:
    """Conventions §12.4: exactly one current-records pattern per domain.
    world.employment_relationships uses effective_to_world_time_id IS NULL —
    there is no separate is_current column to fall out of sync with it."""
    current_relationship_id = make_relationship(
        db_connection, f.world_id, relationship_type_code="employment"
    )
    make_employment_relationship(
        db_connection,
        current_relationship_id,
        f.npc_a,
        f.npc_b,
        effective_from_world_time_id=f.t0,
    )
    ended_relationship_id = make_relationship(
        db_connection, f.world_id, relationship_type_code="employment"
    )
    make_employment_relationship(
        db_connection,
        ended_relationship_id,
        f.npc_a,
        f.npc_b,
        effective_from_world_time_id=f.t0,
        effective_to_world_time_id=f.t1,
    )

    rows = db_connection.execute(
        text("""
            SELECT relationship_id, effective_to_world_time_id IS NULL AS is_current
            FROM world.employment_relationships
            WHERE relationship_id IN (:current_id, :ended_id)
        """),
        {"current_id": current_relationship_id, "ended_id": ended_relationship_id},
    ).all()
    is_current_by_id = {row.relationship_id: row.is_current for row in rows}
    assert is_current_by_id[current_relationship_id] is True
    assert is_current_by_id[ended_relationship_id] is False


def test_an_ownership_relationship_can_be_created(db_connection: Connection, f: Fixture) -> None:
    organization_id = make_organization(
        db_connection, f.world_id, organization_type_code="business"
    )
    relationship_id = make_relationship(
        db_connection, f.world_id, relationship_type_code="ownership"
    )
    make_ownership_relationship(db_connection, relationship_id, f.npc_a, organization_id)


def test_an_owner_cannot_own_itself(db_connection: Connection, f: Fixture) -> None:
    relationship_id = make_relationship(
        db_connection, f.world_id, relationship_type_code="ownership"
    )

    with pytest.raises(IntegrityError) as exc:
        make_ownership_relationship(db_connection, relationship_id, f.npc_a, f.npc_a)
    assert "ck_ownership_relationships_not_self" in str(exc.value)


def test_a_family_relationship_can_be_created(db_connection: Connection, f: Fixture) -> None:
    relationship_id = make_relationship(db_connection, f.world_id, relationship_type_code="family")
    make_relationship_participant(db_connection, relationship_id, f.npc_a, role_code="parent")
    make_relationship_participant(db_connection, relationship_id, f.npc_b, role_code="child")
    make_family_relationship(db_connection, relationship_id, family_unit_name="House Alara")


def test_a_political_relationship_can_be_created(db_connection: Connection, f: Fixture) -> None:
    org_a = make_organization(db_connection, f.world_id, organization_type_code="government")
    org_b = make_organization(db_connection, f.world_id, organization_type_code="government")
    relationship_id = make_relationship(db_connection, f.world_id, relationship_type_code="control")
    make_relationship_participant(db_connection, relationship_id, org_a, role_code="ruler")
    make_relationship_participant(db_connection, relationship_id, org_b, role_code="territory")
    make_political_relationship(db_connection, relationship_id, treaty_terms="Vassalage pact")


# ---------------------------------------------------------------------------
# campaign.organization_state
# ---------------------------------------------------------------------------


def test_an_organization_can_have_state_on_a_timeline(
    db_connection: Connection, f: Fixture
) -> None:
    organization_id = make_organization(db_connection, f.world_id)
    make_organization_state(db_connection, f.timeline_id, organization_id, status_code="active")


def test_only_one_current_organization_state_row_per_timeline(
    db_connection: Connection, f: Fixture
) -> None:
    organization_id = make_organization(db_connection, f.world_id)
    make_organization_state(db_connection, f.timeline_id, organization_id)

    with pytest.raises(IntegrityError) as exc:
        make_organization_state(
            db_connection, f.timeline_id, organization_id, status_code="dissolved"
        )
    assert "ux_organization_state_timeline_organization" in str(exc.value)


def test_organization_state_must_share_its_timelines_world(
    db_connection: Connection, f: Fixture
) -> None:
    other_world = make_world(db_connection, slug="org-state-other-world")
    foreign_organization = make_organization(db_connection, other_world)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_organization_state(db_connection, f.timeline_id, foreign_organization)
    assert "belongs to world" in str(exc.value)


def test_organization_states_event_must_share_its_timeline(
    db_connection: Connection, f: Fixture
) -> None:
    organization_id = make_organization(db_connection, f.world_id)
    other_timeline = make_timeline(db_connection, f.world_id)
    foreign_event = make_event(db_connection, f.world_id, other_timeline, f.t0)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_organization_state(
            db_connection, f.timeline_id, organization_id, last_event_id=foreign_event
        )
    assert "same timeline" in str(exc.value) or "timeline" in str(exc.value)


# ---------------------------------------------------------------------------
# campaign.relationship_state
# ---------------------------------------------------------------------------


def test_a_relationships_shared_state_can_be_recorded(
    db_connection: Connection, f: Fixture
) -> None:
    relationship_id = make_relationship(db_connection, f.world_id)
    make_relationship_state(db_connection, f.timeline_id, relationship_id, status_code="active")


def test_a_relationships_per_holder_state_can_be_recorded(
    db_connection: Connection, f: Fixture
) -> None:
    relationship_id = make_relationship(db_connection, f.world_id)
    make_relationship_participant(db_connection, relationship_id, f.npc_a)
    make_relationship_state(
        db_connection,
        f.timeline_id,
        relationship_id,
        perspective_holder_entity_id=f.npc_a,
        affinity=-30,
        emotional_tone="resentful",
    )


def test_relationship_state_holder_must_be_a_participant(
    db_connection: Connection, f: Fixture
) -> None:
    relationship_id = make_relationship(db_connection, f.world_id)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_relationship_state(
            db_connection, f.timeline_id, relationship_id, perspective_holder_entity_id=f.npc_a
        )
    assert "is not a participant" in str(exc.value)


def test_only_one_current_shared_relationship_state_row_per_timeline(
    db_connection: Connection, f: Fixture
) -> None:
    relationship_id = make_relationship(db_connection, f.world_id)
    make_relationship_state(db_connection, f.timeline_id, relationship_id)

    with pytest.raises(IntegrityError) as exc:
        make_relationship_state(db_connection, f.timeline_id, relationship_id, status_code="ended")
    assert "ux_relationship_state_timeline_relationship_no_holder" in str(exc.value)


def test_only_one_current_per_holder_relationship_state_row_per_timeline(
    db_connection: Connection, f: Fixture
) -> None:
    relationship_id = make_relationship(db_connection, f.world_id)
    make_relationship_participant(db_connection, relationship_id, f.npc_a)
    make_relationship_state(
        db_connection, f.timeline_id, relationship_id, perspective_holder_entity_id=f.npc_a
    )

    with pytest.raises(IntegrityError) as exc:
        make_relationship_state(
            db_connection, f.timeline_id, relationship_id, perspective_holder_entity_id=f.npc_a
        )
    assert "ux_relationship_state_timeline_relationship_holder" in str(exc.value)


def test_shared_and_per_holder_relationship_state_can_coexist(
    db_connection: Connection, f: Fixture
) -> None:
    """The second exit criterion: shared/objective and subjective relationship
    data are separate rows, not one merged row."""
    relationship_id = make_relationship(db_connection, f.world_id)
    make_relationship_participant(db_connection, relationship_id, f.npc_a)

    shared_id = make_relationship_state(
        db_connection, f.timeline_id, relationship_id, status_code="active"
    )
    holder_id = make_relationship_state(
        db_connection,
        f.timeline_id,
        relationship_id,
        perspective_holder_entity_id=f.npc_a,
        status_code="estranged",
        affinity=-60,
    )
    assert shared_id != holder_id


def test_relationship_state_must_share_its_timelines_world(
    db_connection: Connection, f: Fixture
) -> None:
    other_world = make_world(db_connection, slug="rel-state-other-world")
    foreign_relationship = make_relationship(db_connection, other_world)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_relationship_state(db_connection, f.timeline_id, foreign_relationship)
    assert "belongs to world" in str(exc.value)


# ---------------------------------------------------------------------------
# narrative.event_effects.target_relationship_id /
# interaction.consequences.resulting_relationship_state_id
# ---------------------------------------------------------------------------


def test_an_event_effect_can_target_a_relationship(db_connection: Connection, f: Fixture) -> None:
    relationship_id = make_relationship(db_connection, f.world_id)
    event_id = make_event(db_connection, f.world_id, f.timeline_id, f.t0)
    make_event_effect(db_connection, event_id, target_relationship_id=relationship_id)


def test_an_event_effect_cannot_target_a_relationship_and_an_entity_at_once(
    db_connection: Connection, f: Fixture
) -> None:
    relationship_id = make_relationship(db_connection, f.world_id)
    event_id = make_event(db_connection, f.world_id, f.timeline_id, f.t0)

    with pytest.raises(IntegrityError) as exc:
        make_event_effect(
            db_connection,
            event_id,
            target_relationship_id=relationship_id,
            target_entity_id=f.npc_a,
        )
    assert "ck_event_effects_at_most_one_target" in str(exc.value)


def test_a_consequence_can_reference_a_resulting_relationship_state(
    db_connection: Connection, f: Fixture
) -> None:
    relationship_id = make_relationship(db_connection, f.world_id)
    relationship_state_id = make_relationship_state(db_connection, f.timeline_id, relationship_id)
    interaction_id = make_interaction(db_connection, f.timeline_id, f.t0)
    make_consequence(
        db_connection,
        interaction_id,
        consequence_type="relationship_change",
        resulting_relationship_state_id=relationship_state_id,
    )


def test_an_event_effects_relationship_target_must_share_its_world(
    db_connection: Connection, f: Fixture
) -> None:
    other_world = make_world(db_connection, slug="event-effect-relationship-other-world")
    foreign_relationship = make_relationship(db_connection, other_world)
    event_id = make_event(db_connection, f.world_id, f.timeline_id, f.t0)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_event_effect(db_connection, event_id, target_relationship_id=foreign_relationship)
    assert "belongs to world" in str(exc.value)


def test_a_consequences_relationship_state_must_share_its_timeline(
    db_connection: Connection, f: Fixture
) -> None:
    other_timeline = make_timeline(db_connection, f.world_id)
    foreign_relationship = make_relationship(db_connection, f.world_id)
    foreign_relationship_state = make_relationship_state(
        db_connection, other_timeline, foreign_relationship
    )
    interaction_id = make_interaction(db_connection, f.timeline_id, f.t0)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_consequence(
            db_connection,
            interaction_id,
            consequence_type="relationship_change",
            resulting_relationship_state_id=foreign_relationship_state,
        )
    assert "belongs to timeline" in str(exc.value)


# ---------------------------------------------------------------------------
# world.relationships.world_id / campaign.relationship_state.timeline_id
# immutability (deployable-integrity correction)
# ---------------------------------------------------------------------------


def test_a_relationships_world_cannot_be_reparented(db_connection: Connection, f: Fixture) -> None:
    relationship_id = make_relationship(db_connection, f.world_id)
    other_world = make_world(db_connection, slug="relationship-reparent-other-world")

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("UPDATE world.relationships SET world_id = :w WHERE relationship_id = :r"),
            {"w": other_world, "r": relationship_id},
        )
    assert "immutable" in str(exc.value)


def test_a_relationships_description_can_still_be_updated(
    db_connection: Connection, f: Fixture
) -> None:
    relationship_id = make_relationship(db_connection, f.world_id)
    db_connection.execute(
        text("UPDATE world.relationships SET description = 'Updated' WHERE relationship_id = :r"),
        {"r": relationship_id},
    )
    row = db_connection.execute(
        text("SELECT description FROM world.relationships WHERE relationship_id = :r"),
        {"r": relationship_id},
    ).one()
    assert row.description == "Updated"


def test_a_relationship_states_timeline_cannot_be_reparented(
    db_connection: Connection, f: Fixture
) -> None:
    relationship_id = make_relationship(db_connection, f.world_id)
    relationship_state_id = make_relationship_state(db_connection, f.timeline_id, relationship_id)
    other_timeline = make_timeline(db_connection, f.world_id)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "UPDATE campaign.relationship_state SET timeline_id = :t "
                "WHERE relationship_state_id = :rs"
            ),
            {"t": other_timeline, "rs": relationship_state_id},
        )
    assert "immutable" in str(exc.value)


def test_a_relationship_states_status_can_still_be_updated(
    db_connection: Connection, f: Fixture
) -> None:
    """The exact non-identity update src/dnd_ai/commands/relationships.py
    evolve_relationship_reaction() performs on an existing row: status and
    reaction fields change, timeline_id does not."""
    relationship_id = make_relationship(db_connection, f.world_id)
    relationship_state_id = make_relationship_state(
        db_connection, f.timeline_id, relationship_id, status_code="active"
    )
    event_id = make_event(db_connection, f.world_id, f.timeline_id, f.t0)
    db_connection.execute(
        text("""
            UPDATE campaign.relationship_state
            SET relationship_status_id =
                (SELECT relationship_status_id FROM campaign.relationship_statuses
                 WHERE code = 'estranged'),
                affinity = -50, last_event_id = :event
            WHERE relationship_state_id = :rs
        """),
        {"event": event_id, "rs": relationship_state_id},
    )
    row = db_connection.execute(
        text("""
            SELECT (SELECT code FROM campaign.relationship_statuses
                    WHERE relationship_status_id = rs.relationship_status_id) AS status_code,
                   affinity
            FROM campaign.relationship_state rs WHERE relationship_state_id = :rs
        """),
        {"rs": relationship_state_id},
    ).one()
    assert row.status_code == "estranged"
    assert row.affinity == -50


# ---------------------------------------------------------------------------
# world.relationship_participants reverse guard against orphaning
# world.relationship_perspectives / campaign.relationship_state
# ---------------------------------------------------------------------------


def test_a_participant_with_no_dependents_can_be_deleted(
    db_connection: Connection, f: Fixture
) -> None:
    relationship_id = make_relationship(db_connection, f.world_id)
    participant_id = make_relationship_participant(db_connection, relationship_id, f.npc_a)
    db_connection.execute(
        text("DELETE FROM world.relationship_participants WHERE relationship_participant_id = :p"),
        {"p": participant_id},
    )


def test_cannot_delete_a_participant_still_holding_a_perspective(
    db_connection: Connection, f: Fixture
) -> None:
    relationship_id = make_relationship(db_connection, f.world_id)
    participant_id = make_relationship_participant(db_connection, relationship_id, f.npc_a)
    make_relationship_perspective(db_connection, relationship_id, f.npc_a)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "DELETE FROM world.relationship_participants WHERE relationship_participant_id = :p"
            ),
            {"p": participant_id},
        )
    assert "relationship_perspective" in str(exc.value)


def test_cannot_delete_a_participant_still_scoped_by_relationship_state(
    db_connection: Connection, f: Fixture
) -> None:
    relationship_id = make_relationship(db_connection, f.world_id)
    participant_id = make_relationship_participant(db_connection, relationship_id, f.npc_a)
    make_relationship_state(
        db_connection, f.timeline_id, relationship_id, perspective_holder_entity_id=f.npc_a
    )

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "DELETE FROM world.relationship_participants WHERE relationship_participant_id = :p"
            ),
            {"p": participant_id},
        )
    assert "relationship_state" in str(exc.value)


def test_cannot_reparent_a_participants_entity_when_a_perspective_depends_on_it(
    db_connection: Connection, f: Fixture
) -> None:
    relationship_id = make_relationship(db_connection, f.world_id)
    participant_id = make_relationship_participant(db_connection, relationship_id, f.npc_a)
    make_relationship_perspective(db_connection, relationship_id, f.npc_a)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "UPDATE world.relationship_participants SET entity_id = :e "
                "WHERE relationship_participant_id = :p"
            ),
            {"e": f.npc_b, "p": participant_id},
        )
    assert "relationship_perspective" in str(exc.value)


def test_changing_a_participants_role_without_reparenting_is_unaffected(
    db_connection: Connection, f: Fixture
) -> None:
    relationship_id = make_relationship(db_connection, f.world_id)
    participant_id = make_relationship_participant(
        db_connection, relationship_id, f.npc_a, role_code="subject"
    )
    make_relationship_perspective(db_connection, relationship_id, f.npc_a)

    db_connection.execute(
        text("""
            UPDATE world.relationship_participants
            SET participant_role_id =
                (SELECT relationship_participant_role_id FROM world.relationship_participant_roles
                 WHERE code = 'object')
            WHERE relationship_participant_id = :p
        """),
        {"p": participant_id},
    )


def test_deleting_one_of_two_roles_for_the_same_participant_is_allowed(
    db_connection: Connection, f: Fixture
) -> None:
    """A perspective/state row only cares that the entity is *a* participant
    in the relationship, not which role — deleting one of two role rows for
    the same entity must not be blocked while the other role row still
    covers it."""
    relationship_id = make_relationship(db_connection, f.world_id)
    subject_participant_id = make_relationship_participant(
        db_connection, relationship_id, f.npc_a, role_code="subject"
    )
    make_relationship_participant(db_connection, relationship_id, f.npc_a, role_code="object")
    make_relationship_perspective(db_connection, relationship_id, f.npc_a)

    db_connection.execute(
        text("DELETE FROM world.relationship_participants WHERE relationship_participant_id = :p"),
        {"p": subject_participant_id},
    )


def test_deleting_an_entire_relationship_cascades_despite_dependents(
    db_connection: Connection, f: Fixture
) -> None:
    """Legitimate whole-relationship deletion (and its cascading children)
    must never be blocked by the participant-removal reverse guard,
    regardless of what order Postgres processes the sibling cascades in."""
    relationship_id = make_relationship(db_connection, f.world_id)
    make_relationship_participant(db_connection, relationship_id, f.npc_a)
    make_relationship_perspective(db_connection, relationship_id, f.npc_a)
    make_relationship_state(
        db_connection, f.timeline_id, relationship_id, perspective_holder_entity_id=f.npc_a
    )

    db_connection.execute(
        text("DELETE FROM world.relationships WHERE relationship_id = :r"), {"r": relationship_id}
    )

    remaining = db_connection.execute(
        text("SELECT count(*) FROM world.relationship_participants WHERE relationship_id = :r"),
        {"r": relationship_id},
    ).scalar()
    assert remaining == 0
