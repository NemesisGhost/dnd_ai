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
3. **World roles** are Owner, Editor, Reviewer and Reader, plus a separate world-use grant (permission to host a campaign on the world). A user may hold several world roles on one world. Capabilities are a closed mapping in `dnd_ai.domain.world_authority`. The read-only `world_viewer` role that [ADR 0019](0019-world-visibility-and-viewer-role.md) added in Phase 15 (`world.view` only: the world, its timelines and its calendars) is **kept unchanged** and fits the same model; it is distinct from Reader, which also reads the world's published canon. Whether to retire `world_viewer` in favour of Reader is an open owner question (see "Defaults adopted").
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
| `world_viewer` (ADR 0019) versus Reader | Both exist. Viewer carries `world.view` only; Reader adds published canon. No automatic conversion; the owner may later retire Viewer. |
| Lifecycle of the campaign-originated records (player characters, item instances) | Follows the same campaign-only authorization as their authoring (the D8 exceptions apply to the record, lifecycle included), so a campaign GM can finish them without a world role. |

## Consequences

- Platform authority is no longer minted by campaign configuration (finding F4), and a campaign GM can no longer rewrite shared canon or read another campaign's world prep (F1, F2).
- Users who relied on a campaign `gm` assignment to create worlds lose that until an Admin assigns system GM; the upgrade note in [LOCAL_DEPLOYMENT.md](../LOCAL_DEPLOYMENT.md) says how to find them.
- Campaign GMs without a world role cannot edit definitions on a world they do not own; the owner grants Editor explicitly.
- Revoking system GM stops world management on the next request without deleting any world-role row; restoring GM restores it.
- Shared canon secrets (an NPC's secret name, a quest's `gm_notes`) are known to everyone who writes or reviews the world and to every campaign GM running on it. This is inherent to a shared world and is documented rather than engineered around.
- Excluded: world forks, per-campaign revision pinning, hosted multi-tenant scopes, custom system roles, impersonation.

## Amendment: integration into Phase 15 (2026-10-24)

**Sequencing.** The accepted Q10 said the roles land after the Phase 15 merge and before Phase 16. The owner revised that: the roles integrate into `phase15/completion` *before Phase 15 closes*, so Phase 15's final acceptance runs against the final authority model. This amends Q10's sequencing only; nothing else in the decision is reopened. The integration is the merge of `feature/scoped-role-model` into an isolated `integration/scoped-roles` branch from `phase15/completion`, followed by focused reconciliation commits; it reaches `phase15/completion` only by a later, owner-approved fast-forward together with a matching database upgrade. Until then the roles are neither merged into the Phase 15 branch nor deployed, and Phase 15 remains "implemented; acceptance pending".

**What the integration settled** (the current-side surfaces the roles branch never saw):

- *Campaign-originated records are readable by the campaign.* A player-character identity or an item instance, unpublished, is shown by campaign `canon.edit` alone (the D8 exceptions apply to reading as they do to writing and to the lifecycle). Before this, a campaign GM could create one and then not read it.
- *Item `origin_notes` do not cross campaigns.* Item instances are world rows with no campaign column, so the GM-only notes are read only in the context that holds the item (a recorded state, inventory entry or owner on the caller's timeline, or created by the caller and not yet awarded) or by `world.canon.read_private`; an edit that could not read them leaves them unchanged. Authorship is used only to keep an author's own not-yet-awarded notes readable; it grants nothing.
- *Runtime stays runtime.* The NPC runtime option catalog (conditions and resources to pick from while running an NPC) is campaign state and needs campaign `canon.edit` only; it had been gated like private canon.
- *Organization members and offices split.* Stint changes are shared definitions (campaign editor and world Editor, `can_edit`); the operational status is campaign state (`can_set_status`). Private and archived stints stay visible to a campaign editor: they are GM-only fields of published definitions.
- *Published member reads need no world role.* Characters, parties, knowledge, quests, organization members, world search and counts and travel were checked; nothing private appears because a runtime GM is present, and counts and lists share one filter.
- *Per-record eligibility is server-computed.* A record's read carries `authoring {campaign_originated, can_read_private, can_edit, can_review}`, and the lifecycle read offers only the actions the caller holds. Both come from one module (`dnd_ai.domain.record_authoring`) that also states the action-to-capability mapping and the exceptions, so previews, read models and commands agree; the portal reads these fields and never a role or a category. The option catalogs report `can_create` for the world Editor only.
- *Losing permission is handled.* A refused save for lack of the world role stops writes, clears what the server's private read had filled the form with, and shows back only what the person changed.
- *Revision 138's downgrade completes* on a database that holds the new data (it deferred-trigger-blocked its own index rebuild before); the lossy downgrade is rehearsed, but it is not the rollback path.

**Deployment.** The upgrade is offline: stop the writers, `pg_dump`, `alembic upgrade head` (137, 138), start the matching API and portal together. Rollback is restoring the dump with the previous commit, never the lossy downgrade. `scripts/operations/verify_scoped_role_upgrade.py` checks a restored copy before and after. Assigning Editor/Reviewer to secondary GMs who should keep authoring is a per-world owner decision made afterwards in the Sharing screen.

**Still defaults, not decisions.** Q2, Q5, Q8, Q11, Q12, Q13, the lifecycle of the campaign-originated records, Viewer/Reader coexistence and the Q4 interpretation ("no campaign role requires system GM") are implemented as the defaults above and remain for the owner's confirmation (decision register DR-7) before the integration branch is landed.

## References

- [SCOPED_ROLE_IMPLEMENTATION_PLAN.md](../SCOPED_ROLE_IMPLEMENTATION_PLAN.md)
- [ADR 0003](0003-separate-world-timeline-and-campaign.md), [ADR 0014](0014-world-authoring-authority.md), [ADR 0015](0015-typed-world-content-authoring.md), [ADR 0018](0018-world-creation-eligibility.md)
- [DATABASE_MODEL.md](../architecture/DATABASE_MODEL.md) §19, [ENTITY_LIFECYCLE.md](../ENTITY_LIFECYCLE.md) §3
