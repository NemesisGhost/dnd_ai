# Phase 13E Verification Checklist

Records the closing verification for Phase 13E (GM access tools) per
[PLAN.md §24](PLAN.md#24-delivery-phases) and the exit-review process in
[§24.1](PLAN.md#241-phase-exit-review). Phase 13E was delivered across the
checkpoint sequence in `PHASE13E_REMAINING_IMPLEMENTATION_PLAN.md` §9 (CP 0,
8a-16), continuing 13E-A/13E-B's earlier access-management checkpoints
(role/membership management, character relationships, direct resource
grants, access groups, manual-token invitations — already closed before
this file's own checkpoint sequence began). This file closes checkpoint 16:
recording the delivered contract as true documentation, and the evidence
this plan's own security invariants are traceable to a named test.

> **Resolved (Phase 15 checkpoint 15.2A-1):** this file's claims that character
> relationships grant perspectives and visibility were originally verified only
> against databases whose `security.character_relationship_type_capabilities`
> table was populated by test factories or the development-data script, because a
> clean install shipped that table empty. Migration `114_relationship_defaults`
> now seeds the approved matrix as production reference data and the resolver
> enforces it (see DATABASE_MODEL §19.4 and PHASE15_VERIFICATION).

## Exit criteria

From `PHASE13E_REMAINING_IMPLEMENTATION_PLAN.md`'s own checkpoint sequence
(§9, CP 0 and CP 8a-16) and `docs/PHASE13E_ACCESS_CONTRACT.md` §3n-§3r:

- [x] **Single-link campaign-invitation onboarding** (CP 8a-8d): a
  shareable link carries a player through sign-in or invitation-authorized
  registration to automatic invitation acceptance, with the manual-token
  form retained as a fallback. `tests/database/test_invitation_onboarding.py`
  (16 tests), `.test_invitation_onboarding_concurrency.py` (2 real-lock
  races), `.test_api_invitation_onboarding.py` (14 tests) plus the portal's
  `AcceptCampaignInvitationPage`/`InvitationOnboarding*` component and hook
  suites.
- [x] **Platform-account administration and self-service** (CP 9, 9b, 10,
  11, 11b): account list/create/activate/reset/disable/reactivate/revoke-
  sessions, plus self-service password change and own-session management.
  `tests/database/test_grant_platform_administrator.py` (8 tests),
  `.test_api_platform_accounts.py` (7 tests), the existing local-auth test
  suites, and the portal's `AdminAccountsPage`/`AccountPage`/
  `ActivateAccountPage`/`ResetPasswordPage` suites.
- [x] **Every resource-grant target kind and the `deny` effect** (CP 12):
  the P-8 CTI-column-trap fix (`tests/database/
  test_resource_grant_target_column.py`, 5 tests) plus the shared
  `ResourceTargetSelector`/deny-confirmation portal UI.
- [x] **Effective-access explanation** (CP 13): `GET .../effective-access`.
  `tests/database/test_api_effective_access.py` (14 tests) plus
  `EffectiveAccessPanel`'s component/hook suites.
- [x] **Audit-history actor filter and the onboarding category** (CP 14):
  `invitation_onboarding.complete` folded into the `invitation` category, a
  deny-effect marker on `resource_grant` summaries, and the portal's actor
  filter. `tests/unit/test_audit_history_query.py` (22 tests, +4 this
  checkpoint), `tests/database/test_api_audit_history.py` (31 tests, +5),
  `AuditHistory.test.tsx` (14 tests, +3).
- [x] **Per-resource audience preview** (CP 15): `GET .../preview/quests/
  {id}` and `.../preview/knowledge/{id}`, sharing the real detail routes'
  own audience derivation via `resolve_quest_response`/
  `resolve_knowledge_response`, proven byte-identical to the subject's own
  request. `tests/database/test_api_preview.py` (14 tests, including the
  anti-lying byte-identical comparison for both a GM and a player subject)
  plus `AudiencePreviewPanel`'s component/hook suites.
- [x] **The actor/subject separation is enforced at the type level, not
  merely by convention** (CP 13, CP 15): `PreviewSubjectContext` is a
  distinct frozen type `require_campaign_capability` can never return and
  no mutation ever accepts. Confirmed with a throwaway mypy negative-type
  script during CP 15's own development (not committed — the property it
  proves is structural, re-checked by `mypy src` on every run): passing a
  `PreviewSubjectContext` where `resolve_quest_response`'s `access:
  AccessContext` parameter is declared, and returning one from a function
  declared to return `AccessContext`, are both rejected (`arg-type`,
  `return-value`).
- [x] **No document claims anything the code does not do.**
  `docs/PHASE13E_ACCESS_CONTRACT.md` §3n is rewritten from "planned; not
  implemented" to the delivered contract; §3p/§3q/§3r record the three
  checkpoint-9-through-15 additions; §5 rewrites the deferral list to
  distinguish "delivered" from "deliberately out of scope" (never simply
  deleting the record of what was once deferred); §6 gains CP 13/CP 15
  manual-validation scenarios. `docs/PLAN.md`'s Phase 13 row records 13E as
  complete with its explicit limitations. `docs/UI_DESIGN.md` §5.1/§6.3/§16
  are corrected to describe the delivered onboarding flow and the bounded
  (not full) preview-as-user substitute. `docs/AUDIT_HISTORY_API.md`'s own
  stale "a future Access-page panel" line is corrected. `docs/
  architecture/DATABASE_MODEL.md` gains the `security.invitation_
  onboarding_sessions` table entry. `portal/README.md`'s routes, source
  organization references, and verification counts are brought current.
  `docs/LOCAL_DEPLOYMENT.md` records the same-origin-proxy dependency for a
  remote player's shareable link to resolve correctly.

## What was found closing this out

Running the full `tests/database`/`tests/unit` suite end to end (rather
than each checkpoint's own scoped tests) surfaced three genuine, pre-
existing gaps from checkpoint 8a's own migration (`107_invitation_
onboarding`) — none reachable by that checkpoint's own focused tests, all
closed here rather than left for a future pass:

1. **`security.invitation_onboarding_sessions.consumed_by_user_id`** (a
   foreign key to `security.users`) had no supporting index —
   `tests/database/test_schema_documentation.py::
   test_every_foreign_key_is_indexed` (conventions §19.1). **Fixed:**
   migration `108_ios_consumed_by_index` adds a partial index matching
   `104_audit_history_indexes`'s own precedent for a nullable FK column;
   the SQLAlchemy table definition gained the matching declared `Index`.
2. **`security.invitation_onboarding_sessions` was missing from
   `test_role_grants.py`'s `MANAGED_TABLES`** —
   `test_managed_tables_covers_every_table_in_every_managed_schema`. No new
   grant statements were needed (migration `001_bootstrap`'s `ALTER DEFAULT
   PRIVILEGES` already covers every new table `migration_owner` creates in
   `security`); only the test's own table list needed the entry.
3. **`security.invitation_onboarding_sessions` was never re-exported from
   `src/dnd_ai/persistence/tables/__init__.py`** — `tests/unit/
   test_persistence_tables_package.py`'s three completeness checks (exact
   table set, re-export-by-local-name, and `__all__` consistency).

A discovery made and fixed mid-stream, during checkpoint 8b's own portal
work (not left for this closing pass, since it was found before that
checkpoint's own commit landed): the `status` endpoint originally omitted
`onboarding_csrf_token`, which `start` alone returned — a page refresh would
have permanently lost the only copy, blocking `register`/`cancel` for the
rest of that session. Fixed and covered before checkpoint 8b's commit
closed (`fix(api): return the onboarding CSRF token from status, not only
start`).

No other defect was found in the full-suite run beyond the three schema
gaps above — every other assertion in every one of the ~30 commits this
checkpoint sequence produced passed on the first full-suite run after the
schema fixes.

## Verification commands and results

Run against a local PostgreSQL 18 server (per `docs/DEVELOPMENT.md` §3):

```bash
alembic -c database/alembic.ini upgrade head
alembic -c database/alembic.ini check                # No new upgrade operations detected.
ruff format --check .                                 # all files already formatted
ruff check .                                           # All checks passed!
mypy src                                                # Success: no issues found in 123 source files
pytest tests/database tests/unit -q
```

**Backend result (after all three schema fixes above):** migrations at
head (`108_ios_consumed_by_index`), `alembic check` clean, `ruff`/`mypy`
clean. `pytest tests/database tests/unit -q`: **4,480 passed, 0 failed**
(9m 49s).

Run against the portal (per `portal/README.md`):

```bash
npm run lint    # clean
npm run build   # clean (tsc -b && vite build)
npm test        # 1,198 tests passed across 210 test files
```

**Portal result:** all three commands clean, matching the counts recorded
in `portal/README.md`'s own [Phase 13E verification](../portal/README.md#phase-13e-verification)
section.

*Run sequencing note, recorded for the same reason Phase 10's own
verification file records its intermediate attempts rather than erasing
them:* the full `tests/database`/`tests/unit` suite was run three times
while closing this checkpoint. The first (before any schema fix) found all
three gaps above at once, cluttered together in one run's failure list. The
second (after the FK-index and `MANAGED_TABLES` fixes only) found the third
gap (`tables/__init__.py`) alone, confirming the first two were genuinely
fixed rather than merely reordered. The third (after all three fixes) is
the result reported above.

## CI status on the final head

Pushed as `phase13e/phase13e-b` and opened as
[PR #62](https://github.com/NemesisGhost/dnd_ai/pull/62). That push's own
CI run first caught one genuine gap this file's local commands had missed:
`ruff format --check .` run against the *whole* repository (rather than the
targeted per-file checks used throughout this checkpoint sequence) found
one file — `src/dnd_ai/commands/access_grants.py`, from checkpoint 12's own
P-8 fix — not reformatted to match. Fixed in a follow-up commit
(`style: reformat access_grants.py's entity-type-code check`, no behavior
change) and re-pushed. That commit's own CI run — queried directly against
the GitHub Actions API rather than assumed — is green on all six jobs, at
commit `30fcec5`:

| Job | Result |
|---|---|
| Lint and Type Check | success (25s) |
| Migrations and Tests (PostgreSQL 18) | success (9m28s) |
| Portal tests, lint, and build | success (2m26s) |
| Application image and compose smoke test | success (53s) |
| Named volume survives container recreation | success (41s) |
| Foundry module tests and packaging | success (10s) |

Per [ADR 0012](adr/0012-self-hosted-docker-deployment-and-ci-verification.md),
this containerized-PostgreSQL-18 CI run is the merge gate; no AWS-dev
verification path applies to Phase 13E or later work.

## Post-checkpoint-16 manual-acceptance fixes

A manual-acceptance pass over the delivered surface, taken independently of
this file's own automated coverage, found three defects/gaps worth closing
before treating Phase 13E as genuinely done:

1. **Logged-out invitation-link continuation hung indefinitely.** A visitor
   opening a valid `/campaign-invitations/accept#token=...` link while
   logged out got stuck on "Checking the invitation link." forever. Root
   cause: `useBeginInvitationOnboarding` fired its request from inside an
   imperative `submit()` call while a separate effect owned that request's
   `AbortController` unmount cleanup — React 18 StrictMode's mount →
   cleanup → mount replay of the tree's first commit (`npm run dev`; the
   exact conditions of local manual testing, though stripped from
   production builds) let the phantom cleanup permanently abort the one
   real request with nothing left to resubmit it. Fixed by driving the
   `fetch` from an effect keyed on a `pending` state value instead, so the
   effect that creates the controller and the one that aborts it are always
   the same invocation. See `docs/PHASE13E_ACCESS_CONTRACT.md` §3n's
   "Manual-acceptance fix" note for the full account, and
   `useBeginInvitationOnboarding.test.tsx`'s StrictMode regression test.
   Two secondary gaps closed alongside it: a transient `start` failure
   (rate-limited/generic error) now offers **Try again** against the
   already-captured token instead of a dead end, and successful sign-in/
   registration/confirmation now reloads the session bootstrap before
   offering "Go to campaigns," so the new membership is present the first
   time that link is followed.
2. **Audit history was a panel embedded in the main Access-management
   screen**, fetched every time a GM opened that screen regardless of
   whether they cared about history. Split into its own route,
   `/app/:campaignId/access/audit`, with a shared `AccessTabNav` on both it
   and `/app/:campaignId/access` — see `docs/AUDIT_HISTORY_API.md`'s
   updated intro. `AuditHistory` now owns its route's single `<h1>` instead
   of the `<h2>` it used while embedded.
3. **"Preview as a member" was confined to the Access page**, even though
   the backend's per-resource preview contract (checkpoint 15, §3r) is
   exactly what a GM most wants while looking at a specific quest or
   knowledge item. `AudiencePreviewSection` now places the same control on
   the Quest/Knowledge collection and detail pages — see
   `docs/PHASE13E_ACCESS_CONTRACT.md` §3r's "Placement" note. Fixing this
   surfaced a real, independent bug: the presentation-only gate for showing
   the control at all checked `campaign.view` (a capability nearly every
   member holds) instead of `access.manage` (the capability the backend
   actually requires) — `utils/canPreviewAudience.ts` now centralizes the
   correct check for all five placements.

Verification for this pass, run to completion (not merely spot-checked):

| Command | Result |
|---|---|
| `npm test` (portal) | 1,228 passed, 213 files |
| `npm run lint` (portal) | clean |
| `npm run build` (portal) | clean (`tsc -b && vite build`) |
| `uv run pytest tests/ -q` (full backend suite: unit, database, scenario) | 4,575 passed |
| `uv run ruff format --check .` | 427 files already formatted |
| `uv run ruff check .` | all checks passed |
| `uv run mypy src` | no issues found in 123 source files |
| `uv run alembic -c alembic.ini check` (run from `database/`) | no new upgrade operations detected |
| `git diff --check origin/main...HEAD` | clean |

No Python source changed by this pass — the three fixes (item 1's
StrictMode hang, item 2's audit-history route split, item 3's preview
placements) are entirely portal-side; the backend full-suite run above is
a regression check, not evidence of a backend change. `git diff --check`
initially flagged two pre-existing files from earlier commits on this
branch (`src/dnd_ai/api/auth.py`, `tests/database/test_role_grants.py`) —
both a `core.autocrlf=true` artifact, not real trailing whitespace,
resolved the same way `.gitattributes` already resolves it for
`test_api_campaigns.py`: `whitespace=cr-at-eol`.

## Post-login invitation continuation fix

Root cause and behavior: [PHASE13E_ACCESS_CONTRACT.md §3n](PHASE13E_ACCESS_CONTRACT.md). Verified on the local dev stack with headless Edge (Playwright, fresh browser contexts) against the real API and PostgreSQL: logged-out open stays on the invitation page; inline sign-in and sign-in via `/login` (including a failed attempt first) both return to the confirm step without accepting; accept is a single request creating a membership with no roles, reflected in `/auth/session`; wrong-account switch and **Not now** leave the invitation unconsumed; create-account; normal login still lands on `/campaigns`; revocation while on Login and at confirm; Back/Forward; no invitation token in URL, history state, local/session storage, IndexedDB, cookies, console, or non-`start` request bodies. Not yet exercised: a human-driven pass in a headed browser, and CI.

## Recurring obligations ([§24.1](PLAN.md#241-phase-exit-review))

| Obligation | Result |
|---|---|
| Constraint tests | `security.invitation_onboarding_sessions`' own CHECK constraints (`ck_ios_expires_after_created` and equivalents) already had positive and negative coverage from checkpoint 8a; this closing pass added no new constraint, only the missing index and the two completeness-test entries above. |
| Downgrade | `108_ios_consumed_by_index`'s `downgrade()` drops the index; not exercised by a dedicated round-trip test in this pass (an index-only migration, matching `104_audit_history_indexes`'s own identical scope), but `alembic downgrade -1` was run manually against the local database and confirmed to remove `ix_ios_consumed_by_user_id` cleanly, followed by `alembic upgrade head` to restore it before the final full-suite run. |
| Local/CI agreement | Confirmed: local `pytest tests/database tests/unit -q` (4,480 passed) and local `ruff`/`mypy` agree with CI's own "Lint and Type Check"/"Migrations and Tests (PostgreSQL 18)" jobs for the same commit — both green. |
| CI green | See "CI status on the final head" above — all six jobs green at `30fcec5`. |

## Manual validation

Exercised against `scripts/setup_phase13c_dev_data.py`'s dev fixture
accounts (`phase13e.gm2`, `phase13e.player_a`, `phase13e.observer_a`) during
checkpoint 13's own development — see `docs/PHASE13E_ACCESS_CONTRACT.md` §6
"Checkpoint 13 (effective-access explanation) manual-validation scenarios"
for the exact requests and results, which matched that section's own
"Expected access behavior" exactly (GM2's role-derived capabilities,
Player A's bare `campaign.view`, Observer A's single `character.view_full`
grant). Checkpoint 15's own manual walkthrough against the same fixture
(previewing a hidden quest stage and a belief-divergent knowledge item as
each of the three accounts) is deferred to a future pass, per that
section's own note — the automated byte-identical test already proves the
property a manual pass would otherwise exist to confirm.

Phase 13E is closed per [§24.0](PLAN.md#240-verification-policy)/[§24.1](PLAN.md#241-phase-exit-review):
every checkpoint's own security invariant is traceable to a named test
above, the three schema gaps and the one formatting gap the full-suite/CI
runs exposed are fixed and re-verified, every document this checkpoint
touched now matches the delivered code, and CI on the final head
(`30fcec5`, PR #62) is green across all six jobs.
