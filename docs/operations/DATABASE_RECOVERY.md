# Database Recovery Operations

> **Status: accepted production deliverable.** The recovery
> implementation completed its final production review at commit `f0572d0`.
> Further speculative review is not an acceptance gate. Validate it in
> operation with periodic disposable backup -> restore -> verify drills and
> reopen implementation work only for an observed failure, a topology change,
> or a PostgreSQL/Compose major-version change. A drill should include
> operator-supplied business-data counts or checksums; archive readability and
> schema verification alone cannot prove that a backup contains the intended
> business data.

Authoritative operator reference for backup, restore, role bootstrap,
verification, and teardown against the self-hosted Docker Compose
topology, via **`scripts/operations/database_recovery.py`**. See
[DEVELOPMENT.md §3.6](../DEVELOPMENT.md#36-self-hosted-docker-compose) for
everyday `compose.yaml` setup (start/stop, configuration variables, running
migrations) — this document covers recovery specifically and is the one
place full command invocations live; `DEVELOPMENT.md` links here rather
than duplicating them.

Run `uv run python scripts/operations/database_recovery.py <command> --help`
for the full flag reference at any time; every example below is a
complete, runnable invocation. The script is cross-platform (Python 3.12,
run the same way from Bash or PowerShell), so this document shows one
command block per operation rather than duplicated Bash/PowerShell copies
— that duplication is exactly what caused flags, environment files, image
overrides, and variable names to drift in past revisions of this project's
recovery documentation. A few procedures below (the drill, and the
major-version experiment/cutover) need a uniquely generated project name;
those show both a Bash and a PowerShell block for *generating* the name,
since the two shells' variable syntax genuinely differs, but only one
command block afterward, in Bash style (`$DND_TEST_PROJECT` and similar);
PowerShell users substitute their own variable from the block above (e.g.
`$DndTestProject`) everywhere the Bash block references it.

## Safety model

This is not a single "read-only" claim — the script distinguishes three
levels, and no command in it silently crosses from a lower level to a
higher one:

- **static** — argument/placeholder/path validation and Compose
  configuration rendering (`docker compose config`). No container needs to
  be running; nothing is created. `preflight --level static` exposes
  exactly this.
- **docker-ephemeral** — may run `docker compose exec`/`cp` against an
  **already-running** `db` container (creates no new container), and, for
  the migration-target check specifically (preflight, `restore --mode
  fresh`, `bootstrap-roles` — never `verify`), creates a genuinely **new**
  one-off `migrate` container via `docker compose run --rm` (see "Required
  preparation" below for why the preflight one never triggers a build
  silently). `verify` never creates any new container — see below. None of
  this creates, drops, or alters any PostgreSQL database, role, or volume.
  `preflight --level docker` (the default) runs both levels.
- **destructive** — force-drops/recreates a database, runs real
  migrations, restores a dump, or `down -v`s a project. Always gated
  behind an explicit `--confirm-*` flag, checked **before any subprocess
  runs** — static or docker-ephemeral — so a missing flag leaves
  everything, including Docker-side state, untouched.

`verify` performs no PostgreSQL state mutation, unconditionally — it has no
`--confirm-*` flag and never runs migrations, and **every check it runs
stays within the one, explicitly selected `--project`/`--compose-file` and
its running `db` service**, via `docker compose exec db psql`: the
cluster-wide role check queries that cluster's always-present `postgres`
maintenance database, because role definitions are cluster-wide, not
per-database (see `check_roles`); every application-database check —
ownership, extensions, structural counts, the migration-head check, and
operator `--check` queries — queries `--db-name`. `verify` never consults
`MIGRATION_DATABASE_URL` and never touches the `migrate` service, another
Compose project, or an external database, for any check — a stale,
mistargeted, or even externally-pointed `MIGRATION_DATABASE_URL` cannot
make any part of `verify` inspect a different database than the rest of
it.

**Its Alembic check does not shell out to `alembic current
--check-heads`.** That command loads this repository's own
`database/migrations/env.py`, whose `run_migrations_online()`
unconditionally executes and commits `CREATE SCHEMA IF NOT EXISTS core;`
before running any migration — genuine, project-specific mutation that
Alembic's own `dont_mutate=True` (which only constrains Alembic's internal
version-table bookkeeping) does **not** suppress, so `alembic current
--check-heads` is not actually a pure read against *this* project. Instead,
`verify` computes the repository's head and known-revision sets **entirely
locally, in-process** via Alembic's `ScriptDirectory` API (parses the
migration scripts on disk — no subprocess, no container, no database
connection at all) and reads the **selected database's** revisions with a
single fixed `SELECT ... json_agg(version_num) ...` query against
`core.alembic_version`, over the same `db` container `exec`, with
PostgreSQL's own `default_transaction_read_only=on` set for that session —
the JSON result is parsed exactly, preserving duplicates and rejecting
anything malformed, rather than collapsed into a set that could hide a
corrupted `core.alembic_version` — see "Verification" below for the full
mechanism.

`restore` and `bootstrap-roles` run their static and docker-ephemeral
checks — their **preflight** — before doing anything destructive, and
refuse to continue, without touching the target application database,
role, or volume, if any of those checks fails. **That is the guarantee
this script makes: not "nothing happens," but "no PostgreSQL state
changes, and no destructive step runs, until every preflight check has
passed."** Preflight itself is not silent, either — it prints what it's
about to do before running the docker-ephemeral checks, and the
`preflight` command exposes the same checks standalone, for inspection
independent of any mutation.

### Required preparation: build the `migrate` image first

`docker compose run --rm migrate ...` builds the `migrate` image
implicitly if it's missing from the local Docker cache (confirmed live
against installed Compose v5.3.1 — no flag in that version suppresses
this). That is fine for an actual migration run, but not for a *preflight*
check that is supposed to be cheap and side-effect-free: this script's
migration-target verification (`verify_migration_target`, used by
`restore --mode fresh`, `bootstrap-roles`, and
`preflight --for restore-fresh|bootstrap-roles`) always checks whether the
image already exists first (`docker image inspect`), and refuses to run
the check — reporting a clear failure with the exact build command —
rather than let a Docker build happen as a side effect of a safety check.

Build it deliberately, once, before running any of the commands above:

```bash
docker compose --env-file <your-env-file> -p <your-project> -f compose.yaml --profile tools build migrate
```

This is a genuinely network-dependent, potentially slow operation (image
layers may need pulling), which is exactly why it's never triggered
implicitly by a check. The *actual* migration steps inside `restore`'s and
`bootstrap-roles`' destructive phase (running real migrations, not just
checking a connection) are not gated behind this — building there is
normal, expected recovery behavior, not a preflight surprise.

### Port isolation

`restore`, `bootstrap-roles`, and `preflight` all fail by default if the
rendered Compose configuration would publish a host port for `db` — the
base self-hosted topology (`compose.yaml` alone, with no
`compose.override.yaml`) publishes none, and an unexpected published port
during a recovery workflow is exactly the kind of drift preflight exists
to catch. Pass `--allow-published-db-port` to acknowledge a deliberate
exception (e.g. testing against a local-dev topology that includes
`compose.override.yaml`'s loopback-only port); the acknowledged binding is
then printed (host IP, host port, container port — never anything secret).
**A binding to all interfaces (`0.0.0.0`/`::`), not just loopback, is
still reported loudly even when acknowledged** — it is never silently
folded into an ordinary pass. Every example in this document below uses
`compose.yaml` alone, so none of them need this flag.

## Concepts and state boundaries

**What a `pg_dump` backup does *not* cover.** `pg_dump` captures exactly one database's schemas, tables, data, and the grants recorded inside that database — nothing that lives outside it. PostgreSQL roles (`CREATE ROLE ...`) are **cluster-wide**, not database-local: they live in the cluster's shared catalog rather than inside any one database, so `pg_dump -d dnd_ai` never includes them. This project's six roles — `migration_owner`, `migration_runner`, `app_read_write`, `app_read_only`, `integration_worker`, `admin_maintenance` — are created once, cluster-wide, by the `001_bootstrap` Alembic revision ([DATABASE_CONVENTIONS.md §27.1](../DATABASE_CONVENTIONS.md#271-database-roles)), and every schema object and default privilege throughout the database is owned by, or granted to, one of them. **A `dnd_ai.dump` file by itself is not a complete recovery artifact for a brand-new PostgreSQL cluster** — restoring it onto a fresh server with no roles yet created fails as soon as `pg_restore` reaches the first statement referencing `migration_owner` or any of the other five.

The repository-native fix is to let Alembic recreate the roles before restoring data — the same `001_bootstrap` revision that created them on the original server, applied to the fresh one. `restore` (below) does this for you, in the right order for whichever of fresh-cluster or existing-cluster mode applies. (`pg_dumpall --globals-only` is a built-in alternative for capturing roles; it's discussed, and why it isn't the default recommendation here, further down.)

**What role bootstrap does *not* recover.** Recreating the six *role definitions* — and the grants/ownership `001_bootstrap` assigns to them — is not the same as reproducing everything about the roles' live state on the server you backed up from:

- **`pg_dump` never includes cluster roles at all** — not their existence, not their passwords, not their attributes.
- **Alembic recreates the repository-defined roles and grants**, exactly as `001_bootstrap` defines them. That's schema-level structure, not credentials.
- **Not recovered by either the dump or the migration**: any password set on a login role after `001_bootstrap` created it, credentials issued by an external identity system, role memberships added by hand after bootstrap, `ALTER ROLE ... SET` session defaults, or any other post-deployment role change.
- **After restoring onto a new cluster, rotate or reapply runtime credentials yourself**, as a deliberate step — from your deployment's own secret-management process, never the dump file, this documentation, or the repository. `restore` (below) prints a reminder of this at the end; it does not and cannot do it for you.
- The bootstrap superuser (`POSTGRES_USER`, `postgres` by default) is for this recovery tooling and the `migrate` job only — never for `src/dnd_ai/api`. `api` must connect as `app_read_write` and nothing else; this is enforced twice, not merely documented: `compose.yaml` requires a separate `API_DATABASE_URL` with no fallback default, and `dnd_ai.config.Settings`/`dnd_ai.api.deps.verify_database_identity` refuse to start the process at all — checking both the configured URL's identity and the live connection's `session_user`/`current_user` — if it is ever pointed at `postgres`, `migration_runner`, or `migration_owner` ([DATABASE_CONVENTIONS.md §27.1](../DATABASE_CONVENTIONS.md#271-database-roles)).

Do not "solve" any of the above by indiscriminately restoring a `pg_dumpall --globals-only` capture — see why, further down.

**What dropping and recreating the database loses.** Recreating the target database is deliberate — it guarantees a clean target for `pg_restore` — but "roles survive it" is not the same claim as "everything is fine afterward." Three categories of state behave three different ways:

- **Cluster-wide state survives untouched**: the six roles, their attributes, and role-to-role memberships all live in the cluster's shared catalog, not any one database.
- **Database-local state is restored by `pg_restore`** from the dump: schema/table ownership, `ALTER DEFAULT PRIVILEGES` entries, schema- and table-level grants, and installed extensions.
- **One piece of database-local state is restored by neither, and must be reapplied explicitly**: `001_bootstrap` also runs `GRANT CREATE ON DATABASE <db> TO migration_owner` — a privilege on the *database object itself*, recorded in `pg_database.datacl`, not on anything inside it. A plain `pg_dump -Fc` (no `--create`) never captures this. Missing it doesn't fail loudly — a recovered deployment can look completely fine until a later migration needs `CREATE EXTENSION`, and only then fails with a permission error. **`restore` reapplies this grant automatically**, immediately after recreating the database and before restoring the dump, using the same safe psql-variable/`\gexec` mechanism documented in `_grant_create_on_database`'s docstring in the script itself — never raw string interpolation of the database name into SQL. `verify` checks for it directly afterward.

**Confirm the project before doing anything destructive.** `database_recovery.py` never guesses or defaults a project name — but you still have to know it. Compose defaults `COMPOSE_PROJECT_NAME` to the containing directory's name unless a deployment sets it explicitly:

```bash
docker compose -p "<your-project>" -f compose.yaml ps
```

If that doesn't show the deployment you intend to act on, stop — confirm the right project name before continuing. `-f compose.yaml` only (no other `-f`, and no auto-loaded `compose.override.yaml`) means this, and every command below, never publishes a host port.

The `db` service's health check (`pg_isready`) deliberately targets the always-present `postgres` maintenance database, not the application database — see `compose.yaml`'s `healthcheck:` comment. That matters here specifically because restoring drops and recreates the application database: a health check pointed at it would either hold a connection that blocks the drop, or report the container unhealthy for the window between drop and recreate.

## Backup

Dumps a database to a host file, cleaning up its own temporary in-container copy:

```bash
uv run python scripts/operations/database_recovery.py backup \
  --project "<your-project>" \
  --env-file .env \
  --compose-file compose.yaml \
  --db-user postgres \
  --db-name dnd_ai \
  --output "./dnd_ai-$(date +%Y%m%d).dump"
```

`-Fc` (custom format, compressed) is always used — it's the only format `restore`/`validate-archive` accept. The result is an ordinary host file, not scoped to any Compose project: back it up like any other file (off-host copy, versioned storage, whatever your deployment needs), and reuse it with the drill or a real restore below. Per "Concepts" above, it's a **database-only** artifact — recovering onto a brand-new cluster also needs the role-recreation step built into `restore`. Pass `--overwrite` to replace an existing output file; without it, `backup` refuses to clobber one, and it also refuses if `--output`'s parent directory doesn't already exist (it never creates one implicitly) or if `--output` resolves to a config file already in use. If `pg_dump` and the host copy both succeed but removing the in-container temporary copy afterward fails, `backup` still exits 0 (the dump was captured successfully) but prints an explicit `backup succeeded WITH CLEANUP WARNING` message naming the leftover container path — never an unconditional "complete" message that would hide that.

**To validate an existing archive without restoring it**, run `validate-archive`:

```bash
uv run python scripts/operations/database_recovery.py validate-archive \
  --project "<your-project>" \
  --env-file .env \
  --compose-file compose.yaml \
  --dump-file ./dnd_ai-20260811.dump
```

This runs two checks, in order. **First, a static, local, host-side check**: the file must begin with the PostgreSQL custom-format signature — the 5-byte string `PGDMP` that `pg_dump -Fc` always writes as its first bytes. No Docker container is involved yet, and a file that doesn't have this signature (a plain-text `-Fp` dump, a tar-format `-Ft` dump, or an unrelated file) is rejected immediately. This step exists because `pg_restore --list` succeeding is **not** by itself proof of custom format — it can also read tar-format archives — so this tool checks the signature itself rather than inferring format from what `pg_restore` happens to accept. **Only once that passes** does the **docker-ephemeral** step run: it requires the `db` container to already be running (only for its PostgreSQL client toolchain, not a live database), and it temporarily modifies that container's filesystem — copying the archive to a uniquely named temporary path, running `pg_restore --list` against it, and always attempting to remove the copy afterward. It never connects to PostgreSQL, never creates or drops a database. If removing the temporary copy fails, the check is reported as **failed** (not a warning) and the file is left in place for inspection, so a caller stops rather than proceeding with an uninspected stray file. Together, the two checks prove the archive is specifically a well-formed, readable PostgreSQL **custom-format** dump with inspectable contents — not just something `pg_restore` happens to be able to read — and still **not** semantic compatibility with any particular application/schema version. It's the same check `restore` runs during its own preflight, exposed standalone.

## Fresh-cluster restore

Use this when standing up a **brand-new PostgreSQL cluster** — a new self-hosted deployment, an isolated restore drill, or a project-wide-adopted major-version cutover (below). There is no existing application database to protect; the one PostgreSQL's container init creates from `POSTGRES_DB` is disposable, and `restore --mode fresh` treats it that way. **Build the `migrate` image first** (see "Required preparation" above) — the preflight steps below refuse to trigger that build for you.

```bash
docker compose -p "<your-project>" -f compose.yaml up -d --wait db

uv run python scripts/operations/database_recovery.py restore \
  --project "<your-project>" \
  --env-file .env \
  --compose-file compose.yaml \
  --db-user postgres \
  --db-name dnd_ai \
  --dump-file ./dnd_ai-20260811.dump \
  --mode fresh \
  --confirm-drop \
  --confirm-restore
```

In fresh-cluster mode, `restore` runs its preflight — static and docker-ephemeral checks, no PostgreSQL state mutation — before touching anything: both `--confirm-drop`/`--confirm-restore` are checked first (before any subprocess at all — a missing flag means literally nothing has run, Docker-side or otherwise), then Compose configuration rendering, port-isolation, server reachability, `--dump-file` archive validation (`pg_restore --list` against a temporary in-container copy), the `migrate` image's presence (refusing to trigger a build if absent), and an *active* check — a live connection through the `migrate` service's own configuration, in a genuinely new one-off container, not a guess — confirming `MIGRATION_DATABASE_URL` really targets this database. Only once every one of those passes does it print `PREFLIGHT PASSED — beginning destructive recovery` and start the **destructive** phase:

1. Runs the `migrate` service directly against the database that PostgreSQL's own container init already created — this **is** the "temporary/bootstrap application database": on a genuinely fresh cluster it holds nothing yet, so migrating it to create the six roles, extensions, schemas, and current schema objects costs nothing. (This is the first destructive step, and it only runs after every preflight check above — including both confirmation flags — has already passed.)
2. Verifies all six roles exist (via the `postgres` maintenance database), stopping — without dropping anything — if they don't.
3. Force-drops and recreates that same database, reapplies the `CREATE ON DATABASE` grant `dropdb`/`createdb` just discarded, and restores your dump into it.

Run `preflight --for restore-fresh --dump-file <dump>` (plus the same `--project`/`--env-file`/`--compose-file`/`--db-user`/`--db-name`) any time to see exactly these static/docker-ephemeral checks — and only these — without restoring anything; add `--level static` to skip the docker-ephemeral checks entirely and confirm no container needs to be running at all.

**Restoring a dump created by a newer application/schema revision into an older application image is unsupported** — make sure the `migrate` image you're running already knows about the dump's revision (or later) before proceeding.

After it finishes: reapply or rotate runtime credentials for `migration_runner`/`app_read_write`/`app_read_only`/`integration_worker`/`admin_maintenance` with `set-role-password` (below) — `restore` prints this reminder; it can't do it for you, since it never accepts or stores a password itself (see "What role bootstrap does not recover" above and "Provisioning application-role credentials" below) — then run `verify` (below) before treating the deployment as authoritative.

## Existing-cluster restore

Use this when the **cluster itself survives** but the application database is gone, corrupt, or otherwise unusable — an ordinary in-place recovery, not a new cluster. The key difference from fresh-cluster mode: migrations must never be asked to connect to a database that might not exist or might be the thing that's broken, and this preflight is built so it structurally cannot — it never tries to connect to a possibly-corrupt target before recreating it.

**Quiesce every other consumer first** — `dropdb --force` (step below) disconnects anything still connected, and discovering what was still connected *while* it happens is worse than confirming there's nothing left beforehand. Stop the `api` service (`docker compose stop api`), any background worker/Discord/FoundryVTT adapters once they exist as committed services (per [DEVELOPMENT.md §2](../DEVELOPMENT.md#2-repository-layout)), and close any interactive `psql`/GUI session or scheduled job connected to the target database. Re-confirm the project immediately before continuing:

```bash
docker compose -p "<your-project>" -f compose.yaml ps
```

```bash
uv run python scripts/operations/database_recovery.py restore \
  --project "<your-project>" \
  --env-file .env \
  --compose-file compose.yaml \
  --db-user postgres \
  --db-name dnd_ai \
  --dump-file ./dnd_ai-20260811.dump \
  --mode existing \
  --confirm-drop \
  --confirm-restore
```

In existing-cluster mode, preflight is the same as fresh-cluster mode (both confirmation flags checked first, then Compose configuration, port isolation, server reachability, and `--dump-file` archive validation) with one deliberate difference: **it verifies the six roles against the `postgres` maintenance database, without ever connecting to the (possibly missing or corrupt) target database itself.** If all six check out, `PREFLIGHT PASSED` prints and it proceeds straight to force-drop/recreate/regrant/restore, exactly as above, with no Alembic connection to the damaged database required beforehand. If any role or the `migration_runner` → `migration_owner` membership is missing, `restore` stops at preflight and does not touch the target database at all — migrations normally target an application database, and they cannot bootstrap roles through a database that doesn't yet exist or isn't reachable. Run `preflight --for restore-existing --dump-file <dump>` to see exactly this, standalone.

**If roles are missing, bootstrap them into a deliberately named temporary database first** — never the real recovery target, so a partially-migrated attempt never overloads or gets confused with it:

```bash
cat > .env.bootstrap <<'EOF'
POSTGRES_USER=postgres
POSTGRES_PASSWORD=<the same password this cluster's real POSTGRES_USER already has>
POSTGRES_DB=dnd_ai
MIGRATION_DATABASE_URL=postgresql+psycopg://postgres:<the same password>@db:5432/dnd_ai_bootstrap_tmp
EOF
```

```powershell
$envContent = @"
POSTGRES_USER=postgres
POSTGRES_PASSWORD=<the same password this cluster's real POSTGRES_USER already has>
POSTGRES_DB=dnd_ai
MIGRATION_DATABASE_URL=postgresql+psycopg://postgres:<the same password>@db:5432/dnd_ai_bootstrap_tmp
"@
[System.IO.File]::WriteAllText("$PWD\.env.bootstrap", $envContent, [System.Text.UTF8Encoding]::new($false))
```

Note the URL's database name — `dnd_ai_bootstrap_tmp`, not the real target — is the only thing that needs to differ from your real deployment's own connection details; `POSTGRES_USER`/`POSTGRES_PASSWORD` are this cluster's actual superuser credentials, because bootstrap-roles is creating roles on your **real** cluster, just inside a throwaway database on it. `.env.bootstrap` is not committed (`.gitignore`'s `.env.*` pattern covers it); remove it once you're done, the same as any other short-lived credential file.

```bash
uv run python scripts/operations/database_recovery.py bootstrap-roles \
  --project "<your-project>" \
  --env-file .env.bootstrap \
  --compose-file compose.yaml \
  --connect-user postgres \
  --temp-db-name dnd_ai_bootstrap_tmp \
  --protect-db-name dnd_ai \
  --confirm-env-targets-temp-db
```

`bootstrap-roles`' own preflight (static + docker-ephemeral, before anything destructive) checks Compose configuration, port isolation, server reachability, that the temporary database doesn't already exist, and that the `migrate` image is already built. Once that passes, it creates `dnd_ai_bootstrap_tmp` — the temporary database itself has to exist before the active target check below can run, which is why creating it comes first — then **actively verifies**, by connecting through the `migrate` service's own configuration and comparing `current_database()`/`current_user()`, that `MIGRATION_DATABASE_URL` really does target it before running any real migration. `--protect-db-name` is a safety guard: `bootstrap-roles` refuses to run if `--temp-db-name` equals it. `--confirm-env-targets-temp-db` is a required acknowledgment that `.env.bootstrap`'s `MIGRATION_DATABASE_URL` is *intended* to point at the temporary database — the script still never opens that file to check for you, but it no longer merely trusts the flag either: if the active check finds `MIGRATION_DATABASE_URL` actually points somewhere else (the real recovery target, for instance), migrations are never run, the temporary database is dropped again, and the command exits nonzero explaining the mismatch. If role verification fails after migrating (a different, later failure), the temporary database is left in place for inspection rather than silently dropped, and the command distinguishes "bootstrap succeeded, cleanup failed, temporary database remains" (still exits nonzero — operator intervention is required) from an outright failure in its final message.

**`preflight --for bootstrap-roles` cannot run this active check** — the temporary database doesn't exist yet when `preflight` runs standalone, so there is nothing to connect to. It instead confirms the temporary name is syntactically safe, reserved-name-clean, and **not already in use — a database already existing under that name is a hard preflight failure**, since `bootstrap-roles` itself will refuse to reuse it, and a failed existence query is reported and hard-fails distinctly from "confirmed absent" rather than being treated as if the database were absent. `preflight` explicitly says in its output that it cannot perform the same battery `bootstrap-roles` itself does, rather than implying parity.

Once roles are confirmed, re-run the `restore --mode existing` command above — it will now find all six roles and proceed. After it finishes, reapply/rotate runtime credentials and run `verify`, the same as fresh-cluster mode.

## Provisioning application-role credentials

`001_bootstrap` creates all five LOGIN roles (`migration_runner`, `app_read_write`, `app_read_only`, `integration_worker`, `admin_maintenance`) with **no password** — password authentication is refused until one is set. `bootstrap-roles`/`restore` only ever prove the roles exist with the right attributes; neither one, and no other command in this script, ever accepts, stores, or prints a password on your behalf (this module's own docstring: "This script never reads or prints POSTGRES_PASSWORD ... or any other credential"). `set-role-password` is the one command that does, and it is required — not optional — before anything connects as the role it targets. In particular: **`docker compose up -d api` must never run before `set-role-password --role app_read_write` has succeeded** — `api` always connects to PostgreSQL as `app_read_write` (`compose.yaml`'s own comment on that service), never `postgres`/`migration_runner`/`migration_owner`, and there is no Compose-native ordering guarantee for a step external to Compose entirely, the same limitation that already made `migrate` (a `profiles: ["tools"]` one-off job) a manual, documented first step rather than something `depends_on` could express.

```bash
export APP_READ_WRITE_PASSWORD=<a real value>   # a shell export, never a file this repo tracks
uv run python scripts/operations/database_recovery.py set-role-password \
  --role app_read_write \
  --password-env-var APP_READ_WRITE_PASSWORD \
  --project "<your-project>" \
  --env-file .env \
  --compose-file compose.yaml
```

The password is read from `--password-env-var` (a variable already set in *this* process's own environment) or `--password-file` (a mounted secret) — never accepted as a `--password` flag, which would put it in `ps`/`docker top`/shell history for as long as the process ran. It reaches PostgreSQL only inside the STDIN payload of a piped `psql ALTER ROLE ...` statement, escaped as a SQL string literal in-process (`_pg_string_literal` — doubling embedded quotes is the standard SQL mechanism, not a project-specific one) — never a command-line argument, never printed by this script, by `run()`'s own argv-only diagnostic line, or by Compose. `--role` accepts only the five real LOGIN roles (`argparse`'s own `choices=`); `migration_owner` is not a valid choice at all — it is `NOLOGIN` by design (§27.1) and a password on it would be meaningless.

This mutates exactly one role's credential and nothing else, so — unlike `restore`/`bootstrap-roles` — it carries no `--confirm-*` gate. It is fully idempotent: rerun it any time, with a new value, to rotate that role's password without touching any other role's — migration and application credentials stay independently rotatable because they are always two separate roles with two separate passwords, never a shared one.

**Confirm it actually took before starting anything that depends on it:**

```bash
uv run python scripts/operations/database_recovery.py verify-roles \
  --project "<your-project>" --env-file .env --compose-file compose.yaml
```

`verify-roles`' report (via `check_roles`) now includes one line per LOGIN role reading `[PASS] role app_read_write password: password set` or `[WARN] role app_read_write password: NO PASSWORD SET — ...`. It is deliberately a `WARN`, not a hard failure that would flip the command's exit code — `bootstrap-roles` calls this same check immediately after creating fresh roles, before any operator has had a chance to run `set-role-password` yet, and a hard failure there would break that already-working flow. Read the report itself, not just the exit code: a `WARN` line here after you believe the full `migrate` → `set-role-password` → `up -d api` sequence has completed means it has not, and `api` will be unable to authenticate at all until it is fixed.

Once you build `API_DATABASE_URL` from the new password (percent-encoded — the same rule `MIGRATION_DATABASE_URL` already follows, see `.env.example`) and set it in `.env`, `docker compose up -d api` is safe to run.

## Verification

Run this after any restore, before treating a deployment as authoritative:

```bash
uv run python scripts/operations/database_recovery.py verify \
  --project "<your-project>" \
  --env-file .env \
  --compose-file compose.yaml \
  --db-user postgres \
  --db-name dnd_ai \
  --check "SELECT count(*) FROM core.worlds" "3"
```

`verify` runs the complete acceptance battery in one command — nothing here is left as "adapt the query yourself". **It performs no PostgreSQL state mutation, unconditionally**: there is no `--confirm-*` flag, and every check below, including the Alembic head check, only reads.

- **Role verification**, repeated as part of acceptance (all six roles, correct LOGIN/NOLOGIN, `migration_runner` membership).
- **`migration_owner`'s `CREATE ON DATABASE` privilege** — direct, sufficient proof by itself; nothing else in this battery needs to attempt creating anything to re-confirm it.
- **Ownership**, one focused query per object kind so a defect in one kind can't hide behind another: schemas, tables/sequences/views/matviews, functions/procedures, domains/enums. Each expects a single `migration_owner` owner (`public` and `pg_%` schemas excluded throughout — extension-owned objects there are expected, not a defect).
- **`core.alembic_version`'s exceptional owner**, checked against `--connect-role` (defaults to `--db-user`) **by name**, not folded into the grouped relation-ownership count above. Alembic creates its own bookkeeping table before `001_bootstrap` can `SET ROLE migration_owner`, and `001_bootstrap` deliberately grants that table's DML to `migration_owner` without transferring ownership — so this table is legitimately owned by whichever role connected and bootstrapped the database, which is configurable (`POSTGRES_USER`, or whatever role your deployment's migration URL actually connects as), not hardcoded to `postgres`. Any *other* owner appearing among the relations query above is a real defect, not this expected exception.
- **Required extensions** (`pgcrypto`, `pg_trgm`) — hard failure if missing. `btree_gist` is checked too but only as a warning if absent, since it's installed by a later revision (009) and its absence is expected on a database that predates it.
- **The explicitly selected database is at the repository's current migration head(s)** — but **not** via `alembic current --check-heads`, and **not** via `MIGRATION_DATABASE_URL` or the `migrate` service at all. That command loads this repository's own `database/migrations/env.py`, and `env.py`'s `run_migrations_online()` unconditionally executes and commits `CREATE SCHEMA IF NOT EXISTS core;` before running any migration (see `env.py`'s own comments — it exists so a brand-new database can be migrated from nothing). Alembic's `dont_mutate=True`, which the `current` command always runs with, only constrains **Alembic's own** version-table bookkeeping; it has no power over custom SQL a project's `env.py` chooses to run. So on a target with no `core` schema yet, `alembic current --check-heads` would itself create — and commit — that schema, which is exactly the kind of side effect a verification step must never have. `verify` therefore never invokes that command, or `env.py`, at all. Instead it:
  1. Computes the repository's head(s) **and** the full set of revision ids that exist anywhere in its migration history — **entirely locally, in this same process** via Alembic's `ScriptDirectory` API, which only parses `alembic.ini`'s `script_location` and the migration scripts on disk — no subprocess, no container, no `env.py`, no database connection whatsoever. A repository that somehow reports zero head revisions is itself a hard failure, checked before anything about the database is even queried.
  2. Checks `core.alembic_version` exists via `to_regclass()`, a pure catalog lookup that returns null rather than erroring, so a target missing `core` entirely is reported as its own clean, distinct failure rather than crashing or creating anything.
  3. Reads the **selected database's** revisions — the exact same `--project`/`--compose-file`/`--db-user`/`--db-name` every other check above already inspects, via the identical `docker compose exec db psql` mechanism, never a separate connection through the `migrate` service — with a single fixed query, `SELECT COALESCE(json_agg(version_num), '[]'::json) FROM core.alembic_version`, over a connection with PostgreSQL's own `default_transaction_read_only=on` set for the whole session (the same mechanism the `--check` queries below use), so the server itself — not this tool's care — would reject any write that connection ever attempted. This design specifically closes a gap an earlier revision of this check had: because the database-side query always goes through the same `--db-user`/`--db-name` as every other check, a stale or mistargeted `MIGRATION_DATABASE_URL` — even one pointing at a completely different server — can no longer make this one check silently inspect a different database than the rest of `verify`.
  4. Parses that JSON result **exactly** — every row preserved, in order, duplicates included — never a human-formatted psql table and never Alembic CLI output. Any element that isn't a non-empty, non-whitespace-padded string (covers SQL `NULL`, which `json_agg` renders as JSON `null`) is a hard failure. An empty result (`core.alembic_version` has no rows at all) is a hard failure, not treated as vacuously matching an empty repository head set — repository heads are already guaranteed nonempty by step 1, so zero/zero can never occur, but this is checked independently anyway. Duplicate rows are a hard failure, detected **before** any deduplicating conversion to a set — a corrupted `core.alembic_version` with the same revision recorded twice never silently collapses into "just one entry."
  5. Checks every database revision id is **known** to the repository's migration history (from step 1) — not merely a head, but anywhere in history — before comparing head sets at all. A revision id that doesn't exist anywhere in this repository is its own distinct hard failure ("unknown to this repository"), separate from an ordinary "behind head" mismatch (a real, historical revision that just isn't a current head).
  6. Only then compares the two head sets **exactly** — correctly supporting a legitimate single- or multiple-head repository. A database sitting at an older revision, one that has diverged across multiple heads, one referencing an unknown revision, one with duplicate or malformed rows, or one missing `core.alembic_version` altogether is caught correctly and makes this check fail, without ever mutating the target.

  Every failure this check can report is a short, fixed, classified message — never raw subprocess output or exception text — so a connection failure can never leak a connection string, password, env-file content, or raw Compose environment value into the result.
- **Structural table counts** — proves the expected schemas and tables exist. This is deliberately **not** the same claim as "the expected business data exists": a structurally valid deployment may legitimately contain zero rows in any given table (a brand-new deployment has zero worlds, and that's correct, not broken).
- **Your own data checks**, via repeatable `--check "<SELECT ...>" "<expected scalar>"` pairs — operator-controlled, and refused if a check isn't a single non-empty `SELECT`. **Read-only execution is enforced by PostgreSQL itself, not by that lexical check**: each `--check` query runs with `default_transaction_read_only=on` set for that one psql process, so a `SELECT` that calls a side-effecting function (confirmed against `SELECT lo_create(-1)`) fails with a server-side "cannot execute ... in a read-only transaction" error and is reported as a failed check — the lexical single-statement/`SELECT`-prefix requirement only rejects obviously wrong input before it reaches the server. This is how you verify the data you actually expect, rather than treating "nonzero" as a universal proxy for correctness. For a restore drill, record source-side counts (or checksums) before backing up, then pass them as `--check` expectations after restoring — comparing selected source and restored counts, not assuming either is right.

Any hard-failing check makes `verify` exit nonzero; `btree_gist`'s absence is reported but does not by itself fail the run.

**`verify` never runs a real migration, and does not offer an opt-in to run one.** An earlier revision of this tool had a `--confirm-migrate` flag that ran an actual `alembic upgrade head` as an end-to-end smoke test; it was removed because it added no acceptance value the head check above doesn't already cover — once the head check above confirms the database is genuinely at head, an `alembic upgrade head` run against that same database has nothing to apply and cannot exercise any code path the head check, the role checks, and the direct `CREATE ON DATABASE` privilege check don't already exercise. If you specifically want to exercise a real migration run as part of a recovery drill, that already happens for you: `restore --mode fresh` and `bootstrap-roles` both run one as part of their own destructive phase, before `verify` is ever invoked (see "Fresh-cluster restore" and "Existing-cluster restore" above).

## Isolated restore drill

**An untested backup is not a recovery plan.** Periodically run backup → restore → verify against a real dump, but inside a project that cannot be confused with, reach, or delete your real deployment — or an earlier or concurrently running drill — **and using its own disposable credentials, never your real `.env`.** Never reuse one fixed project name: a leftover container from an interrupted earlier drill, or a second drill running at the same time, would make that name's final teardown delete a project that isn't the one you just ran.

**Create a disposable environment file first.** Compose auto-loads `.env` from the working directory for variable substitution on every command that doesn't say otherwise; without a separate file, a drill would still interpolate credentials from your **real** deployment's `.env`. `--env-file` replaces `.env` entirely for the command it's given on, rather than merging with it (verified live: with `--env-file` set, values from a same-named variable in `.env` do not leak through), so giving the drill its own file closes that gap completely:

```bash
cat > .env.restore-test <<'EOF'
POSTGRES_USER=postgres
POSTGRES_PASSWORD=<a-fresh-disposable-password>
POSTGRES_DB=dnd_ai
MIGRATION_DATABASE_URL=postgresql+psycopg://postgres:<the-same-fresh-disposable-password>@db:5432/dnd_ai
EOF
```

PowerShell — **do not use `Set-Content -Encoding utf8`**: under Windows PowerShell 5.1 that writes a UTF-8 byte-order mark, which can become part of the first key in a dotenv file or behave inconsistently depending on the parser reading it. Write the file with `[System.IO.File]::WriteAllText` and an explicit BOM-less encoding instead — this behaves identically on Windows PowerShell 5.1 and PowerShell 7:

```powershell
$envContent = @"
POSTGRES_USER=postgres
POSTGRES_PASSWORD=<a-fresh-disposable-password>
POSTGRES_DB=dnd_ai
MIGRATION_DATABASE_URL=postgresql+psycopg://postgres:<the-same-fresh-disposable-password>@db:5432/dnd_ai
"@
[System.IO.File]::WriteAllText("$PWD\.env.restore-test", $envContent, [System.Text.UTF8Encoding]::new($false))
```

Generate an actual fresh password yourself — do not paste a real credential into it, and do not reuse your real deployment's password here either. Both placeholders must resolve to the exact same credential, percent-encoded in the URL if it contains characters special to URLs (`@ : / ? # [ ] %`). `.env.restore-test` is not committed (`.gitignore`'s `.env.*` pattern, `!.env.example` the one exception); remove it once the drill is done, the same as any other short-lived secret.

Generate a unique project name every time:

```bash
DND_TEST_PROJECT="dnd-ai-restore-test-$(date +%Y%m%d%H%M%S)-$$"
echo "$DND_TEST_PROJECT"
```

```powershell
$DndTestProject = "dnd-ai-restore-test-$(Get-Date -Format 'yyyyMMddHHmmss')-$([guid]::NewGuid().ToString('N').Substring(0,8))"
Write-Host $DndTestProject
```

Confirm nothing already exists under it, build the `migrate` image for this project, then run the drill — fresh-cluster mode, since a disposable project always starts from an empty volume — through the same commands as any fresh-cluster restore, pointed at the drill's project and environment file:

```bash
docker compose --env-file .env.restore-test -p "$DND_TEST_PROJECT" -f compose.yaml ps

docker compose --env-file .env.restore-test -p "$DND_TEST_PROJECT" -f compose.yaml up -d --wait db

docker compose --env-file .env.restore-test -p "$DND_TEST_PROJECT" -f compose.yaml --profile tools build migrate

uv run python scripts/operations/database_recovery.py restore \
  --project "$DND_TEST_PROJECT" \
  --env-file .env.restore-test \
  --compose-file compose.yaml \
  --db-user postgres \
  --db-name dnd_ai \
  --dump-file ./dnd_ai-20260811.dump \
  --mode fresh \
  --confirm-drop \
  --confirm-restore

uv run python scripts/operations/database_recovery.py verify \
  --project "$DND_TEST_PROJECT" \
  --env-file .env.restore-test \
  --compose-file compose.yaml \
  --db-user postgres \
  --db-name dnd_ai \
  --check "SELECT count(*) FROM core.worlds" "<the count you recorded on the source before backing up>"
```

`-f compose.yaml` only, so the drill never loads `compose.override.yaml` and never publishes a host port (no `--allow-published-db-port` needed). A throwaway project never has any other consumer connected to begin with, so existing-cluster mode's quiesce step is trivially satisfied here — this is exactly why the drill always uses fresh-cluster mode instead, rather than adding a second code path just for drills.

**If anything fails, or `verify` reports something unexpected, stop before tearing anything down.** Inspect the throwaway project — logs, an interactive `psql` session, whatever the failure calls for — a disposable project is exactly the thing it's safe to leave running while you investigate:

```bash
docker compose --env-file .env.restore-test -p "$DND_TEST_PROJECT" -f compose.yaml logs db
```

Do not script this drill with automatic teardown-on-exit — that would delete the evidence a failed drill exists to surface. Once you're done, whether the drill succeeded or you've finished investigating a failure, tear down deliberately and remove the disposable environment file:

```bash
uv run python scripts/operations/database_recovery.py teardown \
  --project "$DND_TEST_PROJECT" \
  --env-file .env.restore-test \
  --compose-file compose.yaml \
  --confirm-teardown

rm .env.restore-test
```

Compose derives container, network, and (because `compose.yaml`'s `dnd_ai_pgdata` volume has no explicit top-level `name:`) volume names from the project name, so each uniquely-named drill gets entirely separate resources; only the *base* image layers are shared (each project's `migrate` image is still built under its own project-qualified tag — see "Required preparation" above). Using the same host dump file for both the drill and a real recovery is fine — it's an ordinary file on the host filesystem, not scoped to any project.

## Restore — exceptional path: in place, over an existing database

Recreating the database (above) is the normal recovery path — prefer it whenever you can afford the brief downtime. Restoring **in place**, without dropping the database first, is for the narrower case where you specifically cannot recreate it (for example, other services depend on it staying up) and are willing to accept the limitations below. This path is deliberately **not** wired into `database_recovery.py restore` — it has different semantics (`--clean --if-exists` rather than force-drop/recreate) and different failure modes, and folding both into one command would make the common path's behavior less obvious. Confirm the target project first, the same as before anything destructive above:

```bash
docker compose -p "<your-project>" -f compose.yaml cp ./dnd_ai-20260811.dump db:/tmp/restore.dump
docker compose -p "<your-project>" -f compose.yaml exec -T db pg_restore -U postgres -d dnd_ai --clean --if-exists /tmp/restore.dump
docker compose -p "<your-project>" -f compose.yaml exec -T db rm /tmp/restore.dump
```

Because this path never drops the database, the `GRANT CREATE ON DATABASE ... TO migration_owner` privilege from the original bootstrap is untouched — the reapplication `restore` does above only matters after a drop/recreate cycle, not here.

**What `--clean` actually guarantees, precisely:** for each object the dump *contains*, `pg_restore --clean` emits a `DROP` for that object immediately before recreating it from the dump; `--if-exists` just silences the error when an object it expects to drop isn't there. That is narrower than "resets the database to match the dump":

- **Anything not represented in the dump is left alone.** A table, role grant, or other object created after the backup was taken is untouched, so an in-place restore can leave stale or unrelated state behind rather than reproducing a clean copy of the backed-up database.
- **It can fail outright, rather than silently succeeding**, when another session holds a lock on an object being dropped, the dump's objects are owned by a role that doesn't match what's currently in place, or a dependency isn't in the state `--clean`'s drop order expects.

Treat in-place `--clean --if-exists` restoration as an exceptional, break-glass procedure, not the default.

## Why `pg_dumpall --globals-only` is not the default recommendation

`pg_dumpall --globals-only` is PostgreSQL's built-in way to capture cluster-wide role definitions, and it would technically solve "the database dump doesn't include roles" too. It's deliberately not what this document leads with, because on a real (potentially shared) PostgreSQL cluster it captures more than this application's six roles: every role in the cluster, not just this project's; role **attributes and password hashes**, an unnecessary credential-hygiene risk to apply unreviewed; and it can silently change existing roles' attributes or passwords if applied blindly to a cluster that already has some of them.

If you need cluster-wide role parity for reasons beyond this project, treat `pg_dumpall --globals-only` output as sensitive, review it before applying, and scope it down rather than applying it wholesale. For this project specifically, `bootstrap-roles`/`restore` only ever create the exact six roles `001_bootstrap` defines, nothing from any other application on the cluster, and never touch a password hash.

## Current minor upgrades

**Upgrading the PostgreSQL minor version** (e.g. `18.4` → a later `18.x`) is a routine restart, because minor versions share an on-disk format: bump the tag in `compose.yaml`'s `db.image` and `docker compose -p "<your-project>" -f compose.yaml up -d db`, using the same project and the same volume.

## Future major-version adoption and cutover

**This repository currently supports PostgreSQL 18.x only** ([DATABASE_CONVENTIONS.md §2.1](../DATABASE_CONVENTIONS.md#21-supported-postgresql-version)). No PostgreSQL 19 (or any other major-version) production procedure is executable today — documenting how the *mechanics* of a future cutover would work is not the same as this project having adopted, verified, or supporting that version, and it hasn't. A future major must go through a reviewed, project-wide adoption change before any production use, exactly as described below. There are two genuinely different phases, and they must not be conflated:

**Phase A — before adoption: an isolated compatibility experiment, never a production target.** Before proposing the project-wide change in Phase B, you can check whether the new major version actually works against this schema and this migration history, using a disposable Compose project that can never become authoritative and is always torn down afterward. This is the only place `compose.pg-experiment-image.yaml` — a scratch, never-committed Compose override — is used:

```yaml
# compose.pg-experiment-image.yaml — scratch file, not committed
services:
  db:
    image: postgres:<candidate-version>   # never latest, never an unbounded major tag
```

```bash
DND_EXPERIMENT_PROJECT="dnd-ai-pg-experiment-$(date +%Y%m%d%H%M%S)-$$"

docker compose --env-file .env.pg-experiment -p "$DND_EXPERIMENT_PROJECT" -f compose.yaml -f compose.pg-experiment-image.yaml up -d --wait db

docker compose --env-file .env.pg-experiment -p "$DND_EXPERIMENT_PROJECT" -f compose.yaml -f compose.pg-experiment-image.yaml --profile tools build migrate

uv run python scripts/operations/database_recovery.py restore \
  --project "$DND_EXPERIMENT_PROJECT" \
  --env-file .env.pg-experiment \
  --compose-file compose.yaml \
  --compose-file compose.pg-experiment-image.yaml \
  --db-user postgres \
  --db-name dnd_ai \
  --dump-file ./dnd_ai-20260811.dump \
  --mode fresh \
  --confirm-drop \
  --confirm-restore

uv run python scripts/operations/database_recovery.py verify \
  --project "$DND_EXPERIMENT_PROJECT" \
  --env-file .env.pg-experiment \
  --compose-file compose.yaml \
  --compose-file compose.pg-experiment-image.yaml \
  --db-user postgres \
  --db-name dnd_ai
```

`.env.pg-experiment` is created the same BOM-free way as `.env.restore-test` above, with its own fresh disposable password — never a real deployment's. Every command carries **both** `-f compose.yaml` and `-f compose.pg-experiment-image.yaml`, and `--compose-file` passed twice to the script for the same reason: omitting the override lets Compose reconcile the service back to `compose.yaml`'s own currently-pinned image, silently testing the wrong version. Run the project's full compatibility pass here too — migrations, `tests/database`/`tests/scenario` pointed at this project's connection details, and this document's own procedures — then tear the experiment project down with `teardown --confirm-teardown` regardless of outcome. **Nothing from this phase is ever cut over to** — its only output is a decision (adopt or don't) and evidence to support it.

**Phase B — adoption: one reviewed change, applied before any real deployment moves.** Once Phase A's evidence supports it, bump the version pin in tracked configuration: `compose.yaml`'s `db.image` tag, CI's PostgreSQL service-container version, `REQUIRED_POSTGRES_MAJOR_VERSION` (`tests/conftest.py`), [DATABASE_CONVENTIONS.md §2.1](../DATABASE_CONVENTIONS.md#21-supported-postgresql-version) and any other version-policy text naming `18.x`, and the optional AWS path's RDS `postgres_version` pin (`terraform/modules/database`) if that path is in use — in one commit, verified by the full test/CI pass this change implies. **From this point on, `compose.yaml` alone, with no override, already targets the new major version** — that is what makes it "adopted," not a scratch file naming the same tag.

**Phase C — cutover of a real deployment, using tracked configuration directly.** Because Phase B already moved the real pin, standing up the new-version project needs **no image override at all** — it is an ordinary fresh-cluster restore into a newly named project, using plain `-f compose.yaml`:

```bash
DND_PROJECT_NEW="<your-project>-pg-new"

docker compose -p "$DND_PROJECT_NEW" -f compose.yaml up -d --wait db

docker compose --env-file .env.pg-new -p "$DND_PROJECT_NEW" -f compose.yaml --profile tools build migrate

uv run python scripts/operations/database_recovery.py restore \
  --project "$DND_PROJECT_NEW" \
  --env-file .env.pg-new \
  --compose-file compose.yaml \
  --db-user postgres \
  --db-name dnd_ai \
  --dump-file ./dnd_ai-20260811.dump \
  --mode fresh \
  --confirm-drop \
  --confirm-restore

uv run python scripts/operations/database_recovery.py verify \
  --project "$DND_PROJECT_NEW" \
  --env-file .env.pg-new \
  --compose-file compose.yaml \
  --db-user postgres \
  --db-name dnd_ai
```

A **new project name is still required** — Compose project names determine the named-volume namespace (see `compose.yaml`'s comment on `dnd_ai_pgdata` having no explicit top-level `name:`), so a project that already has a `dnd_ai_pgdata` volume keeps reusing exactly that volume regardless of which image tag it's pointed at, and the on-disk format is **not** compatible across major versions — PostgreSQL refuses to even start against a data directory from a different major version. The only way to guarantee a genuinely fresh data directory is a genuinely different project. `.env.pg-new` is created the same BOM-free way as `.env.restore-test` above, with its own fresh password for the new cluster; never reuse the real deployment's or the drill's credentials here. **The old deployment keeps its own `.env` and its own credentials, completely untouched by any of this.**

**A scratch image override is unnecessary for an ordinary cutover once Phase B has happened** — `compose.yaml` already names the adopted version. It remains available, narrowly, for a rare follow-up case: testing a *different patch image within the already-adopted major version* before bumping the tracked patch pin (for example, validating `19.5` ahead of `18.4` → `19.5`'s own tracked bump) — use it exactly as in Phase A, on a disposable, never-cutover project, never as a substitute for actually moving the tracked pin before a real cutover.

Inspect both volumes before cutover, confirming there are genuinely two, not one reused:

```bash
docker volume ls --filter "name=<your-project>_dnd_ai_pgdata"
docker volume ls --filter "name=${DND_PROJECT_NEW}_dnd_ai_pgdata"
```

**Cutover is not automatic — something concrete has to change, deliberately**, only once `verify` has fully passed against the new project:

- Whatever currently decides that the old project/`.env` is the one in use — a deployment script, a systemd unit, a process supervisor, a CI/CD job, or simply which `-p`/`--env-file` pair you type by habit — has to be updated to point at `$DND_PROJECT_NEW`/`.env.pg-new` instead.
- In practice that usually means promoting `.env.pg-new` into the deployment's real `.env` (backed by a real, retained secret-management process), not continuing to reference a file named after a one-off upgrade indefinitely.

**Only after the new project is confirmed live and stable does the old one get retired, and only deliberately** — using the **old** project's own configuration:

```bash
uv run python scripts/operations/database_recovery.py teardown \
  --project "<your-project>" \
  --env-file .env \
  --compose-file compose.yaml \
  --confirm-teardown
```

Consider keeping the old volume around for a rollback window rather than deleting it in the same session as cutover, if your recovery-time tolerance allows it.

`pg_upgrade` is a documented alternative that avoids a full dump/restore for a large database, at the cost of more manual steps than this repository's `compose.yaml` currently automates — it remains an advanced, unautomated alternative, not covered here.

## Cleanup and rollback

Every disposable environment file this document creates (`.env.restore-test`, `.env.pg-experiment`, `.env.pg-new`, `.env.bootstrap`) is `.gitignore`d by the `.env.*` pattern and contains a real, if throwaway, credential — remove each one once its procedure is done, the same as any other short-lived secret. `compose.pg-experiment-image.yaml` is likewise `.gitignore`d and scratch: remove it once the experiment project (Phase A) it was created for has been torn down. Neither file is ever load-bearing for a real, currently-authoritative deployment — Phase C's cutover uses `compose.yaml` directly, with nothing scratch left over to forget about.

If a `restore` or `bootstrap-roles` run fails partway through, it deliberately leaves evidence in place rather than cleaning up automatically — an in-container dump copy, a temporary bootstrap database, or (for `teardown`) nothing at all, since `teardown` only ever runs when you explicitly ask it to. Inspect the failure (`docker compose ... logs db`, an interactive `psql` session, whatever it calls for) before tearing anything down; only run `teardown --confirm-teardown` once you're done investigating, and only against the project the failure actually happened in.

### Exit-status summary

| Situation | Exit code | Meaning |
|---|---|---|
| Any hard preflight check fails | nonzero | Destructive phase never started; target application database untouched |
| `--confirm-drop`/`--confirm-restore`/`--confirm-teardown`/`--confirm-env-targets-temp-db` absent | nonzero | No subprocess ran at all |
| `backup`/`restore` succeeds but a non-essential cleanup step (removing an in-container temp file) fails afterward | **0**, with a printed `... succeeded WITH CLEANUP WARNING` message naming the leftover path | The primary operation's data is intact; a stray temp file needs manual removal |
| `bootstrap-roles` verifies roles successfully but cannot remove the temporary database afterward | nonzero, with a message distinguishing "bootstrap succeeded" from "cleanup failed, temporary database remains" | Operator intervention is required — the nonzero exit is deliberate here, unlike the backup/restore cleanup-warning case |
| `bootstrap-roles`/`restore -mode fresh` fails after role verification but before/during the destructive steps | nonzero, evidence preserved (temporary database, or a partially-migrated fresh-mode target) | Never auto-cleaned; inspect before retrying or tearing down |
| `verify`'s read-only migration-head check finds the database behind head, diverged across multiple heads, missing `core`/`core.alembic_version` entirely, or containing zero, duplicate, unknown, or malformed revision rows | nonzero | No migration ran, and nothing was created — `verify` never invokes `env.py`; re-run `restore`/`bootstrap-roles` or investigate the migration history instead |
| `preflight --for bootstrap-roles` finds the temporary database name already in use, or its existence query fails | nonzero (hard failure) | Distinguished from "confirmed absent" — a failed query is never treated as evidence of absence |
| `validate-archive`/`restore` preflight rejects a file that lacks the PostgreSQL custom-format ('PGDMP') signature | nonzero | Rejected locally, before any Docker operation; plain-text/tar-format archives are not accepted even if `pg_restore` could read them |
