# Phase 13E access-management contract inventory

Written for the 13E-A increment (read-only campaign access overview,
`docs/PLAN.md` §13) and updated for 13E-B's first mutation checkpoint
(campaign-role change). Records what the backend actually exposes for
GM access management as of these increments — not a design proposal, and
not a claim that Phase 13E or any of its remaining mutation work is
complete. **13E-A (the read-only overview) and 13E-B checkpoint 1 (change
an existing member's campaign-role assignment) are delivered.** Everything
else below marked "reserved for a later increment" is existing backend
capability with no portal UI yet, or (where noted) a backend contract that
does not exist at all yet.

## 1. Existing read endpoints

| Endpoint | Module | Capability | Notes |
|---|---|---|---|
| `GET /campaigns/{campaign_id}/access-overview` | `dnd_ai.api.access_overview` | `access.manage` | New in 13E-A. See §3. |

No other read endpoint exposes campaign membership, role, character-relationship, or resource-grant state — confirmed by inspection of `dnd_ai.api.memberships`, `dnd_ai.api.access_grants`, and `dnd_ai.api.campaign_invitations` (all write-only; see §2).

## 2. Existing mutation endpoints (reserved for a later 13E increment, except where noted)

| Endpoint | Method | Module | Capability | Boundary |
|---|---|---|---|---|
| `/campaigns/{campaign_id}/memberships` | POST | `dnd_ai.api.memberships` | `access.manage` | Campaign-scoped |
| `/campaigns/{campaign_id}/memberships/{membership_id}/roles` | POST | `dnd_ai.api.memberships` | `access.manage` | Campaign-scoped |
| `/campaigns/{campaign_id}/memberships/roles/{membership_role_id}/revoke` | POST | `dnd_ai.api.memberships` | `access.manage` | Campaign-scoped |
| `/campaigns/{campaign_id}/memberships/roles/{membership_role_id}/change` | POST | `dnd_ai.api.memberships` | `access.manage` | Campaign-scoped — **portal-wired, 13E-B checkpoint 1.** See §3a. |
| `/campaigns/{campaign_id}/memberships/{membership_id}/character-relationships` | POST | `dnd_ai.api.access_grants` | `access.manage` | Campaign-scoped |
| `/campaigns/{campaign_id}/character-relationships/{id}/revoke` | POST | `dnd_ai.api.access_grants` | `access.manage` | Campaign-scoped |
| `/campaigns/{campaign_id}/resource-grants` | POST | `dnd_ai.api.access_grants` | `access.manage` | Campaign-scoped |
| `/campaigns/{campaign_id}/resource-grants/{id}/revoke` | POST | `dnd_ai.api.access_grants` | `access.manage` | Campaign-scoped |
| `/campaigns/{campaign_id}/invitations` | POST | `dnd_ai.api.campaign_invitations` | `access.manage` | Campaign-scoped (returns a raw invitation token — never suitable to echo in a list contract) |
| `/campaign-invitations/accept` | POST | `dnd_ai.api.campaign_invitations` | none (`require_human_user_id` only) | Self-service |
| `/campaigns` | POST | `dnd_ai.api.campaigns` | none at the route; real authorization inside `dnd_ai.commands.campaigns.create_campaign` | Human, but not generically self-service — see §4 |
| `/admin/accounts` | POST | `dnd_ai.api.local_auth` | `security.users.is_platform_administrator` (checked in-command) | Platform-administrator |
| `/admin/accounts/{user_id}/password-reset` | POST | `dnd_ai.api.local_auth` | `is_platform_administrator` | Platform-administrator |
| `/admin/accounts/{user_id}/disable` | POST | `dnd_ai.api.local_auth` | `is_platform_administrator` | Platform-administrator |
| `/admin/accounts/{user_id}/reactivate` | POST | `dnd_ai.api.local_auth` | `is_platform_administrator` | Platform-administrator |
| `/admin/accounts/{user_id}/revoke-sessions` | POST | `dnd_ai.api.local_auth` | `is_platform_administrator` | Platform-administrator |
| `/auth/activate`, `/auth/password-reset`, `/auth/change-password`, `/auth/sessions` (list/delete own) | various | `dnd_ai.api.local_auth` | none — acts on the caller's own account | Self-service |

None of the campaign-scoped rows above pass `allow_foundry_access=True` to `require_campaign_capability` — see §4.

## 3. `GET /campaigns/{campaign_id}/access-overview` (new, 13E-A)

- **Capability:** `access.manage`, resolved via the existing `dnd_ai.api.access.require_campaign_capability` dependency — the identical gate every mutation endpoint in §2 already uses for the same category of action.
- **Boundary:** campaign-scoped, human principal only (local-session or OIDC — see §4; Foundry-adapter credentials are rejected).
- **Request:** `campaign_id` path parameter (UUID) only. No query parameters, no request body.
- **Response (`CampaignAccessOverviewResponse`):** `{ members: [CampaignMemberSummaryResponse], assignable_roles: [AssignableRoleResponse] }`, one member entry per currently open (`ended_at IS NULL`) campaign membership:
  - `campaign_membership_id` (UUID — identity only, never rendered as page text)
  - `display_name`, `status_code`, `status_display_name`, `joined_at`
  - `roles: [{ membership_role_id, role_id, code, display_name }]` — active (non-revoked, non-expired, `is_active`) roles only. `membership_role_id` (13E-B) is the identifier the portal's role-change control targets — identity only, never rendered as page text, matching `campaign_membership_id`'s own contract.
  - `character_relationships: [{ membership_character_relationship_id, character_id, character_display_name, relationship_type_code, relationship_type_display_name, granted_at, expires_at }]` — current (non-revoked, non-expired, timeline-scoped) relationships only
  - `grants: [{ resource_grant_id, capability_code, capability_display_name, effect, target_type, reason, granted_at, expires_at }]` — current, membership-targeted (not access-group-targeted), active-capability resource grants only (see the capability-parity correction below)
  - `assignable_roles: [{ role_id, code, display_name }]` (13E-B) — every role currently usable by this campaign (`dnd_ai.queries.access_overview.list_assignable_campaign_roles`: a system template or a role scoped to this campaign, `is_active`), campaign-level rather than per-member since this codebase's role model carries no hierarchy — the read-contract counterpart to §3a's mutation, so the portal never hardcodes or guesses the assignable set.
- **Pagination/filtering:** none. Per-campaign membership/role/relationship/grant counts are expected to stay small (matching the existing precedent in `dnd_ai.api.memberships`/`.access_grants`, neither of which paginates); no cursor, no limit, no total count.
- **401:** unauthenticated requests never reach this route's own logic — `dnd_ai.api.auth.get_authenticated_user_id` (the same dependency every other route uses) rejects them first; this route adds no separate 401 handling.
- **403:** an authenticated member of the campaign who does not hold `access.manage`.
- **404:** no active, authorizing membership in the campaign at all, **or** the campaign does not exist — both indistinguishable, matching `require_campaign_capability`'s existing non-disclosing contract (the same 404 shape `dnd_ai.api.memberships`/`.access_grants` already give).
- **Validation:** a malformed `campaign_id` (not a UUID) is rejected by FastAPI's own path-parameter validation before any handler code runs (422).
- **Recoverable errors:** any other failure (5xx) is not specially handled by this route and surfaces as a generic error to the portal's existing recoverable-error boundary with retry.
- **Audience-safe fields:** `security.users.display_name` only (never `email`, never a login identifier, never `external_identities.subject`); `membership_statuses.display_name` (campaign-scoped status, not the account-wide `lifecycle_status_id`); `roles.display_name`/`code`; `character_relationship_types.display_name`/`code` plus the related character's `core.entities.canonical_name`; `capabilities.display_name`/`code`, `effect`, `target_type` (the grant's target *kind* only — `character`/`entity`/`knowledge_item`/`quest`/`session`/`event` — never the specific target resource's own display identity), `reason`, `granted_at`, `expires_at`.
- **Correction (review pass):** the resource-grants query now also requires `security.capabilities.is_active`, matching `dnd_ai.domain.access.resolve_access_context`'s own resource-grant resolution — an otherwise-current grant of a *deactivated* capability confers no effective access there and must not appear here as a current grant either. Covered by `tests/database/test_api_access_overview.py::test_a_grant_of_a_deactivated_capability_is_excluded_while_an_active_one_remains`.

## 3a. `POST /campaigns/{campaign_id}/memberships/roles/{membership_role_id}/change` (new, 13E-B checkpoint 1)

The first Phase 13E-B mutation checkpoint: lets an authorized campaign
access manager change an existing, currently active campaign member's role
assignment. Scope is deliberately narrow — see `docs/PLAN.md` §13 for what
this checkpoint excludes (invitations, account lifecycle, session
revocation, character-relationship/explicit-grant changes, every other
access-management mutation).

- **Role model discovered:** `security.membership_roles` lets one
  `security.campaign_memberships` row hold **multiple simultaneous active
  roles** (`ux_membership_roles_active` only forbids two *active* rows for
  the *same* role on the same membership) — never a single-valued
  "current role" column. Roles are **temporal**: a row is never updated in
  place; it is revoked (`revoked_at` set) and a new row inserted.
  Accordingly this checkpoint changes **one targeted role assignment**
  (`membership_role_id`), not "the member's role" — any other role the
  same membership independently holds is left untouched, so a multi-role
  membership never has its whole role set silently replaced.
- **Capability:** `access.manage`, via the identical `require_campaign_capability`
  dependency every other row in §2 uses.
- **Request (`ChangeMembershipRoleRequest`):** `{ new_role_id: UUID }`. Route
  path carries `campaign_id` and the target `membership_role_id`.
- **Response (`MembershipRoleResponse`, reused from the existing assign-role
  contract):** `{ membership_role_id: UUID }` — the id of the *new* row
  created by this change (the old one is revoked, not reused, per the
  temporal-history point above). `201`, matching `assign_membership_role`'s
  own status code for "a new row now exists," even though an existing row
  also changed.
- **Assignable-role read contract:** §3's new `assignable_roles` field —
  every role usable by this campaign (system template or campaign-scoped),
  currently `is_active`. No hierarchy or delegation narrows this further:
  this codebase's role model is flat, so every role `access.manage` may
  assign is equally assignable to any member, including the actor's own.
- **Self-change:** permitted, with no special-case check anywhere in the
  stack. The only thing that can block a self-change is the retention
  invariant below — including when the caller is changing their own last
  qualifying assignment.
- **Last-manager protection:** enforced server-side, evaluated *after* both
  the revoke and the new assignment apply within the same transaction —
  `security.campaign_has_access_manager(campaign_id)`, the identical
  read-only helper `revoke_membership_role`'s own pre-check already uses,
  scoped identically to *active* campaigns only (a `pending`/`draft`
  campaign's sole `access.manage` holder may freely change away from it).
  A change that would leave an active campaign with no membership holding
  `access.manage` raises a plain `ValueError`, mapped to **400** —
  deliberately the same status code (not 409) `revoke_membership_role`
  already uses for the identical invariant, so the two routes stay
  consistent rather than the newer one inventing a different contract for
  the same failure.
- **Active-state boundary (correction pass):** the target `membership_role_id`
  must currently be an *eligible, active* assignment — the identical
  "currently true" definition §3's `roles` field already uses to decide
  what to show as a member's current role, so this mutation can never act
  on a row the read side would no longer show as active:
  - not already revoked (`revoked_at IS NULL`);
  - not expired (`expires_at IS NULL OR expires_at > now()`);
  - its *current* role still `is_active`;
  - its owning membership not ended (`ended_at IS NULL`) and in the
    `active` membership status (`security.membership_statuses.code =
    'active'` and `.is_active`).

  Any of these failing raises `MembershipRoleNotActiveError`, mapped to
  **409** — identically for all of them (already revoked, expired, current
  role deactivated, or membership ended/non-active), so a caller can never
  learn *which* condition applied, only that the assignment is no longer a
  valid target. The candidate `new_role_id` is held to the same activeness
  bar: an inactive role is rejected by the *existing* `RoleNotUsableByCampaignError`
  (**404**) — grouped with "not usable by this campaign" rather than a new
  shape, since an inactive role was never a legitimate target in the first
  place (unlike the 409 cases above, which *were* valid a moment ago).
- **Same-role no-op (correction pass):** if `new_role_id` names the role
  `membership_role_id` already, currently holds, the request is rejected
  as `ChangeMembershipRoleNoOpError`, mapped to **422** ("malformed or
  invalid role request"), checked before any write. No revoke, no new row,
  no audit entry — and critically, no idempotency-key completion, so a
  caller who corrects their selection and retries with the *same*
  `Idempotency-Key` still gets the real command run rather than a cached
  "successful" no-op. The portal disables Save for this exact case so it
  is rarely reached at all; the server-side check is defense in depth.
- **Concurrency (correction pass):** two independent guarantees, both
  proven by real-connection PostgreSQL regression tests
  (`tests/database/test_membership_role_concurrency.py`):
  - *Eligibility-check/write race:* the target row, its owning membership,
    and its current role are locked together (`FOR UPDATE OF mr, cm, r`)
    before any eligibility check runs, and the candidate `new_role_id` row
    is separately locked (`FOR UPDATE`) before its own check — so a
    concurrent deactivation of either role, or a concurrent ending of the
    membership, cannot slip in between this function's own read and
    write. A concurrent change/revoke of the identical `membership_role_id`
    is serialized the same way (same-row coverage) — the loser observes
    the winner's committed effect (already-revoked) once unblocked, never
    an interleaved write.
  - *Campaign `access.manage` retention:* this checkpoint adds no locking
    of its own for this — it relies entirely on the pre-existing
    `security.assert_campaign_retains_access_manager()` (migration 080),
    which locks `campaign.campaigns` `FOR UPDATE` and is invoked by a
    `DEFERRABLE INITIALLY DEFERRED` constraint trigger on `security.
    membership_roles`, evaluated against the fully-committed final state
    at commit time. Two concurrent changes (or a change racing a revoke)
    against *different* management-granting rows can never both commit
    when their combined effect would leave an active campaign with zero
    qualifying managers — the loser is rejected either by this route's own
    app-level pre-check (a **400** `ValueError`, if its check happens to
    run after the winner already committed) or by the database's deferred
    trigger (a **5xx**-mapped `IntegrityError`, if both sides write before
    either commits) — which mechanism catches it is a genuine timing
    outcome of the real race, not something either the application or a
    caller controls.
- **Idempotency:** the same durable, PostgreSQL-backed
  `security.idempotent_requests` mechanism `assign_membership_role`/
  `create_campaign_membership` already use — an `Idempotency-Key` replay
  returns the original response verbatim rather than re-running the
  command. The portal (correction pass) now generates and sends this
  header itself: one opaque key (`crypto.randomUUID()`) per logical
  `(membership_role_id, new_role_id)` edit, reused verbatim across a retry
  of that exact selection (an unknown network outcome), regenerated the
  moment the selection changes (a different role row, or a different
  target role on the same row), and cleared entirely on confirmed success
  — so a later edit, even one that happens to choose the identical role
  again, always gets a fresh key rather than risking a replay of a stale
  cached response. See `portal/src/hooks/useChangeMembershipRole.ts`.
- **Cross-campaign/unknown-role rejection:** identical to `assign_membership_role`'s
  existing checks — a `membership_role_id` outside `campaign_id`, or a
  `new_role_id` neither a system template nor scoped to `campaign_id`
  (including a nonexistent one), both raise `MembershipNotInCampaignError`/
  `RoleNotUsableByCampaignError` (**404**, non-disclosing — a caller can
  never tell "doesn't exist" from "belongs to a different campaign").
- **Audit:** one `audit.change_log` row (`change_action_code = 'updated'`,
  `table_name = 'membership_roles'`, `record_id` = the new
  `membership_role_id`), atomic with the state change, recording
  `actor_user_id`, `world_id` (the campaign's own pinned timeline's world —
  never a caller-supplied value), `previous_status`/`new_status` (the old
  and new role **codes** — reusing `audit.change_log`'s pre-existing
  lifecycle-transition columns, the same ones `dnd_ai.commands.local_auth`'s
  account disable/reactivate commands already populate), and
  `changed_fields = { "previous_membership_role_id": "<uuid>" }` for
  traceability back to the revoked row. No credential, session token, or
  CSRF token ever reaches this record.
- **CSRF/Origin:** this route carries no CSRF logic of its own — like every
  other cookie-authenticated mutation in this application, `dnd_ai.api.auth`'s
  global `_enforce_csrf_and_origin` (checked for every `POST`/`PUT`/`PATCH`/
  `DELETE` against a browser-session principal) requires a matching
  `X-CSRF-Token` header and an allowed `Origin`; a missing/mismatched token
  or a disallowed/missing `Origin` is rejected before this route's own logic
  ever runs.
- **Effective immediately:** the change is visible on the next
  `GET .../access-overview` request and the next `/auth/session` bootstrap
  — no caching layer sits in front of either.

## 4. Principal/boundary summary

- **Local-session/OIDC-human:** `dnd_ai.api.auth.require_human_user_id` accepts only `LOCAL_SESSION_AUTH_METHOD` and `OIDC_AUTH_METHOD`. Every campaign-scoped access-management route (§2's campaign-scoped rows, plus the new overview read) is reachable by either.
- **Platform-administrator:** `/admin/accounts*` (`dnd_ai.api.local_auth`) — gated on `security.users.is_platform_administrator`, checked *inside* the command (a non-platform-administrator caller gets a fixed, non-disclosing 404, not 403). Entirely separate from any campaign's `access.manage` — a campaign owner is not automatically a platform administrator, and vice versa.
- **Campaign-scoped:** every `access.manage`-gated route in §2, plus the new overview read — authorization is per-campaign, resolved fresh per request via `dnd_ai.domain.access.resolve_access_context`.
- **Self-service:** routes that act only on the caller's own account/own invitation with no special capability (`/auth/login`, `/auth/logout`, `/auth/change-password`, `/auth/sessions` list/delete-own, `/auth/activate`, `/auth/password-reset`, `POST /campaign-invitations/accept`).
- **Foundry/machine boundary:** a `FOUNDRY_ACCESS_AUTH_METHOD`-authenticated principal may reach a campaign-scoped route only when that route explicitly opts in via `require_campaign_capability(..., allow_foundry_access=True, foundry_scope=...)`. **None** of the access-management routes in §2, nor the new access-overview read, opt in — a paired Foundry device or its adapter credential cannot list, create, or revoke any membership, role, relationship, or grant, and cannot read the new overview either. The retired `FOUNDRY_SYSTEM_AUTH_METHOD` cannot reach any authenticated route at all (rejected earlier, in `get_authenticated_user_id` itself).
- **`POST /campaigns` (its own category):** callable by any human principal, but real authorization is inside `dnd_ai.commands.campaigns.create_campaign` (pre-existing `access.manage` in another campaign attached to the same timeline, plus a positively issued `security.timeline_bootstrap_grants` row) — not a generic "any authenticated human may create any campaign" self-service contract.

## 5. Missing contracts deferred to a later Phase 13E increment

No backend read/write contract exists yet for:

- Listing pending/outstanding `security.campaign_invitations` for a campaign.
- Access-group management: creating an access group, listing its members, or adding/removing a membership from one — `security.access_groups`/`.access_group_memberships` exist in schema and are read internally by `dnd_ai.domain.access.resolve_access_context`, but no API route anywhere creates, lists, or mutates them.
- Any audit-history read endpoint — `audit.change_log` rows are written by every mutation above, but no route reads them back.
- A preview-as-user/perspective workflow (docs/UI_DESIGN.md §6.3) — no existing endpoint.
- A UI for the remaining mutation endpoints in §2: adding/removing a campaign member, bare role assignment (adding a role a member does not yet hold) or revocation (removing one with no replacement), character-relationship grant/revocation, resource-grant creation/revocation, invitation issuance, account creation/activation/reset/disable/reactivate/revoke-sessions. **Changing an existing member's role assignment is now wired (§3a, 13E-B checkpoint 1)** — the one exception to this list.

None of the above is implemented yet. 13E-A was read-only; 13E-B checkpoint 1 adds exactly the one mutation in §3a and nothing else in this list.

## 6. Manual-validation development fixture accounts

**Development-only. Never applicable to a real deployment.** `scripts/setup_phase13c_dev_data.py` (the same idempotent, preview-by-default Phase 13C/13D fixture script) now also provisions five deterministic local accounts so the Phase 13E-A Access overview can be exercised by hand against a real local PostgreSQL server — the local dev database otherwise contains only the pre-existing administrator/GM account, which cannot alone exercise a non-GM path, a second campaign's isolation, or a disabled account.

### Safe invocation

The script already refuses to run against anything but a local/self-hosted development database (`DND_AI_ENVIRONMENT` must be a local/dev value; a non-loopback `DATABASE_URL` host or a production-looking database name aborts unless `DND_AI_ALLOW_NONLOCAL_DEV_DATA=1` explicitly acknowledges it) and prints a password-redacted summary of the resolved target before any write. It now also requires `PHASE13E_DEV_ACCOUNT_PASSWORD` — checked before any database connection is opened at all:

```powershell
$env:PHASE13E_DEV_ACCOUNT_PASSWORD = Read-Host "Phase 13E development account password"
uv run python scripts/setup_phase13c_dev_data.py --user-id <existing-admin-user-id>            # preview (rolled back)
uv run python scripts/setup_phase13c_dev_data.py --user-id <existing-admin-user-id> --apply    # write
```

- **Never commit a real value.** `PHASE13E_DEV_ACCOUNT_PASSWORD` belongs only in your own shell session, or in the gitignored `.env` (see `.env.example`'s own placeholder) — never in a tracked file, never printed by this script, never in a commit.
- **Rerun safely at any time.** Every step is create-or-reuse by a fixed, deterministic key (normalized login name; `(campaign, user)` for a membership; `(membership, role)` for a role; `(campaign, grantee, capability, character)` for a grant) — a second `--apply` reuses every row, creates nothing new, and never rotates an already-created account's password. The one exception, `_ensure_phase13e_account_disabled`, is itself idempotent (disabling an already-disabled account is a documented no-op).
- **Recognize the intended local database** by the printed `target database (password redacted): ...` line before any write — it must name your own local/self-hosted PostgreSQL server (`127.0.0.1:5432` by default per `docs/DEVELOPMENT.md` §3.1), never a shared or production-looking host/database name.

### Seeded accounts

| Login | Display name | Campaign | Role (capability) | Character relationship | Explicit grant |
|---|---|---|---|---|---|
| `phase13e.gm2` | Phase13E Dev GM2 | Phase13C Campaign A | `campaign_owner` (`access.manage`) | none | none |
| `phase13e.player_a` | Phase13E Dev Player A | Phase13C Campaign A | `player` (`campaign.view` only) | `owner` relationship to Phase13C Character A | one revoked grant (`character.view_summary`) — must not appear on the overview |
| `phase13e.observer_a` | Phase13E Dev Observer A | Phase13C Campaign A | `observer` (`campaign.view` only) | none | one active grant (`character.view_full` on Phase13C Character A) — must appear |
| `phase13e.player_b` | Phase13E Dev Player B | Phase13C Campaign B | `player` (`campaign.view` only) | none (Campaign B has no character fixture of its own) | none |
| `phase13e.disabled` | Phase13E Dev Disabled Player | Phase13C Campaign A | `player` (`campaign.view` only), then disabled | none | none |

All five share the one password supplied via `PHASE13E_DEV_ACCOUNT_PASSWORD` for that run. The pre-existing administrator/GM account is never modified — no password, login identifier, membership, role, capability, or session change.

### 13E-B checkpoint 1 manual-validation scenarios

No seed change was needed for this checkpoint — the existing five accounts
above already exercise every rule §3a documents:

- **Ordinary role change:** log in as `phase13e.gm2`, open Campaign A's
  Access page, choose the "Change role" control on `phase13e.player_a`'s
  `player` role, select `observer`, Save. The overview refreshes to show
  `observer` in place of `player`; `phase13e.player_a`'s unrelated
  character relationship/grant rows are unaffected.
- **Last-manager protection (self-change):** still as `phase13e.gm2` —
  Phase13C Campaign A is `active` and `phase13e.gm2` is its sole
  `access.manage` holder (`campaign_owner`) — attempt to change `gm2`'s own
  role to `player`. Rejected (400); `gm2` keeps `campaign_owner` and the
  Access nav item remains visible on the next request.
- **Non-manager self-change:** log in as `phase13e.observer_a` — no
  `access.manage`, so the Access page (and its role-change control) is
  never reachable at all; confirms the control's absence is not the only
  thing standing between a non-manager and this mutation (`POST
  .../roles/{membership_role_id}/change` also still returns 403 directly).
- **Cross-campaign isolation:** as `phase13e.gm2` (Campaign A only), a
  direct `POST /campaigns/<campaign_a_id>/memberships/roles/<a
  membership_role_id belonging to Campaign B>/change` returns 404 — the
  same non-disclosing contract §3a documents.
- **Idempotent replay:** repeating the same change request with the same
  `Idempotency-Key` returns the original response unchanged, without
  creating a second new role-assignment row. The portal itself now
  generates and reuses this header automatically — no manual header
  entry is needed to exercise it by hand; a genuine network retry (e.g.
  toggling dev tools offline mid-Save) is the observable case.
- **Same-role no-op (correction pass):** in the Change-role control, the
  Save button stays disabled while the selected role equals the row's
  current role — there is no UI path to submit a no-op at all. A direct
  `POST .../roles/{membership_role_id}/change` with `new_role_id` equal
  to the row's current role returns 422 and leaves the row untouched.
- **Active-state boundary (correction pass):** these conditions are not
  reachable through the seeded dev accounts without a direct database
  edit (none of the five accounts' assignments are expired, ended, or
  role-deactivated), so this checkpoint's PostgreSQL-backed tests
  (`tests/database/test_api_memberships.py`) are the authoritative
  coverage for expired assignments, ended/non-active memberships, and
  inactive current/new roles — all rejected with a non-disclosing 409/404
  per §3a, never a 5xx.

### Expected access behavior

- **GM2** can log in and open the Access page directly, with no platform-administrator privilege needed — it holds `access.manage` only through the ordinary `campaign_owner` role.
- **Player A** and **Observer A** hold no `access.manage`: the Access nav item must not appear for either, and a direct `GET /campaigns/{campaign_a_id}/access-overview` request must return `403`.
- **Cross-campaign isolation:** Player A never sees Campaign B in their campaign list (no membership, no relationship reaching it); Player B never sees Campaign A, and vice versa.
- **Grants:** on Campaign A's Access overview, Observer A shows exactly one grant (`View Character Full Detail`); Player A shows none — the revoked grant is excluded, proving the same exclusion `tests/database/test_api_access_overview.py` already covers automatically.
- **Disabled account:** `phase13e.disabled` cannot authenticate and holds no usable browser session, but its Campaign A membership still appears on the Access overview with an ordinary "Active" *membership* status — `dnd_ai.queries.access_overview` deliberately never consults account-wide `security.users.lifecycle_status_id` (see §3 above). This is the documented contract, not a defect; the fixture does not invent a "disabled" label the implemented response does not provide.
