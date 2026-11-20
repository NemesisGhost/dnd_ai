# Start a local development instance

Use a new development database and an unused local Compose project for this journey. PostgreSQL 18, uv, Docker Compose, Node and npm are the supported tools. Run the commands from the repository root unless a step changes directories.

1. Install the Python project and its development dependencies with `uv sync --locked --extra dev`. Copy `.env.example` to a private `.env` on a fresh checkout. Keep an existing configuration if one is already present.
2. Set a private `POSTGRES_PASSWORD`. Build `MIGRATION_DATABASE_URL` for the migration login at host `db` and `DATABASE_URL` for the host-side tools at `localhost`. Set `APP_READ_WRITE_PASSWORD` and `API_DATABASE_URL` for the separate `app_read_write` login at `db`. Percent-encode the password portion of each URL. Set `API_LOCAL_SESSION_ALLOWED_ORIGINS` to an HTTPS origin for a production-mode API. The local development alternative below uses the host API with a loopback browser origin. [Configuration template](../../.env.example)
3. Start the local database and migrate it. The default local override binds the database to loopback. The base Compose file publishes no host ports.

   ```sh
   docker compose up -d db
   docker compose --profile tools run --rm migrate
   ```

4. Export the host-side `DATABASE_URL` to the shell running the bootstrap command. On an empty database run `uv run python scripts/bootstrap_admin.py --login-name admin --display-name "Platform Administrator"`. Keep the one-time activation token private. Once the portal is running, open `http://localhost:5173/activate#token=<activation-token>` in your own browser and set the first password. On an existing instance use an existing account or follow [administrator recovery](PLATFORM_ADMINISTRATOR_RECOVERY.md).
5. For local portal development, set `DND_AI_LOCAL_SESSION_ALLOWED_ORIGINS=http://localhost:5173` for the host API and run `uv run uvicorn dnd_ai.api.app:app --host 127.0.0.1 --port 8000`. In a second terminal run the following commands.

   ```sh
   cd portal
   npm ci
   npm run dev
   ```

6. Open `http://localhost:5173`, activate the account and sign in. Vite sends `/auth/*` to the API unchanged and strips the leading `/api` from other proxied calls. On the API, `/healthz` checks process liveness and `/readyz` checks database connectivity. [Create a world and run a session](../tutorials/first-campaign.md)

To run the containerized API, use the runtime-role setup, production origin and secret requirements in the [Compose instructions](../DEVELOPMENT.md#36-self-hosted-docker-compose). Stop local services with `docker compose down` to retain the named volume. [Backup and restore](DATABASE_RECOVERY.md)
