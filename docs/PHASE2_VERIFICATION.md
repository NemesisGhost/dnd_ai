# Phase 2 Verification Checklist

Verifies Phase 2 (Core world platform) per [PLAN.md §23](PLAN.md#23-delivery-phases), following the exit review in [§23.1](PLAN.md#231-phase-exit-review).

## Exit Criteria

- [x] A world and an arbitrary entity can be created with provenance — entity references a source, canon status, and lifecycle status, and `audit.change_log` records the creation
- [x] Creating an entity with an unseeded canon status is rejected by the database, with a negative test
- [x] `app_read_write` can read and write every table this phase creates; `app_read_only` can read and is refused on write
- [x] Re-running the phase's seeds produces no change; the seed-idempotency CI step is wired up and green
- [x] Every new table and non-obvious column carries a comment, and every foreign key is indexed
- [~] Entity subtype consistency is enforceable — **mechanism built and proven, but against a synthetic subtype.** See "Partially met" below.

All verified against the deployed AWS `dev` RDS instance, per [§23.0](PLAN.md#230-aws-verification-policy). CI run for the final commit: both jobs green.

### Partially met: subtype consistency

`core.enforce_entity_subtype()` exists, is centralized per [conventions §7.4](DATABASE_CONVENTIONS.md#74-subtype-consistency), and has positive and negative tests — including a multi-level chain where the required table is named by an *ancestor* type rather than the entity's own.

But Phase 2 delivers no subtype tables, so it is exercised against a synthetic table created inside the test transaction. That was foreseen and stated in the phase's own criteria, and it is genuinely useful — being table-agnostic is what let it be proven before the first real subtype exists. It is not the same as being proven in production shape. **Phase 4 closes this**, and its first-time obligations say so.

## What Was Built

20 tables across five revisions — the 16 from [§4.3](PLAN.md#43-foundation-tables) plus four supporting lookups the model needs (`source_types`, `name_types`, `world_time_precisions`, `change_actions`).

| Revision | Delivers |
|---|---|
| `003_core_lookups_and_security` | canon/lifecycle/source-type lookups, `security.users`/`roles`/`user_roles`, shared `core.set_updated_at()` trigger |
| `004_worlds_and_entities` | `core.worlds`, `core.entity_types`, `core.sources`, `core.entities`, `core.enforce_entity_subtype()` |
| `005_names_and_tags` | `core.name_types`, `core.entity_names`, `core.tags`, `core.entity_tags`, cross-world tag guard |
| `006_calendars_world_times` | `core.world_time_precisions`, `core.calendars`, `core.calendar_months`, `core.world_times`, `core.worlds.default_calendar_id` |
| `007_audit_change_log` | `audit.change_actions`, `audit.change_log`, append-only grants |

Sliced deliberately rather than delivered as one migration: this phase's first-time obligations were both silent-failure modes, and proving them over six tables is cheaper than discovering them broken over twenty.

## Recurring Obligations ([§23.1](PLAN.md#231-phase-exit-review))

Re-checked against the live `dev` database at phase end, not assumed:

| Obligation | Result |
|---|---|
| Object ownership | All 20 tables owned by `migration_owner`. Only `core.alembic_version` is not, correctly — Alembic creates it before any revision runs |
| Default privileges | `app_read_write` holds SELECT on every table; asserted per-table in `test_role_grants.py`, and `app_read_only` proven to hold no write privilege |
| Seed idempotency | 42 rows across six lookups; re-seeding leaves them byte-identical. CI step green |
| Constraint tests | 248 tests, positive and negative throughout |
| Comments and FK indexes | Zero tables without a comment; zero foreign keys without a supporting index |
| Downgrade | Full round trip to `base` and back, repeatedly, including on an ephemeral database while the main one stayed at head |
| CI green | Both jobs on a real push |

## Bugs and Gaps Found

Verification's job is to find things. It found six.

1. **`alembic check` was silently wrong.** `target_metadata` was an empty `MetaData()` — correct only while the database had no tables. Once revision 003 created some, autogenerate compared them against nothing and reported every one as a table to drop. Fixed by adding `src/dnd_ai/persistence/tables.py` with real SQLAlchemy Core metadata, which [DEVELOPMENT.md §2](DEVELOPMENT.md#2-repository-layout) always planned for. Note Alembic compares comments with no opt-out, so comments now live in both the migration and the metadata — deliberate duplication that makes drift fail loudly.
2. **Downgrade-to-base broke on a shared instance.** `role "integration_worker" cannot be dropped because some objects depend on it / DETAIL: 1 object in database dnd_ai`. Roles are cluster-wide while schemas and grants are per-database, so the blocking dependency lived in a database `DROP OWNED` cannot reach. Found by CI, not locally — the ephemeral-database mechanism in [§29.9](PLAN.md#299-aws-first-verification-mechanism) creates exactly this situation by design. `DROP ROLE` now tolerates the failure and keeps the role, which is the correct outcome when it is still in use.
3. **That fix exposed a second bug.** With roles surviving, `env.py`'s "has `alembic_version` been created?" proxy for "is `migration_owner` usable here?" became wrong: after a downgrade the role exists but has no privileges, so `SET ROLE` succeeded and everything after failed with "permission denied for schema core". Replaced the proxy with a direct check of the actual precondition.
4. **`integration_worker` could not write audit rows.** Asserting append-only surfaced that it had *no* privileges on `audit.change_log` at all — `001_bootstrap` only grants it DML in the `integration` schema. A bare `REVOKE` would have left it unable to append while the append-only test still passed, since holding no privileges trivially satisfies "cannot UPDATE". [§24.1](DATABASE_CONVENTIONS.md#241-what-to-audit) requires integration writes to be audited, so the migration now grants `SELECT, INSERT` explicitly before revoking the rewrite verbs.
5. **A doc conflict in the canon-status vocabulary.** [PLAN.md §4.4](PLAN.md#44-canon-lifecycle) and DOMAIN_MODEL.md both list seven values; ENTITY_LIFECYCLE.md §2.1 listed six while referring to "a deprecated definition" in its own §12. Added `deprecated` to §2.1 and recorded how it differs from `superseded`.
6. **Alembic revision ids are capped at 32 characters.** `core.alembic_version.version_num` is `VARCHAR(32)`, and a longer id fails only at the very end of the migration, after all DDL has run. Recorded in `script.py.mako` so the next revision does not rediscover it.

Two test bugs also surfaced, both mine rather than the schema's: a trigger test that asserted `updated_at` advances between two statements in one transaction (it cannot — `now()` is transaction-start time), and an invalid `INSERT ... RETURNING` used as a scalar subquery.

## Deliberate Scoping Decisions

Recorded here because each is a place a later phase could reasonably expect something that is not there.

- **`core.entity_types` is unseeded.** [§4.4](PLAN.md#44-canon-lifecycle) specifies seeding canon statuses and says nothing about entity types, and §2.2's inheritance tree names subtype tables that do not exist until Phases 4, 5, and 9. Each phase registers the types it actually builds.
- **`security.roles` is unseeded.** The role vocabulary is not specified anywhere in the domain docs; inventing it here would preempt that decision.
- **`core.worlds.default_ruleset_id` is absent.** `rules.rulesets` arrives in Phase 4; the column and its foreign key arrive with it, as `default_calendar_id` did this phase.
- **Timeline scoping of `core.entity_names` is absent.** [DATABASE_MODEL.md §5.4](architecture/DATABASE_MODEL.md#54-names-aliases-and-tags) notes names may be timeline-scoped; that needs `campaign.timelines` from Phase 3.
- **`audit.change_log.event_id` is unconstrained.** `narrative.events` arrives in Phase 6. The column exists so rows written now can be linked later.
- **Test data is built by raw inserts**, not through commands as [§32.3](DATABASE_CONVENTIONS.md#323-data-builders) will eventually require — the command layer does not exist yet, and these tests target database enforcement, which is the exception §32.3 allows. `tests/factories.py` records this so the builders get replaced rather than grown into a parallel write path.

## Outstanding

Carried forward from Phase 1 and still open:

- **Orphaned KMS key** (`5a359a0a-4d30-4c00-925f-2dfad6e5820d`) from the Phase 1 teardown. The deploying IAM user lacks `kms:ScheduleKeyDeletion`.
- **No `CREATEDB`-capable test role.** CI's ephemeral databases use the master user. Least-privilege gap, noted in [INFRASTRUCTURE.md §11](INFRASTRUCTURE.md#11-known-gaps-and-discrepancies).
- **`iam_auth_db_users` duplicates the login-role list** in `001_bootstrap.py`, kept in sync by hand.
- **No remote Terraform state**, and `staging`/`prod` unbuilt ([§29.2](PLAN.md#292-remote-terraform-state), [§29.3](PLAN.md#293-environments-dev-staging-prod)).

Next phase: Phase 3 (Timelines and campaigns) per [PLAN.md §23](PLAN.md#23-delivery-phases).
