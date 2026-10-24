"""The relationship type compatibility policy (domain/relationship_authoring.py)."""

import itertools

import pytest

from dnd_ai.domain.relationship_authoring import (
    ORGANIZATION_TYPE_CODES,
    PARTICIPANT_TYPE_CODES,
    PERSON_TYPE_CODES,
    PLACE_TYPE_CODES,
    RELATIONSHIP_KINDS,
    RELATIONSHIP_TYPE_POLICIES,
    RelationshipInvalidError,
    RelationshipParticipantIncompatibleError,
    RelationshipParticipantInvalidError,
    pairs_for,
    policy_conflicts,
    validate_participants,
)

# `world.relationship_participant_roles` as seeded by migrations 076 and 130.
SEEDED_ROLES = {
    "subject",
    "object",
    "parent",
    "child",
    "employer",
    "employee",
    "owner",
    "property",
    "ruler",
    "territory",
    "member",
    "organization",
    "ally",
    "rival",
    "other",
    "origin",
    "destination",
}
SEEDED_TYPES = {
    "family",
    "employment",
    "membership",
    "ownership",
    "alliance",
    "rivalry",
    "war",
    "control",
    "worship",
    "adjacency",
    "capital_of",
    "parent_of",
    "other",
    "route",
}


def accepted(relationship_type: str, *participants: tuple[str, str]) -> bool:
    try:
        validate_participants(RELATIONSHIP_TYPE_POLICIES[relationship_type], list(participants))
    except (
        RelationshipInvalidError,
        RelationshipParticipantIncompatibleError,
        RelationshipParticipantInvalidError,
    ):
        return False
    return True


def test_every_type_is_in_exactly_one_kind_and_roles_are_seeded() -> None:
    owned = [t for kind in RELATIONSHIP_KINDS for t in kind.types]
    assert sorted(owned) == sorted(set(owned)) and set(owned) == SEEDED_TYPES
    assert set(RELATIONSHIP_TYPE_POLICIES) == SEEDED_TYPES
    for policy in RELATIONSHIP_TYPE_POLICIES.values():
        assert {r.code for r in policy.roles} <= SEEDED_ROLES
        assert all(r.entity_type_codes <= PARTICIPANT_TYPE_CODES for r in policy.roles)
        assert policy.kind in {k.code for k in RELATIONSHIP_KINDS}


def test_the_kind_catalog_derived_from_the_policy_is_the_delivered_one() -> None:
    catalog = {k.code: (k.types, k.roles, k.fixed_roles) for k in RELATIONSHIP_KINDS}
    assert catalog == {
        "family": (("family",), ("parent", "child", "subject", "object", "other"), None),
        "employment": (("employment",), ("employer", "employee"), ("employer", "employee")),
        "ownership": (("ownership",), ("owner", "property"), ("owner", "property")),
        "membership": (("membership",), ("member", "organization"), ("member", "organization")),
        "route": (("route",), ("origin", "destination"), ("origin", "destination")),
        "political": (
            ("alliance", "rivalry", "war", "control"),
            ("subject", "object", "ally", "rival", "ruler", "territory", "other"),
            None,
        ),
        "general": (
            ("worship", "adjacency", "capital_of", "parent_of", "other"),
            ("subject", "object", "other"),
            None,
        ),
    }


def test_the_matrix_accepts_and_refuses_exactly_as_documented() -> None:
    # Every type x two-role pairing x entity types: derive the expected answer independently
    # of `validate_participants` from the role's allowed entity types.
    for policy in RELATIONSHIP_TYPE_POLICIES.values():
        for first, second in itertools.product(policy.roles, repeat=2):
            roles = [first.code, second.code]
            shape_fits = (
                sorted(roles) == sorted(policy.exact_roles)
                if policy.exact_roles is not None
                else all(need & set(roles) for need in policy.required_roles)
            )
            for a, b in itertools.product(sorted(PARTICIPANT_TYPE_CODES), repeat=2):
                expected = (
                    shape_fits
                    and a in first.entity_type_codes
                    and b in second.entity_type_codes
                    and (
                        not policy.same_group_of
                        or any(a in g and b in g for g in policy.same_group_of)
                    )
                )
                assert accepted(policy.code, (first.code, a), (second.code, b)) is expected, (
                    policy.code,
                    first.code,
                    a,
                    second.code,
                    b,
                )


@pytest.mark.parametrize("relationship_type", ["ownership", "control", "worship"])
def test_characters_pair_with_characters_in_either_direction(relationship_type: str) -> None:
    for me in sorted(PERSON_TYPE_CODES):
        with_a_person = {
            p.my_role
            for p in pairs_for(me)
            if p.relationship_type == relationship_type
            and set(p.other_entity_type_codes) >= PERSON_TYPE_CODES
        }
        # A character is offered both sides, with a character on the other side.
        assert len(with_a_person) == 2, (relationship_type, me, with_a_person)


def test_people_are_not_offered_places_only_types() -> None:
    for me in sorted(PERSON_TYPE_CODES):
        offered = {p.relationship_type for p in pairs_for(me)}
        assert not offered & {"adjacency", "capital_of", "parent_of", "route"}
        assert offered >= {"family", "ownership", "control", "worship", "alliance", "other"}


def test_capital_of_is_directional() -> None:
    capital = [p for p in pairs_for("settlement") if p.relationship_type == "capital_of"]
    assert {(p.my_role, p.other_role) for p in capital} == {("subject", "object")}
    governed = [p for p in pairs_for("nation") if p.relationship_type == "capital_of"]
    assert {(p.my_role, p.other_role) for p in governed} == {("object", "subject")}
    assert all("npc" not in p.other_entity_type_codes for p in capital + governed)


def test_symmetric_types_pair_a_role_with_itself_or_each_other() -> None:
    alliance = [p for p in pairs_for("nation") if p.relationship_type == "alliance"]
    assert {(p.my_role, p.other_role) for p in alliance} == {("ally", "ally")}
    adjacency = [p for p in pairs_for("settlement") if p.relationship_type == "adjacency"]
    assert {(p.my_role, p.other_role) for p in adjacency} == {
        ("subject", "object"),
        ("object", "subject"),
    }
    assert "dungeon_area" not in {c for p in adjacency for c in p.other_entity_type_codes}
    assert pairs_for("dungeon_area") and not [
        p for p in pairs_for("dungeon_area") if p.relationship_type == "adjacency"
    ]


def test_parent_of_stays_within_one_kind_of_record_and_never_a_person() -> None:
    assert not [p for p in pairs_for("npc") if p.relationship_type == "parent_of"]
    org = [p for p in pairs_for("business") if p.relationship_type == "parent_of"]
    assert org and all(set(p.other_entity_type_codes) <= ORGANIZATION_TYPE_CODES for p in org)
    region = [p for p in pairs_for("region") if p.relationship_type == "parent_of"]
    assert region and all(set(p.other_entity_type_codes) <= PLACE_TYPE_CODES for p in region)
    assert not accepted("parent_of", ("subject", "religion"), ("object", "settlement"))


def test_cardinality_and_required_roles() -> None:
    town, other = ("subject", "settlement"), ("subject", "settlement")
    assert not accepted("war", ("subject", "nation"), ("subject", "nation"))  # no object side
    assert not accepted("control", ("ruler", "nation"), ("ruler", "nation"))  # nothing controlled
    assert not accepted("capital_of", town, other)  # two capitals
    assert not accepted("capital_of", town)  # too few
    assert not accepted(
        "adjacency", ("subject", "settlement"), ("object", "settlement"), ("other", "settlement")
    )  # too many
    assert accepted("war", ("subject", "nation"), ("object", "nation"), ("other", "religion"))
    assert accepted("control", ("ruler", "government"), ("territory", "settlement"))
    assert not accepted("alliance", ("ruler", "nation"), ("territory", "settlement"))


def test_location_is_accepted_wherever_a_narrower_place_is_required() -> None:
    assert accepted("capital_of", ("subject", "location"), ("object", "nation"))
    assert accepted("capital_of", ("subject", "settlement"), ("object", "location"))
    assert accepted("alliance", ("ally", "location"), ("ally", "nation"))


def test_error_codes_distinguish_entity_from_shape_and_route_keeps_its_own() -> None:
    policy = RELATIONSHIP_TYPE_POLICIES["capital_of"]
    with pytest.raises(RelationshipParticipantIncompatibleError):
        validate_participants(policy, [("subject", "npc"), ("object", "nation")])
    with pytest.raises(RelationshipInvalidError):
        validate_participants(policy, [("subject", "settlement"), ("subject", "settlement")])
    with pytest.raises(RelationshipParticipantInvalidError):
        validate_participants(
            RELATIONSHIP_TYPE_POLICIES["route"], [("origin", "npc"), ("destination", "settlement")]
        )
    with pytest.raises(RelationshipParticipantInvalidError):
        validate_participants(
            RELATIONSHIP_TYPE_POLICIES["membership"],
            [("member", "npc"), ("organization", "settlement")],
        )


def test_policy_conflicts_report_only_what_the_policy_says() -> None:
    assert policy_conflicts("worship", [("subject", "npc", "Mira"), ("object", "npc", "Tom")]) == []
    reasons = policy_conflicts(
        "capital_of", [("subject", "npc", "Varek"), ("object", "nation", "Vell")]
    )
    assert reasons == ["Varek (npc) cannot be the capital in capital of."]
    # A control record stored with `subject` is reported, never reinterpreted.
    assert policy_conflicts("control", [("subject", "nation"), ("object", "npc")])
    assert policy_conflicts(
        "alliance", [("ally", "nation"), ("ally", "nation")], type_offered=False
    ) == ["This type of relationship is no longer offered."]
    assert policy_conflicts("invented", []) == ["This type of relationship is no longer offered."]


def test_the_portal_fixture_matches_the_policy() -> None:
    import json

    from tests.unit.relationship_policy_fixture import FIXTURE_PATH, build

    stored = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert stored == build(), (
        "portal/src/fixtures/relationshipPolicy.json is stale; regenerate it with "
        "`python -m tests.unit.relationship_policy_fixture`"
    )


def test_a_stored_self_relationship_is_reported_when_the_type_needs_distinct_entities() -> None:
    same, other = object(), object()
    pair = [("subject", "settlement", "Highmarch"), ("object", "settlement", "Highmarch")]
    reasons = policy_conflicts("adjacency", pair, entity_ids=[same, same])
    assert reasons == ["The same record cannot be on both sides of adjacency."]
    assert policy_conflicts("adjacency", pair, entity_ids=[same, other]) == []
    # A type that does not require distinct entities is unaffected, and ids are optional.
    assert policy_conflicts("other", pair, entity_ids=[same, same]) == []
    assert policy_conflicts("adjacency", pair) == []
