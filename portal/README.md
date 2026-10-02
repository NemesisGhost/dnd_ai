# D&D AI Portal

The portal is the browser interface for D&D AI. It uses React, TypeScript,
Vite, and React Router.

## Current status

**Phases 13A, 13B, 13C, 13D, and 13E are complete and verified.** The six
13D read-only screens (Home, World, Characters, Quests, Sessions, Knowledge)
are wired to live campaign-scoped API endpoints, each behind a shared
`*Boundary` component providing consistent loading, empty, denied
(non-discoverable), error-with-retry, and background-refreshing states.
**13E (GM access tools) is complete**: single-link invitation onboarding
(sign-in or invitation-authorized registration, then automatic acceptance),
platform-account administration and self-service account management, every
resource-grant target kind and the `deny` effect, a per-member
effective-access explanation, a per-resource (quest/knowledge) audience
preview, and an actor filter plus new categories on the campaign audit
history — alongside 13E-A/13E-B's earlier role, membership, character-
relationship, access-group, and invitation management. The automated suite
(`npm test`, `npm run lint`, `npm run build`) and a live multi-role browser
pass have both passed — see [Phase 13E verification](#phase-13e-verification)
below. Deliberately not built: full preview-as-user/impersonation over
every read screen (D-1's bounded substitute above covers this instead) and
explicit membership reactivation outside invitation acceptance. 13F
(Foundry connections/device UI), 13G (Phase 12 surfaces), and 13H (E2E
coverage and production packaging) have not started.

The portal currently includes:

- A responsive application shell and nested campaign routes.
- Local login and session restoration through FastAPI.
- Authoritative identity, campaign, timeline, role, perspective, capability,
  and feature data from `GET /auth/session`.
- Loading, unauthenticated, recoverable-error, and empty-campaign states.
- Inline campaign and character-perspective selection.
- Fresh session bootstrap when entering, leaving, or switching campaign
  scope, including browser Back/Forward navigation.
- In-memory character-perspective selection, checked against the latest
  server-authorized perspective list after refresh; capabilities (e.g. the
  Access nav item) come only from the bootstrap's per-campaign `capabilities`
  list, never derived locally from role or perspective.
- A Home dashboard showing the latest session, previous-session recap, and
  recent events (a narrower slice than Phase 13's full dashboard bullet —
  active quests, recent discoveries, relevant NPCs/factions, reminders, and
  an Ask entry point are not yet on this page).
- A World explorer with type-filtered and text-searchable result cards and
  keyset pagination.
- Characters, Quests (list and detail), and Sessions (list and detail)
  screens reading live campaign-scoped data.
- A Knowledge screen filterable by view (across the documented knowledge
  views) and authorized party, with search and keyset pagination.
- A visibly disabled Ask feature while the server manifest disables it.
- Light/dark theme switching.
- A live Access screen showing current members, roles, character
  relationships, resource grants of every target kind (both `allow` and
  `deny`), access groups, pending invitations, audit history, an
  effective-access explanation per member, and a per-resource audience
  preview. Delivered mutations include member and role management,
  character relationships, resource grants/group grants of any target kind
  and effect, access-group management, and invitation issue/revoke. See
  [Access management (13E)](#access-management-13e) below.
- A single-link invitation-onboarding flow (sign-in or invitation-authorized
  account creation, then automatic acceptance), with the manual token-entry
  form retained as a fallback.
- Platform-account administration (`/admin/accounts`) and self-service
  account management (`/account`): create/activate/reset/disable/reactivate/
  revoke-sessions, and own-password-change/own-session-revocation
  respectively.
- A placeholder page for the later Ask increment (Phase 12-gated).
- Automated tests covering routing, session and perspective behavior, and
  each screen's loading, empty, denied, and error states.

Navigating between pages within the same campaign preserves the provider
and selected perspective. Changing campaign scope resets them.

The campaign picker's Default campaign marker describes the server's
bootstrap default, not a persisted last-visited preference.

## Prerequisites

The portal has been verified with:

- Node.js 24.13.1
- npm 11.8.0

Use versions compatible with the dependencies recorded in `package-lock.json`.

## Install dependencies

From the repository root:

```powershell
Set-Location .\portal
npm install
```

For a clean checkout or automated build, use:

```powershell
Set-Location .\portal
npm ci
```

`npm ci` installs exactly the dependency versions recorded in
`package-lock.json` and does not update the lock file.

## Run locally

From `C:\Users\nemes\dnd_ai\portal`:

```powershell
npm run dev
```

Vite normally serves the portal at:

```text
http://localhost:5173
```

## Quality checks

Run the focused component tests:

```powershell
npm test
```

Run the linter:

```powershell
npm run lint
```

Create a production build:

```powershell
npm run build
```

The build output is written to `portal\dist`. The `dist` directory is generated
output and should not be committed.

Before committing portal work, run:

```powershell
npm test
npm run lint
npm run build
```

## Development proxy contract

Frontend API requests use same-origin relative URLs. Session bootstrap uses
`GET /auth/session`, not `/api/session`.

During local development, Vite forwards:

- `/api/*` to `http://localhost:8000/api/*`
- `/auth/*` to `http://localhost:8000/auth/*`

FastAPI must be running separately. Its database configuration must point
to the PostgreSQL instance actually used by that API process. Native local
PostgreSQL and Docker Compose can use different hostnames and ports.

In production, the reverse proxy must serve the portal and forward API
requests from the same public origin.

Do not commit local database credentials or authentication secrets.

## Routes

The navigation redesign (`docs/UI_DESIGN.md` §4-§5, `docs/PLAN.md` §23.6) is
implemented. `/` always redirects to `/login`; an authenticated visitor is
then redirected again, from `/login`, to `/home` (or to a validated
continuation destination carried in router history state — never the URL —
when the visitor was redirected here from a protected route). Logging out
navigates explicitly to `/login` with no continuation state, so a different
user signing in next always lands on `/home`. Unknown routes always show a
not-found page; they never redirect to `/login`.

Public routes (`PublicLayout`: identity chrome plus the theme selector;
Home/Campaigns/the profile menu additionally appear here for a visitor who
is, unusually, already authenticated):

- `/` — redirects to `/login`.
- `/login`
- `/campaign-invitations/accept` — manual authenticated-acceptance form, and
  (Phase 13E checkpoints 8a-8d) the single-link onboarding landing page:
  opening `/campaign-invitations/accept#token=<one-time-token>` reads the
  fragment exactly once, immediately replaces it with the fragment-free URL,
  and exchanges the token for a short-lived server-side onboarding session
  before offering sign-in or invitation-authorized account creation.
- `/auth/activate` and `/auth/password-reset` (Phase 13E checkpoint 11) —
  extract a one-time token from the URL fragment the same way, immediately
  clear it from browser history, and submit it in a JSON body.
- Any unmatched path — a shared, non-disclosing not-found page.

Authenticated global routes (`AuthenticatedAppLayout`: the single session
gate for every route below, with persistent Home/Campaigns navigation and
the profile menu — see `src/layouts/AuthenticatedAppLayout.tsx`):

- `/home` — the landing page: a welcome line, the bootstrap's default
  campaign (if any), up to six of the signed-in account's campaigns, a link
  to the full campaign browser, an empty state with a Browse-campaigns and
  an accept-invitation link when there are none, and an Account section
  (Your account, and Platform accounts for a platform administrator).
- `/campaigns` — the full campaign browser (unchanged from Phase 13C).
- `/account` — self-service password change and own-session management, for
  any authenticated account.
- `/platform/accounts` — platform-account administration, gated on
  `SessionBootstrap.is_platform_administrator` (never a campaign-scoped
  `access.manage` grant). A non-administrator sees the same not-found page
  as an unknown route and triggers no account-list request.
- `/admin/accounts` — kept as a redirect to `/platform/accounts` for
  existing bookmarks; the backend endpoint itself is still
  `/api/admin/accounts*`.

Authenticated campaign routes (nested under `/app/:campaignId`, gated by the
same global session boundary plus `CampaignLayout`'s own authorized-campaign
lookup):

- `/app/:campaignId/home`
- `/app/:campaignId/world`
- `/app/:campaignId/world/:category/:entityId`
- `/app/:campaignId/characters`
- `/app/:campaignId/quests`
- `/app/:campaignId/quests/:questId`
- `/app/:campaignId/sessions`
- `/app/:campaignId/sessions/:sessionId`
- `/app/:campaignId/knowledge`
- `/app/:campaignId/knowledge/:knowledgeItemId`
- `/app/:campaignId/ask` (placeholder — disabled pending Phase 12)
- `/app/:campaignId/access` — live campaign access-management surface
  (13E-A/13E-B; see [Access management (13E)](#access-management-13e) below)
- `/app/:campaignId/access/audit` — the same Access section's audit-history
  tab, its own route so a direct reload works and neither tab fetches the
  other's data

Every route above except `ask` is a live, API-backed screen. Campaign IDs
from URLs are matched against the current bootstrap's
authorized campaign list. Unavailable campaigns receive a generic
unavailable/not-found state.

Frontend navigation visibility is presentation only. The backend remains
responsible for authorizing every resource request.

## Source organization

- `src/api`: Typed fetch clients, one module per backend contract (session,
  world, quests, sessions, knowledge, characters, campaign summary, login,
  access management, audit history, invitations, invitation onboarding,
  platform accounts, account activation/password reset, self-service
  account management, effective access, and audience preview).
- `src/components`: Interface components, including the `*Boundary`
  components (e.g. `WorldEntitiesBoundary`, `KnowledgeItemsBoundary`,
  `CampaignQuestsBoundary`) that turn a hook's fetch state into consistent
  loading/empty/denied/error/refreshing UI for each screen, plus the shared
  header chrome (`PortalHeader`, `PortalFooter`, `GlobalNavigation`,
  `ProfileMenu`, `ProfileAvatar`).
- `src/context`: Session and character-perspective contexts/providers.
- `src/fixtures`: Test-only fixture data; never used outside tests.
- `src/hooks`: Data-fetching hooks backing each boundary, plus session,
  login, logout, and perspective behavior.
- `src/layouts`: `PublicLayout` and `AuthenticatedAppLayout` (the shared
  header/footer shells and the single authenticated-session gate), plus
  `CampaignSessionBoundary`/`CampaignLayout`.
- `src/pages`: Route-level screens (the `/home` landing page, World,
  Characters, Quests, Sessions, Knowledge, Access, invitation
  acceptance/onboarding, Login, admin accounts, self-service account,
  account activation, password reset) and placeholders, including the
  shared `NotFoundPage`.
- `src/themes`: Light/dark theme context, provider, and selector.
- `src/test`: Shared test initialization.
- `src/types`: TypeScript representations of backend contracts.
- `src/App.tsx`: Declarative route table.
- `src/main.tsx`: Router and provider setup.

## Authentication boundary

The portal uses local application authentication and an opaque server-side
browser session. JavaScript does not read the HttpOnly session cookie.

`GET /auth/session` supplies current identity and authorization context.
The frontend retains bootstrap data, including the CSRF token, in memory;
it does not persist these values in localStorage or sessionStorage.

Cookie-authenticated mutations requiring CSRF protection must send the
in-memory token using `X-CSRF-Token`. The backend also validates Origin.

Campaign roles are display information. The frontend must not derive or
grant capabilities from role names or perspective choices.

A selected character is a requested viewing context, not an authorization
grant. A null selection does not grant campaign-wide access.

Foundry device authentication remains a separate boundary. The portal does
not store Foundry device credentials.

A successful login lands on `/home`, or on a continuation destination
carried in router history state (set only when a protected route redirected
here) once that destination passes a same-origin, allowlisted-path check
(`src/utils/postLoginDestination.ts`). Logging out calls `POST /auth/logout`,
reloads session state, and then explicitly navigates to `/login` with no
continuation state in the same synchronous step, so a later sign-in by a
different person never lands back on the signed-out person's page. Revoking
the current browser session from `/account` is the one case where the same
person is returned to `/account` after signing back in, because that
redirect goes through the ordinary protected-route continuation path rather
than the explicit logout navigation.

Backend endpoint availability does not mean that every account-management
or authentication workflow has a completed portal screen.

The invitation-acceptance page accepts a token from a password-style input,
holding it in React memory only, as a fallback for a player who cannot open
the generated link. The single-link workflow (Phase 13E checkpoints 8a-8d)
is the primary path: the one-time token appears only in the URL fragment,
is removed immediately with `history.replaceState`, and is exchanged in a
JSON request body for an opaque, short-lived, `HttpOnly` onboarding cookie.
It never appears in a path, query string, request log, cookie value,
local/session storage, IndexedDB, audit record, or later read response.
`ActivateAccountPage`/`ResetPasswordPage` (checkpoint 11) extract their own
one-time tokens from the URL fragment the identical way.

Account creation from the onboarding route is invitation-authorized. The
portal exposes no unrestricted public registration. A valid onboarding
session lets a player either sign in to an existing account or create and
activate their own local account, after which the invitation is accepted
for that authenticated account. Acceptance creates or reactivates a
campaign membership only; it does not assign roles or restore historical
relationships, grants, or access-group membership.

## Navigation redesign verification

The automated suite (`npm test`, `npm run lint`, `npm run build`) covers the
root/login/logout redirects, the `/home` landing page, the profile menu's
disclosure semantics and keyboard/focus behavior, `/platform/accounts`
(including the no-request guarantee for a non-administrator), campaign
switching always entering Campaign Home, and deep-link continuation.

The following manual browser and assistive-technology checks (navigation
plan §7.3) have not yet been run against a real local stack and remain
outstanding:

1. Sign-in as a non-administrator and as a platform administrator; confirm
   the landing page and profile-menu contents, and Platform Accounts'
   presence/absence.
2. Deep link while signed out, sign in, and confirm arrival at the original
   destination; confirm `/login` while already signed in reaches `/home`;
   confirm Back after logout never shows protected content.
3. The invitation single-link flow still reaches "Go to campaigns" without
   interruption from the ordinary login-landing rule.
4. Keyboard-only use of the header and profile menu in every theme.
5. Screen reader (NVDA + Firefox or Chrome on Windows) announcements of the
   Global/Campaign landmarks, the profile button's name and expanded state,
   the Administration group, and the logout error alert.
6. Responsive layout at 320px/390px/768px/1024px/≥1280px and 200% zoom, with
   no horizontal page scroll.
7. A campaign switch from a quest detail with a character perspective
   selected lands on Campaign Home with the header staying visible during
   the reload.
8. A zero-campaign account's landing empty state and invitation entry
   point.

## Phase 13E verification

Automated checks for the completed 13E checkpoint sequence (run from
`portal/`):

- `npm test` — 1,198 tests passed across 210 test files.
- `npm run lint` passed.
- `npm run build` passed.

See `docs/PHASE13E_VERIFICATION.md` for the full backend+portal evidence
record, including the manual-validation scenarios run against the dev
fixture accounts.

## Phase 13C/13D verification

Automated checks for the latest reviewed invitation checkpoint (run from
`portal/`), preserved for historical reference:

- `npm test` — 1,034 tests passed across 160 test files.
- `npm run lint` passed.
- `npm run build` passed.

Live checks reported for 13C (campaign/perspective context):

- Login succeeds and opens campaign selection.
- Refresh restores the authenticated session.
- An account with no campaigns sees the empty state.
- An unknown campaign URL receives Campaign not found.
- Two authorized campaigns appear with correct timeline and role data.
- Selecting a campaign refreshes `/auth/session` before displaying its protected context.
- Change campaign and browser Back/Forward refresh authorization when campaign scope changes.
- Navigating within one campaign preserves the selected perspective.
- Selecting either of two authorized perspectives refreshes the session and keeps the dropdown and context summary synchronized.
- Removing a perspective or campaign membership through supported backend operations removes it from the portal after refresh.
- Session expiry/revocation followed by refresh shows login without retained protected context.
- A failed refresh hides protected context and offers a working retry.
- Disabled Phase 12 surfaces make no related network requests.

Live checks reported for 13D (Home, World, Characters, Quests, Sessions,
Knowledge), exercised across GM, player, and observer/assistant-GM
perspectives:

- Each screen loads live data for an authorized campaign/character
  perspective, and reflects a perspective or campaign switch correctly.
- GM, player, and observer views differ correctly where authorization or
  knowledge scoping applies (notably Knowledge and World).
- Inaccessible or unauthorized resources produce the denied/unavailable
  state rather than leaking existence.
- Quests and Sessions list-to-detail navigation works, and World/Knowledge
  search, category/view filters, and keyset pagination return correct live
  results.
- A simulated request failure shows the error state and a working retry.

## Access management (13E)

`/app/:campaignId/access` began as the 13E-A read-only screen backed by
`GET /campaigns/{campaignId}/access-overview` (server-side capability
`access.manage` — the same capability that already gates the Access nav
item's visibility). It shows, per currently active campaign member: their
display name and membership status, active roles, current character
relationships, and explicit membership-targeted resource grants, all with
human-readable labels. Identifiers in the response DTO (membership,
character, role, and grant IDs) exist only for record identity — the page
never renders them as visible text, only as React keys.

13E-B extends that screen with server-authorized controls for:

- adding and ending campaign memberships;
- adding, changing, and revoking role assignments;
- adding, changing, and revoking character relationships;
- adding and revoking a direct resource grant of **any** target kind
  (character, entity, event, knowledge item, quest, or session) and either
  `allow` or an explicitly-confirmed `deny` effect, via the shared
  `ResourceTargetSelector`;
- creating, updating, deactivating, and reactivating access groups;
- adding multiple campaign members to a group in one atomic operation and
  removing individual group members;
- adding and revoking a group-owned resource grant of any target kind and
  effect, identically to a direct grant;
- issuing, listing, and revoking pending campaign invitations, with a
  copyable single-link invitation (see below) alongside manual-entry;
- explaining a selected member's effective access (`EffectiveAccessPanel`,
  one disclosure per member row: every capability held, with its role/
  relationship/grant sources, plus any active `deny`); and
- previewing a quest or knowledge item exactly as a selected member would
  see it (`AudiencePreviewPanel`), for spoiler-checking before a session.
  `AudiencePreviewSection` places the same control directly on the Quest
  and Knowledge collection pages (resource type locked to the page, the
  specific resource still picked via `ResourceTargetSelector`) and their
  detail pages (both the type and the resource locked to what is already
  on screen) — there is no page for previewing a whole *collection*,
  because no backend route projects one; only the same single-quest/
  single-knowledge-item detail endpoint `AudiencePreviewPanel` already
  used exists. Every placement independently checks the same
  `access.manage` capability before fetching the campaign's member list.

Reading campaign audit history, filterable by category and by actor
(the actor list sourced from its own bounded, identically-authorized
facet, `GET .../audit-history/actors` — never the complete access-overview
response, and never a new account-directory query), is a sibling route
rather than a panel on this same screen — `/app/:campaignId/access/audit`,
with its own tab (`AccessTabNav`) shared with the management route above.
Opening one tab never fetches the other's data, and reloading the audit
URL directly works the same as navigating to it.

The GM's copyable single-link invitation
(`/campaign-invitations/accept#token=<one-time-token>`) is the primary
player-facing acceptance path; the manual-entry token form remains available
as a fallback for a player who cannot open the generated link. Opening the
link establishes a short-lived onboarding session, offers **Sign in** or
invitation-authorized **Create account**, and accepts the invitation
automatically after authentication. The accepted membership still receives
no role or other access automatically — a GM configures that separately.

Platform-account administration (`/platform/accounts`, with `/admin/accounts`
kept as a redirect for existing bookmarks: create, issue a password-reset
link, disable, reactivate, revoke all sessions) and
self-service account management (`/account`: change own password, list and
revoke own browser sessions) are separate, non-campaign-scoped pages — see
[Routes](#routes) above.

Deliberately not built: full preview-as-user/impersonation over every read
screen (Option A — the effective-access explanation plus the per-resource
audience preview above are the bounded substitute, by owner decision D-1);
explicit membership reactivation outside invitation acceptance (a departed
member is re-added as a new membership, never reactivated in place); Foundry
administration; and Phase 12 AI features. The authoritative endpoint and
security details are maintained in `docs/PHASE13E_ACCESS_CONTRACT.md`.

## Learning checkpoints

The Phase 13A implementation was intentionally divided into small checkpoints:

1. Create and verify the React, TypeScript, and Vite scaffold.
2. Replace the generated demo with an accessible application shell.
3. Define provisional TypeScript bootstrap types and fixture data.
4. Display fixture-backed campaign context.
5. Add React Router without changing the visible application.
6. Add placeholder routes.
7. Introduce nested campaign layouts and capability-aware navigation.
8. Configure the future same-origin development proxy.
9. Add focused tests for meaningful route and navigation behavior.
10. Document the development workflow and validate the completed foundation.

Portal authorship changes at increment 13E (`docs/PLAN.md` §2.9). Increments
13A through 13D are owner-authored, with AI assistance limited to teaching,
explanation, review, and debugging. From 13E onward the portal is Claude
Code-authored by owner decision, and the owner manually validates every
increment against a real local PostgreSQL 18 server before it is closed out.
Backend authorization remains authoritative in both cases: portal code may
hide or disable a control for presentation only.
