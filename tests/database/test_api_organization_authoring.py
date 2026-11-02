"""HTTP contract and command behavior for typed Organization and Religion
authoring (Phase 15.1)."""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, text

from tests.authoring_support import AuthoringHarness, harness_fixture_factory
from tests.content_support import ContentSetup
from tests.factories import make_location, make_organization, make_religion, make_world

pytestmark = pytest.mark.database

KINDS = [
    "organization",
    "business",
    "government",
    "military_unit",
    "political_faction",
    "religious_organization",
]


@pytest.fixture
def harness(db_connection: Connection) -> Iterator[AuthoringHarness]:
    yield from harness_fixture_factory()(db_connection)


@pytest.fixture
def s(harness: AuthoringHarness, db_connection: Connection) -> ContentSetup:
    return ContentSetup(harness, db_connection)


def make_religion_via_api(s: ContentSetup, name: str = "The Old Way") -> dict:
    response = s.gm.post(
        s.url("religions"),
        {"name": name, "summary": None, "pantheon_structure": "Nine gods"},
        key=s.gm.fresh_key(),
    )
    assert response.status_code == 201, response.text
    return response.json()


def create(s: ContentSetup, kind: str = "organization", name: str = "Org", **extra: object) -> dict:
    body: dict[str, object] = {"kind": kind, "name": name}
    if kind == "organization":
        body["organization_type"] = "guild"
    if kind == "religious_organization" and "religion_id" not in extra:
        body["religion_id"] = make_religion_via_api(s)["religion_id"]
    body.update(extra)
    response = s.gm.post(s.url("organizations"), body, key=s.gm.fresh_key())
    assert response.status_code == 201, response.text
    return response.json()


def update(s: ContentSetup, org: dict, **fields: object) -> object:
    typed = org["typed"]
    body: dict[str, object] = {
        "expected_row_version": org["row_version"],
        "name": org["name"],
        "summary": org["summary"],
        "public_description": org["public_description"],
        "internal_description": org["internal_description"],
        "parent_organization_id": org["parent"] and org["parent"]["entity_id"],
        "headquarters_location_id": org["headquarters"] and org["headquarters"]["entity_id"],
        "religion_id": org["religion"] and org["religion"]["entity_id"],
        **typed,
        **fields,
    }
    return s.gm.post(
        s.url(f"organizations/{org['organization_id']}/update"), body, key=s.gm.fresh_key()
    )


def location(s: ContentSetup, name: str = "Keep", category: str = "building") -> dict:
    response = s.gm.post(
        s.url("locations"), {"category": category, "name": name}, key=s.gm.fresh_key()
    )
    assert response.status_code == 201
    return response.json()


# --- create -----------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", KINDS)
def test_each_kind_creates_a_complete_draft_with_the_right_types(
    s: ContentSetup, kind: str
) -> None:
    view = create(s, kind, f"A {kind}")
    assert view["kind"]["code"] == kind
    assert (view["canon_status"], view["lifecycle_status"], view["changed"]) == (
        "draft",
        "active",
        True,
    )
    row = s.connection.execute(
        text("""
            SELECT et.code AS entity_type, ot.code AS organization_type, e.created_by_user_id,
                   st.code AS source_type
            FROM core.entities e
            JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id
            JOIN world.organizations o ON o.organization_id = e.entity_id
            JOIN world.organization_types ot ON ot.organization_type_id = o.organization_type_id
            JOIN core.sources src ON src.source_id = e.source_id
            JOIN core.source_types st ON st.source_type_id = src.source_type_id
            WHERE e.entity_id = :e
        """),
        {"e": view["organization_id"]},
    ).one()
    expected_type = "guild" if kind == "organization" else kind
    assert (row.entity_type, row.organization_type, row.source_type) == (
        kind,
        expected_type,
        "gm_entry",
    )
    assert row.created_by_user_id == s.gm.user_id
    assert view["organization_type"] == expected_type


def test_the_generic_kind_chooses_among_the_four_untyped_organization_types(
    s: ContentSetup,
) -> None:
    for chosen in ("guild", "criminal_organization", "secret_society", "other"):
        assert (
            create(s, "organization", chosen, organization_type=chosen)["organization_type"]
            == chosen
        )
    for bad in ("government", "business", "religious_organization", "nonsense", None):
        response = s.gm.post(
            s.url("organizations"),
            {"kind": "organization", "name": "x", "organization_type": bad},
            key=s.gm.fresh_key(),
        )
        assert response.status_code == 400, bad


def test_a_typed_kind_cannot_choose_its_organization_type(s: ContentSetup) -> None:
    response = s.gm.post(
        s.url("organizations"),
        {"kind": "government", "name": "x", "organization_type": "guild"},
        key=s.gm.fresh_key(),
    )
    assert response.status_code == 400


def test_business_fields_and_defaults(s: ContentSetup) -> None:
    view = create(s, "business", "Shop", business_type="Forge", reputation=40)
    assert view["typed"] == {
        "business_type": "Forge",
        "operating_status": "operating",
        "reputation": 40,
    }
    closed = create(s, "business", "Closed shop", operating_status="closed")
    assert closed["typed"]["operating_status"] == "closed"
    for bad in ({"operating_status": "thriving"}, {"reputation": 101}, {"reputation": -101}):
        response = s.gm.post(
            s.url("organizations"), {"kind": "business", "name": "x", **bad}, key=s.gm.fresh_key()
        )
        assert response.status_code in (400, 422), bad


@pytest.mark.parametrize(
    ("kind", "field"),
    [
        ("government", "government_form"),
        ("military_unit", "unit_type"),
        ("political_faction", "ideology"),
    ],
)
def test_each_kind_carries_its_own_typed_field(s: ContentSetup, kind: str, field: str) -> None:
    view = create(s, kind, "Typed", **{field: "Value"})
    assert view["typed"] == {field: "Value"}


@pytest.mark.parametrize(
    ("kind", "foreign"),
    [
        ("government", "unit_type"),
        ("military_unit", "business_type"),
        ("political_faction", "government_form"),
        ("organization", "ideology"),
        ("religious_organization", "reputation"),
    ],
)
def test_a_field_that_does_not_apply_to_the_kind_is_refused(
    s: ContentSetup, kind: str, foreign: str
) -> None:
    body: dict[str, object] = {
        "kind": kind,
        "name": "x",
        foreign: 5 if foreign == "reputation" else "v",
    }
    if kind == "organization":
        body["organization_type"] = "guild"
    if kind == "religious_organization":
        body["religion_id"] = make_religion_via_api(s)["religion_id"]
    response = s.gm.post(s.url("organizations"), body, key=s.gm.fresh_key())
    assert response.status_code == 400


def test_a_religious_organization_needs_a_religion_and_no_other_kind_takes_one(
    s: ContentSetup,
) -> None:
    missing = s.gm.post(
        s.url("organizations"),
        {"kind": "religious_organization", "name": "x"},
        key=s.gm.fresh_key(),
    )
    assert missing.status_code == 400 and missing.json()["error"]["code"] == "validation_failed"
    religion = make_religion_via_api(s)
    extra = s.gm.post(
        s.url("organizations"),
        {"kind": "government", "name": "x", "religion_id": religion["religion_id"]},
        key=s.gm.fresh_key(),
    )
    assert extra.status_code == 400


@pytest.mark.parametrize("kind", ["dungeon", "npc", "location", "religion", "bogus", ""])
def test_kinds_outside_the_closed_set_are_refused(s: ContentSetup, kind: str) -> None:
    response = s.gm.post(s.url("organizations"), {"kind": kind, "name": "x"}, key=s.gm.fresh_key())
    assert response.status_code in (400, 422)


@pytest.mark.parametrize(
    "body",
    [
        {"kind": "government", "name": ""},
        {"kind": "government", "name": "x" * 201},
        {"kind": "government", "name": "x", "public_description": "y" * 4001},
        {"kind": "government", "name": "x", "world_id": str(uuid.uuid4())},
        {"kind": "government", "name": "x", "entity_type_code": "npc"},
        {"name": "no kind"},
    ],
)
def test_malformed_bodies_write_nothing(s: ContentSetup, body: dict) -> None:
    before = s.count("core.entities")
    response = s.gm.post(s.url("organizations"), body, key=s.gm.fresh_key())
    assert response.status_code in (400, 422)
    assert s.count("core.entities") == before


def test_create_audits_once_and_writes_no_state(s: ContentSetup) -> None:
    states = {t: s.count(t) for t in ("campaign.organization_state", "narrative.events")}
    view = create(s, "government", "Crown", government_form="Monarchy")
    rows = s.audit("create_organization")
    assert len(rows) == 1 and rows[0].action == "created"
    assert str(rows[0].entity_id) == view["organization_id"] and rows[0].source_id is not None
    assert rows[0].changed_fields["kind"] == "government"
    assert states == {t: s.count(t) for t in states}


def test_a_failure_after_the_root_insert_leaves_no_rows(
    s: ContentSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    import dnd_ai.commands.organizations as organizations

    def boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("injected failure after the organization row")

    monkeypatch.setattr(organizations, "_insert_subtype_rows", boom)
    tables = (
        "core.entities",
        "core.sources",
        "world.organizations",
        "world.governments",
        "audit.change_log",
        "security.idempotent_requests",
    )
    before = {t: s.count(t) for t in tables}
    response = s.gm.post(
        s.url("organizations"), {"kind": "government", "name": "Doomed"}, key=s.gm.fresh_key()
    )
    assert response.status_code == 500
    assert before == {t: s.count(t) for t in tables}


# --- references and hierarchy ------------------------------------------------------------------


def test_references_resolve_to_names_and_cross_world_ids_look_like_missing_ones(
    s: ContentSetup,
) -> None:
    parent = create(s, "government", "Crown")
    hq = location(s, "Castle")
    religion = make_religion_via_api(s)
    view = create(
        s,
        "religious_organization",
        "Temple",
        parent_organization_id=parent["organization_id"],
        headquarters_location_id=hq["location_id"],
        religion_id=religion["religion_id"],
    )
    assert view["parent"]["name"] == "Crown"
    assert view["headquarters"]["name"] == "Castle"
    assert view["religion"]["name"] == "The Old Way"

    other = make_world(s.connection, "org-foreign")
    foreign = {
        "organization_parent_invalid": (
            "parent_organization_id",
            str(make_organization(s.connection, other)),
        ),
        "headquarters_location_invalid": (
            "headquarters_location_id",
            str(make_location(s.connection, other)),
        ),
        "religion_invalid": ("religion_id", str(make_religion(s.connection, other))),
    }
    for code, (field, value) in foreign.items():
        body: dict[str, object] = {
            "kind": "religious_organization",
            "name": "x",
            "religion_id": religion["religion_id"],
        }
        body[field] = value
        response = s.gm.post(s.url("organizations"), body, key=s.gm.fresh_key())
        assert response.status_code == 400 and response.json()["error"]["code"] == code, code
        missing = dict(body)
        missing[field] = str(uuid.uuid4())
        again = s.gm.post(s.url("organizations"), missing, key=s.gm.fresh_key())
        assert again.json()["error"] == {
            **response.json()["error"],
            "correlation_id": again.json()["error"]["correlation_id"],
        }


def test_wrong_typed_and_unusable_references_share_one_code(s: ContentSetup) -> None:
    location_view = location(s, "Wrong type")
    gone = create(s, "government", "Gone")
    s.transition(gone["organization_id"], "archive", gone["row_version"])
    rejected = create(s, "government", "Rejected")
    s.set_status(rejected["organization_id"], canon="rejected")
    attempts = [
        {"parent_organization_id": location_view["location_id"]},
        {"parent_organization_id": gone["organization_id"]},
        {"parent_organization_id": rejected["organization_id"]},
    ]
    codes = set()
    for extra in attempts:
        response = s.gm.post(
            s.url("organizations"),
            {"kind": "government", "name": "x", **extra},
            key=s.gm.fresh_key(),
        )
        assert response.status_code == 400
        codes.add(response.json()["error"]["code"])
    assert codes == {"organization_parent_invalid"}
    religion_as_hq = s.gm.post(
        s.url("organizations"),
        {
            "kind": "government",
            "name": "x",
            "headquarters_location_id": make_religion_via_api(s)["religion_id"],
        },
        key=s.gm.fresh_key(),
    )
    assert religion_as_hq.json()["error"]["code"] == "headquarters_location_invalid"


def test_self_parent_and_cycles_are_refused_with_a_classified_error(s: ContentSetup) -> None:
    a = create(s, "government", "A")
    b = create(s, "military_unit", "B", parent_organization_id=a["organization_id"])
    c = create(s, "business", "C", parent_organization_id=b["organization_id"])
    for target in (a["organization_id"], b["organization_id"], c["organization_id"]):
        current = s.gm.get(s.url(f"organizations/{a['organization_id']}")).json()
        response = update(s, current, parent_organization_id=target)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "organization_hierarchy_cycle"
    assert s.gm.get(s.url(f"organizations/{a['organization_id']}")).json()["parent"] is None
    assert s.audit("update_organization") == []


def test_reparenting_updates_and_audits_ids_only(s: ContentSetup) -> None:
    p1 = create(s, "government", "P1")
    p2 = create(s, "government", "P2")
    child = create(s, "business", "Child", parent_organization_id=p1["organization_id"])
    view = update(s, child, parent_organization_id=p2["organization_id"]).json()
    assert view["parent"]["name"] == "P2"
    diff = s.audit("update_organization")[0].changed_fields["parent_organization_id"]
    assert diff == {"from": p1["organization_id"], "to": p2["organization_id"]}


def test_option_lists_exclude_self_descendants_unusable_and_other_worlds(s: ContentSetup) -> None:
    a = create(s, "government", "A")
    b = create(s, "business", "B", parent_organization_id=a["organization_id"])
    create(s, "military_unit", "C")
    gone = create(s, "government", "Gone")
    s.transition(gone["organization_id"], "archive", gone["row_version"])
    s.stranger.post(
        s.url("organizations", s.other_cid),
        {"kind": "government", "name": "Foreign"},
        key=s.stranger.fresh_key(),
    )

    def names(**params: object) -> list[str]:
        items = s.gm.get(s.url("organizations/parent-options"), **params).json()["items"]
        return [i["name"] for i in items]

    assert names() == ["A", "B", "C"]
    assert names(**{"for": a["organization_id"]}) == ["C"]
    assert names(**{"for": b["organization_id"]}) == ["A", "C"]
    assert s.gm.get(s.url("organizations/parent-options"), cursor="junk").status_code == 422


def test_the_options_catalog_describes_every_kind(s: ContentSetup) -> None:
    body = s.gm.get(s.url("organizations/options")).json()
    by_code = {k["code"]: k for k in body["kinds"]}
    assert set(by_code) == set(KINDS)
    assert by_code["religious_organization"]["needs_religion"] is True
    assert [f["name"] for f in by_code["business"]["fields"]] == [
        "business_type",
        "operating_status",
        "reputation",
    ]
    assert {o["value"] for o in by_code["organization"]["fields"][0]["options"]} == {
        "guild",
        "criminal_organization",
        "secret_society",
        "other",
    }


# --- update ---------------------------------------------------------------------------------------


def test_update_replaces_fields_and_audits_a_bounded_diff(s: ContentSetup) -> None:
    org = create(s, "business", "Old", business_type="Forge")
    view = update(
        s,
        org,
        name="New",
        public_description="Known for steel",
        internal_description="Fronts for the guild",
        business_type="Armoury",
        reputation=-20,
    ).json()
    assert (view["name"], view["typed"]["business_type"], view["typed"]["reputation"]) == (
        "New",
        "Armoury",
        -20,
    )
    assert view["internal_description"] == "Fronts for the guild"
    diff = s.audit("update_organization")[0].changed_fields
    assert diff["name"] == {"from": "Old", "to": "New"}
    assert diff["reputation"] == {"from": None, "to": -20}
    # Narrative fields are recorded as changed, never with their values.
    assert diff["internal_description"] == {"from": None, "to": {"redacted": True}}
    assert "Fronts for the guild" not in str(diff)
    assert "kind" not in diff


def test_no_op_stale_and_not_editable_updates(s: ContentSetup) -> None:
    org = create(s, "government", "Same", government_form="Council")
    again = update(s, org).json()
    assert again["changed"] is False and again["row_version"] == org["row_version"]
    assert s.audit("update_organization") == []

    first = update(s, org, name="First")
    assert first.status_code == 200
    stale = update(s, org, name="Second")
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "stale_write"

    s.set_status(org["organization_id"], canon="approved")
    current = s.gm.get(s.url(f"organizations/{org['organization_id']}")).json()
    locked = update(s, current, name="Third")
    assert locked.status_code == 409 and locked.json()["error"]["code"] == "content_not_editable"


def test_a_religious_organization_can_change_its_religion(s: ContentSetup) -> None:
    first = make_religion_via_api(s, "First faith")
    second = make_religion_via_api(s, "Second faith")
    org = create(s, "religious_organization", "Temple", religion_id=first["religion_id"])
    view = update(s, org, religion_id=second["religion_id"]).json()
    assert view["religion"]["name"] == "Second faith"
    assert s.connection.execute(
        text(
            "SELECT religion_id FROM world.religious_organizations WHERE religious_organization_id = :e"
        ),
        {"e": org["organization_id"]},
    ).scalar() == uuid.UUID(second["religion_id"])


def test_the_generic_kind_can_change_its_type_but_no_kind_changes_category(s: ContentSetup) -> None:
    org = create(s, "organization", "Order", organization_type="guild")
    view = update(s, org, organization_type="secret_society").json()
    assert view["organization_type"] == "secret_society" and view["kind"]["code"] == "organization"
    assert update(s, view, kind="government").status_code == 422


# --- publish preconditions ---------------------------------------------------------------------------


def test_publishing_waits_for_the_parent_headquarters_and_religion(s: ContentSetup) -> None:
    parent = create(s, "government", "Crown")
    hq = location(s, "Castle")
    religion = make_religion_via_api(s)
    org = create(
        s,
        "religious_organization",
        "Temple",
        parent_organization_id=parent["organization_id"],
        headquarters_location_id=hq["location_id"],
        religion_id=religion["religion_id"],
    )
    version = org["row_version"]
    for action in ("submit-for-review", "approve"):
        version = s.transition(org["organization_id"], action, version)["row_version"]

    def attempt() -> dict:
        response = s.gm.post(
            s.lifecycle(org["organization_id"], "/publish"),
            {"expected_row_version": version},
            key=s.gm.fresh_key(),
        )
        return {
            "status": response.status_code,
            "code": response.json().get("error", {}).get("code"),
        }

    assert attempt() == {"status": 409, "code": "reference_not_published"}
    view = s.gm.get(s.url(f"organizations/{org['organization_id']}")).json()
    assert {"action": "publish", "reason": "reference_not_published"} in view["blocked_actions"]
    s.publish(parent["organization_id"], parent["row_version"])
    assert attempt()["code"] == "reference_not_published"
    s.publish(hq["location_id"], hq["row_version"])
    assert attempt()["code"] == "reference_not_published"
    s.publish(religion["religion_id"], religion["row_version"])
    assert attempt() == {"status": 200, "code": None}


# --- authorization and cache ---------------------------------------------------------------------------


def test_players_and_strangers_are_refused_on_every_route(s: ContentSetup) -> None:
    org = create(s, "government", "Secret")
    religion = make_religion_via_api(s)
    paths = [
        ("get", s.url("organizations/options")),
        ("get", s.url("organizations/parent-options")),
        ("get", s.url(f"organizations/{org['organization_id']}")),
        ("post", s.url("organizations")),
        ("post", s.url(f"organizations/{org['organization_id']}/update")),
        ("get", s.url("religions/options")),
        ("get", s.url("religions/reference-options")),
        ("get", s.url(f"religions/{religion['religion_id']}")),
        ("post", s.url("religions")),
        ("post", s.url(f"religions/{religion['religion_id']}/update")),
    ]
    body = {"kind": "government", "name": "x", "expected_row_version": 1}
    for actor, expected in ((s.player, 403), (s.stranger, 404)):
        for method, path in paths:
            call = getattr(actor, method)
            response = call(path) if method == "get" else call(path, body, key=actor.fresh_key())
            assert response.status_code == expected, (actor.name, path)


def test_cross_world_organizations_and_religions_are_a_404(s: ContentSetup) -> None:
    foreign_org = s.stranger.post(
        s.url("organizations", s.other_cid),
        {"kind": "government", "name": "Foreign"},
        key=s.stranger.fresh_key(),
    ).json()
    foreign_religion = s.stranger.post(
        s.url("religions", s.other_cid), {"name": "Foreign faith"}, key=s.stranger.fresh_key()
    ).json()
    for path in (
        f"organizations/{foreign_org['organization_id']}",
        f"religions/{foreign_religion['religion_id']}",
        f"organizations/{uuid.uuid4()}",
    ):
        assert s.gm.get(s.url(path)).status_code == 404
    body = {"expected_row_version": 1, "name": "x"}
    assert (
        s.gm.post(s.url(f"organizations/{foreign_org['organization_id']}/update"), body).status_code
        == 404
    )
    assert (
        s.gm.post(s.url(f"religions/{foreign_religion['religion_id']}/update"), body).status_code
        == 404
    )
    assert (
        s.gm.post(
            s.lifecycle(foreign_org["organization_id"], "/archive"), {"expected_row_version": 1}
        ).status_code
        == 404
    )


def test_a_location_is_not_an_organization_route_target(s: ContentSetup) -> None:
    place = location(s)
    assert s.gm.get(s.url(f"organizations/{place['location_id']}")).status_code == 404
    assert s.gm.get(s.url(f"religions/{place['location_id']}")).status_code == 404


def test_authoring_reads_are_never_cacheable(s: ContentSetup) -> None:
    org = create(s, "government", "Cache")
    for path in (
        "organizations/options",
        f"organizations/{org['organization_id']}",
        "religions/options",
        "religions/reference-options",
    ):
        assert s.gm.get(s.url(path)).headers["cache-control"] == "no-store"


def test_replay_and_conflict_semantics(s: ContentSetup) -> None:
    body = {"kind": "government", "name": "Once"}
    first = s.gm.post(s.url("organizations"), body, key="org-1")
    second = s.gm.post(s.url("organizations"), body, key="org-1")
    assert first.status_code == second.status_code == 201 and first.json() == second.json()
    assert len(s.audit("create_organization")) == 1
    conflict = s.gm.post(
        s.url("organizations"), {"kind": "government", "name": "Other"}, key="org-1"
    )
    assert conflict.status_code == 409


# --- religions --------------------------------------------------------------------------------------------


def test_religion_lifecycle_of_authoring(s: ContentSetup) -> None:
    religion = make_religion_via_api(s, "Sun faith")
    assert religion["canon_status"] == "draft" and religion["pantheon_structure"] == "Nine gods"
    view = s.gm.post(
        s.url(f"religions/{religion['religion_id']}/update"),
        {
            "expected_row_version": religion["row_version"],
            "name": "Sun faith",
            "summary": "Worship of dawn",
            "pantheon_structure": "Nine gods",
        },
        key=s.gm.fresh_key(),
    ).json()
    assert view["summary"] == "Worship of dawn" and view["changed"] is True
    assert s.audit("update_religion")[0].changed_fields == {
        "summary": {"from": None, "to": {"redacted": True}}
    }
    noop = s.gm.post(
        s.url(f"religions/{religion['religion_id']}/update"),
        {
            "expected_row_version": view["row_version"],
            "name": "Sun faith",
            "summary": "Worship of dawn",
            "pantheon_structure": "Nine gods",
        },
        key=s.gm.fresh_key(),
    ).json()
    assert noop["changed"] is False
    options = s.gm.get(s.url("religions/reference-options")).json()["items"]
    assert [o["name"] for o in options] == ["Sun faith"]


def test_religion_reference_options_exclude_archived_and_other_worlds(s: ContentSetup) -> None:
    keep = make_religion_via_api(s, "Keep")
    gone = make_religion_via_api(s, "Gone")
    s.transition(gone["religion_id"], "archive", gone["row_version"])
    s.stranger.post(
        s.url("religions", s.other_cid), {"name": "Foreign"}, key=s.stranger.fresh_key()
    )
    items = s.gm.get(s.url("religions/reference-options")).json()["items"]
    assert [i["name"] for i in items] == ["Keep"]
    assert items[0]["religion_id"] == keep["religion_id"]


# --- audience-safe organization detail ------------------------------------------------------------------------


def test_player_detail_is_published_only_and_never_discloses_gm_text_or_draft_links(
    s: ContentSetup,
) -> None:
    draft_parent = create(s, "government", "Secret parent")
    draft_hq = location(s, "Secret hq")
    org = create(
        s,
        "business",
        "Public shop",
        public_description="Sells swords",
        internal_description="GM ONLY: fronts for assassins",
        parent_organization_id=draft_parent["organization_id"],
        headquarters_location_id=draft_hq["location_id"],
    )
    path = f"/campaigns/{s.cid}/world/organizations/{org['organization_id']}"
    assert s.player.get(path).status_code == 404  # still a draft
    s.set_status(org["organization_id"], canon="canon")
    detail = s.player.get(path)
    assert detail.status_code == 200
    body = detail.json()
    assert body["name"] == "Public shop" and body["public_description"] == "Sells swords"
    assert body["parent"] is None and body["headquarters"] is None
    assert "internal_description" not in body
    assert "GM ONLY" not in detail.text and "Secret parent" not in detail.text
    s.set_status(draft_parent["organization_id"], canon="canon")
    assert s.player.get(path).json()["parent"]["name"] == "Secret parent"
    gm_view = s.gm.get(s.url(f"organizations/{org['organization_id']}")).json()
    assert gm_view["internal_description"] == "GM ONLY: fronts for assassins"
    assert s.player.get(f"/campaigns/{s.cid}/audit-history").status_code == 403
    history = s.gm.get(f"/campaigns/{s.cid}/audit-history")
    assert history.status_code == 200
    assert "GM ONLY" not in history.text and "fronts for assassins" not in history.text


def test_a_missing_or_foreign_organization_detail_is_a_404(s: ContentSetup) -> None:
    foreign = make_organization(s.connection, make_world(s.connection, "org-detail-foreign"))
    for target in (foreign, uuid.uuid4()):
        assert s.gm.get(f"/campaigns/{s.cid}/world/organizations/{target}").status_code == 404
