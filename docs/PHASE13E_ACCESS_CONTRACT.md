# Phase 13E access-management contract inventory

Written for the 13E-A increment (read-only campaign access overview,
`docs/PLAN.md` §13). Records what the backend actually exposes for
GM access management as of this increment — not a design proposal, and
not a claim that Phase 13E or any of its mutation work is complete.
**Only 13E-A (the read-only overview) is delivered.** Everything else
below marked "reserved for a later increment" is existing backend
capability with no portal UI yet, or (where noted) a backend contract
that does not exist at all yet.

## 1. Existing read endpoints

| Endpoint | Module | Capability | Notes |
|---|---|---|---|
| `GET /campaigns/{campaign_id}/access-overview` | `dnd_ai.api.access_overview` | `access.manage` | New in 13E-A. See §3. |

No other read endpoint exposes campaign membership, role, character-relationship, or resource-grant state — confirmed by inspection of `dnd_ai.api.memberships`, `dnd_ai.api.access_grants`, and `dnd_ai.api.campaign_invitations` (all write-only; see §2).

## 2. Existing mutation endpoints (reserved for a later 13E increment)

| Endpoint | Method | Module | Capability | Boundary |
|---|---|---|---|---|
| `/campaigns/{campaign_id}/memberships` | POST | `dnd_ai.api.memberships` | `access.manage` | Campaign-scoped |
| `/campaigns/{campaign_id}/memberships/{membership_id}/roles` | POST | `dnd_ai.api.memberships` | `access.manage` | Campaign-scoped |
| `/campaigns/{campaign_id}/memberships/roles/{membership_role_id}/revoke` | POST | `dnd_ai.api.memberships` | `access.manage` | Campaign-scoped |
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
- **Response (`CampaignAccessOverviewResponse`):** `{ members: [CampaignMemberSummaryResponse] }`, one entry per currently open (`ended_at IS NULL`) campaign membership:
  - `campaign_membership_id` (UUID — identity only, never rendered as page text)
  - `display_name`, `status_code`, `status_display_name`, `joined_at`
  - `roles: [{ role_id, code, display_name }]` — active (non-revoked, non-expired, `is_active`) roles only
  - `character_relationships: [{ membership_character_relationship_id, character_id, character_display_name, relationship_type_code, relationship_type_display_name, granted_at, expires_at }]` — current (non-revoked, non-expired, timeline-scoped) relationships only
  - `grants: [{ resource_grant_id, capability_code, capability_display_name, effect, target_type, reason, granted_at, expires_at }]` — current, membership-targeted (not access-group-targeted), active-capability resource grants only (see the capability-parity correction below)
- **Pagination/filtering:** none. Per-campaign membership/role/relationship/grant counts are expected to stay small (matching the existing precedent in `dnd_ai.api.memberships`/`.access_grants`, neither of which paginates); no cursor, no limit, no total count.
- **401:** unauthenticated requests never reach this route's own logic — `dnd_ai.api.auth.get_authenticated_user_id` (the same dependency every other route uses) rejects them first; this route adds no separate 401 handling.
- **403:** an authenticated member of the campaign who does not hold `access.manage`.
- **404:** no active, authorizing membership in the campaign at all, **or** the campaign does not exist — both indistinguishable, matching `require_campaign_capability`'s existing non-disclosing contract (the same 404 shape `dnd_ai.api.memberships`/`.access_grants` already give).
- **Validation:** a malformed `campaign_id` (not a UUID) is rejected by FastAPI's own path-parameter validation before any handler code runs (422).
- **Recoverable errors:** any other failure (5xx) is not specially handled by this route and surfaces as a generic error to the portal's existing recoverable-error boundary with retry.
- **Audience-safe fields:** `security.users.display_name` only (never `email`, never a login identifier, never `external_identities.subject`); `membership_statuses.display_name` (campaign-scoped status, not the account-wide `lifecycle_status_id`); `roles.display_name`/`code`; `character_relationship_types.display_name`/`code` plus the related character's `core.entities.canonical_name`; `capabilities.display_name`/`code`, `effect`, `target_type` (the grant's target *kind* only — `character`/`entity`/`knowledge_item`/`quest`/`session`/`event` — never the specific target resource's own display identity), `reason`, `granted_at`, `expires_at`.
- **Correction (review pass):** the resource-grants query now also requires `security.capabilities.is_active`, matching `dnd_ai.domain.access.resolve_access_context`'s own resource-grant resolution — an otherwise-current grant of a *deactivated* capability confers no effective access there and must not appear here as a current grant either. Covered by `tests/database/test_api_access_overview.py::test_a_grant_of_a_deactivated_capability_is_excluded_while_an_active_one_remains`.

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
- A UI for any of the existing mutation endpoints in §2 (role assignment/revocation, character-relationship grant/revocation, resource-grant creation/revocation, invitation issuance, account creation/activation/reset/disable/reactivate/revoke-sessions).

None of the above is implemented by 13E-A. This increment is read-only.
