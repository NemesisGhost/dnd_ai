# Phase 4 Remaining Issues

> **CLOSED (2026-08-02).** All seven items below are implemented, tested, and verified — see [PHASE4_VERIFICATION.md § Closeout](PHASE4_VERIFICATION.md#closeout-2026-08-02) for the resolving revisions and evidence. This file is retained as a historical record of what the closeout review found and fixed; it is no longer an active gate, and Phase 5 is unblocked.

This is the blocking issue register for final Phase 4 closeout. Do not begin Phase 5 until every item below is implemented, tested, and verified by the full AWS GitHub Actions workflow.

## Review baseline and scope

The review examined commit `7d4500e` after migrations `023`–`030` were added. The corresponding [`aws-verification` run](https://github.com/NemesisGhost/dnd_ai/actions/runs/30755760409) completed successfully: empty-database migration, full downgrade/upgrade round trip, seed verification, `alembic check`, formatting, Ruff, mypy, all 612 tests, and cleanup.

A green run proves the paths the suite exercises. It does not prove parent-update and allow-list-removal cases for which no test exists. The items below are defects in the final revision-030 schema, SQLAlchemy metadata, or CI workflow and can affect later phases.

Historical states that existed only between revisions are intentionally excluded. The project has no production data to preserve and previously applied migrations remain immutable. A historical transition belongs here only if an already-deployed database may still contain affected data or the final behavior can damage later work.

## Required fixes

### 1. Complete world-ruleset allow-list protection

`rules.enforce_world_ruleset_still_in_use()` in revision 027 protects world defaults and campaigns only. Removing or repointing an allow-list row can still invalidate ruleset-allowance invariants introduced by revision 029 for:

- `character.characters.species_id`
- `character.character_builds.ruleset_version_id`
- `campaign.character_conditions.condition_id`
- `campaign.character_resources.resource_definition_id`

The same function always returns `OLD`. That is correct for `DELETE`, but a permitted `UPDATE` must return `NEW`; returning `OLD` silently cancels the update.

Acceptance criteria:

- Reject deletion or repointing while any of the six dependency categories uses the association: world default, campaign, character species, character build, character condition, or character resource.
- Return `NEW` for permitted updates and `OLD` for permitted deletes.
- Add a negative test for every dependency category.
- Add positive tests proving an unused association can be deleted and can actually be repointed.

### 2. Protect ruleset consistency from parent updates

Revision 026 and related corrections validate most relationships only when the child row is inserted or updated. A later parent edit can invalidate existing children without firing those checks. Revision 030 protects world/scope identity but not rules identity.

Protect or reverse-validate at least:

- `rules.ruleset_versions.ruleset_id`
- every rule-definition `ruleset_version_id` used by a cross-version invariant
- `character.character_builds.character_id` and `ruleset_version_id`
- `character.character_spellcasting_profiles.character_build_id`
- `rules.proficiency_types.target_kind`
- any other parent field whose update can make an existing build association inconsistent

These columns normally represent identity or scope, so immutability is preferred unless a real supported correction workflow requires transactional reverse validation.

Acceptance criteria:

- No parent update can leave a relationship that the equivalent child insert would reject.
- Tests begin with valid related rows, attempt each protected parent update, and prove the database rejects it or revalidates all dependents atomically.
- The chosen mutable/immutable policy is recorded in `DATABASE_MODEL.md` and migration comments.

### 3. Validate proficiency-type ruleset version

`character.enforce_proficiency_ruleset_version()` checks the selected skill or saving-throw ability against the build, but never checks `proficiency_type_id`. A build from one ruleset version can therefore use a proficiency type from another.

Acceptance criteria:

- Require `rules.proficiency_types.ruleset_version_id` to match the referenced build's `ruleset_version_id` for every proficiency target kind.
- Add negative insert and update tests plus a positive same-version test.

### 4. Correct the SQLAlchemy canon-status default

The live database correctly uses `rules.default_canon_status_id()`, but `src/dnd_ai/persistence/tables.py` declares `rules.rulesets.canon_status_id` with a bare subquery server default. PostgreSQL rejects that default form; Alembic does not currently compare server defaults, so the normal schema check does not expose the drift.

Acceptance criteria:

- Change the metadata default to `rules.default_canon_status_id()`.
- Confirm metadata and the live schema agree.
- Add a focused test or otherwise make this class of default drift detectable.

### 5. Finish the ruleset-family/version separation

Revision 024 renamed the seeded family code from `dnd5e_2024` to `dnd5e`, but the final family row still has the display name `D&D 5e (2024)` and a 2024-specific description. The metadata table comment also uses `D&D 5e (2024)` as its example. This still models the version in both the family and version layers.

Acceptance criteria:

- Use edition-neutral family data such as code `dnd5e`, display name `D&D 5e`, and a family-level description.
- Keep `2024` on `rules.ruleset_versions` as the version label and place edition-specific description there.
- Correct the SQLAlchemy table comment and seed expectations.
- Apply deployed data changes through a new forward-only migration; do not edit revision 022 or 024.

### 6. Resolve rule-source enforcement

Rule `source_id` columns are nullable and use `ON DELETE SET NULL`. The database therefore cannot enforce the convention that AI-generated, imported, integrated, homebrew, or proposed rule content retains provenance.

Acceptance criteria:

- Choose and document one policy before adding more rule content:
  - enforce source presence structurally for the canon statuses/origins that require it, preserving source rows with an appropriate delete policy; or
  - explicitly define source presence as an application-command obligation, including validation and tests at that boundary.
- Reconcile `DATABASE_CONVENTIONS.md`, `DATABASE_MODEL.md`, metadata comments, and tests with the selected policy.
- Do not describe nullable `source_id` as database-enforced provenance.

### 7. Make CI cleanup failures visible

The GitHub Actions cleanup step appends `|| true` to both ephemeral-database deletion and security-group ingress revocation. Either operation can fail while the job remains green, leaving a database behind or port 5432 open to the runner CIDR.

Acceptance criteria:

- Always attempt both cleanup operations.
- Capture each result and fail the cleanup step after both attempts if either failed.
- Preserve enough output to identify which cleanup operation failed.
- Verify the full workflow still removes the ephemeral database and ingress rule on both success and an intentionally failed test path.

## Completion gate

Close Phase 4 only after all seven items meet their acceptance criteria and the following evidence is recorded in `PHASE4_VERIFICATION.md`:

- New forward-only corrective migration or migrations; no edits to applied revisions.
- Positive and negative tests for every new invariant and parent-update path.
- `ruff format --check`, `ruff check`, and mypy clean.
- Full test suite green.
- Upgrade from the existing head to the new head.
- Full `downgrade base` → `upgrade head` round trip.
- Seed reproducibility/idempotency checks green.
- `alembic check` clean.
- The complete GitHub Actions AWS workflow green, including cleanup.
- Final documentation reconciliation, then removal of this file as an active gate or conversion to a closed historical record.

## Explicitly not tracked

- **Revision 023's ordering while upgrading a populated revision-022 database.** The project has no production data to preserve, the deployed verification databases are ephemeral, and only the final schema matters. Revisit only if an actual persistent revision-022 database is discovered.
- **Open-ended session intervals.** Start-only sessions intentionally represent an ongoing fictional-time interval with an unbounded upper range. Unscheduled sessions use neither endpoint and have a `NULL` range; overlapping sessions remain allowed.
- **Intermediate names and columns inside applied revisions.** The final revision-030 schema is authoritative; prior migrations remain historical and forward-only.
- **GitHub Actions Node 20 deprecation warnings.** The actions were upgraded and SHA-pinned in the first corrections pass.
- **Documentation drift listed in the post-correction review.** It is corrected by the same documentation-only change that created this register.
