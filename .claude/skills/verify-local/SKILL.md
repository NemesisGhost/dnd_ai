---
name: verify-local
description: Run the local quality/test verification battery (ruff, mypy, pytest, migration checks) via scripts/verify.sh, reporting only pass/fail per stage instead of full command output.
---

# Verify local

Use this instead of running `ruff`, `mypy`, `pytest`, or `alembic` commands
one at a time when you need to confirm the working tree is clean before
committing, opening a PR, or closing a phase review (see
docs/DEVELOPMENT.md §7, §8, §10).

Invoke `scripts/verify.sh <mode>` via Bash:

- `quality` — `ruff format --check`, `ruff check`, `mypy src`. No AWS needed;
  use this for a fast pre-commit check.
- `unit` — `pytest tests/unit`. No AWS needed.
- `database` — `pytest tests/database`. Opens/closes the dev
  security-group ingress automatically.
- `scenario` — `pytest tests/scenario` (skipped if the directory doesn't
  exist). Opens/closes ingress automatically.
- `full` — quality + unit + database + scenario + `alembic check` (schema
  diff). The closest local equivalent to CI's "Migrations and Tests" job,
  minus the destructive full downgrade/upgrade round trip, which CI only
  ever runs against its own disposable ephemeral database
  (`scripts/ci_ephemeral_database.py`).
- `migration-round-trip --confirm-destructive` — `alembic downgrade base`
  then `upgrade head` against whatever `DATABASE_URL` currently points at.
  **Only run this if `DATABASE_URL` points at a database you know is
  disposable** — it is destructive to whatever is there. Without
  `--confirm-destructive` the script refuses to run this stage.

Each stage prints one `PASS: <label> (<seconds>s)` or
`FAIL: <label> (<seconds>s)` line. On failure, the stage's full captured
output is printed once and the script stops — don't re-run the individual
`ruff`/`mypy`/`pytest` command to see what happened; the failure output
already contains it. On success, don't re-run the underlying tools
separately to double-check; the PASS line is the complete signal.

`DATABASE_URL` must already be set per docs/DEVELOPMENT.md §3 before running
`database`/`scenario`/`full`/`migration-round-trip`.
