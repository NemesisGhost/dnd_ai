# ADR 0018: World creation is limited to platform administrators and game masters

- **Status**: Superseded by [ADR 0020](0020-scoped-system-world-and-campaign-roles.md)
- **Date**: 2026-10-06
- **Amends**: [ADR 0014](0014-world-authoring-authority.md) decision 3 (the global capability `world.create`). The rest of ADR 0014 — per-world `world_owner` authority, the closed world-capability mapping, resolution from the database on every request, and legacy-world claiming — is unchanged.

## Context

ADR 0014 gave the global capability `world.create` to every active human principal. In practice that meant:

- `POST /worlds` required only an authenticated human, and `create_world()` authorized nobody;
- the session bootstrap advertised `world.create` to every human, players and observers included;
- the portal therefore offered world creation to accounts that only ever join other people's campaigns.

ADR 0014 rejected "platform-administrator-only" creation because "a new GM can create a world" must remain true. That requirement still holds, but "any human" is broader than it needs. A player who has never run a game has no reason to author a world, and a world is the root that every timeline, campaign, and entity hangs from.

## Decision

1. **Only two kinds of user may create a world:**
   - an **active platform administrator** (`security.users.is_platform_administrator`, through `dnd_ai.domain.access.is_platform_administrator`); or
   - an **active user with an effective assignment of the built-in `gm` role**: an open (`ended_at IS NULL`) campaign membership whose status is `active`, in an `active` campaign, holding an unrevoked, unexpired assignment of an active `security.roles` row with `code = 'gm'` **and `campaign_id IS NULL`** (the system template).
2. **Nothing else qualifies.** `campaign_owner`, `assistant_gm`, `player`, `observer`, a world role such as `world_owner`, `canon.edit`, and `access.manage` each confer no creation right on their own. A campaign-scoped custom role that happens to use the code `gm` is a different role and never qualifies.
3. **One policy, enforced in the command.** `dnd_ai.queries.world_authority.may_create_worlds` is the only definition. `create_world()` calls it first, in the caller's transaction, before validating input or writing anything, and raises `WorldCreationNotAuthorizedError` (HTTP 403 `forbidden`). `POST /worlds` repeats the check before touching the idempotency store, so a refused caller can neither reserve a key nor replay an earlier success. The portal's checks are presentation only.
4. **The bootstrap reports it per user.** `GET /auth/session` returns `global_capabilities: ["world.create"]` exactly when the policy holds for that user and the principal is human. There is no longer a static "every human" set.
5. **Foundry device and machine principals remain refused** by `require_human_user_id` before the policy runs.
6. **Eligibility is creation only.** Being an administrator or a GM grants no authority over any existing world: world reads and edits still come only from `world_owner` membership (ADR 0014). Creating a world makes the creator its first owner, as before.
7. **Portal presentation follows server data only** (`global_capabilities`, a world's `capabilities`, and `available_actions`): persistent navigation keeps unavailable entries visible as disabled non-links; contextual creation and edit actions are omitted; directly entered `/worlds/new` and `/worlds/:worldId/edit` URLs render the ordinary not-found page without mounting the form; a world returned as view-only opens read-only.

## Alternatives considered

- **Keep "any human".** Rejected: it advertises an authoring entry point to every player and gives the server nothing to enforce.
- **Administrators only.** Rejected again for ADR 0014's reason: a GM must be able to create a world without an operator step.
- **Any campaign role carrying `access.manage` or `canon.edit`.** Rejected: those are campaign-scoped capabilities that custom roles can carry; tying a platform-wide right to them would let a campaign's own role configuration mint world creators.
- **A new `security.capabilities` code or a new global role table.** Deferred: the built-in `gm` template is the existing, approved signal for "runs games here", and adding a grantable capability would need its own administration surface.

## Consequences

- A first GM needs either administration or a GM assignment in some campaign; on a fresh install the bootstrap administrator creates the first world (or invites the GM to a campaign first).
- A GM who loses every effective `gm` assignment stops being able to create *new* worlds but keeps owning the worlds they created.
- Test builders that author worlds now make their actor a legitimate creator (platform administration) explicitly instead of relying on "any human".
- Changing the eligibility rule again remains a single-function change plus this ADR's successor; the portal needs no change because it reads `world.create` from the bootstrap.

## References

- [ADR 0014](0014-world-authoring-authority.md)
- [DOMAIN_MODEL.md](../DOMAIN_MODEL.md) — World authority
- [UI_DESIGN.md](../UI_DESIGN.md) — Worlds navigation and routes
- `src/dnd_ai/queries/world_authority.py`, `src/dnd_ai/commands/worlds.py`, `src/dnd_ai/api/worlds.py`, `src/dnd_ai/api/local_auth.py`
