# D&D AI Portal

The portal is the browser interface for D&D AI. It uses React, TypeScript,
Vite, and React Router.

## Current status

**Phases 13A, 13B, 13C, and 13D are complete and verified.** The six 13D
read-only screens (Home, World, Characters, Quests, Sessions, Knowledge) are
wired to live campaign-scoped API endpoints, each behind a shared
`*Boundary` component providing consistent loading, empty, denied
(non-discoverable), error-with-retry, and background-refreshing states. The
automated suite (`npm test`, `npm run lint`, `npm run build`) and a live
multi-role browser pass have both passed — see
[Phase 13C/13D verification](#phase-13c13d-verification) below. **13E (GM
access tools) is in progress**: 13E-A delivered the live campaign access
overview, and 13E-B now includes role and membership management, character
relationships, character-targeted grants, access groups, audit history, and
manual-token campaign invitations. The next planned invitation checkpoint
adds a single-link sign-in/registration/acceptance workflow; it is specified
below but is not implemented yet. Platform account lifecycle management,
preview-as-user, and the remaining non-character grant surfaces also remain.
13F (Foundry connections/device UI), 13G (Phase 12 surfaces), and 13H (E2E
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
  relationships, direct resource grants, access groups, pending invitations,
  and audit history. Delivered mutations include member and role management,
  character relationships, character-targeted grants, access-group
  management, and invitation issue/revoke. See
  [Access management (13E)](#access-management-13e) below.
- An authenticated campaign-invitation acceptance page with manual token
  entry. Single-link onboarding and invitation-authorized registration are
  planned but not implemented.
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

Public routes:

- `/`
- `/login`

Planned public onboarding route (not implemented yet):

- `/campaign-invitations/accept#token=<one-time-token>` — the token will be
  removed from the URL immediately and exchanged for a short-lived,
  server-side onboarding session. Until that checkpoint is delivered,
  `/campaign-invitations/accept` remains an authenticated manual-entry page.

Authenticated campaign selection:

- `/campaigns`

Authenticated campaign routes:

- `/app/:campaignId/home`
- `/app/:campaignId/world`
- `/app/:campaignId/characters`
- `/app/:campaignId/quests`
- `/app/:campaignId/quests/:questId`
- `/app/:campaignId/sessions`
- `/app/:campaignId/sessions/:sessionId`
- `/app/:campaignId/knowledge`
- `/app/:campaignId/ask` (placeholder — disabled pending Phase 12)
- `/app/:campaignId/access` — live campaign access-management surface
  (13E-A/13E-B; see [Access management (13E)](#access-management-13e) below)

Every route above except `ask` is a live, API-backed screen. Campaign IDs
from URLs are matched against the current bootstrap's
authorized campaign list. Unavailable campaigns receive a generic
unavailable/not-found state.

Frontend navigation visibility is presentation only. The backend remains
responsible for authorizing every resource request.

## Source organization

- `src/api`: Typed fetch clients, one module per backend contract (session,
  world, quests, sessions, knowledge, characters, campaign summary, login,
  access management, audit history, and invitations).
- `src/components`: Interface components, including the `*Boundary`
  components (e.g. `WorldEntitiesBoundary`, `KnowledgeItemsBoundary`,
  `CampaignQuestsBoundary`) that turn a hook's fetch state into consistent
  loading/empty/denied/error/refreshing UI for each screen.
- `src/context`: Session and character-perspective contexts/providers.
- `src/fixtures`: Test-only fixture data; never used outside tests.
- `src/hooks`: Data-fetching hooks backing each boundary, plus session,
  login, and perspective behavior.
- `src/layouts`: Authentication/session boundaries and campaign layouts.
- `src/pages`: Route-level screens (Home, World, Characters, Quests,
  Sessions, Knowledge, Access, invitation acceptance, Login) and
  placeholders.
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

Backend endpoint availability does not mean that every account-management
or authentication workflow has a completed portal screen.

The implemented invitation page accepts a token from a password-style input
and holds it in React memory only. It never places the token in a URL or
browser storage. The planned single-link workflow is a deliberate, narrowly
bounded extension: the one-time token will appear only in a URL fragment,
will be removed immediately with `history.replaceState`, and will be
exchanged in a JSON request body for an opaque, short-lived, `HttpOnly`
onboarding cookie. It must never appear in a path, query string, request log,
cookie value, local/session storage, IndexedDB, audit record, or later read
response.

Account creation from that future route will be invitation-authorized. The
portal will not expose unrestricted public registration. A valid onboarding
session will allow a player either to sign in to an existing account or to
create and activate their own local account, after which the invitation is
accepted for that authenticated account. Acceptance creates or reactivates a
campaign membership only; it does not assign roles or restore historical
relationships, grants, or access-group membership.

## Phase 13C/13D verification

Automated checks for the latest reviewed invitation checkpoint (run from
`portal/`):

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
- adding and revoking character-targeted direct resource grants;
- creating, updating, deactivating, and reactivating access groups;
- adding multiple campaign members to a group in one atomic operation and
  removing individual group members;
- adding and revoking character-targeted group grants;
- reading campaign audit history; and
- issuing, listing, and revoking pending campaign invitations.

The current invitation-acceptance page requires the player to authenticate
and paste the token manually. The next planned checkpoint replaces the GM's
copyable token with a copyable single link while keeping manual entry as a
fallback. Opening the link will establish a short-lived onboarding session,
offer **Sign in** or invitation-authorized **Create account**, and accept the
invitation after authentication. The accepted membership still receives no
role or other access automatically.

Still deferred: the single-link onboarding implementation, broader
platform-administrator account lifecycle screens, preview-as-user,
membership reactivation outside invitation acceptance, non-character grant
search/presentation, explicit deny-grant creation, Foundry administration,
and Phase 12 AI features. The authoritative endpoint and security details
are maintained in `docs/PHASE13E_ACCESS_CONTRACT.md`.

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

The production UI is owner-authored. AI assistance may be used for teaching,
explanation, review, and debugging.
