# UI development setup

The portal lives in `ui/`. Authentication is intentionally left behind an adapter while the browser authentication design is selected. Everything else can run locally now.

After configuring `.env`, Windows developers can run the complete database, migration, demonstration-data, and frontend-dependency setup in one step:

```powershell
.\scripts\setup_ui_dev.ps1
```

The explicit steps performed by that command follow.

## From an empty local database

1. Copy `.env.example` to `.env` and set `POSTGRES_PASSWORD`, `MIGRATION_DATABASE_URL`, and host-facing `DATABASE_URL` as described in [DEVELOPMENT.md](DEVELOPMENT.md#36-self-hosted-docker-compose).
2. Start PostgreSQL and migrate it:

   ```powershell
   docker compose up -d db
   docker compose --profile tools run --rm migrate
   ```

3. Create the persistent demonstration campaign:

   ```powershell
   uv run python -m scripts.setup_demo_data
   ```

   The command is idempotent. It creates the `portal-demo` world only when absent and otherwise prints the existing campaign manifest. It creates GM, assistant-GM, two-player, and observer identities under the deliberately non-production issuer `https://portal-dev.invalid`. When browser auth is selected, either configure matching subjects in that provider or replace these external-identity links deliberately.

4. Start FastAPI on the host:

   ```powershell
   uv run uvicorn dnd_ai.api.app:app --reload
   ```

5. In another terminal, install and start the portal:

   ```powershell
   cd ui
   npm install
   npm run dev
   ```

Open `http://127.0.0.1:5173`. Vite proxies `/api/*` to FastAPI at `127.0.0.1:8000`, matching the planned same-origin production route without enabling broad CORS.

## Verification

```powershell
cd ui
npm test
npm run typecheck
npm run build
```

The demonstration-data command is development authoring infrastructure, not a production seed. Lookup seeds remain migration-managed. Static world authoring currently has no public command/API, so this bounded script reuses the same trusted authoring factories as the Phase 10 acceptance scenario; campaign and access state use application commands.
