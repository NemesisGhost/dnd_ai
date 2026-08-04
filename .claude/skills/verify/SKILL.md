---
name: verify
description: Run this repo's local "definition of done" verification loop (docs/DEVELOPMENT.md §10) — ruff format/check, mypy, alembic upgrade+check against AWS dev, seed idempotency, and the full pytest suite — before claiming a change is verified, before opening a PR, or after any schema/table-metadata change. Use `--skip-db` for a fast lint-only pass while iterating.
allowed-tools: Bash(scripts/verify.sh:*)
argument-hint: [--skip-db]
---

Run `scripts/verify.sh $ARGUMENTS` and report the result.

This one script replaces the manual sequence of separate `ruff format --check`,
`ruff check`, `mypy src`, `alembic upgrade head`, `alembic check`,
`pytest tests/database/test_seed_idempotency.py`, and full `pytest` calls —
it runs every step regardless of earlier failures, opens and always closes
the AWS dev security-group ingress rule (`scripts/aws-db-allow-my-ip.sh`)
around the database steps even on failure, and prints one `[PASS]`/`[FAIL]`/
`[SKIP]` line per step plus a final summary.

Do not reimplement these steps by hand with separate tool calls — that is
exactly the repeated-tool-call pattern this script exists to collapse. Read
the script's own comments (`scripts/verify.sh`) before changing what it
checks, and note it deliberately skips the CI job's `alembic downgrade base`
round trip: that only runs safely against CI's ephemeral, empty per-run
database (`scripts/ci_ephemeral_database.py`), and running it here would
downgrade the shared, persistent AWS `dev` database that other work depends
on. Verify a downgrade manually, alone on `dev`, per docs/DEVELOPMENT.md §4,
only right after writing the migration being rolled back.

After the run:

- If everything passed, say so briefly (no need to reproduce the full
  step-by-step output back to the user unless they ask).
- If something failed, summarize which step(s) and why, using the tail of
  output the script already printed — don't re-run the failing command
  again just to see the same output a second time unless you're actively
  debugging a fix.
- A `mypy src` step reported `[SKIP]` means this machine's Application
  Control policy blocked mypy's DLL, not that types were checked and passed
  — say so explicitly rather than treating it as a clean type-check.
