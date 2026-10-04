# ADR 0014: World authoring authority is a per-world membership

- **Status**: Accepted
- **Date**: 2026-10-03
- **Builds on**: [ADR 0003](0003-separate-world-timeline-and-campaign.md), which separates world, timeline, and campaign. This ADR adds the missing authorization concept for the *world* aggregate.
- **Related**: the unmerged branch `phase14/product-direction-and-world-ownership` proposed "ownership scopes" (a different model). It is **not adopted**; see Alternatives.

## Context

Phase 14 (authoring-first roadmap, [PLAN.md](../PLAN.md)) lets a game master create a world, its timelines, and a campaign through the portal. Before this ADR:

- `core.worlds` had no owner, creator, or authority of any kind; worlds were created only by migrations, scripts, and test factories.
- The only authorization concepts were *campaign* memberships/roles/capabilities and an account-administration flag (`security.users.is_platform_administrator`), which by design "never masquerades as campaign roles".
- There was no way to answer "who may edit this world, or add a timeline to it, or start a campaign on it?" without inferring from campaign roles, which would be a policy nobody had approved.

## Decision

1. **Authority attaches to the world aggregate through `security.world_memberships`**: one open row per `(world, user)`, a role from the lookup `security.world_roles` (seeded with `world_owner`), the existing `security.membership_statuses`, and `joined_at`/`ended_at`. Rows are never deleted by commands. `core.worlds` is unchanged (no new NOT NULL column, no owner column).
2. **World capabilities are a closed, server-side mapping** in `domain/world_authority.py`, not rows in `security.capabilities` (which is assignable to campaign roles):
   `world_owner → {world.view, world.manage, timeline.manage, campaign.create}`.
   Campaign settings reuse the existing `access.manage`; entity lifecycle reuses `canon.edit`. No new campaign capability codes are introduced.
3. **Global capability `world.create`** is held by every active human principal (local session or OIDC). Foundry device principals and machine/service principals never receive it. It is computed server-side and exposed through the session bootstrap; the portal never infers it.
4. **Authority is resolved from database state on every request.** It is never cached, never derived from campaign roles, `is_platform_administrator`, or `created_by_user_id`, and a world owner receives no campaign membership or campaign reads from owning a world.
5. **`create_world` makes its creator the first owner in the same transaction.** Legacy worlds (created before migration 110) have no membership and **nobody may author them** until trusted infrastructure runs `claim_unowned_world`, available only through `scripts/claim_world_ownership.py` and only while the world has zero membership rows of any status.
6. **World slugs are server-generated**, never client-supplied, because a globally unique client-chosen slug would let any user probe for other users' worlds.

## Alternatives considered

- **Ownership scopes** (a tenant-like `ownership_scopes` / `ownership_scope_memberships` layer plus a NOT NULL `core.worlds.ownership_scope_id`). Rejected for Phase 14: its stated purpose (hosted, multi-operator offering) is the deferred Phase 22; it forces a NOT NULL column through ~390 factory call sites and populated-upgrade tests; its migration numbers collide with revisions already on `main`; and a per-world membership table can later sit beneath a scope without migration conflict. The unmerged branch is left in place and is not deleted.
- **Inferring world authority from `campaign_owner` roles** of campaigns on the world. Rejected: not an approved policy, and it makes campaign archival silently revoke world authority.
- **`core.worlds.owner_user_id`.** Rejected: cannot express co-owners without another migration and puts ownership on the definition row.
- **Platform-administrator-only world creation.** Rejected: contradicts "a new GM can create a world" and adds an operator step. A later policy change stays portal-transparent because `world.create` is delivered through the bootstrap.

## Consequences

- A world has a database-level backstop: a deferred constraint trigger refuses a commit that leaves a previously owned world with no active owner.
- Existing worlds are not authorable until an operator claims them (documented in [LOCAL_DEPLOYMENT.md](../LOCAL_DEPLOYMENT.md)).
- Any human user can create unlimited worlds (accepted; a quota is not warranted for a self-hosted product).
- Co-owner management, ownership transfer, and a world-membership UI are deferred until a demonstrated need.
- The decision does not retire the existing timeline bootstrap grant or the `access.manage` campaign-creation reuse path; their deprecation is reviewed in Phase 18.

## References

- [PLAN.md](../PLAN.md) Phase 14
- [DOMAIN_MODEL.md](../DOMAIN_MODEL.md) §4.1
- [DATABASE_MODEL.md](../architecture/DATABASE_MODEL.md)
- [ENTITY_LIFECYCLE.md](../ENTITY_LIFECYCLE.md)
