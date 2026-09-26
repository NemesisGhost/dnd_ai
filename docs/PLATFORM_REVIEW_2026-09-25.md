# Platform Review — 2026-09-25

A full-repository review of the D&D AI World Platform: documentation conformance,
database/server/UI implementation, test coverage, home-network deployment readiness,
a comparison against the *AI D&D Campaign Intelligence Platform* marketing and feature
proposal, and a feasibility analysis for a future hosted/paid branch.

- **Reviewed commit:** `ead1b3c` ("External testing set up"), branch `phase13e/phase13e-b`, working tree clean.
- **Out of scope by request:** `terraform/` implementation code (referenced only where it bears on hosting feasibility).
- **Relationship to other documents:** this is a point-in-time review, not an authoritative document.
  [PLAN.md](PLAN.md) remains the delivery-status source of truth;
  [architecture/DATABASE_MODEL.md](architecture/DATABASE_MODEL.md) remains authoritative for schema.
  Where this review disagrees with [PROJECT_STATUS.md](PROJECT_STATUS.md), the observations
  recorded here were re-run on the commit above and PROJECT_STATUS.md should be refreshed.

---

## 0. What was actually executed

Every number below came from a command run during this review, not from reading a document.
Docker Desktop was unavailable, so the Compose topology was verified by inspection only.

| Check | Command | Result |
|---|---|---|
| Python formatting | `uv run ruff format --check .` | **Pass** — 411 files already formatted |
| Python lint | `uv run ruff check .` | **Pass** — all checks passed |
| Python types (CI scope) | `uv run mypy src` | **Pass** — 118 source files |
| Python types (all scripts) | `uv run mypy scripts` | **Pass** — 7 source files |
| Full Python suite + coverage | `uv run pytest --cov=src/dnd_ai --cov-branch` | **Pass** — **4,480 passed**, 0 failed, 0 skipped, 10m47s |
| Python coverage (full suite) | same run | **97% statements / 88% branches / 96% combined** |
| Python coverage (`tests/unit` only) | `uv run pytest tests/unit --cov=src/dnd_ai` | 561 passed, **65% statements** |
| Portal suite + coverage | `npx vitest run --coverage` | **Pass** — 160 files, **1,034 tests** |
| Portal coverage | same run | **90.76% statements / 83.04% branches / 95.14% functions** |
| Portal lint | `npm run lint` | **Pass** |
| Portal build | `npm run build` | **Pass** — `tsc -b` + Vite bundle (422 kB JS / 107 kB gzip) |
| Foundry module suite | `node --test` | **Pass** — **77 tests** |
| Foundry packaging | `node packaging/package.mjs` | Manifests now agree at `0.2.0` |
| Production dependency set | `uv export` vs `uv export --all-extras`, plus a clean base-only venv | **`httpx` absent from the production install** — see Finding 1 |
| Compose / migrations / container smoke | — | **Not run**: Docker daemon unavailable in this environment |

Coverage tooling is not part of the repository. `pytest-cov` was supplied transiently via
`uv run --with pytest-cov`, and `@vitest/coverage-v8` via `npm install --no-save`; neither
`pyproject.toml`, `uv.lock`, `portal/package.json`, nor `portal/package-lock.json` was modified,
and `git status` is clean.

### Scale of the codebase

| Artifact | Count |
|---|---|
| Alembic revisions | 107 |
| Tables modelled in `src/dnd_ai/persistence/tables/` | ~165 across 12 schemas |
| Schemas declared in the logical model (`import` documented, unbuilt) | 13 |
| Python source | ~50,850 lines (118 modules) |
| Python tests | ~94,500 lines; 2,772 test functions (458 unit / 2,219 database / 95 scenario) |
| HTTP routes | 98, plus `/healthz` and `/readyz` |
| Portal | ~230 source modules, 160 test files |
| Foundry module | 12 ES modules, 11 test files, zero dependencies |

---

## Part 1 — Implementation fidelity to the documentation, and progress toward the documented goals

### 1.1 Verdict

**Fidelity: very high. Progress: uneven by design, and further behind than the phase table implies
in one specific respect — the platform can read, authorize, and audit a world far better than it
can author one.**

Every one of CLAUDE.md's eleven non-negotiable rules holds under direct inspection:

| Rule | Evidence found |
|---|---|
| 1. PostgreSQL is the only source of truth | No cache, search, or embedding store exists. `ai.embedding_records` is deliberately unbuilt because nothing reads it yet. |
| 2. AI never writes canon directly | `ai.proposed_changes` → `ai.change_reviews` → `commands.ai_proposals._apply_proposal`, whose closed dispatch table only ever calls two pre-existing canonical commands. `proposal_kind` is a closed `CHECK` set, not free text. |
| 3. Clients never write to the database | The Foundry module and portal both speak only HTTP; all 31 portal API client modules `fetch` against `/api` or `/auth`. |
| 4. Class-table inheritance | `grep -rn INHERITS database/migrations/versions/` returns nothing. `character.npcs` / `player_characters` are keyed on the parent UUID. |
| 5. Four separate concerns | Definition (`world.*`, `character.*`), timeline state (`campaign.*_state`), knowledge (`knowledge.*`), and history (`narrative.events`) are distinct schemas with distinct tables. |
| 6. Events and typed state commit atomically | `api/deps.get_connection` opens one transaction per request; commands are split into `_impl(connection, …)` plus engine wrappers precisely so the API owns the boundary rather than nesting a second one. `tests/database/test_event_state_atomicity.py` asserts it. |
| 7. Branch history never leaks | `campaign.effective_events(timeline_id)` plus `tests/scenario/test_branch_effective_history.py`. |
| 8. Knowledge is per-knower | No `is_player_known` / `is_discovered` column exists anywhere; revision 039 carries an explicit comment forbidding one. (The only `is_known` in the tree is a character's *spell list*, a mechanical property.) |
| 9. Archive, don't delete | `core.lifecycle_statuses` throughout; revocations set `revoked_at` rather than deleting. `end_campaign_membership` revokes roles *and* character relationships in the same transaction rather than reassigning them. |
| 10. No secrets in code | `.env.example` carries commented placeholders only; `DND_AI_SECRETS_DIR` supports file-mounted secrets; `set-role-password` reads from an env var, never a `--password` flag. |
| 11. PostgreSQL 18, self-hosted | `postgres:18.4` in both `compose.yaml` and CI; `tests/conftest.py` **fails** rather than skips on a wrong major version. |

Database conventions hold equally: no `ENUM` types, no tables in `public`, no bare `id` primary
keys, `TEXT` throughout, lookup tables with stable `code` columns, and `alembic check` wired into
CI so the SQLAlchemy Core table definitions cannot drift from the migrations.

Architectural layering (SYSTEM_ARCHITECTURE §5) is respected with unusual rigour. The API layer
confines itself to authentication, authorization, validation, correlation, idempotency, and
response shaping; domain invariants live in `commands/` and `domain/`; `queries/` never mutates.
Cross-campaign leak guards (`validate_session_campaign`, `validate_campaign_party`) were each
promoted to `commands/_shared.py` on second use rather than copy-pasted, and both deliberately
inherit the 404 non-disclosure contract instead of a more informative 403.

Code-level documentation is exceptional — most modules explain *why* a decision was made and what
the rejected alternative was. For a project whose contributors include AI assistants, that is a
material asset, and it should be preserved as the authoring surface is built out.

### 1.2 Where implementation and documentation have drifted

None of these are architectural violations; they are places a reader would be misled.

1. **`docs/PROJECT_STATUS.md` is stale.** It reports "65 test files and 369 tests" for the portal;
   the actual figures are **160 files and 1,034 tests**. All three graded findings it records are
   now fixed: `foundry-module/package.json`'s `test` script is `node --test` (77 tests discovered
   and passing), the two Foundry manifests agree at `0.2.0`, and `mypy scripts` passes cleanly.
   It is dated against commit `518c079`, several merges back.

2. **`PLAN.md` §27.1–§27.2 contradict `PLAN.md` §24.0 and ADR 0012.** §27.2 still describes `dev`
   (shared, always-on AWS RDS) as the environment "CI verifies every commit against… the merge
   gate", and instructs the reader not to stop it for cost hygiene. §27.1 still routes CI
   migrations through "a per-run ephemeral database on `dev`". ADR 0012 moved the merge gate to a
   disposable `postgres:18.4` container, which is what `.github/workflows/ci.yml` actually does.
   Both paragraphs should be rewritten to match §24.0.

3. **`architecture/DATABASE_MODEL.md` mixes built and unbuilt tables in the same lists.** The
   document is explicitly a *logical* model, which is correct, but "built by Phase N revision M"
   annotations are applied inconsistently. §15 and §17 annotate most entries, while §7.2's ten
   NPC-portrayal tables (`character.npc_portrayal_profiles`, `npc_goals`, `npc_routines`,
   `npc_boundaries`, `npc_disclosure_rules`, …) and §17's `campaign.npc_goal_state`,
   `npc_emotional_state`, `character_inventory`, and `entity_overrides` carry no marker and do not
   exist. A reader cannot distinguish "not yet built" from "annotation omitted".
   **Recommendation:** add an explicit `Built` / `Planned` column, or a one-line convention
   statement at the head of each table list.

4. **`LOCAL_DEPLOYMENT.md` describes six Compose services; three exist.** See Part 3.

### 1.3 The real progress gap: there is no authoring surface

`docs/ENTITY_LIFECYCLE.md` §21 enumerates the platform's service commands. Of the 22 listed,
**6 exist in some form and 16 do not**:

| Documented command | Status |
|---|---|
| `RecordEvent` | `commands.events.record_event` |
| `ApplyTimelineStateChange` | Partial — `character_state`, `movement`, `update_organization_status`, `evolve_relationship_reaction` |
| `SubmitAiProposal` | Via `commands.ai_npc.request_npc_conversation_turn` |
| `ApproveAiProposal` / `RejectAiProposal` | `commands.ai_proposals.review_proposed_change` |
| `CreateEntity`, `CreateCharacter`, `CreateNpc`, `CreatePlayerCharacter`, `CreateLocation`, `CreateDungeon`, `CreateQuest` | **Missing** |
| `SubmitEntityForReview`, `ApproveEntity`, `PublishEntityAsCanon`, `SupersedeEntity` | **Missing** |
| `ArchiveEntity`, `RestoreEntity`, `DeleteDraftEntity` | **Missing** |
| `VoidEvent`, `CorrectEvent` | **Missing** |
| `CreateTimelineBranch` | **Missing** — `parent_timeline_id` appears in no command and no route |
| `PromoteImportBatch` | **Missing** (Phase 15) |

`SYSTEM_ARCHITECTURE.md` §5.3's own recommended list has the same holes: `CreateWorld`,
`CreateTimeline`, `CreateNpc`, `StartSession`, and `CreateTimelineBranch` are all absent.
`commands.campaigns.create_campaign` requires a **pre-existing `timeline_id`**, and no command or
route creates a world or a timeline at all. Of the 98 routes, exactly one (`POST /campaigns`)
creates anything a GM would call world content.

The practical consequence is visible in `scripts/setup_phase13c_dev_data.py`, which populates
`core.worlds`, `core.entities`, `character.characters`, `character.npcs`, `narrative.events`,
`knowledge.knowledge_items`, and roughly thirty other tables by **direct `INSERT` statements** —
the exact pattern `DEVELOPMENT.md` §6.1 forbids ("build test data through the same commands
production uses"). The script is not at fault; there are no commands for it to call.

Likewise, the canon lifecycle that `ENTITY_LIFECYCLE.md` §§4, 7, 8, 12–14 specifies in detail
(draft → review → approved → canon → superseded → archived → restored) exists as
`core.canon_statuses` and `core.lifecycle_statuses` rows and is *read* during authorization, but
no command transitions an entity through it.

**This is the largest gap between the documented platform and the built one.** It does not appear
in PLAN.md's progress table because Phases 2–9 were scoped as *schema* delivery and closed on
schema evidence, while Phase 10's vertical slice deliberately chose a narrow set of play-time
commands. But it means a GM cannot today create an NPC, a location, a quest, or a timeline branch
through any supported interface.

**Recommendation:** add an explicit authoring workstream to PLAN.md — either alongside Phase 13 or
as a new phase before 15 — covering `CreateEntity` / `CreateCharacter` / `CreateNpc` /
`CreateLocation` / `CreateQuest`, the canon-status transitions, `ArchiveEntity` / `RestoreEntity`,
and `CreateTimelineBranch`. Phase 15 structurally depends on it: `PromoteImportBatch` is specified
to promote staged rows *through the same entity-creation commands manual authoring uses*, and
those commands do not exist.

### 1.4 Progress against each documented goal

| Documented goal | State |
|---|---|
| Persistent worlds, timelines, branching | Schema complete and tested; branch-effective history proven. No branch-creation command. |
| Shared NPC/PC mechanical model | Schema complete (builds, ability scores, class levels, proficiencies, spells). Rules *content* is a token seed set: 2 classes, 2 subclasses, 2 species, 2 feats, 3 features, 5 spells, 18 skills. |
| Event-driven world evolution, queryable history | Complete and strongly tested. |
| Party-specific discovery and knowledge | Complete — the richest part of the model (versions, transfers, distortion, public knowledge, expertise). |
| Controlled AI proposals | Complete for two proposal kinds; policy engine (`domain.ai_policy`) present. |
| AI-assisted NPC simulation | One use case (`npc_conversation`) end to end; portrayal-profile schema unbuilt. |
| AI-assisted GM tools | Audience-aware synthesis (`gm_brief` / `player_summary` / `observer_summary`) implemented; no preparation copilot. |
| FoundryVTT integration | Implemented — pairing, per-device credentials, scoped tokens, combat sync, 77 module tests. Licensed live v13 acceptance still unrecorded. |
| REST / service API | 98 routes with real authentication, authorization, idempotency, audit, non-disclosure, and keyset pagination. |
| Web portal | Login, invitation acceptance, campaign selection, perspective selection, Home / World / Characters / Quests / Sessions / Knowledge, and GM access management are live. Ask is a gated placeholder. |
| Discord integration | Not started. |
| MCP integration | Not started. |
| RAG / reference corpus | Retrieval, citation, grants, and audit implemented over PostgreSQL full-text search; no synthesis tier over retrieved passages. |
| Campaign-data import | Not started (Phase 15). |
| Additional rulesets | `domain.character_calculations` gates on `dnd5e` and returns raw-only sheets otherwise — correct posture, one ruleset implemented. |
| Local production deployment | Database, migrations, and API only. See Part 3. |

---

## Part 2 — Test coverage: current state, deficiencies, and remediation

### 2.1 Headline numbers

| Suite | Tests | Statement coverage | Branch coverage |
|---|---:|---:|---:|
| Python — **full suite** (`tests/unit` + `tests/database` + `tests/scenario`) | 4,480 | **97%** | **88%** |
| Python — **`tests/unit` alone** | 561 | **65%** | — |
| Portal (Vitest + jsdom + Testing Library) | 1,034 | **90.8%** | **83.0%** |
| Foundry module (`node --test`) | 77 | not measured | not measured |
| Browser end-to-end | **0** | — | — |

**The >85% bar is met, and the 100% goal is within reach — but only when "unit" is read as "the
Python suite", not as `tests/unit/`.** That distinction matters for how you act on it, so it is
worth stating plainly:

- Read as *the whole Python test suite*, coverage is **97% statements / 88% branches**, with
  **65 of 118 modules at 100%**. This comfortably clears >85% and is a genuinely strong position.
- Read as *`tests/unit/` in isolation*, coverage is **65%**. This is not a defect to fix by moving
  tests. The command, query, and API layers are thin coordinators over SQL — their behaviour *is*
  the SQL, and testing them without PostgreSQL would mean mocking `Connection.execute`, which
  proves nothing about production. `tests/database` is the correct home for that logic and the
  project's own conventions (DEVELOPMENT §6, PLAN §26.1–26.2) say so.

**Recommendation:** restate the target in `DEVELOPMENT.md` §6 as a **combined-suite** coverage gate
(≥95% statements, ≥90% branches, trending to 100%), and keep a separate, *lower* expectation for
`tests/unit/` scoped to what genuinely has no database dependency (`domain/`, `config`,
`api/pagination`, `api/errors`, `api/correlation`, `api/client_address`). Measuring `tests/unit` in
isolation against an 85% bar would push the project toward mock-heavy tests that reduce real
confidence.

### 2.2 Python coverage by layer

| Layer | Statements | Branches |
|---|---:|---:|
| `persistence/` | 99.2% | 10/18 |
| `queries/` | 98.5% | 199/220 |
| `api/` | 96.6% | 457/538 |
| `commands/` | 96.5% | 506/562 |
| `domain/` | 96.1% | 109/128 |
| `config.py` + root | 96.3% | 85/90 |

**The 269 uncovered statements and 152 partially-covered branches are concentrated in
error/degraded paths, not happy paths.** The weakest modules, worst first:

| Module | Statements | Uncovered lines / notes |
|---|---:|---|
| `api/deps.py` | 75.6% | Engine singleton lifecycle (`dispose_engine`), production `verify_database_identity` failure branch |
| `persistence/seeds.py` | 75.8% | Malformed/absent seed-file handling |
| `commands/sessions.py` | 76.9% | `end_session` guard branches |
| `commands/reference_corpus.py` | 77.9% | Source removal, grant revocation, passage-ingest failure paths |
| `api/access_groups.py` | 80.1% | 25 statements — idempotency-replay and no-op-revoke branches |
| `api/character_state.py` | 81.3% | 18 statements across the four state-mutation routes' error arms |
| `api/audit.py` | 81.8% | Single audit-write helper branch |
| `api/ai_synthesis.py` / `api/ai_npc.py` | 84.2% / 85.7% | Provider-unavailable and provider-error paths |
| `domain/ai_provider.py` | 89.2% | **10 partial branches** — HTTP error, malformed-response, and timeout handling |

**Remediation (Python), in priority order:**

1. **Cover `domain/ai_provider.py`'s transport failure modes.** Ten partial branches in the one
   module that talks to an external network service is the highest-value gap in the tree. Add unit
   tests with a stubbed `httpx` transport for: connect timeout, read timeout, 429, 500, non-JSON
   body, JSON body missing `choices`, and a response that fails `ValidationError`. This is pure
   unit work — no database — so it raises `tests/unit` coverage too. It would also have caught
   Finding 1.
2. **Cover the idempotency-replay and no-op-revoke branches** in `api/access_groups.py`,
   `api/access_grants.py`, `api/character_state.py`, and `commands/sessions.py`. These are exactly
   the branches PHASE13E_ACCESS_CONTRACT.md documents as deliberate duplicate-audit fixes, so they
   are *specified* behaviour that should have positive and negative tests per the project's own
   §32.1 rule.
3. **Cover `persistence/seeds.py` and `api/deps.py` failure paths.** Small, cheap, and both sit on
   the startup/deploy path where a silent failure is expensive.
4. **Add a coverage gate to CI.** See §2.5.

### 2.3 Structural gaps in the Python suite

Three test categories the project's own plan requires do not exist at all.

1. **No property-based tests.** `hypothesis>=6.92.0` is a declared dev dependency and
   `grep -rln "from hypothesis\|@given" tests/` returns **nothing**. PLAN.md §26.4 explicitly
   requires property-based testing for five targets: timeline resolution, relationship participant
   combinations, event-effect application, quest dependency graphs, and world-time ordering.
   **Remediation:** these five are unusually good Hypothesis candidates because each has an
   invariant expressible independently of the implementation — e.g. for any branch point `b` and
   any event set, `effective_events(child)` must equal
   `{e in parent : e.sort_key < b} ∪ {e in child}`; for any world-time pair, `sort_key` ordering
   must agree with calendar ordering. Start with timeline resolution and world-time ordering
   (highest invariant density, lowest fixture cost), using `@given` over generated `sort_key`
   sequences against the real database via the existing session fixtures.

2. **No performance tests.** PLAN.md §26.5 requires measurement of effective-state queries, NPC
   context assembly, dungeon-map retrieval, session event ingestion, knowledge filtering, and
   branch resolution. `grep -rln "benchmark\|perf_counter\|EXPLAIN" tests/` returns nothing.
   **Remediation:** rather than wall-clock assertions (flaky in CI), assert on **query plans and
   row counts**: run `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` against the six named queries and
   fail if a plan contains a sequential scan on a table above a threshold row count, or if the
   planned row estimate exceeds a bound. That is deterministic, catches the actual regression
   (a dropped index, an unindexed FK), and costs nothing in runtime variance. Pair it with
   `pytest-benchmark` (BSD-3) only for the two genuinely CPU-bound paths (context assembly,
   character-sheet derivation), reporting rather than gating.

3. **Tests are never type-checked.** `pyproject.toml` defines a `[[tool.mypy.overrides]]` block for
   `tests.*`, but `mypy src` never loads it — mypy reports `unused section(s): module = ['tests.*']`
   on every run. 94,500 lines of test code with 2,772 test functions are entirely untyped from the
   checker's point of view. **Remediation:** extend CI to `mypy src tests scripts`. It already
   passes on `src` and `scripts`; expect an initial batch of annotations in `tests/factories.py`
   and `tests/conftest.py`, after which the override block starts doing its job.

Minor items:

4. **CI's mypy scope on `scripts/` is one file.** `.github/workflows/ci.yml` runs
   `mypy scripts/wait_for_ci.py`. `mypy scripts` (all 7 modules) passes today — widen it before it
   regresses.
5. **Six conditional `pytest.skip()` calls** in migration tests (`test_phase5_populated_upgrade`,
   `test_phase8_populated_upgrade`, `test_access_group_description_length_migration`,
   `test_login_failure_audit_action_migration`, `test_downgrade_deferred_trigger_ordering`, and one
   branch of `test_api_world_explorer`). The full run reported zero skips, so these are currently
   inert, but a skip that can silently become permanent is worth converting to an explicit
   assertion on the precondition it guards.

### 2.4 Portal / UI testing — correcting the premise, then the real gaps

**The premise that "UI tests currently do not use any automated test suites" is not accurate, and
the actual position is considerably better than that.** The portal has a real, well-maintained
automated suite:

- **Vitest 4** as the runner, configured in `portal/vite.config.ts` with `environment: "jsdom"`.
- **`@testing-library/react` 16** and **`@testing-library/jest-dom` 7**.
- **160 test files, 1,034 tests**, all passing, run in CI on every push and pull request by the
  `portal-check` job alongside `npm run lint` and `npm run build`.
- **90.8% statement / 83.0% branch / 95.1% function coverage** when measured.
- Tests are behaviour-focused and accessibility-aware — they query by role and accessible name,
  and several assert live-region announcement behaviour (`CampaignAccessPage`'s `role="status"`
  region exists specifically so a screen reader observes a role change that unmounts its origin).
- Seven `CampaignAccessPage.*.integration.test.tsx` files exercise multi-component flows, not just
  isolated units.

What is genuinely missing is a **browser** layer, plus tooling hygiene. The real gaps:

| Gap | Evidence | Impact |
|---|---|---|
| **No browser E2E suite** | No Playwright/Cypress/WebDriver dependency or config anywhere | PLAN §26.7 and Phase 13H require one. Nothing verifies real cookie behaviour, CSRF, redirect flows, or cross-layer authorization against a live API. |
| **No coverage measurement or gate** | `@vitest/coverage-v8` not installed; `npm test` is bare `vitest run` | Coverage can regress invisibly. |
| **No `@testing-library/user-event`** | 43 files use `fireEvent` | `fireEvent` dispatches a single synthetic event; `user-event` reproduces the full browser sequence (pointerdown → focus → keydown → input → change). Form/select/typing behaviour can pass under `fireEvent` and fail in a browser. |
| **42 files hand-roll `fetch` stubs** | `vi.stubGlobal` / `global.fetch` per file | Each file re-implements request matching. Contract drift between a stub and the real API is undetectable. |
| **No automated accessibility assertions** | No `axe` dependency | UI_DESIGN §11 and §16 require keyboard accessibility and responsive behaviour at three widths; nothing enforces it. |
| **No visual/theme regression coverage** | — | `ThemeProvider` supports multiple themes; nothing verifies contrast or layout in each. |
| **`AuditHistory.tsx` is tested but unreachable** | Only `AuditHistory.test.tsx` imports it | 1,316 lines across component, hook, API client, CSS, and tests — all green, all dead. See Finding 4. |
| **One coverage-sensitive flake** | `AuditHistory.test.tsx:246` "Load more" failed under v8 instrumentation, passed standalone and with `--testTimeout=20000` | A 1,000 ms `waitFor` default is too tight under load; it will flake on a slow CI runner. |

### 2.5 Recommended FOSS test stack and a staged path to acceptable coverage

All recommendations are free and open source, and all are chosen to satisfy PLAN §26.6–26.7's
proportionality rule — no generalized UI harness, no duplication of domain tests.

**Coverage measurement (do this first — it is an afternoon's work and makes everything else
measurable):**

| Tool | Licence | Use |
|---|---|---|
| `pytest-cov` + `coverage.py` | MIT / Apache-2.0 | Add to `[project.optional-dependencies].dev`. Configure `[tool.coverage.run] branch = true, source = ["src/dnd_ai"]` and `[tool.coverage.report] fail_under = 95` in `pyproject.toml`. |
| `@vitest/coverage-v8` | MIT | Add to `portal/devDependencies`. Set `test.coverage.thresholds` in `vite.config.ts` to `{ statements: 90, branches: 82, functions: 95 }` — today's measured numbers, so it ratchets rather than blocks. |
| `diff-cover` | Apache-2.0 | Fails a pull request whose *changed lines* fall below a higher bar (say 100%) without demanding a repo-wide rewrite. This is the mechanism that actually gets you to 100% over time. |

Add two CI steps: `uv run pytest --cov` in `postgres-verification`, and
`npm test -- --coverage` in `portal-check`. Both already run the suite; only the flags change.

**Browser end-to-end — use Playwright:**

| Tool | Licence | Why |
|---|---|---|
| **`@playwright/test`** | Apache-2.0 | The right choice here, not Cypress. It drives Chromium, Firefox, and WebKit from one config; it handles multiple independent browser contexts in one test, which is exactly what you need for two-device Foundry pairing and for GM/player/observer distinctions; its `storageState` support lets you assert the *absence* of durable browser-readable credentials (a stated Phase 13H criterion); it has first-class tracing for debugging CI-only failures; and its built-in `toHaveScreenshot` covers the visual/theme requirement with no extra dependency. Cypress cannot do multi-origin/multi-context cleanly and its open-source parallelization story is weaker. |
| **`@axe-core/playwright`** | MPL-2.0 | One `expect(await new AxeBuilder({page}).analyze()).toHaveNoViolations()` per screen covers UI_DESIGN §11's accessibility criterion mechanically. |

Wire it to a real stack, not mocks — that is the entire point of the layer. A
`compose.e2e.yaml` that brings up `db`, runs `migrate`, runs `scripts/bootstrap_admin.py`, runs
`scripts/setup_phase13c_dev_data.py`, starts `api`, and serves the built portal behind a proxy
gives Playwright a genuine same-origin target. Run it as a **separate CI job** so it never slows
the existing gates.

Scope the E2E suite to PLAN §26.7's own list — roughly 15 specs, not 150:

1. Activate → log in → select campaign → log out.
2. Failed login and password recovery return uniform responses (no account enumeration).
3. After login, no durable browser-readable credential exists (assert `localStorage`,
   `sessionStorage`, and non-`HttpOnly` cookies are empty; assert the `__Host-` cookie is present
   and `HttpOnly`).
4. A state-changing request without the `X-CSRF-Token` header is rejected.
5. Campaign switch and character-perspective switch refetch from the server (assert a network
   request occurs, not just a re-render).
6. GM, player, and observer see different Home dashboards for the same campaign.
7. Revoking a role removes access on the next request.
8. Revoking a browser session invalidates it on the next request.
9. Two-device Foundry pairing: device A's credential cannot act as device B.
10. With Phase 12 features disabled, the Ask surface issues **no** network request.
11. A hidden resource is absent from search results, and its direct URL returns the same
     "not available" shape as a nonexistent one (non-disclosure).
12. Invitation acceptance, including the token-replay path recently fixed.
13. Keyboard-only traversal of the primary navigation and one detail screen.
14. Axe scan of Home, World, Character Sheet, Quests, Knowledge, and Access.
15. Screenshot comparison of one representative screen in each theme at 400 px, 768 px, and
     1280 px.

**Component-layer improvements (cheap, high value):**

| Tool | Licence | Use |
|---|---|---|
| **`@testing-library/user-event`** | MIT | Migrate the 43 `fireEvent` files incrementally — new tests use `user-event`, existing ones convert when touched. Prioritise the form-heavy Access components. |
| **`msw`** (Mock Service Worker) | MIT | Replace the 42 hand-rolled `fetch` stubs with one shared set of request handlers. Beyond deduplication, MSW intercepts at the network layer, so the same handlers work in Vitest *and* Playwright, and an unhandled request becomes a loud error instead of a silent `undefined`. |

**API contract and property testing (addresses §2.3 gap 1 from a different angle):**

| Tool | Licence | Use |
|---|---|---|
| **`schemathesis`** | MIT | Generates property-based tests directly from FastAPI's auto-generated OpenAPI schema. Points at all 98 routes and asserts that no input produces a 500, that responses match their declared schemas, and — with a small custom check — that no unauthenticated request ever returns 200. This is the highest-leverage single addition available: one config file exercises the entire API surface, and it is a genuine property-based suite, partially satisfying PLAN §26.4. |
| **`hypothesis`** | MPL-2.0 | Already a declared dependency. Use it for the five §26.4 targets as described in §2.3. |

**Foundry module:** coverage is unmeasured. Node 20+ supports `node --test --experimental-test-coverage`
natively with zero new dependencies — add `--experimental-test-coverage` to the CI step and record
the baseline.

**Staged plan:**

| Stage | Work | Outcome |
|---|---|---|
| 1 (days) | `pytest-cov` + `@vitest/coverage-v8` + thresholds + `diff-cover` in CI; `--experimental-test-coverage` for Foundry | Coverage becomes visible and cannot silently regress |
| 2 (1 week) | `ai_provider` transport tests; idempotency/no-op-revoke branches; `seeds.py` / `deps.py` failure paths; `mypy src tests scripts` | Python ≥98% statements, ≥92% branches; tests type-checked |
| 3 (1 week) | `schemathesis` against the OpenAPI schema; Hypothesis for timeline resolution + world-time ordering | Property-based coverage exists; whole-API fuzz gate |
| 4 (2 weeks) | Playwright + `compose.e2e.yaml` + the 15 specs + axe | Phase 13H's E2E criterion satisfied |
| 5 (ongoing) | `user-event` and MSW migration as files are touched; `EXPLAIN`-plan performance assertions | §26.5 satisfied; browser-fidelity risk retired |

Fix the `AuditHistory` flake in stage 1 by passing an explicit `{ timeout: 5000 }` to the
`waitFor` at `portal/src/components/AuditHistory.test.tsx:246`.

---

## Part 3 — Deployment: Docker on a home network behind a No-IP domain

### 3.1 Current state

`compose.yaml` defines **three** services. `LOCAL_DEPLOYMENT.md` specifies **six**.

| Service | Specified in LOCAL_DEPLOYMENT.md | Exists in `compose.yaml` |
|---|---|---|
| `db` / `postgres` | Yes | **Yes** — `postgres:18.4`, named volume at `/var/lib/postgresql` (correct for PG 18's changed layout), healthcheck against the `postgres` maintenance DB, no published port |
| `migrate` | Implied | **Yes** — one-off, `profiles: ["tools"]` |
| `api` | Yes | **Yes** — Uvicorn, `DND_AI_ENVIRONMENT=production` as a fixed literal, connects as `app_read_write`, no published port |
| `ui` | Yes | **No** |
| `proxy` | Yes | **No** |
| `ddns` | Yes | **No** |
| `worker` / scheduler | "when required" | **No** — and `SYSTEM_ARCHITECTURE.md` §10's transactional outbox has no table either |

A repository-wide search for `caddy`, `traefik`, `noip`, `ddns`, `letsencrypt`, `certbot`, and
`acme` finds matches **only in documentation** (`ADR 0013`, `LOCAL_DEPLOYMENT.md`, `PLAN.md`,
`UI_DESIGN.md`) and in `src/dnd_ai/api/client_address.py`. No proxy configuration, no TLS
automation, and no dynamic-DNS updater exists in the tree.

`.github/workflows/` contains one workflow (`ci.yml`). There is no deploy, release, or image-publish
workflow, and no image is pushed to any registry.

### 3.2 What is already correct, and genuinely valuable

The application-side groundwork for this exact topology is done, and done well:

- **Trusted-proxy handling exists and is safe.** `DND_AI_TRUSTED_PROXIES` (CIDR or address list)
  plus `api/client_address.resolve_client_ip` trusts `X-Forwarded-For` **only** when the immediate
  TCP peer is a configured trusted proxy, reads the **last** entry (so prepended forgeries cannot
  win), validates it parses as an IP, and falls back to `request.client.host` in every other case.
  Default is trust-nothing.
- **No reliance on `X-Forwarded-Proto`.** The session cookie's `Secure` flag and the `__Host-`
  prefix derive from `settings.environment == "production"`, not the request scheme, so TLS
  termination at a proxy cannot accidentally downgrade the cookie. This avoids the single most
  common reverse-proxy authentication bug.
- **Origin/CSRF enforcement is production-mandatory.** `DND_AI_LOCAL_SESSION_ALLOWED_ORIGINS` has
  no fallback default and requires HTTPS origins in production; a double-submit `X-CSRF-Token` is
  checked against the session's server-stored value.
- **Least-privilege database identity is enforced at runtime, not just configured.** `api` must
  authenticate as `app_read_write`; the lifespan hook opens a real connection and checks both
  `session_user` and `current_user`, aborting Uvicorn startup on mismatch. CI additionally proves
  live privilege boundaries (`CREATE TABLE` and `SET ROLE migration_owner` both rejected).
- **CORS is narrow and never wildcards**, scoped to the Foundry origin only.
- **Secrets can be file-mounted** via `DND_AI_SECRETS_DIR`, not just env vars.
- **Backup/restore tooling is real and substantial** — `scripts/operations/database_recovery.py`
  (2,590 lines, 9 subcommands: `backup`, `roles`, `validate`, `preflight`, `bootstrap`,
  `set-role-password`, `restore`, `verify-roles`, `teardown`) with a 614-line runbook at
  `docs/operations/DATABASE_RECOVERY.md` covering fresh-cluster restore, existing-cluster restore,
  isolated restore drills, and major-version cutover.
- **Volume persistence is CI-proven** — the `persistence-check` job writes a marker, force-recreates
  the container, and asserts the marker survived, against the real named volume rather than CI's
  tmpfs override.
- **First-admin bootstrap is DB-direct and fails closed** — `scripts/bootstrap_admin.py` refuses to
  run once any `security.users` row exists, and is never exposed over HTTP.

### 3.3 Missing steps to run as a normal public website

The following is the complete list of what must be added. Nothing here requires application-code
changes except items 3 and 9.

**1. Add a `ui` service that serves the built portal.**
`Dockerfile` copies only `src/` and `database/`; the portal is never built into an image. Add a
second stage or a separate `portal/Dockerfile`:

```dockerfile
FROM node:24-alpine AS portal-build
WORKDIR /portal
COPY portal/package.json portal/package-lock.json ./
RUN npm ci
COPY portal/ ./
RUN npm run build
# Serve the static output from the proxy image or a minimal static server.
```

Serving the `dist/` output directly from the proxy container (Caddy's `file_server`) is simpler
than a separate `ui` container and one fewer moving part. Either is acceptable; pick one and record
it in `LOCAL_DEPLOYMENT.md`.

**2. Add a `proxy` service with automatic TLS.**
**Caddy is the better fit than Traefik here** — its two-line automatic-HTTPS default, built-in
static file server, and single-file config match a one-host deployment far better than Traefik's
label-driven dynamic discovery, which exists to solve a problem (frequently changing service
topology) this deployment does not have. A working `Caddyfile` for the documented topology:

```caddyfile
world.example.com {
    encode zstd gzip

    header {
        Strict-Transport-Security "max-age=31536000; includeSubDomains"
        X-Content-Type-Options "nosniff"
        X-Frame-Options "DENY"
        Referrer-Policy "strict-origin-when-cross-origin"
        -Server
    }

    # The portal hardcodes /api/* and /auth/* (portal/src/api/*.ts).
    # The API mounts its routes at the ROOT (/campaigns/..., /auth/...),
    # so /api must be stripped and /auth must NOT be.
    handle_path /api/* {
        reverse_proxy api:8000
    }

    handle /auth/* {
        reverse_proxy api:8000
    }

    # Everything else is the SPA; unknown paths fall back to index.html
    # so client-side routes such as /app/<id>/world deep-link correctly.
    handle {
        root * /srv/portal
        try_files {path} /index.html
        file_server
    }
}
```

The `handle_path` / `handle` asymmetry is the one non-obvious detail and the most likely source of
a first-deployment failure: `portal/vite.config.ts` rewrites `/api` → `/` in development but
forwards `/auth` verbatim, and production must match that exactly.

**3. Serve the SPA's deep links.** `try_files {path} /index.html` above handles it. Without it,
refreshing `/app/<campaign-id>/world` returns 404. There is no `basename` configured in the React
router, so the portal must be served from the origin root — do not mount it under a subpath
without also setting Vite's `base` and the router's `basename`.

**4. Add a `ddns` service for No-IP.** No official first-party container is required; the update is
a single authenticated HTTPS GET. Either use the community `oznu/cloudflare-ddns`-equivalent for
No-IP, or — preferably, given the "no new dependency" posture elsewhere — a five-line loop in a
`ddns` service built from the existing Python image:

```yaml
  ddns:
    image: curlimages/curl:latest
    restart: unless-stopped
    environment:
      NOIP_HOSTNAME: ${NOIP_HOSTNAME:?required}
      NOIP_USERNAME: ${NOIP_USERNAME:?required}
      NOIP_PASSWORD: ${NOIP_PASSWORD:?required}
    command: >-
      sh -c 'while true; do
        curl -fsS -u "$$NOIP_USERNAME:$$NOIP_PASSWORD"
          "https://dynupdate.no-ip.com/nic/update?hostname=$$NOIP_HOSTNAME"
          || echo "no-ip update failed"; sleep 300; done'
```

Prefer a No-IP **DDNS key** over the account password, and mount it as a file secret rather than an
env var. Alert on repeated failure — a silently stalled updater plus an ISP lease change is an
outage with no other symptom.

**5. Open exactly two router ports: 443 and 80, both forwarded only to the proxy host.** Port 80 is
needed for the ACME HTTP-01 challenge and for the HTTP→HTTPS redirect; Caddy handles both. Do
**not** forward 5432 or 8000. `compose.override.yaml` publishes `db` and `api` on `127.0.0.1` for
development — its own header comment warns against copying those mappings into a real deployment,
and that warning should be honoured.

**6. Choose the public hostnames and set the three origin variables consistently.** With a No-IP-only
arrangement, two provider hostnames (one for the portal/API, one for Foundry) are the simplest
shape. Then set:
- `API_LOCAL_SESSION_ALLOWED_ORIGINS=https://world.<domain>` (required, HTTPS-only in production)
- `API_FOUNDRY_ALLOWED_ORIGINS=https://foundry.<domain>` (only if Foundry integration is enabled)
- `API_TRUSTED_PROXIES=<the proxy container's subnet>` — **this one is easy to forget and its
  absence is silent.** Left unset, `resolve_client_ip` returns the proxy's own address for every
  request, so the per-IP login rate limiter degrades to a single global bucket. Use the Compose
  network's CIDR (e.g. `172.20.0.0/16`), not a container name.

**7. Add resource limits.** ADR 0013 accepts that Foundry and D&D AI share the host. Without
`deploy.resources.limits` on `api` and `db`, an AI request or a large query can starve Foundry.
Set `cpus` and `memory` limits plus reservations for both.

**8. Add log rotation and disk monitoring.** Set `logging.driver: json-file` with
`max-size`/`max-file` on every service, or switch the daemon default. A residential host with an
unrotated container log is a predictable disk-full outage.

**9. Schedule backups and prove a restore.** The tooling exists; the schedule does not. Add a
host cron or a `backup` Compose service that runs `database_recovery.py backup` nightly, retains
N days, and copies at least one encrypted snapshot offsite. Then actually run the documented
isolated restore drill and record the result — `LOCAL_DEPLOYMENT.md`'s own production-readiness
gate requires it.

**10. Add health-driven restart and startup ordering for the full stack.** `db` and `api` already
have healthchecks and `unless-stopped`. `proxy` and `ui` need the same, and the documented
must-run-first sequence (`migrate`, then `set-role-password`, then `api`) is currently a manual
procedure in a comment. A small `scripts/operations/deploy.sh` that performs backup → build →
migrate → verify-roles → recreate → health-check → smoke-test would make it repeatable and is the
natural home for the rollback path ADR 0013 requires.

**11. Publish immutable, commit-tagged images.** ADR 0013 requires "immutable versioned images"
traceable to a Git commit. Today images are built locally by `docker compose build`, so a rollback
has nothing to roll back to. Add a release workflow that builds and pushes
`ghcr.io/<owner>/dnd-ai:<git-sha>` on a tag, and have `compose.yaml` accept
`image: ${DND_AI_IMAGE:-dnd-ai:local}`.

**12. Decide the Foundry routing arrangement.** ADR 0013 wants `foundry.<domain>` on the same
proxy. Since Foundry is a separate Compose project, that means a shared external Docker network
(`docker network create edge`) that both projects attach to, with the proxy in one of them. Record
which project owns the proxy.

**Optional but worth considering for a residential host:** put the proxy behind a Cloudflare Tunnel
(`cloudflared`, Apache-2.0) instead of forwarding router ports. It removes inbound port forwarding
entirely, hides the home IP, survives dynamic-IP changes without No-IP, and terminates TLS at the
edge. The trade-off is a dependency on a third party in the request path and a TLS-termination
boundary outside your control — which conflicts with ADR 0013's self-hosted posture, so it should
be a deliberate, recorded decision rather than a default.

### 3.4 Deployment readiness summary

| Area | Status |
|---|---|
| Database container, volume, healthcheck, persistence | **Ready** — CI-proven |
| Migrations as a one-off job | **Ready** |
| API container, least-privilege identity, startup verification | **Ready** |
| Cookie/CSRF/origin hardening | **Ready** |
| Trusted-proxy / `X-Forwarded-For` handling | **Ready** (must be configured) |
| Backup/restore tooling | **Ready**; scheduling, offsite copy, and a recorded drill are missing |
| Portal image and static serving | **Missing** |
| Reverse proxy, TLS, security headers, `/api` strip, SPA fallback | **Missing** |
| Dynamic DNS | **Missing** |
| Resource limits, log rotation, disk alerts | **Missing** |
| Immutable tagged images, deploy/rollback script | **Missing** |
| Background worker / outbox | **Missing** (no feature requires it yet) |

Phase 14 is accurately described in PLAN.md as "partially implemented", but the split is worth
naming precisely: the **application** is production-shaped and the **operational envelope** is not
started. Items 1, 2, 3, and 5 above are the minimum for a working public site; 6 through 11 are the
minimum for one you would leave running unattended.

---

## Part 4 — Current scope versus the marketing and feature proposal

### 4.1 How the two documents relate

The proposal is broadly **compatible** with the built platform — strikingly so in its philosophy
section, which restates this repository's existing architecture almost rule for rule (canon is
authoritative, AI proposes and never writes, truth/belief/knowledge/theory are distinct,
authorization precedes context assembly, rules are versioned and sourced, provenance survives
import). Nothing in the proposal requires abandoning or reworking what exists.

The disagreements are about **emphasis and sequencing**, and there is one genuine architectural
addition the current model does not anticipate at all.

### 4.2 Feature-by-feature mapping

**Legend:** ✅ built · 🟡 partial / foundation exists · 📄 documented but unbuilt · ❌ nothing exists

| Proposal feature | State | Notes |
|---|---|---|
| **§6 Session-note import & campaign intelligence** (proposal's #1 build priority) | 📄 | `import` schema is fully specified in DATABASE_MODEL §20 (9 tables) and PLAN Phase 15; nothing is built. Also blocked by the missing entity-creation commands — `PromoteImportBatch` must go through them. |
| §6.2 Extraction targets (entities, events, claims, contradictions) | ❌ | No extraction pipeline, no AI agent role wired for it (`session_summarizer` is seeded but only used for synthesis). |
| §6.5 Provenance on accepted changes | 🟡 | `core.sources` / `core.source_documents` / `audit.change_log` / `ai.context_snapshots` give most required fields. No link from a promoted change back to a source passage. |
| **§7 GenAI preparation copilot** | ❌ | `ai.agent_roles` seeds `quest_manager`, `world_state_manager`, `lore_consistency_checker`; none is wired. |
| **§8 NPC creation and portrayal profiles** | 📄 | DATABASE_MODEL §7.2 specifies ten `character.npc_*` tables; none exists. `domain.context_assembly.assemble_npc_conversation_context` already assembles knowledge, quests, relationships, and encounter state — the profile is the missing input. |
| §8.2 Detail levels (narrative-only → full sheet) | 🟡 | Character builds support the full end; there is no simulation-level marker and **no creature stat-block table at all**. |
| §8.3 Canon control over AI-invented content | ✅ | Exactly what `ai.proposed_changes` + `domain.ai_policy` + `review_proposed_change` do. |
| **§9 Structured NPC interaction scenes** | 🟡 | `interaction.*` (8 tables) models actions, targets, check requests, results, degrees of success, visibility, and consequences — a strong foundation. `resolve_check` and `perform_interaction` exist. No scene-orchestration layer, no AI DC recommendation, no outcome bands. |
| §9.6 Outcome bands | 🟡 | `interaction.check_results.degree_of_success` exists; band configuration does not. |
| §9.7 Roll visibility | 🟡 | A visibility column exists on `check_results`; no GM control surface. |
| **§10 Creature builder / encounter analysis** | ❌ | `narrative.encounters` runs an encounter; nothing analyses one. No expected-AC/HP/damage model, no CR math, no party-relative assessment. Requires new schema (creature stat blocks) and a new rules-engine surface. |
| **§12 Personalized player dashboard** | 🟡 | `CampaignHomePage` + `queries.summary` deliver a live campaign home. No bookmarks, no personal notes, no "what changed since you last played". |
| **§13 Character-filtered campaign knowledge** | ✅ | The strongest match in the whole comparison. `queries.knowledge_browse` implements six audience-filtered views; non-disclosure is enforced in the query layer and regression-tested. |
| §13.2 Known / Believed / Suspected / Unknown | 🟡 | Known and Believed are modelled richly (`entity_knowledge.confidence`, `interpretation`, `knowledge_versions.distortion_type`). **Suspected (player theory) is not modelled.** |
| §13.3 Q&A workflow with citations | 🟡 | Retrieval + audience filtering exist; the AI answer tier does not (`Ask` is a gated placeholder). |
| **§14 Personalized recaps / character timeline** | 🟡 | `ai_synthesis` produces GM-brief / player-summary / observer-summary from already-filtered data — the correct architecture. No character-specific recap, no timeline view. |
| **§15 NPC / faction / quest memory** | 🟡 | Player-visible NPC and quest records exist with audience filtering. No player-authored notes on them. |
| **§16 Item-specific discussion boards** | ❌ | **Nothing exists, and nothing is planned.** No table, no doc mention (`grep -rli discussion docs/` finds nothing). This is the proposal's biggest genuinely new architectural requirement — see §4.3. |
| **§17 Player notes, bookmarks, theories** | ❌ | `bookmark` appears in UI_DESIGN as a UI affordance with no backing model. No notes, no theories, no corrections, no merge suggestions. |
| **§18 Rules-aware character advancement** | 🟡 | `character.character_builds` and its seven build-scoped child tables model a validated build, with ruleset-version agreement enforced by trigger and every parent identity column made immutable. But there is **no advancement command**, no prerequisite engine, no level-up flow, and `domain.character_calculations` is nine pure arithmetic functions. Rules content is a token seed set (2 classes, 5 spells). |
| **§19 Character and rules assistant** | 🟡 | `commands.reference_corpus.retrieve_cited_passages` does authorized, cited, audited retrieval over PostgreSQL FTS. DATABASE_MODEL §18 notes the missing piece explicitly: "no AI agent yet turns a retrieved passage set into prose." |
| **§20 Character-aware player advisor** | ❌ | No character portrayal profile, no learning-from-play loop, no advisor agent. `ai.agent_roles` has no `player_advisor` role. |
| §20.2 Learning portrayal from session imports | ❌ | Depends on both import and portrayal profiles. |
| **§21 Player participation in scenes** | 🟡 | Interaction schema supports intent/approach as `actions` with descriptions; no player-facing surface. |
| **§22–24 Personal imports, ownership, derived-artifact permission inheritance** | 🟡 | Real foundation: `security.resource_grants` has a `source_document_id` target, `ai.reference_source_campaigns` is a per-campaign retrieval grant with an `is_house_rule` precedence flag, and `core.source_documents` is immutable and hash-identified. **But the grant model is campaign-scoped, not owner-scoped** — there is no "player owns this source and the GM cannot read it" concept, and no capability split between *view source* / *search source* / *use for AI* / *use for validation* / *request approval*. |
| §23.2 GM approval card | ❌ | No approval-request flow for a character option. |
| §24 Permission inheritance for derived artifacts | 🟡 | `ai.reference_passages` inherit their source's campaign grant. Nothing propagates restrictions to summaries, explanations, citations, or cached responses. |
| **§25 Copyright / content policy boundary** | ✅ | Posture already matches: only openly licensed content is seeded, `core.sources` records provenance, and removal (`remove_source_document`) exists. |
| **§26 Player session-note imports** | ❌ | Depends on §6 plus private ownership. |
| §26.4 Multiple accounts of a session | 🟡 | `knowledge.knowledge_versions` + `information_transfers` already model conflicting accounts and distortion — a good foundation for reconciliation. |
| **§27 Context firewall** | ✅ | Among the best-implemented parts. `ai.context_requests.request_kind` is a closed set (`npc_conversation`, `rules_question`, `gm_brief`, `player_summary`, `observer_summary`); the three synthesis tiers are three **separately authorized query paths**, not one payload filtered afterwards; `ai.context_snapshots` retains exactly what was sent. |
| §27.2 Exclusions (GM cannot read player-private material) | 🟡 | Every exclusion involving existing data types is enforced. The player-private exclusions cannot be enforced because player-private data does not exist yet. |
| **§28 Canon / knowledge / belief / theory separation** | 🟡 | Canon, event, knowledge, belief, proposal, and preparation content are all modelled. **Theory is not.** |
| **§29 Proposal and approval workflow** | ✅ | Implemented generically; two proposal kinds wired. |
| **§30–31 Recommended UX and delivery sequence** | 🟡 | Proposal Phase A (visibility and context foundation) is essentially **complete** — that is the platform's strongest area. Phases B through G are largely unbuilt. |

### 4.3 The one genuinely new architectural requirement

**Player-private collaboration (proposal §16, §17, §26, and the player-owned-source half of
§22–24) has no home in the current model, and adding it is not a small extension.**

Everything in the existing security model answers one question: *may this user see this canonical
thing?* Roles grant campaign-scoped capability defaults; character relationships and resource
grants add per-resource access; access groups bundle grantees. All of it is **additive**, and a GM
role accumulates the most capability.

The proposal requires the opposite shape in one place: content that a **GM specifically cannot
read**, enforced in the backend, where the GM is otherwise the most privileged actor in the
campaign. That is a new authorization primitive — not "this grant does not extend to you" but
"this resource has an owner set that excludes campaign-role-derived access entirely."

This has concrete consequences worth deciding deliberately before any of it is built:

1. **A new schema** — call it `collaboration` — for player-authored, non-canonical content:
   threads, comments, notes, bookmarks, theories, and immutable share snapshots. It must not live
   in `knowledge` (that schema describes the fictional world's awareness, a distinction
   DATABASE_MODEL §15 states explicitly) and must not live in `campaign`.
2. **An owner-scoped access path** in `domain.access` that is evaluated *instead of*, not in
   addition to, capability resolution for these tables. `security.resource_grants` can express the
   grant, but `access.has_capability`'s role-default path must be structurally unable to reach
   collaboration rows.
3. **A negative test obligation.** "A GM with `canon.edit` and `access.manage` receives 404 for a
   party-only thread" must be a database-level regression test, and the same must hold for search,
   counts, exports, and every AI context path. The existing non-disclosure test discipline is the
   right model to copy.
4. **A context-purpose extension.** `ai.context_requests.request_kind` gains `player_advisor` and
   `party_planning`, and the corresponding assembly functions must be written so that
   collaboration rows can *only* enter those two paths.
5. **An honest privacy claim.** The proposal §16.1 already gets this right and it should be carried
   into the product documentation verbatim: on a self-hosted deployment, application privacy cannot
   protect players from the server's own administrator, who is usually the GM. Promise "the GM-role
   user cannot reach player-private material through any supported API, search, export, or AI tool",
   never "the GM cannot see it."

Point 5 deserves emphasis because it interacts with Part 5: player-private collaboration is
substantially more credible on a **hosted** deployment than on a GM's own mini-PC. If
player-private collaboration becomes a headline feature, that is an argument for the hosted branch
being the primary product rather than a later add-on.

### 4.4 Recommended changes to plan and scope

**Reordering.** The proposal's build order (session intelligence → rules-aware management →
grounded AI) is sound, but it assumes a foundation the repository does not quite have. Insert the
authoring surface first:

| Order | Work | Why |
|---:|---|---|
| **0 (new)** | **Entity-authoring commands and canon lifecycle** (§1.3) | Import promotion, NPC creation, portrayal profiles, and creature stat blocks all need it. Without it the GM cannot create the content everything else operates on. Currently unscheduled in PLAN.md. |
| 1 | Phase 15 import, scoped to the proposal's §6 workflow | The proposal's flagship differentiator; schema already specified. |
| 2 | Player-private collaboration (`collaboration` schema, owner-scoped access) | Architecturally the riskiest addition; the security model deserves to absorb it before the surface area grows further. Proposal Phase C. |
| 3 | NPC portrayal profiles + `campaign.npc_emotional_state` / `npc_goal_state` | Already specified in DATABASE_MODEL §7.2/§17; unlocks §8, §9, and §20. |
| 4 | Rules content + advancement engine | The proposal's §18/§19 and the "trustworthy recommendations" claim depend on real rules data, which is a **content** problem as much as a code one. |
| 5 | Creature stat blocks + encounter analysis | Genuinely new schema; the most self-contained new feature. |
| 6 | Grounded assistance tiers (rules answers, GM copilot, player advisor) | Phase 12's provider abstraction and context firewall already support them. |

**Documentation changes to make now:**

1. **Add a Phase 0-style authoring workstream to PLAN.md §24** (see §1.3).
2. **Add a `collaboration` schema section to DATABASE_MODEL.md** with the owner-scoped access rule
   stated as an architectural constraint, before any of it is built — this is exactly the
   "extend the domain model explicitly rather than deviate quietly" process CLAUDE.md §5 prescribes.
3. **Add `Theory` to DOMAIN_MODEL.md's vocabulary** as a distinct concept from belief, owned by a
   player (not a character), never canon, and never an input to NPC context.
4. **Record a decision on creature stat blocks** — whether `character.characters` with a
   simulation-level marker covers monsters, or a separate `rules.creature_templates` /
   `world.creature_instances` pair is needed. The proposal's §10 assumes the latter.
5. **Reconcile the marketing category with ADR 0013.** The proposal's positioning ("self-hostable
   campaign intelligence platform") matches the architecture exactly; the *player-private
   collaboration* differentiator does not match single-host self-hosting. Say so explicitly in the
   product documentation rather than discovering it in a support conversation.
6. **Do not adopt the proposal's §32 guardrails list wholesale** — several items it says to avoid
   ("automatic canon changes", "AI access to all content by default", "treating every NPC as a full
   PC", "treating CR as sufficient analysis") are already structurally impossible here, and
   restating them as future constraints understates what the platform has already achieved.

**Scope items in the proposal worth explicitly declining or deferring:**

- **Native transcription** — the proposal already excludes it; keep it excluded. A text import API
  with a documented provider-submission contract is the right boundary.
- **Full rulebook ingestion** — `core.source_documents` plus `ai.reference_passages` already support
  it technically. The legal review the proposal §25 calls for should gate the *feature*, not the
  schema, and the SRD 5.1/5.2 CC-BY-4.0 path is the only one to build against for now.
- **Embeddings / vector search** — DATABASE_MODEL §18 deliberately leaves `ai.embedding_records`
  unbuilt until FTS proves insufficient. That judgment is correct and should survive the proposal's
  RAG language; PostgreSQL FTS over a structured corpus with relational filters is a strong
  baseline and `pgvector` can be added later without a schema rewrite.

---

## Part 5 — Feasibility of a hosted, paid branch

Two candidate topologies were requested: hosted Docker (a VPS or managed container host) and an
AWS-deployed application. Both are feasible. The differences that matter are smaller than the work
they share.

### 5.1 What the shared work is

**Roughly 80% of the effort for either option is application work that is identical in both**, and
none of it is optional for a paid service.

| Requirement | Current state | Work required |
|---|---|---|
| **Tenant isolation** | **No tenant concept exists.** `core.worlds` has no owner column, and `core.worlds.slug` carries a **globally unique constraint** — two customers could not both own a world slugged `faerun`. `security.users` is a flat global namespace with `is_platform_administrator`. | Introduce an account/organization boundary (or make `worlds` owner-scoped and scope `slug` uniqueness to the owner). This is a migration touching the root of the entity graph, so it is much cheaper now than later. |
| **Defence in depth on isolation** | Single `app_read_write` role for all traffic; no row-level security. Isolation is enforced entirely in the query layer. | The query layer is genuinely rigorous and regression-tested, so RLS is not strictly required — but for a paid multi-tenant service, PostgreSQL RLS on tenant-scoped tables is the difference between "one query bug is a bug" and "one query bug is a cross-customer data breach". Recommend RLS as a second layer, keyed on a `SET LOCAL` tenant id per transaction (which `get_connection` is already the natural place to set). |
| **Self-service signup** | None. Accounts are created by `POST /admin/accounts` (platform admin) or by invitation. `bootstrap_admin.py` is DB-direct and fails closed. | Email verification, self-service registration, terms acceptance, account deletion/export (GDPR/CCPA). |
| **Billing** | Nothing. | Plan/subscription/entitlement model, payment provider integration, dunning, plan-change handling, invoices. |
| **Quotas and metering** | Nothing. AI usage is unmetered and uncapped. | Per-tenant limits on campaigns, storage, imports, and especially **AI token spend** — the one cost that scales with usage and can be driven arbitrarily high by a single customer. Meter at `ai.context_requests` / `ai.generated_outputs`, which already exist and already record everything needed. |
| **Distributed rate limiting** | `domain/rate_limit.py` is **in-process** and explicitly documents the limitation: "each Uvicorn worker process has its own independent counters, so a multi-worker/horizontally-scaled deployment enforces the limit *per worker*, not globally." | Move to a shared store. The module's interface (`allow(key, now=...)`) is clean and injectable, so this is a swap, not a rewrite. PostgreSQL can back it (the project already stores idempotency records durably) — no Redis dependency is required. |
| **Per-tenant AI credentials** | One global `DND_AI_AI_PROVIDER_API_KEY` / `_MODEL` / `_BASE_URL` in `config.Settings`. | Per-tenant provider configuration, or a platform key with strict per-tenant metering. Also required: bring-your-own-key, which many prospective customers will want. |
| **Background work** | No worker, no outbox table, despite `SYSTEM_ARCHITECTURE` §10 specifying a transactional outbox. | Imports, AI generation, and email all need async execution once requests are user-facing and latency-bound. |
| **Multi-tenant operations** | Single-tenant runbooks. | Per-tenant backup/restore and export, per-tenant incident isolation, aggregate observability, status page, support access controls with audit. |
| **Legal** | Proposal §25 flags it. | Terms, privacy policy, DPA, subprocessor list, and a real answer on user-uploaded copyrighted rulebooks — which is materially riskier hosted than self-hosted, because the service becomes the distributor. |

**What is already right, and it is a lot.** The platform is unusually well positioned for this:

- **Sessions are PostgreSQL-backed opaque tokens**, not in-process or signed-stateless. Any number
  of API instances can serve any request, and revocation is immediate and global.
- **Idempotency is durable** (`security.idempotent_requests`), so retries are safe across instances.
- **Authorization is centralized** in `domain/access.py` and enforced in the query layer before rows
  leave it — adding a tenant predicate has one natural place to go.
- **The audit trail already exists** (`audit.change_log`, plus the `ai.*` provenance chain), which
  is what a paid service needs for support and dispute resolution.
- **The application boundary is genuinely deployment-neutral** — `api/app.py` and `api/deps.py`
  contain no hosting assumptions, exactly as ADR 0013 claims.
- **Feature flags and a server-authoritative feature manifest already exist**, which is the natural
  mechanism for plan-tier gating.

### 5.2 Option A — Hosted Docker (VPS or managed container host)

**Feasibility: high. This is the recommended first step.**

The deployment artifact is the one you will already have built for Part 3. A VPS (Hetzner, Fly.io,
Railway, DigitalOcean, or equivalent) running the same `compose.yaml` plus managed PostgreSQL gets
you to a paid beta with **no infrastructure work beyond Part 3 and one managed-database swap**.

| Aspect | Assessment |
|---|---|
| Incremental infra work | Minimal — same images, same Compose file, managed PostgreSQL instead of the `db` service |
| Operational burden | Moderate — you own patching, monitoring, and scaling, but on a machine that does not lose power when the house does |
| Cost | Predictable and low: roughly $20–60/month for a small VPS plus managed PostgreSQL, flat regardless of traffic |
| Scaling | Vertical first (which will carry you a long way — this is a low-QPS, high-value-per-request workload), then a second API instance behind the same proxy once rate limiting is shared |
| Backup/restore | `database_recovery.py` works unchanged; managed PostgreSQL adds PITR |
| Fit with existing decisions | **Excellent** — no ADR needs superseding; ADR 0013's own "a move to a VPS is justified if availability, bandwidth, or multi-operator needs exceed the residential host" clause anticipates it exactly |
| Blast radius of a bad deploy | One host, one customer set, one rollback |

**Required changes beyond the shared work:** shared rate limiting (§5.1), a real worker process
(a second container from the same image, once an outbox exists), and per-tenant backup/export.

### 5.3 Option B — AWS

**Feasibility: high, but the currently planned shape is the wrong one for this application.**

`PLAN.md` §31 specifies API Gateway + a single FastAPI Lambda behind an ASGI adapter, with direct
RDS connections. That plan was written to minimize idle cost for a development vertical slice, and
for that purpose it was reasonable. As a paid production target it works against the application's
actual characteristics:

| Lambda mismatch | Why it bites here |
|---|---|
| **Connection pooling** | The application uses a synchronous SQLAlchemy `Engine` with a pool created once per process (`api/deps.get_engine`). Lambda freezes and thaws execution environments, so pooled connections are held across invocations and multiplied by concurrency. RDS Proxy becomes mandatory, not optional — and RDS Proxy has a fixed hourly cost that erodes the whole "no idle cost" premise. |
| **Long AI requests** | `domain/ai_provider` calls `httpx.post(..., timeout=30.0)` synchronously. A 30-second blocking call inside a Lambda invocation is billed for its full wall-clock duration at provisioned memory. API Gateway's default integration timeout (30 s for an HTTP API, a hard 29 s for a REST API) sits at or below the provider timeout, so a slow provider produces a gateway timeout while the Lambda keeps running and billing. Raising it requires a service-quota increase and makes the cost profile worse, not better. |
| **In-process rate limiting** | Per-invocation isolation makes the current limiter meaningless, not merely weaker. It must be replaced before any Lambda deployment, not after. |
| **Background work** | An outbox drained by a polling worker does not fit Lambda; it becomes SQS + EventBridge, which is a different design than `SYSTEM_ARCHITECTURE` §10 describes. |
| **Cold starts** | FastAPI plus SQLAlchemy plus psycopg plus PyJWT/cryptography is a heavy import graph. Expect 1–3 second cold starts on an interactive page load. |
| **Operational complexity** | API Gateway + Lambda + RDS Proxy + RDS + VPC + NAT/endpoints + Secrets Manager + CloudFront + S3 is a large surface for a solo operator relative to one container. |

**A better AWS shape, if AWS is chosen:** **ECS Fargate** (or App Runner) running the *same image*
Part 3 produces, behind an ALB, with RDS PostgreSQL, CloudFront + S3 for the portal, and Secrets
Manager for credentials. This preserves the existing pooled-connection model, the long-request
profile, and the worker design with **no application changes at all** beyond the shared work in
§5.1. `PLAN.md` §31.2 already keeps Fargate "available for workloads that genuinely require
persistent processes" — a pooled-connection, long-request, outbox-draining application is precisely
that workload, and the §31 plan should be amended to say so.

| Aspect | Assessment |
|---|---|
| Incremental infra work | **Substantial** — Terraform for VPC, ALB, ECS/Fargate, RDS, CloudFront, S3, Secrets Manager, ECR, IAM, CloudWatch. The existing `terraform/modules/database` and `secrets` cover roughly the RDS and secrets slice; there is no compute module. |
| Operational burden | Lower per-incident (managed everything), higher per-change (IaC, IAM, deployment pipeline) |
| Cost | Materially higher and usage-coupled: expect ~$100–250/month at low traffic (ALB ~$18, Fargate task ~$15–35, RDS `db.t4g.small` multi-AZ ~$50–60, NAT gateway ~$32 if VPC egress is needed, CloudFront, backups) before any AI spend |
| Scaling | Genuine horizontal scaling and multi-AZ availability |
| Compliance posture | Meaningfully better — the right answer if you ever need SOC 2 or enterprise procurement |
| Fit with existing decisions | ADR 0012 and 0013 both preserve this path explicitly; §31 needs amending from Lambda to Fargate |

### 5.4 Recommendation

**Sequence: Option A first, Option B only on evidence.**

1. **Do the shared work in §5.1 regardless.** It is the actual project, and none of it is
   AWS-specific or Docker-specific. Do the **tenant boundary migration early** — it touches
   `core.worlds` and `core.entities`, the root of the graph, and every month of additional schema
   makes it more expensive.
2. **Launch the paid tier on Option A.** A single VPS plus managed PostgreSQL running the same
   images as the home deployment is the lowest-risk path to real paying customers, and it validates
   billing, quotas, and support before infrastructure cost matters.
3. **Move to Option B (Fargate, not Lambda) on evidence** — measured availability requirements,
   multi-region need, enterprise procurement, or a compliance obligation. The portable application
   boundary means this is a deployment change, exactly as ADR 0013 claims, *provided* the shared
   work is done first.
4. **Amend `PLAN.md` §31 now** to record Fargate (or App Runner) as the AWS compute target for a
   hosted production deployment, with the Lambda plan retained as a historical, cost-optimized
   development option and the four mismatches in §5.3 recorded as the reason.

**Branching strategy.** Do **not** maintain a long-lived `hosted` branch. Everything in §5.1 is
strictly additive to the single-tenant product and belongs on `main` behind configuration:

- Tenant scoping ships as a migration plus a `NULL`/default tenant for self-hosted deployments.
- Billing, signup, and quotas ship as modules gated by a `DND_AI_HOSTED_MODE` setting and the
  existing server-authoritative feature manifest.
- A separate Compose overlay (`compose.hosted.yaml`) and a separate Terraform environment carry the
  deployment differences.

A divergent branch would fork the 107 migrations and the 4,480-test suite, and the self-hosted
product would slowly stop receiving the improvements the hosted one drives. One codebase with a
hosted-mode flag is the same discipline the project already applies to OIDC (optional, all-or-nothing,
production-validated) and to the Phase 12 feature manifest.

---

## Appendix A — Findings register

Severity reflects production exposure, not effort. Every finding below was reproduced during this
review.

| # | Severity | Finding | Location | Remediation |
|---:|---|---|---|---|
| 1 | **High** | **`httpx` is a runtime dependency of the AI provider but is declared only in the `dev` extra.** `domain/ai_provider.py` does `import httpx` lazily inside `OpenAiCompatibleProvider`'s request methods. The `Dockerfile` installs with `uv sync --locked --no-dev` and requests **no extras**, so the production image has no `httpx` — proven by `uv export` (0 matches) vs `uv export --all-extras` (1 match), and by installing the base requirement set into a clean venv (`find_spec('httpx')` → `None`). With an AI provider configured (`API_AI_PROVIDER_API_KEY` or a custom `API_AI_PROVIDER_BASE_URL`, both first-class options in `compose.yaml`), the first AI request raises `ModuleNotFoundError` and returns a generic 500. Invisible to CI because every test job installs `--all-extras`. | `pyproject.toml`, `Dockerfile`, `src/dnd_ai/domain/ai_provider.py:324,397` | Move `httpx` to `[project.dependencies]`. Add a unit test asserting `importlib.util.find_spec("httpx") is not None`, or better, import `httpx` at module top level so a missing dependency fails at import rather than at request time. Consider a CI step that builds the production image and imports `dnd_ai.domain.ai_provider`. |
| 2 | **High (delivery)** | **No world-authoring commands.** 16 of the 22 service commands in `ENTITY_LIFECYCLE.md` §21 are unimplemented, including every `Create*`, the whole canon-status lifecycle, `ArchiveEntity`/`RestoreEntity`, and `CreateTimelineBranch`. No route creates a world, timeline, NPC, location, quest, or item. All world content is produced by direct `INSERT` in `scripts/setup_phase13c_dev_data.py`. Blocks Phase 15. | `src/dnd_ai/commands/`, `docs/ENTITY_LIFECYCLE.md` §21 | Add an authoring workstream to `PLAN.md` §24 (see §1.3). |
| 3 | **Medium** | **Phase 14 operational envelope is unstarted.** No `proxy`, `ui`, `ddns`, or `worker` service; no TLS automation, security headers, `/api` path-strip, SPA fallback, resource limits, log rotation, backup schedule, tagged images, or deploy/rollback script. | `compose.yaml`, `docs/LOCAL_DEPLOYMENT.md` | Part 3, items 1–12. |
| 4 | **Medium** | **The audit-history UI is complete, tested, and unreachable.** `AuditHistory.tsx` (353 lines, 36 statements), `useAuditHistory.ts` (326 lines, 61 statements), `api/auditHistory.ts` (109), `AuditHistory.css` (91), and `AuditHistory.test.tsx` (437) — 1,316 lines total — are imported by nothing except their own test files. `AccessPage.tsx` renders 18 other components and not this one, so `GET /campaigns/{id}/audit-history` has no user-facing consumer. `PHASE13E_ACCESS_CONTRACT.md` §3l describes audit-history categories as delivered. | `portal/src/components/AuditHistory.tsx`; `portal/src/pages/AccessPage.tsx` | Render it in the Access page (or a GM Tools route), or explicitly record it as staged for a later checkpoint. Either way, close the gap between "tested" and "reachable". |
| 5 | **Medium** | **No property-based tests.** `hypothesis` is a declared dev dependency; `grep -rln "from hypothesis\|@given" tests/` returns nothing. `PLAN.md` §26.4 requires five specific targets. | `tests/` | §2.3 gap 1; consider `schemathesis` for breadth first. |
| 6 | **Medium** | **No performance tests.** `PLAN.md` §26.5 names six measurement targets; none exists. | `tests/` | §2.3 gap 2 — assert on `EXPLAIN` plans, not wall-clock. |
| 7 | **Medium** | **No coverage measurement or gate**, Python or portal. Neither `pytest-cov` nor `@vitest/coverage-v8` is a declared dependency; `scripts/verify.sh` never mentions coverage. | `pyproject.toml`, `portal/package.json`, `.github/workflows/ci.yml`, `scripts/verify.sh` | §2.5 stage 1. |
| 8 | **Medium** | **No browser end-to-end suite.** `PLAN.md` §26.7 and Phase 13H require one; no Playwright/Cypress dependency exists. Cookie, CSRF, revocation, and non-disclosure behaviour is unverified in a real browser. | — | §2.5 stage 4 — Playwright + axe against an ephemeral Compose stack. |
| 9 | **Low** | **Tests are never type-checked.** `pyproject.toml`'s `[[tool.mypy.overrides]] module = "tests.*"` is reported unused on every `mypy src` run. ~94,500 lines of test code are unchecked. | `pyproject.toml`, `.github/workflows/ci.yml` | Run `mypy src tests scripts` in CI. |
| 10 | **Low** | **CI type-checks one script.** `mypy scripts/wait_for_ci.py` in CI; `mypy scripts` (7 modules) passes locally today. | `.github/workflows/ci.yml` | Widen to `scripts`. |
| 11 | **Low** | **Portal test flake under load.** `AuditHistory.test.tsx:246` ("Load more") failed under v8 coverage instrumentation and passed both standalone and with `--testTimeout=20000`. The 1,000 ms `waitFor` default is too tight for a slow runner. | `portal/src/components/AuditHistory.test.tsx:246` | Pass an explicit `{ timeout: 5000 }`. Audit other `waitFor` calls that follow a state transition. |
| 12 | **Low** | **`PROJECT_STATUS.md` is stale** — portal counts are 2.8× understated (65/369 vs 160/1,034), and all three of its graded findings are fixed. | `docs/PROJECT_STATUS.md` | Refresh against this review. |
| 13 | **Low** | **`PLAN.md` §27.1–§27.2 contradict §24.0 and ADR 0012**, still describing AWS `dev` RDS as CI's merge gate. | `docs/PLAN.md` §27.1–27.2 | Rewrite to match §24.0. |
| 14 | **Low** | **`DND_AI_FEATURE_AI_NPC_DIALOGUE` gates nothing at the boundary.** The setting exists, `compose.yaml` passes it through, and `config.Settings` validates provider configuration when it is true — but no API route consults it, and `/auth/session`'s feature manifest is the hardcoded constant `_PHASE_12_FEATURES_ALL_DISABLED`. `POST /campaigns/{id}/ai/npc-conversation` is reachable whenever a provider is configured, regardless of the flag. Both behaviours are individually documented and deliberate; together they mean the flag does not do what its name implies. | `src/dnd_ai/api/ai_npc.py:82`, `src/dnd_ai/api/local_auth.py:517` | Either gate the AI routes on the flag and derive the manifest from settings, or rename/document the setting as provider configuration rather than a feature gate. |
| 15 | **Low** | **`DATABASE_MODEL.md` mixes built and unbuilt tables** with inconsistent "built by Phase N" annotations. Ten `character.npc_*` tables and four `campaign.*` state tables appear in "Primary tables" lists without markers and do not exist. | `docs/architecture/DATABASE_MODEL.md` §7.2, §17 | Add a `Built`/`Planned` marker or a per-list convention statement. |
| 16 | **Info** | **Rules content is a token seed set** — 2 classes, 2 subclasses, 2 species, 2 feats, 3 features, 5 spells. No creature stat-block table exists. The "rules-aware" pillar is schema-complete and content-empty. | `database/seeds/rules.*.yaml` | Content work, plus a decision on creature modelling (Part 4 §4.4 item 4). |
| 17 | **Info** | **Six conditional `pytest.skip()` calls** in migration tests. Currently inert (the full run reported zero skips), but a skip that can silently become permanent is a false-green risk. | `tests/database/test_phase{5,8}_populated_upgrade.py` and three others | Convert to explicit assertions on the guarded precondition. |
| 18 | **Info** | **Licensed live Foundry v13 acceptance is still unrecorded**, and `PHASE12_VERIFICATION.md` does not exist — both are named as the remaining exit gates for Phases 11 and 12. | `docs/PHASE11_VERIFICATION.md`; `docs/` | Run and record both. |

## Appendix B — Reproducing this review's measurements

```bash
# Python quality gates
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run mypy scripts

# Full Python suite with branch coverage (needs PostgreSQL 18 on DATABASE_URL)
uv run --with pytest-cov pytest --cov=src/dnd_ai --cov-branch \
    --cov-report=term-missing:skip-covered

# tests/unit in isolation
uv run --with pytest-cov pytest tests/unit --cov=src/dnd_ai --cov-report=term

# Portal suite with coverage
cd portal
npm install --no-save @vitest/coverage-v8
npx vitest run --coverage.enabled --coverage.provider=v8 \
    --coverage.reporter=text-summary --coverage.all \
    --coverage.include='src/**/*.{ts,tsx}' \
    --coverage.exclude='src/**/*.test.{ts,tsx}' \
    --coverage.exclude='src/test/**' --coverage.exclude='src/fixtures/**' \
    --testTimeout=20000
npm run lint
npm run build

# Foundry module
cd foundry-module && node --test

# Finding 1: prove httpx is absent from the production dependency set
uv export | grep -c '^httpx=='             # -> 0  (what the Dockerfile installs)
uv export --all-extras | grep -c '^httpx=='  # -> 1  (what CI/tests install)
```
