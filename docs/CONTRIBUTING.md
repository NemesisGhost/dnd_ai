# Contributing

Onboarding for new contributors: getting a working environment, then the workflow for changing things.

**Start with §1.** Development runs against a local or Compose PostgreSQL 18 server, and `compose.yaml` defines the supported topology.

---

## Table of Contents

- [1. Local setup (start here)](#1-local-setup-start-here)
- [2. External API keys](#2-external-api-keys)
- [3. Changing application code](#3-changing-application-code)
- [4. Git workflow](#4-git-workflow)
- [5. Getting help](#5-getting-help)

---

## 1. Local setup (start here)

The repository contains the database, command/query layers, and FastAPI application. Verification records preserve completed delivery evidence.

Development runs against a **local or self-hosted PostgreSQL 18 server**. Nothing in this section needs an AWS account. The fastest path is `docker compose up -d db` — a native PostgreSQL install works too.

### 1.1 Required tools

| Tool | Version | Notes |
|---|---|---|
| Git | any | |
| **Docker** (recommended) or **PostgreSQL 18.x** natively | | `compose.yaml` provides PostgreSQL 18.4 with no local install; native install options per platform: [DEVELOPMENT.md §3.1](DEVELOPMENT.md#31-postgresql) |
| Python | 3.12+ | Pinned in [DEVELOPMENT.md §1](DEVELOPMENT.md#1-toolchain) |
| uv | latest | Dependency management — [install](https://docs.astral.sh/uv/getting-started/installation/) |

Recommended: VS Code or your preferred IDE. Node.js 18+ only if you start on the React UI, which has not begun.

**Use PostgreSQL 18, not whatever version is convenient.** A different major version can produce local results that disagree with CI.

### 1.2 Setup

The full walkthrough is [DEVELOPMENT.md §3](DEVELOPMENT.md#3-local-setup). The short version, with Docker:

```bash
cp .env.example .env
# edit .env: set POSTGRES_PASSWORD, MIGRATION_DATABASE_URL, and DATABASE_URL's
# password segments to match — required, no working defaults ship in this repo;
# see docs/DEVELOPMENT.md §3.6

docker compose up -d db           # PostgreSQL 18.4, no local install needed

uv sync
uv run alembic -c database/alembic.ini upgrade head
uv run pytest
```

Without Docker, install PostgreSQL 18 natively instead of the first step: `psql --version` must report 18.x, then `createdb -U postgres dnd_ai`.

The project's six database roles are created by the `001_bootstrap` migration, not by hand — that is what keeps your server in agreement with CI's containerized PostgreSQL.

### 1.3 Then read

Follow [CLAUDE.md §4](../CLAUDE.md#4-documentation-map-and-context-loading-policy): search [DOMAIN_MODEL.md](DOMAIN_MODEL.md) for the affected vocabulary, read the [DATABASE_CONVENTIONS.md](DATABASE_CONVENTIONS.md) sections governing the mechanisms you will change, and consult [architecture/SYSTEM_ARCHITECTURE.md §5](architecture/SYSTEM_ARCHITECTURE.md#5-layering) when application-layer placement is in scope.

---

## 2. External API keys

Needed only for the OpenAI and Discord integrations.

- **OpenAI**: the NPC-conversation and campaign-synthesis adapter (`src/dnd_ai/domain/ai_provider.py`, `OpenAiCompatibleProvider`) is implemented and calls the **OpenAI Chat Completions API** (`POST /chat/completions`, function-calling for structured output) — not the Responses API. The same class also serves a locally hosted, OpenAI-API-compatible model server (Ollama, vLLM, LM Studio, ...) by pointing it at that server's base URL instead; see `.env.example`'s "AI provider" section. Get a key at [platform.openai.com/api-keys](https://platform.openai.com/api-keys) — this is an OpenAI **Platform** key, billed per API call, not a ChatGPT subscription key.
- **Discord bot**: not implemented yet. [discord.com/developers/applications](https://discord.com/developers/applications) — create an application, add a bot, copy the token, application ID, and public key

Store them in your local environment or a host-mounted secret, not in source control. Never put a real key in `.env`, a `.tf` file, a seed file, or a commit.

---

## 3. Changing application code

```bash
uv run ruff format .
uv run ruff check . --fix
uv run mypy src
uv run pytest
```

All four must pass locally before opening a pull request, and CI must then go green against containerized PostgreSQL 18. CI is the merge gate, not the local result. If a green local run turns into a red CI run, treat it as a real defect or local/CI drift and investigate.

The full workflow — Alembic revision requirements, the three test layers, CI expectations — is [DEVELOPMENT.md §4–§8](DEVELOPMENT.md#4-database-and-migrations), and the definition of done is [§10](DEVELOPMENT.md#10-definition-of-done).

Before writing anything, confirm it fits the current architecture and check the eleven non-negotiable rules in [CLAUDE.md §5](../CLAUDE.md#5-non-negotiable-architectural-rules). If a task appears to require breaking one, stop and raise it rather than deviating quietly.

---

## 4. Git workflow

- Work on a feature branch; don't commit directly to `main`
- Commit messages explain what and why
- Review `git status` and `git diff` before every commit

**Never commit**: `terraform.tfvars`, `secrets.local.json`, `.env`, `*.tfstate`, `tfplan`, `.terraform/`

**Do commit**: `*.example` files, Terraform module code, `uv.lock`, documentation, scripts

Documentation is part of the change, not a follow-up. If a change introduces a new cross-cutting concept, update the relevant file under `docs/` in the same commit — these documents are meant to stay current rather than be reconciled later. All documentation belongs under `docs/`; only `README.md` and `CLAUDE.md` live at the repository root.

---

## 5. Getting help

| Question | Where |
|---|---|
| What does this term mean? | [DOMAIN_MODEL.md](DOMAIN_MODEL.md) |
| How should this table look? | [DATABASE_CONVENTIONS.md](DATABASE_CONVENTIONS.md) + [architecture/DATABASE_MODEL.md](architecture/DATABASE_MODEL.md) |
| Where does this code go? | [architecture/SYSTEM_ARCHITECTURE.md §5](architecture/SYSTEM_ARCHITECTURE.md#5-layering) |
| Which library or tool? | [DEVELOPMENT.md §1](DEVELOPMENT.md#1-toolchain) |
| Local database won't connect? | [DEVELOPMENT.md §3](DEVELOPMENT.md#3-local-setup) |
| Green locally, red in CI? | Check PostgreSQL major version, extensions, and environment differences first |
| Self-hosting with Docker? | [DEVELOPMENT.md §3.6](DEVELOPMENT.md#36-self-hosted-docker-compose) |
| How do I create/archive an entity? | [ENTITY_LIFECYCLE.md](ENTITY_LIFECYCLE.md) |

Still stuck: open an issue at [github.com/NemesisGhost/dnd_ai/issues](https://github.com/NemesisGhost/dnd_ai/issues) with what you tried, what you expected, what happened, and sanitized error output.

External references: [PostgreSQL](https://www.postgresql.org/docs/), [Alembic](https://alembic.sqlalchemy.org/), [SQLAlchemy](https://docs.sqlalchemy.org/).
