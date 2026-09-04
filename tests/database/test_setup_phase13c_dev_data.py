"""scripts/setup_phase13c_dev_data.py apply/rerun behavior.

Exercises `_run()` directly against the ephemeral per-session test database
(`db_connection`, always rolled back — see tests/conftest.py), the same way
`--apply` runs it, without ever touching a real dev/prod database. Proves
the two invariants the task this script supports actually depends on:
running it twice does not duplicate campaigns/memberships/characters/
grants, and the real `get_session_bootstrap` query recognizes the result
(both campaigns, both character perspectives on the first one).

`pythonpath = ["scripts"]` (pyproject.toml) makes `setup_phase13c_dev_data`
importable here the same way `uv run python scripts/setup_phase13c_dev_data.py`
runs it directly — see that setting's own comment for why.
"""

import uuid

from setup_phase13c_dev_data import _run
from sqlalchemy import Connection, text

from dnd_ai.domain.passwords import hash_password
from dnd_ai.queries.bootstrap import get_session_bootstrap
from tests.factories import make_user


def _make_local_account(connection: Connection, *, display_name: str = "Dev Tester") -> uuid.UUID:
    """A minimal `security.users` row with an active local (issuer='local')
    identity and password credential — the exact shape `setup_phase13c_dev_
    data._resolve_user` requires. Raw inserts, matching tests/factories.py's
    own documented "testing database enforcement" exception: this test is
    specifically exercising the setup script's own database logic, not the
    local-auth activation flow (already covered by
    tests/database/test_local_auth_commands.py)."""
    user_id = make_user(connection, display_name)
    connection.execute(
        text(
            "INSERT INTO security.external_identities (user_id, issuer, subject) "
            "VALUES (:user_id, 'local', 'dev-tester')"
        ),
        {"user_id": user_id},
    )
    connection.execute(
        text(
            "INSERT INTO security.local_credentials (user_id, password_hash) "
            "VALUES (:user_id, :password_hash)"
        ),
        {"user_id": user_id, "password_hash": hash_password("correct horse battery staple")},
    )
    return user_id


def test_run_is_idempotent_and_bootstrap_recognizes_the_result(db_connection: Connection) -> None:
    user_id = _make_local_account(db_connection)

    first = _run(db_connection, user_id=user_id)
    assert first.lines, "first run should have created every record"
    assert all("[created]" in line for line in first.lines), first.lines

    second = _run(db_connection, user_id=user_id)
    assert all("[reused" in line for line in second.lines), second.lines
    # Same number of records recognized both times — nothing duplicated.
    assert len(second.lines) == len(first.lines)

    view = get_session_bootstrap(db_connection, user_id=user_id)
    assert view.display_name == "Dev Tester"
    assert len(view.campaigns) == 2

    names = {c.campaign_name for c in view.campaigns}
    assert names == {"Phase13C Campaign A", "Phase13C Campaign B"}

    timeline_ids = {c.timeline_id for c in view.campaigns}
    assert len(timeline_ids) == 2, "the two campaigns must sit on two distinct timelines"

    campaign_a = next(c for c in view.campaigns if c.campaign_name == "Phase13C Campaign A")
    perspective_names = {p.character_name for p in campaign_a.character_perspectives}
    assert perspective_names == {"Phase13C Character A", "Phase13C Character B"}

    campaign_b = next(c for c in view.campaigns if c.campaign_name == "Phase13C Campaign B")
    assert campaign_b.character_perspectives == ()
