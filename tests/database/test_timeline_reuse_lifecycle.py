"""Timeline-reuse authorization must ignore archived and deleted campaigns.

Archiving a campaign deliberately retains its memberships and roles, so a
non-world-owner who created campaign A through a bootstrap grant keeps
`access.manage` on it. That retained role must not authorize creating a second
campaign on the same timeline (reuse path B) while A is archived or deleted,
consistent with `require_campaign_capability`'s lifecycle contract. Reactivating
A restores reuse. The last test races a real archive against a real reuse on two
PostgreSQL connections.
"""

import threading
from collections.abc import Iterator

import pytest
from sqlalchemy import Connection, Engine, text

from dnd_ai.commands.campaigns import (
    TimelineNotAuthorizedError,
    archive_campaign,
    create_campaign,
    grant_timeline_bootstrap,
)
from dnd_ai.commands.timelines import create_timeline
from tests.authoring_support import Actor, AuthoringHarness, harness_fixture_factory
from tests.builders import make_authored_world
from tests.database.test_authoring_concurrency import (
    _purge_user_worlds,
    _wait_until_blocked,
)
from tests.factories import make_user

pytestmark = pytest.mark.database


@pytest.fixture
def harness(db_connection: Connection) -> Iterator[AuthoringHarness]:
    yield from harness_fixture_factory()(db_connection)


class Setup:
    """A world owned by `owner`; `author` is NOT a world owner and holds a live
    bootstrap grant for the world's unused primary timeline."""

    def __init__(self, harness: AuthoringHarness, connection: Connection) -> None:
        self.connection = connection
        self.owner = harness.new_actor("Owner")
        self.author: Actor = harness.new_actor("Author")
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

    def create(self, name: str):  # type: ignore[no-untyped-def]
        return self.author.post("/campaigns", self.body(name), key=self.author.fresh_key())

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


def test_an_archived_campaign_cannot_authorize_timeline_reuse(s: Setup) -> None:
    first = s.create("Campaign A")
    assert first.status_code == 201, first.text
    a = first.json()["campaign_id"]
    s.archive(a)

    before = s.footprint()
    denied = s.create("Campaign B")
    assert denied.status_code == 404, denied.text
    assert denied.json()["error"]["code"] == "not_found"
    after = s.footprint()
    assert after == before  # nothing created, no audit row, no completed reservation
    assert after[0] == 1  # exactly one campaign on the timeline


def test_reactivating_the_campaign_restores_timeline_reuse(s: Setup) -> None:
    a = s.create("Campaign A").json()["campaign_id"]
    s.archive(a)
    assert s.create("Campaign B").status_code == 404

    version = s.author.get(f"/campaigns/{a}/settings").json()["row_version"]
    reactivated = s.author.post(
        f"/campaigns/{a}/reactivate",
        {"expected_row_version": version},
        key=s.author.fresh_key(),
    )
    assert reactivated.status_code == 200, reactivated.text

    allowed = s.create("Campaign B")
    assert allowed.status_code == 201, allowed.text
    assert s.footprint()[0] == 2


def test_a_deleted_campaign_cannot_authorize_timeline_reuse(s: Setup) -> None:
    a = s.create("Campaign A").json()["campaign_id"]
    # Narrowest supported setup: there is no delete command, so mark the row.
    s.connection.execute(
        text(
            "UPDATE campaign.campaigns SET lifecycle_status_id = "
            "(SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'deleted') "
            "WHERE campaign_id = :c"
        ),
        {"c": a},
    )
    before = s.footprint()
    denied = s.create("Campaign B")
    assert denied.status_code == 404, denied.text
    assert s.footprint() == before


def test_a_live_active_campaign_still_authorizes_reuse(s: Setup) -> None:
    assert s.create("Campaign A").status_code == 201
    assert s.create("Campaign B").status_code == 201


# --- Real two-connection race: archive vs reuse ---------------------------------------------


def test_reuse_racing_an_in_flight_archive_waits_and_is_then_refused(
    postgres_engine: Engine,
) -> None:
    with postgres_engine.begin() as setup:
        owner = make_user(setup, "Reuse Race Owner")
        author = make_user(setup, "Reuse Race Author")
        world = make_authored_world(setup, owner_user_id=owner, name="Reuse Race World")
        timeline = create_timeline(
            setup, world_id=world.world_id, actor_user_id=owner, name="Unused", description=None
        ).timeline_id
        grant_timeline_bootstrap(setup, timeline_id=timeline, granted_to_user_id=author)
        first = create_campaign(
            setup,
            timeline_id=timeline,
            ruleset_version_id=world.ruleset_version_id,
            name="Campaign A",
            creator_user_id=author,
        )
        version = setup.execute(
            text("SELECT row_version FROM campaign.campaigns WHERE campaign_id = :c"),
            {"c": first.campaign_id},
        ).scalar_one()

    try:
        archiver = postgres_engine.connect()
        tx = archiver.begin()
        archive_campaign(
            archiver,
            campaign_id=first.campaign_id,
            actor_user_id=author,
            expected_row_version=version,
        )
        out: dict[str, object] = {}

        def reuse() -> None:
            with postgres_engine.begin() as connection:
                try:
                    create_campaign(
                        connection,
                        timeline_id=timeline,
                        ruleset_version_id=world.ruleset_version_id,
                        name="Campaign B",
                        creator_user_id=author,
                    )
                    out["result"] = "created"
                except TimelineNotAuthorizedError:
                    out["result"] = "not_authorized"

        thread = threading.Thread(target=reuse)
        thread.start()
        # The reuse request blocks on the campaign row the archive holds.
        _wait_until_blocked(
            postgres_engine, "query LIKE '%FOR SHARE%' AND query LIKE '%campaign.campaigns%'"
        )
        assert "result" not in out  # still waiting: it did not authorize on stale state
        tx.commit()
        archiver.close()
        thread.join(timeout=15)

        assert out["result"] == "not_authorized"
        with postgres_engine.connect() as verify:
            campaigns = verify.execute(
                text("SELECT count(*) FROM campaign.campaigns WHERE timeline_id = :t"),
                {"t": timeline},
            ).scalar()
        assert campaigns == 1
    finally:
        with postgres_engine.begin() as cleanup:
            cleanup.execute(text("SET LOCAL session_replication_role = replica"))
            cleanup.execute(
                text(
                    "DELETE FROM security.membership_roles WHERE campaign_membership_id IN "
                    "(SELECT campaign_membership_id FROM security.campaign_memberships "
                    "WHERE user_id = :u)"
                ),
                {"u": author},
            )
            cleanup.execute(
                text("DELETE FROM security.campaign_memberships WHERE user_id = :u"), {"u": author}
            )
            cleanup.execute(
                text(
                    "DELETE FROM security.timeline_bootstrap_grants WHERE granted_to_user_id = :u"
                ),
                {"u": author},
            )
            cleanup.execute(
                text("DELETE FROM audit.change_log WHERE actor_user_id = :u"), {"u": author}
            )
            cleanup.execute(
                text(
                    "DELETE FROM security.campaign_creation_reservations WHERE actor_user_id = :u"
                ),
                {"u": author},
            )
        _purge_user_worlds(postgres_engine, owner)
        with postgres_engine.begin() as cleanup:
            cleanup.execute(text("SET LOCAL session_replication_role = replica"))
            cleanup.execute(text("DELETE FROM security.users WHERE user_id = :u"), {"u": author})
