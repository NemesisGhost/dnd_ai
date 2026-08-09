# Phase 3 Verification Checklist

Verifies Phase 3 (Timelines and campaigns) per [PLAN.md §23](PLAN.md#23-delivery-phases), following the exit review in [§23.1](PLAN.md#231-phase-exit-review).

## Exit Criteria

- [x] Two campaigns can share one timeline
- [x] A timeline can branch from another timeline. A root has neither a parent nor a branch point; a branch requires both a parent and a branch world time
- [x] A world cannot have two primary timelines at once, and a branch cannot belong to a different world than its parent — each rejected by the database, each with a negative test
- [x] An entity name may remain world-global or be scoped to a same-world timeline; a cross-world timeline reference is rejected by the database
- [x] Party membership is timeline-scoped: a membership written to one sibling branch does not create a raw membership row in the other
- [x] A party membership cannot overlap itself within the same timeline and party. Negative tests cover bounded and open-ended overlaps; positive tests prove that adjacent `[from, to)` periods and a later return after a gap are accepted
- [x] Membership endpoints from the wrong world and intervals whose end is not later than their start are rejected by the database
- [~] Branch structure is verified in this phase; inherited-history isolation is explicitly recorded as unverified until Phase 6 supplies events and the effective-history query. See "Not proven: branch isolation" below.

All verified against the deployed AWS `dev` RDS instance, per [§23.0](PLAN.md#230-verification-policy): full downgrade-to-`base` and upgrade-to-`head` round trip, `alembic check` clean, 327 tests passing.

### Not proven: branch isolation

Rule 7 in [CLAUDE.md](../CLAUDE.md#5-non-negotiable-architectural-rules) — a timeline inherits parent history only up to its branch point — is the reason branching exists. This phase proves the *structure* a branch needs to make that possible (parent, branch world time, same-world agreement, an acyclic parent chain) and proves that *membership rows* are timeline-scoped rather than shared. It does not and cannot prove *isolation*, because there is no event history to leak until `narrative.events` exists. [DATABASE_CONVENTIONS.md §32.2](DATABASE_CONVENTIONS.md#322-scenario-tests) now attributes the branch-isolation scenario test to Phase 6 explicitly, and Phase 6's exit criteria carry the corresponding obligation.

## What Was Built

Five revisions, six tables.

| Revision | Delivers |
|---|---|
| `008_timelines` | `campaign.timelines`, paired root/branch CHECK, `campaign.enforce_timeline_branch()` (same-world parent, same-world branch point, acyclic parent chain), partial-unique "one primary per world" |
| `009_parties_memberships` | `btree_gist`, `campaign.parties`, `campaign.party_memberships` with the ADR 0010 exclusion constraint and `campaign.sync_party_membership_period()` |
| `010_campaigns` | `campaign.campaigns`, `campaign.campaign_parties`, `campaign.enforce_campaign_party_world()` |
| `011_sessions` | `campaign.sessions` (both real-world and fictional-time columns), `campaign.enforce_session_world_times()` |
| `012_entity_name_timelines` | `core.entity_names.timeline_id`, `core.enforce_entity_name_timeline_world()` — closes the Phase 2 carry-forward |

`campaign.parties` and `campaign.party_memberships` were rebuilt mid-phase: the first attempt used real-world `TIMESTAMPTZ` and a three-column exclusion key, before [ADR 0010](adr/0010-use-sort-key-ranges-for-fictional-time-intervals.md) landed on `origin/main` and settled both questions — fictional time via `core.world_times` endpoints and a derived `INT8RANGE`, and a four-column key that adds `timeline_id`. The rebuild is what shipped; the interim design left no trace in the schema.

The final exclusion constraint, read back from the live database:

```sql
EXCLUDE USING gist (timeline_id WITH =, party_id WITH =,
                    member_entity_id WITH =, effective_period WITH &&)
```

## Recurring Obligations ([§23.1](PLAN.md#231-phase-exit-review))

Re-checked against the live `dev` database at phase end, not assumed:

| Obligation | Result |
|---|---|
| Object ownership | All six tables owned by `migration_owner` |
| Default privileges | `app_read_write`/`app_read_only` asserted per-table in `test_role_grants.py`, now covering `timelines`, `parties`, `party_memberships`, `campaigns`, `campaign_parties`, `sessions` |
| Seed idempotency | No new seed data this phase — nothing to re-check |
| Constraint tests | 327 tests total (up from 248 at Phase 2 exit); every new CHECK, exclusion constraint, and trigger has a positive and negative test |
| Comments and FK indexes | Zero tables without a comment; `test_every_foreign_key_is_indexed` clean after fixing the three gaps below |
| Downgrade | Full round trip to `base` and back through all twelve revisions |
| CI green | Confirmed by later full-chain GitHub Actions runs, including Phase 4 corrections run [`30755760409`](https://github.com/NemesisGhost/dnd_ai/actions/runs/30755760409), which migrated through all Phase 3 revisions, completed a full downgrade/upgrade round trip, and ran the complete suite successfully. |

## Bugs and Gaps Found

1. **`migration_owner` could not create `btree_gist`.** `001_bootstrap` ends with `SET ROLE migration_owner`, so every later revision runs as that role — but it had no database-level `CREATE`, and `btree_gist` (trusted on PG 13+, verified trusted on `dev`'s 15.18) still needs at least that. Failed with `permission denied to create extension "btree_gist"` even connected as the RDS master. Fixed by granting `CREATE ON DATABASE` to `migration_owner` in the bootstrap, resolved via `current_database()` so it works on the master database and on every ephemeral test database alike.
2. **A BEFORE trigger validated a branch point that didn't exist.** `campaign.enforce_timeline_branch()` looked up `branch_world_time_id`'s world unconditionally; when a caller left it `NULL` (the case `ck_timelines_branch_fields_paired` exists to catch), the trigger raised its own confusing "belongs to world NULL" error first, since BEFORE triggers run ahead of CHECK evaluation. Fixed by skipping that lookup when the branch point is absent, so the CHECK constraint is what actually reports it.
3. **Test cleanup assumed a cascade that doesn't exist.** The concurrency test for the membership exclusion constraint tried to `DELETE FROM core.worlds` to tear down; `core.entities` does not cascade from `core.worlds` (only `ON DELETE CASCADE` from the entity side), so the delete failed on a live foreign key. Fixed by deleting child-first, explicitly, in dependency order.
4. **Three foreign keys had no supporting index**, caught by `test_every_foreign_key_is_indexed`: `party_memberships.effective_from_world_time_id`, `party_memberships.effective_to_world_time_id`, `timelines.branch_world_time_id`. All three are on tables built in this phase; none had a natural composite-index that happened to cover them, unlike some earlier tables.
5. **A column comment existed in the migration but not in `tables.py`.** `alembic check` caught `timelines.is_primary`'s comment as a pending "modify_comment" operation — the metadata file is the source of truth `alembic check` compares against, and it had fallen one comment behind the migration that created the column.
6. **A cycle self-parent test named the wrong defender.** `test_a_timeline_cannot_be_its_own_parent` asserted the failure came from `ck_timelines_no_self_parent`, but `campaign.enforce_timeline_branch()`'s BEFORE trigger walks the parent chain and catches a self-reference as the shortest possible cycle first. Both are real, independent defenses; the test now accepts either message rather than asserting an evaluation order that was never guaranteed.

## Deliberate Scoping Decisions

- **`campaigns.ruleset_id` and `worlds.default_ruleset_id` are absent.** `rules.rulesets` arrives in Phase 4; both columns and their foreign keys arrive with it, following the `default_calendar_id` precedent from Phase 2.
- **`party_memberships.member_entity_id` references `core.entities`, not `character.characters`.** That table doesn't exist until Phase 4. The database cannot yet reject a non-character party member — Phase 4 closes it with a negative test.
- **`timelines.branch_event_id` is absent.** `narrative.events` arrives in Phase 6. `test_branch_event_id_is_not_present_yet` marks the deferral so its closure in Phase 6 is deliberate rather than silently forgotten.
- **`campaign_parties` is not timeline-scoped.** [DATABASE_MODEL.md §6.3](architecture/DATABASE_MODEL.md#63-parties-and-membership)'s ER diagram scopes `timeline_id` to `party_memberships` only; a party's association with a campaign is stable regardless of which branch is being viewed.
- **Sessions get a derived range but no exclusion constraint.** Revision 023 later added `world_time_period`, derived from the fictional-time endpoints under ADR 0010. Unlike memberships, nothing requires two sessions not to overlap in fictional time — a flashback session is a legitimate overlap.
- **`campaigns.lifecycle_status_id` and `sessions.lifecycle_status_id` reuse `core.lifecycle_statuses`** rather than introducing campaign- or session-specific status vocabularies. Neither [§5.3](PLAN.md#53-campaigns) nor [§5.5](PLAN.md#55-sessions) names new lookup tables to create, and `campaign.timelines` (this same phase) already set the precedent of reusing the generic lifecycle table for a campaign-domain concept.
- **Test data is still built by raw inserts**, per the Phase 2 note — the command layer does not exist yet. `tests/factories.py` gained `make_world_time`, `make_timeline`, `make_party`, `make_campaign`, `make_session`.

## Outstanding

Carried forward from Phase 2, still open:

- **Orphaned KMS key** (`5a359a0a-4d30-4c00-925f-2dfad6e5820d`) from the Phase 1 teardown.
- **No `CREATEDB`-capable test role.** CI's ephemeral databases use the master user.
- **`iam_auth_db_users` duplicates the login-role list** in `001_bootstrap.py`.
- **No remote Terraform state**, and `staging`/`prod` unbuilt.

Phase 3 is closed. Phase 4 subsequently built rules and shared characters; current project status is recorded in [README.md § Current Status](../README.md#current-status).
