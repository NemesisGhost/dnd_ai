# Phase 13E access-management contract inventory

Written for the 13E-A increment (read-only campaign access overview,
`docs/PLAN.md` §13) and updated for 13E-B's mutation checkpoints
(campaign-role change; add one role; revoke one role; add an existing
account as a member; remove an existing membership; add/change/revoke a
member's character relationship; add/revoke a member's direct resource
grant). Records what the backend actually exposes for GM access management
as of these increments — not a design proposal, and not a claim that Phase
13E or any of its remaining mutation work is complete. **13E-A (the
read-only overview), 13E-B checkpoint 1 (change an existing member's
campaign-role assignment), 13E-B checkpoint 2 (add one additional role to,
and revoke one existing role from, an existing active campaign
membership), 13E-B checkpoint 3 (add an existing account to the campaign
with one initial role; end an existing membership), 13E-B's
character-relationship-management checkpoint (add a character relationship
to an existing membership; change an existing relationship's type; revoke
a character relationship — see §3g/§3h/§3i/§3j), and 13E-B checkpoint 5
(add a direct, character-targeted resource grant to an existing
membership; revoke an existing resource grant — see §3k) are
delivered.** Everything else below marked "reserved for a later increment"
is existing backend capability with no portal UI yet, or (where noted) a
backend contract that does not exist at all yet.

## 1. Existing read endpoints

| Endpoint | Module | Capability | Notes |
|---|---|---|---|
| `GET /campaigns/{campaign_id}/access-overview` | `dnd_ai.api.access_overview` | `access.manage` | New in 13E-A. **Extended, checkpoint 5**: `grantable_resource_capabilities` metadata and per-grant `target_id`/`target_display_name`. See §3/§3k. |
| `GET /campaigns/{campaign_id}/eligible-accounts` | `dnd_ai.api.access_overview` | `access.manage` | New in 13E-B checkpoint 3 — exact-match account lookup for "Add campaign member". See §3d. |

No other read endpoint exposes campaign membership, role, character-relationship, or resource-grant state — confirmed by inspection of `dnd_ai.api.memberships`, `dnd_ai.api.access_grants`, and `dnd_ai.api.campaign_invitations` (all write-only; see §2).

## 2. Existing mutation endpoints (reserved for a later 13E increment, except where noted)

| Endpoint | Method | Module | Capability | Boundary |
|---|---|---|---|---|
| `/campaigns/{campaign_id}/memberships` | POST | `dnd_ai.api.memberships` | `access.manage` | Campaign-scoped — **portal-wired, 13E-B checkpoint 3** (hardened to require an initial `role_id`; previously reserved/unused). See §3e. |
| `/campaigns/{campaign_id}/memberships/{membership_id}/end` | POST | `dnd_ai.api.memberships` | `access.manage` | Campaign-scoped — **new, portal-wired, 13E-B checkpoint 3.** See §3f. |
| `/campaigns/{campaign_id}/memberships/{membership_id}/roles` | POST | `dnd_ai.api.memberships` | `access.manage` | Campaign-scoped — **portal-wired, 13E-B checkpoint 2.** See §3b. |
| `/campaigns/{campaign_id}/memberships/roles/{membership_role_id}/revoke` | POST | `dnd_ai.api.memberships` | `access.manage` | Campaign-scoped — **portal-wired, 13E-B checkpoint 2.** See §3c. |
| `/campaigns/{campaign_id}/memberships/roles/{membership_role_id}/change` | POST | `dnd_ai.api.memberships` | `access.manage` | Campaign-scoped — **portal-wired, 13E-B checkpoint 1.** See §3a. |
| `/campaigns/{campaign_id}/memberships/{membership_id}/character-relationships` | POST | `dnd_ai.api.access_grants` | `access.manage` | Campaign-scoped — **portal-wired, hardened, character-relationship-management checkpoint.** See §3h. |
| `/campaigns/{campaign_id}/character-relationships/{id}/change` | POST | `dnd_ai.api.access_grants` | `access.manage` | Campaign-scoped — **new, portal-wired, character-relationship-management checkpoint.** See §3i. |
| `/campaigns/{campaign_id}/character-relationships/{id}/revoke` | POST | `dnd_ai.api.access_grants` | `access.manage` | Campaign-scoped — **portal-wired, hardened, character-relationship-management checkpoint.** See §3j. |
| `/campaigns/{campaign_id}/resource-grants` | POST | `dnd_ai.api.access_grants` | `access.manage` | Campaign-scoped — **portal-wired, hardened, checkpoint 5** (character targets only). See §3k. |
| `/campaigns/{campaign_id}/resource-grants/{id}/revoke` | POST | `dnd_ai.api.access_grants` | `access.manage` | Campaign-scoped — **portal-wired, hardened, checkpoint 5.** See §3k. |
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
- **Response (`CampaignAccessOverviewResponse`):** `{ members: [CampaignMemberSummaryResponse], assignable_roles: [AssignableRoleResponse], assignable_characters: [AssignableCharacterResponse], assignable_relationship_types: [AssignableCharacterRelationshipTypeResponse], grantable_resource_capabilities: [GrantableResourceCapabilityResponse] }` (`assignable_characters`/`assignable_relationship_types` are character-relationship-management checkpoint — see §3g; `grantable_resource_capabilities` is checkpoint 5 — see §3k), one member entry per currently open (`ended_at IS NULL`) campaign membership:
  - `campaign_membership_id` (UUID — identity only, never rendered as page text)
  - `display_name`, `status_code`, `status_display_name`, `joined_at`
  - `account_is_active` (checkpoint-6 correction) — a single derived boolean (`security.users.lifecycle_status_id -> core.lifecycle_statuses.code = 'active'`), never the raw status code, login name, email, or identity subject. Added so the portal's access-group "Add member" selector (§3l) can exclude a membership `add_access_group_member` would reject anyway (its owning account platform-disabled) instead of offering it and having the request always fail.
  - `roles: [{ membership_role_id, role_id, code, display_name }]` — active (non-revoked, non-expired, `is_active`) roles only. `membership_role_id` (13E-B) is the identifier the portal's role-change control targets — identity only, never rendered as page text, matching `campaign_membership_id`'s own contract.
  - `character_relationships: [{ membership_character_relationship_id, character_id, character_display_name, relationship_type_code, relationship_type_display_name, granted_at, expires_at }]` — current (non-revoked, non-expired, timeline-scoped, fictional-time-unbounded — checkpoint-4 correction) relationships **whose character is itself currently active** (checkpoint-4 review correction: a relationship to a character deactivated/archived after the relationship was granted is now excluded here too, matching `dnd_ai.domain.access.resolve_access_context`'s own identical exclusion) only
  - `grants: [{ resource_grant_id, capability_code, capability_display_name, effect, target_type, target_id, target_display_name, reason, granted_at, expires_at }]` — current, membership-targeted (not access-group-targeted), active-capability resource grants **whose target is itself currently active** (checkpoint 5, the identical generalization of the character-relationship exclusion above — see §3k) only (see the capability-parity correction below). `target_id` (checkpoint 5) is identity only, never rendered as page text, matching every other raw id in this response — populated for all six target kinds so the portal can detect an exact active duplicate combination when adding a new grant. `target_display_name` (checkpoint 5) is populated only for a `character` target (`core.entities.canonical_name`, the same safe name `character_relationships` already uses) and `null` for every other target kind — see the audience-safe-fields note below.
  - `assignable_roles: [{ role_id, code, display_name }]` (13E-B) — every role currently usable by this campaign (`dnd_ai.queries.access_overview.list_assignable_campaign_roles`: a system template or a role scoped to this campaign, `is_active`), campaign-level rather than per-member since this codebase's role model carries no hierarchy — the read-contract counterpart to §3a's mutation, so the portal never hardcodes or guesses the assignable set.
- **Pagination/filtering:** none. Per-campaign membership/role/relationship/grant counts are expected to stay small (matching the existing precedent in `dnd_ai.api.memberships`/`.access_grants`, neither of which paginates); no cursor, no limit, no total count.
- **401:** unauthenticated requests never reach this route's own logic — `dnd_ai.api.auth.get_authenticated_user_id` (the same dependency every other route uses) rejects them first; this route adds no separate 401 handling.
- **403:** an authenticated member of the campaign who does not hold `access.manage`.
- **404:** no active, authorizing membership in the campaign at all, **or** the campaign does not exist — both indistinguishable, matching `require_campaign_capability`'s existing non-disclosing contract (the same 404 shape `dnd_ai.api.memberships`/`.access_grants` already give).
- **Validation:** a malformed `campaign_id` (not a UUID) is rejected by FastAPI's own path-parameter validation before any handler code runs (422).
- **Recoverable errors:** any other failure (5xx) is not specially handled by this route and surfaces as a generic error to the portal's existing recoverable-error boundary with retry.
- **Audience-safe fields:** `security.users.display_name` only (never `email`, never a login identifier, never `external_identities.subject`); `membership_statuses.display_name` (campaign-scoped status, not the account-wide `lifecycle_status_id`); `roles.display_name`/`code`; `character_relationship_types.display_name`/`code` plus the related character's `core.entities.canonical_name`; `capabilities.display_name`/`code`, `effect`, `target_type` (the grant's target *kind* only — `character`/`entity`/`knowledge_item`/`quest`/`session`/`event` — never the specific target resource's own display identity for the five non-character kinds), `reason`, `granted_at`, `expires_at`; `account_is_active` (checkpoint-6 correction) — one derived boolean, never the account-wide `lifecycle_status_id` code itself.
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

## 3b. `POST /campaigns/{campaign_id}/memberships/{campaign_membership_id}/roles` (hardened, 13E-B checkpoint 2)

The route and command (`assign_membership_role`) already existed — this
checkpoint hardens the command to the same "currently true" eligibility bar
§3a's checkpoint-1 correction pass already established for `change_
membership_role`, then wires it into the portal as the Access page's
"Add role" action for an existing member. Never creates a membership; only
adds one role to a membership that already exists.

- **Capability:** `access.manage`, via the identical `require_campaign_capability` dependency every other row in §2 uses.
- **Request (`AssignMembershipRoleRequest`):** `{ role_id: UUID, expires_at?: datetime }`. Route path carries `campaign_id` and the target `campaign_membership_id`. `expires_at` is a pre-existing field this checkpoint does not remove; the portal's own Add-role control never sets it (no UI for a time-limited grant yet).
- **Response (`MembershipRoleResponse`):** `{ membership_role_id: UUID }` — the new row's id. `201`, unchanged.
- **Eligibility (hardened this checkpoint):** all checked before any write, all raising identically within each group so a caller cannot distinguish which condition applied:
  - the target `campaign_membership_id` must belong to `campaign_id` (pre-existing; `MembershipNotInCampaignError`, 404, non-disclosing — identical for "doesn't exist" and "belongs to a different campaign");
  - the membership must be currently open (`ended_at IS NULL`) and in the `active` membership status (`security.membership_statuses.code = 'active'` and `.is_active`) — **new**;
  - the membership's own user account must currently be platform-active (`security.users.lifecycle_status_id` -> `core.lifecycle_statuses.code = 'active'`, the identical account-usability check every login path in this codebase already applies) — **new**; both of the two conditions above raise `MembershipNotActiveError` (409);
  - the `role_id` must be a system template or scoped to `campaign_id`, **and** currently `is_active` (`RoleNotUsableByCampaignError`, 404 — the `is_active` half is **new**; the scope half is pre-existing) — matching `dnd_ai.queries.access_overview.list_assignable_campaign_roles`'s own assignable-role definition exactly, so a role the read-contract would never offer can never be assigned either;
  - a duplicate still-active assignment of the same role to the same membership is rejected as a 409 by the pre-existing `ux_membership_roles_active` unique index (existing `IntegrityError` handler) — not pre-checked, matching this module's documented "database-enforced invariants this module deliberately does not duplicate" policy.
- **Concurrency (new):** the target membership row, then its owning user row, then the candidate role row are locked (`FOR UPDATE OF cm` / `FOR UPDATE OF u` / `FOR UPDATE`, in that order — always membership-then-role, the same order `change_membership_role` already uses for its own target/candidate pair, so the two commands can never deadlock against each other) before any eligibility check runs — so a concurrent ending of the membership, a concurrent disablement of its user account, or a concurrent deactivation of the candidate role cannot slip in between this function's own read and its later `INSERT`. Proven by real-connection PostgreSQL regression tests (`tests/database/test_membership_role_concurrency.py`): assign vs. membership-ending, assign vs. role-deactivation, assign vs. account-disablement.
- **Idempotency/audit:** unchanged from the pre-existing contract — the same durable `Idempotency-Key` mechanism, one `audit.change_log` row per successful call, atomic with the insert.
- **Sibling roles:** untouched — this inserts exactly one new row; any other role the same membership independently holds is unaffected.
- **Actor scope:** `granted_by_membership_id` is always the caller's own resolved `AccessContext.campaign_membership_id` — never caller-supplied, so it is same-campaign by construction.

## 3c. `POST /campaigns/{campaign_id}/memberships/roles/{membership_role_id}/revoke` (hardened, 13E-B checkpoint 2)

The route and command (`revoke_membership_role`) already existed — this
checkpoint closes a duplicate-audit gap in the *route*, then wires it into
the portal as the Access page's "Revoke role" action. Never ends a
membership; revokes exactly one role assignment.

- **Capability:** `access.manage`, via the identical `require_campaign_capability` dependency every other row in §2 uses.
- **Request:** no body. Route path carries `campaign_id` and the target `membership_role_id`. Accepts an optional `Idempotency-Key` header — **new this checkpoint**.
- **Response contract change:** previously a bodyless `204 No Content`; now `200`/`MembershipRoleResponse` (`{ membership_role_id: UUID }`, reusing the existing assign-role response shape) — needed so `begin_idempotent_request`/`complete_idempotent_request` have a response to cache. See `revoke_membership_role_endpoint`'s own docstring for the full "why" (the duplicate-audit gap this closes).
- **Active-state/eligibility:** unchanged from the pre-existing contract. `revoke_membership_role` does **not** require the target to currently be an eligible/active assignment the way `change_membership_role` requires of its own target — an already-revoked row is a documented, harmless no-op (`RevokeMembershipRoleResult.revoked = False`), proven by the pre-existing, unmodified `tests/database/test_membership_role_concurrency.py::test_a_change_and_a_revoke_targeting_the_identical_row_serialize`. A nonexistent `membership_role_id`, or one belonging to a different campaign, is still rejected identically as `MembershipNotInCampaignError` (404, non-disclosing).
- **Idempotency/audit (hardened this checkpoint):** the pre-checkpoint-2 route wrote one `audit.change_log` row on *every* call, including a plain retry against an already-revoked row — a genuine, if narrow, duplicate-audit gap for an ordinary network retry with no `Idempotency-Key` reuse. Fixed two ways: (1) an `Idempotency-Key` replay (the same durable `security.idempotent_requests` mechanism §3a/§3b already use) returns the cached response verbatim without re-running the command at all; (2) independent of any key, the route's audit write is now conditioned on `RevokeMembershipRoleResult.revoked` — `False` (the no-op case) writes no audit row at all, so even a retry that reaches the command a second time under a *different* (or no) key converges on one real revocation and exactly one audit record.
- **Last-manager protection:** unchanged — `security.campaign_has_access_manager(campaign_id)`, scoped to *active* campaigns only, evaluated after the write; skipped entirely for the no-op case (nothing changed, so nothing can newly violate the invariant).
- **Self-revocation:** permitted, with no special-case check anywhere in the stack — identical to `change_membership_role`'s own self-change policy. The only thing that can block it is the retention invariant above.
- **Concurrency (new regression coverage; behavior itself unchanged):** the pre-existing `FOR UPDATE` lock on the target row already served same-row serialization (see the pre-existing change-vs-revoke same-row test); this checkpoint adds a revoke-vs-revoke same-row test and a revoke-vs-revoke different-management-row retention-race test (`tests/database/test_membership_role_concurrency.py`), completing the same "every pairing of change/revoke against the same or different management-granting rows" coverage §3a already established for change-vs-change and change-vs-revoke.
- **Sibling roles:** untouched — only the named row is revoked.

## 3d. `GET /campaigns/{campaign_id}/eligible-accounts` (new, 13E-B checkpoint 3)

The account-selection read contract behind the portal Access page's "Add
campaign member" action. Never a directory/search endpoint — see the
design note below.

- **Capability:** `access.manage`, via the identical `require_campaign_capability` dependency every other row in §2/§3 uses.
- **Request:** `campaign_id` path parameter plus one required query parameter, `login_name` (string, 1-64 characters — the same bound `dnd_ai.commands.local_auth`'s own login-name format constraint allows, so a longer value can never match a stored one and is rejected by FastAPI's own query-parameter validation, 422, before reaching the database).
- **Response (`EligibleAccountLookupResponse`):** `{ account: { user_id, display_name } | null }`. `account` is `null` for "no such account", "exists but is not currently platform-active", and "exists and is active but already has an open membership in this campaign" — all three folded into the identical result, so a caller can never distinguish which applied (the same non-disclosure discipline every `DomainAuthorizationError` in this codebase already applies). `user_id` is identity only, submitted back verbatim as §3e's `user_id` — never rendered as page text.
- **Design choice — exact match, not directory search:** `dnd_ai.queries.access_overview.find_eligible_campaign_account` resolves `login_name` to at most one account via an exact match (after the same `normalize_login_name()` every local-auth login path already applies) against `security.external_identities` (`issuer = dnd_ai.domain.access.LOCAL_AUTH_ISSUER`) — never a prefix/substring search. A search-shaped endpoint would let any `access.manage` holder enumerate accounts platform-wide by trying successive queries; `campaign.view`/`access.manage` scope one campaign's authorization, not a platform-wide user directory, and this checkpoint's own scope explicitly forbids exposing one merely to support account selection. The caller must already know the exact login name (communicated out-of-band, by whoever administers accounts) — there is no in-app directory browse.
- **Scope limitation (deliberate, not an oversight):** only resolves a **local** login. An OIDC-only account has no login name of this shape to look up by; broadening this to OIDC subjects is deferred to whichever future increment needs it.
- **401/403/404:** identical to §3's contract — `get_authenticated_user_id` rejects unauthenticated requests first; an authenticated member without `access.manage` gets 403; no active membership in the campaign at all (or the campaign not existing) gets 404, indistinguishably.
- **Pagination/filtering:** none — this is a single exact-match lookup, not a list.
- **Idempotency/audit:** none — a pure read, matching §3's own contract.

## 3e. `POST /campaigns/{campaign_id}/memberships` (hardened, 13E-B checkpoint 3)

The route and command (`create_campaign_membership`) already existed but
was reserved/unused (§2's original "reserved for a later 13E increment"
row, with no real caller besides its own tests) — this checkpoint hardens
it into the portal Access page's "Add campaign member" action: selecting
an existing, eligible account and adding it to the campaign with one
initial role, atomically. Never account creation, never an invitation,
never a reactivation of an earlier-departed membership.

- **Capability:** `access.manage`, via the identical `require_campaign_capability` dependency every other row in §2/§3 uses.
- **Request contract change (`CreateCampaignMembershipRequest`):** `{ user_id: UUID, role_id: UUID }` — `role_id` is **new and required** this checkpoint. Safe to harden without a compatibility shim: this route had no real caller before now (confirmed by repo-wide inspection), so there was no roleless-membership contract to preserve.
- **Response contract change (`CampaignMembershipResponse`):** `{ campaign_membership_id: UUID, membership_role_id: UUID }` — `membership_role_id` is new, naming the atomically-created initial role assignment. `201`, unchanged.
- **Command:** `dnd_ai.commands.memberships.add_campaign_member` (new). Every check below runs, and every row lock is taken, before any write — a rejection never leaves a partial write behind, matching `change_membership_role`'s own discipline:
  - `campaign_id` must currently be `active` (`core.lifecycle_statuses.code`) — `CampaignNotActiveError` (409). Locks `campaign.campaigns` `FOR UPDATE` first.
  - `user_id` must exist and currently be a platform-active account (`security.users.lifecycle_status_id` -> `core.lifecycle_statuses.code = 'active'`) — `AccountNotEligibleError` (404 — an ineligible account was never a legitimate target, unlike the 409 cases above). Locks the target `security.users` row `FOR UPDATE`.
  - `user_id` must also hold at least one currently unrevoked local-login identity (`security.external_identities`, `issuer = dnd_ai.domain.access.LOCAL_AUTH_ISSUER`, `revoked_at IS NULL`) — `AccountNotEligibleError` again (review correction: the command previously trusted §3d's own read-side eligibility check instead of re-deriving it, so a caller who already knew — or guessed — an active OIDC-only user's `user_id`, or one whose sole local identity had since been revoked, could add it directly, bypassing §3d's non-disclosure contract entirely). Matches §3d's own eligibility definition exactly. Locks every matching `security.external_identities` row `FOR UPDATE`, locked immediately after the `security.users` row above (this function's own consistent top-to-bottom lock order).
  - `role_id` must be a system template or scoped to `campaign_id`, and currently `is_active` — `RoleNotUsableByCampaignError` (404), identical to `assign_membership_role`'s own check. Locks the candidate role row `FOR UPDATE`.
  - A target `user_id` who already holds an *open* membership in `campaign_id` is deliberately **not** pre-checked — `ux_campaign_memberships_open` rejects that race as an ordinary 409 `IntegrityError` at insert time, matching this module's documented "database-enforced invariants this module deliberately does not duplicate" policy. This is what actually makes the add-vs-add concurrency case below correct: no pre-check to race past.
- **Re-entry creates a new row, never a reactivation:** a target whose only prior membership in this campaign is *closed* (`ended_at IS NOT NULL`) gets a **new** `security.campaign_memberships` row from this insert — `ended_at`/`ended_by_membership_id` on the earlier row are never touched. This deliberately diverges from `dnd_ai.commands.campaign_invitations._activate_or_create_membership`'s own reactivate-if-closed behavior for its different (invitation-acceptance) flow — membership reactivation is explicitly out of this checkpoint's scope.
- **Concurrency:** proven by real-connection PostgreSQL regression tests (`tests/database/test_membership_lifecycle_concurrency.py`): two concurrent adds of the same account (resolved by the unique index at insert time, not a pre-check); a concurrent campaign deactivation, candidate-role deactivation, target-account disablement, or target-identity revocation, each blocked by this command's own row locks. No application command currently revokes a local identity (no route writes `security.external_identities.revoked_at`); the identity-revocation race test exercises the raw SQL write directly, the same way the campaign-deactivation race test already does for its own lifecycle transition with no dedicated command.
- **Idempotency/audit:** the same durable `Idempotency-Key` mechanism every other row in §2/§3 uses. Two `audit.change_log` rows are written per successful call — one per table this call inserts into (`campaign_memberships`, `membership_roles`) — matching each table's own pre-existing single-row-per-insert convention rather than inventing a new "one row describes two tables" shape.
- **Cross-campaign/unknown-role rejection:** a `role_id` neither a system template nor scoped to `campaign_id` (including a nonexistent one, or one deactivated) is `RoleNotUsableByCampaignError` (404, non-disclosing), identical to §3b/§3a.
- **Actor scope:** `granted_by_membership_id` (recorded on the new role row) is always the caller's own resolved `AccessContext.campaign_membership_id` — never caller-supplied.

## 3f. `POST /campaigns/{campaign_id}/memberships/{campaign_membership_id}/end` (new, 13E-B checkpoint 3)

The portal Access page's "Remove member" action: ends an existing, open
campaign membership. Never a role change, never an account-lifecycle
action (disable/reactivate) — those remain out of scope.

- **Capability:** `access.manage`, via the identical `require_campaign_capability` dependency every other row in §2/§3 uses.
- **Request:** no body. Route path carries `campaign_id` and the target `campaign_membership_id`. Accepts an optional `Idempotency-Key` header.
- **Response (`EndCampaignMembershipResponse`):** `{ campaign_membership_id: UUID }` — the closed membership's own id, echoed back so `begin_idempotent_request`/`complete_idempotent_request` have a response to cache, the identical pattern §3c's revoke response already established. `200`, not `201`: this closes an existing row, it creates nothing.
- **Command:** `dnd_ai.commands.memberships.end_campaign_membership` (new). Locks the target membership row (`FOR UPDATE`) before evaluating anything, matching `revoke_membership_role`'s identical discipline. Raises `MembershipNotInCampaignError` (404, non-disclosing) for a nonexistent `campaign_membership_id` or one belonging to a different campaign.
- **Effect:** sets `ended_at`/`ended_by_membership_id` (the caller's own resolved membership) and moves `membership_status_id` to the `revoked` status ("Closed by a GM or owner action" — `database/seeds/security.membership_statuses.yaml`'s own words, which this always is: the route requires `access.manage` even for a self-removal). In the same transaction, every one of the membership's currently active `security.membership_roles` rows **and** (checkpoint-4 correction) every one of its currently active `security.membership_character_relationships` rows is revoked (`revoked_at` set) — never deleted, never reassigned — so a departed member is never left holding rows the read side would still describe as an active current role or character relationship. The relationship half closes a real gap: `dnd_ai.commands.campaign_invitations._activate_or_create_membership` (the invitation-acceptance flow's own reactivation path) reopens the *same* `campaign_membership_id` row in place, so a relationship left unrevoked here would have silently regained effect the moment that membership reopened, with no new grant and no new audit entry to explain why — proven by `tests/database/test_api_campaign_invitations.py::test_ending_a_membership_then_reaccepting_an_invitation_does_not_restore_its_old_character_relationship`.
- **Already-ended target (harmless no-op, mirroring §3c's revoke contract exactly):** a `campaign_membership_id` that is already ended does nothing — `EndCampaignMembershipResult.ended = False` — no second `ended_at`/`ended_by_membership_id` write, no role/relationship-row changes, no audit row. The route's audit write is conditioned on `.ended`, so even a plain retry with no key reused (or a different key) converges on one real removal and exactly one audit record — identical to §3c's own duplicate-audit-gap fix.
- **Last-manager protection:** `security.campaign_has_access_manager(campaign_id)`, scoped to *active* campaigns only, evaluated after the write via the same shared `_assert_active_campaign_retains_access_manager` helper `revoke_membership_role`/`change_membership_role` use — a plain `ValueError`, mapped to **400**, matching those two routes' identical contract for this invariant. Skipped entirely for the no-op case.
- **Self-removal:** permitted, with no special-case check anywhere in the stack — identical to every other self-mutation in this module. The only thing that can block it is the retention invariant above; a lone `access.manage` holder on an active campaign cannot remove their own membership, but a second manager can remove theirs (or the first's) freely.
- **Sibling campaigns/memberships:** untouched — only the named membership (and its own role rows) is affected.
- **Effective immediately:** the removed member disappears from the next `GET .../access-overview` (already filtered to `ended_at IS NULL`) and the next `/auth/session` bootstrap (`dnd_ai.queries.bootstrap`, same filter) — no browser-session revocation is performed or required; a still-valid session simply stops being authorized on its next request.
- **Concurrency:** proven by real-connection PostgreSQL regression tests (`tests/database/test_membership_lifecycle_concurrency.py`): two concurrent removals of the identical membership (same-row serialization, second observes the no-op); a concurrent `change_membership_role` against one of the membership's own role rows (blocked by this command's membership-row lock); two managers concurrently ending their own distinct manager-bearing memberships on the same active campaign (the combined-effect retention race, resolved by the database's own deferred trigger under barrier-coordinated real concurrency); self-removal racing a different manager's concurrent attempt to end that same membership (same-row serialization again, not a retention race, since a second manager remains either way).
- **Idempotency/audit:** the same durable `Idempotency-Key` mechanism every other row in §2/§3 uses. One `audit.change_log` row per actual removal (`table_name = 'membership_roles'`/`'membership_character_relationships'` are **not** separately recorded — `changed_fields.revoked_membership_role_ids`/`.revoked_membership_character_relationship_ids` (checkpoint-4 correction added the latter) list every role/relationship row this call revoked on the single `campaign_memberships` audit row instead, since they are all one logical removal event, not independent creates the way §3e's two inserts are).

## 3g. `assignable_characters`/`assignable_relationship_types` on `GET /campaigns/{campaign_id}/access-overview` (new fields, character-relationship-management checkpoint)

The read-contract counterpart §3h/§3i's mutations need so the portal's
"Add/change character relationship" controls never have to hardcode or
guess either assignable set — the identical role §3's own `assignable_roles`
already plays for §3a/§3b.

- `assignable_characters: [{ character_id, display_name }]` —
  `dnd_ai.queries.access_overview.list_assignable_campaign_characters`:
  every `character.characters` row (never a bare `core.entities` row of
  some other type) belonging to the campaign's own world (resolved
  server-side from the caller's pinned timeline, exactly like `grant_
  character_relationship`'s own `expected_world_id`) and currently active
  (`core.lifecycle_statuses.code = 'active'`) — the identical "never a
  legitimate target" bar §3h's own hardening now enforces. **Not** narrowed
  to player characters only: an NPC is a legitimate target too (a
  portrayer/assistant-GM relationship is meaningful for an NPC, per
  docs/architecture/DATABASE_MODEL.md §19.4's own relationship-type list).
  Campaign-level by world, not per-member — which *combinations* are
  already active for a given member is derived by the portal from that
  member's own `character_relationships` list already in this response.
- `assignable_relationship_types: [{ character_relationship_type_id, code, display_name }]`
  — `dnd_ai.queries.access_overview.list_assignable_character_relationship_types`:
  every currently `is_active` `security.character_relationship_types` row.
  Relationship types carry no campaign scope of their own (unlike roles),
  so this is not further narrowed by `campaign_id`/`world_id`.
- No pagination — matching §3's own "expected to stay small" precedent.

## 3h. `POST /campaigns/{campaign_id}/memberships/{campaign_membership_id}/character-relationships` (hardened, character-relationship-management checkpoint)

The route and command (`grant_character_relationship`) already existed
(Phase 10 workstream 21/25) — this checkpoint hardens the command to the
same "currently true" eligibility bar §3b/§3e already established for
role/membership mutations, then wires it into the portal as the Access
page's "Add character relationship" action.

- **Relationship model discovered:** `security.membership_character_relationships`
  lets one `(campaign_membership_id, character_id)` pair hold **multiple
  simultaneous active relationships of different types**
  (`ux_membership_character_relationships_active_type` only forbids two
  *active* rows for the *same* `(membership, character, type)` triple) —
  e.g. a member may simultaneously be both `viewer` and `portrayer` of the
  same character. Relationships are **temporal**, identically to roles: a
  row is never updated in place; it is revoked (`revoked_at` set) and a
  new row inserted (§3i). Relationship types are reference rows
  (`security.character_relationship_types`, a `code`/`is_active`/`sort_order`
  lookup table, not an enum) — see §3g.
- **Capability:** `access.manage`, via the identical `require_campaign_capability` dependency every other row in §2/§3 uses.
- **Request (`GrantCharacterRelationshipRequest`):** `{ character_id: UUID, relationship_type_code: string, timeline_id?: UUID, effective_from_world_time_id?: UUID, effective_to_world_time_id?: UUID }` — unchanged this checkpoint. The portal's own Add-relationship control sets only `character_id`/`relationship_type_code`; the temporal-scope fields have no UI yet (pre-existing capability, not newly exposed).
- **Response (`CharacterRelationshipResponse`):** `{ membership_character_relationship_id: UUID }`. `201`, unchanged.
- **Eligibility (hardened this checkpoint):** all checked before any write, all raising identically within each group so a caller cannot distinguish which condition applied:
  - the target `campaign_membership_id` must belong to `campaign_id` (pre-existing; `MembershipNotInCampaignError`, 404, non-disclosing);
  - the membership must be currently open (`ended_at IS NULL`) and in the `active` membership status — **new**; the membership's own user account must currently be platform-active — **new**; both raise `MembershipNotActiveError` (409) — identical to §3b's own two checks for `assign_membership_role`;
  - the target `character_id` must exist, belong to the campaign's own world, **and** currently be active (`core.lifecycle_statuses.code = 'active'`) — the world-scope half is pre-existing, the activeness half is **new**; both fold into the existing `TargetNotInCampaignWorldError` (404);
  - `relationship_type_code` must resolve to a currently `is_active` type — **new**; previously any existing code (even a deactivated one) was accepted. Raises the new `RelationshipTypeNotActiveError` (404), folding "doesn't exist" and "deactivated" identically, mirroring `RoleNotUsableByCampaignError`'s reasoning for roles;
  - a duplicate still-active `(membership, character, type)` triple is rejected as a 409 by the pre-existing `ux_membership_character_relationships_active_type` unique index (existing `IntegrityError` handler) — not pre-checked, matching this module's own "database-enforced invariants deliberately not duplicated" policy.
- **Campaign lifecycle (new, checkpoint-4 correction):** `campaign_id` itself must currently be `active` (`core.lifecycle_statuses.code`), reusing `dnd_ai.commands.memberships.CampaignNotActiveError` (409) — closes a real gap: `require_campaign_capability("access.manage")` never itself consults campaign lifecycle status, so a campaign could be deactivated after the request was authorized but before this write committed, previously letting it commit anyway. Locked `campaign.campaigns FOR UPDATE` *after* the target membership row rather than before it — locking campaign-first would create a genuine deadlock opportunity against any concurrent role mutation's own deferred `campaign.campaigns` lock (`security.assert_campaign_retains_access_manager()`); see `dnd_ai.commands.access_grants`' own module docstring for the full argument. `revoke_character_relationship` (§3j) deliberately keeps no such check — closing access must stay available even against an inactive campaign.
- **Concurrency (new):** the target membership row, then `campaign.campaigns`, then its owning user row, then the target character row, then the candidate relationship-type row are locked in that order (`FOR UPDATE OF cm` / `FOR UPDATE OF c` / `FOR UPDATE OF u` / `FOR UPDATE OF e` / `FOR UPDATE`) before any eligibility check runs — always membership-then-campaign-then-role/type, the same relative order `assign_membership_role`/`change_membership_role` already use for their own disjoint row sets, so this command can never deadlock against either. Proven by real-connection PostgreSQL regression tests (`tests/database/test_character_relationship_concurrency.py`): grant-vs-grant of the identical relationship (unique-index insertion lock, no pre-check needed), grant vs. membership-ending, grant vs. character-deactivation, grant vs. relationship-type-deactivation, grant vs. campaign-deactivation.
- **Idempotency/audit:** unchanged — the same durable `Idempotency-Key` mechanism every other create-shaped row in §2/§3 uses; one `audit.change_log` row per successful call. A request rejected for campaign inactivity rolls back its whole transaction, including any `Idempotency-Key` reservation — a retry with the same key once the campaign is active again runs the real command rather than replaying a cached rejection.
- **Fictional-time bounds (checkpoint-4 correction):** supplying **both** `effective_from_world_time_id` and `effective_to_world_time_id` records a closed historical interval that never currently grants access — see §3g's own note and `dnd_ai.domain.access.resolve_access_context`'s docstring for the full "current record" rule this reuses (this schema tracks no "current fictional now" a bounded window could be compared against, so a bounded relationship is fail-closed rather than treated as unbounded, previously the case). Supplying only `effective_from_world_time_id` (or neither) still grants normally and remains current indefinitely.
- **Sibling relationships:** untouched — this inserts exactly one new row; any other relationship (to this character or any other) the same membership independently holds is unaffected.

## 3i. `POST /campaigns/{campaign_id}/character-relationships/{membership_character_relationship_id}/change` (new, character-relationship-management checkpoint)

The character-relationship analogue of §3a's `change_membership_role`:
atomically revokes one existing, currently-active relationship assignment
and inserts a new one with a different relationship type — never a bulk
replace of every relationship a member holds.

- **Capability:** `access.manage`, via the identical `require_campaign_capability` dependency every other row in §2/§3 uses.
- **Request (`ChangeCharacterRelationshipRequest`):** `{ new_relationship_type_id: UUID }`. Route path carries `campaign_id` and the target `membership_character_relationship_id`. Unlike §3h's grant contract (which takes a `relationship_type_code` string), this takes the type by **id** — mirroring §3a's `new_role_id: UUID` shape, and matching §3g's `assignable_relationship_types` metadata, which carries both `code` and `character_relationship_type_id` so the portal can satisfy either contract without a lookup of its own.
- **Response (`CharacterRelationshipResponse`, reused from §3h):** `{ membership_character_relationship_id: UUID }` — the id of the *new* row. `201`, matching §3h's own status code for "a new row now exists," even though an existing row also changed.
- **Command:** `dnd_ai.commands.access_grants.change_character_relationship` (new). The new row carries forward the old row's own `timeline_id`/`effective_from_world_time_id`/`effective_to_world_time_id` temporal scope unchanged — only the relationship type changes. Takes a new required `expected_world_id` argument (checkpoint-4 review correction), resolved server-side by the route from the caller's own authorized campaign timeline (`timeline_world_id(connection, access.timeline_id)`) — never accepted from the request body.
- **Campaign lifecycle (new, checkpoint-4 correction):** identical to §3h's own new check — `campaign_id` must currently be `active`, checked immediately after the target row is located (before its own eligibility below), raising the same `CampaignNotActiveError` (409).
- **Active-state boundary:** the target `membership_character_relationship_id` must currently be an eligible, active assignment — not already revoked, not expired, not fictional-time-bounded and therefore closed (both `effective_from_world_time_id`/`effective_to_world_time_id` set — checkpoint-4 correction, see §3h's own fictional-time-bounds note), its owning membership not ended and in the `active` membership status, its owning user account no longer currently platform-active, or its character no longer currently active or no longer in `expected_world_id` (the last two, **checkpoint-4 review correction**: `change_character_relationship` had not been hardened to the same target-eligibility boundary §3h's `grant_character_relationship` already enforces — it locked/rechecked the relationship, membership, campaign, and replacement type, but never the membership owner's platform account or the existing character's lifecycle/world, so an access manager could durably change a relationship while its account or character was inactive, and account/character reactivation could expose the changed grant). Any of these failing raises `CharacterRelationshipNotActiveError`, mapped to **409** — identically for all of them, mirroring §3a's own `MembershipRoleNotActiveError` contract exactly (a caller cannot learn *which* condition applied), and deliberately folded into this same error rather than reusing §3h's own `MembershipNotActiveError`/`TargetNotInCampaignWorldError`: those two are shaped around a caller-*supplied* fresh target, while this command's user/character are the *existing* relationship's own already-fixed attributes. The candidate `new_relationship_type_id` is held to the same bar as §3h's own type check: nonexistent or deactivated raises `RelationshipTypeNotActiveError` (**404**) — never a legitimate target in the first place, unlike the 409 cases above.
- **Same-type no-op:** if `new_relationship_type_id` names the type `membership_character_relationship_id` already, currently holds, the request is rejected as `ChangeCharacterRelationshipNoOpError`, mapped to **422**, checked before any write — identical to §3a's own `ChangeMembershipRoleNoOpError` contract, including the "never durably cached as a successful idempotent-replay result" reasoning.
- **Duplicate-result rejection:** a retry naming a `new_relationship_type_id` the same `(membership, character)` pair already holds actively (from some *other* assignment) is rejected as a 409 by the pre-existing `ux_membership_character_relationships_active_type` unique index — not pre-checked, matching §3h's own policy.
- **Concurrency:** the target row and its owning membership are locked together (`FOR UPDATE OF mcr, cm`), then `campaign.campaigns` (`FOR UPDATE OF c`, checkpoint-4 correction), then, separately, the membership's owning user row and the relationship's own character row (`FOR UPDATE OF u`/`FOR UPDATE OF e`, checkpoint-4 review correction), before evaluating the target's own eligibility, and the candidate new relationship-type row is separately locked (`FOR UPDATE`) before its own check — relationship/membership, campaign, owning user, character, candidate type: the identical order §3h's `grant_character_relationship` uses for its own disjoint checks, so this command can never deadlock against it (see §3h's own note on why campaign is locked after the target row, not before — the user/character locks follow the same reasoning). A concurrent change/revoke of the identical row is serialized the same way (same-row coverage) — the loser observes the winner's committed effect (already-revoked/superseded) once unblocked, raising `CharacterRelationshipNotActiveError` rather than an interleaved write. Proven by real-connection PostgreSQL regression tests (`tests/database/test_character_relationship_concurrency.py`): change vs. relationship-type-deactivation, change vs. campaign-deactivation, change vs. account-disablement, change vs. character-deactivation, change-vs-revoke same-row, change-vs-change same-row.
- **Revoke stays unchecked (deliberate, unchanged):** `revoke_character_relationship` (§3j) checks none of the four conditions above — account, character, membership, or campaign lifecycle — closing access must remain possible for cleanup regardless of any of them.
- **No retention invariant:** unlike §3a's `change_membership_role`, this checkpoint adds no campaign `access.manage`-retention check — a character relationship never carries `access.manage` (character-scoped capabilities and the campaign-wide `access.manage` capability are disjoint concerns, per `dnd_ai.commands.access_grants`' own module docstring).
- **Idempotency:** the same durable `Idempotency-Key` mechanism §3a uses — one opaque key per logical `(membership_character_relationship_id, new_relationship_type_id)` edit, reused verbatim across a retry of that exact selection, regenerated the moment the selection changes, cleared on confirmed success. See `portal/src/hooks/useChangeCharacterRelationship.ts`.
- **Audit:** one `audit.change_log` row (`change_action_code = 'updated'`, `table_name = 'membership_character_relationships'`, `record_id` = the new row's id), atomic with the state change, recording `previous_status`/`new_status` (the old/new relationship-type **codes**) and `changed_fields = { "previous_membership_character_relationship_id": "<uuid>" }` — the identical shape §3a's own audit row uses.
- **Self-change:** permitted, with no special-case check — there is no retention invariant to protect.
- **Effective immediately:** the change is visible on the next `GET .../access-overview` request and the next `/auth/session` bootstrap.

## 3j. `POST /campaigns/{campaign_id}/character-relationships/{membership_character_relationship_id}/revoke` (hardened, character-relationship-management checkpoint)

The route and command (`revoke_character_relationship`) already existed —
this checkpoint closes the identical duplicate-audit gap §3c already
closed for `revoke_membership_role_endpoint`, then wires it into the
portal as the Access page's "Revoke relationship" action.

- **Capability:** `access.manage`, via the identical `require_campaign_capability` dependency every other row in §2/§3 uses.
- **Request:** no body. Route path carries `campaign_id` and the target `membership_character_relationship_id`. Accepts an optional `Idempotency-Key` header — **new this checkpoint**.
- **Response contract change:** previously a bodyless `204 No Content`; now `200`/`CharacterRelationshipResponse` (`{ membership_character_relationship_id: UUID }`, reusing §3h's own grant response shape) — needed so `begin_idempotent_request`/`complete_idempotent_request` have a response to cache. Identical reasoning to §3c's own response-contract change for `revoke_membership_role_endpoint`.
- **Active-state/eligibility:** `revoke_character_relationship` does **not** require the target to currently be an eligible/active assignment the way `change_character_relationship` requires of its own target — an already-revoked row is a documented, harmless no-op (`RevokeCharacterRelationshipResult.revoked = False`), proven by `tests/database/test_character_relationship_concurrency.py::test_two_concurrent_revokes_of_the_same_relationship_serialize`. A nonexistent `membership_character_relationship_id`, or one belonging to a different campaign, is still rejected identically as `MembershipNotInCampaignError` (404, non-disclosing).
- **Campaign lifecycle: deliberately not checked (checkpoint-4 correction confirmed this, did not change it):** unlike §3h/§3i's grant/change, `revoke_character_relationship` never requires `campaign_id` to be `active` — revoking access must remain available for cleanup even against an inactive campaign, proven by `tests/database/test_api_access_grants.py::test_revoking_a_relationship_on_an_inactive_campaign_still_succeeds`.
- **Idempotency/audit (hardened this checkpoint):** the pre-hardening route wrote one `audit.change_log` row on *every* call, including a plain retry against an already-revoked row — the identical duplicate-audit gap §3c closed for role revocation. Fixed the same two ways: (1) an `Idempotency-Key` replay returns the cached response verbatim without re-running the command; (2) independent of any key, the route's audit write is now conditioned on `RevokeCharacterRelationshipResult.revoked` — `False` writes no audit row at all.
- **No retention invariant:** unchanged — a character relationship never carries `access.manage`, so there is nothing for this route to protect (see §3i).
- **Self-revocation:** permitted, with no special-case check — the server decides authorization; the portal never locally grants or withholds the control based on whether the target is the caller's own relationship.
- **Concurrency:** the pre-existing `FOR UPDATE OF mcr` lock on the target row serializes same-row races; this checkpoint adds regression coverage for revoke-vs-revoke and change-vs-revoke same-row cases (`tests/database/test_character_relationship_concurrency.py`). Revoke racing the owning membership's own ending is **not** a race this function needs to resolve — `revoke_character_relationship` never re-checks membership eligibility at all (documented in that function's own docstring), so a concurrent write to a different `security.campaign_memberships` row cannot affect its `FOR UPDATE OF mcr` lock.
- **Sibling relationships:** untouched — only the named row is revoked.
- **Immediate authorization effect:** revocation removes the character from the target user's next `GET /auth/session` bootstrap (`dnd_ai.queries.bootstrap.get_session_bootstrap` re-resolves `AccessContext.character_capabilities` fresh on every call — no caching layer) and, if the revoked relationship was the sole source of a `selected_character_id` default, that field becomes `null` on the next bootstrap rather than continuing to name a no-longer-authorized character. Already covered by the pre-existing, unmodified `tests/database/test_query_bootstrap.py::test_relationship_revocation_is_reflected_on_the_next_call`/`test_character_relationship_with_capability_is_a_selectable_perspective`/`test_multiple_perspectives_leave_selected_character_null` — this checkpoint changes no bootstrap-query code, so no new bootstrap-level test was needed; the existing suite already proves the same-request re-resolution behavior this route's own hardening depends on. A route request made using the revoked perspective (e.g. a character-scoped read) fails with that route's own established non-disclosing response on its *next* request — no browser-session revocation is performed or required.

## 3k. `POST /campaigns/{campaign_id}/resource-grants` / `.../resource-grants/{id}/revoke` (hardened, checkpoint 5, corrected)

The direct-resource-grant management checkpoint: the `security.
resource_grants` schema, resolver (`dnd_ai.domain.access.
resolve_access_context`), read-overview join, commands
(`create_resource_grant`/`revoke_resource_grant`), and API routes all
already existed (Phase 10) — this checkpoint hardens the commands to the
same "currently true" eligibility bar §3h/§3b already established, adds a
server-authoritative delegation policy (nothing this codebase had before),
closes the identical membership-ending silent-reactivation gap checkpoint
4 closed for character relationships (extended by a post-delivery
correction — see the membership-ending-integration bullet below — to also
close a member's access-group links, not just their own direct grants), and
wires the portal's own
"Direct resource access" section to it — scoped to **character targets
only** this checkpoint.

- **Grant model discovered:** `security.resource_grants` attaches to
  either a campaign membership or an access group (`grantee_campaign_
  membership_id`/`grantee_access_group_id`, exactly one), and targets
  exactly one of six kinds (`character_id`, `entity_id`, `knowledge_
  item_id`, `quest_id`, `session_id`, `event_id`) with one capability and
  an `effect` (`allow`/`deny`). `ux_resource_grants_active` forbids two
  *active* rows for the identical `(grantee, target, timeline_id,
  capability_id, effect)` tuple — otherwise multiple simultaneous grants
  to the same target are permitted (e.g. an `allow` and a narrower `deny`
  at the same time). No `resource_type` reference table exists (docs/
  architecture/DATABASE_MODEL.md §19.6 deliberately rejects a universal
  ACL framework); target validity is enforced by real per-kind foreign
  keys instead.
- **Capability:** `access.manage`, via the identical `require_campaign_capability` dependency every other row in §2/§3 uses.
- **Delegation policy (new this checkpoint — no prior rule existed):**
  `dnd_ai.domain.access.RESOURCE_GRANT_CAPABILITY_CATALOG` is a fixed,
  server-authoritative table of which `security.capabilities.code` values
  are ever a legitimate pairing with which of the six target kinds,
  derived from this codebase's own actual `has_capability(...)`/
  `resource_grant_targets()` call sites (not guessed): every `character.*`
  code is valid only for a `character_id` target (mirroring `security.
  character_relationship_type_capabilities`' own identical scoping of
  those same codes to character relationships); `campaign.view`/
  `canon.edit` are valid for the other five target kinds (the only two
  capabilities any reader in this codebase ever checks against them).
  `access.manage`, `import.approve`, and `rules_source.manage` are
  excluded from every target kind entirely — each is checked only via
  `require_campaign_capability`, which never passes a resource-target
  keyword, so a resource-scoped grant of one would be silently inert
  against every real call site, and this codebase's authorization model
  has no documented notion of *resource-scoped* platform/campaign
  administration regardless. `character.discover` (checkpoint-5
  correction) is also excluded from the `character_id` list even though it
  is otherwise a `character.*` code: its own baseline reader passes no
  resource target at all, and the one call site that *does* pass a
  `character_id` can only confirm a grant that already exists — no reader
  anywhere in this codebase resolves "should a resource grant of
  `character.discover` make character X newly discoverable" from a bare
  `(membership, capability)` pair the way the other eight `character.*`
  codes do for their own gated actions; see `RESOURCE_GRANT_CAPABILITY_
  CATALOG`'s own docstring for the full account. `access.manage`
  authorizes assignment from this entire fixed catalog regardless of which
  capabilities the granting membership itself currently holds — the
  identical precedent `assign_membership_role`/`grant_character_
  relationship` already established for roles and relationship types (an
  access manager need not personally hold a capability to delegate it).
- **Request (`CreateResourceGrantRequest`):** `{ capability_code, effect, grantee_campaign_membership_id?, grantee_access_group_id?, character_id?, entity_id?, knowledge_item_id?, quest_id?, session_id?, event_id?, reason? }` — unchanged shape (all six target kinds and both grantee kinds remain backend-supported); the portal's own Add-grant control only ever sends `grantee_campaign_membership_id`, `character_id`, and `capability_code` (`effect` always `"allow"` — see the portal-scope note below).
- **Response (`ResourceGrantResponse`):** `{ resource_grant_id: UUID }`. `201`, unchanged.
- **Eligibility (hardened this checkpoint):** all checked before any write, all raising identically within each group so a caller cannot distinguish which condition applied:
  - a `grantee_campaign_membership_id` grantee must belong to `campaign_id` (pre-existing; `MembershipNotInCampaignError`, 404, non-disclosing); must be currently open and in the `active` membership status, and its owning user account must currently be platform-active — both **new**, folded into `MembershipNotActiveError` (409), the identical bar §3h's own `grant_character_relationship` hardening established. Not applicable to a `grantee_access_group_id` grantee, which carries no lifecycle of its own (`security.access_groups` has no `is_active`/status column) — access-group-targeted grants are otherwise unchanged and remain out of this checkpoint's own portal scope (see below).
  - `campaign_id` itself must currently be `active` — **new**, `CampaignNotActiveError` (409), the identical gap-closing check checkpoint 4 added for character relationships.
  - whichever of the six target kinds is supplied must exist, belong to the campaign's own world/campaign scope (pre-existing), **and** currently be active — the activeness half is **new**, folded into the existing `TargetNotInCampaignWorldError`/`SessionNotInCampaignError` (404): a character/entity/knowledge-item/quest/event target's `core.lifecycle_statuses.code` must be `'active'` (all five are `core.entities` rows via class-table inheritance), and a session target's own `campaign.sessions.lifecycle_status_id` must be `'active'` (the one target kind without a `core.entities` row of its own).
  - `capability_code` must be currently active **and** a valid pairing for the supplied target kind under `RESOURCE_GRANT_CAPABILITY_CATALOG` — both **new**, folded into the new `ResourceGrantCapabilityNotGrantableError` (404): a nonexistent code, a deactivated one, and an incompatible pairing (e.g. `character.control` against a `quest_id`) are all indistinguishable to the caller.
  - a duplicate still-active `(grantee, target, timeline_id, capability, effect)` combination is rejected as a 409 by the pre-existing `ux_resource_grants_active` unique index (existing `IntegrityError` handler) — not pre-checked, matching this module's own "database-enforced invariants deliberately not duplicated" policy.
- **Concurrency (new):** the grantee (membership row, or nothing further for an access-group grantee), then `campaign.campaigns`, then, separately, the membership grantee's owning user row, then the target resource row, then the candidate capability row are locked in that order (`FOR UPDATE OF cm` / `FOR UPDATE OF c` / `FOR UPDATE OF u` / `FOR UPDATE OF e`-or-`s` / `FOR UPDATE`) before any eligibility check runs — grantee, then campaign, then owning user, then target, then capability: the identical relative order §3h's `grant_character_relationship` uses for its own disjoint checks, so this command can never deadlock against it. Proven by real-connection PostgreSQL regression tests (`tests/database/test_resource_grant_concurrency.py`): create-vs-create of the identical grant (unique-index insertion lock), create vs. membership-ending, create vs. account-disablement, create vs. campaign-deactivation, create vs. target-deactivation (both the entity-rooted and the session code path), create vs. capability-deactivation, and two-concurrent-revokes-serialize.
- **Idempotency:** unchanged for create — the same durable `Idempotency-Key` mechanism every other create-shaped row in §2/§3 uses. A request rejected for any of the eligibility conditions above rolls back its whole transaction, including any `Idempotency-Key` reservation — a retry with the same key once the condition clears runs the real command rather than replaying a cached rejection.
- **Audit content (hardened this checkpoint, correction):** one `audit.change_log` row per successful create, and per actual revocation, exactly as before — but both now carry a bounded, non-free-form `changed_fields` payload (`grantee_campaign_membership_id`/`grantee_access_group_id` — exactly one non-null, `target_kind`/`target_id`, `capability_code`, `effect`) instead of none at all. `create_resource_grant_endpoint` reads these from the already-validated request body; `revoke_resource_grant_endpoint` reads them from `RevokeResourceGrantResult`'s own new fields, populated server-side by `revoke_resource_grant()` from the locked grant row itself — never re-derived from caller input, since a revoke request only ever supplies `resource_grant_id`. `reason` (free-form caller text) is never recorded, matching `dnd_ai.api.local_auth`'s "Never store" list.
- **Revoke stays unchecked (deliberate, unchanged):** `revoke_resource_grant` checks none of the eligibility conditions above (account, character/target, membership, campaign) — closing access must remain possible for cleanup regardless, matching §3j's identical policy for `revoke_character_relationship`.
- **Revoke response contract change (hardened this checkpoint):** previously a bodyless `204 No Content` with no `Idempotency-Key` support and an unconditional audit write on every call (including a plain retry against an already-revoked row); now `200`/`ResourceGrantResponse` (`{ resource_grant_id: UUID }`), an optional `Idempotency-Key`, and the audit write conditioned on `RevokeResourceGrantResult.revoked` — the identical duplicate-audit-gap fix §3c/§3j already made for role/relationship revocation.
- **No change endpoint:** unlike a character relationship's single-dimension type change, a resource grant's meaningful fields (target, capability, effect, temporal/timeline scope) could each independently change, with no single unambiguous "this is what changed" audit story — revoking the old grant and creating a new one (both already hardened, audited, and idempotent) is the deliberate replacement for a generic edit form; see `dnd_ai.commands.access_grants`' own module docstring.
- **Membership-ending integration (checkpoint 5, extended by correction):** `end_campaign_membership` revokes every currently active `security.resource_grants` row whose `grantee_campaign_membership_id` is the ending membership, in the same transaction that closes it — the identical silent-reactivation gap checkpoint 4 closed for character relationships. It also now closes (`removed_at = now()`, never deletes) the ending membership's own currently open `security.access_group_memberships` rows — the *membership's link* to each access group it belonged to — so a group's own resource grants stop applying to a departed member too, without touching the group's grant row or any other member's link to it. This closes a real gap the first cut of this checkpoint missed: `resolve_access_context`'s group-membership subquery only ever considers a currently open `access_group_memberships` row, and `_activate_or_create_membership` reactivates the *same* `campaign_membership_id` row in place on a later invitation acceptance — without this correction, a departed member's stale group membership (and every grant made to that group) would silently regain effect the moment they rejoined. Covered by `tests/database/test_api_membership_lifecycle.py::test_ending_a_membership_also_revokes_its_resource_grants`/`::test_ending_a_membership_also_closes_its_access_group_memberships` and `tests/database/test_api_campaign_invitations.py::test_ending_a_membership_then_reaccepting_an_invitation_does_not_restore_its_old_character_relationship` (extended checkpoint 5 to also cover the resource-grant half through a real reactivation) and the new `::test_ending_a_membership_then_reaccepting_an_invitation_does_not_restore_its_old_access_group_membership` (checkpoint-5 correction — the full access-group scenario: initial effect, closure on end, non-reactivation on a reopened membership, and restoration only via an explicit new `access_group_memberships` insert).
- **Read-side parity (checkpoint 5):** `dnd_ai.domain.access.resolve_access_context` and `get_campaign_access_overview` both now exclude a resource grant whose own target is not currently active — the same "currently true" generalization applied to the mutation side above, so a target deactivated *after* a grant was created stops being authorization-effective (and stops appearing on the overview) on the very next request, not just at creation time.
- **Portal scope this checkpoint (deliberate, not full coverage):** the portal's "Add direct resource access" control only offers **character** as a selectable resource type — the one target kind with an existing safe display-name/search contract (`dnd_ai.queries.access_overview.list_assignable_campaign_characters`, already built for §3g). The other five target kinds (`entity`, `knowledge_item`, `quest`, `session`, `event`) have no safe, campaign-scoped display/search contract of their own yet (resolving one for each is a materially larger surface — five unrelated resource kinds — than this checkpoint's own scope), so they are omitted from the portal rather than presented with a raw id; a grant to any of them remains fully supported by the backend (all six target kinds are hardened identically) and, if one already exists (created directly, or by a future increment), still appears on the overview with its `target_type` label and no display name, exactly as before. Access-group-targeted grants are likewise omitted from the portal this checkpoint — "Do not implement access-group grants" was this checkpoint's own explicit instruction; the backend continues to support them unchanged. `grantable_resource_capabilities` (§3) is shaped generally (one row per valid `(capability, target_type)` pairing) specifically so a future checkpoint that adds a safe contract for another target kind needs no change to that endpoint, only a portal change.
- **Server delegation policy answers this checkpoint's own open question:** an access manager may delegate any capability in the fixed catalog for the target's kind, **not** only capabilities they personally currently hold — see the delegation-policy bullet above for the precedent this follows and the reasoning.

## 3l. `POST /campaigns/{campaign_id}/access-groups` and friends (new, checkpoint 6)

**Discovered model** (`security.access_groups`/`.access_group_memberships`, revision 080; `lifecycle_status_id` added by revision 105): a group is campaign-scoped (`campaign_id`, `ON DELETE CASCADE`), named uniquely within its campaign (`ux_access_groups_campaign_name`, case-sensitive plain-text comparison — a deliberate choice, not an oversight, matching this table's own established convention with no `citext`/`lower()` normalization anywhere in schema), 1-200 characters (`ck_access_groups_name_length`); with an optional `description`, 1-2000 characters when present (`ck_access_groups_description_length`, migration 106 — a checkpoint-6 correction; a blank value normalizes to `NULL` before storage, never an empty string); and, since revision 105, `lifecycle_status_id` (`core.lifecycle_statuses` — the same shared lookup `campaign.campaigns`/`.sessions`/`.timelines`/`core.entities`/`security.users` all already use; only `active`/`archived` are ever written by this checkpoint's own commands, though the FK does not itself forbid the lookup's other codes). Membership (`access_group_memberships`) links a group to a `campaign_membership_id` — never a bare `user_id` — with `removed_at` closing the row rather than deleting it (`ux_access_group_memberships_open`, a partial unique index, prevents a duplicate open link). One campaign membership may belong to multiple groups simultaneously; groups do not nest (no `parent_access_group_id` or similar exists, and none is added). Hard deletion of either table is never performed by any command.

**Routes** (`dnd_ai.api.access_groups` over `dnd_ai.commands.access_groups`, all gated `access.manage`):

| Method & path | Command | Status | Notes |
|---|---|---|---|
| `POST /campaigns/{campaign_id}/access-groups` | `create_access_group` | 201 | `{name, description?}`. Requires the campaign currently active. Blank/whitespace-only name rejected (422, `BlankAccessGroupNameError`) before any write; an over-length name (>200, `ck_access_groups_name_length`) or description (>2000, `ck_access_groups_description_length`, migration 106) rejected (422 — `Field(max_length=...)` at the API layer, `AccessGroupNameTooLongError`/`AccessGroupDescriptionTooLongError` at the command layer, matching bounds all the way down); a duplicate name is left to `ux_access_groups_campaign_name`'s own 409. |
| `POST /campaigns/{campaign_id}/access-groups/{access_group_id}/update` | `update_access_group` | 200 | `{name, description?}`. Requires an active group in this campaign (`AccessGroupNotInCampaignError`/`AccessGroupNotActiveError`). Rejects an unchanged request (422, `AccessGroupUpdateNoOpError`), a blank name, and an over-length name/description (checkpoint-6 correction, identical bounds to create), before any write. No generic patch — only `name`/`description` are ever accepted. |
| `POST /campaigns/{campaign_id}/access-groups/{access_group_id}/deactivate` | `deactivate_access_group` | 200 | No body. Archives the group; closes every open membership and revokes every active resource grant it owns, in the same transaction — unbounded, regardless of how many. Already-archived is a harmless no-op (no second audit row). `changed_fields` (checkpoint-6 correction) bounds each dependent list to an exact `count`, a `sample_ids` prefix capped at 20, and a `sample_truncated` flag — never the full, unbounded id list the first cut of this checkpoint wrote. |
| `POST /campaigns/{campaign_id}/access-groups/{access_group_id}/reactivate` | `reactivate_access_group` | 200 | No body. Flips the group back to active only — never reopens a membership or un-revokes a grant deactivation already closed. Requires the campaign currently active (a widening action). Already-active is a harmless no-op. |
| `POST /campaigns/{campaign_id}/access-groups/{access_group_id}/members` | `add_access_group_member` | 201 | `{campaign_membership_id}` — the authoritative campaign-membership id, never a bare `user_id`. Requires an active group, an open/active/platform-active target membership, and an active campaign — all before any write. A duplicate open link is left to `ux_access_group_memberships_open`'s own 409. |
| `POST /campaigns/{campaign_id}/access-group-memberships/{access_group_membership_id}/remove` | `remove_access_group_member` | 200 | No body. Closes the link (`removed_at`), never deletes it. Checks nothing beyond campaign scope — closing access must remain possible for cleanup, matching every other revoke/end/remove command in this document. Self-removal permitted (no per-campaign retention invariant applies to a group link). Already-removed is a harmless no-op. |

Group-owned resource grants use the **existing** §3k routes unchanged — `POST /campaigns/{campaign_id}/resource-grants` / `.../resource-grants/{id}/revoke` already accept `grantee_access_group_id`. The one change: `create_resource_grant`'s group-grantee branch now also locks the group row (`FOR UPDATE OF ag`) and requires it currently be active (`AccessGroupNotActiveError`, 409) — before revision 105 a group carried no lifecycle to check. The portal exposes only the same character-target `allow`-grant workflow already built for §3k's member-target grants; it does not add create controls for a `deny` effect or any of the other five target kinds for a group grantee either, matching §3k's own portal-scope limitation. An existing backend-created `deny` grant on a group remains visible/revocable with the same effect-aware "Remove denial" wording §3k's correction already established.

**Read contract:** `GET /campaigns/{campaign_id}/access-overview` gains `access_groups: AccessGroupSummaryResponse[]` (`dnd_ai.queries.access_overview.list_campaign_access_groups`) — every group in the campaign, **both** `active` and `archived` (so the portal can offer "Reactivate"), each with its currently open members (`access_group_membership_id`, `campaign_membership_id`, `display_name`, `added_at`) and currently active, group-owned resource grants (the identical shape §3k's own per-member `grants[]` already uses — `target_type`/`target_id`/`target_display_name`, the last populated only for a `character_id` target). No separate "eligible members" endpoint exists: the portal's group-add control reuses the overview's own top-level `members` list, filtering to `status_code == "active"` **and** `account_is_active` (checkpoint-6 correction — see §3's own note on that field) client-side — the server still authoritatively re-validates eligibility at mutation time regardless, the same "read side only narrows offered choices, never the authorization boundary" pattern §3d's `find_eligible_campaign_account` already established for a different control.

**Concurrency:** group create/rename/deactivate/reactivate lock their own group row first (`dependent-row-then-campaign-row`, this document's established order); `add_access_group_member` locks group, then membership, then campaign, then the membership's owning user; `create_resource_grant`'s group-grantee branch locks the group row before `campaign.campaigns`, matching `reactivate_access_group`'s own relative order rather than inverting it. Proven by `tests/database/test_access_group_concurrency.py`: duplicate-name create/rename races, add-member vs. group-deactivation/membership-ending/account-disablement, two-concurrent-additions, two-concurrent-removals-serialize, group-grant-create vs. group-deactivation, group-deactivation vs. grant-revocation, and two-concurrent-deactivations/reactivations-serialize.

**Idempotency:** every mutating route accepts an `Idempotency-Key` via the same durable `security.idempotent_requests` mechanism every other route in this document uses.

**Audit:** one `audit.change_log` row per actual state change (`create_access_group`/`update_access_group`/`deactivate_access_group`/`reactivate_access_group`/`add_access_group_member`/`remove_access_group_member`, `table_name` `access_groups`/`access_group_memberships`), the latter four conditioned on the underlying command's own no-op result exactly like every other revoke/end/remove route in this document. `create_access_group`/`update_access_group` record the command's own normalized `description` (trimmed, blank-to-`NULL`) in `changed_fields`, never the raw request body value (checkpoint-6 correction). `update_access_group`'s row records the group's previous/new name in `previous_status`/`new_status` (reusing those generic columns, matching `change_membership_role`'s own precedent for a different kind of "old → new" change) so `GET /campaigns/{campaign_id}/audit-history` can show a rename summary. `deactivate_access_group`'s row bounds each dependent id list in `changed_fields` (checkpoint-6 correction — see the routes table above) rather than writing every removed-membership/revoked-grant id verbatim. Audit-history gains two new categories, `access_group` (the four lifecycle commands, target = the group) and `access_group_membership` (the two membership commands, target = the added/removed account, `change_summary` = the group's name) — see `docs/AUDIT_HISTORY_API.md` §2 for the full label-resolution contract, including how both reuse the identical `grantee_access_group_id`/`grantee_group_name` and `target_user_id`/`target_user_display_name` resolution the `resource_grant`/`membership` categories already established, rather than adding new columns.

## 4. Principal/boundary summary

- **Local-session/OIDC-human:** `dnd_ai.api.auth.require_human_user_id` accepts only `LOCAL_SESSION_AUTH_METHOD` and `OIDC_AUTH_METHOD`. Every campaign-scoped access-management route (§2's campaign-scoped rows, plus the new overview read) is reachable by either.
- **Platform-administrator:** `/admin/accounts*` (`dnd_ai.api.local_auth`) — gated on `security.users.is_platform_administrator`, checked *inside* the command (a non-platform-administrator caller gets a fixed, non-disclosing 404, not 403). Entirely separate from any campaign's `access.manage` — a campaign owner is not automatically a platform administrator, and vice versa.
- **Campaign-scoped:** every `access.manage`-gated route in §2, plus the new overview read — authorization is per-campaign, resolved fresh per request via `dnd_ai.domain.access.resolve_access_context`.
- **Self-service:** routes that act only on the caller's own account/own invitation with no special capability (`/auth/login`, `/auth/logout`, `/auth/change-password`, `/auth/sessions` list/delete-own, `/auth/activate`, `/auth/password-reset`, `POST /campaign-invitations/accept`).
- **Foundry/machine boundary:** a `FOUNDRY_ACCESS_AUTH_METHOD`-authenticated principal may reach a campaign-scoped route only when that route explicitly opts in via `require_campaign_capability(..., allow_foundry_access=True, foundry_scope=...)`. **None** of the access-management routes in §2, §3l's access-group routes, nor the access-overview read, opt in — a paired Foundry device or its adapter credential cannot list, create, or revoke any membership, role, relationship, grant, or access group, and cannot read the overview either. The retired `FOUNDRY_SYSTEM_AUTH_METHOD` cannot reach any authenticated route at all (rejected earlier, in `get_authenticated_user_id` itself).
- **`POST /campaigns` (its own category):** callable by any human principal, but real authorization is inside `dnd_ai.commands.campaigns.create_campaign` (pre-existing `access.manage` in another campaign attached to the same timeline, plus a positively issued `security.timeline_bootstrap_grants` row) — not a generic "any authenticated human may create any campaign" self-service contract.

## 5. Missing contracts deferred to a later Phase 13E increment

No backend read/write contract exists yet for:

- Listing pending/outstanding `security.campaign_invitations` for a campaign.
- ~~Access-group management~~ — **delivered by checkpoint 6, §3l**: create/rename/deactivate/reactivate a group, add/remove a member. Group-owned resource grants continue through the existing §3k routes unchanged in shape (hardened to require the grantee group currently be active).
- ~~Any audit-history read endpoint~~ — **delivered independently of this checkpoint sequence**: `GET /campaigns/{campaign_id}/audit-history` (`dnd_ai.api.audit_history`/`.queries.audit_history`; see `docs/AUDIT_HISTORY_API.md` for the full contract). Checkpoint 6 extends its category allowlist with `access_group`/`access_group_membership` (§3l).
- A preview-as-user/perspective workflow (docs/UI_DESIGN.md §6.3) — no existing endpoint.
- A UI for the remaining mutation endpoints in §2: invitation issuance, account creation/activation/reset/disable/reactivate/revoke-sessions, membership reactivation, and access-group-targeted resource grants of a non-character target kind (see §3k's own "Portal scope this checkpoint" note). **Changing an existing member's role assignment (§3a, checkpoint 1), adding/revoking one role on an existing membership (§3b/§3c, checkpoint 2), adding an existing account as a member/ending an existing membership (§3d/§3e/§3f, checkpoint 3), adding/changing/revoking a member's character relationship (§3g/§3h/§3i/§3j, the character-relationship-management checkpoint), adding/revoking a member's character-targeted direct resource grant (§3k, checkpoint 5), and the complete access-group lifecycle/membership/character-target-grant management (§3l, checkpoint 6) are now wired** — the exceptions to this list.
- A UI for the other five resource-grant target kinds (`entity`, `knowledge_item`, `quest`, `session`, `event`) and for a resource-grant `deny` effect — see §3k's own "Portal scope this checkpoint" note for why (no safe display/search contract yet for the five target kinds; no portal need yet for an explicit deny). The backend command itself is hardened identically for all six target kinds and both effects, for both grantee kinds.

None of the above is implemented yet, except as noted. 13E-A was read-only; 13E-B checkpoints 1, 2, 3, the character-relationship-management checkpoint, checkpoint 5, and checkpoint 6 together add exactly the sixteen mutations in §3a/§3b/§3c/§3e/§3f/§3h/§3i/§3j/§3k/§3l (plus the §3d/§3g read contracts, the §3k grantable-capabilities/target-identity read additions, and the §3l access-groups read addition) and nothing else in this list — no invitation, non-character access-group grant, preview-as-user, Foundry, or AI mutation; no account creation, activation, disablement, or reactivation; no membership reactivation.

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

### 13E-B checkpoint 2 manual-validation scenarios

One dev-data addition was needed for this checkpoint (see "Seeded accounts"
above, Player B): a second `campaign_owner` role on `phase13e.player_b` in
Campaign B, making Player B a second `access.manage` holder there alongside
the pre-existing `--user-id` account's own membership — deliberately placed
in Campaign B, not Campaign A, so it never disturbs `phase13e.gm2`'s own
role as Campaign A's sole manager (the checkpoint-1 last-manager scenario
above still depends on that).

- **Add a role:** log in as `phase13e.gm2`, open Campaign A's Access page,
  choose "Add role" on `phase13e.observer_a` (currently `observer` only),
  select `player` from the server-supplied list (which must already
  exclude `observer`), Save. The overview refreshes to show both `observer`
  and `player` on Observer A; nothing else on the row changes.
- **Add-role choices exclude held roles:** the same control on
  `phase13e.player_b` (Campaign B; holds `player` and `campaign_owner`)
  must never offer either of those two — only the remaining system-template
  roles (`gm`, `assistant_gm`, `observer`, `import_reviewer`,
  `rules_curator`).
- **Revoke a role:** as `phase13e.gm2`, revoke `phase13e.player_a`'s
  `player` role. Confirmation names both the member and the role. After
  confirming, the overview refreshes and Player A holds no roles;
  `player_a`'s unrelated character relationship is unaffected. (This
  leaves Player A a member with no role — a valid, if unusual, state this
  checkpoint's own scope does not additionally restrict; deliberately not
  reversed by this scenario since the dev fixture is recreated fresh by a
  clean seed run.)
- **Safe self-revocation with a second manager:** log in as
  `phase13e.player_b` (Campaign B), open the Access page, revoke your own
  `campaign_owner` role. Succeeds (200) — the `--user-id` account's own
  Campaign B membership remains a manager, so the campaign never loses its
  last one. Player B keeps its `player` role and its Access-nav item
  disappears on the next request (no more `access.manage`).
- **Last-manager rejection (revoke):** still as `phase13e.gm2` in Campaign
  A — the sole `access.manage` holder there, unchanged by this checkpoint's
  dev-data addition — attempt to revoke `gm2`'s own `campaign_owner` role.
  Rejected (400); `gm2` keeps the role and the Access nav item remains
  visible on the next request. Mirrors the checkpoint-1 last-manager
  scenario for change, now exercised for a bare revoke.
- **Disabled-account rejection (add role):** the seeded `phase13e.disabled`
  account (Campaign A, `player` role, platform-disabled) cannot be given an
  additional role: a direct `POST .../memberships/{disabled_membership_id}/roles`
  as `phase13e.gm2` returns 409 — no seed change needed, this fixture
  already existed for the read-side scenario in §3.
- **Cross-campaign isolation:** as `phase13e.gm2` (Campaign A only), a
  direct `POST /campaigns/<campaign_a_id>/memberships/<a Campaign-B
  membership id>/roles` (add), or `.../roles/<a Campaign-B membership_role_
  id>/revoke` (revoke), both return 404 — the same non-disclosing contract
  §3b/§3c document.
- **Idempotent replay (add):** repeating the same add-role request with the
  same `Idempotency-Key` returns the original response unchanged, without
  creating a second role row.
- **Idempotent replay (revoke):** repeating the same revoke request with
  the same `Idempotency-Key` returns the original response unchanged,
  writing no second `audit.change_log` row — the portal generates and
  reuses this header automatically, exactly like the existing change-role
  control.

### 13E-B checkpoint 3 manual-validation scenarios

No seed change was needed for this checkpoint — `phase13e.player_b`
(Campaign B only, no membership in Campaign A) already provides an
existing, eligible, cross-campaign account to add; the other four seeded
accounts already exercise the removal side.

- **Add an existing account:** log in as `phase13e.gm2`, open Campaign A's
  Access page, choose "Add campaign member", enter the login name
  `phase13e.player_b`, "Find account" — the resolved display name ("Phase13E
  Dev Player B") is shown for confirmation, never the raw account id.
  Select `observer` from the server-supplied initial-role list, Save. The
  overview refreshes to show Player B as a Campaign A member holding
  `observer`; Player B's own, separate Campaign B membership and roles are
  unaffected (a new, second membership row for the same user, not a
  reactivation of anything).
- **Eligibility excludes an already-active member:** the same "Find
  account" step with login name `phase13e.gm2` (Campaign A's own caller)
  or `phase13e.player_a`/`phase13e.observer_a` (already Campaign A members)
  returns "No eligible account found for that login name." — indistinguish
  able from a login name that does not exist at all.
- **Remove a member:** as `phase13e.gm2`, choose "Remove member" on
  `phase13e.observer_a`'s card. The confirmation names Observer A and
  explains that their campaign access will end. Confirm — the overview
  refreshes with Observer A no longer listed; Observer A's own active grant
  (`View Character Full Detail`) and `phase13e.player_a`'s unrelated
  character relationship are unaffected.
- **Self-removal with a second manager:** log in as `phase13e.player_b`
  (Campaign B, holding `campaign_owner` alongside the pre-existing
  `--user-id` account's own Campaign B membership), open the Access page,
  "Remove member" on Player B's own card. The confirmation names it as the
  caller's own access. Succeeds (200) — the `--user-id` account remains
  Campaign B's manager, so the campaign never loses its last one. Player
  B's Access-nav item disappears on the next request.
- **Last-manager rejection (removal):** as `phase13e.gm2` in Campaign A —
  the sole `access.manage` holder there — attempt "Remove member" on `gm2`'s
  own card. Rejected: the control shows "This member cannot be removed —
  the campaign must always retain at least one access manager."; `gm2`
  remains a Campaign A member and the Access nav item stays visible on the
  next request.
- **Disabled-account/cross-campaign eligibility boundaries not seed-
  exercisable:** an eligible-but-disabled account, and an already-ended
  (re-addable) membership, are not reachable through the five seeded
  accounts without a direct database edit (`phase13e.disabled`'s only
  membership is already open in Campaign A, so it is excluded by the
  "already a member" rule before its disabled status is ever reached) —
  this checkpoint's PostgreSQL-backed tests
  (`tests/database/test_api_membership_lifecycle.py`) are the authoritative
  coverage for a disabled target's exclusion, an inactive/cross-scope
  initial role, a non-active target campaign, and a duplicate-open-
  membership race, all rejected with a non-disclosing 404/409, never a 5xx.
- **Idempotent replay (add):** repeating the same add-member request with
  the same `Idempotency-Key` returns the original response unchanged,
  creating no second membership or role row.
- **Idempotent replay (removal):** repeating the same removal request with
  the same `Idempotency-Key` returns the original response unchanged,
  writing no second `audit.change_log` row.

### Character-relationship-management checkpoint manual-validation scenarios

No seed change was needed — `phase13e.player_a`'s pre-existing `owner`
relationship to "Phase13C Character A" (see the seeded-accounts table
above) already provides an existing relationship to change/revoke, and
`phase13e.observer_a` (no relationship of their own) provides a target
with nothing yet to add to.

- **Add a character relationship:** log in as `phase13e.gm2`, open Campaign
  A's Access page, expand `phase13e.observer_a`'s card, choose "Add
  character relationship". "Phase13C Character A" and every currently
  active relationship type are offered (server-authoritative, never
  hardcoded). Select "Viewer", Add. The overview refreshes to show the new
  relationship on Observer A's card; `phase13e.player_a`'s own unrelated
  `owner` relationship to the same character is unaffected (sibling
  relationships preserved).
- **Add excludes an already-active combination:** on `phase13e.player_a`'s
  own card, "Add character relationship" with "Phase13C Character A"
  selected omits "Owner" from the relationship-type choices (already
  active for that exact character) while still offering every other type —
  proving the exclusion is per-`(character, type)` combination, not a
  blanket "already has a relationship to this character" rule.
- **Change relationship type:** as `phase13e.gm2`, choose "Change type" on
  `phase13e.player_a`'s "Owner" relationship, select "Primary Controller",
  Save. The overview refreshes to show "Primary Controller" in place of
  "Owner" for the same character; the old assignment's row is revoked, not
  overwritten (temporal history preserved, verifiable via `tests/database/
  test_api_access_grants.py::test_changing_a_character_relationship_type_succeeds`'s
  own database assertions).
- **Revoke a character relationship:** as `phase13e.gm2`, choose "Revoke
  relationship" on `phase13e.player_a`'s current relationship. The
  confirmation names the character and member and explains that the
  character perspective will no longer be available. Confirm — the
  overview refreshes with the relationship gone; on Player A's own next
  `GET /auth/session`, the corresponding entry disappears from `character_
  perspectives` (`dnd_ai.queries.bootstrap` re-resolves fresh every call —
  no browser-session revocation needed).
- **Idempotent replay (add/change):** repeating the same add or change
  request with the same `Idempotency-Key` returns the original response
  unchanged, creating no second relationship row.
- **Idempotent replay (revoke):** repeating the same revoke request with
  the same `Idempotency-Key` returns the original response unchanged,
  writing no second `audit.change_log` row.

### Checkpoint 5 (direct resource-grant management) manual-validation scenarios

No seed change was needed — `phase13e.observer_a`'s pre-existing active
grant (`View Character Full Detail` on "Phase13C Character A", see the
seeded-accounts table above) already provides an existing grant to revoke,
and `phase13e.player_a` (no grant of its own beyond the pre-existing
*revoked* one) provides a target with room to add a fresh one.

- **Add direct resource access:** log in as `phase13e.gm2`, open Campaign
  A's Access page, expand `phase13e.player_a`'s card, choose "Add direct
  resource access". "Character" is the only resource type offered;
  "Phase13C Character A" and every currently grantable capability not
  already active for it are offered (server-authoritative, never
  hardcoded). Select "View Character Knowledge", Add. The overview
  refreshes to show the new grant on Player A's card; `phase13e.observer_
  a`'s own unrelated active grant to the same character is unaffected
  (sibling grants preserved).
- **Add excludes an already-active combination:** the pre-existing
  *revoked* `character.view_summary` grant on `phase13e.player_a` does
  **not** exclude `character.view_summary` from the capability choices
  (only a currently *active* combination is excluded) — confirming the
  exclusion is about current state, not history.
- **Revoke direct resource access:** as `phase13e.gm2`, choose "Revoke
  access" on `phase13e.observer_a`'s active grant. The confirmation names
  Observer A, the permission (`View Character Full Detail`), and the
  resource ("Phase13C Character A"), and explains that access may
  disappear immediately. Confirm — the overview refreshes with the grant
  gone; `phase13e.observer_a`'s own unrelated `observer` role is
  unaffected.
- **Non-character target kinds, access-group grants, and deny effects not
  seed-exercisable:** none of the seeded accounts has a grant of any of
  the other five target kinds, an access-group-targeted grant (access
  groups have no management UI at all yet), or a `deny`-effect grant (the
  portal's own Add flow only ever creates `allow`) — this checkpoint's
  PostgreSQL-backed tests (`tests/database/test_api_access_grants.py`,
  `test_resource_grant_concurrency.py`) and portal tests (`AccessPage.
  test.tsx`, `CampaignAccessPage.resourceGrant.integration.test.tsx`) are
  the authoritative coverage for those, plus the disabled-account/ended-
  membership/inactive-campaign/inactive-target/deactivated-or-incompatible-
  capability eligibility boundaries, all rejected with a non-disclosing
  404/409, never a 5xx. A `deny` grant can still reach the portal if
  created directly against the database (or by a future increment) —
  `RevokeResourceGrant` renders it with effect-aware wording ("Remove
  denial" rather than "Revoke access", explaining that access may be
  *restored* from another source rather than lost) rather than the
  allow-oriented copy this checkpoint originally shipped with (correction).
- **Idempotent replay (add):** repeating the same add request with the
  same `Idempotency-Key` returns the original response unchanged, creating
  no second grant row.
- **Idempotent replay (revoke):** repeating the same revoke request with
  the same `Idempotency-Key` returns the original response unchanged,
  writing no second `audit.change_log` row.

### Checkpoint 6 (campaign access-group management) manual-validation scenarios

**Not manually exercised against the dev fixture as part of this
checkpoint** — no seed change was made, and no accepted/Codex-reviewed
manual walkthrough of this checkpoint has occurred. `tests/database/
test_api_access_groups.py`/`test_access_group_concurrency.py` and the
portal's own component/hook/integration tests are the authoritative,
already-run coverage. A future manual pass against `scripts/
setup_phase13c_dev_data.py` should cover, at minimum: creating a group as
`phase13e.gm2`; adding `phase13e.player_a`/`phase13e.observer_a` to it;
granting the group `character.view_summary` on "Phase13C Character A" and
confirming both members gain that view without an individual grant of
their own; deactivating the group and confirming both members lose that
access on their next request while their own direct roles/grants are
unaffected; reactivating it and confirming it starts empty (no members, no
grants) until explicitly re-populated; and reviewing the resulting
`access_group`/`access_group_membership` audit-history entries for correct
labels.

### Expected access behavior

- **GM2** can log in and open the Access page directly, with no platform-administrator privilege needed — it holds `access.manage` only through the ordinary `campaign_owner` role.
- **Player A** and **Observer A** hold no `access.manage`: the Access nav item must not appear for either, and a direct `GET /campaigns/{campaign_a_id}/access-overview` request must return `403`.
- **Cross-campaign isolation:** Player A never sees Campaign B in their campaign list (no membership, no relationship reaching it); Player B never sees Campaign A, and vice versa.
- **Grants:** on Campaign A's Access overview, Observer A shows exactly one grant (`View Character Full Detail`); Player A shows none — the revoked grant is excluded, proving the same exclusion `tests/database/test_api_access_overview.py` already covers automatically.
- **Disabled account:** `phase13e.disabled` cannot authenticate and holds no usable browser session, but its Campaign A membership still appears on the Access overview with an ordinary "Active" *membership* status — `dnd_ai.queries.access_overview` deliberately never consults account-wide `security.users.lifecycle_status_id` (see §3 above). This is the documented contract, not a defect; the fixture does not invent a "disabled" label the implemented response does not provide.
