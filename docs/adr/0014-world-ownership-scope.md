# ADR 0014: World ownership scope, separate from campaign membership

- **Status**: Accepted
- **Date**: 2026-09-25

## Context

`core.worlds` has never had an owner, creator, or administrator column. Every world in the codebase today is created by a migration, the dev-data seeding script, or a test factory issuing a raw `INSERT` — there is no `create_world` command, and nothing records who is responsible for administering a given world. World slugs are globally unique (`ux_worlds_slug`), which also means two independent self-hosted operators (or, later, two independent hosted customers) could not each use the same natural slug for their own world.

The platform's existing authorization model has two mechanisms that look related but solve different problems, and neither covers this gap:

- `security.campaign_memberships` + `security.roles`/`security.membership_roles` scope authorization to *one campaign*. Being a campaign's `campaign_owner` or `gm` says nothing about who may administer the *world* that campaign's timeline belongs to, and a world can outlive or be shared by many campaigns.
- `security.users.is_platform_administrator` is a single global flag for platform-wide account-management operations. Its own migration comment is explicit that "global administrative privileges ... never masquerade as campaign roles" — and by the same reasoning, they should not masquerade as *world* administration either. Making every platform administrator implicitly the owner of every world would be exactly that.

The proposed product direction (`docs/PRODUCT_DIRECTION.md`) anticipates a future where one operator might run several independent worlds, and where a world might eventually be administered by more than one person (a co-GM, a world-building partner) without either becoming a platform administrator or a campaign GM. It also anticipates possible future hosted/shared deployment without committing to it now. The database needs a place to attach that boundary before more schemas and features accumulate around `core.worlds`, since adding it later (retrofitting every world-scoped table) is strictly more expensive than adding it now, while the schema is still small.

This decision is scoped narrowly: it introduces the ownership boundary and enough command-layer support to establish and maintain it safely. It does not introduce billing, subscriptions, entitlements, quotas, hosted-mode configuration, or an ownership-mutation API/UI — those are separate, later decisions (`docs/PRODUCT_DIRECTION.md` §11).

## Decision

Introduce a first-class **ownership scope** (`security.ownership_scopes`) as the root of world ownership, deliberately named to avoid colliding with `security.users` ("accounts") or implying a billing tenant:

- `security.ownership_scopes` — a first-class entity (`ownership_scope_id`, `name`, `lifecycle_status_id`, timestamps). No "personal" vs. "organization" type column: a scope with one member behaves as a personal boundary today, and the same shape supports a multi-member organization later without a schema change.
- `security.ownership_scope_roles` — a small lookup table (`owner`, `member`), following the "lookup table over enum" convention (`docs/DATABASE_CONVENTIONS.md` §11).
- `security.ownership_scope_memberships` — the many-to-many association between `security.users` and `security.ownership_scopes`, shaped exactly like `security.campaign_memberships` (open/closed rows, never deleted) and reusing the existing generic `security.membership_statuses` lookup (invited/active/suspended/revoked/departed) rather than inventing a parallel status vocabulary.
- `core.worlds.ownership_scope_id` — a new `NOT NULL` foreign key to `security.ownership_scopes`. The old global `ux_worlds_slug` unique constraint is replaced by `ux_worlds_ownership_scope_id_slug` on `(ownership_scope_id, slug)`: slugs are unique within an ownership scope, not globally.

Explicitly **not** decided or built by this change:

- No `create_world` command. World creation remains a raw-insert operation (migrations, dev-data script, test factories) until the broader missing-authoring-surface work (`docs/PRODUCT_DIRECTION.md` §9) is scheduled. Those call sites are updated to supply an `ownership_scope_id`.
- No API or portal surface for managing ownership scopes or their membership. The command layer (`create_ownership_scope`, `add_ownership_scope_member`, `remove_ownership_scope_member`) is complete and tested; wiring it to routes/UI is deferred to avoid pulling this change into a broader access-management feature.
- No transfer-between-scopes command. A world's `ownership_scope_id` can be reassigned later by a dedicated command when a real need exists; nothing today requires it.
- No row-level security policy. The schema is shaped so a future RLS policy could key off `ownership_scope_id`, but none is added now.
- No billing, subscription, plan, entitlement, or quota table. Future billing may attach to `security.ownership_scopes`, but nothing here assumes what that will look like.

**Existing-data migration.** A populated database cannot safely guess which human should own its pre-existing worlds — the earliest-created user is not necessarily the intended owner, and a database may have zero users, one user, or several with no recorded relationship to any world. The migration creates one explicit **legacy ownership scope** with **zero memberships**, backfills every existing `core.worlds` row onto it, then leaves it deliberately unowned. This is a documented, forward-only migration step, not a bug: an operator must explicitly run the `add_ownership_scope_member` command (via `scripts/claim_legacy_ownership_scope.py`) to assign the legacy scope's first owner — most naturally, whoever the bootstrap-admin script (`scripts/bootstrap_admin.py`) created as the platform's first `is_platform_administrator`, though the command does not require that.

**Final-owner invariant.** Enforced at the command layer (not a database constraint trigger): `remove_ownership_scope_member` acquires a scope-scoped `pg_advisory_xact_lock` (mirroring `dnd_ai.commands.local_auth`'s `_PLATFORM_ADMINISTRATOR_LIFECYCLE_LOCK_KEY` pattern for the analogous "never leave zero active platform administrators" invariant) before checking whether the membership being removed is the scope's last active owner. This is a deliberately lighter mechanism than the `DEFERRABLE INITIALLY DEFERRED` constraint-trigger machinery `security.campaign_has_access_manager()` uses for campaign-owner retention (migration `080_security_identity_and_access`) — that heavier machinery exists because a campaign's owner/access-manager invariant must hold even against direct-SQL or multi-statement mutation paths that don't go through a single command; an ownership scope has no such path yet (no API, no UI, one command), so an application-layer check is sufficient today and avoids building trigger machinery this feature does not yet need.

## Consequences

- Two independent owners can now use the same world slug (e.g. `waterdeep`) without collision — a prerequisite for any future shared/hosted deployment, achieved without adding any hosted-mode configuration now.
- Every world-scoped query or command that needs to resolve "who administers this world" has one FK hop to walk (`core.worlds.ownership_scope_id` → `security.ownership_scope_memberships`), independent of that world's campaigns, timelines, or `is_platform_administrator` flags.
- A populated self-hosted installation upgrading through this migration will have an unowned legacy ownership scope until an operator explicitly claims it — this is a one-time, documented manual step (`docs/LOCAL_DEPLOYMENT.md` operations section), not a silent behavior change to any existing authorization check (nothing today reads `ownership_scope_id` for authorization decisions, since no command yet depends on it).
- Adding a `create_world` command later has a stable foundation to build on (it will simply require an `ownership_scope_id` the caller is an active `owner`/`member` of) rather than needing its own retrofit of the ownership concept.
- This ADR deliberately leaves the creature/NPC modeling decision, player-private collaboration schema, and RLS policy design out of scope — see `docs/PRODUCT_DIRECTION.md` §10–11 for those as separate, still-open questions.

## References

- `docs/PRODUCT_DIRECTION.md` §9, §11 — the missing authoring prerequisite and future ownership-adjacent workstreams this ADR partially addresses.
- `docs/architecture/DATABASE_MODEL.md` §19.2, §19.3 — `security.campaign_memberships`/`security.roles`, the membership-shaped and lookup-table conventions this design reuses.
- `docs/DATABASE_CONVENTIONS.md` §11 (lookup tables), §25 (migrations), §24 (audit conventions).
- `src/dnd_ai/commands/local_auth.py` — the `is_platform_administrator` final-admin advisory-lock pattern this ADR's final-owner invariant follows.
- `database/migrations/versions/080_security_identity_and_access.py` — the campaign-owner retention invariant this ADR deliberately does not replicate in full, and why.
