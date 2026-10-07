# Scoped System, World, and Campaign Authorization — Implementation Plan

- **Status:** Proposed (planning only; nothing here is implemented)
- **Date:** 2026-10-06
- **Branch:** `feature/scoped-role-model`, based on `origin/phase15/completion` at `82ed14c2e2ef07da02baf77b9a8455c1bab56a40`
- **Migration head at planning time:** `135_scrub_narrative_text` (on the Phase 15 base). Do not reserve a number from this; see §12.4.
- **Supersedes on approval:** [ADR 0018](adr/0018-world-creation-eligibility.md) entirely; amends [ADR 0014](adr/0014-world-authoring-authority.md) decisions 2, 4 and 5 and [ADR 0015](adr/0015-typed-world-content-authoring.md) decision 3. The superseding ADR is written in checkpoint SR-0.

This document separates **verified facts** (§2, each with a code or document reference observed on the base commit) from **recommendations** (§3 onward). A recommendation is not a decision until the owner approves it; open questions are collected in §14.

---

## 1. Goal and scope

Introduce three independent authorization scopes:

| Scope | Roles | Governs |
|---|---|---|
| **System** | Admin, GM, Player, Observer | Platform operations and eligibility (accounts, system roles, creating worlds, hosting campaigns) |
| **World** | Owner, Editor, Reviewer, Reader (+ a separate world-use grant) | One world's settings, sharing, shared canon, and permission to host campaigns on it |
| **Campaign** | The full existing model (owner, GM, assistant GM, player, observer, import reviewer, rules curator, custom roles, relationships, grants, groups) | Everything inside one campaign |

Roles supply capability defaults. Services authorize **capabilities**, never role names. No scope implies authority in another: a system GM is not a GM in anyone's campaign; a world Owner is not a member of campaigns on the world; a campaign GM is not a world Editor.

Out of scope: see §15.

---

## 2. Current state (verified)

### 2.1 System scope: one boolean, plus a derived "GM" signal

- `security.users.is_platform_administrator` (migration `099_local_authentication`) is the only platform-level authority. It is read by `is_platform_administrator()` in [domain/access.py](../src/dnd_ai/domain/access.py) (line ~675) and gates `/admin/accounts*` inside the commands in [commands/local_auth.py](../src/dnd_ai/commands/local_auth.py) (`_create_local_account_impl`, `_issue_password_reset_token_impl`, `_set_local_account_lifecycle_status_impl`).
- Granting it to an existing account is out-of-band only: `grant_platform_administrator()` via [scripts/grant_platform_administrator.py](../scripts/grant_platform_administrator.py) (decision D-10, [PHASE13E_ACCESS_CONTRACT.md §3p](PHASE13E_ACCESS_CONTRACT.md)). The first admin comes from `bootstrap_initial_admin` ([scripts/bootstrap_admin.py](../scripts/bootstrap_admin.py)).
- **Last-admin protection exists only for disablement:** `LastActivePlatformAdministratorError` with a global advisory lock (`_PLATFORM_ADMINISTRATOR_LIFECYCLE_LOCK_KEY`). There is no "revoke admin" command at all.
- There is **no system GM role**. [ADR 0018](adr/0018-world-creation-eligibility.md) (landed on the Phase 15 branch; `git diff origin/main...origin/phase15/completion -- src/dnd_ai/queries/world_authority.py` shows +66 lines) derives `world.create` from `may_create_worlds()` in [queries/world_authority.py](../src/dnd_ai/queries/world_authority.py): an active admin **or** anyone holding an effective assignment of the built-in `gm` role (`security.roles.code = 'gm' AND campaign_id IS NULL`) in **any** active campaign (`holds_effective_system_gm_role`).
- **Template vs. assignment confusion (as requested to distinguish):** `security.roles` rows with `campaign_id IS NULL` are *system templates* usable by every campaign ([DATABASE_MODEL.md §19.3](architecture/DATABASE_MODEL.md)); they are only ever *assigned* through `security.membership_roles` on a campaign membership. Nothing in the schema assigns a role at the system level. ADR 0018's "system GM" is therefore "holds the campaign-template `gm` in some campaign", which any campaign `access.manage` holder can confer — a campaign's own role configuration mints platform-wide world creators.
- The session bootstrap ([api/local_auth.py](../src/dnd_ai/api/local_auth.py) `session_bootstrap_endpoint`, [queries/bootstrap.py](../src/dnd_ai/queries/bootstrap.py)) returns `is_platform_administrator: bool` and `global_capabilities: ["world.create"] | []`.

### 2.2 World scope: owner-only, single role per user

- `security.world_roles` is seeded with `world_owner` only ([database/seeds/security.world_roles.yaml](../database/seeds/security.world_roles.yaml)); `security.world_memberships` (migration `110_world_authoring_authority`) allows **one open row per (world, user)**, so a user cannot hold two world roles.
- Capabilities are a closed code mapping in [domain/world_authority.py](../src/dnd_ai/domain/world_authority.py): `world_owner → {world.view, world.manage, timeline.manage, campaign.create}`. Resolution: `resolve_world_authority()`; route dependency: `require_world_capability()` in [api/world_access.py](../src/dnd_ai/api/world_access.py).
- A deferred trigger (`security.assert_world_retains_owner`) prevents ending the last owner row. `security.world_has_active_owner()` **does not consult account lifecycle** (its own comment says so), so disabling the sole owner's account leaves an owner row that satisfies the trigger but authorizes nobody.
- There are **no** routes to list, add, end, or transfer world roles (ADR 0014 "Consequences": co-owners, transfer and a membership UI were deferred). Legacy worlds are claimed with [scripts/claim_world_ownership.py](../scripts/claim_world_ownership.py).
- `get_world_detail()` in [queries/worlds.py](../src/dnd_ai/queries/worlds.py) lists only campaigns the caller manages (`managed_campaigns`) and otherwise a boolean `has_blocking_campaigns`; world ownership already does not disclose other campaigns.

### 2.3 Campaign scope: complete and correctly campaign-local

- `resolve_access_context()` in [domain/access.py](../src/dnd_ai/domain/access.py) resolves membership → role capabilities → character relationships → resource grants (membership- and group-targeted, with `deny`) for **one campaign and its own pinned timeline only**; any other timeline raises `UnauthorizedTimelineError`. Nothing in it reads world or system state. This satisfies "never borrow authority from another campaign" for campaign reads.
- Seeded templates (migrations `080`, `085`, `086`): `campaign_owner {access.manage, campaign.view, canon.edit}`, `gm {campaign.view, canon.edit, character.view_full, character.view_knowledge}`, `assistant_gm {campaign.view, canon.edit, character.view_full}`, `player {campaign.view}`, `observer {campaign.view}`; `import_reviewer` and `rules_curator` exist with **no capabilities** (vocabulary only). `rules_source.manage` is checked by [api/reference_corpus.py](../src/dnd_ai/api/reference_corpus.py); `import.approve` is checked nowhere (no import pipeline exists — `import.*` tables are not created by any migration).
- The DB invariant `security.assert_campaign_retains_access_manager` keeps an active campaign from losing its last non-expiring `access.manage` holder. Like the world invariant, `security.campaign_has_access_manager()` **does not consult account lifecycle**.
- Role assignment: `assign_membership_role`, `change_membership_role`, `revoke_membership_role`, `add_campaign_member`, `end_campaign_membership` in [commands/memberships.py](../src/dnd_ai/commands/memberships.py), all `access.manage`-gated, no system-role check of the assignee.
- Invitations ([commands/campaign_invitations.py](../src/dnd_ai/commands/campaign_invitations.py), [commands/invitation_onboarding.py](../src/dnd_ai/commands/invitation_onboarding.py)) carry **no role**; acceptance creates/reactivates a membership and nothing else. Invitation-authorized registration creates a local account bound to the onboarding session (§3n of the access contract). Account activation by an admin ([commands/local_auth.py](../src/dnd_ai/commands/local_auth.py) `create_local_account` → `/activate`) already needs no campaign.

### 2.4 Campaign creation borrows authority across campaigns

`create_campaign()` → `_authorize_timeline_reuse()` in [commands/campaigns.py](../src/dnd_ai/commands/campaigns.py) authorizes by any of:

- **Path A:** world `campaign.create` (world owner);
- **first-campaign bootstrap grant** (`security.timeline_bootstrap_grants`, trusted infrastructure only);
- **Path B:** an active `access.manage` membership in **any existing campaign on the same timeline** — authority borrowed from another campaign through the shared timeline.

No system-level eligibility is checked. The creator receives exactly one role, `campaign_owner` — **not** `gm`.

### 2.5 Campaign capabilities write shared world canon

[ADR 0015](adr/0015-typed-world-content-authoring.md) decision 3 authorizes world-scoped definitions with **campaign** `canon.edit`. The single choke point is `lock_authoring_scope()` in [commands/_content.py](../src/dnd_ai/commands/_content.py); `lock_operation_scope()` in [commands/_operations.py](../src/dnd_ai/commands/_operations.py) wraps it. Consequently any campaign `gm`/`assistant_gm`/`campaign_owner` on a world can create, edit, publish, archive, and supersede canon seen by **every** campaign on that world. Writers and the records they touch:

| Command module (via `lock_authoring_scope`) | World-scoped records written |
|---|---|
| [locations.py](../src/dnd_ai/commands/locations.py), [dungeons.py](../src/dnd_ai/commands/dungeons.py) | `world.locations`, `world.dungeons`, `world.dungeon_areas`, `world.area_connections`, features/hazards/interactables |
| [organizations.py](../src/dnd_ai/commands/organizations.py), [religions.py](../src/dnd_ai/commands/religions.py) | organization/religion definitions |
| [npcs.py](../src/dnd_ai/commands/npcs.py), [npc_portrayal.py](../src/dnd_ai/commands/npc_portrayal.py), [player_characters.py](../src/dnd_ai/commands/player_characters.py) | `character.*` identity, `character.npc_portrayal_profiles`, `character.player_characters` |
| [quest_definitions.py](../src/dnd_ai/commands/quest_definitions.py) | quest definitions incl. GM-only `gm_notes` ([persistence/tables/narrative.py](../src/dnd_ai/persistence/tables/narrative.py)) |
| [knowledge_definitions.py](../src/dnd_ai/commands/knowledge_definitions.py) | knowledge-item definitions |
| [item_definitions.py](../src/dnd_ai/commands/item_definitions.py), [item_instances.py](../src/dnd_ai/commands/item_instances.py) | `world.item_definitions`, `world.item_instances` (no campaign column) |
| [world_relationships.py](../src/dnd_ai/commands/world_relationships.py) | `world.relationships` and typed subtypes |
| [sources.py](../src/dnd_ai/commands/sources.py) | `core.sources`, `core.entity_source_links` |
| [entity_lifecycle.py](../src/dnd_ai/commands/entity_lifecycle.py) | canon status (submit/approve/reject/publish/supersede) and lifecycle (archive/restore/delete-draft) of all of the above |
| [world_time.py](../src/dnd_ai/commands/world_time.py) `create_world_time` (via `lock_operation_scope`) | `core.world_times` (world_id only) |

Read side: the authoring read models, review queues ([queries/review_queue.py](../src/dnd_ai/queries/review_queue.py)), revisions (`core.entity_revisions`, "GM-only") and provenance ([queries/provenance.py](../src/dnd_ai/queries/provenance.py)) are gated by the same campaign `canon.edit`, so drafts and prep written from campaign A are visible to campaign B's GM.

Records that are correctly campaign- or timeline-scoped today: `campaign.sessions`, `campaign.session_participants`, `campaign.parties`, `narrative.events` (`campaign_id`), all `campaign.*_state` tables (timeline-scoped), knowledge runtime, encounters, campaign clock, AI proposals (`ai.proposed_changes` bound to `campaign_id` in [commands/ai_proposals.py](../src/dnd_ai/commands/ai_proposals.py)), AI synthesis/NPC context ([api/ai_synthesis.py](../src/dnd_ai/api/ai_synthesis.py), [domain/context_assembly.py](../src/dnd_ai/domain/context_assembly.py)), world search (`/campaigns/{id}/world/search` in [api/world_explorer.py](../src/dnd_ai/api/world_explorer.py)), and Foundry principals (bound to one `campaign_id` in [domain/foundry_pairing.py](../src/dnd_ai/domain/foundry_pairing.py)).

### 2.6 Provenance and attribution already present

All FK to `security.users`, which commands never delete: `core.entities.created_by_user_id`; `core.entity_revisions.created_by_user_id` (per-revision author, append-only); `core.sources.created_by_user_id`; `core.entity_source_links.attached_by_user_id`; `core.source_documents.ingested_by_user_id`; `ai.proposed_changes.decided_by_user_id`; `campaign.sessions/parties.created_by_user_id`; `character.player_characters.player_user_id`; `audit.change_log.actor_user_id` (every approval/publish/lifecycle transition). Nothing ties attribution to current authority, so revoking or transferring access does not erase it today.

### 2.7 Portal

- [utils/worldAccess.ts](../portal/src/utils/worldAccess.ts) gates "New world" on `global_capabilities` and world links on per-world `capabilities`; [pages/CampaignsPage.tsx](../portal/src/pages/CampaignsPage.tsx) shows "Create campaign" when `world.create` is held and, with no campaigns, "Ask a GM to invite you".
- [components/ProfileMenu.tsx](../portal/src/components/ProfileMenu.tsx) and the `/platform/accounts` route adapter in [App.tsx](../portal/src/App.tsx) gate on `is_platform_administrator`. [UI_DESIGN.md §4.4](UI_DESIGN.md#44-platform-accounts-authorization) already anticipates a server capability such as `accounts.manage` replacing the flag.
- There is no world sharing screen and no system-role control on [pages/AdminAccountsPage.tsx](../portal/src/pages/AdminAccountsPage.tsx).

### 2.8 Deployment state (drives the migration policy)

No production deployment exists: [ADR 0013](adr/0013-locally-host-production-on-existing-mini-pc.md) is "planning; not yet implemented", and [PROJECT_STATUS.md](PROJECT_STATUS.md) calls the system pre-release. Populated databases are the owner's local/dev databases, development-data scripts ([scripts/setup_phase13c_dev_data.py](../scripts/setup_phase13c_dev_data.py), [scripts/setup_phase15_world_content.py](../scripts/setup_phase15_world_content.py)) and CI. The migration must upgrade a populated dev database correctly and round-trip; no zero-downtime or multi-release compatibility window is warranted.

### 2.9 Findings motivating this work (graded)

Graded with the E/I/T/D/B dimensions used in [PROJECT_STATUS.md](PROJECT_STATUS.md) (each 0–2). The full rubric text, including the score-to-severity bands above the Low (3) and Medium (4) examples it shows, is not in the repository, so only totals are given; the owner should confirm severity labels.

| # | Finding | Evidence | E/I/T/D/B | Total |
|---|---|---|---|---:|
| F1 | A campaign `gm`/`assistant_gm` on a shared world can create, edit, publish, archive, or supersede canon used by every campaign on that world | §2.5, `lock_authoring_scope` | 1/2/1/1/2 | 7 |
| F2 | World drafts, revisions, provenance, and GM-only prep authored from one campaign are readable by every other campaign's `canon.edit` holders on the world | §2.5 read side | 1/1/1/2/1 | 6 |
| F3 | `access.manage` in one campaign on a timeline lets the holder create further campaigns on that timeline without world authority (Path B) | §2.4 | 1/1/1/1/1 | 5 |
| F4 | World-creation eligibility can be minted by any campaign owner assigning the `gm` template | §2.1 | 1/1/1/0/1 | 4 |
| F5 | Disabling the sole owner/access manager strands a world or campaign with no in-app recovery | §2.2, §2.3 | 1/1/0/1/1 | 4 |

Exposure is E1 throughout because nothing is deployed to production (§2.8). None of these is a reason to change Phase 15; they are fixed by this workstream after Phase 15 merges (§12).

---

## 3. Decisions and recommended defaults

### D1. System roles: multiple assignments, union of explicit capabilities, no hierarchy

**Recommendation:** a user may hold **any combination** of the four system roles; effective system capabilities are the **union** of each held role's explicit set. There is no inheritance: Admin does not imply GM, GM does not imply Player.

- *Why multiple:* the common self-hosted owner is both Admin and GM; a single-role model would force an Admin-implies-GM hierarchy, which the brief rules out, or would force administrators to give up running games.
- *Alternative rejected:* one role per user with a fixed ordering (Admin > GM > Player > Observer). It silently grants GM eligibility to every admin and makes "an administrator who should not create worlds" inexpressible.
- An active account with **no** system role is valid and holds no system capabilities (equivalent to Observer for platform purposes). Account creation requires choosing at least one role (default Player), so this state arises only from deliberate revocation.

### D2. System capability matrix (closed, code-side)

Like world capabilities today, these are a closed mapping in a new `domain/system_authority.py`, **not** rows in `security.capabilities` (which is assignable to campaign roles).

| System capability | Admin | GM | Player | Observer | Meaning |
|---|:-:|:-:|:-:|:-:|---|
| `accounts.manage` | ✔ | | | | Create/disable/reactivate accounts, issue activation/reset links, revoke sessions |
| `system_roles.manage` | ✔ | | | | Assign/revoke GM, Player, Observer (Admin grant: see D3) |
| `world.create` | | ✔ | | | Create a world (creator becomes its Owner). Code kept for portal compatibility |
| `campaign.host` | | ✔ | | | Eligible to create a campaign (still needs world-use, D7) and to be assigned campaign roles that confer ownership or GM authority (D11) |

Player and Observer carry **no** platform capabilities in this work. They are explicit account classifications used as invitation/creation defaults and shown in administration. Whether a system Observer should be barred from campaign roles carrying write capabilities is an owner question (Q5); the recommended default is "classification only".

System capabilities never confer campaign membership, campaign capabilities, or world capabilities.

### D3. Transition from `is_platform_administrator`

**Recommendation:**

1. Backfill an `admin` assignment for every user with `is_platform_administrator = true` (any lifecycle status, so a later reactivation restores it).
2. Also backfill `gm` for those users. This preserves their current `world.create` (ADR 0018 gives it to admins); without it, a fresh install's bootstrap admin could no longer create the first world.
3. Backfill `player` for every other user.
4. **Do not** grant system `gm` to existing holders of the campaign `gm` template (consequences in §9.2).
5. Drop the column in the same revision; `is_platform_administrator()` becomes "holds an unrevoked `admin` assignment and the account is active". Downgrade re-adds and repopulates it.
6. Keep the bootstrap field `is_platform_administrator` as a **derived** compatibility value until the portal reads `accounts.manage` (same checkpoint, SR-2), then remove it.
7. `bootstrap_initial_admin` assigns `admin` + `gm`. `grant_platform_administrator.py` writes an `admin` assignment and remains the **only** way to grant Admin (D-10 preserved). Admins may assign GM/Player/Observer over HTTP and may **revoke** Admin over HTTP subject to the last-admin guard (Q1 asks whether HTTP Admin grant should be allowed).

*Alternative rejected:* keep the column as a mirror. Two sources of truth for the most sensitive flag, with no remaining reader, is a defect waiting to happen.

### D4. World roles and capability matrix

Extend `security.world_roles` with `world_editor`, `world_reviewer`, `world_reader` (codes stable; display names Owner/Editor/Reviewer/Reader). A user may hold **several** world roles on one world (e.g. Editor + Reviewer); capabilities are the union. **Owner explicitly lists** the editing and reviewing capabilities — not by inheritance, but because an owner who cannot edit their own world would simply self-assign Editor, so withholding them adds friction without separation of duties.

| World capability | Owner | Editor | Reviewer | Reader | Use grant |
|---|:-:|:-:|:-:|:-:|:-:|
| `world.view` — overview, timelines list | ✔ | ✔ | ✔ | ✔ | ✔ |
| `world.canon.read` — published canon, player-safe projection | ✔ | ✔ | ✔ | ✔ | |
| `world.canon.read_private` — drafts, GM-only fields, revisions, provenance, sources | ✔ | ✔ | ✔ | | |
| `world.canon.edit` — create/edit definitions, sources, world relationships; submit/return-to-draft/delete-draft | ✔ | ✔ | | | |
| `world.canon.review` — approve, reject, publish, supersede, archive, restore | ✔ | | ✔ | | |
| `world.manage` — settings, rulesets, calendars, archive/restore the world | ✔ | | | | |
| `timeline.manage` — create/branch/edit/archive timelines | ✔ | | | | |
| `world.share` — assign/end Editor/Reviewer/Reader, issue/revoke use grants | ✔ | | | | |
| `world.transfer` — add/remove Owners | ✔ | | | | |
| `campaign.create` — host a campaign on this world (D7) | ✔ | | | | ✔ |

- Self-approval is allowed when one person holds Editor + Reviewer (single-GM worlds would otherwise deadlock). Mandatory two-person review is not introduced.
- "Deletion" of a world means archive (rule 9, [ENTITY_LIFECYCLE.md §14](ENTITY_LIFECYCLE.md)); physical deletion stays limited to unreferenced drafts and fixtures.
- Archive/restore/supersede of canon are `world.canon.review`, not `world.canon.edit`, because they change what every campaign sees (Q13).

### D5. World Reader is scoped sharing

Reader grants `world.view` + `world.canon.read` only: **published** canon in its player-safe projection (the same projection rules players get). It never includes drafts, GM-only fields (`gm_notes`, secret names, hidden attributes), revisions, provenance, sources, or anything campaign-scoped. A Reader is not a member of any campaign and sees no campaign's events, state, knowledge, sessions, or AI output.

### D6. Campaign GM authority does not confer world authority (and vice versa)

`lock_authoring_scope` gains a **world** authorization step, resolved under the existing locks:

- World-definition **writes** (every row in §2.5's table except the exceptions in D8) require the matching world capability (`world.canon.edit` or `world.canon.review`) **and** the existing campaign `canon.edit` on the route campaign. Both are required because authoring routes are campaign-scoped (`/campaigns/{id}/…`) and their read models are perspective-bound; requiring both means a world Editor who is only a Player in campaign B cannot author through B, and a campaign GM without a world role cannot author shared canon.
- World-definition **private reads** (authoring views, drafts, review queue, revisions, provenance, sources) require `world.canon.read_private`. Campaign GMs without a world role keep reading **published** canon including its GM-only fields in their own campaign (they need them to run the game; see §5.3).
- Recommended now: no world-scoped authoring routes. A world Editor needs a campaign in which they hold `canon.edit` to author. A world-scoped authoring workspace (authoring without any campaign) is deferred (Q8).

### D7. Minimal world-use authorization

A new `security.world_use_grants` row (world, user, granted by, revoked at/by) confers `world.view` + `campaign.create` on that world and nothing else — no canon reads beyond what a campaign's own members get, no timeline management.

`create_campaign` authorizes exactly when **all** hold, re-checked under the existing world `FOR SHARE` / timeline `FOR UPDATE` locks:

1. the creator holds system `campaign.host` (GM);
2. the creator holds world `campaign.create` (Owner or an unrevoked use grant);
3. if the timeline already has a campaign, the creator holds `timeline.manage` (Owner) on its world — campaigns on one timeline share timeline state ([ADR 0003](adr/0003-separate-world-timeline-and-campaign.md)), so a use-grant holder may only start a campaign on a timeline with no campaign (the Owner provisions a branch per hosted campaign; Q6).

**Path B is removed.** The timeline bootstrap-grant path stays (trusted infrastructure only) but also requires condition 1. The creator receives **both** `campaign_owner` and `gm` in the same transaction.

Revoking a use grant stops *new* campaigns only; existing campaigns continue unchanged (the campaign is the user's own aggregate once created).

### D8. Campaign-originated records that live in world tables (explicit exceptions)

Three records are world-scoped by schema but created as part of running a campaign. Recommended classification (Q9):

| ID | Record | Recommendation |
|---|---|---|
| E1 | `core.world_times` via `create_world_time` | Stays authorized by campaign `canon.edit`. A time point is a shared anchor (label + sort key) needed to record any event; requiring world Editor would block play on a hosted world. UI copy states labels are visible to every campaign on the world. |
| E2 | `world.item_instances` via `item_instances.py` | Stays campaign-authorized (instances are created when loot is awarded; custody and state are timeline-scoped). SR-5 must verify that `origin_notes` is not readable from another campaign; if it is, restrict that field to `world.canon.read_private` or the creating context. |
| E3 | Player-character identity via `player_characters.py` | Stays campaign-authorized (`canon.edit`) until Phase 16 defines player authoring. Draft gating already hides unpublished PCs. |

Every other `lock_authoring_scope` caller is a world-definition write and follows D6.

### D9. Shared canon: live updates, not pinned revisions or forks

**Recommendation:** keep the existing model — campaigns see the current published definition. The protections are review (`world.canon.review` publishes), the append-only revision history (`core.entity_revisions`), supersession, and timeline branching for divergent *history/state*. Pinning a campaign to definition revisions, or forking a world's definitions, is deferred as a separate feature; nothing in this work requires it.

### D10. Authorship is provenance, not authority

Reuse §2.6's columns unchanged. Contributor credit is derived from `core.entity_revisions.created_by_user_id`; approval credit from `audit.change_log` approve/publish rows (and lifecycle revisions). Importer credit will use `core.source_documents.ingested_by_user_id` and Phase 18 batch provenance. Ownership transfer, role ending, grant revocation, and account disablement must not update or null any of these (tested in SR-4/SR-5). No new attribution table.

### D11. Campaign roles that require system GM eligibility

**Recommendation:** assigning (via `add_campaign_member`, `assign_membership_role`, `change_membership_role`, or campaign creation) a role that is the built-in `gm` template **or carries `access.manage`** requires the assignee to hold system `campaign.host` at that moment. All other roles — `assistant_gm`, `player`, `observer`, `import_reviewer`, `rules_curator`, custom roles without `access.manage` — need no system role (Q4).

- *Why:* campaign ownership and the GM seat are what a system GM "is eligible for"; the check is capability-based (`access.manage`) so a custom role cannot bypass it.
- **Assignment-time, not continuous.** Revoking someone's system GM does not strip existing campaign roles or world ownership (it would silently break running campaigns). It prevents new creation and new GM/owner assignments, and administration shows "holds campaign GM/owner without system GM" (Q3).
- A campaign GM status never borrows across campaigns: eligibility is a system check on the assignee; the authority itself is still the requested campaign's membership.

---

## 4. Account, invitation, and administration workflows

### 4.1 Creating a GM with no campaign

1. Admin opens Platform Accounts and either creates an account (login name, display name, **system roles**, default Player) or selects an existing one.
2. Admin assigns system **GM** (`POST /admin/accounts/{user_id}/system-roles`). Audited.
3. A new user receives the existing one-time activation link; activation creates credentials only. No campaign, world, or invitation is involved.
4. After sign-in, the GM's bootstrap has `campaigns: []` and `global_capabilities` ⊇ `{world.create, campaign.host}`. `/campaigns` shows **Create a world** and, if any world grants them `campaign.create`, **Create a campaign** (§7).
5. Creating a campaign assigns `campaign_owner` + `gm` to the creator explicitly, in the creating transaction (D7).

### 4.2 Who may change what

| Change | Who | Guard |
|---|---|---|
| Grant Admin | Out-of-band script only (D-10) | — |
| Revoke Admin | Admin (HTTP) | Last active admin (shared advisory lock, extended to revocation) |
| Assign/revoke GM, Player, Observer | Admin | Audited; never touches campaign or world rows |
| Assign/end Editor/Reviewer/Reader; issue/revoke use grants | World Owner (`world.share`) | Target must be an active account; non-disclosing account lookup by exact login name (reuse `find_eligible_campaign_account`'s pattern in [queries/access_overview.py](../src/dnd_ai/queries/access_overview.py)) |
| Add/remove world Owner; transfer ownership | World Owner (`world.transfer`) | New Owner must hold system `campaign.host` (world ownership is a GM-tier responsibility, mirroring world creation); DB retains ≥1 owner |
| Invite to a campaign; assign campaign roles | Campaign `access.manage` (unchanged) | D11 eligibility for GM/owner roles; DB keeps ≥1 access manager |
| Transfer campaign ownership | Campaign `access.manage` | New `transfer_campaign_ownership` wraps assign + optional revoke in one transaction and one audit record; D11 applies |

### 4.3 Invitations

- Inviting is unchanged: `access.manage`, no role carried, acceptance creates/reactivates membership only. **Acceptance never reads or writes system roles.** A GM then assigns campaign roles, subject to D11.
- Existing accounts: accept while signed in (unchanged).
- New accounts via invitation-authorized registration: the created account receives system **Player** explicitly in the registration transaction (never GM or Admin), so no account exists without a deliberate classification. Q12 asks whether invited registration should remain.

### 4.4 Revocation and disablement effects

All authority is resolved from current rows on every request, so every change takes effect on the next request (no caches to invalidate).

| Event | Effect |
|---|---|
| System GM revoked | No new worlds, campaigns, or GM/owner campaign assignments. Existing world roles and campaign roles remain (D11). |
| Admin revoked / account disabled | Loses `accounts.manage`/`system_roles.manage`; last-admin guard applies to both paths. |
| Account disabled | Every resolver already requires an active account, so all system, world, and campaign authority stops at once; sessions are revoked (existing). Rows are kept so reactivation restores access. The response and the accounts list report worlds/campaigns where this account was the **only** active owner/access manager (F5), and the recovery operations below apply. |
| World role ended | Immediate loss of that world capability; authored records and attribution unchanged. |
| Use grant revoked | No new campaigns on that world; existing campaigns unaffected. |
| Campaign membership ended / role revoked | Unchanged existing behavior. |

### 4.5 Administrative overrides (separate, deliberate, audited)

Routine Admin access grants **no** world or campaign reads. Two recovery operations exist, each an explicit command with its own audit record (`actor_user_id`, target, reason text required), callable only by an active Admin, and never folded into ordinary reads:

- `recover_world_ownership(world_id, new_owner_user_id, reason)` — only when the world has no owner with an **active account**; new owner must hold `campaign.host`.
- `recover_campaign_access_manager(campaign_id, new_user_id, reason)` — only when the campaign has no access manager with an active account; assigns `campaign_owner` (creating a membership if needed); D11 applies.

Recommended surface: commands plus operator scripts first (the posture of `claim_world_ownership.py` and `grant_platform_administrator.py`); an Admin portal action only if the owner wants it (Q11). No "view as admin" or perspective-merging override is added.

---

## 5. Shared-world and campaign boundaries

### 5.1 Classification of existing commands

| Class | Commands | Authority after this work |
|---|---|---|
| **Shared world canon** | §2.5 table except E1–E3; `worlds.py` settings; `world_time.create_calendar`; `timelines.py` | World capability (D4/D6) |
| **Campaign/timeline state** | `campaign_clock`, `character_builds`, `character_state`, `dungeon_state`, `encounter_*`, `event_corrections`, `events`, `interactions`, `item_operations`, `knowledge_runtime`, `movement`, `parties`, `party_members`, `quest_runtime`, `relationships` (state), `session_*`, `travel`, `ai_proposals`, `ai_npc` | Campaign capabilities only (unchanged) |
| **Campaign-originated world rows** | E1–E3 (D8) | Campaign `canon.edit` (explicit exception) |
| **Campaign-private material** | sessions, session participants, events, encounter preparation, knowledge runtime, access groups/grants, invitations, AI synthesis/NPC context | Campaign capabilities only; never reachable through world roles |
| **User-owned private material** | own account, own sessions, portal preferences; Phase 16 notes/theories | Self only |

### 5.2 Non-disclosure guarantees (each becomes a test)

World membership of any kind — and holding roles in another campaign on the same world — never exposes another campaign's private notes and preparation, unrevealed events, encounter plans, character knowledge or private state, import staging/proposals, AI context/summaries/answers, or player-private content. This already holds structurally because those reads go through `resolve_access_context` for the route campaign; SR-5 adds explicit regression tests rather than new mechanism.

### 5.3 The unavoidable spoiler limitation

Two different things must not be conflated:

- **World canon secrets** (an NPC's secret name, a quest definition's `gm_notes`, hidden knowledge-item definitions) are properties of the shared world. Anyone authorized to write or review that world — and every campaign GM who runs a campaign on it — necessarily knows them. This is inherent to sharing a world and is documented, not engineered around.
- **Campaign secrets** (events not yet revealed, encounter plans, session prep, what each character knows, AI context) live in campaign-scoped records and stay invisible to world roles and other campaigns.

Authoring guidance: campaign-specific planning belongs in campaign-scoped records (session and encounter preparation), not in world definitions' GM-only fields.

---

## 6. Proposed schema

One Alembic revision (number allocated from the head at implementation time, §12.4), following [DATABASE_CONVENTIONS.md](DATABASE_CONVENTIONS.md) §11 (lookups), §19.1 (FK indexes), §24 (audit), §25 (migrations, seeds), §27 (grants), §31 (comments), and §34 anti-patterns.

1. **`security.system_roles`** — standard lookup (`system_role_id`, `code`, `display_name`, `description`, `sort_order`, `is_active`), seeded via `database/seeds/security.system_roles.yaml` with `admin`, `gm`, `player`, `observer`. Protect the four codes from rename with `core.enforce_protected_lookup_codes()` (the revision-080 mechanism), since code-side capability mapping depends on them.
2. **`security.user_system_roles`** — `user_system_role_id PK`, `user_id FK → security.users ON DELETE RESTRICT` (immutable), `system_role_id FK` (immutable), `granted_by_user_id FK NULL` (NULL only for backfill/bootstrap/script rows), `granted_at`, `revoked_at NULL`, `revoked_by_user_id FK NULL`, `created_at`. Partial unique `(user_id, system_role_id) WHERE revoked_at IS NULL`; `CHECK (revoked_at IS NULL OR revoked_at >= granted_at)`; rows never deleted by commands.
3. **Backfill** per D3, then drop `security.users.is_platform_administrator`.
4. **World roles:** add `world_editor`, `world_reviewer`, `world_reader` to `security.world_roles.yaml`. Replace the "one open row per (world, user)" partial unique index with one on `(world_id, user_id, world_role_id) WHERE ended_at IS NULL`. Add `granted_by_user_id FK NULL` and `ended_by_user_id FK NULL` with partial FK indexes. The owner-retention trigger is unchanged (it already filters `wr.code = 'world_owner'`).
5. **`security.world_use_grants`** — `world_use_grant_id PK`, `world_id FK → core.worlds ON DELETE CASCADE` (immutable), `user_id FK` (immutable), `granted_by_user_id FK NOT NULL`, `granted_at`, `revoked_at NULL`, `revoked_by_user_id FK NULL`. Partial unique open `(world_id, user_id)`.
6. **Grants:** new tables get `app_read_write` through default privileges; `app_read_only` stays deny-by-default (revision `115`) except that `security.system_roles` joins `REPORTING_READABLE_TABLES` if `security.world_roles` is on it at implementation time.
7. **No DB enforcement of D11 or last-admin.** Both are application checks under locks (D11 is an assignment-time eligibility rule, not an invariant; last-admin keeps the existing advisory-lock design). A DB backstop for last-admin is a reasonable alternative but not required by any observed failure.
8. **Downgrade:** re-add `is_platform_administrator` populated from unrevoked `admin` assignments; delete non-owner world-membership rows, restore the original unique index; drop new tables and seed rows.

---

## 7. API contracts

All mutations: human principals only, CSRF + allowed Origin for cookie callers, `Idempotency-Key` through `security.idempotent_requests` with actor scope in the fingerprint, one `audit.change_log` row per real change, none on no-op replays, non-disclosing 404 for unknown/unauthorized targets.

**Session bootstrap (`GET /auth/session`)**
- Add `system_roles: string[]` (display only).
- `global_capabilities` becomes the union from D2 (`accounts.manage`, `system_roles.manage`, `world.create`, `campaign.host`), still computed per user and empty for non-human principals.
- Each `campaigns[]` entry adds `world_capabilities: string[]` — the caller's capabilities on that campaign's world — so the portal can present authoring as read-only without inferring.
- `is_platform_administrator` stays derived until SR-2's portal change lands, then is removed.

**System administration** (all require `accounts.manage` or `system_roles.manage` as noted; checks live in the commands, as today)
- `GET /admin/accounts` adds `system_roles` per account and a filter `?system_role=`; adds `holds_campaign_lead_without_gm: bool` (D11 report).
- `POST /admin/accounts` accepts `system_role_codes` (default `["player"]`; `admin` refused with 422 per D-10).
- `POST /admin/accounts/{user_id}/system-roles` `{system_role_code}` → 201/200-replay; `admin` refused.
- `POST /admin/accounts/{user_id}/system-roles/{system_role_code}/revoke` → 409 `last_active_platform_administrator` where applicable.
- Disable response gains `stranded: {world_ids: [], campaign_ids: []}` (IDs only; the admin is not shown names they could not otherwise read). Q11 covers whether that disclosure is acceptable.

**World access** (`require_world_capability`)
- `GET /worlds/{world_id}/access` (`world.share`): role assignments and use grants with display names and granted-by.
- `POST /worlds/{world_id}/roles` `{login_name, role_code}` (`world.share`; `world_owner` requires `world.transfer`).
- `POST /worlds/{world_id}/roles/{world_membership_id}/end`.
- `POST /worlds/{world_id}/use-grants` `{login_name}`; `POST /worlds/{world_id}/use-grants/{id}/revoke`.
- `POST /worlds/{world_id}/ownership-transfer` `{login_name, retain_previous_owner_as: null | "world_editor" | "world_reviewer" | "world_reader"}`.
- `GET /worlds` lists worlds where the caller holds any world role or an open use grant, each with `capabilities` and `role_codes`.
- Errors: `world_role_target_ineligible` (409, inactive target account), `target_requires_system_gm` (409, a new Owner without system GM), `world_owner_required` (409, the retention trigger, mapped).

**Campaigns**
- `POST /campaigns`: D7 authorization; response unchanged; errors `system_gm_required` (403, the caller lacks system `campaign.host`) and the existing non-disclosing `TimelineNotAuthorizedError`.
- Role-assignment endpoints add `target_requires_system_gm` (409, D11). `GET /campaigns/{id}/access-overview` marks assignable roles that the target is ineligible for, so the UI can explain rather than fail.
- `POST /campaigns/{id}/ownership-transfer` (`access.manage`).

**Authoring and review routes** keep their paths; their dependency/command gains the D6 world check. Error for a campaign GM without world authority: the existing non-disclosing `CampaignNotAuthorizedError` mapping is **not** reused (the user can see the record); return 403 `world_authority_required` so the UI can explain.

**Recovery** (`accounts.manage`, Admin only): `POST /admin/recovery/world-ownership`, `POST /admin/recovery/campaign-access-manager` — only if Q11 approves HTTP; otherwise scripts.

---

## 8. UI flows and navigation

Every gate below reads server data (`global_capabilities`, `world_capabilities`, per-world `capabilities`, `available_actions`) — never role labels. Hiding is presentation; the server re-checks.

- **Profile menu / Platform Accounts:** gate on `accounts.manage` (replacing `is_platform_administrator`, per [UI_DESIGN.md §4.4](UI_DESIGN.md#44-platform-accounts-authorization)).
- **Platform Accounts page:** system-role badges per account; a "System roles" editor (checkboxes for GM/Player/Observer; Admin shown read-only with the recovery-runbook note); create-account form gains the system-role choice; filter by role; a notice for "campaign GM/owner without system GM".
- **Accounts with no campaigns (`/campaigns`, `/home` resolver):**
  - GM: "You are not in any campaigns yet." with **Create a world**, and **Create a campaign** when any world grants `campaign.create`.
  - Player/Observer: the existing "Ask a GM to invite you" plus **Accept a campaign invitation**.
  - Sidebar structure is unchanged; campaign entries stay disabled with "Select a campaign first".
- **Worlds:** the list shows the caller's world roles ("Owner", "Editor · Reviewer", "Reader", "Can host campaigns"). A new **Sharing** page (`/worlds/:worldId/sharing`, owner only; a disabled non-link otherwise, following the stable-structure rule) lists role holders and use grants with add/end/revoke and ownership transfer (confirmation dialog; focus returns to the trigger).
- **World overview for a Reader or use-grant holder:** read-only; Readers get a published-canon browser (SR-7); use-grant holders see world metadata and "Host a campaign here".
- **Campaign setup (`/campaigns/new`):** world picker lists only worlds with `campaign.create`; timeline picker lists only timelines the server says are eligible (D7 rule 3) with a reason for disabled ones.
- **Campaign authoring screens:** when `world_capabilities` lacks `world.canon.edit`, editors open read-only with "Editing shared world content requires the world Editor role (ask the world owner)". Review actions follow `world.canon.review`. E1–E3 screens are unaffected.
- **Access page:** the role picker explains D11 ineligibility inline.

[UI_DESIGN.md](UI_DESIGN.md) §3, §4.3, §4.4, §4.6, §5.2, §6.4 and §8 are updated in the same checkpoints.

---

## 9. Migration, seed, fixture, and compatibility policy

### 9.1 Backfill (D3)

| Existing state | After migration |
|---|---|
| `is_platform_administrator = true` | `admin` + `gm` |
| Every other user (any lifecycle) | `player` |
| `world_owner` rows | Unchanged |
| Campaign roles of every kind | Unchanged |

### 9.2 Consequences of not promoting campaign GMs

- Users who today create worlds only through a campaign `gm` assignment (ADR 0018) **lose** `world.create` and campaign creation until an Admin assigns system GM. The accounts filter "campaign GM/owner without system GM" lists them for a one-pass review.
- Campaign GMs without world roles keep running their campaigns but **cannot edit shared world definitions** on worlds they do not own (F1 fixed). On a typical dev database the owner already owns the worlds (claimed via `claim_world_ownership.py` or created in-app), so the visible impact is limited to secondary GMs. If the owner wants them to keep authoring, they assign world Editor explicitly after upgrade.
- Nothing is deleted; no attribution changes.

### 9.3 Seeds, fixtures, and scripts

- Seeds: new `security.system_roles.yaml`; three rows appended to `security.world_roles.yaml` (lookups are replay-safe; idempotency re-verified per §25.6).
- [tests/factories.py](../tests/factories.py): `make_user(..., platform_administrator=True)` writes an `admin` assignment; add `make_system_role_assignment`, `make_world_role`, `make_world_use_grant`. Test builders that author worlds today become admins (ADR 0018); they must now assign `gm` and, for non-owners, world roles explicitly.
- [scripts/bootstrap_admin.py](../scripts/bootstrap_admin.py), [scripts/grant_platform_administrator.py](../scripts/grant_platform_administrator.py), [scripts/setup_phase13c_dev_data.py](../scripts/setup_phase13c_dev_data.py), [scripts/setup_phase15_world_content.py](../scripts/setup_phase15_world_content.py): assign system roles explicitly; the dev data's GM accounts get system `gm`.
- Compatibility: `world.create` keeps its code and bootstrap location; `is_platform_administrator` stays in the bootstrap (derived) until the portal moves to `accounts.manage` in the same checkpoint. No other compatibility shims.

---

## 10. Audit requirements

One `audit.change_log` row per real change, no secrets or narrative in metadata, no row on idempotent replays:

| Command | Category / action |
|---|---|
| `assign_system_role`, `revoke_system_role` | `system_role` · assigned / revoked (metadata: role code, target user id) |
| `assign_world_role`, `end_world_role` | `world_access` · role assigned / ended |
| `grant_world_use`, `revoke_world_use` | `world_access` · use granted / revoked |
| `transfer_world_ownership` | `world_access` · ownership transferred (from/to user ids, retained role) |
| `transfer_campaign_ownership` | `membership` · ownership transferred |
| `recover_world_ownership`, `recover_campaign_access_manager` | `administrative_override` · reason text (bounded, required) |
| Backfill | none per row; the migration docstring records the policy |

The campaign audit-history read ([AUDIT_HISTORY_API.md](AUDIT_HISTORY_API.md)) does not show system or world events; a world-scoped audit read is out of scope.

---

## 11. Implementation checkpoints

Each checkpoint is one short-lived branch/PR (or commit group), with focused tests and docs in the same change, merged in order. "Done" means the listed tests pass locally against PostgreSQL 18, the full suites and portal checks pass, and final-head CI is green ([DEVELOPMENT.md §10](DEVELOPMENT.md#10-definition-of-done)).

**SR-0 — Decision record (docs only).** New ADR "Scoped system, world, and campaign roles" (number allocated at write time) superseding ADR 0018 and amending ADR 0014 D2/D4/D5 and ADR 0015 D3, recording D1–D11 and the owner's answers to §14.
*Accept:* owner approval recorded; ADR 0014/0015/0018 status lines updated.

**SR-1 — System-role schema and resolution.** Migration (§6 items 1–3, 6, 8 for system roles); `domain/system_authority.py`; `queries/system_authority.py` (`resolve_system_capabilities`); `is_platform_administrator()` reimplemented on assignments; last-admin count on assignments; bootstrap `system_roles` + new `global_capabilities`; `may_create_worlds` → `world.create` from GM only; factories/scripts.
*Accept:* backfill test on a populated pre-upgrade database (admin→admin+gm, others→player, campaign `gm` holders unchanged); downgrade round trip restores the column; bootstrap returns the right capability sets for each role combination; a campaign-`gm` holder without system GM gets 403 on `POST /worlds`.

**SR-2 — System-role administration.** Commands, routes (§7), audit, idempotency; Platform Accounts UI; profile menu on `accounts.manage`; remove `is_platform_administrator` from the bootstrap; invited registration assigns Player.
*Accept:* admin assigns/revokes GM; non-admin gets non-disclosing 404; revoking the last admin → 409 under concurrent attempts (real-PostgreSQL race test reusing the advisory lock); invited registration yields exactly `player`; portal tests for the editor and the menu gate.

**SR-3 — Campaign creation eligibility.** D7: system `campaign.host` + world `campaign.create` + timeline rule; remove Path B; bootstrap-grant path requires GM; creator gets `campaign_owner` + `gm`.
*Accept:* tests for each of: owner GM succeeds; owner without system GM refused; use-grant holder on unused timeline succeeds and on used timeline refused; former Path B caller refused; creator holds both roles; no campaign borrowing across a shared timeline.

**SR-4 — World roles, use grants, sharing, transfer.** Migration (§6 items 4–5); capability matrix D4; resolver returns multiple roles; world access routes; ownership transfer; Sharing page; `GET /worlds` includes Readers/Editors/Reviewers/use grants.
*Accept:* Editor+Reviewer combination yields the union; last-owner end refused; transfer keeps `core.entities.created_by_user_id` and revision authors unchanged; non-owner gets 404/403 per existing world rules; Sharing UI tests including confirmation focus.

**SR-5 — World canon boundary.** `lock_authoring_scope` world step (D6) with lock order documented in [SYSTEM_ARCHITECTURE.md §7.1](architecture/SYSTEM_ARCHITECTURE.md); lifecycle split edit/review; private reads (`world.canon.read_private`) for authoring views, review queue, revisions, provenance, sources; E1–E3 left on campaign `canon.edit` (verify E2 `origin_notes`); bootstrap `world_capabilities`; portal read-only presentation.
*Accept:* campaign GM without world role → 403 on every world-definition write and private read in §2.5, and still reads published canon (with GM-only fields) in their campaign; Editor without Reviewer cannot publish; Reviewer without Editor cannot create; E1–E3 still work for campaign GMs; cross-campaign non-disclosure tests (§5.2) for sessions, events, encounter prep, knowledge runtime, AI synthesis cache/context, proposals, search; concurrency test: world role ended mid-command is honored under the new lock.

**SR-6 — Campaign role eligibility, transfers, recovery.** D11 in all assignment commands and the access overview; `transfer_campaign_ownership`; stranded reporting on disable; recovery commands (+ scripts, or routes if Q11).
*Accept:* assigning `gm`/owner/custom-`access.manage` role to a non-GM → 409; to a GM → OK; revoking system GM leaves existing campaign roles intact and is listed in the admin report; recovery refused while an active owner exists, succeeds otherwise, and writes an override audit row; admin with no campaign membership still gets 404 on every campaign read.

**SR-7 — World Reader surface (minimal).** World-scoped published-canon browse using the player-safe projection already used for campaign readers (no new projection rules).
*Accept:* Reader sees published canon only; no drafts, GM-only fields, revisions, provenance, or any campaign data; non-Reader gets 404. *Deferrable* if the owner prefers (Q7).

**SR-8 — End-to-end scenario and documentation closure.** A `tests/scenario` test of §4.1 plus the shared-world case below; manual validation (§13.2); docs (§13.3); verification record.
*Accept:* scenario passes on a clean database; manual checklist recorded; final-head CI green.

Shared-world scenario for SR-8: Admin creates GM-A and GM-B; GM-A creates world W and campaign A; GM-A grants GM-B a use grant and branches a timeline; GM-B creates campaign B on it; GM-B invites P, who is Player in B and (invited by GM-A) Observer in A. Assert: GM-B cannot edit W's definitions until made Editor; GM-A sees nothing of campaign B; P's capabilities in A and B differ; nothing of A's prep, events, knowledge, or AI output is visible from B.

---

## 12. Coordination with Phase 15

### 12.1 Overlapping files and contracts

High churn on `phase15/completion`; expect conflicts:

- [queries/world_authority.py](../src/dnd_ai/queries/world_authority.py), [domain/world_authority.py](../src/dnd_ai/domain/world_authority.py) — ADR 0018 itself is Phase 15 work and is replaced here.
- [commands/_content.py](../src/dnd_ai/commands/_content.py) (`lock_authoring_scope`), [commands/_operations.py](../src/dnd_ai/commands/_operations.py), [commands/entity_lifecycle.py](../src/dnd_ai/commands/entity_lifecycle.py), and the ~14 command modules that call them.
- [queries/review_queue.py](../src/dnd_ai/queries/review_queue.py), [queries/provenance.py](../src/dnd_ai/queries/provenance.py), the authoring read models (`available_actions`).
- [commands/campaigns.py](../src/dnd_ai/commands/campaigns.py), [commands/worlds.py](../src/dnd_ai/commands/worlds.py), [api/local_auth.py](../src/dnd_ai/api/local_auth.py), [queries/bootstrap.py](../src/dnd_ai/queries/bootstrap.py), [domain/access.py](../src/dnd_ai/domain/access.py).
- [tests/factories.py](../tests/factories.py) and the Phase 15 clean-database exit scenario / final-acceptance guards.
- Portal: [App.tsx](../portal/src/App.tsx), [utils/worldAccess.ts](../portal/src/utils/worldAccess.ts), `WorldsNavGroup`, `CampaignsPage`, `CampaignSetupPage`, `AdminAccountsPage`, `ProfileMenu`, bootstrap fixtures/types.
- Docs: DATABASE_MODEL §19, DOMAIN_MODEL world authority, UI_DESIGN, PLAN/PLANv2, PROJECT_STATUS, PHASE15_VERIFICATION.
- Migration head.

### 12.2 Safe to start after this plan is approved (before Phase 15 merges)

- SR-0 (ADR and doc drafts on this branch).
- Pure code with unit tests and no imports from churned modules: `domain/system_authority.py`, the D4 world capability table, D11 eligibility predicate.
- Drafting the migration body without fixing its revision id or `down_revision`.

### 12.3 Wait for Phase 15 to merge

SR-1 onward, because each touches the bootstrap, factories, `lock_authoring_scope`, or the Phase 15 exit scenario that Phase 15's own acceptance is still validating.

### 12.4 Synchronization checkpoint

Before implementation and again before merge, fetch origin and reconcile subsequent `phase15/completion` changes while that branch remains active. Once Phase 15 merges, synchronize with `origin/main`. Revalidate authorization contracts, affected files, and the migration head after synchronization. Specifically re-check: §2.5's writer list (new `lock_authoring_scope` callers), §2.4's authorization paths, the bootstrap shape, and that no new role/capability seed landed. Allocate the migration revision id and `down_revision` from `alembic heads` **at implementation time**; never reuse a number from this plan or from another branch.

### 12.5 Impact on Phase 15 imports, approval, promotion, provenance

- **Imports:** Phase 15 has none (import tables do not exist; import is Phase 18). Phase 18 must promote world-canon proposals only for world Reviewers (or Owners) and campaign-scoped proposals for campaign `import.approve`; `import_reviewer` alone never publishes world canon.
- **Approval:** entity lifecycle approve/publish/reject/supersede/archive move from campaign `canon.edit` to `world.canon.review` (+ campaign `canon.edit` route context). AI proposal review stays campaign-scoped (it changes campaign state).
- **Promotion:** unchanged mechanism; promoted records still go through the same commands and therefore the same world checks.
- **Provenance:** reads move to `world.canon.read_private`; attribution columns untouched.
- **Authorization:** Phase 15's ADR 0018 tests are rewritten, not extended.

### 12.6 Later phase gates and sequencing (recommendation only; the plan is not renumbered)

- Land SR-1…SR-8 **after Phase 15 merges and before Phase 16 starts** (Q10). Phase 16's privacy exit criteria ("GM-role users must not access player-private material") should be tested against the final role model, and its "multi-GM worlds" revisit noted in ADR 0015 is exactly D6.
- Phase 15's clean-database exit scenario gains one setup step after merge (bootstrap admin is GM, or admin assigns GM) — made in SR-1 as a test-fixture change, not a change to Phase 15 scope.
- Phase 17 browser acceptance adds "admin creates GM without campaign" and "world sharing".
- Phase 18 import authorization follows §12.5.

---

## 13. Tests, manual validation, documentation

### 13.1 Focused automated tests (smallest that prove each invariant)

- **Unit:** system and world capability unions for every role combination; no hierarchy (Admin alone lacks `world.create`); D11 predicate including custom roles carrying `access.manage`.
- **Database:** constraint positive/negative tests for both new tables and the changed world index; seed idempotency; protected lookup codes; populated upgrade + downgrade round trip; FK indexes and comments present.
- **Command:** each §11 acceptance item; last-admin and last-owner races (reuse existing race-test patterns); world role ended mid-authoring.
- **API:** CSRF/Origin, idempotent replay without duplicate audit, non-disclosing 404s, error codes in §7.
- **Non-disclosure regression:** §5.2 matrix, one test per category, from a user holding a world role and a role in another campaign.
- **Portal:** gates read only server fields (no role-label inference), Sharing page, Platform Accounts role editor, no-campaign GM empty state, read-only authoring presentation.

No new harness or fault-injection work is planned (PLAN §24.1 proportionality).

### 13.2 Manual validation checklist

1. Fresh install: bootstrap admin can create a world and a campaign.
2. Admin creates a new account with GM only; activation link works; the GM lands on an empty `/campaigns` with Create a world.
3. GM creates a world and campaign; Access shows them as campaign owner and GM.
4. Admin revokes the GM's system GM: existing campaign still works; Create a world disappears; admin list flags the account.
5. Owner shares the world: Editor, Reviewer, Reader, and a use grant to another GM; each sees exactly the expected controls.
6. The hosting GM creates a campaign on an owner-provisioned branch; cannot pick a timeline already in use.
7. A campaign GM without a world role sees authoring as read-only with the explanation; can still record events and create world-time points.
8. Same person is GM in one campaign and Player in another on the same world: switching campaigns changes capabilities; nothing leaks.
9. Ownership transfer with "retain as Editor"; authored records still show the original creator.
10. Disable the sole owner of a world: admin sees it reported; recovery restores ownership with an audit entry.
11. Last admin cannot be revoked or disabled.
12. Keyboard and screen-reader pass over the Sharing page and the system-role editor; narrow and wide layouts.

### 13.3 Documentation updated during implementation

- New ADR (SR-0); status notes on ADR 0014, 0015, 0018.
- [DATABASE_MODEL.md](architecture/DATABASE_MODEL.md) §19.1 (remove the flag, add system roles), §19.2a (roles, multi-role index, use grants), §19.3 (system templates are not system assignments), §5.3a/§5.5 read gating.
- [DOMAIN_MODEL.md](DOMAIN_MODEL.md) world authority paragraph and §23 Security domain (system role, world roles, world-use grant vocabulary).
- [SYSTEM_ARCHITECTURE.md](architecture/SYSTEM_ARCHITECTURE.md) §18 security model and §7.1 lock order.
- [ENTITY_LIFECYCLE.md](ENTITY_LIFECYCLE.md) §3.1a and lifecycle transition authority.
- [UI_DESIGN.md](UI_DESIGN.md) as listed in §8; [PHASE13E_ACCESS_CONTRACT.md](PHASE13E_ACCESS_CONTRACT.md) §3p/§4 (system roles replace the flag).
- [operations/PLATFORM_ADMINISTRATOR_RECOVERY.md](operations/PLATFORM_ADMINISTRATOR_RECOVERY.md), [LOCAL_DEPLOYMENT.md](LOCAL_DEPLOYMENT.md) (upgrade note: assign system GM and world Editors after upgrade).
- [PLAN.md](PLAN.md)/[PLANv2.md](PLANv2.md) authoring matrix (§16) and [PROJECT_STATUS.md](PROJECT_STATUS.md) — status only, when checkpoints close.
- A verification record for the workstream when it closes.

---

## 14. Owner decisions required

| # | Question | Recommendation |
|---|---|---|
| Q1 | May an Admin grant Admin over HTTP, or does D-10's out-of-band rule stay? | Keep out-of-band; allow HTTP revoke with last-admin guard |
| Q2 | Backfill existing admins with GM as well? | Yes (preserves current world creation) |
| Q3 | Is system-GM eligibility checked only at assignment time, or continuously? | Assignment time; report mismatches |
| Q4 | Which campaign roles require system GM? | Built-in `gm` and any role carrying `access.manage` only |
| Q5 | Should system Observer restrict campaign role assignment? | No; classification only for now |
| Q6 | May use-grant holders create branch timelines for their campaigns? | No; the Owner provisions branches |
| Q7 | Ship the Reader browse surface (SR-7) now or defer? | Ship minimal SR-7; defer if Phase 16 timing is tight |
| Q8 | World-scoped authoring without a campaign? | Defer; require world role + campaign `canon.edit` now |
| Q9 | Accept exceptions E1–E3 as campaign-authorized? | Yes, with E2 verification in SR-5 |
| Q10 | Sequence this between Phase 15 merge and Phase 16 start? | Yes |
| Q11 | Recovery overrides over HTTP, or scripts only? Is listing stranded IDs to the disabling admin acceptable? | Scripts first; IDs-only report acceptable |
| Q12 | Keep invitation-authorized registration (accounts created by an invitation) with system Player? | Keep; it never grants more than Player |
| Q13 | Archive/restore/supersede of canon: Reviewer (recommended) or Editor? | Reviewer |
| Q14 | Confirm severity bands for §2.9 totals (the rubric's band table is not in the repository) | — |

---

## 15. Exclusions and dependencies

**Excluded:** hosted/multi-tenant ownership scopes (ADR 0014 alternative; Phase 22); world forks and per-campaign revision pinning (D9); world-scoped authoring workspace (Q8); world-scoped audit history; mandatory two-person review; custom system roles or a system-role hierarchy; mapping OIDC claims to system roles; email delivery; admin impersonation/preview-as-user; Phase 16 private collaboration; Phase 18 import staging; retiring `security.timeline_bootstrap_grants` (Phase 18 review per ADR 0014).

**Dependencies:** Phase 15 merged (§12.3); PostgreSQL 18 locally and in CI; existing advisory-lock and retention-trigger patterns; existing idempotency, audit, CSRF/Origin, and non-disclosure infrastructure.

**Recommended first implementation checkpoint:** SR-0 (ADR recording the answers to §14), then SR-1 (system-role schema, backfill, and resolver), because every later checkpoint depends on `campaign.host` and the removal of the `is_platform_administrator` flag, and SR-1 is the smallest change that fixes F4 on its own.
