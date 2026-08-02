# Phase 4 Remaining Issues

> **OPEN (2026-08-02).** Revision 036 and its push-triggered GitHub Actions
> workflow are green, but Phase 4 remains open for one final-schema integrity
> correction and three focused verification gaps. Do not begin Phase 5 until the
> completion gate below is satisfied.

## Review baseline and scope

The review examined commit `f154f49` after revisions `035`–`036. GitHub Actions
run [`30771818049`](https://github.com/NemesisGhost/dnd_ai/actions/runs/30771818049)
passed migration to revision 036, the full `downgrade base` → `upgrade head`
round trip, seed verification, `alembic check`, formatting, Ruff, mypy, all 847
tests, ephemeral-database removal, and ingress revocation.

That evidence closes the five items from the revision-034 review. The items below
were found by reviewing the resulting revision-036 schema and verification suite.
They concern final behavior that can affect Phase 5 or later work, not transient
states between historical revisions.

## Schema blocker

### 1. Enforce the world's ruleset allow-list for character languages

`character.character_languages` currently accepts any `rules.languages` row. It
does not verify that the language's ruleset family is present in the character's
world-level `rules.world_rulesets` allow-list. The reverse guard in
`rules.enforce_world_ruleset_still_in_use()` likewise does not treat character
languages as dependents, and revision 035's shared-lock path is never entered for
this association.

This leaves three final-schema defects:

- A character can acquire a language from a ruleset family its world does not
  allow.
- An allow-list association can be removed or repointed while a character still
  uses a language from that family.
- Concurrent character-language creation and allow-list removal/repointing can
  commit around one another.

Acceptance criteria:

- Add a new forward-only Alembic revision; do not edit revisions 001–036.
- On `character.character_languages` insert or update, resolve the character's
  world and language's ruleset version, then require its family to be allowed by
  that world.
- Reuse the concurrency-safe `rules.ruleset_allowed_for_world()` locking path or
  an equivalently documented single-row locking mechanism.
- Extend `rules.enforce_world_ruleset_still_in_use()` so delete or repoint of an
  allow-list row is rejected while any character in that world uses a language
  from that ruleset family.
- Continue to allow one character to know languages from multiple ruleset
  families when every family is allowed by the world.
- Add positive same-family and allowed-multiple-family tests.
- Add negative insert and update tests for a language from a disallowed family,
  proving an existing valid row remains unchanged after a rejected update.
- Add delete and repoint tests for an association used by a character language.
- Add two-connection tests for concurrent language insertion versus allow-list
  deletion and repointing.
- Update SQLAlchemy metadata comments and `DATABASE_MODEL.md` to describe the
  installed enforcement after the revision lands.

## Verification gaps

### 2. Prove a waiting allow-list mutation resumes and is rejected

The revision-035 concurrency tests use `lock_timeout` to prove a concurrent delete
or repoint blocks, then commit the creator and retry in a new transaction. They do
not prove the complete production sequence in which the original blocked statement
remains waiting, resumes after the creator commits, re-evaluates the now-visible
dependency, and is rejected.

Acceptance criteria:

- Add at least one threaded two-connection test without `lock_timeout` as the
  expected result.
- Begin the delete or repoint while the dependency-creating transaction holds its
  shared lock and prove the statement is waiting.
- Commit the creator, then prove that same waiting statement resumes and fails due
  to the committed dependency; do not replace it with a retry in a third
  transaction.
- Use bounded synchronization and cleanup so a failed assertion cannot hang CI or
  leak test data.
- Apply the same pattern to the new character-language dependency or explicitly
  document why one representative test exercises the shared mechanism for all
  categories.

### 3. Assert the CI cleanup entry point exits nonzero

`tests/unit/test_ci_cleanup.py` proves `run_cleanup()` returns `False` for simulated
failures, but CI invokes `scripts/ci_cleanup.py::main()`. No test proves that the
entry point converts that result into a failing process exit code.

Acceptance criteria:

- Patch the real cleanup callables or `run_cleanup()` so `main()` follows a
  simulated failure path without touching AWS.
- Assert that `main()` raises `SystemExit` with `code == 1` when either operation
  fails.
- Retain the existing tests proving both operations are attempted and both error
  messages are reported.

### 4. Assert the exact edition-neutral family description

The seed test rejects only the old edition-specific family description. A different
incorrect description would still pass, so revision 034's inline seed correction is
not fully frozen by the verification suite.

Acceptance criteria:

- Assert the exact revision-034 family description:
  `The fifth-edition Dungeons & Dragons ruleset family, spanning multiple published editions (e.g. 2014, 2024).`
- Retain the exact family code/display-name, version label, and version-description
  assertions.
- Keep the assertion alongside structured-seed verification so future wording
  changes require an intentional forward-only migration and test update.

## Completion gate

Close Phase 4 only after all four items meet their acceptance criteria and
`PHASE4_VERIFICATION.md` records:

- New forward-only corrective revision(s), with no edits to applied revisions.
- Positive, negative, reverse-dependency, and two-connection tests required above.
- `ruff format --check`, `ruff check`, and mypy clean.
- Full test suite green.
- Upgrade from revision 036 to the new head.
- Full `downgrade base` → `upgrade head` round trip.
- Seed reproducibility/idempotency checks green.
- `alembic check` clean.
- A complete push-triggered GitHub Actions AWS workflow green, including cleanup.
- Final documentation reconciliation converting this register to a closed record
  and unblocking Phase 5.

## Explicitly not tracked

- **Revision 023's ordering while upgrading a populated revision-022 database.**
  The project has no production data to preserve, the deployed verification
  databases are ephemeral, and only the final schema matters. Revisit only if an
  actual persistent revision-022 database is discovered.
- **Open-ended session intervals.** Start-only sessions intentionally represent an
  ongoing fictional-time interval with an unbounded upper range. Unscheduled
  sessions use neither endpoint and have a `NULL` range; overlapping sessions
  remain allowed.
- **Intermediate names, values, and columns inside applied revisions.** The final
  schema is authoritative; prior migrations remain historical and forward-only.
- **The revision-034 review items.** Revisions 035–036 and their associated tests
  closed the allow-list race for the six then-registered dependency categories,
  completed rule-content identity immutability, added the missing proficiency
  update test, added family/version seed assertions, and made CI cleanup testable.
  This register tracks only the character-language omission and the narrower
  verification improvements above.
