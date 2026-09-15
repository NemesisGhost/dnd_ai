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
[Phase 13C/13D verification](#phase-13c13d-verification) below. 13E (GM
access tools), 13F (Foundry connections/device UI), 13G (Phase 12 surfaces),
and 13H (E2E coverage and production packaging) have not started.

The portal currently includes:

- A responsive application shell and nested campaign routes.
- Local login and session restoration through FastAPI.
- Authoritative identity, campaign, timeline, role, perspective, capability,
  and feature data from `GET /auth/session`.
- Loading, unauthenticated, recoverable-error, and empty-campaign states.
- Campaign selection and a Change campaign navigation link.
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
- A World explorer with type-filtered/text-searchable browsing, typed detail
  routes (religions, item instances, historical events, locations with
  containment breadcrumbs), and keyset pagination.
- Characters, Quests (list and detail), and Sessions (list and detail)
  screens reading live campaign-scoped data.
- A Knowledge screen filterable by view (across the documented knowledge
  views) and authorized party, with search and keyset pagination.
- A visibly disabled Ask feature while the server manifest disables it.
- Light/dark theme switching.
- Placeholder pages for later portal increments (Ask, Access management).
- 369 automated tests (`npm test`) covering routing, session/perspective
  behavior, and each screen's loading/empty/denied/error states.

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
- `/app/:campaignId/access` (placeholder — Phase 13E)

Every route above except `ask` and `access` is a live, API-backed screen.
Campaign IDs from URLs are matched against the current bootstrap's
authorized campaign list. Unavailable campaigns receive a generic
unavailable/not-found state.

Frontend navigation visibility is presentation only. The backend remains
responsible for authorizing every resource request.

## Source organization

- `src/api`: Typed fetch clients, one module per backend contract (session,
  world, quests, sessions, knowledge, characters, campaign summary, login).
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
  Sessions, Knowledge, Login) and placeholders.
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

## Phase 13C/13D verification

Automated checks (all screens, run from `portal/`):

- `npm test` — 369 tests passed across 65 test files.
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