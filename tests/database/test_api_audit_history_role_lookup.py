"""Regression tests for the audit-history previous-role lookup
(`dnd_ai.queries.audit_history`, the `prev_role` join): a system role and a
role of the audited campaign may legally share one `code`
(`security.roles`' `uq_roles_campaign_code` only scopes uniqueness to
`campaign_id`, and `ux_roles_system_code` only forbids two *system* roles
sharing one), while `audit.change_log.previous_status` records only that
code. Resolving the old role by code alone therefore matched *both* roles
and turned a single `change_membership_role` audit row into two response
items — same `change_log_id`, conflicting old-role labels — which also
consumed two page slots per event under `LIMIT`.

The fix resolves the exact predecessor assignment through the
`previous_membership_role_id` `dnd_ai.api.memberships` already records in
`changed_fields`. These tests drive that through the real assign/change
endpoints (so the audit rows have exactly the shape production writes) and
then read the history back through `GET /campaigns/{id}/audit-history`:

- system and campaign roles sharing a code, changing *from* each, *to* each,
  and directly between the two;
- exactly one item per `change_log_id`, with the correct old/new labels;
- page traversal at `limit=1` and at several multi-item limits, unique ids
  and identical coverage/order to the unpaginated read;
- legacy/missing/invalid predecessor metadata falls back to the recorded
  code (or "Unknown role") — never to a display name picked from the two
  candidates, and never to another campaign's or another membership's role;
- cross-campaign isolation and safe presentation (no `changed_fields` or
  predecessor id in any response body).

The pre-existing `test_api_audit_history.py` keeps covering the rest of the
endpoint's contract; its fixtures use distinct generated role codes, which is
precisely why it could not observe this defect."""

import uuid
from collections.abc import Callable, Iterator
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, text

from dnd_ai.api.app import create_app
from dnd_ai.api.audit import record_change_log
from dnd_ai.api.auth import get_authenticated_user_id
from dnd_ai.api.deps import get_engine
from tests.factories import (
    lookup_id,
    make_campaign,
    make_campaign_membership,
    make_membership_role,
    make_role,
    make_role_capability,
    make_timeline,
    make_user,
    make_world,
    oidc_principal,
)

pytestmark = pytest.mark.database

_SYSTEM_LABEL = "System Dup"
_CAMPAIGN_LABEL = "Campaign Dup"
_OTHER_CAMPAIGN_LABEL = "Other Campaign Dup"
_TARGET_ONE_LABEL = "Target One"
_TARGET_TWO_LABEL = "Target Two"


def _named_role(
    connection: Connection, *, campaign_id: uuid.UUID | None, code: str, display_name: str
) -> uuid.UUID:
    role_id = make_role(connection, campaign_id=campaign_id, code=code)
    connection.execute(
        text("UPDATE security.roles SET display_name = :n WHERE role_id = :r"),
        {"n": display_name, "r": role_id},
    )
    return role_id


class Fixture:
    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        access_manage_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "access.manage"
        )
        view_id = lookup_id(
            connection, "security", "capabilities", "capability_id", "campaign.view"
        )

        self.campaign_id = make_campaign(connection, self.timeline_id, "Role Lookup Campaign A")
        self.other_campaign_id = make_campaign(
            connection, self.timeline_id, "Role Lookup Campaign B"
        )

        self.shared_code = f"dup_{uuid.uuid4().hex[:8]}"
        # One system template and one role per campaign, all sharing one code
        # but carrying distinct display names so a wrong pick is visible.
        self.system_role_id = _named_role(
            connection, campaign_id=None, code=self.shared_code, display_name=_SYSTEM_LABEL
        )
        self.campaign_role_id = _named_role(
            connection,
            campaign_id=self.campaign_id,
            code=self.shared_code,
            display_name=_CAMPAIGN_LABEL,
        )
        self.other_campaign_role_id = _named_role(
            connection,
            campaign_id=self.other_campaign_id,
            code=self.shared_code,
            display_name=_OTHER_CAMPAIGN_LABEL,
        )
        self.target_one_id = _named_role(
            connection,
            campaign_id=self.campaign_id,
            code=f"one_{uuid.uuid4().hex[:8]}",
            display_name=_TARGET_ONE_LABEL,
        )
        self.target_two_id = _named_role(
            connection,
            campaign_id=self.campaign_id,
            code=f"two_{uuid.uuid4().hex[:8]}",
            display_name=_TARGET_TWO_LABEL,
        )

        def _admin(campaign_id: uuid.UUID, label: str) -> tuple[uuid.UUID, uuid.UUID]:
            role_id = make_role(
                connection, campaign_id=campaign_id, code=f"admin_{uuid.uuid4().hex[:8]}"
            )
            make_role_capability(connection, role_id, access_manage_id)
            make_role_capability(connection, role_id, view_id)
            user_id = make_user(connection, label)
            membership_id = make_campaign_membership(connection, campaign_id, user_id)
            make_membership_role(connection, membership_id, role_id)
            return user_id, membership_id

        self.admin_user_id, self.admin_membership_id = _admin(
            self.campaign_id, "Role Lookup Admin A"
        )
        self.other_admin_user_id, _ = _admin(self.other_campaign_id, "Role Lookup Admin B")

        self.member_user_id = make_user(connection, "Role Lookup Member A")
        self.member_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.member_user_id
        )
        self.second_member_user_id = make_user(connection, "Role Lookup Second Member A")
        self.second_member_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.second_member_user_id
        )
        self.other_member_user_id = make_user(connection, "Role Lookup Member B")
        self.other_member_membership_id = make_campaign_membership(
            connection, self.other_campaign_id, self.other_member_user_id
        )

    @property
    def user_ids(self) -> list[uuid.UUID]:
        return [
            self.admin_user_id,
            self.other_admin_user_id,
            self.member_user_id,
            self.second_member_user_id,
            self.other_member_user_id,
        ]


@pytest.fixture
def f(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as connection:
        fixture = Fixture(connection, f"audit-role-lookup-{uuid.uuid4().hex[:8]}")
    yield fixture
    with postgres_engine.begin() as cleanup:
        cleanup.execute(text("SET LOCAL session_replication_role = replica"))
        cleanup.execute(
            text("DELETE FROM audit.change_log WHERE world_id = :w"), {"w": fixture.world_id}
        )
        cleanup.execute(
            text("""
                DELETE FROM security.membership_roles WHERE campaign_membership_id IN (
                    SELECT campaign_membership_id FROM security.campaign_memberships
                    WHERE campaign_id IN (
                        SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t
                    )
                )
            """),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM security.role_capabilities WHERE role_id IN (
                    SELECT role_id FROM security.roles
                    WHERE campaign_id IN (
                        SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t
                    ) OR role_id = :system_role
                )
            """),
            {"t": fixture.timeline_id, "system_role": fixture.system_role_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM security.roles
                WHERE campaign_id IN (
                    SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t
                ) OR role_id = :system_role
            """),
            {"t": fixture.timeline_id, "system_role": fixture.system_role_id},
        )
        cleanup.execute(
            text("""
                DELETE FROM security.campaign_memberships WHERE campaign_id IN (
                    SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :t
                )
            """),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text("DELETE FROM campaign.campaigns WHERE timeline_id = :t"),
            {"t": fixture.timeline_id},
        )
        cleanup.execute(
            text("DELETE FROM core.worlds WHERE world_id = :w"), {"w": fixture.world_id}
        )
        cleanup.execute(
            text("DELETE FROM security.users WHERE user_id = ANY(:users)"),
            {"users": fixture.user_ids},
        )


@pytest.fixture
def client_factory(postgres_engine: Engine) -> Callable[[uuid.UUID], TestClient]:
    def _make(user_id: uuid.UUID) -> TestClient:
        app = create_app()
        app.dependency_overrides[get_engine] = lambda: postgres_engine
        app.dependency_overrides[get_authenticated_user_id] = lambda: oidc_principal(user_id)
        return TestClient(app, raise_server_exceptions=False)

    return _make


def _history_url(campaign_id: uuid.UUID, **params: object) -> str:
    query = "&".join(f"{k}={quote(str(v), safe='')}" for k, v in params.items() if v is not None)
    base = f"/campaigns/{campaign_id}/audit-history"
    return f"{base}?{query}" if query else base


def _assign(
    client: TestClient, campaign_id: uuid.UUID, membership_id: uuid.UUID, role_id: uuid.UUID
) -> uuid.UUID:
    response = client.post(
        f"/campaigns/{campaign_id}/memberships/{membership_id}/roles",
        json={"role_id": str(role_id)},
    )
    assert response.status_code == 201, response.text
    return uuid.UUID(response.json()["membership_role_id"])


def _change(
    client: TestClient,
    campaign_id: uuid.UUID,
    membership_role_id: uuid.UUID,
    new_role_id: uuid.UUID,
) -> uuid.UUID:
    response = client.post(
        f"/campaigns/{campaign_id}/memberships/roles/{membership_role_id}/change",
        json={"new_role_id": str(new_role_id)},
    )
    assert response.status_code == 201, response.text
    return uuid.UUID(response.json()["membership_role_id"])


# Newest-first: what `GET .../audit-history?category=role` must return for the
# chain `chain` below drives, oldest event last.
_EXPECTED_CHAIN_SUMMARIES_NEWEST_FIRST = [
    f"{_CAMPAIGN_LABEL} → {_SYSTEM_LABEL}",  # C -> S (both share the code)
    f"{_SYSTEM_LABEL} → {_CAMPAIGN_LABEL}",  # S -> C (both share the code)
    f"{_TARGET_TWO_LABEL} → {_SYSTEM_LABEL}",  # T2 -> S
    f"{_CAMPAIGN_LABEL} → {_TARGET_TWO_LABEL}",  # C -> T2
    f"{_TARGET_ONE_LABEL} → {_CAMPAIGN_LABEL}",  # T1 -> C
    f"{_SYSTEM_LABEL} → {_TARGET_ONE_LABEL}",  # S -> T1
    _SYSTEM_LABEL,  # the initial assignment of S
]


@pytest.fixture
def chain(f: Fixture, client_factory: Callable[[uuid.UUID], TestClient]) -> Fixture:
    """Drives one membership through every kind of change between a system
    role and a same-coded campaign role, through the real endpoints, then
    adds an unrelated same-coded change in campaign B (isolation target)."""
    with client_factory(f.admin_user_id) as client:
        current = _assign(client, f.campaign_id, f.member_membership_id, f.system_role_id)
        for new_role_id in (
            f.target_one_id,  # S  -> T1
            f.campaign_role_id,  # T1 -> C
            f.target_two_id,  # C  -> T2
            f.system_role_id,  # T2 -> S
            f.campaign_role_id,  # S  -> C (same code on both sides)
            f.system_role_id,  # C  -> S (same code on both sides)
        ):
            current = _change(client, f.campaign_id, current, new_role_id)
    with client_factory(f.other_admin_user_id) as client:
        other = _assign(
            client, f.other_campaign_id, f.other_member_membership_id, f.other_campaign_role_id
        )
        _change(client, f.other_campaign_id, other, f.system_role_id)
    return f


def _read_all(
    client: TestClient, campaign_id: uuid.UUID, *, limit: int, category: str | None = None
) -> list[list[dict[str, object]]]:
    """Walks every page from the first to the last, returning the pages."""
    pages: list[list[dict[str, object]]] = []
    cursor: str | None = None
    for _ in range(100):  # a runaway cursor loop fails loudly instead of hanging
        response = client.get(
            _history_url(campaign_id, limit=limit, category=category, cursor=cursor)
        )
        assert response.status_code == 200, response.text
        body = response.json()
        pages.append(body["items"])
        cursor = body["next_cursor"]
        if cursor is None:
            return pages
    raise AssertionError("audit-history pagination did not terminate")


def _flatten(pages: list[list[dict[str, object]]]) -> list[dict[str, object]]:
    return [item for page in pages for item in page]


# ---------------------------------------------------------------------------
# A shared code no longer duplicates or mislabels role changes
# ---------------------------------------------------------------------------


def test_the_fixture_really_has_a_system_and_a_campaign_role_sharing_a_code(
    postgres_engine: Engine, f: Fixture
) -> None:
    # Guards the premise: if the schema ever forbade this, the regression
    # tests below would silently stop proving anything.
    with postgres_engine.connect() as connection:
        rows = connection.execute(
            text("SELECT campaign_id FROM security.roles WHERE code = :c ORDER BY display_name"),
            {"c": f.shared_code},
        ).all()
    assert len(rows) == 3
    assert sum(1 for (campaign_id,) in rows if campaign_id is None) == 1


def test_every_role_change_is_exactly_one_item_with_the_correct_labels(
    client_factory: Callable[[uuid.UUID], TestClient], chain: Fixture
) -> None:
    with client_factory(chain.admin_user_id) as client:
        response = client.get(_history_url(chain.campaign_id, category="role", limit=100))
    assert response.status_code == 200
    items = response.json()["items"]
    ids = [item["change_log_id"] for item in items]
    assert len(ids) == len(set(ids)), f"duplicate change_log_id in {ids}"
    assert [item["change_summary"] for item in items] == _EXPECTED_CHAIN_SUMMARIES_NEWEST_FIRST
    assert all(item["target_label"] == "Role Lookup Member A" for item in items)
    assert [item["action_label"] for item in items] == [
        *["Role changed"] * 6,
        "Role added",
    ]


def test_the_unfiltered_history_has_the_same_unique_role_items(
    client_factory: Callable[[uuid.UUID], TestClient], chain: Fixture
) -> None:
    with client_factory(chain.admin_user_id) as client:
        items = client.get(_history_url(chain.campaign_id, limit=100)).json()["items"]
    ids = [item["change_log_id"] for item in items]
    assert len(ids) == len(set(ids))
    assert [item["change_summary"] for item in items] == _EXPECTED_CHAIN_SUMMARIES_NEWEST_FIRST


def test_a_limit_of_one_walks_every_event_exactly_once_in_order(
    client_factory: Callable[[uuid.UUID], TestClient], chain: Fixture
) -> None:
    with client_factory(chain.admin_user_id) as client:
        pages = _read_all(client, chain.campaign_id, limit=1)
        full = client.get(_history_url(chain.campaign_id, limit=100)).json()["items"]
    # A duplicated row would either show up as a repeated id or as a page
    # with more (or fewer) than the single item limit=1 promises.
    assert [len(page) for page in pages] == [1] * len(_EXPECTED_CHAIN_SUMMARIES_NEWEST_FIRST)
    flat = _flatten(pages)
    ids = [item["change_log_id"] for item in flat]
    assert len(ids) == len(set(ids))
    assert ids == [item["change_log_id"] for item in full]
    assert [item["change_summary"] for item in flat] == _EXPECTED_CHAIN_SUMMARIES_NEWEST_FIRST


@pytest.mark.parametrize("limit", [2, 3, 4, 6, 7])
def test_multi_item_pages_cover_the_same_events_in_the_same_order(
    client_factory: Callable[[uuid.UUID], TestClient], chain: Fixture, limit: int
) -> None:
    total = len(_EXPECTED_CHAIN_SUMMARIES_NEWEST_FIRST)
    with client_factory(chain.admin_user_id) as client:
        pages = _read_all(client, chain.campaign_id, limit=limit)
        full = client.get(_history_url(chain.campaign_id, limit=100)).json()["items"]
    expected_sizes = [limit] * (total // limit) + ([total % limit] if total % limit else [])
    assert [len(page) for page in pages] == expected_sizes
    flat = _flatten(pages)
    ids = [item["change_log_id"] for item in flat]
    assert len(ids) == len(set(ids))
    assert ids == [item["change_log_id"] for item in full]
    assert [item["change_summary"] for item in flat] == _EXPECTED_CHAIN_SUMMARIES_NEWEST_FIRST


def test_an_older_change_keeps_its_label_when_a_later_change_shares_the_code(
    client_factory: Callable[[uuid.UUID], TestClient], chain: Fixture
) -> None:
    # The label is a property of the recorded predecessor, not of where the
    # event lands on a page: at limit=1 each event is read in isolation and
    # must show the same summary it shows on a full page.
    with client_factory(chain.admin_user_id) as client:
        full = client.get(_history_url(chain.campaign_id, category="role", limit=100)).json()[
            "items"
        ]
        single = _flatten(_read_all(client, chain.campaign_id, limit=1, category="role"))
    assert {i["change_log_id"]: i["change_summary"] for i in single} == {
        i["change_log_id"]: i["change_summary"] for i in full
    }


# ---------------------------------------------------------------------------
# Isolation and safe presentation are preserved
# ---------------------------------------------------------------------------


def test_the_other_campaigns_same_coded_role_never_appears_in_this_campaigns_history(
    client_factory: Callable[[uuid.UUID], TestClient], chain: Fixture
) -> None:
    with client_factory(chain.admin_user_id) as client:
        body_text = client.get(_history_url(chain.campaign_id, limit=100)).text
        other = client.get(_history_url(chain.other_campaign_id, limit=100))
    assert _OTHER_CAMPAIGN_LABEL not in body_text
    assert "Role Lookup Member B" not in body_text
    # Caller has no access to campaign B: not a member, so indistinguishable
    # from a campaign that does not exist.
    assert other.status_code == 404


def test_the_other_campaign_sees_only_its_own_single_correctly_labelled_change(
    client_factory: Callable[[uuid.UUID], TestClient], chain: Fixture
) -> None:
    with client_factory(chain.other_admin_user_id) as client:
        items = client.get(
            _history_url(chain.other_campaign_id, category="role", limit=100)
        ).json()["items"]
    assert [item["change_summary"] for item in items] == [
        f"{_OTHER_CAMPAIGN_LABEL} → {_SYSTEM_LABEL}",
        _OTHER_CAMPAIGN_LABEL,
    ]
    assert len({item["change_log_id"] for item in items}) == 2


def test_the_predecessor_identifier_and_changed_fields_never_reach_the_response(
    client_factory: Callable[[uuid.UUID], TestClient], chain: Fixture, postgres_engine: Engine
) -> None:
    with postgres_engine.connect() as connection:
        recorded_ids = [
            str(row[0])
            for row in connection.execute(
                text("""
                    SELECT changed_fields ->> 'previous_membership_role_id'
                    FROM audit.change_log
                    WHERE world_id = :w AND command_name = 'change_membership_role'
                """),
                {"w": chain.world_id},
            )
        ]
    assert len(recorded_ids) == 7  # six changes in campaign A, one in campaign B
    with client_factory(chain.admin_user_id) as client:
        raw = client.get(_history_url(chain.campaign_id, limit=100)).text
    assert "changed_fields" not in raw
    assert "previous_membership_role_id" not in raw
    for recorded_id in recorded_ids:
        assert recorded_id not in raw
    for item_key in ("previous_status", "new_status", "previous_role", "role_membership_id"):
        assert item_key not in raw
    assert chain.shared_code not in raw, "a raw role code leaked into a resolved label"


# ---------------------------------------------------------------------------
# Legacy / missing / invalid predecessor metadata
# ---------------------------------------------------------------------------


class LegacyCases:
    """One `change_membership_role` audit row per predecessor-metadata shape,
    each recorded against its own (revoked) new-role row so every case is
    independently addressable by `record_id`. The audited (new) role is
    always Target One."""

    def __init__(self, engine: Engine, f: Fixture) -> None:
        self.f = f
        self.change_log_ids: dict[str, int] = {}
        self.expected: dict[str, str] = {}
        code = f.shared_code

        with engine.begin() as connection:
            # Real assignments the pointer-based cases can aim at: the member's
            # own earlier assignment of S (valid), a *different* member's
            # assignment of C in the same campaign, and campaign B's member's
            # assignment of B's same-coded role.
            own_system_assignment = make_membership_role(
                connection, f.member_membership_id, f.system_role_id, revoked=True
            )
            second_members_assignment = make_membership_role(
                connection, f.second_member_membership_id, f.campaign_role_id, revoked=True
            )
            other_campaign_assignment = make_membership_role(
                connection, f.other_member_membership_id, f.other_campaign_role_id, revoked=True
            )

            def record(
                case: str,
                *,
                previous_status: str | None,
                changed_fields: dict[str, object] | None,
                expected: str,
            ) -> None:
                new_row = make_membership_role(
                    connection, f.member_membership_id, f.target_one_id, revoked=True
                )
                record_change_log(
                    connection,
                    change_action_code="updated",
                    schema_name="security",
                    table_name="membership_roles",
                    record_id=new_row,
                    entity_id=None,
                    world_id=f.world_id,
                    actor_user_id=f.admin_user_id,
                    correlation_id=None,
                    command_name="change_membership_role",
                    event_id=None,
                    previous_status=previous_status,
                    new_status="irrelevant",
                    changed_fields=changed_fields,
                )
                change_log_id = connection.execute(
                    text(
                        "SELECT change_log_id FROM audit.change_log "
                        "WHERE record_id = :r AND command_name = 'change_membership_role'"
                    ),
                    {"r": new_row},
                ).scalar_one()
                self.change_log_ids[case] = change_log_id
                self.expected[case] = expected

            unresolved = f"{code} → {_TARGET_ONE_LABEL}"
            record("no_metadata", previous_status=code, changed_fields=None, expected=unresolved)
            record("empty_metadata", previous_status=code, changed_fields={}, expected=unresolved)
            record(
                "unrelated_metadata",
                previous_status=code,
                changed_fields={"something_else": "x"},
                expected=unresolved,
            )
            record(
                "malformed_id",
                previous_status=code,
                changed_fields={"previous_membership_role_id": "not-a-uuid"},
                expected=unresolved,
            )
            record(
                "non_string_id",
                previous_status=code,
                changed_fields={"previous_membership_role_id": 12345},
                expected=unresolved,
            )
            record(
                "unknown_id",
                previous_status=code,
                changed_fields={"previous_membership_role_id": str(uuid.uuid4())},
                expected=unresolved,
            )
            record(
                "assignment_in_another_campaign",
                previous_status=code,
                changed_fields={"previous_membership_role_id": str(other_campaign_assignment)},
                expected=unresolved,
            )
            record(
                "assignment_of_another_membership",
                previous_status=code,
                changed_fields={"previous_membership_role_id": str(second_members_assignment)},
                expected=unresolved,
            )
            record(
                "recorded_code_disagrees_with_assignment",
                previous_status="some_other_code",
                changed_fields={"previous_membership_role_id": str(own_system_assignment)},
                expected=f"some_other_code → {_TARGET_ONE_LABEL}",
            )
            record(
                "no_metadata_and_no_code",
                previous_status=None,
                changed_fields=None,
                expected=f"Unknown role → {_TARGET_ONE_LABEL}",
            )
            # Control: the same valid pointer, agreeing code — resolved exactly.
            record(
                "valid_pointer",
                previous_status=code,
                changed_fields={"previous_membership_role_id": str(own_system_assignment)},
                expected=f"{_SYSTEM_LABEL} → {_TARGET_ONE_LABEL}",
            )


@pytest.fixture
def legacy(postgres_engine: Engine, f: Fixture) -> LegacyCases:
    return LegacyCases(postgres_engine, f)


@pytest.mark.parametrize(
    "case",
    [
        "no_metadata",
        "empty_metadata",
        "unrelated_metadata",
        "malformed_id",
        "non_string_id",
        "unknown_id",
        "assignment_in_another_campaign",
        "assignment_of_another_membership",
        "recorded_code_disagrees_with_assignment",
        "no_metadata_and_no_code",
        "valid_pointer",
    ],
)
def test_legacy_or_invalid_predecessor_metadata_is_shown_conservatively(
    client_factory: Callable[[uuid.UUID], TestClient], legacy: LegacyCases, case: str
) -> None:
    with client_factory(legacy.f.admin_user_id) as client:
        response = client.get(_history_url(legacy.f.campaign_id, category="role", limit=100))
    assert response.status_code == 200, "one bad audit row must never fail the whole read"
    matching = [
        item
        for item in response.json()["items"]
        if item["change_log_id"] == legacy.change_log_ids[case]
    ]
    assert len(matching) == 1, "exactly one item per audit row"
    summary = matching[0]["change_summary"]
    assert summary == legacy.expected[case]
    if case not in ("valid_pointer",):
        # Ambiguity is never resolved by picking one of the two candidate
        # roles, nor by leaking another campaign's role name.
        for label in (_SYSTEM_LABEL, _CAMPAIGN_LABEL, _OTHER_CAMPAIGN_LABEL):
            assert label not in summary


def test_legacy_rows_do_not_duplicate_and_paginate_stably(
    client_factory: Callable[[uuid.UUID], TestClient], legacy: LegacyCases
) -> None:
    expected_ids = sorted(legacy.change_log_ids.values(), reverse=True)
    with client_factory(legacy.f.admin_user_id) as client:
        for limit in (1, 4):
            flat = _flatten(_read_all(client, legacy.f.campaign_id, limit=limit, category="role"))
            ids = [item["change_log_id"] for item in flat]
            assert ids == expected_ids, f"limit={limit}"
            assert len(ids) == len(set(ids))
