"""`scripts/ai_provider_smoke_test.py`'s disposable fixture: creation and
cleanup only — never invokes an actual AI provider (`_create_fixture`/
`_cleanup_fixture` are pure database setup/teardown; the provider call
lives entirely in `main()`, which this test never calls), so this makes no
live or billable request.

`pythonpath = ["scripts"]` (pyproject.toml) makes `ai_provider_smoke_test`
importable here the same way `tests/database/test_setup_phase13c_dev_data.py`
imports `setup_phase13c_dev_data`.

Uses the session `postgres_engine` fixture rather than the rollback-based
`db_connection` one: `_create_fixture`/`_cleanup_fixture` open and commit
their own transactions against an `Engine`, exactly as `main()` does.
"""

import ai_provider_smoke_test
import pytest
from sqlalchemy import Engine, text

pytestmark = pytest.mark.database


def test_create_fixture_records_its_own_ownership_scope(postgres_engine: Engine) -> None:
    with postgres_engine.begin() as connection:
        fixture = ai_provider_smoke_test._create_fixture(connection)
    try:
        with postgres_engine.connect() as connection:
            world_scope = connection.execute(
                text("SELECT ownership_scope_id FROM core.worlds WHERE world_id = :w"),
                {"w": fixture.world_id},
            ).scalar_one()
        assert world_scope == fixture.ownership_scope_id
    finally:
        ai_provider_smoke_test._cleanup_fixture(postgres_engine, fixture)


def test_cleanup_fixture_removes_the_world_and_its_ownership_scope(
    postgres_engine: Engine,
) -> None:
    with postgres_engine.begin() as connection:
        fixture = ai_provider_smoke_test._create_fixture(connection)

    ai_provider_smoke_test._cleanup_fixture(postgres_engine, fixture)

    with postgres_engine.connect() as connection:
        world_count = connection.execute(
            text("SELECT count(*) FROM core.worlds WHERE world_id = :w"),
            {"w": fixture.world_id},
        ).scalar_one()
        scope_count = connection.execute(
            text("SELECT count(*) FROM security.ownership_scopes WHERE ownership_scope_id = :s"),
            {"s": fixture.ownership_scope_id},
        ).scalar_one()
    assert world_count == 0
    assert scope_count == 0
