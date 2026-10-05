"""Supersession publishes an approved replacement, so it must enforce the same
Phase 15 publish preconditions as ordinary publish (ENTITY_LIFECYCLE section 21.1),
and the replacement-candidate list must not offer one that would be refused."""

from collections.abc import Callable, Iterator
from dataclasses import dataclass

import pytest
from sqlalchemy import Connection, text

from tests.authoring_support import AuthoringHarness, harness_fixture_factory
from tests.content_support import ContentSetup

pytestmark = pytest.mark.database


@pytest.fixture
def harness(db_connection: Connection) -> Iterator[AuthoringHarness]:
    yield from harness_fixture_factory()(db_connection)


@pytest.fixture
def s(harness: AuthoringHarness, db_connection: Connection) -> ContentSetup:
    return ContentSetup(harness, db_connection)


def post(s: ContentSetup, path: str, body: dict, status: int = 201) -> dict:
    response = s.gm.post(s.url(path), body, key=s.gm.fresh_key())
    assert response.status_code == status, (path, response.text)
    return response.json()


def version(s: ContentSetup, entity_id: str) -> int:
    value = s.connection.execute(
        text("SELECT row_version FROM core.entities WHERE entity_id = :e"), {"e": entity_id}
    ).scalar()
    assert isinstance(value, int)
    return value


def draft_place(s: ContentSetup, name: str = "Draft Place") -> str:
    return post(s, "locations", {"category": "region", "name": name})["location_id"]


def species(s: ContentSetup) -> str:
    return s.gm.get(s.url("npcs/options")).json()["species"][0]["species_id"]


def add_structure(s: ContentSetup, quest_id: str, target: str | None = None) -> None:
    quest = s.gm.get(s.url(f"quests/{quest_id}")).json()
    stage = post(
        s,
        f"quests/{quest_id}/stages",
        {"expected_row_version": quest["row_version"], "name": "Stage", "stage_type": "sequential"},
        200,
    )
    post(
        s,
        f"quests/{quest_id}/stages/{stage['stages'][0]['quest_stage_id']}/objectives",
        {
            "expected_row_version": stage["row_version"],
            "name": "Objective",
            "objective_type": "other",
            "requirement_level": "required",
            "completion_mode": "automatic",
            "visibility_policy": "visible",
            "target_entity_id": target,
        },
        200,
    )


@dataclass
class Case:
    old: str
    replacement: str
    code: str
    # Makes the precondition true without touching either entity's lifecycle state
    # beyond what publishing the reference or completing the quest requires.
    fix: Callable[[], None]


def _publish_reference(s: ContentSetup, entity_id: str) -> Callable[[], None]:
    return lambda: s.publish(entity_id, version(s, entity_id))


def _finish(s: ContentSetup, old: str, replacement: str) -> None:
    s.set_status(old, canon="canon")
    s.set_status(replacement, canon="approved")


def quest_incomplete(s: ContentSetup) -> Case:
    old = post(s, "quests", {"name": "Old quest", "summary": None})["quest_id"]
    new = post(s, "quests", {"name": "New quest", "summary": None})["quest_id"]
    _finish(s, old, new)

    def fix() -> None:
        s.set_status(new, canon="draft")
        add_structure(s, new)
        s.set_status(new, canon="approved")

    return Case(old, new, "quest_definition_incomplete", fix)


def quest_target_draft(s: ContentSetup) -> Case:
    target = draft_place(s, "Target")
    old = post(s, "quests", {"name": "Old quest", "summary": None})["quest_id"]
    new = post(s, "quests", {"name": "New quest", "summary": None})["quest_id"]
    add_structure(s, new, target)
    _finish(s, old, new)
    return Case(old, new, "reference_not_published", _publish_reference(s, target))


def location_parent_draft(s: ContentSetup) -> Case:
    parent = draft_place(s, "Parent")
    old = post(s, "locations", {"category": "settlement", "name": "Old town"})["location_id"]
    new = post(
        s,
        "locations",
        {"category": "settlement", "name": "New town", "parent_location_id": parent},
    )["location_id"]
    _finish(s, old, new)
    return Case(old, new, "reference_not_published", _publish_reference(s, parent))


def organization_parent_draft(s: ContentSetup) -> Case:
    parent = post(s, "organizations", {"kind": "government", "name": "Parent gov"})[
        "organization_id"
    ]
    old = post(s, "organizations", {"kind": "government", "name": "Old gov"})["organization_id"]
    new = post(
        s,
        "organizations",
        {"kind": "government", "name": "New gov", "parent_organization_id": parent},
    )["organization_id"]
    _finish(s, old, new)
    return Case(old, new, "reference_not_published", _publish_reference(s, parent))


def organization_headquarters_draft(s: ContentSetup) -> Case:
    hq = draft_place(s, "HQ")
    old = post(s, "organizations", {"kind": "government", "name": "Old gov"})["organization_id"]
    new = post(
        s,
        "organizations",
        {"kind": "government", "name": "New gov", "headquarters_location_id": hq},
    )["organization_id"]
    _finish(s, old, new)
    return Case(old, new, "reference_not_published", _publish_reference(s, hq))


def organization_religion_draft(s: ContentSetup) -> Case:
    def religion(name: str) -> str:
        return post(s, "religions", {"name": name, "summary": None, "pantheon_structure": None})[
            "religion_id"
        ]

    def chapter(name: str, religion_id: str) -> str:
        return post(
            s,
            "organizations",
            {"kind": "religious_organization", "name": name, "religion_id": religion_id},
        )["organization_id"]

    faith = religion("Faith")
    old = chapter("Old chapter", religion("Other faith"))
    new = chapter("New chapter", faith)
    _finish(s, old, new)
    return Case(old, new, "reference_not_published", _publish_reference(s, faith))


def npc_origin_draft(s: ContentSetup) -> Case:
    origin = draft_place(s, "Origin")

    def npc(name: str, origin_id: str | None) -> str:
        return post(
            s,
            "npcs",
            {
                "name": name,
                "species_id": species(s),
                "size_category": "medium",
                "origin_location_id": origin_id,
            },
        )["npc_id"]

    old, new = npc("Old npc", None), npc("New npc", origin)
    _finish(s, old, new)
    return Case(old, new, "reference_not_published", _publish_reference(s, origin))


def knowledge_subject_draft(s: ContentSetup) -> Case:
    subject = draft_place(s, "Subject")

    def claim(statement: str, subject_id: str | None) -> str:
        return post(
            s,
            "knowledge",
            {
                "statement": statement,
                "knowledge_type": "secret",
                "truth_status": "true",
                "sensitivity": "secret",
                "subject_entity_id": subject_id,
            },
        )["knowledge_item_id"]

    old, new = claim("Old claim.", None), claim("New claim.", subject)
    _finish(s, old, new)
    return Case(old, new, "reference_not_published", _publish_reference(s, subject))


CASES = [
    quest_incomplete,
    quest_target_draft,
    location_parent_draft,
    organization_parent_draft,
    organization_headquarters_draft,
    organization_religion_draft,
    npc_origin_draft,
    knowledge_subject_draft,
]


def supersede(s: ContentSetup, case: Case, key: str | None = None):  # type: ignore[no-untyped-def]
    return s.gm.post(
        s.lifecycle(case.old, "/supersede"),
        {
            "expected_row_version": version(s, case.old),
            "replacement_entity_id": case.replacement,
            "replacement_expected_row_version": version(s, case.replacement),
        },
        key=key or s.gm.fresh_key(),
    )


def idempotent_rows(s: ContentSetup) -> int:
    value = s.connection.execute(
        text("SELECT count(*) FROM security.idempotent_requests WHERE campaign_id = :c"),
        {"c": s.cid},
    ).scalar()
    assert isinstance(value, int)
    return value


def state(s: ContentSetup, *ids: str) -> list[tuple[str, str, int]]:
    out = []
    for entity_id in ids:
        row = s.connection.execute(
            text("""
                SELECT cs.code, ls.code, e.row_version
                FROM core.entities e
                JOIN core.canon_statuses cs ON cs.canon_status_id = e.canon_status_id
                JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = e.lifecycle_status_id
                WHERE e.entity_id = :e
            """),
            {"e": entity_id},
        ).one()
        out.append((str(row[0]), str(row[1]), int(row[2])))
    return out


@pytest.mark.parametrize("build", CASES, ids=lambda f: f.__name__)
def test_supersession_cannot_publish_an_approved_replacement_that_ordinary_publish_refuses(
    s: ContentSetup, build: Callable[[ContentSetup], Case]
) -> None:
    case = build(s)
    before = state(s, case.old, case.replacement)
    audit_before = s.count("audit.change_log")
    rows_before = idempotent_rows(s)

    # Ordinary publish refuses with the same code (the contract being matched).
    direct = s.gm.post(
        s.lifecycle(case.replacement, "/publish"),
        {"expected_row_version": version(s, case.replacement)},
        key=s.gm.fresh_key(),
    )
    assert direct.status_code == 409 and direct.json()["error"]["code"] == case.code

    key = s.gm.fresh_key()
    refused = supersede(s, case, key)
    assert refused.status_code == 409, refused.text
    assert refused.json()["error"]["code"] == case.code

    assert state(s, case.old, case.replacement) == before  # status and row versions
    assert s.audit("supersede_entity") == []
    assert s.count("audit.change_log") == audit_before
    assert idempotent_rows(s) == rows_before  # no reserved or completed request

    case.fix()
    retry = supersede(s, case, key)  # the same key: the failure left no reservation behind
    assert retry.status_code == 200, retry.text
    assert state(s, case.old)[0][0] == "superseded"
    assert state(s, case.replacement)[0][0] == "canon"
    assert len(s.audit("supersede_entity")) == 2


def test_a_replacement_that_depends_on_the_record_being_superseded_is_refused(
    s: ContentSetup,
) -> None:
    parent = post(s, "locations", {"category": "region", "name": "Old region"})["location_id"]
    child = post(
        s,
        "locations",
        {"category": "region", "name": "Town", "parent_location_id": parent},
    )["location_id"]
    s.set_status(parent, canon="canon")
    s.set_status(child, canon="approved")
    case = Case(parent, child, "reference_not_published", lambda: None)
    before = state(s, parent, child)
    response = supersede(s, case)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "reference_not_published"
    assert state(s, parent, child) == before


def test_a_canon_replacement_stays_valid_under_the_existing_reference_policy(
    s: ContentSetup,
) -> None:
    parent = draft_place(s, "Parent")
    old = post(s, "locations", {"category": "settlement", "name": "Old"})["location_id"]
    new = post(
        s,
        "locations",
        {"category": "settlement", "name": "New", "parent_location_id": parent},
    )["location_id"]
    s.set_status(old, canon="canon")
    s.set_status(new, canon="canon")  # already published: not re-validated
    response = supersede(s, Case(old, new, "", lambda: None))
    assert response.status_code == 200, response.text
    assert state(s, old)[0][0] == "superseded" and state(s, new)[0][0] == "canon"


def test_candidates_hide_approved_replacements_that_cannot_be_published(
    s: ContentSetup,
) -> None:
    old = post(s, "locations", {"category": "settlement", "name": "Old"})["location_id"]
    parent = draft_place(s, "Parent")
    blocked = post(
        s,
        "locations",
        {"category": "settlement", "name": "A blocked", "parent_location_id": parent},
    )["location_id"]
    usable = post(s, "locations", {"category": "settlement", "name": "B usable"})["location_id"]
    s.set_status(old, canon="canon")
    s.set_status(blocked, canon="approved")
    s.set_status(usable, canon="approved")

    def names(**params: object) -> list[str]:
        response = s.gm.get(s.lifecycle(old, "/replacement-candidates"), **params)
        assert response.status_code == 200
        return [c["canonical_name"] for c in response.json()["items"]]

    assert names() == ["B usable"]
    # A page of one still finds the usable record past the unusable one.
    page = s.gm.get(s.lifecycle(old, "/replacement-candidates"), limit=1).json()
    assert [c["canonical_name"] for c in page["items"]] == ["B usable"]
    assert page["next_cursor"] is None

    s.publish(parent, version(s, parent))
    assert names() == ["A blocked", "B usable"]
    # What is offered is what the command accepts.
    offered = s.gm.get(s.lifecycle(old, "/replacement-candidates")).json()["items"]
    assert supersede(s, Case(old, offered[0]["entity_id"], "", lambda: None)).status_code == 200


def test_candidates_keep_a_canon_replacement_and_hide_an_incomplete_approved_quest(
    s: ContentSetup,
) -> None:
    old = post(s, "quests", {"name": "Old quest", "summary": None})["quest_id"]
    incomplete = post(s, "quests", {"name": "A incomplete", "summary": None})["quest_id"]
    published = post(s, "quests", {"name": "B published", "summary": None})["quest_id"]
    s.set_status(old, canon="canon")
    s.set_status(incomplete, canon="approved")
    s.set_status(published, canon="canon")  # canon is never re-validated
    response = s.gm.get(s.lifecycle(old, "/replacement-candidates"))
    assert [c["canonical_name"] for c in response.json()["items"]] == ["B published"]


def test_candidates_do_not_offer_a_replacement_that_depends_on_the_superseded_record(
    s: ContentSetup,
) -> None:
    parent = post(s, "locations", {"category": "region", "name": "Old region"})["location_id"]
    child = post(
        s,
        "locations",
        {"category": "region", "name": "Child", "parent_location_id": parent},
    )["location_id"]
    s.set_status(parent, canon="canon")
    s.set_status(child, canon="approved")
    response = s.gm.get(s.lifecycle(parent, "/replacement-candidates"))
    assert response.json()["items"] == []
