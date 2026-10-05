"""Real-PostgreSQL races for session definitions (checkpoint 15.2D-1).

Numbering is assigned under a per-campaign advisory lock, so concurrent schedules get
consecutive numbers (never a conflict or a duplicate); edits and archives serialize on
the session row. Nothing is mocked; committed fixtures are purged after.
"""

import threading
import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from sqlalchemy import Engine, text

from dnd_ai.commands.session_authoring import archive_session, schedule_session, update_session
from dnd_ai.domain.authoring import StaleWriteError
from tests.builders import make_authored_campaign, make_authored_world
from tests.database.test_authoring_concurrency import _purge_user_worlds
from tests.database.test_content_authoring_concurrency import race
from tests.factories import make_user

pytestmark = pytest.mark.database

SESSION_LOCK = "query LIKE '%campaign.sessions%FOR UPDATE%'"


@dataclass
class Fixture:
    engine: Engine
    owner: uuid.UUID
    campaign_id: uuid.UUID
    session_id: uuid.UUID

    def schedule(self, connection):  # type: ignore[no-untyped-def]
        return schedule_session(
            connection,
            campaign_id=self.campaign_id,
            actor_user_id=self.owner,
            title=None,
            scheduled_for=None,
        )

    def update(self, connection, title: str, version: int):  # type: ignore[no-untyped-def]
        return update_session(
            connection,
            campaign_id=self.campaign_id,
            actor_user_id=self.owner,
            session_id=self.session_id,
            expected_row_version=version,
            title=title,
            scheduled_for=None,
        )

    def archive(self, connection, version: int):  # type: ignore[no-untyped-def]
        return archive_session(
            connection,
            campaign_id=self.campaign_id,
            actor_user_id=self.owner,
            session_id=self.session_id,
            expected_row_version=version,
        )

    def numbers(self) -> list[int]:
        with self.engine.connect() as connection:
            return [
                int(n)
                for n in connection.execute(
                    text(
                        "SELECT session_number FROM campaign.sessions WHERE campaign_id = :c "
                        "ORDER BY session_number"
                    ),
                    {"c": self.campaign_id},
                ).scalars()
            ]

    def state(self) -> tuple[str | None, str]:
        with self.engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT s.title, ls.code FROM campaign.sessions s JOIN core.lifecycle_statuses ls "
                    "ON ls.lifecycle_status_id = s.lifecycle_status_id WHERE s.session_id = :s"
                ),
                {"s": self.session_id},
            ).one()
        return row.title, str(row.code)


@pytest.fixture
def fx(postgres_engine: Engine) -> Iterator[Fixture]:
    with postgres_engine.begin() as setup:
        owner = make_user(setup, "Session Race Owner")
        world = make_authored_world(setup, owner_user_id=owner, name="Session Race World")
        campaign_id = make_authored_campaign(setup, world, name="Session Race Campaign")
        first = schedule_session(
            setup, campaign_id=campaign_id, actor_user_id=owner, title="One", scheduled_for=None
        )
    yield Fixture(postgres_engine, owner, campaign_id, first.session_id)
    with postgres_engine.begin() as cleanup:
        cleanup.execute(
            text("DELETE FROM campaign.sessions WHERE campaign_id = :c"), {"c": campaign_id}
        )
    _purge_user_worlds(postgres_engine, owner)


def test_concurrent_schedules_get_consecutive_numbers(fx: Fixture) -> None:
    errors: list[BaseException] = []

    def run() -> None:
        try:
            with fx.engine.begin() as connection:
                fx.schedule(connection)
        except BaseException as exc:  # the datum is whether any raced call failed
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert errors == []
    assert fx.numbers() == [1, 2, 3, 4, 5, 6, 7]


def test_two_edits_from_one_version_one_wins_one_is_stale(fx: Fixture) -> None:
    out = race(
        fx.engine,
        lambda c: fx.update(c, "Winner", 1),
        lambda c: fx.update(c, "Loser", 1),
        SESSION_LOCK,
    )
    assert isinstance(out.get("error"), StaleWriteError), out
    assert fx.state() == ("Winner", "active")


def test_an_edit_that_loses_to_an_archive_is_stale_and_changes_nothing(fx: Fixture) -> None:
    out = race(
        fx.engine, lambda c: fx.archive(c, 1), lambda c: fx.update(c, "Late", 1), SESSION_LOCK
    )
    assert isinstance(out.get("error"), StaleWriteError), out
    assert fx.state() == ("One", "archived")
