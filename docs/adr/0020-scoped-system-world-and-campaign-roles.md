# ADR 0020: Scoped system, world, and campaign roles

- **Status**: Accepted (owner answers recorded 2026-10-06; the defaults for the questions still open are listed under "Defaults adopted")
- **Date**: 2026-10-06
- **Supersedes**: [ADR 0018](0018-world-creation-eligibility.md) entirely.
- **Amends**: [ADR 0014](0014-world-authoring-authority.md) decisions 2, 4 and 5 (world roles, the closed capability mapping, owner-only authority); [ADR 0015](0015-typed-world-content-authoring.md) decision 3 (world-definition writes were authorized by campaign `canon.edit`).
- **Plan**: [SCOPED_ROLE_IMPLEMENTATION_PLAN.md](../SCOPED_ROLE_IMPLEMENTATION_PLAN.md) holds the verified findings (§2), the schema (§6), the API (§7), and the delivery checkpoints (§11).

## Context

Authority today lives in three places that were never separated:

- **System:** one boolean, `security.users.is_platform_administrator`, plus a derived "system GM" that ADR 0018 read off *campaign* role assignments. Any campaign `access.manage` holder could therefore mint a platform-wide world creator.
- **World:** one `world_owner` role, one row per (world, user), no sharing, no transfer.
- **Campaign:** a complete, campaign-local model (roles, relationships, grants, groups), which is correct and stays as it is.

Two further gaps follow: a campaign `canon.edit` holder can write the shared canon of every campaign on the world (and read its drafts), and campaign creation can borrow `access.manage` from another campaign on the same timeline.

## Decision

1. **Three independent scopes.** System, world and campaign authority are resolved separately, each from the current database state on every request and never cached. No scope implies authority in another: a system GM is not a GM in anyone's campaign, a world Owner is not a campaign member, a campaign GM is not a world Editor, and an Admin has no world or campaign access.
2. **System roles** are `admin`, `gm`, `player`, `observer`, held in `security.user_system_roles` (revocable, history kept). A user may hold any combination; capabilities are the union of each role's explicit set and there is no hierarchy. Capabilities are a closed mapping in `dnd_ai.domain.system_authority`, not rows in `security.capabilities`. `security.users.is_platform_administrator` is removed.
3. **World roles** are Owner, Editor, Reviewer and Reader, plus a separate world-use grant (permission to host a campaign on the world). A user may hold several world roles on one world. Capabilities are a closed mapping in `dnd_ai.domain.world_authority`.
4. **System GM is required to create worlds, to create campaigns, and to manage worlds** the user owns or is authorized to manage (`world.manage`, `world.share`, `world.transfer`, `campaign.create`). Editing, reviewing, reading and timeline work do not need it. The check is applied when the world authority is resolved, so it is continuous. **No campaign role requires system GM** (this is the interpretation of the owner's answer to Q4, recorded here for confirmation).
5. **Creating a campaign** requires system `campaign.host`, the world capability `campaign.create` (Owner or an unrevoked use grant), and, when the timeline already has a campaign, `timeline.manage` on its world. Authority borrowed from another campaign on the same timeline is removed. The creator receives both `campaign_owner` and `gm`.
6. **World canon boundary.** World-definition writes require the matching world capability (`world.canon.edit` or `world.canon.review`) **and** campaign `canon.edit` on the route campaign. Private reads of world definitions (drafts, revisions, provenance, sources, review queue) require `world.canon.read_private`. Three campaign-originated records that live in world tables stay on campaign `canon.edit`: world-time points, item instances, and player-character identity (Q9, accepted).
7. **Authorship is provenance, not authority.** The existing attribution columns are unchanged and are never updated by ownership transfer, role ending, grant revocation or account disablement.
8. **Account activation and campaign admission stay separate.** An Admin can create and activate an account with no campaign. Accepting an invitation never reads or writes system roles; an account created through an invitation receives system `player` only.
9. **Administrative override is explicit.** Routine Admin access grants no world or campaign read. Two audited recovery commands (`recover_world_ownership`, `recover_campaign_access_manager`) exist for stranded aggregates, each with a mandatory reason.
10. **Granting Admin** is by operator script only by default; the in-app path exists behind `DND_AI_ALLOW_IN_APP_ADMIN_GRANT=true` (Q1).
11. **Timelines** are created and branched by users with write access to the world: Owner and Editor (Q6). **World Reader** browse ships in this workstream (Q7). It sequences after the Phase 15 merge and before Phase 16 (Q10).

## Defaults adopted for questions still open

| Question | Default applied |
|---|---|
| Q2 Backfill | Existing administrators receive `admin` and `gm`; open active world Owners receive `gm`; everyone else `player`. Campaign GMs are **not** promoted. |
| Q5 System Observer | Classification only; it restricts no campaign role. |
| Q8 World-scoped authoring | Deferred; a world role plus campaign `canon.edit` is required. |
| Q11 Recovery surface | Commands and operator scripts first; the disabling admin sees IDs only. |
| Q12 Invited registration | Kept, with system `player`. |
| Q13 Archive/restore/supersede of canon | `world.canon.review` (Reviewer or Owner). |

## Consequences

- Platform authority is no longer minted by campaign configuration (finding F4), and a campaign GM can no longer rewrite shared canon or read another campaign's world prep (F1, F2).
- Users who relied on a campaign `gm` assignment to create worlds lose that until an Admin assigns system GM; the upgrade note in [LOCAL_DEPLOYMENT.md](../LOCAL_DEPLOYMENT.md) says how to find them.
- Campaign GMs without a world role cannot edit definitions on a world they do not own; the owner grants Editor explicitly.
- Revoking system GM stops world management on the next request without deleting any world-role row; restoring GM restores it.
- Shared canon secrets (an NPC's secret name, a quest's `gm_notes`) are known to everyone who writes or reviews the world and to every campaign GM running on it. This is inherent to a shared world and is documented rather than engineered around.
- Excluded: world forks, per-campaign revision pinning, hosted multi-tenant scopes, custom system roles, impersonation.

## References

- [SCOPED_ROLE_IMPLEMENTATION_PLAN.md](../SCOPED_ROLE_IMPLEMENTATION_PLAN.md)
- [ADR 0003](0003-separate-world-timeline-and-campaign.md), [ADR 0014](0014-world-authoring-authority.md), [ADR 0015](0015-typed-world-content-authoring.md), [ADR 0018](0018-world-creation-eligibility.md)
- [DATABASE_MODEL.md](../architecture/DATABASE_MODEL.md) §19, [ENTITY_LIFECYCLE.md](../ENTITY_LIFECYCLE.md) §3
