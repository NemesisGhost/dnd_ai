# World Portal development

The portal is a React/Vite/TypeScript client. It never connects directly to PostgreSQL.

```powershell
cd ui
npm install
npm run dev
```

Vite serves `http://127.0.0.1:5173` and proxies `/api/*` to the host FastAPI process at `http://127.0.0.1:8000`, removing the `/api` prefix. This mirrors the planned production same-origin routing and requires no development CORS exception.

Authentication is deliberately isolated in `src/auth/auth.tsx`. Until the browser authentication design is selected, the default provider presents an unauthenticated state and stores no token. Tests may inject an `AuthState`; do not add long-lived tokens to local or session storage.

Commands:

- `npm run dev` — development server
- `npm test` — component tests
- `npm run typecheck` — strict TypeScript checking
- `npm run build` — verified production bundle
