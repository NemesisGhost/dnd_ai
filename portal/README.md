# D&D AI Portal

React/TypeScript/Vite client for the application API. Backend authorization is authoritative.
[Project status](../docs/PROJECT_STATUS.md) owns delivery state; [UI design](../docs/UI_DESIGN.md)
owns routes/navigation/behavior; [style guide](../docs/UI_STYLE_GUIDE.md) owns presentation.
[Access control](../docs/api/ACCESS_CONTROL.md) and the read API references own API contracts.

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


## Source organization

- `src/pages/`: routed screens and workspaces.
- `src/components/`: shared and domain-specific UI components.
- `src/hooks/`: query, mutation and state hooks.
- `src/navigation/`: task origin, selected context, route metadata and breadcrumb contracts.
- `src/api/` and `src/types/`: API clients and TypeScript contracts.

API requests use same-origin credentials and supported CSRF/session handling. Never put
tokens, private drafts or authorization grants in navigation persistence. Route selection
is not permission. Check UI_DESIGN and current route metadata before adding navigation.
Historical implementation/learning checkpoints are indexed in [delivery history](../docs/DELIVERY_HISTORY.md).
