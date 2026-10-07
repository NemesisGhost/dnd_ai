"""A campaign on a timeline never authorizes another campaign on it.

Before ADR 0020 an `access.manage` holder in *any* campaign on a timeline could start
another one there ("path B", finding F3), and these tests proved that a retained role on
an archived or deleted campaign did not. Path B is gone: authority over a world's
timelines is world authority (`timeline.manage`, an Owner or Editor), never borrowed from
a campaign. So no campaign, in any lifecycle state, authorizes reuse, reactivating one
restores nothing, and a world Owner still can.
"""

from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, text

from dnd_ai.commands.campaigns import grant_timeline_bootstrap
from tests.authoring_support import Actor, AuthoringHarness, harness_fixture_factory
from tests.builders import make_authored_world

pytestmark = pytest.mark.database


@pytest.fixture
def harness(db_connection: Connection) -> Iterator[AuthoringHarness]:
    yield from harness_fixture_factory()(db_connection)


class Setup:
    """A world owned by `owner`; `author` is a system GM who is NOT a world owner and holds a
    live bootstrap grant for the world's unused primary timeline."""

    def __init__(self, harness: AuthoringHarness, connection: Connection) -> None:
        self.connection = connection
        self.owner = harness.new_actor("Owner", world_creator=True)
        self.author: Actor = harness.new_actor("Author", system_roles=("gm",))
        world = make_authored_world(connection, owner_user_id=self.owner.user_id)
        self.timeline_id = world.primary_timeline_id
        self.ruleset_version_id = world.ruleset_version_id
        grant_timeline_bootstrap(
            connection, timeline_id=self.timeline_id, granted_to_user_id=self.author.user_id
        )

    def body(self, name: str) -> dict:
        return {
            "timeline_id": str(self.timeline_id),
            "ruleset_version_id": str(self.ruleset_version_id),
            "name": name,
            "description": None,
        }

    def create(self, name: str, actor: Actor | None = None):  # type: ignore[no-untyped-def]
        who = actor or self.author
        return who.post("/campaigns", self.body(name), key=who.fresh_key())

    def archive(self, campaign_id: str) -> None:
        version = self.author.get(f"/campaigns/{campaign_id}/settings").json()["row_version"]
        response = self.author.post(
            f"/campaigns/{campaign_id}/archive",
            {"expected_row_version": version, "reason": None},
            key=self.author.fresh_key(),
        )
        assert response.status_code == 200, response.text

    def count(self, sql: str) -> int:
        return int(self.connection.execute(text(sql)).scalar_one())

    def footprint(self) -> tuple[int, ...]:
        u = f"'{self.author.user_id}'"
        return (
            self.count(
                f"SELECT count(*) FROM campaign.campaigns WHERE timeline_id = '{self.timeline_id}'"
            ),
            self.count("SELECT count(*) FROM security.campaign_memberships"),
            self.count("SELECT count(*) FROM security.membership_roles"),
            self.count("SELECT count(*) FROM audit.change_log"),
            self.count(
                "SELECT count(*) FROM security.campaign_creation_reservations "
                f"WHERE actor_user_id = {u} AND response_status_code IS NOT NULL"
            ),
        )


@pytest.fixture
def s(harness: AuthoringHarness, db_connection: Connection) -> Setup:
    return Setup(harness, db_connection)


def _set_state(s: Setup, campaign_id: str, state: str) -> None:
    if state == "archived":
        s.archive(campaign_id)
    elif state == "deleted":
        # Narrowest supported setup: there is no delete command, so mark the row.
        s.connection.execute(
            text(
                "UPDATE campaign.campaigns SET lifecycle_status_id = "
                "(SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'deleted') "
                "WHERE campaign_id = :c"
            ),
            {"c": campaign_id},
        )


@pytest.mark.parametrize("state", ["active", "archived", "deleted"])
def test_no_campaign_in_any_state_authorizes_reuse_of_its_timeline(s: Setup, state: str) -> None:
    first = s.create("Campaign A")
    assert first.status_code == 201, first.text
    _set_state(s, first.json()["campaign_id"], state)

    before = s.footprint()
    denied = s.create("Campaign B")
    assert denied.status_code == 404, denied.text
    assert denied.json()["error"]["code"] == "not_found"
    assert s.footprint() == before  # nothing created, no audit row, no completed reservation
    assert before[0] == 1  # exactly one campaign on the timeline


def test_reactivating_the_campaign_restores_nothing(s: Setup) -> None:
    a = s.create("Campaign A").json()["campaign_id"]
    s.archive(a)
    version = s.author.get(f"/campaigns/{a}/settings").json()["row_version"]
    reactivated = s.author.post(
        f"/campaigns/{a}/reactivate",
        {"expected_row_version": version},
        key=s.author.fresh_key(),
    )
    assert reactivated.status_code == 200, reactivated.text

    assert s.create("Campaign B").status_code == 404
    assert s.footprint()[0] == 1


def test_a_world_owner_can_still_start_another_campaign_on_the_used_timeline(s: Setup) -> None:
    assert s.create("Campaign A").status_code == 201
    allowed = s.create("Campaign B", actor=s.owner)
    assert allowed.status_code == 201, allowed.text
    assert s.footprint()[0] == 2
