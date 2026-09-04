# D&D AI Portal

The portal is the browser interface for D&D AI. It uses React, TypeScript,
Vite, and React Router.

## Current status

Phase 13A is complete. Phase 13C campaign-context integration is implemented
on this branch, with live multi-campaign and perspective verification still
outstanding. Phase 13C is not yet marked complete.

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
  server-authorized perspective list after refresh.
- Capability-dependent navigation.
- A visibly disabled Ask feature while the server manifest disables it.
- Placeholder pages for later portal increments.
- Focused automated tests for session, routing, and selection behavior.

Navigating between pages within the same campaign preserves the provider
and selected perspective. Changing campaign scope resets them.

The campaign picker's Default campaign marker describes the server's
bootstrap default, not a persisted last-visited preference.

Phase 13D read-only resource views have not started.

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
- `/app/:campaignId/sessions`
- `/app/:campaignId/knowledge`
- `/app/:campaignId/ask`
- `/app/:campaignId/access`

Campaign resource pages remain placeholders. Campaign IDs from URLs are
matched against the current bootstrap's authorized campaign list.
Unavailable campaigns receive a generic unavailable/not-found state.

Frontend navigation visibility is presentation only. The backend remains
responsible for authorizing every resource request.

## Source organization

- `src/api`: HTTP clients.
- `src/components`: Interface components.
- `src/context`: Session and perspective contexts/providers.
- `src/fixtures`: Test fixture data; not production identity data.
- `src/hooks`: Session, login, and perspective behavior.
- `src/layouts`: Authentication boundaries and campaign layouts.
- `src/pages`: Route-level pages and placeholders.
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

## Phase 13C verification

Latest owner-reported local checks:

- 53 automated tests passed.
- ESLint passed.
- Production build passed.

Live checks already reported:

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