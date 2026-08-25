# D&D AI Portal

The portal is the browser interface for D&D AI. It uses React, TypeScript,
Vite, and React Router.

## Current status

Phase 13A establishes the fixture-only UI foundation.

The current portal includes:

- A responsive application shell.
- Public and campaign-specific route boundaries.
- Placeholder routes for the planned portal destinations.
- Fixture-backed campaign, timeline, role, and character-perspective context.
- Capability-dependent navigation.
- A visibly disabled Ask feature pending Phase 12 verification.
- Focused tests for meaningful routing and navigation behavior.
- Development proxies for the future `/api` and `/auth` endpoints.

Phase 13A does not perform authenticated requests or communicate with FastAPI.
The fixture bootstrap contract is provisional. The Phase 13B backend contract
will become authoritative when local authentication and browser sessions are
implemented.

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

React code should use same-origin relative URLs:

```ts
fetch('/api/session')
fetch('/auth/logout')
```

During local development, Vite forwards:

- `/api/*` to `http://localhost:8000/api/*`
- `/auth/*` to `http://localhost:8000/auth/*`

In production, the reverse proxy will serve the portal and forward `/api` and
`/auth` from the same public origin.

Phase 13A components must not make these requests. The proxy exists so later
phases can use the production URL contract during development.

## Placeholder routes

Public routes:

- `/`
- `/login`
- `/campaigns`

Campaign routes:

- `/app/:campaignId/home`
- `/app/:campaignId/world`
- `/app/:campaignId/characters`
- `/app/:campaignId/quests`
- `/app/:campaignId/sessions`
- `/app/:campaignId/knowledge`
- `/app/:campaignId/ask`
- `/app/:campaignId/access`

The `:campaignId` segment is supplied by the selected campaign.

## Source organization

- `src/components`: Reusable interface components.
- `src/fixtures`: Phase 13A fixture data.
- `src/layouts`: Shared route layouts.
- `src/pages`: Route-level page components and placeholders.
- `src/test`: Shared test initialization.
- `src/types`: Provisional frontend data contracts.
- `src/App.tsx`: Current declarative route table.
- `src/main.tsx`: Browser application entry point.

## Authentication boundary

The browser will not store passwords, bearer tokens, or Foundry credentials.

Phase 13B will add:

- Application-owned local authentication.
- Opaque server-side browser sessions.
- A secure `HttpOnly`, `SameSite=Lax` session cookie.
- CSRF tokens for mutating browser requests.
- Allowed-Origin validation.
- Session bootstrap through FastAPI.

Foundry device pairing is a separate authentication boundary and is not part of
the Phase 13A portal foundation.

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