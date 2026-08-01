"""Create or drop the ephemeral per-CI-run test database on AWS dev.

Used by .github/workflows/ci.yml to share one database across that job's
migration checks and pytest run, per docs/PLAN.md §29.9. Not for interactive
use — a plain DATABASE_URL pointed at the dev endpoint, plus
scripts/aws-db-allow-my-ip.sh for reachability, covers that (see
docs/DEVELOPMENT.md §3); tests/conftest.py manages its own ephemeral database
in that case.

Usage: uv run python scripts/ci_ephemeral_database.py <create|drop>

`create` requires DEV_DB_ADMIN_URL (a connection string for a role with
CREATEDB on dev) and GITHUB_ENV (set by the Actions runner) in the
environment; it writes DND_AI_CI_DB_NAME, DATABASE_URL, and
DND_AI_TEST_DATABASE_URL there for subsequent steps. `drop` reads
DND_AI_CI_DB_NAME and DEV_DB_ADMIN_URL back and is a no-op if the former is
unset (nothing was created, e.g. an earlier step failed first).
"""

import os
import sys
import uuid

from sqlalchemy import create_engine, make_url, text


def create_ephemeral_database() -> None:
    admin_url = make_url(os.environ["DEV_DB_ADMIN_URL"])
    db_name = f"dnd_ai_ci_{uuid.uuid4().hex[:12]}"
    test_url = admin_url.set(database=db_name)

    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    engine.dispose()

    test_url_str = test_url.render_as_string(hide_password=False)
    with open(os.environ["GITHUB_ENV"], "a", encoding="utf-8") as f:
        f.write(f"DND_AI_CI_DB_NAME={db_name}\n")
        f.write(f"DATABASE_URL={test_url_str}\n")
        f.write(f"DND_AI_TEST_DATABASE_URL={test_url_str}\n")


def drop_ephemeral_database() -> None:
    db_name = os.environ.get("DND_AI_CI_DB_NAME")
    if not db_name:
        return

    admin_url = make_url(os.environ["DEV_DB_ADMIN_URL"])
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))
    engine.dispose()


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in {"create", "drop"}:
        print("Usage: ci_ephemeral_database.py <create|drop>", file=sys.stderr)
        sys.exit(2)

    if sys.argv[1] == "create":
        create_ephemeral_database()
    else:
        drop_ephemeral_database()
