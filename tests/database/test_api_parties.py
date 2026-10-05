"""Party definition endpoints (checkpoint 15.2C-1, migration 120)."""

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, text

from dnd_ai.commands._shared import PartyNotInCampaignError, validate_campaign_party
from dnd_ai.domain.party_authoring import PartyNotActiveError
from tests.authoring_support import AuthoringHarness, harness_fixture_factory
from tests.content_support import ContentSetup
from tests.factories import make_campaign_party, make_party

pytestmark = pytest.mark.database


@pytest.fixture
def harness(db_connection: Connection) -> Iterator[AuthoringHarness]:
    yield from harness_fixture_factory()(db_connection)


@pytest.fixture
def s(harness: AuthoringHarness, db_connection: Connection) -> ContentSetup:
    return ContentSetup(harness, db_connection)


def parties_url(s: ContentSetup, suffix: str = "", cid: str | None = None) -> str:
    return f"/campaigns/{cid or s.cid}/parties{suffix}"


def create(s: ContentSetup, name: str = "The Company", **extra: object) -> dict:
    response = s.gm.post_raw(parties_url(s), {"name": name, **extra}, key=s.gm.fresh_key())
    assert response.status_code == 201, response.text
    return response.json()


def post(s: ContentSetup, party: dict, action: str, **body: object):  # type: ignore[no-untyped-def]
    return s.gm.post_raw(
        parties_url(s, f"/{party['party_id']}/{action}"),
        {"expected_row_version": party["row_version"], **body},
        key=s.gm.fresh_key(),
    )


def test_create_makes_an_active_party_attached_to_the_campaign_with_one_audit_row(
    s: ContentSetup,
) -> None:
    party = create(s, "The Company", description="SECRET PLANS")
    assert set(party) == {"party_id", "row_version", "created", "changed"}
    assert party["row_version"] == 1 and party["created"] is True
    row = s.connection.execute(
        text("""
            SELECT p.world_id, p.name, p.created_by_user_id, ls.code AS status, p.archived_at,
                   EXISTS (SELECT 1 FROM campaign.campaign_parties cp
                           WHERE cp.party_id = p.party_id AND cp.campaign_id = :c) AS attached
            FROM campaign.parties p
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = p.lifecycle_status_id
            WHERE p.party_id = :p
        """),
        {"p": party["party_id"], "c": s.cid},
    ).one()
    assert row.world_id == s.world_id and row.name == "The Company"
    assert row.created_by_user_id == s.gm.user_id and row.status == "active"
    assert row.archived_at is None and row.attached is True
    (audit,) = s.audit("create_party")
    assert "SECRET PLANS" not in str(audit.changed_fields)
    assert audit.changed_fields["name"] == "The Company"


@pytest.mark.parametrize(
    "body", [{"name": ""}, {"name": "   "}, {"name": "x" * 5000}, {"description": "x" * 50000}]
)
def test_invalid_bodies_are_refused_and_write_nothing(s: ContentSetup, body: dict) -> None:
    before = s.count("campaign.parties")
    response = s.gm.post_raw(parties_url(s), {"name": "ok", **body}, key=s.gm.fresh_key())
    assert response.status_code in (400, 422)
    assert s.count("campaign.parties") == before


def test_players_and_strangers_cannot_write_but_members_can_read(s: ContentSetup) -> None:
    party = create(s)
    body = {"name": "x"}
    assert s.player.post_raw(parties_url(s), body, key=s.player.fresh_key()).status_code == 403
    assert s.stranger.post_raw(parties_url(s), body, key=s.stranger.fresh_key()).status_code in (
        403,
        404,
    )
    listing = s.player.get(parties_url(s))
    assert listing.status_code == 200
    assert listing.json()["can_create"] is False
    assert [p["name"] for p in listing.json()["items"]] == ["The Company"]
    assert "available_actions" not in listing.json()["items"][0]
    assert s.player.get(parties_url(s, f"/{party['party_id']}")).status_code == 200
    gm_item = s.gm.get(parties_url(s)).json()["items"][0]
    assert gm_item["available_actions"] == ["update", "archive"]


def test_update_changes_the_party_and_bumps_the_version(s: ContentSetup) -> None:
    party = create(s)
    updated = post(s, party, "update", name="The Crew", description="Now with a ship")
    assert updated.status_code == 200, updated.text
    assert updated.json()["row_version"] == 2 and updated.json()["changed"] is True
    view = s.gm.get(parties_url(s, f"/{party['party_id']}")).json()
    assert (view["name"], view["description"], view["row_version"]) == (
        "The Crew",
        "Now with a ship",
        2,
    )
    (audit,) = s.audit("update_party")
    assert audit.changed_fields["name"] == {"from": "The Company", "to": "The Crew"}
    assert "Now with a ship" not in str(audit.changed_fields)


def test_a_no_op_update_and_a_stale_one(s: ContentSetup) -> None:
    party = create(s, "Same")
    same = post(s, party, "update", name="Same")
    assert same.status_code == 200 and same.json()["changed"] is False
    assert same.json()["row_version"] == 1 and s.audit("update_party") == []
    assert post(s, party, "update", name="Other").status_code == 200
    stale = post(s, party, "update", name="Third")  # still expects version 1
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "stale_write"


def test_archive_hides_the_party_and_restore_brings_it_back(s: ContentSetup) -> None:
    party = create(s)
    archived = post(s, party, "archive", reason="disbanded")
    assert archived.status_code == 200 and archived.json()["row_version"] == 2
    row = s.connection.execute(
        text("SELECT archived_at IS NOT NULL FROM campaign.parties WHERE party_id = :p"),
        {"p": party["party_id"]},
    ).scalar()
    assert row is True
    assert s.player.get(parties_url(s)).json()["items"] == []
    assert s.player.get(parties_url(s, f"/{party['party_id']}")).status_code == 404
    assert s.gm.get(parties_url(s)).json()["items"] == []
    with_archived = s.gm.get(parties_url(s), include_archived="true").json()["items"]
    assert [(p["name"], p["lifecycle_status"], p["available_actions"]) for p in with_archived] == [
        ("The Company", "archived", ["restore"])
    ]
    # A player cannot ask for archived parties.
    assert s.player.get(parties_url(s), include_archived="true").json()["items"] == []

    current = {"party_id": party["party_id"], "row_version": 2}
    assert post(s, current, "archive").status_code == 409  # already archived
    refused_edit = post(s, current, "update", name="x")
    assert refused_edit.status_code == 409
    assert refused_edit.json()["error"]["code"] == "party_not_active"
    no_reason = s.gm.post_raw(
        parties_url(s, f"/{party['party_id']}/restore"),
        {"expected_row_version": 2},
        key=s.gm.fresh_key(),
    )
    assert no_reason.status_code in (400, 422)
    restored = post(s, current, "restore", reason="back together")
    assert restored.status_code == 200 and restored.json()["row_version"] == 3
    assert [p["name"] for p in s.player.get(parties_url(s)).json()["items"]] == ["The Company"]
    assert (
        post(
            s, {"party_id": party["party_id"], "row_version": 3}, "restore", reason="x"
        ).status_code
        == 409
    )
    codes = [a.action for a in s.audit("archive_party")] + [
        a.action for a in s.audit("restore_party")
    ]
    assert codes == ["archived", "restored"]


def test_a_party_of_another_campaign_or_world_is_indistinguishable_from_missing(
    s: ContentSetup,
) -> None:
    foreign = s.stranger.post_raw(
        parties_url(s, cid=s.other_cid), {"name": "Elsewhere"}, key=s.stranger.fresh_key()
    ).json()
    missing = {"party_id": str(uuid.uuid4()), "row_version": 1}
    bodies = []
    for target in (foreign, missing):
        for action, extra in (("update", {"name": "x"}), ("archive", {})):
            response = post(s, target, action, **extra)
            assert response.status_code == 404, (action, response.text)
            bodies.append((response.json()["error"]["code"], response.json()["error"]["message"]))
        assert s.gm.get(parties_url(s, f"/{target['party_id']}")).status_code == 404
    assert len(set(bodies)) == 1
    # A same-world party attached only to another campaign is also unreachable.
    detached = make_party(s.connection, s.world_id, "Detached")
    assert s.gm.get(parties_url(s, f"/{detached}")).status_code == 404
    assert post(s, {"party_id": str(detached), "row_version": 1}, "archive").status_code == 404


def test_replay_and_conflict(s: ContentSetup) -> None:
    key = s.gm.fresh_key()
    body = {"name": "Once"}
    first = s.gm.post_raw(parties_url(s), body, key=key)
    again = s.gm.post_raw(parties_url(s), body, key=key)
    assert first.status_code == again.status_code == 201 and first.json() == again.json()
    assert s.gm.post_raw(parties_url(s), {"name": "Other"}, key=key).status_code == 409
    in_world = s.connection.execute(
        text("SELECT count(*) FROM campaign.parties WHERE world_id = :w"), {"w": s.world_id}
    ).scalar()
    assert in_world == 1


def test_a_failure_after_the_party_row_leaves_nothing(
    s: ContentSetup, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy import Connection as Conn

    real_execute = Conn.execute

    def failing(self: Conn, statement: object, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        if "INSERT INTO campaign.campaign_parties" in str(statement):
            raise RuntimeError("injected failure before the attachment")
        return real_execute(self, statement, *args, **kwargs)  # type: ignore[arg-type]

    tables = ("campaign.parties", "campaign.campaign_parties", "audit.change_log")
    before = {t: s.count(t) for t in tables}
    monkeypatch.setattr(Conn, "execute", failing)
    response = s.gm.post_raw(parties_url(s), {"name": "Doomed"}, key=s.gm.fresh_key())
    monkeypatch.undo()
    assert response.status_code == 500
    assert before == {t: s.count(t) for t in tables}


def test_an_archived_party_takes_no_new_writes_through_the_shared_check(s: ContentSetup) -> None:
    party = create(s)
    pid = uuid.UUID(party["party_id"])
    cid = uuid.UUID(s.cid)
    validate_campaign_party(s.connection, campaign_id=cid, party_id=pid, require_active=True)
    assert post(s, party, "archive").status_code == 200
    # Reads (the default) still resolve; new writes are refused.
    validate_campaign_party(s.connection, campaign_id=cid, party_id=pid)
    with pytest.raises(PartyNotActiveError):
        validate_campaign_party(s.connection, campaign_id=cid, party_id=pid, require_active=True)
    other = make_party(s.connection, s.world_id, "Unattached")
    with pytest.raises(PartyNotInCampaignError):
        validate_campaign_party(s.connection, campaign_id=cid, party_id=other, require_active=True)
    make_campaign_party(s.connection, cid, other)
    validate_campaign_party(s.connection, campaign_id=cid, party_id=other, require_active=True)


def test_parties_created_before_the_lifecycle_columns_start_active(s: ContentSetup) -> None:
    legacy = make_party(s.connection, s.world_id, "Legacy")
    row = s.connection.execute(
        text(
            "SELECT ls.code, p.row_version FROM campaign.parties p JOIN core.lifecycle_statuses ls "
            "ON ls.lifecycle_status_id = p.lifecycle_status_id WHERE p.party_id = :p"
        ),
        {"p": legacy},
    ).one()
    assert (row.code, row.row_version) == ("active", 1)
