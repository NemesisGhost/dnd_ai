---
name: new-migration
description: Scaffold a new Alembic revision file under database/migrations/versions/ and get reminded of this repo's migration conventions (DATABASE_CONVENTIONS.md §25.2, §3.2, §31, §19.1-2, §7.3) without reading the whole conventions doc. Use when a task requires a schema change — a new table, column, constraint, or trigger.
allowed-tools: Bash(uv run alembic -c database/alembic.ini revision:*)
argument-hint: <short message describing the change>
---

Run:

```
uv run alembic -c database/alembic.ini revision -m "$ARGUMENTS"
```

This creates `database/migrations/versions/<revision>_<slug>.py` from
`database/migrations/script.py.mako`, already containing the five required
docstring sections (Purpose / Forward migration / Rollback / Data
implications / Locking considerations — DATABASE_CONVENTIONS.md §25.2) as
placeholders, plus the `revision`/`down_revision` identifiers wired to the
current head. Report the created file path, then fill in the migration
using this checklist — sourced from DATABASE_CONVENTIONS.md so it doesn't
need a full read of that document for a routine schema change:

- **Schema-qualify everything.** `REFERENCES core.entities(entity_id)`, never
  a bare `REFERENCES entities(entity_id)` (§3.2).
- **Add table and column comments in this same revision**, not a follow-up
  one (§31). `alembic check` compares comments unconditionally with no
  opt-out, so the exact comment text must also be added to the matching
  `src/dnd_ai/persistence/tables/<domain>.py` module — same wording, or
  `alembic check` reports a diff.
- **Index every foreign key** (§19.1), named per §19.2.
- **A subtype table's primary key is the parent entity's UUID** — no new UUID
  generated per subtype level (§7.3).
- **Revision id ≤32 characters.** `core.alembic_version.version_num` is
  `VARCHAR(32)`; a longer id only fails at the very end of the migration,
  after all DDL has already run.
- **No destructive `DROP ... CASCADE`** against persistent environments
  (§25.3).
- **If this touches `database/seeds/*.yaml`**, remember frozen files can't be
  edited once consumed anywhere, including `dev` — add a new file and a new
  migration instead (§25.4).

Once `upgrade()`/`downgrade()` and the matching `tables/` module are both
written, use the `verify` skill (`scripts/verify.sh`) to confirm
`alembic check` reports no diff and the full suite still passes — don't
hand-run the individual ruff/alembic/pytest calls it already bundles.
