# P03-A implementation plan: public profiles, revelation and audience-safe character reads

**Status:** Approved planning document. A0, A1, P0, P1, A2a and A2a-R are implemented and independently reviewed (A2a and A2a-R: PASS WITH NONBLOCKING FINDINGS; handoff `523ae5c`). D7 and D8 are approved (recorded 2026-11-07). A2b-1 and A2b-2 are implemented and reviewed (handoff `a9ec4c4`). A3 is designed and finalized (§10; D4, D5 and D9–D12 approved, §10.15, including the D9-a candidate-statement cutoff approved 2026-11-08) and not implemented. P2, the shared idempotency key lock, is implemented at `d36d565` and independently reviewed (PASS WITH NONBLOCKING FINDINGS; record below §10). A3a now needs P3, committing the request transaction before the response (DEF-022, §11), which is designed and not implemented. The plan was committed on its own as the design commit (`3b3d637`) before A2a's code.

- **A0** is implemented at `fca3ac7`.
- **A1** is implemented at `68dc902` through `6a5773d`. That covers the D3 ownership gate, DEF-011, DEF-013 and the reveal delegation. Its record is in [the A1 design](PHASE14_15_P03A_A1_OWNERSHIP_AUTHORITY_DESIGN_2026-11-06.md) §8. The independent re-review passed at `fc20e8d`. CI is pending until push, and an intermittent race-test timeout is still unresolved. It has now been seen in the A1 lock-wait tests twice in full suites (`test_campaign_owner_caller_expiry.py` once, and `test_character_reveal_delegation.py::test_a_grant_that_waits_on_ending_the_gms_membership_is_refused` once: the request was alive but no session waited on a lock within 15 s), each passing on every rerun. That test now observes its blocker through `pg_blocking_pids` (A2 handoff, below); the cause of the missing wait is not established.
- **D1 and D2** were approved by the owner and recorded on 2026-11-07 (see "Decisions still needed").
- **D3** was approved on 2026-11-06.
- **D8** was approved by the owner on 2026-11-07 as proposed (see "Decisions still needed").
- **D7** was approved by the owner on 2026-11-07 (see "Decisions still needed"); A2b's design follows it (§9).
- **D7-a to D7-f**, the points D7 left open, were approved by the owner in conversation and recorded on 2026-11-07 (§9.10).
- **D4-C, D5-c, D9, D10-a, D11-a and D12-a** were approved by the owner in conversation and recorded on 2026-11-07 (§10.15).
- **D9-a's candidate-statement cutoff** (§10.4) was approved by the owner on 2026-11-08.
- **Still open:** D6, which blocks A4 only.
- **Revision of 2026-11-07, after an independent CHANGES REQUIRED review.** The review text is not in the repository; this revision follows the owner's summary of it.
  - The recovery deadlock is now a prerequisite commit, P0 (§6).
  - The draft-read and deny policy is now proposed decision D8.
  - The release fingerprint now includes `character_id`.
  - Two problems in the first A2a design are fixed (§5.8):
    - the release's lock order inverted against `create_resource_grant`;
    - `canon.edit` denies on a character were read under the wrong key.
  - A second deadlock that predates A2 was found and reproduced, DEF-015 (proposed, §6.6).
- **P0** is implemented at `4dd56fd` (DEF-014). Its independent review is complete (recorded 2026-11-07); its one nonblocking harness finding is addressed by P1's `LockRace` (§7.7).
- **P1** is implemented at `edf46ca` (DEF-015) and its independent review is complete (recorded 2026-11-07). `LockRace` is in `tests/lock_race_support.py`.
- **Revision of 2026-11-07, DEF-015 design.** The correction is prerequisite commit P1 (§7), for Sonnet.
  - It was reproduced on a disposable database in both orders.
  - It also deadlocks with ending the added member's membership, ending the adding manager's membership, and the A2a release path.
  - It changes A2a in one place: the release takes the caller's membership `FOR SHARE`, not `KEY SHARE` (§5.8, §7.6).
- **Revision of 2026-11-07, after the independent A2a review.** The review text is not in the repository; this revision follows the owner's summary of it.
  - Neither D8 deny can be created through the application: `create_resource_grant` refuses a character entity under `entity_id`, the only key every reader consults (§8, proposed DEF-018).
  - The correction is A2a-R (§8), one bounded commit for Sonnet, required before A2a's review closes.
  - Three policy points that D8 does not settle are listed in §8.8 (Q1–Q3).
- **Revision of 2026-11-07, A2b design under approved D7 (§9).**
  - The design restricts copied legacy text by deriving the restriction from the field's origin plus a per-field restriction watermark (one additive migration).
  - It withholds restricted fields from readers who fail the source's read rule, and refuses text writes into them.
  - It refuses a release that would include a withheld field.
  - The release now takes the world row `FOR SHARE` first.
  - It is split into A2b-1 (the restriction) and A2b-2 (the copy).
- **Revision of 2026-11-07, after an independent CHANGES REQUIRED review of the A2b design.** The review text is not in the repository; this revision follows the owner's summary of it.
  - **The defect.** The first version lifted a field's restriction once any release came at or after its copy. A permitted GM could then append, or restore, unreleased source text after a release, and restricted readers would see it at once.
  - **The rule now.** Every content change to a copied field advances that field's restriction watermark, and the database enforces this. A release lifts the restriction only when it covers the watermark, which means it holds the field's current text. Editing another field never moves it.
  - **Tests and migration.** The tests gain the excerpt-append and restore regressions, plus mixed-field, unchanged-field, clear, recopy, stale-write and keyed-retry cases. The migration gains a preflight and a fail-closed downgrade.
  - **Recorded.** D7-a to D7-f are now owner-approved (§9.10), and kind stability is recorded as an application-path assumption (§9.1).
- **Revision of 2026-11-07, A3 design (§10).**
  - **What it designs.** The four audience kinds: storage (migration 145), commands, revocation, lifecycle hooks, audit, retries and same-campaign checks.
  - **Source-tagged.** Revelations sit in `AccessContext` as a source of their own.
  - **Every consumer traced.** The design traces every consumer of the shared discovery bundle.
  - **One lock-order change.** `end_campaign_membership` takes the actor's membership `FOR KEY SHARE`, then the campaign row `FOR UPDATE`, before it closes revelations. Without this, a `campaign_current` snapshot taken concurrently keeps a departing member, who would regain the revelation on rejoining.
  - **Split.** A3 becomes A3a (inert storage and commands) and A3b (discovery).
  - **Decisions.** D4 and D5 are set out with concrete options. Four new owner decisions, D9–D12, cover what OD-17 and the code leave open.
- **Revision of 2026-11-07, A3 finalized after the owner's approvals (§10.15).**
  - **D5-c, release summaries (§10.12):** how release summaries are authored and snapshotted; how older releases without one display (`null`, no fallback); and how search, counts and sorting use the caller's projection.
  - **D4-C, the party roster (§10.13):** the exception is reconciled with the shared discovery rule. It is confined to one route and one function, and kept out of discovery by structural tests and a containment regression.
  - **D11, released profiles (§10.14):** the reader rule is specified.
- **Revision of 2026-11-08, the membership-end concurrency matrix (§10.8).**
  - **What it traces.** Membership end against recovery, role assignment, revocation and change, both kinds of ownership transfer, revelation creation and revocation, snapshots and direct grants, keyed and unkeyed. It was probed on the disposable test database.
  - **Two corrections to A3 (§10.4).**
    - `campaign_current` creation locks the campaign's open memberships before the campaign row. Its snapshot insert otherwise deadlocked with ending a member, in both orders.
    - Both revelation routes reserve their idempotency key after the lock phase. Reserving first deadlocked with ending a membership.
  - **The explicit campaign lock in end stays, for a new reason.** Snapshots no longer depend on it. It is needed because a revocation takes the campaign row before the revelation row (A3-V3).
  - **Three pre-existing cycles** were found and proposed as DEF-019 to DEF-021 (§10.11). None blocks A3.
  - **The untraced-cycle deferral is removed.**
- **Revision of 2026-11-08, after the independent review of the matrix.** The review text is not in the repository; this revision follows the owner's summary of it.
  - **Reservation and replay moved (§10.3, §10.4).** For create and revoke they now come after the fresh, under-lock reveal-authority check and the whole-character deny check. A replay is therefore refused to a caller who lost authority, or came under a deny, after the route's pre-check.
  - **Reservation waits traced (§10.4).**
    - The caller's account is now locked after the campaign row (step 5a). Locked before it, it deadlocked with `add_campaign_member` (probe ACC-1b).
    - The reservation's remaining wait, on a same-key request, can outlast an expiry, so authority is judged again after it (step 8b). *Withdrawn by the next revision: with the key lock the reservation cannot wait.*
  - **Keyed HTTP regressions** are now explicit A3a acceptance criteria (§10.10, criterion 4).
  - **Every A3a race is real.** Each is a command or HTTP race on migration 145's schema and the real request transaction, asserting the audit, receipt, snapshot, revelation, membership and role state (§10.9). The §10.8 SQL probes are design evidence only.
  - **The D9-a candidate-statement cutoff was stated (§10.4) and marked pending owner confirmation.** The owner approved it later the same day (next revision).
- **Revision of 2026-11-08, after the second independent review: the cross-route idempotency deadlock.** The review text is not in the repository; this revision follows the owner's summary of it.
  - **The cycle, reproduced (§10.8.9).**
    - A same-actor keyed request on an existing route reserves key K before its locks. A3, holding its lock phase, then waits for K at its late reservation, and the existing request waits for A3's locks.
    - The reproduction used the real `POST …/memberships/{id}/end` route through `TestClient`, against an A3 SQL stand-in (design evidence).
    - It gave 40P01 in both orders. In one variant the end route returned 200 although its transaction rolled back.
  - **The fix:** a transaction-scoped advisory key lock, taken before any row lock: inside `begin_idempotent_request` for every route, and at A3's new step 0.
    - A3's reservation then cannot wait, so step 8b is withdrawn.
    - It is a shared prerequisite, **P2** (§10.11). Every reserving route was evaluated.
  - **Outcomes and acceptance.** Same-route and cross-route outcomes are specified, including different payloads and a first request that rolls back (§10.8.9). They are A3a acceptance cases (§10.9 item 5, §10.10 criterion 4).
  - **API contract changes** are surfaced (§10.3).
  - **New pre-existing defect, proposed DEF-022:** a failure at commit reaches the client as the handler's success, because the request transaction commits after the response (probe HEAD-C1).
  - **D9-a's cutoff is approved.**
  - **The lock wording is narrowed.** Held locks stop allowed decisions from becoming refused; they need not stop changes that only remove restrictions.
- **P2** is implemented at `d36d565`. Its independent review returned PASS WITH NONBLOCKING FINDINGS: the 15 P2 tests and a 55-test focused run passed, and three nonblocking findings were recorded (caller-order coverage, the A3 call-site guard, the outer-transaction harness). The record is in "P2 implementation and review record", below §10.
- **Revision of 2026-11-08 at `c705ee7`: the commit-before-response correction, P3 (§11).** The owner made DEF-022's correction a requirement for A3a.
  - **Traced.** FastAPI 0.141.1 exits `scope="function"` dependencies after the handler and serialization and before the response is sent. It exits request-scoped dependencies, including `get_connection`, after the response is sent.
  - **Reproduced** through the real membership-end route, with a deterministic commit-time failure (a test-only deferred trigger). HEAD answers 200 with nothing persisted, for keyed (23000) and unkeyed (40P01) requests and for the real retention-trigger race. At HEAD a success is not yet visible when the response starts, and P2's key lock is still held then.
  - **The correction:**
    - one function-scoped `commit_request_transaction` dependency installed app-wide in `create_app`;
    - `get_connection` takes `Request` and registers its connection.
    - No route signature changes. A per-declaration scope was rejected because a mixed declaration opens a second transaction (probe M1).
  - **A prototype** in a throwaway copy returned 500 and persisted nothing in the same cases. It made every success visible, and released the key lock, before the response.
  - **New finding.** P2's `test_a_different_key_takes_its_own_key_lock_without_queueing_behind_a_held_request` passed only because of DEF-022. Its second request is a DEF-019 K1 deadlock victim at COMMIT; at HEAD it answers 200 and persists nothing. P3 corrects the test (§11.8, T8).
  - *Parts of this revision were wrong and are corrected by the next one:* the claim that engine-backed routes do not use the request transaction, the claim that no route signature changes, and the prototype failure totals.
  - **DEF-022 is regraded to 6, Medium, and is blocking for A3a** (§10.11).
- **Revision of 2026-11-08, after the independent CHANGES REQUIRED review of P3.** The review text is not in the repository; this revision follows the owner's summary of it. §11 is rewritten.
  - **Routes classified by their full effective dependency graph** (§11.2): 333 request-transaction routes, 8 engine-backed routes, `readyz` and `healthz`.
    - The eight engine-backed routes are `ai_npc` ×2, `ai_synthesis`, combat sync and `reference_corpus` ×4.
    - They do hold a request transaction through their authorization dependency. At HEAD it stays idle in transaction across the AI provider call; for a cookie session it locks `security.browser_sessions` throughout.
  - **Engine-backed routes end their authorization transaction before any engine-side effect** (`end_request_transaction`, §11.4.3). No transaction is held across a provider call, and an authorization-commit failure precedes every engine effect (probes AE1, AE2).
  - **Guarantees are stated per class** (§11.5): which failures guarantee rollback, and which can follow committed effects.
  - **Serialization, rollback failure, cancellation and an uncertain commit are designed and probed** (§11.4.4–§11.4.7; S1, RB1, CX1, U1). The commit dependency becomes async, so it sees a cancellation; its COMMIT or ROLLBACK runs in a shielded worker thread.
  - **New tests:** T10, uncertain commit then a same-key replay; T9, a deterministic DEF-019 two-ends regression, kept separate from T8's independent-key test; T12, real-route engine-backed coverage; T16, `uv lock --check`.
  - **`uv.lock`:** the FastAPI floor changes one `requires-dist` line, verified in a throwaway copy (§11.7).
  - **The P2 review record is corrected** to the review's findings: caller-order coverage, the A3 call-site guard, and the outer-transaction harness.
  - **The prototype failure totals are reconciled from the log** (§11.9). The earlier "54" was 67, the 40 handshake timeouts are left unattributed, and reruns are kept separate.
- **Amendment of 2026-11-08: P3's cancellation acceptance (§11.4.2, §11.4.6, §11.8).** It follows the latest review, whose text is not in the repository.
  - **Barrier-held tests now cancel the request while COMMIT or ROLLBACK is actually executing in the worker thread.** They are specified by a common barrier protocol: observe entry, deliver the cancellation, hold, prove no close or pool return, release, assert order, no response and lock release, with bounded waits and guaranteed release.
  - **Split by what each layer can prove:**
    - T11b, mocked lifecycle ordering with a fake connection;
    - T11c, real PostgreSQL connection state, pool return, locks and outcome;
    - T11a, the existing handler-phase cancellation test, kept as distinct coverage.
  - **Rollback failure is covered after a handler exception (T7, T11b) and after a cancellation (T11b, T11c).** The original exception or the cancellation is preserved, the failure is logged by class, and the connection is invalidated.
  - **T15 is extended** to the FastAPI and anyio behaviours P3 relies on.
  - **Design change from the probes:** `checkpoint_if_cancelled()` after a successful shielded commit. Without it, a cancellation delivered during COMMIT surfaced only at Starlette's later send (probe L1).
  - **Probed on prototype v2** (L1–L4, B1–B5; §11.3).

**Baseline:**

- §1–§4 and the A0 criteria were checked at `phase15/completion` `e1619db2aee132666705c2d7372fcc0a1769394e`.
- The A2 design (§5) was checked at `6a5773d89fc085f705c860825cb69d75de4db1dd`. No later configuration-verification commit exists.
- The DEF-015 design (§7) was checked at `4dd56fda34c5136ff1e288b7a180ba981dd7f41e`.
- The grant-target correction (§8) was checked by reading source at `0b4704cacef5a49ed24c65068938d28ad6eefc93` (A2a). Nothing was run for it.
- The A2b design (§9) was checked by reading source at `523ae5cbf947af230e1d7a5409912c1039e43a69` (the A2a handoff, on A2a-R `f66240a`). Nothing was run for it.
- The A3 design (§10) was checked by reading source at `a9ec4c4b7a14d7c5236525b2121da8ba6f01475d` (the A2b review handoff). Nothing was run for it.
- The membership-end matrix (§10.8, with §10.4 and §10.11) was traced and probed on 2026-11-08 at the same commit (§10.8, "Method").
- The P3 design (§11) was traced and probed on 2026-11-08 at `c705ee79351ac84d6ac23ff8340aa07278881ac7`, which contains P2 (`d36d565`). The installed and locked versions are FastAPI 0.141.1, Starlette 1.3.1, SQLAlchemy 2.0.51, psycopg 3.3.4 and Uvicorn 0.52.0. Its prototype ran only in a throwaway copy outside the repository.

Every code claim was checked by reading source at the stated commit. No application code, schema or committed test was changed to produce this plan. The DEF-014 and DEF-015 reproductions, and the §10.8 probes, ran throwaway probes on the test suite's per-run disposable PostgreSQL 18 database (§6.1, §7.1, §10.8). The §10.8 probes are kept outside the repository and are not committed.

**Audience:** the owner, P03-A implementers and independent reviewers.

**Governing documents:**

- [PLANv2.md](PLANv2.md) §15H (P03-A checkpoint and migration boundaries).
- [R19_FOUNDATION_IMPLEMENTATION_PLAN.md](R19_FOUNDATION_IMPLEMENTATION_PLAN.md): R19-P1, §5.1 actor contract, §8 tests T6, T7, T82, T85.
- Accepted ADRs [0021](adr/0021-shared-actor-identity-control-and-authoring-responsibility.md) (§2.5, §2.7–§2.9, §4.1, §4.7–§4.8, §6, §7), [0022](adr/0022-creature-templates-combatants-and-promotion.md) and [0023](adr/0023-rules-engine-calculation-validation-and-source-authorization.md).
- [The A1 design](PHASE14_15_P03A_A1_OWNERSHIP_AUTHORITY_DESIGN_2026-11-06.md): §3 lock order and §8 implementation record. A2 must keep both unchanged.
- Design inputs: [PHASE14_15_APP_INTERACTION_INVESTIGATION_2026-11-01.md](PHASE14_15_APP_INTERACTION_INVESTIGATION_2026-11-01.md) §D6 and [PHASE14_15_REMAINING_WORK_AND_HANDOFF_2026-11-02.md](PHASE14_15_REMAINING_WORK_AND_HANDOFF_2026-11-02.md) §6, including the owner-approved 2026-11-06 reveal-authority and encounter-reference policies, which this plan treats as requirements.

---

## Recommendation

**Next: P3, commit before the response (§11, for Sonnet); then A3a, then A3b (§10, for Sonnet); then A4 once D6 is decided.** P2 is done (`d36d565`, reviewed).

- **A3a** has no effect on any audience response.
- **A3b** makes revealed characters discoverable through the one shared bundle. They cannot be opened until A4.
- **Decisions:** D4-C, D5-c, D9, D10-a, D11-a and D12-a are approved (§10.15). The D9-a candidate-statement cutoff (§10.4) is approved (2026-11-08).
- **Concurrency (2026-11-08):**
  - A3a carries §10.4's two lock corrections and §10.9's race tests.
  - The pre-existing DEF-019 to DEF-021 (§10.11) are not prerequisites.
  - **P2, the idempotency key lock, is a prerequisite for A3a's keyed routes** (§10.11). Without it, a same-key request on another route deadlocks with A3 (§10.8.9). *Done: `d36d565`, reviewed.*
  - **P3, commit before the response (DEF-022), is a prerequisite for A3a** (§11), by the owner's direction of 2026-11-08. Without it, a request whose commit fails, including a DEF-019 deadlock victim, answers 2xx with nothing persisted.
  - DEF-019, keyed requests deadlocking on the portal path, should be fixed before A6.

*Previous recommendation (2026-11-07, done; A2b-1 and A2b-2 implemented and reviewed, handoff `a9ec4c4`):* A2b-1, then A2b-2 (§9, for Sonnet), then A3. A2a and its correction A2a-R are implemented and reviewed (handoff `523ae5c`). D7 is approved. A2b-1 adds the D7 restriction (withholding, the save rule, the release check and the release's world lock) before A2b-2 adds the copy itself, so no commit has a copy path without its restriction. D7 and D7-a to D7-f are approved (§9.10); nothing in A2b waits on a further decision. The design was revised after an independent CHANGES REQUIRED review, and the revised design has not yet been re-reviewed.

*Previous recommendation (2026-11-07, done):* correction A2a-R (§8), then the close of A2a's review. A2a-R was implemented at `f66240a`.

- **P0** (§6) fixes the deadlock between `lock_authoring_scope` and administrative recovery. It is implemented at `4dd56fd`; its independent review is complete.
- **P1** (§7) fixes DEF-015: adding a member to an access group deadlocks with that member's authoring write (SQLSTATE 40P01, reproduced in both orders).
  - The same command also deadlocks with ending the added member's membership, ending the adding manager's membership, and A2a's release.
  - The fix changes lock order and lock modes in one command, `add_access_group_members`. It adds deterministic regressions and a failure-safe race harness that also closes the P0 harness finding.
  - Scope and acceptance criteria are in §7.8. It is one bounded commit on top of `4dd56fd`. **Recommend landing it before any A2a code**, because A2a's release lock order (§5.8) now depends on it.
- **A2a** is the public-profile draft and release, designed in §5, with acceptance criteria in the last section. Its read and deny rules depend on D8, which is proposed below for owner approval. A2a starts now: P0 and P1 are reviewed and D8 is approved.

The rest of the A2 track:

- **A2a** covers storage, draft editing, release under `character.reveal`, and the GM reads.
- **A2b** is the legacy copy aid under approved D7 (§9): copied text stays withheld from readers who cannot read its source until it is released.
- **D5 and D6** decide whether a release carries a display name, summary, species or size. Each would be an additive column, so neither blocks A2a. Both must be answered before A4 fixes the audience response shape.
- **D4** waits until A3.

*Original recommendation (2026-11-06, done):* start with slice A0, the `active_encounter_id` filter, implemented at `fca3ac7`.

---

## 1. `character.reveal`: storage and enforcement

**What exists today.** No `character.reveal` code, table or delegation exists.

- Role capabilities are the union of `security.role_capabilities` rows ([access.py:1029-1046](../src/dnd_ai/domain/access.py#L1029-L1046)).
- The resource-grant catalog leaves out administrative codes and `character.discover` ([access.py:129-141](../src/dnd_ai/domain/access.py#L129-L141)).

**Storage.**

- Add `character.reveal` to `security.capabilities` for vocabulary, through a migration INSERT. The seed is frozen, so follow the pattern in migration 139.
- Never resolve it from `role_capabilities` or `resource_grants`. Reject such rows with a trigger, which is a local integrity rule under DATABASE_CONVENTIONS §20.4.
- This applies the same "two sources only" rule ADR 0021 §2.7 sets for `character.assign_control`.

**New table `security.character_reveal_delegations`** (append-style, never edited in place):

- `campaign_id`, `grantee_campaign_membership_id`
- **`gm_membership_role_id`**: the grantee's specific live built-in `gm` assignment
- `granted_by_membership_id`, `granted_at`, `reason`
- `revoked_at`, `revoked_by_membership_id`, `revocation_reason`, `end_reason`
- One live row per grantee, enforced with a partial unique index.

**Resolver.** Add `resolve_reveal_authority(connection, campaign_id, membership_id) -> {owner | delegation | none}` in `domain/`. It returns:

- `owner` when the membership is active and holds a live **built-in** `campaign_owner` row (template with `campaign_id IS NULL`, not revoked or expired, role active);
- `delegation` when an unrevoked delegation exists, its `gm_membership_role_id` row is still live, and the membership is active.

Commands (grant, revoke, release, reveal, revoke-revelation) re-read authority under lock and never trust a cached `AccessContext`. Lock order follows ADR 0021 §2.8 for OD-4a:

- **Grant or revoke delegation:** grantee membership and role rows `FOR UPDATE`, then the campaign `FOR UPDATE`, then re-check that the caller holds the built-in owner role, then the delegation row.
- **Release or reveal:** the caller's owner or `gm` role row and delegation row `FOR SHARE`, then the character's `core.entities` row, then the target rows.

This makes a GM role revocation or delegation revocation serialize with an in-flight release.

**Why bind to the `gm` role row.** It enforces "restoring GM status requires a fresh grant" across every path:

- re-assigning a role always inserts a new row ([memberships.py:454](../src/dnd_ai/commands/memberships.py#L454), [:743](../src/dnd_ai/commands/memberships.py#L743), [:919](../src/dnd_ai/commands/memberships.py#L919));
- there is no command that updates `expires_at`;
- `end_campaign_membership` revokes every role row ([memberships.py:1112-1123](../src/dnd_ai/commands/memberships.py#L1112-L1123)).

So a restored GM always holds a different row, and the old delegation can never come back. Close delegations explicitly (with an `end_reason`) inside the commands rather than through a trigger chain, per §20.4 and the precedent in [memberships.py:1125-1162](../src/dnd_ai/commands/memberships.py#L1125-L1162).

### Every path that changes grant eligibility

| Path | Grantor (owner) | Recipient (GM) / delegation | Required P03-A handling |
|---|---|---|---|
| `create_campaign` (creator gets owner + gm) [campaigns.py:613](../src/dnd_ai/commands/campaigns.py#L613) | gains | gains GM status, no grant | none |
| `assign_membership_role` [memberships.py:337](../src/dnd_ai/commands/memberships.py#L337) | owner may be assigned | `gm` assigned → new row, no grant | none |
| `add_campaign_member` with initial role [memberships.py:779](../src/dnd_ai/commands/memberships.py#L779) | same | same | none |
| `revoke_membership_role` [memberships.py:484](../src/dnd_ai/commands/memberships.py#L484) | owner loses | `gm` row revoked → grant ends | close delegation with `end_reason` |
| `change_membership_role` [memberships.py:591](../src/dnd_ai/commands/memberships.py#L591) | either direction | `gm`→X ends it; X→`gm` is a new row | close on the `gm` side |
| `end_campaign_membership` [memberships.py:964](../src/dnd_ai/commands/memberships.py#L964) | loses | ends | close delegations, plus member-target and snapshot revelations (§2) |
| `transfer_campaign_ownership` [memberships.py:1206](../src/dnd_ai/commands/memberships.py#L1206) | new owner gains now; relinquishing owner loses (keeps `gm`) | **existing grants survive**: grantor is provenance (ADR 0020 decision 7, OD-4a analogy); new owner may revoke | test only |
| Role `expires_at` lapsing (time-based, no write) | owner lapses | read-time liveness fails; a later re-assignment is a new row | read-time check only |
| `recover_campaign_access_manager` [recovery.py:153-195](../src/dnd_ai/commands/recovery.py#L153-L195) | admin creates an owner; can flip an open membership's status to `active` | status flip could revive a delegation bound to a still-live `gm` row | close that membership's delegations when status is changed |
| Invitation acceptance reopens a membership in place [campaign_invitations.py:247-262](../src/dnd_ai/commands/campaign_invitations.py#L247-L262) | none (roles were revoked at end) | none | none, because end already closed everything |
| Campaign archived/deleted (route refuses) / account deactivated (auth fails) | unusable meanwhile | unusable meanwhile | none; the rows are unchanged, so authority returns with no new grant. Read as "not a GM status loss"; reviewer to confirm |
| Role template `is_active` toggle; membership `suspended` | DB-only; no app path exists | fails closed while inactive | document as DB-only |

**Cross-campaign isolation.** Every row is keyed by `campaign_id`, and the resolver only reads the route campaign. Required tests:

- an owner or delegated GM of A gets nothing in B, on the same world and the same timeline;
- a delegation naming a membership or `gm` row from another campaign is refused by a same-campaign trigger, like the existing scope triggers.

---

## 2. Profiles, releases and revelations

**Storage (campaign scope, D1 approved).** The profile tables are specified in §5.3; this section keeps only their outline.

- `campaign.character_public_profiles` holds one mutable **draft** per (campaign, character), with `row_version` (§26.3). Readers are limited by the §5.7a read rule (proposed D8): effective `canon.edit` on the character, or reveal authority.
- `campaign.character_public_profile_releases` holds **immutable** releases, never updated or deleted. Each release snapshots the draft, records each field's origin, and has a gapless `version_number`.
- "Follows later releases" is implemented as "latest release wins", so no pointer is needed. Fixing a mistake means releasing a new version.
- `security.revelation_audience_kinds` is a lookup table, not an ENUM (§5.9/§11): `member`, `access_group`, `campaign_current`, `campaign_current_and_future`. There is no default.
- `security.character_revelations`:
  - campaign, character, kind, and the member or group target (CHECKs by kind);
  - creator, reason;
  - revoked/end columns;
  - same-campaign triggers.
- `security.character_revelation_members` is the `campaign_current` snapshot, written at creation under a campaign lock, with a `removed_at` column.

**Audience rules and the paths that change them:**

- **Member target:** ends when the membership ends. Invitation reactivation reuses the membership UUID, so this follows the existing precedent that a reopened membership starts with nothing.
- **Group target:** live while the group is active and the member has a live group membership.
  - [access_groups.py:597](../src/dnd_ai/commands/access_groups.py#L597) and [:806](../src/dnd_ai/commands/access_groups.py#L806) change who is covered.
  - `deactivate_access_group` [access_groups.py:408](../src/dnd_ai/commands/access_groups.py#L408) should revoke group revelations just as it revokes group grants.
- **`campaign_current`:** snapshot rows only; ended memberships get `removed_at` set.
- **`campaign_current_and_future`:** any active membership, so a returning member counts as a "future" member.

**Enforcement inside `AccessContext`.** Add a separate, source-tagged field (for example `revealed_characters`) to [AccessContext](../src/dnd_ai/domain/access.py#L248). It is resolved in `resolve_access_context` with the same character filters as relationships: lifecycle `active` and canon `canon` ([access.py:1068-1070](../src/dnd_ai/domain/access.py#L1068-L1070)).

- A revelation confers only `character.discover` and a new `character.view_public_profile`.
- It never confers `view_summary`, `view_full`, `view_inventory`, `view_knowledge` or `view_private`.
- `has_capability` adds it to the baseline, so existing denies still win. A whole-character `campaign.view` deny suppresses it, and a deny of `character.discover` alone hides only discovery (ADR 0021 §2.9).
- Revoking a revelation touches only its own row, so legacy viewer relationships and resource grants survive (T6).
- The access-overview explanation ([effective_access.py:82](../src/dnd_ai/queries/effective_access.py#L82)) must show revelation as a distinct source.

**Migration and existing records.** All additive. A1 used `141_character_reveal_delegations`, so A2a is expected to be 142.

- No backfill; no automatic revelation or release.
- `character.character_descriptions` is untouched. It stays reachable only through the authoring reads, which already keeps legacy background restricted.
- After migration, every existing character has no profile and no revelation. Discovery through roles, relationships and grants is unchanged.
- The one intended behavior change is A0.
- New columns must be registered in [data_classification.py](../src/dnd_ai/domain/data_classification.py#L128): release fields `CAMPAIGN_VISIBLE`, draft `GM_ONLY`.

---

## 3. Discovery surfaces and `active_encounter_id`

**Most consumers update together.** Almost every consumer reads the same bundle, so revelation reaches them through one change: add the revealed IDs to the `mentioned` set in [resolve_world_character_visibility](../src/dnd_ai/api/world_explorer.py#L98-L130). Consumers that inherit it:

- World search and counts ([queries/world_explorer.py:255-296](../src/dnd_ai/queries/world_explorer.py#L255-L296))
- `discoverable_entity_ids` and `all_participants_discoverable_sql` ([queries/world_explorer.py:492-620](../src/dnd_ai/queries/world_explorer.py#L492-L620))
- relationships ([api/relationships.py:366](../src/dnd_ai/api/relationships.py#L366))
- organization members ([api/organization_members.py:68](../src/dnd_ai/api/organization_members.py#L68))
- the session roster ([api/sessions.py:184](../src/dnd_ai/api/sessions.py#L184))
- event explanations ([api/event_explanations.py:197-214](../src/dnd_ai/api/event_explanations.py#L197-L214))
- Knowledge subjects ([api/knowledge.py:347](../src/dnd_ai/api/knowledge.py#L347), [:405](../src/dnd_ai/api/knowledge.py#L405))
- the encounter member projection ([api/encounters.py:428](../src/dnd_ai/api/encounters.py#L428))
- the clock reads ([api/campaign_clock.py:107](../src/dnd_ai/api/campaign_clock.py#L107))
- the subject side of preview, which resolves the subject's own `AccessContext`.

**Surfaces that need explicit change:**

- **Projection tier:** add one next to [resolve_character_view_tier](../src/dnd_ai/api/access.py#L455-L490): `public_profile` < `summary` < `full` < `gm`.
- **Link decisions:** [can_open_participant](../src/dnd_ai/api/access.py#L533) and the session roster's [_can_open_character](../src/dnd_ai/api/sessions.py#L169) must treat `public_profile` as openable. Otherwise a revealed character is listed but cannot be opened.
- **Character detail** ([api/characters.py:465](../src/dnd_ai/api/characters.py#L465)):
  - Return a public-tier response carrying the latest release.
  - `species_code` and `size_category` become null at that tier unless released.
  - `sections` gains `public_profile`; the sheet, inventory and parties sections stay false (sections at [api/characters.py:439](../src/dnd_ai/api/characters.py#L439)).
  - Direct entry and browse must agree.
- **Unchanged, regression-test only:** the inventory gate ([api/access.py:496](../src/dnd_ai/api/access.py#L496)), the sheet, and bootstrap perspectives (`view_knowledge`, [queries/bootstrap.py:107](../src/dnd_ai/queries/bootstrap.py#L107)). A revelation must open none of them.
- **Party roster** ([api/parties.py:134-147](../src/dnd_ai/api/parties.py#L134-L147)) deliberately names every current party member without discovery. See D4.
- **Derived mechanics stay outside P03-A.** The public tier never calls `character_sheet` or `character_calculations`.

**`active_encounter_id` today.** It is selected by timeline and `status='active'` only ([queries/character.py:181-193](../src/dnd_ai/queries/character.py#L181-L193)), with no campaign check. `LIMIT 1` therefore picks across campaigns that share a timeline, and campaign-less encounters (`campaign_id` is nullable with `SET NULL`) are also returned.

**The fix:**

- Add a required `campaign_id` to `get_character_view`.
- Filter `e.campaign_id = :campaign` before the `ORDER BY … LIMIT 1`.
- Apply the encounter member-read rule ([queries/encounter.py:100-115](../src/dnd_ai/queries/encounter.py#L100-L115)) through a shared, exported predicate, so the two surfaces can't drift.
- Apply it to every full-tier reader, including `canon.edit` holders and the Foundry paired-device route.

The second caller, AI NPC context ([domain/context_assembly.py:362-396](../src/dnd_ai/domain/context_assembly.py#L362-L396)), must pass the route campaign as well.

---

## 4. Slices, dependencies and review boundaries

| Slice | Scope | Depends on | Checks at the review boundary |
|---|---|---|---|
| **A0** (done, `fca3ac7`) | `active_encounter_id` filter (below) | none | below |
| **A1** (done, `68dc902`–`6a5773d`; CI pending) | `character.reveal` vocabulary, delegation table, resolver, grant/revoke commands and API (owner only), eligibility closure in the membership, ownership and recovery commands, audit | D3 (approved) | Every row of the §1 table as a database test; concurrency tests (revoke `gm` vs grant; revoke delegation vs release); assistant GM, `canon.edit` and custom `access.manage` refused; cross-campaign refusal; migration up/down; the full suite. The release race moves to A2a, because no release existed in A1 |
| **P0** (implemented at `4dd56fd`; independent review complete) | `lock_authoring_scope` takes the campaign row `FOR KEY SHARE` (DEF-014, §6) | none | §6.4–§6.5 |
| **P1** (implemented at `edf46ca`; independent review complete) | `add_access_group_members` locks memberships before the campaign row, in weaker modes (DEF-015, §7); race harness cleanup | P0 | §7.5–§7.8 |
| **P2** (implemented at `d36d565`; independent review: PASS WITH NONBLOCKING FINDINGS) | `begin_idempotent_request` takes a transaction-scoped key lock before its insert; a shared `lock_idempotency_key` helper; structural guards on the helper (§10.11) | none | §10.11, P2; record below §10 |
| **P3** (designed 2026-11-08, revised after CHANGES REQUIRED; before A3a; for Sonnet) | The request transaction ends before the response: one app-wide function-scoped async `commit_request_transaction` dependency; `get_connection` registers its connection; the eight engine-backed handlers end their authorization transaction before engine-side effects; `pyproject.toml` and `uv.lock` raise the FastAPI floor (§11, DEF-022) | P2 | §11.8, §11.11 |
| **A2a** (done, `0b4704c`; reviewed, handoff `523ae5c`) | Migration 142 (§5.3); draft save; release under A1 authority; GM reads (§5.7, §5.7a). No copy aid | A1, P0, P1, D1 and D2 (approved), D8 | The criteria in the A2a acceptance section |
| **A2a-R** (done, `f66240a`; reviewed) | The D8 denies become creatable: `entity_id` may name a character for a `campaign.view` or `canon.edit` deny (§8); overview and explanation name the character | A2a, Q1 (§8.8) | §8.6–§8.7 |
| **A2b-1** (designed, revised after review; for Sonnet) | The D7 restriction: migration 143 (restriction watermarks, preflight, enforcement trigger), the source-read rule, withholding in the GM read, the save rule and watermark advance, the release's world lock and withheld check (§9.1–§9.7) | A2a-R, D7 and D7-a to D7-f (approved) | §9.8–§9.9, with legacy-origin rows seeded by a test helper |
| **A2b-2** (designed, revised after review; for Sonnet) | The copy command and route, `legacy_copy` in the GM read, the copy audit row (§9.4, §9.6) | A2b-1 | §9.8–§9.9: copy rules, recopy, excerpt regressions through the real copy, disclosure sweep, copy races |
| **A3** (designed in §10; split into A3a and A3b, §10.10) | Revelations: audience kinds, snapshot, create/revoke, membership-end and group-deactivate hooks, `AccessContext` source, discovery bundle | A2 (a revelation requires an existing release, D9-d); D4-C, D5-c, D9, D10 (approved) | T82 audiences, including the late joiner; T6 independent-grant survival; whole vs operation deny; cross-surface matrix from investigation D6.4 (lists, counts, pagination, relationships, organizations, roster, events, encounters, Knowledge, preview), with **response-body ID assertions**; bootstrap, inventory and sheet unchanged |
| **A4** | Projection tier, public-profile read in the detail route, `sections`, `can_open` | A3 | Browse/detail agreement; public tier carries no species, size or mechanics unless released; revocation takes effect on the next request |
| **A5** | OD-18 player-profile storage plus GM read (editing is P03-B, T85); publishing a selected field via A2 provenance | A2 | Readable only by A's GMs; nothing in B; no write path for players yet |
| **A6** | Portal: reveal/delegation management, draft and release editor, revelation list and revoke, public character view, effective-access sources | A4 (A5 optional) | jsdom; type contract; non-disclosing errors; real-browser checks recorded as pending |
| **A7** | Character-profile audience preview (investigation D6.3, optional), docs reconciliation, corrected Sella acceptance (investigation D6.8) | A4, A6 | Manual T82/D6.8 on namespaced fixtures, not the owner's campaign |

Every boundary also needs:

- `ruff format --check`, `ruff check`, `mypy src`;
- the focused tests, then the full `pytest`;
- migration up/down on PostgreSQL 18;
- a CI run on the final head;
- an independent review naming the parent and target SHAs.

Docs to update in the same change: `DOMAIN_MODEL`, `DATABASE_MODEL` §19, `PHASE13E_ACCESS_CONTRACT`, `ENTITY_LIFECYCLE` command list.

---

## 5. A2 design: public-profile drafts and releases (2026-11-07)

**Status:** design only, checked against `6a5773d`. Nothing in it is implemented.

### 5.1 The approved rules, as A2 applies them

- **Campaign scope (D1).** A draft and its releases are keyed by (campaign, character).
  - Campaign B has its own draft and releases for the same character.
  - Nothing written in A changes what B's GMs or audiences see.
  - The world definition (`core.entities`, `character.character_descriptions`) is never written.
- **Editing (D2, refined by D8).** Editing requires **effective character-scoped `canon.edit`**, which means both of these:
  - the caller holds role `canon.edit` in the route campaign (assistant GMs included), re-checked under lock by `lock_authoring_scope` ([_content.py:95](../src/dnd_ai/commands/_content.py#L95)), as every authoring write does;
  - no deny removes it for this character (§5.7a).

  A `canon.edit` allow targeting the character does not by itself confer editing (D8).
- **Releasing (D2).** A release requires `character.reveal` authority from `resolve_reveal_authority`: a live built-in owner, or a live delegation bound to the caller's live built-in `gm` assignment.
  - The authority is re-read under lock and judged again at a fresh database instant after the last lock wait (the DEF-013 pattern).
  - `canon.edit` alone, assistant-GM status, a custom `access.manage` holder and a player are refused.
- **Copying legacy text (D2).** Allowed only to a caller whose existing authoring read returns that text (§5.10).
- **Reading drafts and releases (proposed, D8).** A member may read the draft and the release snapshots if they have either:
  - effective character-scoped `canon.edit`; or
  - current `character.reveal` authority, from `resolve_reveal_authority` at the time of the read.

  Reveal authority confers reading only, never editing. A whole-character deny overrides both (§5.7a).
  - Today every reveal-authority holder also holds role `canon.edit`: the owner through migration 085, a delegated GM through the built-in `gm` role in migration 086.
  - So D8 changes the outcome only when a reveal holder has a `canon.edit` deny on one character. They can still read and release that character's profile, but cannot edit it. That follows ADR 0021 §2.9: "An operation-specific deny blocks only that operation."
  - A releaser can therefore always read what they release.
- **What a release does not do.** It makes nothing visible by itself. Audiences see a release only through an A3 revelation, through the A4 read.

### 5.2 Profile fields

| Field | Draft | Release | Classification | Notes |
|---|---|---|---|---|
| `public_appearance` | `TEXT NULL`, at most 4000 characters | snapshot | draft `GM_ONLY`, release `CAMPAIGN_VISIBLE` | The limit is `NPC_TEXT_MAX_LENGTH` ([npc_authoring.py:14](../src/dnd_ai/domain/npc_authoring.py#L14)), the source field's limit, so a copied text always fits |
| `public_background` | same | snapshot | same | same |
| `<field>_origin_id` | FK to the origins lookup | snapshot | `STRUCTURAL` | `authored`, `legacy_appearance` or `legacy_background`. `player_profile` is reserved for A5 and inserted then |
| `<field>_origin_entity_row_version` | `BIGINT NULL` | snapshot | `STRUCTURAL` | The character's `core.entities.row_version` when the text was copied. Present only for a legacy origin |

- **Every field may be null.** A release whose fields are both null is allowed. It withdraws the public text in the next version.
- **Not in A2:**
  - a display name or summary (D5);
  - species and size (D6);
  - player-profile fields (A5).
- **No derived mechanics.** The release command and the profile reads never call `character_sheet`, `character_calculations` or a rules module. A structural test pins this (A2a criterion 9).

### 5.3 Storage: migration `142_character_public_profiles`

The migration is additive, with no backfill. After it runs, every existing character has no draft and no release.

**`campaign.public_profile_field_origins`.** A lookup table (§11: no ENUM) holding `authored`, `legacy_appearance` and `legacy_background`.

**`campaign.character_public_profiles`** (the draft, a mutable record, §10.2). Columns:

- `character_public_profile_id` (PK);
- `campaign_id` (FK to `campaign.campaigns`);
- `character_id` (FK to `character.characters`);
- the §5.2 draft fields;
- `row_version BIGINT NOT NULL DEFAULT 1 CHECK (row_version >= 1)`, kept current by the shared `core.bump_row_version()` trigger (§26.3);
- `created_at`, `created_by_membership_id`, `updated_at`, `updated_by_membership_id`.

Constraints:

- `UNIQUE (campaign_id, character_id)`;
- `UNIQUE (character_public_profile_id, campaign_id, character_id)`, the target of the releases' composite foreign key.

**`campaign.character_public_profile_releases`** (append-only, §10.3). Columns:

- `character_public_profile_release_id` (PK);
- `character_public_profile_id`, `campaign_id`, `character_id`, as a composite FK to the draft's triple, so a release cannot name another campaign's or another character's profile;
- `version_number INT CHECK (version_number >= 1)`;
- `from_draft_row_version BIGINT`;
- the §5.2 snapshot fields;
- `authority_source_code` (`owner` or `delegation`) and `character_reveal_delegation_id` (FK, NULL unless the source is `delegation`, with a CHECK pairing the two);
- `released_by_membership_id`, `released_at TIMESTAMPTZ`;
- `release_note TEXT NULL` (`GM_ONLY`).

Constraints:

- `UNIQUE (character_public_profile_id, version_number)`;
- `UNIQUE (character_public_profile_id, from_draft_row_version)`. A draft version is released at most once; this is also the natural retry key (§5.9).

**Triggers** (§20.4, local integrity only):

- **Scope.** The character belongs to the campaign's world. `created_by`, `updated_by` and `released_by` memberships belong to the row's campaign. A delegation belongs to the campaign and its grantee is the releaser. These follow the scope triggers of migration 141.
- **Origin.** A field's origin matches the field (`legacy_appearance` only on `public_appearance`, and so on). `origin_entity_row_version` is present exactly when the origin is a legacy origin. A null text has origin `authored`.
- **Immutability.** Releases refuse UPDATE, DELETE and TRUNCATE.

**Other database changes:**

- **Grants.** Follow migration 141's pattern. The application role gets SELECT, INSERT and UPDATE on drafts; SELECT and INSERT on releases; SELECT on the lookup. Nothing gets DELETE.
- **Entity reference classification.** Both `character_id` foreign keys are registered as `BLOCKING` in `ENTITY_REFERENCE_CLASSIFICATION` ([entity_lifecycle.py:101](../src/dnd_ai/commands/entity_lifecycle.py#L101)). A character with a profile is therefore never physically deleted (ENTITY_LIFECYCLE §14). Legal removal would need its own reviewed administrative procedure; that is outside A2.
- **Downgrade.** Lossy but supported: it drops the tables, triggers and lookup, as 141 does.

### 5.4 The draft's concurrency token

- **Saving** (`save_character_public_profile_draft`) requires `expected_row_version`.
  - `null` means "there is no draft yet". The command inserts with `INSERT … ON CONFLICT (campaign_id, character_id) DO NOTHING RETURNING`. If nothing is returned, another request created the draft first, and the save fails with 409 `stale_write`.
  - Otherwise the command locks the draft `FOR UPDATE` and compares. A mismatch is 409 `stale_write` (`StaleWriteError`), with nothing written.
- **Partial updates.** A field left out of the request is untouched. An explicit `null` clears the field and resets its origin to `authored`. This is needed for A2b's withheld fields; for A2a it just keeps saves small.
- **No real change.** Values identical to the stored ones write nothing, do not bump `row_version`, write no audit row, and return `changed: false`.
- **Releasing never writes the draft,** so a release does not make a concurrent editor's token stale.

### 5.5 The release snapshot and version allocation

`release_character_public_profile` takes `expected_draft_row_version` and an optional `release_note`. It never takes field content. It snapshots exactly the locked draft at that version, so the release is precisely what the releaser reviewed. Under the §5.8 locks:

1. **Deny.** The caller's `AccessContext` is re-resolved after the campaign lock. A whole-character deny (§5.7a) gives 404, with nothing written. This check runs before step 3, so a denied caller is never handed an existing release.
2. **Draft.** No draft gives 409 `public_profile_draft_missing`.
3. **Natural retry.** If a release with `from_draft_row_version = expected` already exists, return it: 200, `created: false`, plus `is_latest`. This happens even when the draft has since moved on (§5.9).
4. **Stale.** If the current `row_version` is not `expected`, fail with 409 `stale_write`; nothing is written.
5. **Character.** It must still be a `canon`, `active` character of the campaign's world. Otherwise: 404 when it is not in the world or not canon; 409 `public_profile_character_not_active` when it is archived.
6. **Version.** `version_number = COALESCE(MAX(version_number), 0) + 1` for this profile, read under the draft's `FOR UPDATE` lock. Every release of a profile takes that lock, and releases are never deleted, so versions are gapless; the unique constraint is only a backstop. Insert the release, write its audit row, and return 201, `created: true`.

**The current release** is the one with the highest `version_number` ("latest release wins"; OD-17 "follows later releases"). A3 and A4 read it through one query, `latest_character_public_profile_release(campaign_id, character_id)`, added in A2a and used by no audience reader until A4.

### 5.6 Provenance

- **Field origin, kept across edits.** A2b's copy sets a field's origin to its legacy origin and records the source's `core.entities.row_version`. Later edits keep that origin, so editing never removes the record that the text came from legacy material. Clearing the field resets it. *Superseded in part by §9 (approved D7):* there is no blind replacement. A reader the field is withheld from may only clear it (§9.4, D7-a). Every content change to a copied field also advances its restriction watermark, and a release lifts the restriction only when it covers that watermark (§9.2).
  - The rule over-attributes rather than under-attributes. A2a has no copy, so every origin is `authored`.
- **On each release:** the per-field origins, `from_draft_row_version`, `released_by_membership_id`, `released_at`, the authority source (owner or delegation), and the delegation's id when there is one.
- **Releases outlive authority.** A release made under a delegation stays after the delegation ends. The approved policy of 2026-11-06 says ending a GM's grant ends *future* release authority. A1's lifecycle hooks never touch releases.
- **Audit** (`audit.change_log`, one row per real change, none for a repeat or a no-op):
  - a draft save records changed field names and the new `row_version`;
  - a copy (A2b) records the origin and the source row version;
  - a release records `version_number`, `from_draft_row_version` and the authority source.

  Audit rows never carry profile text. It lives only in the draft and release rows. Revision snapshots (`capture_revision`) are **not** written, because `core.entity_revisions` is world-scoped and any campaign's reader with `world.canon.read_private` can read it.

### 5.7 Routes and authorization

All routes are under `/campaigns/{campaign_id}/characters/{character_id}/public-profile`. A character outside the campaign's world, a non-character entity, or a non-canon character gets 404 (not disclosed). The read, edit and release rules, and how denies apply to them, are in §5.7a.

| Route | Route filter | Authority in the handler or command | Result |
|---|---|---|---|
| `GET …/public-profile` | `campaign.view` | The §5.7a read rule; failing it gives 404 | The draft (or `null`), its `row_version` and `has_unreleased_changes`; the latest release; a list of release summaries (version, time, releaser name, authority source, draft version); `can_edit` and `can_release` (no lock); the D5 label (canonical name and summary, read-only); in A2b, `legacy_copy` availability, shown only to a caller who passes that kind's read rule |
| `GET …/public-profile/releases/{version_number}` | `campaign.view` | The §5.7a read rule; failing it gives 404 | One release snapshot |
| `POST …/public-profile/draft` | `canon.edit` (role; a coarse first filter) | `lock_authoring_scope(world_capability=None)`, then the §5.7a edit rule, re-resolved under those locks. A caller who can still read gets 403 `public_profile_edit_denied`; anyone else gets 404 | 201 created, or 200 with `changed`; supports `Idempotency-Key` |
| `POST …/public-profile/releases` | `campaign.view` | A reveal-authority pre-check before the idempotency lookup (below); then authority locked and re-judged at a fresh instant (§5.8); then the whole-character deny re-resolved under lock, which gives 404 | 201 `created: true`, or 200 `created: false` (§5.9); supports `Idempotency-Key` |
| `POST …/public-profile/draft/copy-legacy` (A2b) | `canon.edit` | The edit rule, plus the kind's source-read rule, before the idempotency lookup and again under lock (§9.4, §9.6) | 201 if it created the draft, else 200, with the new draft `row_version`; supports `Idempotency-Key` |

**Why `campaign.view` for the reads and the release.** D8 lets a reveal holder read and release without `canon.edit`, so neither path may require `canon.edit` at the route. Players also hold `campaign.view`. They fail the read rule with a 404, which discloses nothing, and they fail the release pre-check with a 403 that names no character (next paragraph).

**Authorization runs before the idempotency lookup** (DATABASE_CONVENTIONS §26.4).

- **The pre-check.** Before `start_campaign_idempotency`, the release endpoint calls `resolve_reveal_authority(lock="none")` and refuses with 403 **`character_reveal_required`** (a new error code).
  - Reveal authority depends only on the campaign, so this 403 says nothing about the character.
  - A caller who has lost authority cannot replay a stored response.
- **The character checks come after the lookup.** The whole-character deny and the character checks give 404s, and run after it.

**Idempotency fingerprint (review correction).** All three POST routes put the path's `character_id` into the fingerprinted payload: `{"character_id": str(character_id), **body.model_dump(mode="json")}`. This is the pattern `update_player_character` already uses ([player_character_authoring.py](../src/dnd_ai/api/player_character_authoring.py), `{"player_character_id": …, **body}`).

- **Why it matters.** The store's scope is (actor, campaign, key). The release body `{expected_draft_row_version, release_note}` does not identify the character. Without `character_id`, a reused key with the same body on character Y would replay X's stored 201 for Y. Y would then appear released when it was not.
- **With it,** the fingerprints differ and the request gets the existing non-disclosing idempotency 409. This is pinned by A2a criterion 13.

### 5.7a Reading, editing and releasing under denies (proposed, D8)

**Which deny keys apply.** `campaign.view` and `canon.edit` are generic-target capabilities. A resource grant can name them for a character only through the `entity_id` target (`RESOURCE_GRANT_CAPABILITY_CATALOG`, [access.py:228](../src/dnd_ai/domain/access.py#L228)).

*Correction (A2a review, §8):* the catalog permits that key, but `create_resource_grant`'s CTI guard refuses a character entity under `entity_id`. So at `0b4704c` neither deny below can be created through the application, only by direct SQL. A2a-R (§8) removes that refusal for exactly these two denies. The read keys below are unchanged.

- **Whole-character deny:** `not access.has_capability("campaign.view", entity_id=character_id)`. This is the test `resolve_character_inventory_access` uses ([api/access.py:514](../src/dnd_ai/api/access.py#L514)).
- **`canon.edit` deny on the character:** a `deny` for `canon.edit` under `("entity_id", character_id)` in `grant_effects`. A deny under `("character_id", character_id)` counts too, so that a stray row also fails closed.
  - `has_capability("canon.edit", character_id=…)` alone is **not** enough: it consults only the `character_id` key, under which no `canon.edit` grant can be created.
  - That mistake already exists in `resolve_character_view_tier` ([api/access.py:482](../src/dnd_ai/api/access.py#L482)) and `resolve_character_inventory_access` ([:515](../src/dnd_ai/api/access.py#L515)), so neither sees a per-character `canon.edit` deny. It predates A2 and is outside it: proposed **DEF-016**. A2 must not copy the pattern.
- **Effective character-scoped `canon.edit`:** role `canon.edit`, no whole-character deny, and no `canon.edit` deny on the character. An `allow` grant of `canon.edit` on the character does **not** confer editing on a member without role `canon.edit` (D8). Otherwise a resource grant would become the first per-character authoring path, which ADR 0021 §4 reserves for stewardship and delegations.

| Deny on the caller | Read draft and releases | Edit draft | Release |
|---|---|---|---|
| None | Allowed with effective character-scoped `canon.edit` **or** reveal authority | Allowed with effective character-scoped `canon.edit` | Allowed with reveal authority |
| Whole-character (`campaign.view` on the character's entity) | **Refused**, 404, for every source, the owner included (ADR 0021 §2.9: suppresses profiles "from every source") | **Refused**, 404 | **Refused**, 404, nothing written; checked before a natural retry can return a release (§5.5 step 1) |
| `canon.edit` on the character | Only the `canon.edit` path is removed; a reveal holder still reads | **Refused**: 403 `public_profile_edit_denied` if the caller can still read, otherwise 404 | No effect: a different operation (§2.9) |
| `character.reveal` | Cannot exist: A1's trigger refuses any resource-grant row naming `character.reveal` (migration 141) | — | Per-character release denial is therefore not available. Adding it would extend A1's trigger to accept deny-only rows, which is out of scope |
| `character.view_*`, `character.discover`, A3's `character.view_public_profile` | No effect: these govern audience projections, not the GM draft | No effect | No effect |

D7's restriction on copied legacy fields is separate. It applies after this table, on top of it, and is unchanged by D8.

**Under lock.**

- **Edits** re-resolve the `AccessContext` after `lock_authoring_scope` has taken all its locks.
- **Releases** re-resolve it after taking the caller's membership `FOR SHARE` and the campaign row `KEY SHARE` (§5.8).
- **Why that is enough.** A deny reaches a member in three ways, and each one conflicts with a lock the command already holds when it re-resolves:
  - **`create_resource_grant` naming the member.** It takes the member's membership `FOR UPDATE` and the campaign row `FOR UPDATE`, which conflict with the command's membership `FOR SHARE` and campaign `KEY SHARE`.
  - **`create_resource_grant` naming a group the member belongs to.** It takes the campaign row `FOR UPDATE`, which conflicts with `KEY SHARE`.
  - **Adding the member to a group that holds a deny.** After P1 (§7) this no longer takes the campaign row `FOR UPDATE`. It takes each added member's membership `FOR NO KEY UPDATE`, which conflicts with the `FOR SHARE` that `lock_authoring_scope` and the release take on the caller's membership. This is why the release takes its membership `FOR SHARE`, not `KEY SHARE`: `KEY SHARE` would not wait for the add (§7.6, probe S7/S8 against S7b/S8b).

  So a concurrent deny either commits before the re-resolve and is seen, or waits for the command to commit. P0 keeps the campaign conflict, since `KEY SHARE` still conflicts with `FOR UPDATE`, and P1 moves the group-add conflict to the membership row.
- **Reads** are judged at the moment of the read.

### 5.8 Transactions and locks

Each command is one transaction, and the audit row commits with the write. The orders below add to the A1 design's §3 table and reverse none of its rows. They assume P0 (§6): `lock_authoring_scope` takes the campaign row `FOR KEY SHARE`. They also assume P1 (§7): `add_access_group_members` takes the added members' memberships `FOR NO KEY UPDATE` before the campaign row, and the campaign `KEY SHARE`.

| Command | Locks, in order |
|---|---|
| `save_character_public_profile_draft` | `lock_authoring_scope`: world (S) → caller's role rows and membership (S) → account (S) → campaign (**KEY SHARE**, after P0), then the role `canon.edit` re-check → the `AccessContext` re-resolved for the §5.7a edit rule → character's `core.entities` row (S) → the draft row (U), or the insert's unique-index wait |
| `release_character_public_profile` (**corrected**) | Caller's authority rows, as in `resolve_reveal_authority(lock="share")`: the owner assignment (S), or else the `gm` assignment (S) then the delegation row (S) → **caller's membership (S; `KEY SHARE` in the first revision, changed by P1, §7.6) → campaign row (KEY SHARE) → character's `core.entities` row (KEY SHARE)** → the draft row (U) → `clock_timestamp()` → `resolve_reveal_authority(as_of=<that instant>)`, which must return the **same** source as the locked read, or the release is refused with 403 `character_reveal_required` → the `AccessContext` re-resolved for the whole-character deny → write |
| `copy_legacy_text_to_public_profile_draft` (A2b) | As for a draft save, with the kind's world capability resolved under the world lock. The character's `row_version` and its source text are read in separate statements under the entity `FOR SHARE` lock, which every description writer conflicts with (§9.6) |
| `release_character_public_profile` after A2b-1 | **World (S) first**, then the row above unchanged; the withheld check runs after the natural-retry and stale steps (§9.6) |

**Correction to the first A2a design.** The first design locked the character's entity before the caller's membership. `create_resource_grant` locks the grantee's membership `FOR UPDATE`, then the campaign `FOR UPDATE`, then the target entity `FOR UPDATE` ([access_grants.py:1341](../src/dnd_ai/commands/access_grants.py#L1341)). A grant to the releaser naming the character would therefore hold the membership and wait for the entity, while the release held the entity and waited for the membership: a deadlock.

The release now takes membership, then campaign, then entity. That is the order `create_resource_grant`, `grant_character_relationship` and `lock_authoring_scope` already use. The last lock wait is still the draft row, so the fresh-instant re-check (DEF-013 pattern) still follows every wait.

**Release, case by case.**

- **Same-source rule.** If the owner row expires during a wait and only a delegation remains, the delegation's rows were never locked. Refusing is fail-closed, and a retry resolves the delegation freshly.
- **Revoking the releaser's `gm` role, ending their membership, or re-granting their delegation.** Each takes the releaser's role rows `FOR UPDATE` first; the release takes them `FOR SHARE` first. Whichever gets there first goes first.
- **Revoking the delegation.** The revocation queues on the delegation row, and the release waits for nothing the revocation holds.
- **A resource grant to the releaser on this character.** Both take the releaser's membership first (`FOR UPDATE` against `FOR SHARE`), so the first to lock it goes first.
- **A resource grant *by* the releaser.** The grant's insert takes `KEY SHARE` on the releaser's membership through `granted_by_membership_id`, which is compatible with the release's `FOR SHARE`. Neither waits for the other there.
- **Relinquishing transfer by the releasing owner.** Ordered by the owner row: U against S.
- **Relinquishing transfer to a releasing GM.** The transfer locks that GM's membership `FOR UPDATE`. The release waits for it at the membership `FOR SHARE` while holding only its authority rows, which the transfer does not request.
- **A delegation re-grant to the releasing GM.** The grant locks the grantee's `gm` assignment `FOR UPDATE` before the grantee's membership `FOR NO KEY UPDATE`. The release takes that assignment `FOR SHARE` first, so whichever reaches the `gm` row first goes first. The release's membership `FOR SHARE` conflicts with the grant's `FOR NO KEY UPDATE` only after that point. A release by an owner locks no `gm` row. It waits at the membership while holding only its owner assignment, which the grant locks at most `FOR SHARE`.
- **Administrative recovery.**
  - Recovery holds the campaign `FOR NO KEY UPDATE`, which is compatible with the release's campaign `KEY SHARE`. When recovery waits for the promoted member's membership, the release holding it can still finish.
  - Recovery closes a delegation only for a membership that was not `active`. For such a membership the release's authority read returns no row and locks nothing.
- **Adding the releaser to an access group.** Before P1 this deadlocks, as it does for every authoring write (DEF-015, reproduced: §7.1, S7/S8). After P1 the add takes the releaser's membership `FOR NO KEY UPDATE` before the campaign row, and that conflicts with the release's membership `FOR SHARE`. So the first to reach the membership goes first. If the add commits first, the release's re-resolve sees the new group membership and any deny it carries. Neither holds the campaign row in a mode the other's wait conflicts with (probe S7b/S8b).
- **Archiving the character.** Archiving locks the entity `FOR UPDATE`, which conflicts with the release's `KEY SHARE`. Either the release commits first, or it reads the archived state after its lock and refuses.

**Saving the draft.**

- **Against a release.** A save takes no role rows `FOR UPDATE` and holds only shared locks before the draft row. The release's membership `FOR SHARE` and campaign `KEY SHARE` are compatible with the save's locks (`FOR SHARE` on its own membership, `KEY SHARE` on the campaign). So the draft row alone orders the two.
- **Against GM-role revocation, membership end, campaign archive and resource-grant creation.** This is the existing `lock_authoring_scope` order: role rows and membership first. P0 preserves it.

### 5.9 Concurrent edits, stale requests and retries

| Situation | Outcome |
|---|---|
| Two saves with the same `expected_row_version` | The first commits (`row_version` + 1). The second waits on the draft row, then gets 409 `stale_write`; nothing is written |
| Two first saves (no draft yet) | One gets 201. The other waits on the unique index, then gets 409 `stale_write` |
| A save commits before a release of the previous version | The release is 409 `stale_write`, with no release row. The releaser reloads, reviews and releases the new version |
| A release commits before a save | The save proceeds, because its token is unchanged. The release holds the earlier content |
| Two releases of the same draft version, under different keys or no key, including one by the owner and one by a delegated GM | One gets 201 with version *n*. The other waits on the draft row, then gets 200 `created: false` with the same release, and the first releaser as provenance. Exactly one row and one audit row |
| The response to a successful release is lost; retried with the same `Idempotency-Key` | The stored receipt is replayed, and nothing is written, after the authority pre-check (§5.7). The receipt is minimal (`replay_body`): the status code, ids, version numbers and flags survive (`character_public_profile_release_id`, `version_number`, `from_draft_row_version`, `created`, `is_latest`); free-text metadata such as `authority_source` is omitted, and the client refetches it from the GM read. If the caller has lost authority meanwhile, 403; the release is still visible in that read (releaser, time, draft version) |
| The same, retried without a key or with a new key | 200 `created: false`, with the release made from that draft version. `is_latest` says whether a later release exists. This is never a false `stale_write`, even when the draft has since moved on |
| The same key with a different body | The existing non-disclosing idempotency 409 |
| The same key **and the same body** on a different character's path (release, draft save or copy) | The existing non-disclosing idempotency 409, because `character_id` is in the fingerprint (§5.7). Nothing is written for the second character, and the first character's stored response is never replayed for it |
| The caller's finite owner assignment, or their `gm` assignment, expires while the release waits | 403 `character_reveal_required` from the fresh-instant re-check (DEF-013 pattern); nothing is written |

### 5.10 The legacy copy aid: read trace and design (A2b)

**Where legacy text is read today** (traced at `6a5773d`):

| Reader | Gate | Returns legacy text? |
|---|---|---|
| `GET …/authoring/player-characters/{id}` ([player_character_authoring.py:191](../src/dnd_ai/api/player_character_authoring.py#L191)) through `get_character_authoring` ([queries/npc_authoring.py:85](../src/dnd_ai/queries/npc_authoring.py#L85)) | campaign `canon.edit`; any character of the campaign's world (ADR 0021 §4.1) | `background`, `appearance`, and the GM-only `notes` |
| `GET …/authoring/npcs/{id}` ([npc_authoring.py:192](../src/dnd_ai/api/npc_authoring.py#L192)) | campaign `canon.edit` **and** world `world.canon.read_private` | the same three fields |
| Revision history and comparison ([review_queue.py:120](../src/dnd_ai/api/review_queue.py#L120), [:150](../src/dnd_ai/api/review_queue.py#L150)) | `canon.edit` and `world.canon.read_private` | yes, as diffs of the authoring snapshot (`capture_revision`) |
| Audit history ([audit_history.py](../src/dnd_ai/api/audit_history.py)) | `access.manage` | no: an allowlist of commands, and only `previous_membership_role_id` is read from `changed_fields` |
| Provenance ([provenance.py](../src/dnd_ai/queries/provenance.py)) | `canon.edit` | no: lifecycle actor and time, "never the free-text reason or the changed fields" |
| Character detail, world explorer, bootstrap, sheet, inventory, relationships, sessions, encounters, Knowledge, AI context, Foundry routes | various | **no.** Only [commands/npcs.py](../src/dnd_ai/commands/npcs.py) and [queries/npc_authoring.py](../src/dnd_ai/queries/npc_authoring.py) reference `character.character_descriptions` in `src/` |

**Design.**

- **One shared read rule per kind.** Put the rule for each kind in one place: `player_character` needs no world capability; `npc` needs `WORLD_CANON_READ_PRIVATE`. Both authoring GET routes, the copy command and D7's withholding read it, and a parity test pins that they agree.
- **Choosing the kind and locking.** The command reads the entity's type without a lock (a character's type never changes, as with A1's unlocked campaign-of-membership read). It then calls `lock_authoring_scope` with that kind's world capability. A caller without it gets the existing 403 `world_authority_required`.
- **What may be copied.** Only `appearance` → `public_appearance` and `background` → `public_background`. `notes` is never copyable.
- **How the copy writes.** It replaces the target field with the whole source text. The GM then cuts it down to the safe excerpt. It requires `expected_row_version`, sets the origin (§5.6), and bumps `row_version`. An empty source gives 409 `public_profile_legacy_text_missing`.
- **Copying is done on the server,** so the origin is a fact about the copy. Text a GM pastes by hand is `authored`. The origin is a record, not a safety label: nothing is published without a release.
- **D7 (approved).** The GM read, the save and the release apply the restriction; the release takes the world row `FOR SHARE` before its authority rows, the same position `lock_authoring_scope` uses. The full design is §9, which supersedes this section's design bullets where they differ.

### 5.11 Drafts and legacy text stay out of audience responses

- **No audience reader in A2.** A2 adds only GM-side routes: every one requires the §5.7a read, edit or release rule, which no player or observer meets. No audience reader selects the new tables, and none selects `character.character_descriptions` (trace above).
- **Releases.** A release becomes an audience field only through A4's read of the latest release for a revealed character. A2a's tests show that a release alone appears in no audience response.
- **Guards added in A2a:**
  - **Structural tests.** Pin which `src/` modules reference each table: the draft table only from the profile command and query modules; `character.character_descriptions` only from the modules listed above, plus A2b's copy command.
  - **Registry entries.** `data_classification` entries for every new text column: draft text `GM_ONLY`, release text `CAMPAIGN_VISIBLE`, `release_note` `GM_ONLY`.
  - **A marker sweep of response bodies** (A2a criterion 8).
- **Mechanics.** These stay outside the profile (§5.2).

### 5.12 A1's guarantees, preserved

- **No new authority source.** `resolve_reveal_authority` and the live-owner and live-`gm` predicates are reused unchanged.
  - Assistant GM, `canon.edit` alone, custom `access.manage`, a lapsed or revoked delegation, and the owner or delegated GM of another campaign are all refused, and tested in A2a.
- **No change to the commands A1 reviewed.** The membership, ownership-transfer, recovery and delegation commands and their lifecycle hooks are unchanged, and A2 adds no lifecycle hook.
- **Ending authority leaves releases alone.** A release outlives the authority that made it. Revocation stays independent (ADR 0021 §2.9), and A3 owns revelations.
- **Lock order.** Only rows are added to the A1 design's §3 table (§5.8), and none is reversed. A1's deadlock and race regressions are rerun at A2a's review boundary.

---

## 6. Prerequisite commit P0 (for Sonnet, before A2a): `lock_authoring_scope` against recovery

**Status:** designed 2026-11-07 against `6a5773d`; **implemented at `4dd56fd`** (DEF-014 in the defect register) and awaiting independent review. It is one bounded commit on `phase15/completion` and touches no schema and no API shape. A nonblocking finding about its race harness, that failure cleanup must release blockers and join worker commands before fixture teardown, is addressed in P1 (§7.7).

### 6.1 The defect (proposed DEF-014, reproduced)

**The two lock sequences.**

- `lock_authoring_scope` ([_content.py:95](../src/dnd_ai/commands/_content.py#L95)) takes, in order:
  1. the world `FOR SHARE`;
  2. the caller's unrevoked role rows and open membership `FOR SHARE`;
  3. the account `FOR SHARE`;
  4. the campaign row `FOR SHARE` ([_content.py:169](../src/dnd_ai/commands/_content.py#L169)).
- `recover_campaign_access_manager` ([recovery.py:153](../src/dnd_ai/commands/recovery.py#L153)) takes the campaign row `FOR NO KEY UPDATE`, then asks for the promoted user's open membership `FOR UPDATE` ([recovery.py:166-170](../src/dnd_ai/commands/recovery.py#L166-L170)).

**The cycle.** `FOR SHARE` conflicts with `FOR NO KEY UPDATE`. So an authoring write by the member being promoted can hold the membership while waiting for the campaign, while recovery holds the campaign and waits for the membership. PostgreSQL aborts one with SQLSTATE 40P01, which the API reports as a 500.

**Reproduction.**

- **The review's probe.** It survives only as compiled bytecode: `tests/database/__pycache__/test_review_a2a_recovery_inversion_tmp…pyc`, whose source is not in the tree. It:
  1. used the Gate fixture and `_strand_the_campaign_for_recovery`;
  2. paused `lock_authoring_scope` just before its campaign statement;
  3. started recovery for the same user;
  4. confirmed through `pg_blocking_pids` that recovery was blocked by the author;
  5. released the author, and got `REPRODUCED SQLSTATE 40P01`.
- **Re-run independently on 2026-11-07** with a throwaway probe (deleted afterwards) on local PostgreSQL 18:
  - **Unchanged (`FOR SHARE`):** recovery is blocked on the author, and then 40P01.
  - **Patched by rewriting the statement to `FOR KEY SHARE`:** recovery is blocked on the author, the author commits, and then recovery commits. No error.

**Scope.** Every command that goes through `lock_authoring_scope` is affected (§6.3). The window requires an administrator to recover a stranded campaign while the member being promoted is in the middle of an authoring write. Recovery runs only when no non-expiring access manager exists.

### 6.2 The correction: one lock mode

Change the campaign statement in `lock_authoring_scope` from `FOR SHARE` to **`FOR KEY SHARE`**. Nothing else in the helper changes.

**Why this is the smallest correct change:**

- `FOR KEY SHARE` conflicts only with `FOR UPDATE`. `FOR SHARE` also conflicts with `FOR NO KEY UPDATE` and with plain non-key `UPDATE`s.
- Weakening one lock can only remove waits; it adds none. So the change cannot introduce a new deadlock.
- The only waits it removes are against the campaign row's `FOR NO KEY UPDATE` and non-key `UPDATE` takers, and the trace below shows recovery is the only one.

**What it preserves, and why:**

| Protection | Mechanism | After P0 |
|---|---|---|
| Campaign archive, reactivate and settings edit serialize with an authoring write | `archive_campaign`, `reactivate_campaign` and `update_campaign` all take the campaign row `FOR UPDATE` first, through `_lock_campaign_for_manage` ([campaigns.py:682](../src/dnd_ai/commands/campaigns.py#L682)). These are the only application `UPDATE`s of `campaign.campaigns` (`campaigns.py:723`, `:801`); migration 024's `UPDATE`s are a one-time backfill | `FOR UPDATE` conflicts with `KEY SHARE`, so this is preserved. In READ COMMITTED, an author who waited reads the archived status after its lock and fails with `CampaignArchivedError` |
| Role loss (`revoke_membership_role`, `change_membership_role`) and membership end (`end_campaign_membership`) serialize with an authoring write | The role rows and membership `FOR SHARE`, taken before the campaign row; the deferred retention trigger takes the campaign `FOR UPDATE` at commit | Unchanged. The helper's comment about why the membership comes before the campaign still holds, because `KEY SHARE` still conflicts with the trigger's `FOR UPDATE` |
| Account deactivation | The account `FOR SHARE` | Unchanged |
| World archive, end of a world role, world ownership transfer and world recovery | The world `FOR SHARE` | Unchanged |
| Resource-grant, relationship and access-group writes that take the campaign row `FOR UPDATE` | `FOR UPDATE` against the author's campaign lock | Preserved. This is also what orders D8's deny re-check (§5.7a). *Superseded for access-group member additions by P1 (§7):* those no longer take the campaign `FOR UPDATE`, and serialize with an author at the member's membership row instead |
| Recovery serializes with another recovery, `add_campaign_member`, a relinquishing transfer and the retention trigger | Recovery's own campaign `FOR NO KEY UPDATE`, which conflicts with every `FOR UPDATE` and with another `FOR NO KEY UPDATE` | Unchanged; recovery is not edited |
| Recovery against an in-flight authoring write | Previously the author waited for recovery at the campaign row, the inverted order that deadlocks | Recovery now waits for the author at the membership `FOR UPDATE`, as `end_campaign_membership` does. Recovery only adds authority (an owner role, a status change to `active`, closing a delegation for a membership that was not active), so the author's earlier authorization stays valid at its commit |

**Rejected alternatives.**

- *Reorder recovery to lock the membership before the campaign.* The membership may not exist yet: recovery inserts it under the campaign lock. A membership created concurrently would still be locked after the campaign. This also edits a command A1 reviewed.
- *Take the campaign row first in `lock_authoring_scope`.* This reintroduces the deadlock against the retention trigger that the helper's comment records.
- *Drop the campaign lock.* This loses archive serialization.

### 6.3 Callers of the shared helper (traced at `6a5773d`)

There are 64 call sites across 28 command modules. `lock_operation_scope` ([_operations.py:30](../src/dnd_ai/commands/_operations.py#L30)) delegates to `lock_authoring_scope` (`:43`) and adds only the read of the campaign's timeline id.

**Direct calls of `lock_authoring_scope`** (29, in 13 modules):

- `dungeons`, `entity_lifecycle`, `item_definitions`, `item_instances`, `knowledge_definitions`, `locations`, `npc_portrayal`, `npcs`, `organizations`, `quest_definitions`, `religions`, `sources`, `world_relationships`.
- Player-character identity writes reach it through `player_characters` → `npcs.create_character_identity` / `update_character_identity`.

**Calls of `lock_operation_scope`** (35, in 15 modules):

- `campaign_clock`, `character_builds`, `dungeon_state`, `encounter_operations`, `encounter_preparation`, `event_corrections`, `item_operations`, `knowledge_runtime`, `parties`, `party_members`, `quest_runtime`, `session_authoring`, `session_play`, `travel`, `world_time`.

**What each caller does after the helper, checked by grep across all of them:**

- None locks `campaign.campaigns`, `security.campaign_memberships` or `security.membership_roles` again, in any mode. So no caller upgrades from the new mode later.
- Three read campaign columns without a lock: `character_builds.py:85` and `item_definitions.py:138` read `ruleset_version_id`; `item_instances.py:47` joins on it. `ruleset_version_id` and `timeline_id` are not editable by any application command (`update_campaign` writes only `name` and `description`), so a non-key `UPDATE` can't change them under the author.
- Every caller's later locks (entities, sessions, encounters, clock rows, advisory locks) are below the campaign row in the existing order and are unaffected.

Behavior change for callers: none, except that a concurrent recovery no longer makes them wait or fail.

### 6.4 Deterministic regressions (P0)

All of these run against PostgreSQL 18. Each uses the lock-wait harness already in the tree:

- `race(engine, hold, racer, blocked_on)` and `_wait_until_blocked` in `tests/database/test_content_authoring_concurrency.py`, which wait on a `pg_stat_activity` predicate;
- `_PidHold`, `_run_command` and `_wait_until_blocked_by` in `test_character_reveal_delegation_deadlocks.py`, which check `pg_blocking_pids`.

Where a test must stop a command *between two of its own statements*, it uses a `before_cursor_execute` listener on that command's connection. The listener blocks on a `threading.Event` when it sees the statement that marks the pause point, as the review probe did. Every test releases held locks on failure and reports a racer that finished before blocking, instead of waiting out a timeout.

1. **Author first, recovery second (the reproduced case).**
   - Setup: `_strand_the_campaign_for_recovery`, so the promoted member is a finite owner with `canon.edit`.
   - The author's real authoring command (for example `create_location`) is paused just before its campaign statement, while holding its membership `FOR SHARE`.
   - Start `recover_campaign_access_manager` for that user, and wait until `pg_blocking_pids` shows recovery blocked by the author. Then resume the author.
   - Expect: the author commits its write, then recovery commits; no 40P01; the promoted member holds the recovered role.
   - On `6a5773d` this test fails with 40P01.
2. **Recovery first, author second.**
   - Recovery is paused after its campaign `FOR NO KEY UPDATE`, before its membership statement.
   - The author's command runs to completion while recovery is paused. That directly shows `KEY SHARE` does not wait for `FOR NO KEY UPDATE`. Then resume recovery.
   - Expect: both commit.
   - On `6a5773d` the author blocks on the campaign row, and the test fails because the author is not complete while recovery is paused.
3. **Campaign archive still serializes, in both orders.**
   - (a) This is the existing `test_a_creation_waits_for_an_in_flight_campaign_archive_and_is_refused`, but its wait predicate `'%FROM campaign.campaigns WHERE campaign_id = %FOR SHARE%'` must become `'%FOR KEY SHARE%'`. `FOR KEY SHARE` does not contain the text `FOR SHARE`. Keep the assertions: `CampaignArchivedError`, nothing written.
   - (b) New: the author is paused after its campaign lock, and `archive_campaign` blocks on it (`pg_blocking_pids`). The author commits, then the archive commits.
4. **Role loss still serializes.** The existing tests `test_a_creation_waits_for_an_in_flight_role_revocation_and_is_refused` and `test_a_role_revocation_waits_for_an_in_flight_creation_and_the_write_stands` must pass unchanged. Add the variant where the revoked role is the built-in owner (the retention trigger fires at commit), with the author waiting at its role-row lock. Expect: refused with `CampaignNotAuthorizedError`, no deadlock.
5. **Membership end still serializes, in both orders (new).** `end_campaign_membership` against an authoring write by that member:
   - an end in flight makes the write wait at the membership lock, then refuse (404), with nothing written;
   - a write in flight makes the end wait, and the write stands.
6. **A deny is still ordered (new; protects D8 later).** `create_resource_grant` of a whole-character `campaign.view` deny for the author, held in flight, makes the author's command wait at the campaign `KEY SHARE`. That test asserts only the wait and the ordering. It asserts no outcome, because existing authoring commands don't consult per-character denies.
7. **Recovery serialization is unchanged.** Rerun `test_character_reveal_delegation_deadlocks.py` and `test_stranding_and_recovery.py` unchanged.

### 6.5 P0 acceptance and boundary

- **Code:** one line in `_content.py` (the lock mode), the helper's docstring and lock-order comment updated to name `KEY SHARE` and why, and the test changes in §6.4.
- **Docs:**
  - [SYSTEM_ARCHITECTURE.md](architecture/SYSTEM_ARCHITECTURE.md): line 315 ("campaign `FOR SHARE` (required `active`)"), and line 321 (the "takes `FOR SHARE` on the parent" rule, noting the campaign exception and its reason);
  - a DEF-014 entry in the defect register (reproduction, fix, regressions).
- **Checks:**
  - the new and modified tests;
  - `test_content_authoring_concurrency.py`, `test_scoped_roles_concurrency.py`, `test_authoring_concurrency.py`, the A1 suites (`test_campaign_owner_*.py`, `test_character_reveal_delegation*.py`) and `test_stranding_and_recovery.py`;
  - the full `pytest`;
  - `ruff format --check`, `ruff check`, `mypy src`, `git diff --check`.
- **Not in P0:** DEF-015, DEF-016, any A2 code, the four untracked plans, and push.
- **Commit locally and stop for independent review,** naming the parent and target SHAs.

### 6.6 Related findings that P0 does not fix

- **DEF-015 (proposed; reproduced 2026-11-07): adding a member to an access group against that member's authoring write.** Designed in §7 as prerequisite commit P1. The first candidate recorded here, membership locks before a campaign `FOR UPDATE`, was tested and **rejected**: it deadlocks with recovery (§7.4).
- **DEF-016 (proposed; found by reading, not tested): a per-character `canon.edit` deny is unreachable in the view-tier and inventory resolvers.** See §5.7a. Its fix is to read the `entity_id` key. That would reduce a GM's view of a character they are denied, so it needs its own decision and tests. It is outside P0 and A2.

---

## 7. Prerequisite commit P1 (for Sonnet, before A2a): DEF-015, adding an access-group member

**Status:** designed 2026-11-07 against `4dd56fd`; not implemented. It is one bounded commit on `phase15/completion`, reviewed on its own before any A2a code. It changes no schema, no API shape and no response body.

### 7.1 The defect (proposed DEF-015, reproduced)

**How it was reproduced.**

- **The probe.** A throwaway pytest module, deleted afterwards and never committed, ran on the suite's own disposable database. `postgres_engine` creates a fresh database per run, upgrades it to head and drops it afterwards. The server was local PostgreSQL 18.
- **Fixtures.** The probe reused P0's fixtures: an author whose only campaign role is a custom one with `canon.edit`, and `stranded` for recovery.
- **Each scenario:**
  1. Start the first command and pause it at a named statement, using a `before_cursor_execute` listener on its thread.
  2. Start the second command.
  3. Record whether `pg_blocking_pids` shows the second blocked by the first, or whether it finished while the first was paused.
  4. Release the first command and join both threads.
- **Variants.** The same scenarios ran against HEAD, the proposed correction (§7.3) and two rejected variants (§7.4).

| # | First command (paused) | Second command | HEAD `4dd56fd` | P1 (§7.3) |
|---|---|---|---|---|
| S1 | An author, holding its membership `FOR SHARE`, just before its campaign lock | Add that author to a group | Add blocked by the author, then **40P01** | Both commit |
| S2 | Add, before its second lock (HEAD: holds the campaign; P1: holds the memberships) | That member's authoring write | Author blocked by the add, then **40P01** | Both commit |
| S3 | Recovery of the member, holding the campaign `FOR NO KEY UPDATE`, before its membership statement | Add that member | Both commit (the add waits at the campaign) | Both commit (the add finishes while recovery is paused) |
| S4 | Add, before its second lock | Recovery of that member | Both commit | Both commit (recovery waits at the membership) |
| S5 | End of the added member's membership, after its role and membership locks | Add that member | **40P01** | The end commits; the add is refused with `MembershipNotActiveError` (409), nothing written |
| S6 | Add, before its second lock | End of that member's membership | **40P01** | Both commit; the end closes the new group row |
| S7 | A2a release lock prefix (authority rows S, membership `KEY SHARE`), before its campaign lock | Add the releaser | **40P01** | Both commit, **but the add does not wait for the release** |
| S8 | Add, before its second lock | The release prefix | **40P01** | Both commit; the release does not wait |
| S7b | As S7, with the release's membership `FOR SHARE` | Add the releaser | **40P01** | The add waits for the release; both commit; the release saw no group row |
| S8b | Add, before its second lock | The release prefix with membership `FOR SHARE` | **40P01** | The release waits for the add; both commit; **the release sees the new group row** |
| S9 | Add made by a second owner, just before its insert | End of that owner's membership | **40P01** | Both commit |
| S10 | End of the second owner's membership, after its locks | Add made by that owner | **40P01** | Both commit (see §7.9, residual 1) |
| S11 | `create_resource_grant` made by the member being added, after its campaign lock | Add that member | Both commit | Both commit |
| S12 | Add, before its second lock | That grant | Both commit | Both commit |
| S13 | Add, holding the campaign, before its account lock | Revocation of that member's role (retention trigger at commit) | Both commit | Both commit |
| S14 | Add by the owner of member M to group G1 | Add by M of the owner to group G2 | Both commit (serialized at the campaign) | Both commit (no wait) |
| S15 | Group deactivation, after its status update | Add to that group | The add is refused with `AccessGroupNotInCampaignError` (404, wrong class: §7.9, residual 2) | Unchanged; this statement is not edited |

**The original report understated the scope.** At HEAD, adding a member deadlocks with:

- that member's authoring write (S1, S2);
- ending that member's membership (S5, S6);
- ending the adding manager's own membership (S9, S10);
- A2a's release (S7, S8).

Recovery (S3, S4) works, because both commands take the campaign row first.

**Origin.** Commit `1a46b87` (the batch add) moved the campaign lock ahead of the membership locks. Before it, `6cbd12a` locked group, membership, campaign, then account. The module docstring and `test_access_group_concurrency.py`'s docstring still describe that older order.

**Grade (proposed):** 0 + 1 + 1 + 0 + 1 = **3, Low**.

- Exposure 0: not deployed.
- Impact 1: one request of the pair fails with an unclassified 500. A retry succeeds, nothing is written and nothing is disclosed.
- Triggerability 1: two ordinary manager or member actions with narrow timing.
- Detection 0.
- Blast radius 1: every authoring and operation command, and membership end.

### 7.2 Both lock sequences, traced at `4dd56fd`

**Adding members** (`POST …/access-groups/{group}/members`, [api/access_groups.py:528](../src/dnd_ai/api/access_groups.py#L528) → [access_groups.py:597](../src/dnd_ai/commands/access_groups.py#L597)):

1. With an `Idempotency-Key`, `begin_idempotent_request` inserts first. Its foreign keys take `KEY SHARE` on the actor's account and on the campaign row. Without a key, it takes nothing.
2. The group: `FOR UPDATE OF ag` (`:634`).
3. The campaign: `FOR UPDATE OF c` (`:660`).
4. For each member, in UUID order: the membership `FOR UPDATE OF cm`, joined to `membership_statuses` (`:685`); then the account `FOR UPDATE OF u` (`:722`).
5. For each member, an `INSERT INTO security.access_group_memberships`. Its foreign keys take `KEY SHARE` on the group and the member's membership (both already held) and on the **actor's membership**, through `added_by_membership_id`. That is the first lock on the actor's membership, and it comes after the campaign. The `BEFORE INSERT` scope trigger only reads.
6. The endpoint then:
   - reads `timeline_world_id` without a lock;
   - inserts one `audit.change_log` row per member, whose foreign key takes `KEY SHARE` on the actor's account;
   - updates its own idempotency row.
7. At commit, nothing more is locked. `access_group_memberships`, `audit.change_log` and `idempotent_requests` have no deferred trigger.

**The commands it meets:**

| Command | Locks, in order (commit-time locks last) |
|---|---|
| Authoring and operation writes (`lock_authoring_scope`, after P0) | Idempotency insert (`KEY SHARE` on the campaign and account) → world (S) → the actor's role rows and membership (S) → account (S) → campaign (`KEY SHARE`) → entities and the rest → audit insert (`KEY SHARE` on the account). Nothing further at commit for these rows |
| `end_campaign_membership` | The target's role rows (U) → its membership (U) → `UPDATE`s (the `ended_by_membership_id` foreign key takes `KEY SHARE` on the ender's membership) → closes the target's open `access_group_memberships` rows → delegation rows → at commit, the retention trigger takes the campaign row `FOR UPDATE` |
| `recover_campaign_access_manager` | Campaign (`FOR NO KEY UPDATE`) → the member's membership (U), or an insert → a status `UPDATE` when the status changes → role insert → at commit, the retention trigger takes the campaign `FOR UPDATE` only if a membership row was updated |
| `revoke_membership_role` / `change_membership_role` | Role row (U; `change` also takes the membership and role U) → at commit, the retention trigger takes the campaign `FOR UPDATE` |
| `create_resource_grant` | The grantee's membership (U) or group (U) → campaign (U) → the grantee's account (U) → target (U) → capability (U) → insert (the foreign key takes `KEY SHARE` on the **granter's** membership) |
| `remove_access_group_member` | The `access_group_memberships` row (U) only. Its `UPDATE` of `removed_at` changes no foreign-key column and takes no other lock |
| `deactivate_access_group`, `update_access_group`, `reactivate_access_group` | The group (U); reactivate then takes the campaign (U) |
| `create_access_group` | Campaign (U); the insert's foreign key is on the campaign row it already holds |

**The cycles at HEAD.**

- **S1/S2.** The add holds the campaign `FOR UPDATE` and wants the member's membership. The author holds that membership `FOR SHARE` and wants the campaign `KEY SHARE`, which conflicts with `FOR UPDATE`.
- **S5/S6.** The add holds the campaign and wants the membership. The end holds the membership and wants the campaign at commit.
- **S9/S10.** The add holds the campaign and wants `KEY SHARE` on the actor's membership for its insert. Ending the actor's membership holds that row `FOR UPDATE` and wants the campaign at commit.
- **S7/S8.** The same shape as S1/S2, with the release.

### 7.3 The correction: three lock changes in one command

**What changes.** Only `add_access_group_members`. Its new order:

1. **The group:** `FOR UPDATE OF ag`, with the group checks unchanged.
2. **The members' memberships,** in the existing UUID order, each `FOR NO KEY UPDATE`, in a **locking statement without a join**:

   ```sql
   SELECT campaign_id, ended_at, user_id, membership_status_id
   FROM security.campaign_memberships
   WHERE campaign_membership_id = :membership
   FOR NO KEY UPDATE
   ```

3. **The actor's membership** (`added_by_membership_id`): `FOR KEY SHARE`, the mode its foreign key takes anyway. This mirrors `_lock_foreign_key_targets` in [character_reveal.py](../src/dnd_ai/commands/character_reveal.py). It is harmless when the actor is also a member being added.
4. **The campaign:** `FOR KEY SHARE OF c`, with the `active` check and `CampaignNotActiveError` unchanged.
5. **Validation, per member, in UUID order, from the locked rows:**
   1. a row that is missing or belongs to another campaign → `MembershipNotInCampaignError`;
   2. the status, from an unlocked read of `security.membership_statuses` by id → `MembershipNotActiveError`;
   3. the account `FOR UPDATE OF u`, and its check, unchanged.
6. **The inserts,** unchanged.

**Error precedence is unchanged:** group, then campaign, then each member in UUID order (in the campaign, then active, then account active). The same request gets the same error class it gets today. The only differences are which rows are locked before the error is raised, and that a waiting request no longer fails with a 500.

**Why each piece is needed:**

| Piece | Without it | Evidence |
|---|---|---|
| Memberships before the campaign | The authoring, membership-end and release cycles remain (§7.2) | S1, S2, S5–S8 at HEAD |
| Campaign `KEY SHARE`, not `FOR UPDATE` | With memberships first and the campaign `FOR UPDATE`, recovery (campaign `FOR NO KEY UPDATE` → membership) deadlocks in both orders | S3/S4 under the variant "memberships first, campaign `FOR UPDATE`": 40P01 |
| Members `FOR NO KEY UPDATE`, not `FOR UPDATE` | `create_resource_grant` made *by* a member being added takes `KEY SHARE` on that member's membership at its insert, after its campaign `FOR UPDATE`. A `FOR UPDATE` held by the add while it waits for the campaign deadlocks with it. The reveal-delegation grant chose `FOR NO KEY UPDATE` for the same reason | S11/S12 under the variant "memberships `FOR UPDATE`, actor `KEY SHARE`, campaign `KEY SHARE`": 40P01 |
| The actor's membership locked before the campaign | The insert's foreign-key `KEY SHARE` on the actor comes after the campaign, so ending the actor's membership deadlocks with it | S9/S10 without it: 40P01 in every variant |
| A locking statement without a join | In READ COMMITTED, a `FOR … OF cm` statement joined to `membership_statuses` that waited on an updated row re-checks the join against the old status row and returns **no row**. An add that waited behind an end was then refused with `MembershipNotInCampaignError` (404) instead of `MembershipNotActiveError` (409). The reorder makes this wait reachable; at HEAD it ended in a deadlock instead | S5 under every joined variant: `MembershipNotInCampaignError`; P1: `MembershipNotActiveError` |

**What each mode still excludes:**

- **A member's `FOR NO KEY UPDATE`** conflicts with:
  - `FOR UPDATE`: ending the membership, recovery, role assignment and change, and a resource or relationship grant to that member;
  - `FOR NO KEY UPDATE`: a status `UPDATE`, a reveal-delegation grant to the member, and another add of the same member;
  - `FOR SHARE`: that member's authoring and operation writes, and A2a's release.

  It does not conflict with `KEY SHARE`, which the foreign keys of rows the member creates or is named in take.
- **The actor's `KEY SHARE`** conflicts only with `FOR UPDATE`: ending the actor's membership, recovery or role changes for the actor, and a grant to the actor.
- **The campaign `KEY SHARE`** conflicts with every campaign `FOR UPDATE` taker:
  - archive, reactivate and settings edits;
  - the retention trigger at commit;
  - `create_resource_grant` and `grant_character_relationship`;
  - `create_access_group` and `reactivate_access_group`;
  - `add_campaign_member` and a relinquishing transfer.

  So an add still cannot commit into an archived campaign. It does not conflict with recovery's `FOR NO KEY UPDATE`, nor with the `KEY SHARE` that authoring, delegation and the idempotency foreign key take.

**Preserved behaviour:**

| Protection | After P1 |
|---|---|
| **Group membership authorization:** the route requires `access.manage`; the group must be in the campaign and active; each member must be in the campaign, open, active and on an active account; the batch is atomic | Unchanged. The same checks run in the same order on rows locked before they are read. Fingerprint, response and audit are unchanged |
| **Membership end against an add** | Serialized at the member's membership in both orders (S5, S6). An add that waited is refused with 409. An end that waited closes the row the add inserted, because its `UPDATE` takes a fresh snapshot after its lock wait |
| **Role loss** | A revoked member's role rows are not locked by the add, and the revocation's commit-time campaign `FOR UPDATE` waits for the add's `KEY SHARE` while the add needs nothing the revocation holds (S13). `change_membership_role` takes the membership `FOR UPDATE`, so it serializes at the membership |
| **Recovery** | Its campaign `FOR NO KEY UPDATE` is compatible with the add's `KEY SHARE`. The two serialize at the promoted member's membership, in both orders (S3, S4). Recovery's code is unchanged |
| **Authoring** | Serialized at the member's membership (`FOR NO KEY UPDATE` against `FOR SHARE`) in both orders (S1, S2). The author's authorization is still re-checked under its own locks, so a deny added by the group is seen by an author that waited |
| **Account deactivation** | The account `FOR UPDATE` is unchanged and taken after the campaign, as today |
| **Overlapping adds** | The same group still serializes on the group row. For different groups, members are locked in UUID order, so no cycle is possible (`FOR NO KEY UPDATE` conflicts with itself). The actor's `KEY SHARE` conflicts with neither mode used by another add (S14) |
| **Archive** | The campaign `KEY SHARE` still waits for, and is waited on by, `FOR UPDATE` |

### 7.4 Rejected alternatives

- **Memberships first with the campaign still `FOR UPDATE`** (the candidate in the first §6.6 note). This deadlocks with recovery in both orders (S3, S4: 40P01), the same cycle A1 removed for the delegation grant.
- **Campaign `KEY SHARE` first, keeping its position.** The cycle with membership end remains, because the end's commit-time campaign `FOR UPDATE` conflicts with `KEY SHARE`. Found by trace, not probed.
- **Memberships `FOR UPDATE`, actor `KEY SHARE`, campaign `KEY SHARE`.** This deadlocks with a resource grant made by a member being added (S11, S12: 40P01).
- **Taking the campaign first in `lock_authoring_scope`.** This reverses P0's helper and its recorded retention-trigger deadlock.
- **Weakening authoring's membership lock to `KEY SHARE`.** That loses serialization against role and membership-status changes, and the D8 deny ordering.

### 7.5 Callers and neighbours checked

- **Callers of the changed function.**
  - `add_access_group_members` has one production caller: the add endpoint ([api/access_groups.py:572](../src/dnd_ai/api/access_groups.py#L572)).
  - `add_access_group_member` is a thin wrapper used only by tests.
  - The endpoint's idempotency insert, audit inserts and receipt keep their positions (§7.2).
  - `queries/access_overview.py` and `queries/audit_history.py` only name the command.
- **Removing a group member** (`remove_access_group_member`) is unaffected and is not edited. It locks only its own row and writes no foreign-key column.
  - Against an add of the same pair, the insert's partial unique index waits for the remover's transaction while the remover waits for nothing.
  - It needs no campaign or membership lock, because closing access stays available regardless of lifecycle, as the module docstring requires.
- **Group lifecycle.** `deactivate_access_group`, `update_access_group`, `reactivate_access_group` and `create_access_group` are unchanged. The first three serialize with an add on the group row. `create_access_group` locks no membership.
- **`create_resource_grant` with a group grantee** takes the group and then the campaign `FOR UPDATE`. That serializes with an add to the same group at the group row. With an add to another group, it serializes at the campaign (`FOR UPDATE` against `KEY SHARE`), and neither waits for anything else the other holds.
- **`end_campaign_membership`** closes the member's `access_group_memberships` rows. Covered by S5/S6, and by S9/S10 for the actor.
- **Documentation and comments that name the add's campaign `FOR UPDATE`** become inaccurate and change in P1 (§7.8):
  - P0's comment in [_content.py](../src/dnd_ai/commands/_content.py) ("the resource-grant, relationship and access-group writes");
  - [SYSTEM_ARCHITECTURE.md](architecture/SYSTEM_ARCHITECTURE.md) line 315;
  - [PHASE13E_ACCESS_CONTRACT.md](PHASE13E_ACCESS_CONTRACT.md) line 554;
  - the `access_groups.py` module docstring ("Lock ordering");
  - item 2 of `test_access_group_concurrency.py`'s docstring.
- **Existing tests that must pass unchanged:**
  - `test_access_group_concurrency.py` (every add test there runs the add to completion first, then shows the competitor blocked);
  - `test_api_access_groups.py`, including error-precedence and idempotency cases;
  - `test_resource_grant_concurrency.py`;
  - `test_authoring_scope_recovery_locks.py`;
  - `test_content_authoring_concurrency.py`;
  - `test_character_reveal_delegation_deadlocks.py`;
  - `test_stranding_and_recovery.py`.

### 7.6 Consequence for A2a: the release takes its membership `FOR SHARE`

With P1, an add no longer conflicts with any campaign lock a release holds.

- **With `KEY SHARE`** on the releaser's membership, a release does not conflict with the add's `FOR NO KEY UPDATE`. So an add of the releaser to a group carrying a deny could commit between the release's re-resolve and its write (S7, S8: neither waits).
- **With `FOR SHARE`**, they serialize at the membership and neither deadlocks (S7b, S8b). If the add commits first, the release's re-resolve sees the group row.

`FOR SHARE` is the mode `lock_authoring_scope` already takes on the same row. §5.8 records the release's other pairings under this mode; none of them inverts.

### 7.7 Race harness: failure cleanup (addresses the nonblocking P0 harness finding)

**The finding**, as the owner summarized it (its text is not in the repository): failure cleanup must release blockers and join worker commands before fixture teardown. In P0's module:

- `_paused` releases the pause on exit, but the worker threads started inside it are joined only on the success path.
- `observed_race` rolls the holder back on failure, but never joins its racer.

So after a failed assertion, `editor`, `stranded` and `fx` can tear down, deleting rows with `session_replication_role = replica`, while a worker transaction is still open or blocked. Teardown can then wait on that worker, or a daemon worker can outlive the test.

**P1 adds one test helper module**, `tests/lock_race_support.py`, alongside `tests/content_support.py`. It is used as a context manager inside the test body, so it exits before pytest begins any fixture teardown, whatever order the fixtures were requested in:

```python
with LockRace(engine) as race:
    pause = race.pause(thread_name="add", pattern=..., after=None)
    add = race.start("add", operation)
    pause.wait_reached(add)
    author = race.start("author", other_operation)
    race.wait_blocked_by(pause, author)
    pause.release()
    race.join_all()
```

**Its contract:**

1. `start` runs the operation in its own `engine.begin()` transaction on a named thread. It records the backend pid at the first statement, and its result or exception.
2. `pause` registers the `before_cursor_execute` listener as P0's `_Pause` does, keyed by thread name.
3. `hold` opens a held row lock on its own connection.
4. **On exit, success or failure, in this order:**
   1. Every pause that was not released by the test is put into abort mode and released. The paused worker raises inside its own transaction and rolls back, rather than committing half a scenario.
   2. Every hold is rolled back and closed.
   3. Every worker is joined, each with the existing 15-second bound.
   4. A worker still alive gets `pg_cancel_backend`, then `pg_terminate_backend`, on its recorded pid through a separate connection, and is joined again.
   5. The listeners are removed.
5. **Reporting.**
   - If the body raised, that exception propagates unchanged, and any cleanup problem is attached as a note, never replacing it.
   - If the body passed but a worker had to be cancelled or terminated, or never finished, the exit raises `AssertionError` naming the worker and `_waiting_sessions()`. A passing scenario with a stuck worker is a failure.
6. `wait_blocked_by` and `wait_reached` keep P0's behaviour. They follow the `pg_blocking_pids` chain, and report a worker that finished before blocking as it ended, instead of waiting out the clock.

**P1 also does two retrofits:**

- `test_authoring_scope_recovery_locks.py` uses `LockRace` in place of its own `_start` and `_paused`, with its 12 tests otherwise unchanged.
- `observed_race` (`test_content_authoring_concurrency.py`) joins its racer in a `finally`, after rolling the holder back, with the same bound.

**No committed test exercises the harness itself** (CLAUDE.md §6, §7.9). The implementer checks once by hand that a forced assertion failure inside a `LockRace` block leaves no session of the test database `idle in transaction` or waiting on a lock, and records that in the commit evidence.

### 7.8 P1 scope and acceptance criteria (for Sonnet)

**Code (one command):** `add_access_group_members` as specified in §7.3; its docstring states the lock order, the modes and why. Nothing else in `src/` changes, apart from the comment in `_content.py` (§7.5).

**New tests.** These go in `tests/database/test_access_group_member_add_locks.py`, using `LockRace` and real commands. Each wait is observed through `pg_blocking_pids` as blocked by the intended session, or the scenario asserts the second command finished while the first was paused. No longer timeouts are used, and no assertion relies on `lock_timeout`.

1. **The author first** (S1). `create_location` by a `canon.edit` member is paused before its campaign statement. Adding that member is blocked by the author. On release, both commit: the location exists, and the member's group row is open. At `4dd56fd` this fails with 40P01.
2. **The add first** (S2). The add is paused before its campaign statement (after its membership locks), and the author is blocked by the add. Both commit. At `4dd56fd` this fails with 40P01.
3. **Recovery, both orders** (S3, S4), with the `stranded` fixture.
   - Recovery paused after its campaign lock: an add of the promoted member finishes while recovery is paused, then recovery commits.
   - The add paused before its campaign statement: recovery is blocked by the add, and both commit.
   - The promoted member holds the owner role and the group row.
   - These pass at HEAD. They fail for the rejected variant with the campaign `FOR UPDATE`, which is what they guard against.
4. **Ending the added member's membership, both orders** (S5, S6).
   - End first: the add is blocked by the end, then refused with `MembershipNotActiveError`. No group row is written.
   - Add first: the end is blocked by the add, then both commit. The new group row is closed and listed in `removed_access_group_membership_ids`.
   - At `4dd56fd` both fail with 40P01. End-first asserts the error class, which pins the locking statement without a join.
5. **Ending the actor's membership, both orders** (S9, S10). The actor is a second built-in owner, and the original owner stays a non-expiring manager. Both commit in both orders. At `4dd56fd` both fail with 40P01. The end-first case records §7.9 residual 1 in its docstring.
6. **A resource grant made by a member being added, both orders** (S11, S12). `create_resource_grant` with `granted_by_membership_id` set to the member being added. Both commit. This guards the member mode against `FOR UPDATE`.
7. **Role revocation of the added member** (S13). The add is paused while holding the campaign; the revocation is blocked by the add at its commit-time campaign lock; both commit.
8. **Crossed adds** (S14). An add by A of B, and an add by B of A into another group: both commit.
9. **Through the API, one case.** `POST …/members` with an `Idempotency-Key`, against an author paused before its campaign lock. 201, one audit row and one receipt; the author's write stands. This covers the idempotency and audit foreign-key locks in §7.2.
10. **The existing suites pass unchanged** (§7.5). The docstring wording updated in `test_access_group_concurrency.py` is the only edit there.

**Docs, in the same commit:**

- the `access_groups.py` module and function docstrings;
- the `_content.py` comment;
- [SYSTEM_ARCHITECTURE.md](architecture/SYSTEM_ARCHITECTURE.md) line 315, saying that access-group member additions serialize with an author at the member's membership row, not the campaign row;
- [PHASE13E_ACCESS_CONTRACT.md](PHASE13E_ACCESS_CONTRACT.md) line 554 (the order and modes);
- a **DEF-015** entry in the defect register, with this reproduction, the grade, the fix and the regressions. DEF-016 and DEF-017 stay proposed in this plan until the owner decides whether to register them.

**Checks:**

- the new tests, which must fail at `4dd56fd` where the criteria above say so (run once against the parent and recorded);
- the suites in §7.5, plus `test_character_reveal_delegation*.py` and `test_campaign_owner_*.py`;
- the full `pytest`;
- `ruff format --check`, `ruff check`, `mypy src` and `git diff --check`.

**Not in P1:**

- A2a code; DEF-016; residuals 1 and 3 below;
- `create_resource_grant`, `grant_character_relationship`, recovery and every other command;
- the four untracked plans; push.

**Commit locally and stop for independent review,** naming the parent (`4dd56fd`, or P0's reviewed successor) and the target SHA.

### 7.9 Residuals found while tracing (not fixed by P1)

1. **The add's authorization is not re-checked under lock.**
   - **What happens.** The route judges `access.manage` before the command, without locks. An add that waits behind the end of the adding manager's own membership (S10), or behind the revocation of that manager's role, still commits, and `added_by_membership_id` then names an ended membership.
   - **Is it new?** No. It predates P1: at HEAD those pairs deadlock instead. `create_resource_grant` and the other `access.manage` commands behave the same way.
   - **What fixing it needs.** The DEF-013 pattern, applied to the access-management commands as a set: lock the actor's role rows and membership, then re-check at a fresh instant. This needs its own design. It is recorded here and not proposed as a DEF.
2. **Proposed DEF-017: a stale join in the group lock misclassifies a race.**
   - **What happens.** `add_access_group_members`, `update_access_group`, `deactivate_access_group` and `reactivate_access_group` lock the group with `FOR UPDATE OF ag` joined to `lifecycle_statuses`. A command that waited behind a deactivation gets no row and reports `AccessGroupNotInCampaignError` (404) instead of `AccessGroupNotActiveError` (409).
   - **Evidence.** Reproduced at HEAD as S15.
   - **Grade (proposed):** 0 + 0 + 1 + 0 + 0 = 1, Low.
   - **Fix.** Use the same pattern as §7.3: lock without a join, then read the status.
   - **Not fixed by P1.** P1 does not edit the group statement, so the defect is unchanged.
3. **Other late foreign-key locks on an actor's membership.** `create_resource_grant` (`granted_by_membership_id`) and `end_campaign_membership` (`ended_by_membership_id`) take `KEY SHARE` on the actor's membership after their target or campaign locks. P1 does not change them.
   - **Against an add.** P1's member mode `FOR NO KEY UPDATE` makes those late locks compatible with an add (S11, S12).
   - **Elsewhere.** Whether they cycle with other commands was not traced. That is a candidate for a later lock-order audit, not part of DEF-015.
   - **Traced 2026-11-08.** Both do cycle: see §10.8.5 and §10.8.6, and proposed DEF-019 and DEF-021 in §10.11.

---

## 8. A2a review correction A2a-R: making the D8 denies creatable (proposed DEF-018)

**Status:** designed 2026-11-07 by reading source at `0b4704c`. Not implemented, and no probe was run. It is one bounded commit on `phase15/completion`, on top of A2a, and the A2a review cannot close until it lands. It changes no schema, no route and no request or response shape: one response field is filled in where it was `null`. The owner answered Q1, Q2 and Q3 on 2026-11-07 (§8.8); the answers are applied below.

### 8.1 The defect

**The readers.** D8 and every existing character reader look for both denies under the `("entity_id", character_id)` key:

- [public_profiles.py:88](../src/dnd_ai/domain/public_profiles.py#L88) (`whole_character_denied`) and `:94` (`canon_edit_denied_for_character`, which also counts a stray `character_id` row);
- character detail, parties, relationships and sheet: [api/characters.py](../src/dnd_ai/api/characters.py) `:498`, `:625`, `:721`, `:875`;
- inventory: [api/access.py:513](../src/dnd_ai/api/access.py#L513);
- party rosters: [api/parties.py:167](../src/dnd_ai/api/parties.py#L167);
- event explanations: [api/event_explanations.py:200](../src/dnd_ai/api/event_explanations.py#L200);
- World Explorer search and reference mode: `_grant_denied_entity_ids` in [api/world_explorer.py:133](../src/dnd_ai/api/world_explorer.py#L133).

**The writer refuses both keys.**

- **`character_id` target.** The catalog allows only the nine `character.*` codes ([access.py:131](../src/dnd_ai/domain/access.py#L131), `:229`). `campaign.view` and `canon.edit` are refused with `ResourceGrantCapabilityNotGrantableError` (404).
- **`entity_id` target.** The catalog allows `campaign.view` and `canon.edit`. But the P-8 CTI guard ([access_grants.py:1063](../src/dnd_ai/commands/access_grants.py#L1063), applied at `:1192`–`:1214`) refuses any entity whose type is `character`, `npc` or `player_character`, with `TargetNotInCampaignWorldError` (404).

**The database permits it.** `ck_resource_grants_exactly_one_target`, the `entity_id → core.entities` foreign key and `enforce_resource_grant_scope()`, which checks only the world, all accept such a row. That is how the inventory tests and A2a's tests create these denies: directly, with `make_resource_grant`.

**Why the guard is wrong here, and only here.** Its rationale is that the read side keys off the dedicated column, so a grant in `entity_id` would be inert. That holds for `character.*` codes, which readers check under `character_id`. It is false for `campaign.view` and `canon.edit` on a character:

- every reader above checks them under `entity_id`;
- `character_id` cannot carry them at all.

So the guard blocks the only representation the readers use. The other own-column kinds (`event`, `quest`, `knowledge_item`) are unaffected: their readers do key the dedicated column, for example `resource_grant_targets(cap, "event_id")`.

**Consequence.** ADR 0021 §2.9's whole-character deny and D8's per-character `canon.edit` deny exist only as raw SQL. An owner cannot apply either through the API, and A2a's deny tests and races prove behaviour that no application path can reach.

**Grade (proposed):** 0 + 1 + 2 + 0 + 1 = **4, Medium**.

- Exposure 0: not deployed.
- Impact 1: a documented access restriction cannot be applied; nothing leaks.
- Triggerability 2: every attempt fails.
- Detection 0: the refusal is visible.
- Blast radius 1: every character.

### 8.2 The correction, and the alternatives rejected

**Recommended: narrow the CTI guard for exactly these two denies.** In `_validate_resource_grant_target`, an `entity_id` target whose entity is a character is accepted when the effect is `deny`. The capability catalog then confines it, as today, to `campaign.view` and `canon.edit`. Everything else the guard refuses stays refused.

- **The change:**
  - `create_resource_grant` passes `effect` to `_validate_resource_grant_target`;
  - add `_CHARACTER_ENTITY_TYPE_CODES = frozenset({"character", "npc", "player_character"})`, the subset of `_OWN_COLUMN_ENTITY_TYPE_CODES` with a `character.characters` row;
  - the guard raises unless `entity_type_code in _CHARACTER_ENTITY_TYPE_CODES and effect == "deny"`.
- **Lock order and error precedence are unchanged:** grantee, campaign, account, target `FOR UPDATE`, capability.
- **The resulting refusals:**
  - an allow on a character entity is still refused at the target step (404);
  - a `character.*` deny under `entity_id` passes the target step and is refused at the capability step (404);
  - both are non-disclosing and write nothing.

**Rejected alternatives.**

| Alternative | Why rejected |
|---|---|
| **B.** Add `campaign.view` and `canon.edit` to the `character_id` catalog, and have readers, or `resolve_access_context`, read both keys | Two representations of one fact. `ux_resource_grants_active` cannot detect a deny duplicated across keys. Ten or more readers, or a resolver-wide remap, change, as do `resource_grant_targets(…, "entity_id")` sets, World Explorer search, the portal's duplicate detection and the overview's `target_type` |
| **C.** Accept the request under `character_id` and store it under `entity_id` | The stored row and the audit's `target_kind` would contradict the request; the portal's duplicate detection compares the request's target type |
| **D.** Remove the guard for characters entirely, allows included | Creates allow rows that every reader ignores today and that would silently become authority under a careless DEF-016 fix (§8.4). See Q1 |

### 8.3 Valid combinations after the correction

| Target column | Target entity | Capability | Effect | Before | After |
|---|---|---|---|---|---|
| `entity_id` | character, npc or player character | `campaign.view` | `deny` | Refused, 404 | **Accepted**: the whole-character deny (ADR 0021 §2.9; D8 item 4) |
| `entity_id` | character, npc or player character | `canon.edit` | `deny` | Refused, 404 | **Accepted**: the `canon.edit` deny on the character (D8 item 5) |
| `entity_id` | character, npc or player character | `campaign.view` or `canon.edit` | `allow` | Refused, 404 | Refused, 404 (Q1) |
| `entity_id` | character, npc or player character | any `character.*` code | either | Refused, 404 | Refused, 404 (catalog) |
| `entity_id` | event, quest or knowledge item | any | either | Refused, 404 | Unchanged |
| `entity_id` | any other entity (location, item, organization, …) | `campaign.view` or `canon.edit` | either | Accepted | Unchanged |
| `character_id` | a character | a `character.*` code | either | Accepted | Unchanged |
| `character_id` | a character | `campaign.view` or `canon.edit` | either | Refused, 404 | Unchanged (the catalog) |
| any | any | `character.reveal`, `access.manage`, `import.approve`, `rules_source.manage` | either | Refused | Unchanged (the catalog; A1's trigger for `character.reveal`) |

### 8.4 Who, scope, lifecycle, duplicates, revocation, existing rows

- **Who may create a deny.** Any caller who passes the route filter `access.manage`, on `POST /campaigns/{id}/resource-grants`, for a membership or an access-group grantee. Today that means the built-in owners: custom `access.manage` has no application path (A1 F1). No new gate is added.
  - An owner may deny a co-owner, or themselves. D8 item 4 already says the whole-character deny binds an owner.
  - A denied owner keeps `access.manage` (a resource deny never touches it, migration 080's comment on `effect`), so they can still revoke the deny.
- **Grantee eligibility is unchanged:** an open, active membership on an active account, or an active group, in the route campaign.
- **Campaign scope.** The row carries the route campaign, and `resolve_access_context` reads only that campaign's grants. A deny in campaign A has no effect on the same character's profile or reads in campaign B of the same world.
- **World scope.** The character must belong to the campaign's world. The command checks it, and the scope trigger checks it again; a character from another world is 404.
- **Timeline scope.** The command writes `timeline_id = NULL`, so the deny applies on the campaign's own timeline.
- **Lifecycle.**
  - **At creation:** the character must be active, as for every entity target today (archived → 404). A non-canon character is accepted; the profile routes already 404 it.
  - **Later:** the resolver ignores grants whose target is not active. A deny on a character archived later stops applying while it is archived, and applies again on reactivation. For a deny that is fail-closed. A save or release of an archived character is refused anyway (409 `public_profile_character_not_active`).
- **Duplicates.** `ux_resource_grants_active` (grantee, all target columns, `timeline_id`, capability, effect; `NULLS NOT DISTINCT`) makes an identical active deny a 409. These are distinct rows, and all of them count, with deny winning in `grant_effects`:
  - a deny next to a raw row that has `timeline_id` set;
  - a deny next to a stray `character_id` `canon.edit` deny;
  - one membership deny plus one group deny.
- **Revocation.** It is unchanged, by id, through `POST …/resource-grants/{id}/revoke`, and takes effect on the next request (`AccessContext` is resolved per request).
- **Existing rows.** None can have come from the command since checkpoint 12 introduced the guard. Rows written before that, or by direct SQL, keep their present meaning:
  - their denies already apply;
  - allows on a character under `entity_id` stay inert (below);
  - the overview now names their character (§8.5).

  No migration and no backfill.
- **Access-group changes take effect on the next request.** The resolver counts a group deny only through an open `access_group_memberships` row of an active group. So:
  - adding a member to the group denies them on their next request;
  - removing them, or deactivating the group (which revokes its grants), lifts the deny;
  - reactivating the group does not restore the revoked grants.
- **Does the correction enable new allow grants? No.** Under Q1's recommended answer it creates no allow path. If the owner instead permits allows:
  - a `campaign.view` allow under `entity_id` makes `has_capability` true where the baseline is false, which is inert today, because every route also requires role `campaign.view`;
  - a `canon.edit` allow is read today only by `has_effective_character_canon_edit`, which ignores allows (D8 item 2 is kept either way);
  - but DEF-016's view-tier and inventory checks would turn such an allow into GM-tier visibility if they were ever switched to `entity_id` without restricting them to denies.

  The deny-only rule removes that trap.
- **D8 item 2 is preserved.** `has_effective_character_canon_edit` requires role `canon.edit`, and no change here touches it. The existing test `test_an_allow_grant_of_canon_edit_does_not_confer_editing_or_reading` keeps its raw allow row (stray-row defence) and stays.

### 8.5 Affected routes, options, explanations, resolvers

| Surface | Change |
|---|---|
| `POST /campaigns/{id}/resource-grants` ([api/access_grants.py:457](../src/dnd_ai/api/access_grants.py#L457)), membership and group grantees | Accepts the two new combinations. Request, response, fingerprint (`campaign_id` plus body) and audit (`target_kind: "entity_id"`, `effect: "deny"`) are unchanged |
| `POST …/resource-grants/{id}/revoke` | Unchanged |
| Grant options (`list_grantable_resource_capabilities`, [queries/access_overview.py:553](../src/dnd_ai/queries/access_overview.py#L553)) | Unchanged. `(campaign.view, entity)` and `(canon.edit, entity)` are already listed, and the character-and-deny sub-rule is finer than its `(code, target_type)` grain. Its docstring gains one sentence naming the sub-rule |
| `GET …/access-overview`: member grants (`:404`) and group grants (`:790`) | `target_display_name` is filled in for an `entity_id` target that is a character (`LEFT JOIN character.characters` on `rg.entity_id`), using the same audience-safe `canonical_name` rule as a `character_id` target. `target_type` stays `"entity"`, so the portal's duplicate detection keeps working |
| `GET …/members/{id}/effective-access`: the direct-grant query (`:230`) and the group-grant query (`:300`) of [queries/effective_access.py](../src/dnd_ai/queries/effective_access.py), each feeding both sources and denials | The same rule. A whole-character deny lists as `campaign.view — <character>`; a `canon.edit` deny as `canon.edit — <character>` |
| Resolvers: `resolve_access_context`, `has_capability`, `resource_grant_targets`, `public_profiles`, and the readers in §8.1 | No change. They already read `entity_id`; the deny becomes reachable for them |
| DEF-016 sites (`resolve_character_view_tier` at [api/access.py:482](../src/dnd_ai/api/access.py#L482); inventory at `:515`) | No change (Q3). They read `canon.edit` under `character_id`, so a `canon.edit` deny does not lower a GM's view tier or inventory access. This is now reachable, not hypothetical |
| Audit history | No change; it labels grants by capability, effect and grantee, never by target |
| Portal | No change in A2a-R (Q2). Its `entity` selector deliberately excludes characters ([ResourceTargetSelector.tsx:38](../portal/src/components/ResourceTargetSelector.tsx#L38)); its `character` type maps to `character_id`, whose catalog refuses these codes. So the portal cannot create these denies until it changes |
| Docs | `access_grants.py` module docstring and the guard comment; the catalog comment in `domain/access.py` (for characters, `campaign.view` and `canon.edit` are read under `entity_id`); `test_resource_grant_target_column.py`'s docstring; [PHASE13E_ACCESS_CONTRACT.md](PHASE13E_ACCESS_CONTRACT.md) resource-grant section and §3v ("creatable through `POST …/resource-grants` with `entity_id`, effect `deny`"); this plan's A2a record; a **DEF-018** entry in the defect register |

### 8.6 Tests

**Command level** (`tests/database/test_resource_grant_target_column.py`):

1. `entity_id` naming a `character`, an `npc` and a `player_character` entity:
   - a `campaign.view` deny and a `canon.edit` deny are each accepted;
   - the row has the entity in `entity_id`, `character_id` null, `timeline_id` null and `effect = 'deny'`.
2. The same targets with `allow` are refused with `TargetNotInCampaignWorldError`. The existing `test_entity_id_rejects_a_character_target` stays, and a `canon.edit` variant is added.
3. A `character.view_full` deny under `entity_id` on a character is refused with `ResourceGrantCapabilityNotGrantableError`.
4. Quest, event and knowledge-item entities are still refused under `entity_id`, for a deny too.
5. An archived character, and a character from another world, are refused.
6. An identical second active deny is a unique-index `IntegrityError`. After the first is revoked, the same deny can be created again.

**HTTP** (new `tests/database/test_character_public_profile_grant_denies.py`, on the `Gate`/`Members` fixtures used by `test_character_public_profile_api.py`):

- Every deny in this file is created with `POST /campaigns/{id}/resource-grants` by an access manager, never with `make_resource_grant`, and lifted with `POST …/resource-grants/{id}/revoke`.
- "Nothing written" means no draft or release row change and no audit row.

1. **The grant route itself.**
   - A whole-character deny for a member: 201, with the row and the audit `changed_fields` as above.
   - The same `Idempotency-Key` and body replays the same `resource_grant_id`, with one row and one audit row.
   - The same key with another body is the idempotency 409.
   - Without a key, a duplicate is 409.
   - The `allow` body is 404, with nothing written.
   - A `character.view_full` deny under `entity_id` is 404.
   - A group grantee gets 201.
   - A player's attempt is refused by the route filter.
2. **A whole-character deny on an owner (`o1`, created by `o2`).**
   - `GET` profile and `GET` release are 404.
   - Draft save is 404, and release is 404, with nothing written.
   - A release retried with an `Idempotency-Key` first used before the deny is 404, not a replay.
   - After revocation: `GET` is 200, and that key replays the stored receipt: the 201 and the same ids, versions and flags, no new row (omitted metadata such as `authority_source` is refetched).
3. **The same for a delegated GM**, and for the deny created by the owner against themselves; the owner can still revoke it.
4. **A `canon.edit` deny on an owner.**
   - `GET` is 200 with `can_edit: false` and `can_release: true`.
   - Draft save is 403 `public_profile_edit_denied`, with nothing written. A save retried with a pre-deny key is also 403, not a replay.
   - Release is 201.
   - After revocation, the save key replays.
5. **A `canon.edit` deny on an assistant GM** (no reveal authority): `GET` 404 and save 404.
6. **Campaign scope.** A deny in campaign A leaves campaign B's GM free to read, save and release B's profile of the same character.
7. **The deny is the one other readers honour.** `GET /campaigns/{id}/characters/{character}` is 404 for the denied member and 200 for an undenied GM. This pins that the created key matches an existing reader.
8. **Explanations.**
   - The access overview shows the deny (member and group) with `target_type: "entity"` and the character's name.
   - The effective-access explanation lists it under `denials` with the name.
   - A non-character `entity_id` grant still has `target_display_name: null`.

**Access-group changes take effect on the next request (HTTP).**

9. **A group holding a whole-character deny** (created through the route with `grantee_access_group_id`). A delegated GM outside it reads (200). Then:
   - `POST …/access-groups/{group}/members` adds them, and the next `GET`, save and release are 404; a keyed release retry is 404.
   - `POST …/access-group-memberships/{id}/remove` removes them, and the next `GET` is 200, the keyed retry replays, and a new release is 201.
10. **Deactivating that group** lifts the deny on the next request. Reactivating it does not restore the deny, because its grant stays revoked. A new grant restores it.
11. **A group holding a `canon.edit` deny.** Adding an owner makes the next save 403 while release stays 201; removing them makes the next save 200.

**Concurrency** (`tests/database/test_character_public_profile_concurrency.py`, `LockRace`):

12. `_group_with_a_whole_character_deny` creates its grant with `create_resource_grant`, not `make_resource_grant`. The races themselves are unchanged.
13. **The races A2a criterion 6 had to substitute, now possible:** `create_resource_grant` of a whole-character deny naming the character, against a release and against a draft save, in both orders, for a membership grantee and for a group the actor belongs to. Expected:
    - **deny first:** the command waits, then is refused (404) with nothing written;
    - **command first:** the grant waits, then both commit.

    **Lock trace, with no cycle:**
    - **The grant:** grantee membership U (or group U) → campaign U → account U → character entity U → capability → insert.
    - **The release:** authority rows S → membership S → campaign KS → entity KS → draft U.
    - **The save:** `lock_authoring_scope` (… → campaign KS) → entity S → draft U.
    - **Where they meet:** a membership grantee serializes at the membership; a group grantee serializes at the campaign row.

**Existing suites, passing unchanged except where named:**

- `test_resource_grant_target_column.py` (the docstring and the added cases);
- `test_api_access_grants.py`, `test_resource_grant_concurrency.py`, `test_access_resolution.py`;
- `test_api_characters_inventory.py`;
- the A2a suites. In `test_character_public_profile_api.py`, the `deny()` helper switches to the route for `entity_id` denies and keeps direct SQL only for a stray `character_id` row and an allow row, which the application cannot create.

### 8.7 A2a-R scope and acceptance (for Sonnet)

- **Code.**
  - `create_resource_grant` / `_validate_resource_grant_target` (the `effect` parameter, `_CHARACTER_ENTITY_TYPE_CODES`, the narrowed guard and its comment);
  - the two `access_overview` queries and the two `effective_access` queries (the character name for a character under `entity_id`);
  - the docstrings and comments listed in §8.5.
  - Nothing else in `src/`.
- **Not in A2a-R:**
  - the portal (Q2), DEF-016 (Q3), DEF-017, A2b and later slices;
  - any migration; any change to D8's policy code;
  - push.
- **Tests:** §8.6. The new command and HTTP tests must fail at `0b4704c` where they create a deny through the command. Run them once against the parent and record the result.
- **Docs:** §8.5, plus the DEF-018 register entry. If the owner answers Q3 by registering DEF-016, that entry is recorded too, unfixed.
- **Checks:**
  - the focused suites, then the full `pytest`;
  - `ruff format --check`, `ruff check`, `mypy src`, `git diff --check`.
- **Commit locally and stop for independent review,** naming the parent (`0b4704c`) and the target SHA. Then rerun the A2a review's open items.

### 8.8 Policy points D8 does not settle

- **Q1 — May allow grants of `campaign.view` / `canon.edit` name a character? Owner's answer (2026-11-07): no, deny-only, as recommended.**
  - D8 settles only that an allow cannot confer draft editing. It is silent on whether an allow row may exist.
  - Deny-only keeps the CTI guard's purpose (no inert grants shown as active) and creates no allow path anywhere. It leaves no allow rows for a future reader to promote by mistake (§8.4).
  - The alternative accepts allows that do nothing today.
- **Q2 — Must the portal offer these denies in this correction? Owner's answer (2026-11-07): no; the portal controls wait for A6.** The application API offers them in A2a-R; the portal control follows with A6, which already owns the profile and effective-access UI. If the owner wants the portal control now, A2a-R grows by a portal change: the `entity` selector admits characters for a deny of these two codes, and requests map to `entity_id`.
- **Q3 — Should a `canon.edit` deny on a character also lower a GM's view tier or inventory access (DEF-016), or block other character authoring? Owner's answer (2026-11-07): not in A2a-R. The deny's contract here covers public-profile drafting only; DEF-016 is registered for a separate decision about other character authoring, view tiers and inventory.**
  - D8 limits the deny to the profile draft's edit and read path.
  - The view tier, inventory and identity authoring keep their current behaviour, which A2a-R makes reachable. So register DEF-016 now, and decide it separately.
  - The contract text in §3v and the explanation label should say the deny applies to the public-profile draft, so an owner does not expect more.

---

## 9. A2b design: the legacy copy aid under approved D7 (2026-11-07, revised after review)

**Status:** design reviewed; A2b-1 is implemented locally and was returned CHANGES REQUIRED by the independent review (provenance relabel hole) and is corrected by revision 144 (see the A2b-1 provenance correction); A2b-2 (the copy command and route) is implemented at `46a0154` and independently reviewed: PASS WITH NONBLOCKING FINDINGS (see the A2b review outcome and handoff).

- **Baseline.** `523ae5cbf947af230e1d7a5409912c1039e43a69` (the A2a handoff, directly on A2a-R `f66240a`). Every claim was checked by reading source at that commit; nothing was run.
- **Supersedes.** This section replaces the D7-dependent parts of §5.6, §5.8 (copy row) and §5.10 ("Design"). Where they differ, this section wins.
- **Revision after an independent CHANGES REQUIRED review (2026-11-07), then reviewed again.** Neither review's text is in the repository. This revision follows the owner's summary of the first; the second design review, after which A2b-1 was approved for implementation, is recorded here as conversation-supplied evidence only (no review text or verdict wording was available to this session).
  - **What was wrong.** The first version lifted a field's restriction once any release came at or after the copy. A permitted GM could then append, or restore, unreleased source text after that release, and it would be shown at once to readers without source permission.
  - **What replaces it.** Per-field release coverage, tied to the current text through a restriction watermark that every content change advances (§9.2–§9.3).
  - **Also recorded.** D7-a to D7-f are now owner-approved (§9.10).

### 9.1 The approved rule, the source read, and an assumption

D7 (approved; recorded under "Decisions still needed"):

1. Copying a legacy field requires current permission to read its source.
2. Before release, copied fields retain that source-read restriction.
3. A releaser must currently be allowed to read every field included in the release snapshot.
4. Deliberate release makes the snapshot eligible for the later audience mechanism under its release policy.

The owner's answers to D7-a to D7-f (§9.10) are applied throughout.

**The source-read rule** ("may read the source") is one function in `domain/public_profiles.py`. It is keyed by the character's kind, never by the caller's choice, and equals the gate of that kind's legacy authoring read today (D7-e):

| Character kind (`core.entity_types.code`) | Source read requires | Today's authoring read |
|---|---|---|
| `player_character` | role `canon.edit` in the route campaign | `GET …/authoring/player-characters/{id}` ([player_character_authoring.py:191](../src/dnd_ai/api/player_character_authoring.py#L191)): `require_campaign_capability("canon.edit")` |
| `npc` | role `canon.edit` **and** world `world.canon.read_private` on the campaign's world (held by `world_owner`, `world_editor`, `world_reviewer`) | `GET …/authoring/npcs/{id}` ([npc_authoring.py:192](../src/dnd_ai/api/npc_authoring.py#L192)): `_PrivateRead` |
| `character` or any other | nobody | no authoring read exists, so nothing can be copied. The copy route is 404, as an authoring route of the wrong kind is |

- `has_capability("canon.edit")` with no target is role-only ([access.py:334](../src/dnd_ai/domain/access.py#L334)), so per-character denies do not enter the rule. That matches the authoring reads (D7-e). A whole-character deny still removes the profile entirely (D8).
- **Only the current authoring text is a source.** Revision history ([review_queue.py:120](../src/dnd_ai/api/review_queue.py#L120)) is never read by the copy, and no profile response links to it.
- **Only two fields are sources.** `appearance` → `public_appearance` and `background` → `public_background`. `notes` never is.

**Assumption: a character's kind is stable on every application path.** The rule is evaluated with the character's *current* kind at each check, so a kind change would change who may read existing copies. Checked at `523ae5c`:

- No `src/` code sets `core.entities.entity_type_id` or deletes a `character.npcs` or `character.player_characters` row. The only `UPDATE core.entities` statements set name and summary ([_content.py:325](../src/dnd_ai/commands/_content.py#L325)) or canon and lifecycle status ([entity_lifecycle.py:434](../src/dnd_ai/commands/entity_lifecycle.py#L434), [:683](../src/dnd_ai/commands/entity_lifecycle.py#L683), [:707](../src/dnd_ai/commands/entity_lifecycle.py#L707)).
- ADR 0021 §1 item 2: "No code converts one marker into the other."
- **The database does not guarantee it.** Migration 048's `core.enforce_entity_type_change()` refuses a type change only while a subtype row of the old type exists. Direct SQL that first deletes the `character.npcs` row could still change the type.

So this is an **application-path assumption**, not a database invariant. A2b relies on it, as A1's unlocked campaign-of-membership read relies on membership scope. If a later slice (for example P03-C's marker work) makes kind mutable, the copy must first snapshot the source rule (the kind) into the field. Record the assumption in the A2b-1 domain docstring and in `PHASE13E_ACCESS_CONTRACT`.

### 9.2 Field state and the invariants

Each draft field holds:

- **text;**
- **origin** (`authored`, `legacy_appearance` or `legacy_background`, migration 142);
- **`origin_entity_row_version`:** the source character's `core.entities.row_version` at the copy (142);
- **new: the restriction watermark** `public_<field>_restricted_row_version BIGINT NULL`. It is the draft `row_version` at which this field's current content was last written while it had a legacy origin.

**Coverage, per field.** A release *covers* a field when its `from_draft_row_version >= ` that field's watermark.

**Restricted.** A draft field is restricted when all of these hold:

- its text is not NULL;
- its origin is legacy;
- no release of the profile covers it.

**Withheld.** A restricted field is withheld from a caller who fails the source-read rule for the character's kind. Restriction and withholding are derived on every read and command. Nothing stores them, and no request sets them.

**Invariants:**

- **I1, provenance travels with content.** A legacy origin, its `origin_entity_row_version` and its watermark are present together, or absent together. Only the copy sets them; only clearing removes them (the database refuses removal while text remains, revision 144).
- **I2, every content change advances the watermark.** Any write that changes a legacy-origin field's text, origin or `origin_entity_row_version` sets that field's watermark to the new `row_version`. A copy sets it even when the text happens to be identical (a copy always starts new restricted content). The watermark never decreases and never exceeds `row_version`.
- **I3, other fields leave it alone.** A write that does not change a field's content does not move that field's watermark. Editing field A therefore never re-restricts an unchanged, released field B.
- **I4, coverage means the released text is the current text.** A release from draft version *r* snapshots the draft exactly at *r* (§5.5). If *r* ≥ the watermark *w* of field B, B's content did not change between *w* and *r* (by I2, a change would have moved the watermark past *r*). So the released B is the current B. Conversely, any later change to B moves the watermark past every existing release, and B is restricted again until a release covers it (D7-c).
- **I5, only a releaser who could read the field covers it.** A release that would include a field withheld from its releaser is refused (§9.4). So every covering release written after A2b-1 was made by someone who could read that text (D7 item 3). The migration preflight (§9.3) establishes that no earlier release carries a legacy origin.
- **I6, clearing ends the lineage.** Clearing sets the text NULL, the origin `authored`, and both versions NULL. Copying again starts a new lineage at a new watermark.
- **I7, nothing is relabelled by request.** The save and copy bodies have no origin or watermark field. The database enforces I1 and I2 (§9.3), so a command that forgets to advance a watermark fails rather than silently lifting a restriction.

**Why releases need no new column.** Coverage is fully determined by the draft's per-field watermark and the release's existing `from_draft_row_version`, because releases are immutable exact snapshots (I4). Releases keep their per-field origin and `origin_entity_row_version` as provenance. A test pins I4 against the release snapshot (§9.8).

**Over-restriction is accepted.** Editing a released field back to exactly its released text still advances the watermark, and it stays withheld until released again. That is safe, and simpler than comparing text.

### 9.3 Migration `143_public_profile_restriction_watermarks`

The next revision after 142. It is additive.

**Preflight.** Before any change, the upgrade counts draft and release rows whose either field has a legacy origin.

- If any exist, it raises with a message and changes nothing.
- No application path at `523ae5c` writes a legacy origin: no `src/` file names `legacy_appearance` or `legacy_background`, and A2a's commands write only `authored`. Only `test_character_public_profile_schema.py` inserts legacy origins, on disposable test databases.
- So on every application-written database the count is zero. A non-zero count means hand-written rows whose disclosure history is unknown, and the operator must decide. The migration does not guess a watermark or a coverage.

**Columns.** On `campaign.character_public_profiles` only:

- `public_appearance_restricted_row_version BIGINT NULL`;
- `public_background_restricted_row_version BIGINT NULL`.

Both are `STRUCTURAL` in `COLUMN_CLASSES`, with column comments.

**CHECKs (table-local):** each watermark is

- NULL exactly when that field's `origin_entity_row_version` is NULL (through 142's origin trigger, exactly when the origin is not legacy);
- `>= 1`;
- `<= row_version`.

**Trigger `campaign.enforce_public_profile_restriction_watermarks()`**, `BEFORE INSERT OR UPDATE` on drafts. It enforces I2 and does not set anything. For each field:

- **INSERT.** A legacy origin needs `watermark = NEW.row_version`.
- **UPDATE.** If `NEW` has a legacy origin and the text, origin or `origin_entity_row_version` is distinct from `OLD`, the watermark must equal `OLD.row_version + 1`. That is the value `core.bump_row_version()` gives `NEW.row_version`, so the rule does not depend on trigger firing order.
- **UPDATE, unchanged content.** If old and new are both legacy-origin and the content is unchanged, the watermark must not decrease.

A violation raises `integrity_constraint_violation`.

**Existing rows.**

- **Authored drafts (every A2a draft):** both watermarks NULL, which satisfies the CHECKs and the trigger. No row is rewritten, no `row_version` changes, and no audit row is written.
- **Releases:** no change of any kind. Every existing release is authored-only (preflight), so it covers nothing and loses nothing.

**Downgrade.** Drops the trigger, the function and the two columns. It is lossless for authored-only data. After A2b-2 has copied text, a downgrade drops the watermarks, and the down-level code would show copied text to every D8 reader. So a downgrade with legacy-origin rows present raises, the mirror of the preflight.

### 9.4 What each operation does

| Operation | Rule (on top of D8, §5.7a) | Result |
|---|---|---|
| **GET profile** | For each field withheld from the caller: `"<field>": null`, `"<field>_withheld": true`, and the origin code and `origin_entity_row_version` (D7-f). Otherwise the text and `"<field>_withheld": false` | Releases (`latest_release`, the list, `GET …/releases/{n}`) are never withheld (D7 item 4). `can_release` is false while any field is withheld from the caller. `legacy_copy` says, for each copyable field, whether the source text is non-empty. It is present only for a caller who passes both the edit rule and the source read; otherwise it is `null` |
| **Save** (`POST …/draft`) | Under lock, in order: (1) the token: stale → 409 `stale_write`; (2) **text sent for any field withheld from the caller → 403 `public_profile_field_withheld` for the whole request**, nothing written, other fields included, whatever the text; (3) the no-op comparison; (4) the write | A field left out: untouched. Explicit `null`: clears it (I6), allowed even when withheld (D7-a). Text for a field not withheld: written. If that field has a legacy origin, the origin is kept and its watermark advances (I2). A field not named keeps its watermark (I3) |
| **Copy** (`POST …/draft/copy-legacy`, body `{expected_row_version, field}`) | The D8 edit rule and the source read, both in the route pre-check (before the idempotency lookup) and again under lock (§9.6). Empty source text: 409 `public_profile_legacy_text_missing` | Replaces the whole target field with the source text. Sets the origin, `origin_entity_row_version` and watermark = the new `row_version`, and bumps `row_version`. 201 if it created the draft (`expected_row_version: null`), else 200. The response and stored receipt hold ids, `row_version`, `created` and `changed`, never text |
| **Release** | After the natural-retry and stale steps (§5.5 steps 3–4), and only when a new snapshot would be written: if any field at that draft version is withheld from the releaser, **403 `public_profile_field_withheld`**, nothing written (D7 item 3) | The new release covers every field whose watermark ≤ its version, so it lifts their restriction (D7-c). An owner or delegated GM without `world.canon.read_private` cannot release an NPC draft holding uncovered copied content |
| **Audit** | A copy writes one `audit.change_log` row (`copy_legacy_text_to_public_profile_draft`): target field, origin code, `origin_entity_row_version`, new `row_version`. A save's row is unchanged: field names and the new `row_version` | Never text; no row for a refusal, no-op or replay |

**Why the token comes first in a save.** Whether a field is withheld depends on the locked draft, which may differ from what a stale caller read. A stale token is answered 409 first, so the caller reloads and sees the current state.

**Why withholding comes before the no-op comparison.** A caller the field is withheld from would otherwise learn whether a guess matched, from `changed: false`.

**Error codes.**

- The copy refusal for a missing world capability is the existing 403 `world_authority_required`, the same answer the NPC authoring read gives.
- `public_profile_field_withheld` is new: 403, safe message "This draft holds copied text you cannot read."
- Neither code names the hidden content. A caller only reaches either after reading the profile, where `withheld: true` has already been disclosed (D7-f).

**Player characters.** Every D8 reader holds role `canon.edit` today (§5.1), so a player character's copied field is never withheld from anyone who can read the profile. The rule is still applied generally.

### 9.5 Edits, provenance and attempts to bypass the restriction

- **Editing copied text keeps it restricted.**
  - Every edit of a legacy-origin field keeps the origin and advances its watermark, however small the edit (I2).
  - An edit after a release makes the field restricted again until a release covers the new text.
  - Cutting a copy down to an excerpt, releasing the excerpt, then appending source text or restoring the full copy therefore never shows the added text to a restricted reader before it is released.
- **Editing a different field never re-restricts a released one** (I3).
- **No request can relabel a field** (I7). The database rejects a content change that does not advance the watermark.
- **Read and resave.**
  - A caller the field is withheld from cannot read it, cannot send text into it (403 for the whole request), and cannot probe it (the 403 comes before the comparison).
  - A caller who can read it and resaves it with changes advances the watermark; an unchanged resave is a no-op.
- **Clearing** removes the text and resets provenance (I6). A restricted caller may clear (D7-a).
- **Copying again** always starts new restricted content at a new watermark, even from the same source version, even if an earlier copy was released.
- **Manual authoring is accepted (D7-b).** A caller who may read the source and types it in by hand, into an empty field or after clearing a copied one, writes authored text. That is the same as pasting from the NPC authoring view today. The rule protects server-copied content and every edit of it, not what an entitled reader knows.

### 9.6 Source-version consistency and locks

**Copy.** `copy_legacy_text_to_public_profile_draft` uses the save's lock order, with the kind's world capability:

1. Read the character's kind, unlocked (§9.1 assumption).
2. `lock_authoring_scope(world_capability=WORLD_CANON_READ_PRIVATE` for an `npc`, `None` for a `player_character`): world `FOR SHARE` → role rows and membership (S) → account (S) → campaign (KEY SHARE) → role `canon.edit` and the world capability re-checked from committed state.
3. Re-resolve the `AccessContext` for the D8 edit rule.
4. Lock the character's `core.entities` row `FOR SHARE`. Read `row_version` and the canon and lifecycle status in separate statements, as A2a's `_character_row` does.
5. Read `appearance` or `background` from `character.character_descriptions` in a separate statement under that lock.
6. Lock the draft `FOR UPDATE` and compare the token, or insert (the unique-index race, as in a save).
7. Write the text, origin and `origin_entity_row_version`, and set the watermark to `expected_row_version + 1`, or to 1 for an insert.

**Why the text and the version match.** The only writer of `character_descriptions` is `update_character_identity` (and creation). It holds the entity `FOR UPDATE` and bumps `core.entities.row_version` through `touch_entity` in the same transaction ([npcs.py:225](../src/dnd_ai/commands/npcs.py#L225), [:303](../src/dnd_ai/commands/npcs.py#L303)). Under the copy's `FOR SHARE`, no edit can commit between steps 4 and 5. If one was in flight, the copy waited, and it reads that edit's committed text with its new version, never one without the other. No client-side source token is needed: the copier sees the copied text in the draft, and the release is the review step.

**World capability.** Ending or changing a world role (`world_memberships.py:70`), and world ownership recovery or transfer, take the world row `FOR UPDATE`. The world row is the head of the global lock order ([worlds.py](../src/dnd_ai/commands/worlds.py) module docstring). The copy's world `FOR SHARE` is held before it judges `world.canon.read_private`, so that judgement stands until commit. World roles have no time-based expiry, so no fresh-instant re-check is needed for them.

**Save.**

- The save already holds world `FOR SHARE` through `lock_authoring_scope(world_capability=None)`.
- It resolves `resolve_world_authority` after those locks, only for an `npc`, to decide which fields are withheld.
- The set of releases is fixed while the draft is held `FOR UPDATE`, because every release takes that lock. No new lock is needed.

**Release (changed in A2b-1).** The release takes the **world row `FOR SHARE` first**, before its authority rows:

> world (S) → authority rows (S) → caller's membership (S) → campaign (KEY SHARE) → character's entity (KEY SHARE) → draft (U) → `clock_timestamp()` and the same-source re-check → `AccessContext` re-resolve (whole-character deny) → world authority resolved → natural retry → stale → character → **withheld check** → write.

- **Taken on every release.** The world lock is taken for every release, so the order is static.
- **No new deadlock.** The world row comes first in every command that takes it. Every world `FOR UPDATE` taker starts with it and takes none of the release's later rows before it. Every campaign command that takes the world takes it `FOR SHARE` (compatible). So the A1 §3 table and §5.8 gain an edge only at their head, and none is reversed.
- **Kept from A2a.** The fresh-instant re-check still follows the last wait (the draft).
- **Not locked.** Account deactivation is not locked by the release, as A1 accepted (§1 table).

**Reads** judge the source read at the moment of the read, with no locks, as A2a's reads do.

### 9.7 Retries and permission changes

Retries of an existing release survive loss of source permission, but the current D8 access and release-authority checks still apply (D7-d). The same holds for replays of a save.

| Situation | Outcome |
|---|---|
| A copy retried with the same key after the copier lost `world.canon.read_private` | 403 `world_authority_required` from the pre-check, before the idempotency lookup; no replay. The source read *is* the copy's authority (D7 item 1; DATABASE_CONVENTIONS §26.4) |
| A copy retried with the same key while still permitted | The stored receipt; nothing written |
| A copy whose world role is ended while it waits for the world lock | The end commits first; the copy's re-check under lock refuses it with 403; nothing written |
| A save with key K that wrote text into copied field B, retried with K after the saver lost the source read | The stored receipt (ids, `row_version`, flags; no text); nothing written. The D8 edit pre-check still runs first: under a whole-character deny it is 404; under a `canon.edit` deny it is 403 or 404 |
| A save refused 403 `public_profile_field_withheld`, retried with the same key after the role is restored | Runs afresh (a refusal stores nothing); stale 409 if the draft moved |
| A releaser loses `world.canon.read_private`, then retries a release of a version **already released**, with or without a key | The stored receipt, or 200 `created: false`; no snapshot written; no text (D7-d). The pre-check still refuses a caller who has lost reveal authority (403 `character_reveal_required`), or who is under a whole-character deny (404) |
| The same releaser releases a **new** version holding uncovered copied content | 403 `public_profile_field_withheld`; nothing written |
| A world role is ended while a release waits for the world lock | The end commits first; the release then finds the field withheld: 403, nothing written |
| A world role is ended while a release holds the world lock | The end waits; the release commits (201) |
| The world role is restored | The field is visible again on the next read. Nothing is stored per reader |
| The source is edited after the copy | The draft keeps the copied text and its source version. A new copy takes the new text and starts a new watermark |
| A whole-character deny | Unchanged: 404 for read, save, copy and release (D8) |

### 9.8 Tests (A2b)

Every scenario uses the HTTP routes with namespaced fixtures. World roles are granted and ended with the world-membership commands, and D8 denies are created with A2a-R's route. "Restricted reader" means a D8 reader without `world.canon.read_private` (the campaign-only owner, an assistant GM with no world role, a `world_reader` GM). "Permitted GM" means one with `world_editor`.

**PostgreSQL: migration and schema.**

- Up, down and up again. `alembic check` is clean.
- **Preflight.** A database holding a hand-inserted legacy-origin draft, or a legacy-origin release, refuses the upgrade and is left unchanged. The downgrade refuses with legacy-origin rows present.
- **Existing rows.** An authored A2a draft and its releases keep `row_version`, text and origins, and gain NULL watermarks, with no audit row.
- **CHECKs.** They refuse:
  - a watermark without a legacy origin;
  - a legacy origin without a watermark;
  - a watermark above `row_version`;
  - a watermark below 1.
- **Trigger.** It refuses:
  - an UPDATE that changes a legacy-origin field's text, origin or source version without setting its watermark to `OLD.row_version + 1`;
  - lowering a watermark;
  - a legacy-origin INSERT whose watermark is not `row_version`.

  It accepts an UPDATE of the other field that leaves this field's watermark unchanged (I3).
- 142's origin trigger is unchanged.

**The excerpt regressions (the review's case).** For an NPC background copy (markers: F for the full source, E for an excerpt of it, X for source text not in E):

1. A permitted GM copies (version *c*). A restricted reader sees B withheld.
2. The permitted GM edits B down to E (*c*+1). Still withheld.
3. A permitted owner releases *c*+1. The restricted reader now sees E in the draft and in the release.
4. **Append:** the permitted GM appends X to B. B is withheld from the restricted reader again, and the release still shows only E. A release by a restricted releaser is refused 403. After a permitted release, B (E plus X) is visible.
5. **Restore:** from step 3 again, the permitted GM replaces B with F. B is withheld until a permitted release of that version, then visible.
6. **Restore exactly the released text:** the permitted GM edits B away from E and back to E. B is withheld (accepted over-restriction, §9.2) until released again.

No body seen by the restricted reader contains X or F before the covering release.

**Unchanged-field visibility.**

- After B is released (step 3), the permitted GM and then a restricted GM each edit appearance A. B stays visible to the restricted reader, and B's watermark is unchanged in the row.
- Then B is edited: only B becomes withheld. A stays visible.

**Mixed-field atomic refusal.** A restricted GM sends one save that changes A and puts text into withheld B.

- The result is 403 `public_profile_field_withheld`.
- The draft is unchanged: `row_version`, A, B, origins and watermarks. No audit row.
- The same is true when the B text equals the stored text (no oracle), and when it differs.
- The same GM saving A alone, with B left out, gets 200. B is unchanged.

**Clear.**

- A restricted GM clears withheld B (D7-a). Result: 200, B NULL, origin `authored`, both versions NULL; A untouched.
- Then the same GM writes new text into B: 200, authored and visible to all.
- A permitted GM clears and types the source by hand: authored, and visible (D7-b, documented behaviour).

**Recopy.**

- Copying again after a covering release: withheld again, with a new watermark, even from the same source version.
- Copying again after a source edit: the new `origin_entity_row_version`, withheld.
- Copying over authored A: A becomes legacy-origin and withheld.

**Stale writes.**

- **Stale token first.** A restricted GM's save with a stale token and text into B gets 409 `stale_write` (not 403); nothing written.
- **Copy against save.** A copy and a save with the same token: the second gets 409.
- **Release after a move.** A release named at a version whose B was later edited gets 409 `stale_write`, or, if that version was already released, 200 `created: false`. Nothing new is covered.
- **Clear against edit.** A restricted GM's clear races a permitted GM's edit: the second gets 409.

**Keyed retries** (every row of §9.7). In particular:

- **Copy replay after losing the world role:** 403, not a replay.
- **Save replay after losing it:** the receipt, writing nothing and holding no text.
- **Keyed release replay and natural retry after losing it:** the receipt, and 200. Both are refused after a whole-character deny (404) and after losing reveal authority (403).
- **Retry of a refused 403 save** after the role is restored: it executes.

**Readers with different source permissions.** On one NPC draft with authored A (marker A) and an uncovered copied B (marker B):

- `world_editor` GM: sees both.
- Owner with no world role, and assistant GM with no world role: see A; B is withheld, with its origin and `origin_entity_row_version` shown; `can_release: false`.
- `world_reader` GM: B withheld.
- Player, observer, campaign B's GM: 404.
- A reveal holder with a `canon.edit` deny on the character and `world_editor`: reads B, cannot edit.
- A player-character copy: shown to every D8 reader.

**Copy rules.**

- **Allowed:**
  - an owner, GM or assistant GM with `world.canon.read_private`, for an NPC;
  - any `canon.edit` holder, for a player character.
- **Refused:**
  - 403 `world_authority_required` without the world capability (NPC);
  - 403 `public_profile_edit_denied` or 404 under a `canon.edit` deny;
  - 404 under a whole-character deny;
  - 409 `public_profile_legacy_text_missing` for empty source text;
  - 404 for a plain `character` kind, and for a character outside the world;
  - 409 `public_profile_character_not_active` when archived;
  - 409 `stale_write`;
  - 422 for `field: "notes"` or any other value.
- **Same key, same body, different character:** the non-disclosing 409.

**Response-body disclosure** (extends A2a criterion 8). The NPC's `background`, `appearance` and `notes` carry distinct markers, and the first two are copied. For every restricted reader, and for players, observers and campaign B's GM, no body contains a marker until a covering release. That covers:

- the profile GET, the release list and `GET …/releases/{n}`;
- the save, copy and release responses and their stored receipts;
- every 403, 404 and 409 body;
- the A2a marker-sweep surfaces;
- the audit history.

`notes` appears in no profile response for anyone. The copy's audit row holds no marker.

**Concurrency** (LockRace, both orders, no deadlock):

- **A copy against `update_npc` on the same character, both winners.**
  - *Update first:* the copy waits on the entity, then records the new text with the new version, never a mix.
  - *Copy first:* the update waits for the copy's `FOR SHARE` on the entity. The copy has recorded the old text with the old version, the update then commits, and a later copy reads the new pair.
- **Same draft.** A copy against a save, and a copy against a release.
- **Ending the copier's world role against a copy, both winners.**
  - *End first:* the copy's re-check under lock refuses it with 403 `world_authority_required`; nothing is written.
  - *Copy first:* the end waits on the world row the copy holds `FOR SHARE`; the copy commits, then the end.
- **Ending the releaser's world role against a release of uncovered copied content, both winners** (§9.7 rows).
  - *End first:* the release finds the field withheld: 403 `public_profile_field_withheld`, nothing written.
  - *Release first:* the end waits; the release commits (201).
- **Ending the saver's world role against a save that writes text into the copied field, both winners.**
  - *End first:* the save finds the field withheld: 403, nothing written.
  - *Save first:* the end waits for the save's world lock; the save commits.
- **A permitted GM's edit of released B against a restricted releaser's release of the earlier version.** Either the release is stale (409) or it covers only the earlier text, and B is withheld afterwards.
- **Rerun unchanged:** A1's, P0's, P1's and A2a's race suites, with the release's world lock.

**Structural tests.**

- `test_character_public_profile_structure.py` admits the copy module as a reader of `character_descriptions`.
- `test_world_gate_registry.py` lists the copy's kind-dependent `lock_authoring_scope` call, as it does the identity helper.
- A parity test pins the source rule's world capability for each kind against the NPC and player-character authoring GET dependencies.
- The route manifest gains the copy route.
- `COLUMN_CLASSES` covers the two new columns.
- A unit test of the restriction predicate covers I3 and I4 over synthetic histories.

### 9.9 Slices and acceptance (for Sonnet)

**A2b-1: the restriction, before any copy exists.**

- **Code:**
  - migration 143 (§9.3);
  - the source-read rule and the restriction predicate in `domain/public_profiles.py`, with the kind assumption in the docstring;
  - withholding in `read_character_public_profile`;
  - the save rule and its watermark advance;
  - the release's world lock and withheld check;
  - `public_profile_field_withheld`.
- **Tests.** Legacy-origin drafts are seeded through a test helper that writes a row satisfying the CHECKs and trigger, because no copy path exists yet. This is the only raw-row seeding, and A2b-2 replaces it with the route. Covers §9.8 except the copy-specific cases, including the excerpt regressions (seeding the copy), unchanged-field visibility, mixed refusal, clear, stale writes, save and release keyed retries, and the release races.
- **Why first:** no commit ever has a copy path without its restriction.

**A2b-2: the copy command and route.**

- **Code:** `copy_legacy_text_to_public_profile_draft`, `POST …/draft/copy-legacy`, `legacy_copy` in the GET, and the audit row.
- **Tests:** the copy rules, recopy, copy keyed retries, the excerpt regressions rerun through the real copy, the disclosure sweep, and the copy races.

**Both slices:**

- The new tests fail at the parent.
- Run `ruff format --check`, `ruff check` and `mypy src`; the focused tests, then the full `pytest`; migration up/down; `git diff --check`; CI on the final head.
- Docs in the same change:
  - `PHASE13E_ACCESS_CONTRACT`: withholding, watermarks and coverage, the copy route, the new error code, the kind assumption;
  - `DATABASE_MODEL`: the two columns and the trigger;
  - `DOMAIN_MODEL`: restriction watermark, coverage, withheld field;
  - the `ENTITY_LIFECYCLE` command list: the copy;
  - this plan's records.
- One local commit each. Stop for independent review naming the parent and target SHAs. No push.

**Out of scope:** the portal (A6); revelations and audience reads (A3/A4); DEF-016 and DEF-017; a "source changed since copy" indicator; D5 and D6 columns; making kind mutable.

### 9.10 D7-a to D7-f: owner-approved (recorded 2026-11-07, from conversation)

The owner approved these in conversation. The approval text is not otherwise in the repository.

- **D7-a.** Withheld fields may be cleared, but restricted callers cannot replace their text. Applied in §9.4 (save) and §9.5.
- **D7-b.** Manual authoring by someone allowed to read the source is accepted. Such text is authored, and nothing in A2b tries to detect it (§9.5).
- **D7-c.** A release lifts restrictions only on the text actually released. Applied as per-field coverage of the restriction watermark (§9.2, I2–I4). A later content change restricts the field again until a release covers it.
- **D7-d.** Retries of an existing release survive loss of source permission, while the current D8 access and release-authority checks still apply. A natural retry and a keyed replay return the existing release without a source check. The release pre-check (reveal authority, whole-character deny) is unchanged. The withheld check runs only when a new snapshot would be written (§9.4, §9.7). Save replays follow the same rule. A copy replay does not, because the source read is the copy's own authority (D7 item 1).
- **D7-e.** Source-read rules match the existing authoring reads: role `canon.edit`, plus `world.canon.read_private` for an NPC, with per-character denies not entering the rule (§9.1).
- **D7-f.** Withheld flags and field-origin metadata may be disclosed: `withheld`, the origin code and `origin_entity_row_version`, never text (§9.4).

---

## 10. A3 design: audience revelations (2026-11-07)

**Status:** design only, **finalized 2026-11-07** with the owner's approval of D4-C, D5-c, D9, D10, D11 and D12 (§10.15). It was checked by reading source at `a9ec4c4b7a14d7c5236525b2121da8ba6f01475d` (the A2b review handoff). Nothing was run for it, and nothing in it is implemented.

**What it replaces.** §2's revelation outline and §3's consumer list are kept as context. Where they differ, this section governs. The main changes from §2 and §3 are:

- one more lock, taken explicitly in `end_campaign_membership`;
- a release is required before a revelation (D9-d);
- one live revelation per character, kind and target (D9-e);
- A3 is split into an inert storage slice (A3a) and a discovery slice (A3b).

**Audience:** Sonnet and the reviewer for A3a and A3b; the owner for the record of the approved decisions (§10.15).

### 10.1 The rules A3 applies

- **OD-17.** A revelation names one member, one access group, or the whole campaign.
  - A campaign-wide revelation states whether it covers **current members only** or **current and future members**. There is no default.
  - An audience receives only deliberately released versions. A revelation follows later releases.
  - Revoking a revelation is independent of every other capability source (ADR 0021 §2.9).
- **ADR 0021 §6.** Publication is not revelation, and one discovery and profile predicate serves every consumer.
- **ADR 0021 §2.9.** A whole-character `campaign.view` deny suppresses discovery and profiles from every source. An operation-specific deny blocks only its operation.
- **D2 and D8.** Creating and revoking a revelation needs `character.reveal` authority (owner, or a live delegation), re-checked under lock at a fresh instant.
  - A whole-character deny on the actor refuses it with 404.
  - A `canon.edit` deny on the character does not refuse it, because revealing is not editing.
- **What a revelation confers.** `character.discover` and the new `character.view_public_profile`, for that character only. Nothing else: never `view_summary`, `view_full`, `view_inventory`, `view_knowledge`, `view_private`, control or play.

### 10.2 Storage: migration `145_character_revelations`

The migration is additive, with no backfill. After it runs, no character has a revelation and every response is unchanged.

**`security.revelation_audience_kinds`** is a lookup table with the 142 origin lookup's shape: id, `code`, `display_name`, `sort_order`, timestamps, and code format and length CHECKs. It is seeded with `member`, `access_group`, `campaign_current` and `campaign_current_and_future`. It is not an ENUM (DATABASE_CONVENTIONS §11), and there is no default.

**`security.character_revelations`** is closed at most once and never edited otherwise. Columns:

- `character_revelation_id` (PK);
- `campaign_id` → `campaign.campaigns`, `ON DELETE RESTRICT`;
- `character_id` → `character.characters`, `ON DELETE RESTRICT`;
- `revelation_audience_kind_id` → the lookup table;
- `target_campaign_membership_id` and `target_access_group_id`, both nullable;
- `created_by_membership_id` (NOT NULL);
- `authority_source`, either `owner` or `delegation`, and `character_reveal_delegation_id`, which is nullable. Together these are provenance, the same pair a release records;
- `reason` (TEXT NOT NULL, 1–1000 characters, as for a delegation);
- `created_at`;
- `ended_at`, `ended_by_membership_id` (NULL for a closure the system makes), `end_reason`, `revocation_reason`;
- `updated_at`.

`end_reason` is one of:

- `revoked`;
- `target_membership_ended`;
- `access_group_deactivated`.

**Constraints on `character_revelations`:**

- **Target shape.** A trigger enforces it by kind code:
  - `member` has exactly the membership target;
  - `access_group` has exactly the group target;
  - both campaign kinds have neither.

  This is a local integrity rule under §20.4, because a CHECK cannot read the lookup table.
- **Closure consistency.** These CHECKs follow migration 141's delegation table:
  - `ended_at` and `end_reason` are set together;
  - `ended_by_membership_id` and `revocation_reason` are set only for `revoked`;
  - `ended_at >= created_at`.
- **Immutability.** A trigger refuses any change to a structural column, and any change to a row that is already closed. A row can therefore be closed once and never reopened. Application roles have UPDATE, DELETE and TRUNCATE revoked except UPDATE of the closure columns, and `app_read_only` gets nothing (as 141).
- **One live row per audience** (D9-e): `CREATE UNIQUE INDEX ux_character_revelations_live ON security.character_revelations (campaign_id, character_id, revelation_audience_kind_id, target_campaign_membership_id, target_access_group_id) NULLS NOT DISTINCT WHERE ended_at IS NULL`. This index is PostgreSQL 15 or later, which PostgreSQL 18 satisfies.

**Same-campaign scope triggers**, following the scope triggers in migrations 141 and 142:

- the character belongs to the campaign's world;
- the target membership, the target group, the creator and the revoker belong to `campaign_id`;
- a delegation named as provenance belongs to the campaign, and its grantee is the creator;
- **a release exists** for (`campaign_id`, `character_id`) when the row is inserted (D9-d). Releases are immutable and cannot be deleted (`ON DELETE RESTRICT`, revoked DELETE), so the condition can never later become false. A release in campaign B does not satisfy it for campaign A.

**`security.character_revelation_members`** is the `campaign_current` snapshot. Columns:

- `character_revelation_member_id` (PK);
- `character_revelation_id`;
- `campaign_id`, copied from the revelation for the scope trigger;
- `campaign_membership_id`;
- `added_at`;
- `removed_at`, `removal_reason` (`membership_ended`).

**Snapshot rules:**

- `UNIQUE (character_revelation_id, campaign_membership_id)`.
- A trigger refuses a row unless:
  - its revelation's kind is `campaign_current`;
  - the membership belongs to the revelation's campaign;
  - the revelation's `created_at = now()`, so only the transaction that created the revelation can insert snapshot rows. No later transaction can add members.
- The only permitted update is setting `removed_at` and `removal_reason` once. DELETE and TRUNCATE are revoked.

**Release summary (D5-c, approved).** The migration also adds a nullable, authored-only `public_summary` to the draft and the release. Authoring, snapshotting, older releases and the search projection are in §10.12.

**Vocabulary.** `character.view_public_profile` is inserted into `security.capabilities`, following migration 139's frozen-seed pattern. A trigger refuses any `security.role_capabilities` row naming it, and any `allow` resource grant naming it, by the "two sources only" rule A1 applied to `character.reveal`.

- Its only allow source is a revelation. When A4 reads a profile, it also admits the summary and higher tiers (D11, §10.14).
- A `deny` resource grant is accepted by the database and honoured. Creating one through the application is deferred (D12).

**Registries:**

- `reason` and `revocation_reason` are classified as the delegation table's are.
- `character_id` gets a `BLOCKING` entity-reference entry.
- The two tables are listed in persistence metadata, `test_role_grants`, and the module-access structural test.

**Downgrade.** It drops the three tables, the functions and the capability row, which loses data by design, as in 141 and 142. It first refuses, atomically, while any `role_capabilities` row or resource grant names `character.view_public_profile`.

### 10.3 Commands, routes and audit

All routes are under `/campaigns/{campaign_id}/characters/{character_id}/revelations`.

| Route | Command | Pre-check (dependency, before body and idempotency lookup) | Body | Success |
|---|---|---|---|---|
| `GET` | `list_character_revelations` (query) | D8 read rule (`canon.edit` on the character, or reveal authority); whole-character deny → 404 | none | Live and ended revelations (see the list below) |
| `POST` | `create_character_revelation` | Reveal authority and whole-character deny, as the release pre-check (`require_may_release`) | `{audience_kind, target_campaign_membership_id?, target_access_group_id?, reason}`; extra fields refused | 201 with a minimal receipt `{character_revelation_id, created: true}`; a natural retry returns 200 `created: false` with the existing id |
| `POST …/{character_revelation_id}/revoke` | `revoke_character_revelation` | As for create | `{reason}` | 200 `{character_revelation_id, revoked}`; an already-ended revelation is `revoked: false` with no audit row |

**Each list entry carries:**

- kind;
- target id and display name;
- creator, `authority_source` and times;
- `end_reason`;
- for `campaign_current`, the `audience_size` and the snapshot's current and removed members.

**Who sees what in the list.** Membership display names are already visible to GMs in the session roster and the access overview. The list never appears in any audience response.

**Errors:**

| Status | Code or condition |
|---|---|
| 403 | `character_reveal_required` |
| 404 | non-disclosing: a whole-character deny, a character outside the world or not canon, a target membership or group outside this campaign or nonexistent, a revelation id belonging to another character |
| 409 | `public_profile_not_released` |
| 409 | `public_profile_character_not_active` (archived) |
| 409 | `revelation_target_not_active`: an ended or non-active membership, or an archived group |
| 422 | a body whose target shape does not match its kind |

**Idempotency** (DATABASE_CONVENTIONS §26.4):

- The fingerprint holds `character_id`, kind, the target ids and `reason`.
- The receipt is minimal, as with `replay_body`.
- **Where the reservation and replay happen (revised 2026-11-08, after review).** The reservation insert and the replay lookup are one statement, `begin_idempotent_request`. It runs inside the command, after the command's locks and after its fresh, under-lock reveal-authority check and whole-character deny check (§10.4, create steps 7–8 and the revoke row). It never runs in the route before the command.
  - **Mechanics.** The route passes its idempotency start (`start_campaign_idempotency` with the fingerprint) to the command as a callback, and the command calls it at step 8a.
  - The command returns either the replay or its own result. On a result, the route writes the audit row and then completes the reservation, as today. Without a key, the callback does nothing.
- **A replay is refused for a caller who has since lost authority or come under a deny.** This holds even when the loss committed after the route's pre-check but before the command took its locks:
  - lost authority returns 403 `character_reveal_required`;
  - a whole-character deny returns 404.

  No receipt is returned and nothing is written. The stored receipt is kept for a caller who is still authorized.
- **Key lock first (prerequisite P2).** A keyed create or revoke takes the idempotency key lock at step 0, before any row lock (§10.4). Every other route takes the same lock inside `begin_idempotent_request`, also before any row lock.
  - So a same-key request on any route waits at the key lock while holding no row lock, and A3's later reservation cannot wait at all.
  - Step 8b's post-reservation re-check is therefore withdrawn. An expiry during the key-lock wait is judged at step 7, which comes after it.
- **Scope and conflict detection are unchanged.**
  - The scope is still `(actor_user_id, campaign_id, idempotency_key)` in `security.idempotent_requests`, shared with every campaign route.
  - The fingerprint still includes the command name, so a key reused on another route is a conflict.
- **Why not in the route.** The reservation's foreign key locks the campaign row. Taking it before the command's locks deadlocks with ending a membership (§10.8.6).
- **A rollback frees the key.** The reservation is part of the request's one transaction. Any refusal or failure after it rolls it back, including validation errors and 40P01, and the rollback also releases the key lock. A valid retry with the same key then runs the command.

**API conflict and retry contract: changes (2026-11-08).** These are A3-specific unless stated. None adds a status code, a header or a retry hint.

1. **A3 replays are conditional on current authorization.**
   - A stored response is returned only after the under-lock authority and deny checks pass. Otherwise the caller gets 403 or 404 and no receipt.
   - Other routes replay after their route pre-check only, and are unchanged.
2. **Authorization is reported before key conflicts.** A caller who reuses a key across routes and has lost authority sees 403 or 404 from an A3 route, not 409.
3. **Cross-route reuse of one key.** With P2 (done, `d36d565`), the later request gets the documented non-disclosing 409, whichever route it is on. Without P2, an A3 route could instead deadlock (a 500) or, through DEF-022, return a success that never committed.
4. **Waiting is unchanged in kind** for every route. A same-key request still waits until the first ends, then replays, conflicts or runs. Only the place it waits moves: from the unique index to the key lock (§10.8.9 E1, E2).
5. **All routes, corrected by P3 before A3a (DEF-022, §11.5–§11.6).** A 2xx is sent only after the request's commit succeeds, and its receipt is then visible and its key lock released. A commit-time failure gets the response the same exception would get inside the handler; it never follows a 2xx. At HEAD a commit-time failure can follow a 2xx.

**Audit:**

- One `audit.change_log` row per real create or revoke. It carries ids, kind, `authority_source` and `audience_size`, and never the reason text in `changed_fields`. A1's delegation commands set this pattern.
- There is no row for a natural retry, a replay, a refusal or an already-ended revoke.
- System closures add their ids to the closing command's existing audit row: `closed_character_revelation_ids`, and `removed_character_revelation_member_ids`.

### 10.4 Locks and transactions

Each command is one transaction. The orders below extend A1 §3 and §5.8. They reverse no existing edge.

**Revised 2026-11-08** after the membership-end trace and disposable-database probes (§10.8):

- `campaign_current` creation now locks the campaign's open memberships before the campaign row (step 4a).
- Both revelation routes reserve their idempotency key after the command's lock phase.

The design as first written deadlocked in both cases (§10.8.4, §10.8.6).

**Revised again 2026-11-08, after the independent review.**

- The reservation and the replay lookup now come after the fresh, under-lock authority and whole-character deny checks, not merely after the locks (step 8a).
- The caller's account is locked in the lock phase (step 5a), so the reservation's foreign key cannot wait on it.
- Authority is judged again after the reservation, whose same-key wait can outlast an expiry (step 8b). *Withdrawn in the next revision.*

**Revised a third time 2026-11-08, after the second review: the cross-route cycle.**

- A keyed create or revoke takes the idempotency key lock at step 0, before any row lock. This requires P2, which makes every route's reservation take the same lock first.
- With every reserver holding the key lock, the late reservation cannot wait, so step 8b is withdrawn.

The waits are traced under "What the reservation can wait on", and the cross-route outcomes are in §10.8.9.

| Command | Locks, in order |
|---|---|
| `create_character_revelation` | (0) **when a key was given:** the idempotency key lock (`lock_idempotency_key`, P2), before any row lock → (1) caller's authority rows `FOR SHARE`, as for a release: the owner assignment, or the `gm` assignment then the delegation → (2) **group target only:** the group row `FOR KEY SHARE`, locked with no join (§7.3 pattern; avoids DEF-017) → (3) caller's membership `FOR SHARE` → (4) **member target only:** the target membership `FOR KEY SHARE`, with no join → (4a) **`campaign_current` only:** every open membership of the campaign (`campaign_id = :c AND ended_at IS NULL`) `FOR KEY SHARE`, with no join, ordered by `campaign_membership_id`; the ids this statement returns are the snapshot candidates (the approved D9-a cutoff, below) → (5) campaign `FOR KEY SHARE` → (5a) **the caller's `security.users` row `FOR KEY SHARE`**, after the campaign row (see "What the reservation can wait on" for why not before it) → (6) character's `core.entities` row `FOR KEY SHARE` → (7) `clock_timestamp()` and `resolve_reveal_authority(as_of=…)` with the same-source rule (§5.8); refusal is 403 → (8) `AccessContext` re-resolved for the actor's whole-character deny; refusal is 404 → (8a) **the idempotency reservation, or the replay lookup** (`begin_idempotent_request`, when the request carries a key); it cannot wait (below), so no further authorization check follows it → (9) validate the character (canon, active, in this world), the release, and the target (open, active, same campaign; group active), reading statuses in separate statements → (10) look up the live duplicate, which gives a natural retry → (11) **`campaign_current` only:** read the membership statuses of the step 4a set; the snapshot is those that are `active` → (12) insert the revelation, any snapshot rows and the audit row. Two concurrent first creations meet at the unique index; the second waits, then returns 200 `created: false` |
| `revoke_character_revelation` | (0) **when a key was given:** the key lock (P2) → (1)–(3) as for create → campaign `FOR KEY SHARE` → the caller's account `FOR KEY SHARE` → the revelation row `FOR UPDATE`, with no join → fresh-instant authority re-check (403) → whole-character deny (404) → **the reservation or replay lookup**, which cannot wait → close |
| `end_campaign_membership` (**changed**) | Unchanged up to and including `close_reveal_delegations_for_membership`. Then two new explicit locks: **the actor's membership (`ended_by_membership_id`) `FOR KEY SHARE`**, then **`campaign.campaigns … FOR UPDATE`**. Then closing member-target revelations and setting `removed_at` on that membership's snapshot rows. Then the existing status update, retention check and commit-time trigger, which finds the campaign row already held |
| `deactivate_access_group` (**changed**) | Unchanged, plus closing that group's live revelations (`access_group_deactivated`) after its grant revocations |

**Why step 4a exists (probed).** Without it, the snapshot insert at step 12 takes a foreign-key `FOR KEY SHARE` on each member's membership row *after* the campaign row.

- `end_campaign_membership` of a current member N holds N `FOR UPDATE` from its second statement, and then waits for the campaign row: its explicit lock after A3, or the retention trigger at HEAD.
- So creation holds the campaign and waits for N, while end holds N and waits for the campaign. PostgreSQL aborts one with 40P01, in both orders:
  - **A3-E1:** creation holds the campaign; end is aborted.
  - **A3-E2:** end holds N; creation is aborted.
- With step 4a, creation and end meet at N before either holds the campaign row, and both commit (A3-F1 to F4).

**Step 4a's mode and form:**

- **`FOR KEY SHARE`** is the mode the snapshot insert's foreign keys need anyway.
  - It conflicts only with `FOR UPDATE`, which every relevant writer takes on a membership: end, assign, the grants, the relationship grant, a transfer's recipient lock, recovery, and invitation reopen.
  - It is compatible with `FOR NO KEY UPDATE` (P1's group add, the delegation grant) and with `FOR SHARE` (authoring, the release, the caller's own lock at step 3).
- **No join.** Statuses are read at step 11, so a membership whose status changed while the lock waited is not misread (DEF-017).
- **Id order.** Two creations take only `FOR SHARE` and `FOR KEY SHARE` on memberships, which never conflict. Ordering keeps a `FOR UPDATE` taker of any one row waiting in one place.

**Why step 4a adds no cycle.**

- Every command that locks a membership `FOR UPDATE` and later needs the campaign row takes the membership first. That covers end, the grant, the relationship grant and the relinquishing transfer. Step 4a also takes memberships first.
- Recovery takes the campaign `FOR NO KEY UPDATE` before its membership. That mode does not conflict with step 5's `FOR KEY SHARE`, so creation passes it (A3-F5, F6).
- `add_campaign_member` takes the campaign `FOR UPDATE` first. Creation waits for it at step 5, and the new member is not in the step 4a set (A3-F10).
- Probed against a relinquishing transfer (A3-F7, F8) and a grant to a member (A3-F9).

**Why the reservation and the replay lookup come after the under-lock checks (revised after review).**

- **Not before the locks (probed).** `security.idempotent_requests.campaign_id` references `campaign.campaigns`, so the reservation insert takes the campaign row `FOR KEY SHARE`.
  - A route that reserves first therefore holds the campaign before any role or membership lock.
  - If that request then waits on a row an end holds, and the end waits for the campaign `FOR UPDATE`, the two deadlock. The row may be the ending revealer's role rows, or a member in step 4a.
  - This was probed for both routes' prefixes:
    - **KEYED-K3:** `campaign_current` creation; creation is aborted.
    - **KEYED-K4:** member creation by the ending revealer; end is aborted.
  - Reserving after the lock phase removed the cycle, and both commit (KEYED-L1 to L3).
  - Those probes reserved after step 6. Moving the reservation further, after steps 7–8, adds no lock: those steps only read. Step 5a's account lock is traced below.
- **Not before the checks (authorization).** The route's pre-check runs before any lock and can be stale by the time the command holds its locks.
  - A revocation of the caller's role or delegation that commits in that gap is seen by step 1's locking read and refused at step 7 (403).
  - A whole-character deny that commits in that gap is seen by step 8's re-resolution and refused there (404). A deny can be committed directly to the caller's membership, or to a group the caller belongs to, or by adding the caller to a denying group.
  - Because the replay lookup comes after both steps, a caller refused there gets no stored receipt. Before this revision, a replay could have been returned after the lock phase but before steps 7–8.
- **What the held locks guarantee, and what they do not.**
  - Steps 1–6 make an *allowed* decision at steps 7 and 8 stay allowed until commit. Each conflicting write that would turn it into a refusal must wait for the request's locks:
    - revoking or changing the caller's role or delegation;
    - ending the caller's membership;
    - a new deny on the caller or a group, or adding the caller to a denying group;
    - deactivating the caller's account;
    - archiving the character, or changing its canon status.
  - The locks need not, and do not always, stop changes that only remove restrictions: revoking a deny, granting a delegation, removing the caller from a denying group. Such a change can commit while the request runs. It cannot turn an allowed decision into a refused one, and a request that was refused is simply refused under the older, stricter state.
  - Time is not a write. An expiry is judged at step 7, after every wait that precedes it.

**What the reservation can wait on, and what that invalidates.** The reservation insert, `INSERT … ON CONFLICT (actor_user_id, campaign_id, idempotency_key) DO NOTHING`, has three possible waits:

1. **Its foreign key to `campaign.campaigns`** (`FOR KEY SHARE`). Already held from step 5, so it does not wait.
2. **Its foreign key to `security.users`** (the caller, `FOR KEY SHARE`).
   - **Without step 5a**, account deactivation (`_set_local_account_lifecycle_status_impl`: advisory lock, then the account `FOR UPDATE`, then the status update) could hold that row. The reservation would wait, and the deactivation's commit makes step 7's answer wrong: the owner and `gm` predicates require an active account.
   - **With step 5a** the row is already held, so the reservation does not wait. Deactivation waits for the request instead, so the request commits first, or the request waits and step 7 refuses it (probes ACC-2a, ACC-3a).
   - **Why after the campaign row, not before it.** `add_campaign_member` locks the campaign `FOR UPDATE` and then the target account `FOR UPDATE`. Aimed at an existing member who is creating a revelation, it deadlocked with an account lock taken before the campaign (ACC-1b, 40P01). With the lock after the campaign row, the add waits at the campaign row and then fails on `ux_campaign_memberships_open` as it always would (ACC-1a).
   - **Every other account `FOR UPDATE` taker** locks the account's membership first: assign, the grants, the relationship grant and a transfer's nested assign. Step 3 holds that membership, so those commands wait for the request before reaching the account.
3. **Its unique index.** The index waits when the same caller has an uncommitted reservation for the same key in this campaign, on any route.
   - **Without a key lock this forms a cycle across routes (reproduced, §10.8.9).**
     - Every existing keyed route reserves before its own row locks (P2 evaluation, §10.11).
     - A same-actor, same-key request on such a route can therefore hold an uncommitted reservation while A3 holds its lock phase. A3 waits for that row at step 8a.
     - The other request then needs a lock that conflicts with A3's: the caller's role rows `FOR UPDATE`, or the campaign `FOR UPDATE` (end's retention lock, the grants, add member).
     - So each waits for the other. The reviewed case is a keyed end of the caller (HEAD-X1, HEAD-X3). Ending another member does the same at the end's commit (HEAD-X2, HEAD-X4).
     - Same-route A3 pairs do not cycle, because both hold only shared modes (HEAD-S1). The waiting request still holds its locks for the whole wait.
   - **With the key lock (step 0 and P2), this wait cannot happen.**
     - Every uncommitted row in `security.idempotent_requests` belongs to a transaction holding that scope's key lock, and A3 holds it from step 0. So step 8a finds no uncommitted conflicting row.
     - Its foreign keys are already held (steps 5, 5a). The reservation therefore cannot wait at all.

**Step 0: the idempotency key lock (requires P2).**

- **The lock.** `SELECT pg_advisory_xact_lock(:namespace, hashtext(:actor || ':' || :campaign || ':' || :key))`, through a shared helper `lock_idempotency_key(connection, *, actor_user_id, campaign_id, idempotency_key)` in `dnd_ai.api.idempotency`.
  - It is exclusive and transaction-scoped: it is released at commit or rollback, the instant the reservation row becomes visible or disappears.
  - `namespace` is one fixed integer constant, registered beside the helper and in DATABASE_CONVENTIONS §26.4. The two-key form keeps it apart from single-key advisory locks such as `local_auth`'s.
- **Who takes it:**
  - **P2:** `begin_idempotent_request`, immediately before its `INSERT`, for every route.
  - **A3:** create and revoke, at step 0. Their later `begin_idempotent_request` at step 8a re-takes it, which is reentrant within a transaction and does not wait.
  - **Without a key,** nothing is taken.
- **The invariant: a key lock is only ever requested by a transaction that holds no row lock.**
  - Existing routes call `begin_idempotent_request` before their command. They hold no row lock then, because their dependencies only read; the release pre-check calls `resolve_reveal_authority` with `lock="none"`.
  - A3 calls the helper at step 0.
  - A request waiting on a key lock therefore holds nothing anyone else waits for, and cannot be part of a deadlock.
  - P2's structural test pins the invariant.
- **Collisions.** Two scopes whose `hashtext` values collide share a lock and serialize briefly. Nothing else changes: uniqueness and the fingerprint still decide the answer, and the waiter still holds no row lock.
- **Waits it moves.** A same-key request now waits at the key lock instead of at the unique index. It waits for the same transaction and reaches the same result (§10.8.9 E1, E2).

**What stays the same.**

- A replay still returns the stored status and body.
- The unkeyed path skips steps 0 and 8a.
- Every other keyed campaign route still reserves first, and with P2 takes the key lock at that moment.
  - P2 removes same-key cycles between any two routes.
  - It does **not** remove DEF-019, whose cycles are between *different* keys on existing routes (§10.11).
  - A3's own routes form no DEF-019 cycle: different keys by KEYED-L1 to L3, and the same key by the key lock. That holds only once P2 is in place (§10.8.9).

**Why the group comes before the caller's membership.**

- After P1, `add_access_group_members` locks the group `FOR UPDATE`, then the added members' memberships `FOR NO KEY UPDATE`. `FOR NO KEY UPDATE` conflicts with the creator's membership `FOR SHARE`.
- So if creation took the membership first and the group second, adding the revealer to the target group would deadlock.
- With the group first, the two meet at the group row.
- `deactivate_access_group` and `update_access_group` take only the group row, so the order cannot form a cycle with them.

**Why the campaign is `KEY SHARE`.** It is the mode A2a's release, `lock_authoring_scope` (after P0) and A1 take.

- It is compatible with recovery's `FOR NO KEY UPDATE`, so recovering a membership for the revealer cannot deadlock with a creation (the DEF-014 cycle).
- It still conflicts with every campaign `FOR UPDATE`:
  - `add_campaign_member`;
  - archive;
  - `create_resource_grant`;
  - the commit-time retention trigger, which every membership UPDATE fires, invitation reopen included;
  - the new explicit lock in `end_campaign_membership`.

**Why `end_campaign_membership` needs the explicit campaign lock (probed).**

- **Revoke against end's closure.**
  - `revoke_character_revelation` takes the campaign `FOR KEY SHARE` and then the revelation row. End closes the same member-target row.
  - If end closed it before taking the campaign row, which at HEAD it takes only at commit, then end would hold the revelation row and wait for the campaign, while the revoke holds the campaign and waits for the row. That is 40P01 (A3-V3, the rejected variant: the revoke is aborted).
  - With the campaign lock before the closures, the two meet at the campaign row, and both commit in either order:
    - **A3-V1:** the revoke first, then end's closure is a no-op;
    - **A3-V2:** end first, then the revoke returns `revoked: false`.
- **Snapshots.** Step 4a is now what keeps a departing member out of a snapshot. The explicit lock is not needed for that any more.
  - **Creation reaches N first.** End waits at N, after locking N's role rows. Creation inserts N's snapshot row and commits. End's closure then runs as a fresh statement after its own campaign lock, and sets `removed_at` on that row (A3-F1, F4).
  - **End reaches N first.** Creation waits at N in step 4a. End commits. The locking statement re-reads N as ended and skips it, so N is not a candidate (A3-F2, F3).
  - Invitation reopening reuses the same `campaign_membership_id` and does not change `joined_at`. That is why a stale open snapshot row would matter: the member would regain the revelation on reopen.

**Why the explicit lock adds no new cycle.**

- End already waits for the campaign row at commit, while holding everything it holds at the new point and more.
- **The actor's key-share lock must come first.** Today that lock is taken by the status UPDATE's foreign key, before the commit-time campaign lock.
  - If the campaign lock moved ahead of it, end would hold the campaign and wait for the actor's membership, while `create_resource_grant` to the actor held that membership `FOR UPDATE` and waited for the campaign.
  - Locking `ended_by_membership_id` `FOR KEY SHARE` explicitly, just before the campaign, keeps today's relative order: actor, then campaign. This was probed in both orders, and both commit (A3-X1, X2).
  - The status UPDATE then needs no new lock. For a self-removal the row is already held `FOR UPDATE`.
- The only rows end locks after the new point are revelation and snapshot rows.
  - Every writer of member-target revelation rows takes the campaign row first: create and revoke at `KEY SHARE`, and end itself.
  - Snapshot rows are inserted only by creation, under step 4a and step 5.
  - The exception is `deactivate_access_group`, which locks only group-target revelations. End never touches those.
- The trace of every command that holds a row end wants, or wants a row end holds, is §10.8. The three cycles it found already exist at HEAD and are unchanged by this lock (§10.8.1, §10.8.5, §10.8.6).
- The A1 §3 table's `end_campaign_membership` row changes to show this lock. P0's, P1's and A1's lock regressions must pass unchanged (§10.8.8).

**Behaviour that changes for an end in flight.**

- After A3, an `end_campaign_membership` that has passed its new campaign lock holds the campaign row `FOR UPDATE` until it commits.
- So a command that takes the campaign row before any membership now waits for it, where at HEAD it ran alongside until end's commit. Those commands are `add_campaign_member`, recovery, archive, and any keyed route's reservation.
- Only the position of the wait changes; neither order deadlocks. A grep at `a9ec4c4` found no existing test that parks an end and expects such a command to finish beside it. The parked-end tests in §10.8.8 all have their second command wait at a membership or role row first.

**D9-a candidate-statement cutoff (approved by the owner, recorded 2026-11-08).** D9-a says the snapshot is taken at "the moment the revelation is created". This design pins that moment to **the start of the step 4a statement**.

- **Candidate.** A membership is a candidate if and only if the step 4a statement returns it. That means its row is open (`ended_at IS NULL`) in the version that statement reads:
  - committed before the statement began; or,
  - for a row whose end was in flight when the statement reached it, still open once that end resolved. The statement waits: an end that commits excludes the member, and one that rolls back keeps them.
- **In the snapshot.** A candidate is in the snapshot if and only if its status is `active` when step 11 reads it. A status change in flight is waited for at step 4a and decided at step 11.
- **Excluded,** even when it commits before the revelation does: any membership created or reopened by a transaction that had not committed when the step 4a statement began.
- **Consequence.** The revelation's `created_at` is the transaction's start, which is earlier than the cutoff. So a snapshot member's `joined_at` can be later than the revelation's `created_at`, by at most the creation's own lock waits. The GM list shows both times as they are.
- **Alternative not recommended:** "every membership committed before the revelation commits". That is achievable only by blocking every join for the whole creation (a campaign `FOR UPDATE` in creation). It would reverse the lock order this section relies on, and reopen the cycles §10.8.4 removed.
- **Status.** Approved. A3a's snapshot rows (§10.8.4 S1–S9) and the T82 matrix's L and X columns are specified against it and are final.

**Joins and the meaning of "current".**

- "Current" (D9-a, D9-b) is the open memberships returned by the step 4a statement that are `active` when read at step 11, under the cutoff above.
- **`add_campaign_member`** takes the campaign `FOR UPDATE` and inserts a membership.
  - An add that committed before step 4a is included.
  - An add in flight is excluded: creation waits for it at step 5, and its membership is not in the locked set (A3-F10).
- **Invitation acceptance** takes the campaign `FOR SHARE`, which is compatible with creation's `KEY SHARE`.
  - **A reopen** is an UPDATE of an ended row. A reopen in flight is skipped by step 4a without waiting, because its committed version is still ended. Its commit-time trigger then waits for the creation, so the member rejoined after the snapshot and is excluded. A reopen that committed first is included. (By trace.)
  - **A new membership** is an INSERT and does not fire the trigger. It is included exactly when it committed before the step 4a statement. (By trace.)

**Not locked.**

- Account deactivation of anyone but the caller. The caller's own account is locked at step 5a.
- Role changes. A revelation's audience is membership-based, so changing a member from GM to player alters nothing.
- Reads: the resolver judges at the moment of reading, with no locks, as every other access read does.

### 10.5 Audiences and the lifecycle hooks

| Path | `member` | `access_group` | `campaign_current` | `campaign_current_and_future` |
|---|---|---|---|---|
| Created | The target, if open and active | Live members of an active group | Snapshot: the open memberships locked at §10.4 step 4a that are `active` (D9-a, D9-b), including GMs and the revealer | Every open, active membership, at every read |
| A member joins the campaign later | n/a | Included if added to the group | **Not included** | Included |
| `end_campaign_membership` | Revelation closed (`target_membership_ended`) | The member's group links are closed by the existing code, so they are excluded | Snapshot row: `removed_at`, `membership_ended` | Excluded, because the membership is not active |
| Rejoining through invitation reopen (same membership UUID) | Not restored | Not restored: a reopened membership starts in no groups | Not restored | **Included**, because the membership is active again (D9-c) |
| `add_access_group_members` / `remove_access_group_member` | n/a | Included / excluded from the next read | n/a | n/a |
| `deactivate_access_group` | n/a | Revelation closed (`access_group_deactivated`) | n/a | n/a |
| `reactivate_access_group` | n/a | Not restored. The group starts empty and powerless, as its grants do | n/a | n/a |
| The revealer loses reveal authority (role, delegation, transfer) | Survives (D9-f) | Survives | Survives | Survives |
| The character is archived, or stops being canon | Inert. The resolver's filter (active, canon) matches relationships and grants, and closes nothing. The revelation applies again if the character is restored | same | same | same |
| Recovery sets an open membership's status to `active` | Members were never targeted while not active (creation refuses non-active targets) | Group links unchanged | That membership was not in the snapshot when it was not active | Included |
| Suspended membership (database-only) | `resolve_access_context` returns None, so nothing applies | same | same | same |

**Resolution.** `resolve_access_context` gains one query, keyed by the route campaign and the caller's membership. It returns live revelations whose character is active and canon and whose audience matches:

- **`member`:** the target is the caller.
- **`access_group`:** the caller has an open link to an active group that is the target. This is the same subquery the resource-grant query uses.
- **`campaign_current`:** an unremoved snapshot row names the caller.
- **`campaign_current_and_future`:** every live row applies.

### 10.6 Source-tagged authority inside `AccessContext`

- **New field.** `AccessContext` gains `revelations: Mapping[UUID, frozenset[RevelationSource]]`, keyed by character. Each source records the revelation id and its kind. The field is separate from `character_capabilities`, so a revelation never becomes a relationship capability and the reverse never happens.
- **`has_capability(code, character_id=X)`.** The baseline gains `code in {character.discover, character.view_public_profile} and X in revelations`. The grant lookup then runs unchanged, so:
  - a resource-grant `deny` under `character_id` still wins;
  - a role-only check (no `character_id`) gains nothing.
- **`resolve_world_character_visibility`.** It adds the revelation keys to `mentioned`. Without this, a caller with `discover_all` false would never test the revealed characters. The SQL predicate is unchanged: `disc_cv_denied` (the whole-character deny and lifecycle-hidden rows) already overrides `force_visible`.
- **Independence (T6).** Revoking a revelation closes only its own row.
  - A relationship, a resource grant, or a second revelation of another kind still supplies whatever it supplied.
  - A relationship or grant never needs a revelation.
  - The effective-access explanation and the access overview show each revelation as its own source, of kind `revelation`, labelled with its audience kind. No source is merged into another.

### 10.7 The shared discovery policy, surface by surface

Almost every consumer reads the bundle that `resolve_world_entity_visibility` builds. So A3b's change to `mentioned` reaches them all at once. Lines were checked at `a9ec4c4`.

| Surface | Where it decides | Effect of A3b on a caller whose only path is a revelation | Depends on A4 |
|---|---|---|---|
| World search list, category counts, pagination | `_VISIBLE_ENTITIES_SQL` via `search_world_entities` and `count_world_entities` ([queries/world_explorer.py](../src/dnd_ai/queries/world_explorer.py)) | Listed and counted. Name matching, the sort and the cursor are unchanged. The card's summary and the summary match use the released summary (§10.12) | The card link (`can_open`) |
| Direct character detail | [api/characters.py](../src/dnd_ai/api/characters.py) (`resolve_character_view_tier`) | **Unchanged: 404.** Discover-only callers already list without opening (`can_open_participant`); a revelation does the same until A4 | Yes: A4 adds the `public_profile` tier |
| World relationships list and detail; the character page's Relationships section | `all_participants_discoverable_sql`, `discoverable_entity_ids` ([queries/world_explorer.py](../src/dnd_ai/queries/world_explorer.py), [queries/relationship.py:159](../src/dnd_ai/queries/relationship.py#L159), [queries/character_relationships.py:156](../src/dnd_ai/queries/character_relationships.py#L156)) | A reader-visible relationship now appears when every participant is discoverable, the revealed character included (D10) | No |
| Organization members | [api/organization_members.py:68](../src/dnd_ai/api/organization_members.py#L68), [queries/organization_members.py:99](../src/dnd_ai/queries/organization_members.py#L99) | Listed in public memberships (D10) | No |
| Session roster | [api/sessions.py:184](../src/dnd_ai/api/sessions.py#L184); `_can_open_character` [:169](../src/dnd_ai/api/sessions.py#L169) | Named; `can_open_character` false | Yes: the link |
| Session travel | [queries/session_travel.py:112](../src/dnd_ai/queries/session_travel.py#L112) | Named | No |
| Event explanations | [api/event_explanations.py:197-211](../src/dnd_ai/api/event_explanations.py#L197-L211), [queries/event_explanations.py:405](../src/dnd_ai/queries/event_explanations.py#L405), [:710](../src/dnd_ai/queries/event_explanations.py#L710) | Named as a participant (D10) | No |
| Encounters | [api/encounters.py:431](../src/dnd_ai/api/encounters.py#L431), [queries/encounter.py:285](../src/dnd_ai/queries/encounter.py#L285) | Named in the member projection of a member-readable encounter (D10) | No |
| `active_encounter_id` on the character page | `_may_reference_active_encounter` ([queries/character.py:113](../src/dnd_ai/queries/character.py#L113)) | Not reached, because the detail route is a 404 | **A4 must keep the public tier free of it** (as the summary tier, A0) |
| Knowledge subjects | [api/knowledge.py:347](../src/dnd_ai/api/knowledge.py#L347), [:405](../src/dnd_ai/api/knowledge.py#L405) | The subject label of an item the caller may already read (D10). It grants no knowledge visibility | No |
| Campaign clock | [api/campaign_clock.py:107](../src/dnd_ai/api/campaign_clock.py#L107), [:195](../src/dnd_ai/api/campaign_clock.py#L195) | None: it uses only the event deny set | No |
| Audience preview | [api/preview.py](../src/dnd_ai/api/preview.py) `resolve_preview_subject` → `resolve_access_context` | Inherits the subject's revelations. The quest and Knowledge adapters show exactly what the subject sees | The character-profile preview (A7) |
| Party roster | [api/parties.py:134-178](../src/dnd_ai/api/parties.py#L134-L178) | D4-C (§10.13): the party's current controllers see its current members; everyone else gets shared discovery. A revelation reaches the roster only through discovery | No |
| Bootstrap perspectives, inventory, sheet, builds, calculations | `view_knowledge`, `resolve_character_inventory_access`, the sheet's tier | **Unchanged.** Regression tests only | No |
| World-level canon search with no campaign | [api/world_canon.py:86](../src/dnd_ai/api/world_canon.py#L86) (`discover_all=False`, no revelations) | Unchanged: revelations are campaign-scoped | No |
| AI context assembly | [domain/context_assembly.py](../src/dnd_ai/domain/context_assembly.py) | Unchanged: no revelation input | No |

**Summary.**

- **A3b:** wiring the bundle, the party roster (D4-C, §10.13), the explanation and overview, and the released-summary projection in search (D5-c, §10.12).
- **A4:** the public tier in direct detail, `can_open` and the roster links, `sections.public_profile`, D6 and D11.
- **Safe meantime:** between A3b and A4 a revealed character is listed but cannot be opened. That is how discover-only callers behave today, so no list and detail pair disagrees in a new way.

### 10.8 Membership end: the concurrency matrix, and retry outcomes

**Revised 2026-11-08.** This section replaces the 2026-11-07 outcome table and the untraced-cycle deferral that §10.11 carried.

**Method.** Each pair was run on the test suite's per-run disposable PostgreSQL 18 database, which is created and dropped by `tests/conftest.py`. The probes ran outside the repository and none is committed.

**Status of this evidence.**

- The probes are **design evidence only**. They chose the lock order; they do not accept it.
- The A3 rows ran against probe tables and SQL that imitate the design, not against migration 145 or the A3a commands.
- Acceptance is the A3a command and HTTP races of §10.9. Those run on the real schema (145's tables, triggers, constraints and foreign keys), with the real commands, and through the real request transaction.
- Where an A3a test and a probe disagree, the A3a test decides, and the design is corrected.

- Each pair uses `LockRace` (§7.7): the first command is paused just before a named statement, the second is started, and the probe waits until the second's session reports the first's in `pg_blocking_pids`. The first is then released.
- **HEAD probes** call the real commands at `a9ec4c4`.
- **A3 probes** run the §10.4 order in SQL, with end's code at `a9ec4c4` plus the §10.4 change. They use probe tables carrying the foreign keys §10.2 specifies: revelation → campaign, character, target membership and creator; snapshot → revelation, campaign and membership.
- **Keyed** means the route's prefix ran first: `begin_idempotent_request`, whose insert takes the campaign row `FOR KEY SHARE`. Unkeyed is the command alone. Every existing race test posts without a key; the portal always sends one (`portal/src/api/*`).

**Reading the tables.**

- *Waits:* `waiter → holder` means `pg_blocking_pids(waiter)` contains the holder's pid while the first command is paused. Every observed row wait was on the holder's transaction id (`ShareLock`).
- *40P01:*
  - PostgreSQL aborted the session that had waited longest. In every probe, that was the one blocked first.
  - The API maps 40P01 to 500, and the recovery script exits with an error.
  - An aborted transaction writes nothing: no row, no audit row and no idempotency reservation.
- *Audit:* each committed command writes its usual single row:
  - `end_campaign_membership` when `ended`;
  - `create_resource_grant` per grant;
  - `transfer_campaign_ownership` when something changed;
  - the recovery script on success;
  - A3's create and revoke per real change.

  A refusal or a no-op writes none.
- *Scene:*
  - A and B are built-in owners with non-expiring assignments; M and N are players; X is a character.
  - "Stranded" means A's owner assignment is finite and B's account is archived. Recovery may then run, because it needs a non-expiring manager on an *active* account. A can still act, and end's retention check still passes through B's row, because `campaign_has_access_manager` ignores account status.
  - E(M by A) is `end_campaign_membership` of M with A as the actor.
- *Pause points:*
  - **HEAD end, "holding M":** before its status UPDATE. It holds M's role rows and M `FOR UPDATE`, and no campaign lock.
  - **A3 end:** "before its campaign lock" (holding M and its closures) or "after its campaign lock" (before the revelation closure).

#### 10.8.1 Against administrative recovery that targets the ending membership

| # | First, paused | Second | Waits | Outcome | Final state | Evidence |
|---|---|---|---|---|---|---|
| R1 | E(M by A), stranded, holding M (A3: before its campaign lock) | recovery for M's user | recovery → end. Recovery holds the campaign `FOR NO KEY UPDATE` and waits for M | **40P01.** On release, end requests the campaign row (at commit at HEAD; explicitly after A3), which recovery holds. Recovery is aborted; end commits | M ended, its roles revoked. No recovered owner, and the campaign is still stranded. Audit: end ×1 | HEAD-R1, A3-X3 |
| R2 | recovery, holding the campaign, before its membership lock | E(M by A) | end → recovery, at the campaign row | **40P01.** On release, recovery waits for M. End is aborted (500); recovery commits | M open and active, holding owner and player. Audit: recovery ×1 | HEAD-R2, A3-X4 |
| R3 | recovery, holding the campaign and M, before its role insert | E(M by A) | end → recovery at M, after locking M's role rows | Recovery commits, then end commits | M ended. End's role closure, a fresh statement, also revokes the owner row recovery has just inserted, so the campaign is stranded again. Audit: recovery ×1, end ×1 | HEAD-R3; A3 by trace (end's new locks come after M) |
| R4 | E(A by A), the stranded finite owner removing themself, holding A | recovery for A's user | recovery → end | As R1: recovery 40P01, end commits | A ended. Only B's owner row is left, on an archived account | HEAD-R4 |
| R5 | E(M by A), holding M | recovery for N's user | none: recovery finishes while end is paused | Both commit | N an owner; M ended | HEAD-R5 |

**Status.** R1, R2 and R4 are a pre-existing cycle, proposed DEF-020 (§10.11).

- Recovery locks the campaign row first and the membership second. Every other command locks the membership first.
- A3 changes neither order: its explicit lock replaces the commit-time one at the same relative position.
- A3 tests must not assert that both commands commit in R1, R2 or R4.

#### 10.8.2 Against role assignment, revocation and change (unkeyed)

| Pair | Lock winner first | Other first | Evidence |
|---|---|---|---|
| E(M) against `assign_membership_role` to M | **Assign holds M:** end waits at M; assign commits; end then revokes the new row too. Final: M ended, no live role. Audit: assign ×1, end ×1 | **End holds M:** assign waits at M, then gets 409 (`MembershipNotActiveError`) and writes nothing | `test_membership_role_concurrency.py::test_a_membership_ending_cannot_race_an_assign_targeting_it`. A3: unchanged, because assign takes no campaign lock |
| E(M) against `change_membership_role` of M's role | They meet at M's role row. **Change first:** end waits, then ends M and revokes the new row | **End first:** change gets 409 (`MembershipRoleNotActiveError`) | `test_membership_lifecycle_concurrency.py::test_a_role_change_cannot_race_a_removal_of_the_same_membership` |
| E(M) against `revoke_membership_role` of M's role | They meet at the role row. **Revoke first:** end closes the rest | **End first:** the revoke returns `revoked: false`, with no audit row | By trace. A3 does not affect it, because both meet before any campaign lock |
| E(M by A) against a revoke or change of N's role | The two serialize at the campaign row: at commit at HEAD, at end's explicit lock after A3. Both commit, and the retention check sees the other's result | — | UNKEYED-K13 (the revoke finished while end was paused, at HEAD). After A3, a revoke reaching commit while end holds the campaign waits for it (by trace) |
| E(A) against A's own owner self-assignment | `test_campaign_owner_lock_order.py::test_ending_an_owners_membership_while_they_assign_themselves_the_owner_role`, `::test_an_owner_ended_first_cannot_then_assign_themselves_the_owner_role`, `::test_a_self_assignment_that_wins_the_lock_is_a_conflict_not_a_deadlock` | | Pass unchanged |
| E(A) against an assign or change *by* A for N | The write locks N, then waits at its insert's foreign-key `KEY SHARE` on A (`granted_by`), which end holds. End needs nothing the write holds (assign takes no campaign lock; change takes it only at commit), so end commits. The write then commits, naming an ended `granted_by` (§7.9 item 1, unchanged) | — | By trace |
| Two ends, or self-removals | `test_membership_lifecycle_concurrency.py::test_two_concurrent_removals_of_the_identical_membership_serialize`, `::test_two_managers_concurrently_removing_their_own_memberships_cannot_both_leave_zero_managers`, `::test_self_removal_racing_another_managers_removal_of_the_same_membership` | | Pass unchanged. Keyed: §10.8.6 |

#### 10.8.3 Against ownership transfer

**Ending the recipient (unkeyed).** Every case is pinned by existing tests, which pass unchanged:

- `test_campaign_owner_lock_order.py`:
  - `::test_ending_the_recipient_while_a_relinquishing_transfer_is_in_flight`
  - `::test_a_recipient_ended_first_refuses_the_transfer_without_losing_the_owner`
  - `::test_a_transfer_in_flight_makes_ending_its_recipient_wait_for_it`
  - `::test_a_relinquishing_transfer_command_leaves_no_partial_state_when_its_recipient_is_gone`
- `test_campaign_owner_expired_recipient.py`:
  - `::test_ending_the_recipient_first_refuses_the_transfer_without_a_deadlock`
  - `::test_ending_a_live_owner_recipient_first_refuses_the_transfer`

A3 changes none of them, because the transfer waits at the recipient's role rows or membership before end's new locks. A **keyed** end of the recipient deadlocks with a relinquishing transfer (KEYED-K5, §10.8.6).

| # | First, paused | Second | Waits | Outcome | Final state | Evidence |
|---|---|---|---|---|---|---|
| T1 | relinquishing transfer A → M, after its gate (A's owner row `FOR UPDATE`) | E(A by B) | end → transfer, at A's role rows | Transfer commits (`assigned`, `relinquished`), then end commits | M is an owner; A's owner row is revoked by the transfer and A is ended. Audit: transfer ×1, end ×1 | HEAD-T1 |
| T2 | E(A by B), holding A's role rows and A | relinquishing transfer A → M | transfer → end, at the gate | End commits; the transfer gets 403 `campaign_owner_required` and writes nothing | A ended; M still a player; B the owner. Audit: end ×1 | HEAD-T2 |
| T3 | non-relinquishing transfer A → M, after its gate (`FOR SHARE`) | E(A by B) | end → transfer, at A's role rows | Both commit | M an owner; A ended | HEAD-T3 |
| T4 | E(A by B), holding A | non-relinquishing transfer A → M | transfer → end, at the gate | End commits; the transfer gets 403 | A ended; M still a player | HEAD-T4 |
| T5 | relinquishing transfer A → M, after its campaign `FOR UPDATE` | E(N by A) | end → transfer, at the campaign row (at commit at HEAD; explicitly after A3) | Both commit. End's `KEY SHARE` on A is compatible with the transfer's locks | M an owner; N ended | HEAD-T5 |

A3's end reaches its new locks only after A's role rows and membership, so T1–T5 are unchanged by A3 (by trace). A non-relinquishing transfer that replaces an expired recipient row revokes that row and takes the campaign row at commit. It serializes with end like a role revoke (by trace).

#### 10.8.4 Against revelation creation, snapshots and revocation (A3)

| # | First, paused | Second | Waits | Outcome | Final state | Evidence |
|---|---|---|---|---|---|---|
| M1 | create (member M) by A, before step 5 (holding M `KEY SHARE`) | E(M by B) | end → create, at M | Create commits; end commits | M ended. The revelation is closed `target_membership_ended`. Audit: create ×1, end ×1 with `closed_character_revelation_ids` | A3-M1 |
| M2 | E(M by B), before its campaign lock | create (member M) by A | create → end, at M (step 4) | End commits; create gets 409 `revelation_target_not_active` and writes nothing | M ended; no revelation | A3-M2 |
| M3 | create (member M) by A, before step 5 (holding A's owner row `FOR SHARE`) | E(A by B), the revealer | end → create, at A's role rows | Create commits; end commits | A ended; the revelation stays live (D9-f) | A3-M3 |
| M3′ | E(A by B), holding A's role rows | create by A | create → end, at step 1 | End commits; create's fresh re-check (step 7) refuses with 403 `character_reveal_required` and writes nothing | A ended; no revelation | By trace (the emulation has no re-check); keyed: KEYED-L2 |
| S1 | create (`campaign_current`) by A, step 4a, paused before step 5 or before step 12 | E(N by B) | end → create, at N | Create commits with N in the snapshot; then end commits | The snapshot holds A, B and M, plus N with `removed_at` and `membership_ended` | A3-F4, A3-F1 |
| S2 | E(N by B), before or after its campaign lock | create (`campaign_current`) by A, step 4a | create → end, at N in step 4a | End commits; create commits without N | The snapshot holds A, B and M | A3-F2, A3-F3 |
| S3 | create, step 4a, before step 5 | recovery for M's user, stranded | recovery → create, at M (recovery holds the campaign `FOR NO KEY UPDATE`) | Create commits (M in the snapshot); recovery commits | M an owner and in the snapshot | A3-F5 |
| S4 | recovery, holding the campaign and M | create, step 4a | create → recovery, at M | Recovery commits; create includes M | M an owner and in the snapshot | A3-F6 |
| S5 | create by B, before step 5 | relinquishing transfer A → M | transfer → create, at M | Both commit | M an owner and in the snapshot | A3-F7 |
| S6 | relinquishing transfer A → M, after its campaign lock | create by B | create → transfer, at M in step 4a | Both commit | as S5 | A3-F8 |
| S7 | create by A, before step 5 | `create_resource_grant` to N by B | grant → create, at N | Both commit | — | A3-F9 |
| S8 | `add_campaign_member` by B, before its role insert (holding the campaign `FOR UPDATE`) | create by A | create → add, at step 5 | Both commit; the new member is not in the snapshot | — | A3-F10 |
| S9 | invitation reopen or insert of N | create | — | §10.4 "Joins": a reopen or insert in flight is excluded; one committed before step 4a is included | — | By trace |
| V1 | revoke (member revelation of M) by A, after its row lock | E(M by B) | end → revoke, at the campaign row | The revoke commits; end's closure is a no-op | Revelation `revoked`; M ended. Audit: revoke ×1, end ×1, with no closed revelation ids | A3-V1 |
| V2 | E(M by B), after its campaign lock | revoke by A | revoke → end, at the campaign row | End commits; the revoke returns `revoked: false` with no audit row | Revelation `target_membership_ended` | A3-V2 |
| AC1 | create by A, after step 5, before step 5a | `add_campaign_member` of A's user (already a member) by B | add → create, at the campaign row | Create commits; the add then fails on `ux_campaign_memberships_open` (409) and writes nothing | One revelation; A's membership unchanged | ACC-1a. With the account lock *before* the campaign row: **40P01**, the add aborted (ACC-1b), which is why step 5a sits after step 5 |
| AC2 | account deactivation of A, holding A's account `FOR UPDATE` | create by A | create → deactivation, at step 5a | Deactivation commits; create's step 7 refuses (403; the owner predicate needs an active account) and writes nothing | A's account inactive; no revelation | ACC-2a |
| AC3 | create by A, past step 5a | account deactivation of A | deactivation → create, at A's account | Create commits; deactivation commits after it | One revelation; A's account inactive | ACC-3a |

**What the probes rejected.**

- **The first §10.4 order** (no step 4a) deadlocks S1 and S2:
  - **A3-E1:** creation holds the campaign; end is aborted, and the snapshot keeps N.
  - **A3-E2:** end holds N; creation is aborted.
  - It commits only when end holds the campaign before creation reaches it (A3-E3).
- **An end that closes revelations without the explicit campaign lock** deadlocks with a revoke (A3-V3: the revoke is aborted).

**Unchanged rows, by trace.**

- **A group creation against an add of the revealer to the group:** they meet at the group row.
- **A creation against revoking the revealer's delegation or `gm` role:** as for a release (§5.8). First come, first served; a creation that waited gets 403.
- **A group revocation against `deactivate_access_group`:** exactly one closure, at the revelation row.

#### 10.8.5 Against direct grants

| # | First, paused | Second | Waits | Outcome | Final state | Evidence |
|---|---|---|---|---|---|---|
| G5 | `create_resource_grant` to M by A, before its insert | E(M by B) | end → grant, at M | Both commit; end revokes the new grant | M ended; the grant revoked and listed in `revoked_resource_grant_ids` | HEAD-G5. Also `test_resource_grant_concurrency.py::test_a_membership_ending_cannot_race_a_create_targeting_it` and `test_character_relationship_concurrency.py::test_a_membership_ending_cannot_race_a_grant_targeting_it`, which pass unchanged |
| G6 / X1 | grant to A by B, before its insert (holding A `FOR UPDATE` and the campaign) | E(M by A) | end → grant, at A: through the status UPDATE's foreign key at HEAD, and at the explicit `KEY SHARE` after A3 | Both commit | M ended; A's grant live | HEAD-G6, A3-X1 |
| G7 / X2 | E(M by A), at its last statement (HEAD) or after its campaign lock (A3) | grant to A by B | grant → end, at A (`FOR UPDATE` against `KEY SHARE`) | Both commit | as G6 | HEAD-G7, A3-X2. **A3a pins this pair in both orders** |
| G1 / X5 | grant to N *by A*, before its insert (holding N and the campaign `FOR UPDATE`) | E(A by B) | end → grant, at the campaign row | **40P01.** On release, the grant's foreign-key `KEY SHARE` on A (`granted_by`) waits for end. End is aborted; the grant commits | A open; the grant live | HEAD-G1, A3-X5 |
| G2 | E(A by B), holding A | grant to N by A | grant → end, at its foreign key on A | **40P01.** End then requests the campaign row, which the grant holds. The grant is aborted; end commits | A ended; no grant | HEAD-G2 |
| G3 | `grant_character_relationship` to N by A, before its insert | E(A by B) | end → relationship grant, at the campaign row | **40P01**: end is aborted | relationship live; A open | HEAD-G3 |
| G4 | `add_campaign_member` by A, before its role insert | E(A by B) | end → add, at the campaign row | **40P01**: end is aborted | new member added; A open | HEAD-G4 |

**Status.** G1–G4 are a pre-existing cycle, proposed DEF-021 (§10.11).

- §7.9 item 3 left it untraced; it is now traced and probed.
- The same cycle follows by trace for `change_character_relationship` (it revokes, then inserts with `granted_by` after its campaign lock) and for a group-target `create_resource_grant`.
- A3's commands lock the caller's membership before the campaign row, so they are not part of it.

**Access-group adds and authoring.** The P1 and P0 orders are unchanged by A3. These tests pass unchanged:

- `test_access_group_member_add_locks.py`:
  - `::test_an_add_that_waited_for_the_end_of_the_members_membership_is_refused_as_not_active`
  - `::test_ending_a_membership_waits_for_an_add_and_closes_the_row_the_add_wrote`
  - `::test_ending_the_actors_membership_waits_for_an_add_paused_before_its_insert`
  - `::test_an_add_waits_for_the_end_of_the_actors_membership_and_both_commit`
- `test_access_group_concurrency.py`:
  - `::test_add_member_cannot_race_membership_ending`
  - `::test_batch_add_locks_every_selected_membership`
- `test_authoring_scope_recovery_locks.py`:
  - `::test_ending_a_membership_waits_for_its_authors_in_flight_write_and_the_write_stands`
  - `::test_an_author_whose_membership_is_being_ended_is_refused_and_writes_nothing`

#### 10.8.6 Keyed requests (the portal path)

| # | First, paused | Second | Waits | Outcome | Evidence |
|---|---|---|---|---|---|
| K1 | keyed E(M by A), holding M | keyed E(N by B) | end2 → end1, at the campaign row: both hold `KEY SHARE` from their reservations, and end2 wants `FOR UPDATE` | **40P01**: end2 is aborted. M ended, N open | KEYED-K1; after A3, KEYED-K8 (same) |
| K2 | keyed E(M by A) | unkeyed E(N by B) | end2 → end1 | Both commit; the unkeyed end holds no campaign lock to upgrade | KEYED-K2 |
| K10 | keyed E(M by A) | keyed revoke of N's role | revoke → end | **40P01**: the revoke is aborted | KEYED-K10 |
| K11 | keyed E(M by A) | keyed change of N's role | change → end | **40P01**: the change is aborted | KEYED-K11 |
| K12 | keyed E(M by A) | keyed grant to N by B | grant → end | **40P01**: the grant is aborted | KEYED-K12 |
| K5 | relinquishing transfer A → M (route takes no key), holding M, before its campaign lock | keyed E(M by B) | end → transfer, at M | **40P01** on the transfer's campaign `FOR UPDATE`: end is aborted; the transfer commits | KEYED-K5 |
| K6 | grant to M by A, holding M, before its campaign lock | keyed E(M by B) | end → grant, at M | **40P01**: end is aborted; the grant commits | KEYED-K6 |
| K3 / K4 | E(N) or E(A) | A3 create, reserving *first* | create → end | **40P01** (§10.4) | KEYED-K3, K4 |
| L1–L3 | E(N), E(A) or create | A3 create, reserving after its lock phase | as S1, S2 and M3′ | Both commit; snapshot correct | KEYED-L1 to L3. The probes reserved after step 6; the revised position, after steps 7–8, adds no lock |

**Status.** K1, K5, K6 and K10–K12 are pre-existing, proposed DEF-019 (§10.11).

**A candidate fix that was rejected: deferring the reservation's campaign foreign key.**

- Deferred, the foreign key is checked at commit. That removed every keyed cycle above (DEFERRED-K1 to K7, L1 to L3).
- But it creates a new deadlock that HEAD does not have: a keyed `assign_membership_role` of `gm` against an `add_campaign_member` with `gm`. The assign holds the role row and, at commit, wants the campaign; the add holds the campaign and wants the role row (DEFERRED-K9: the add is aborted; KEYED-K9 at HEAD: both commit).

#### 10.8.7 Retries and receipts (A3)

| Situation | Outcome |
|---|---|
| Two creations for the same character, kind and target | One 201. The other waits on the unique index, then returns 200 `created: false` with the same id. Exactly one row, one snapshot and one audit row |
| A creation or revoke retried with the same key and body | The stored status and body. They come after the pre-check, the key lock, the lock phase and the under-lock authority and deny checks (steps 7–8). Nothing is written |
| The same key with a different body, on another character, or on the other revelation route | The existing non-disclosing idempotency 409. Nothing is written and the stored receipt is unchanged |
| A creation retried with no key after a lost response | 200 `created: false`; the snapshot is not refreshed (D9-e) |
| A keyed retry after the revealer lost reveal authority | 403 `character_reveal_required` and no replay. If the loss committed before the pre-check, the pre-check refuses. If it committed after the pre-check but before step 1's lock, step 7 refuses. The stored receipt is kept |
| A keyed retry after a whole-character deny on the revealer | 404 and no replay. A deny that committed after the pre-check is caught at step 8. A deny still being committed waits for the request's membership (or campaign) lock and applies to the next request |
| Two concurrent requests with the same key and body | The second waits at the key lock (step 0) holding no row lock. It then passes steps 1–8 and replays the first's receipt. There is one mutation, one audit row and one receipt |
| A keyed request refused or failing after its reservation (a validation 409 or 40P01) | The whole request rolls back, the reservation included. A later valid request with the same key runs the command |
| The caller's finite assignment expires while the request waits at the key lock | Step 7, which follows the wait, refuses with 403 and nothing is written. If the other request committed, its receipt is kept |
| A same-key request on another route, concurrent | §10.8.9 |
| A revoke retried | 200 `revoked: false`; no audit row |
| A creation against revoking the revealer's delegation, or `gm` role, in both orders | As for a release (§5.8): first come, first served; a creation that waited returns 403 |

#### 10.8.8 Existing tests that must pass unchanged after A3a

These are the named tests in §10.8.2, §10.8.3 and §10.8.5, plus:

- P0's `test_authoring_scope_recovery_locks.py` (all);
- P1's `test_access_group_member_add_locks.py` (all);
- A1's `test_campaign_owner_lock_order.py`, `test_campaign_owner_expired_recipient.py`, `test_campaign_owner_caller_expiry.py` and `test_character_reveal_delegation_deadlocks.py`;
- A2a's `test_character_public_profile_concurrency.py`;
- `test_membership_lifecycle_concurrency.py`, `test_membership_role_concurrency.py`, `test_resource_grant_concurrency.py`, `test_character_relationship_concurrency.py`, `test_access_group_concurrency.py` and `test_campaign_invitation_concurrency.py`.

Each covers its intended behaviour through an unkeyed path, and A3's end change moves no wait they observe (§10.4, "Behaviour that changes for an end in flight"). A failure there is a defect in A3a, not a test to update.

#### 10.8.9 The same key across routes (probed 2026-11-08)

**What these probes are.**

- The existing route is real: `POST /campaigns/{c}/memberships/{m}/end` through `TestClient`, in its own request transaction, with its real pre-check, reservation, command, audit and receipt.
- The A3 request is a SQL stand-in for `create_character_revelation` in the §10.4 order. It writes to a probe table, so it is **design evidence only**.
- **HEAD** rows use `begin_idempotent_request` as it is at `a9ec4c4`. **KEYLOCK** rows replace it in-process with P2's version: the key lock, then the original insert. A3's step 0 is added in the stand-in; the repository is unchanged.
- The actor is A, a built-in owner, in every row, and the key is the same within each row.
- Waits are `pg_blocking_pids`, with the lock type taken from `pg_locks`.

| # | First | Second | Waits | HTTP end | A3 | Final receipt for K, audit and state |
|---|---|---|---|---|---|---|
| HEAD-X1 (the reviewed cycle) | A3 create by A, paused before its late reservation (holding A's owner row `FOR SHARE` and the campaign `KEY SHARE`) | keyed end(A by A) | end → A3, at A's role rows (after the end reserved K) | 200 | **40P01** at the reservation | The end's receipt; audit end ×1; A ended; no revelation |
| HEAD-X2 | as X1 | keyed end(N by A) | end → A3, at **COMMIT** (the retention trigger's campaign `FOR UPDATE`) | **200, but rolled back** (the deadlock victim at commit, after the response; DEF-022) | 201 | **A3's** receipt; no audit; N **not** ended |
| HEAD-X3 | keyed end(A by A), reserved K, waiting on a held lock of A's role row | A3 create by A | end → hold; A3 → end, at the reservation's unique index | 200 | **40P01** | The end's receipt; audit end ×1; A ended |
| HEAD-X4 | keyed end(N by A), as X3 | A3 create by A | as X3 | 200 | **40P01** | The end's receipt; audit end ×1; N ended |
| HEAD-X5 | keyed end(B by A) with A finite, as X3; the end then fails its retention check | A3 create by A | as X3 | 400 (rolled back) | 201 | A3's receipt; no end audit; B open |
| KEYLOCK-X1 | as HEAD-X1, plus the key lock at step 0 | keyed end(A by A) | end → A3, on an **advisory** lock, before the end holds any row | **409** | 201 | A3's receipt; no audit; A open; three live role rows |
| KEYLOCK-X2 | as KEYLOCK-X1 | keyed end(N by A) | end → A3, advisory | **409** | 201 | A3's receipt; N open |
| KEYLOCK-X3 | keyed end(A by A), holding the key lock and K, waiting on the held lock | A3 create by A | end → hold; A3 → end, **advisory** (A3 holds no row lock) | 200 | **403** at step 7 (A's owner row revoked by the end) | The end's receipt; audit end ×1; A ended; no revelation |
| KEYLOCK-X4 | keyed end(N by A), as KEYLOCK-X3 | A3 create by A | as KEYLOCK-X3 | 200 | **409** at step 8a (K holds the end's receipt) | The end's receipt; audit end ×1; N ended; no revelation |
| KEYLOCK-X5 | keyed end(B by A), A finite, as KEYLOCK-X3; it then fails retention | A3 create by A | A3 → end, advisory | 400 (rolled back) | 201 (K was free again) | A3's receipt; no end audit; B open |

**Same route (the A3 stand-in twice) and existing routes:**

| # | Pair | Waits | Outcome | Final |
|---|---|---|---|---|
| HEAD-S1 | two A3 creates, same key and body | the second, at the unique index, **while holding its lock phase** | 201, then an identical replay | one receipt, one revelation |
| KEYLOCK-S1 | the same pair | the second, at the advisory lock, holding nothing | 201, then an identical replay | one receipt, one revelation |
| KEYLOCK-S2 | the same key, a different audience | advisory | 201, then 409 | one receipt, one revelation |
| KEYLOCK-S3 | the first fails after reserving | advisory | the first fails; the second 201 | one receipt (the second's), one revelation |
| HEAD-E1 / KEYLOCK-E1 | two keyed ends of N, same key | HEAD: the unique index. KEYLOCK: advisory | 200, then an identical replay, in both | one receipt; audit end ×1 |
| HEAD-E2 / KEYLOCK-E2 | a keyed end of N, then a keyed end of B, same key | as E1 | 200, then 409, in both | one receipt; N ended, B open |
| HEAD-C1 | an unkeyed end of A whose commit-time retention trigger fails | end → hold, at COMMIT | **200**, with nothing persisted | no audit; A open (DEF-022) |

**What the probes show.**

- Without the key lock, a same-key A3 request deadlocks with an existing keyed route in both orders.
- With P2 and step 0, every pairing ends in the documented result:
  - the first commits;
  - the second replays, gets 409, or is refused by current authorization;
  - when the first rolls back, the second runs.
- Existing routes behave identically with the lock; only the lock type of the wait changes.

### 10.9 Tests

Database and HTTP tests use namespaced fixtures. Race tests use `LockRace` (§7.7), and every wait is observed as blocked by the intended session through `pg_blocking_pids`.

**Migration and constraints:**

- `145` upgrades, downgrades and re-upgrades, and `alembic check` is clean.
- The downgrade refuses atomically while a role capability or resource grant names the new capability.
- **Each CHECK and trigger refusal:**
  - a target shape that does not match its kind;
  - cross-campaign targets, creators, revokers and delegations;
  - a character from another world;
  - a revelation with no release in its own campaign, including when only campaign B has a release;
  - an update to a structural column;
  - reopening a closed row;
  - a second live row for the same audience;
  - a snapshot row for a non-`campaign_current` revelation, for another campaign's membership, or inserted in a later transaction;
  - a snapshot update other than the single removal;
  - a role capability or `allow` grant naming `character.view_public_profile`.
- A character with a revelation cannot be physically deleted.

**T82 audience matrix.** Members:

- **P1:** a player in group G;
- **P2:** a player not in G;
- **O:** an observer;
- **L:** joins after the revelations;
- **X:** left, then rejoined through the invitation reopen;
- **R:** another campaign's GM, with a membership on the same world and the same timeline.

Expected visibility for one revealed character, in world search:

| Kind | P1 | P2 | O | L | X after rejoin | R (campaign B) |
|---|---|---|---|---|---|---|
| `member` (P1) | yes | no | no | no | no (if targeted before leaving) | no |
| `access_group` (G) | yes | no | no | only if added to G | no, until re-added | no |
| `campaign_current` | yes | yes | yes | **no** | **no** | no |
| `campaign_current_and_future` | yes | yes | yes | **yes** | **yes** | no |

The matrix also covers:

- group removal and deactivation followed by reactivation;
- revocation of each kind;
- a character archived and then restored.

**Independent sources (T6), each through the real commands:**

- an `observer_approved_viewer` relationship plus a revelation, with the revelation revoked: still discovered. With the relationship revoked instead: still discovered.
- a resource grant `allow` of `character.view_summary` plus a revelation, with the revelation revoked: the summary tier is unchanged.
- a `member` and a `campaign_current_and_future` revelation for one caller, with one revoked: still discovered through the other.
- the explanation lists each source separately before and after.

**Denies:**

- A whole-character `campaign.view` deny, created through the A2a-R route, to the member and to a group: the character is absent from every surface in §10.7 despite each revelation kind, and present again after the deny is revoked.
- A raw `character.discover` deny under `character_id` (D12): hidden from discovery, while bootstrap and other operations are unaffected.
- A `canon.edit` deny on the character for the revealer: creating and revoking still succeed (D8 item 5).

**What a revelation never grants.** For a revealed-only caller:

- `resolve_character_view_tier` refuses;
- inventory is `none`;
- the sheet, build and calculation routes return 404;
- bootstrap perspectives are unchanged;
- `can_open_participant` and the session roster's `can_open_character` are false;
- party-perspective Knowledge is refused.

**Authority:**

| Caller | Create and revoke |
|---|---|
| Owner | 201 / 200 |
| Delegated GM | 201 / 200 |
| Assistant GM | 403 `character_reveal_required` |
| GM without a delegation | 403 `character_reveal_required` |
| Custom `access.manage` holder | 403 `character_reveal_required` |
| Revoked delegation | 403 `character_reveal_required` |
| Expired `gm` assignment | 403 `character_reveal_required` |
| Player, observer | 403 from the route filter |
| Campaign B's owner on campaign A's route | 404 |

- No refusal writes a row or an audit row.
- A revelation made by a GM whose delegation was later revoked keeps applying, and the new owner can revoke it (D9-f).

**Rules and receipts:**

- the release precondition (409);
- archived character (409);
- target shapes (422);
- ended or inactive targets (409);
- cross-campaign targets (404);
- natural retry and keyed replay;
- the same key on another character (409);
- the audit row's content.

**Concurrency** (the §10.8 matrix; revised 2026-11-08):

- **Real races only (revised after review).** Every A3a race is an actual race on the migrated schema: migration 145's tables, triggers, CHECKs, unique indexes and foreign keys, and every earlier migration. The §10.8 SQL probes are design evidence and are not acceptance. Two forms are required:
  - **Command races.** The real A3a commands (`create_character_revelation`, `revoke_character_revelation`, the changed `end_campaign_membership`), and the real competing commands, each in its own `LockRace` worker transaction. The first is paused at the named statement.
  - **HTTP races.** For every row that involves an A3 route or the end route, the race is also run through `TestClient`. The request runs in the route's own single transaction (`get_connection`), with its dependencies, pre-check, idempotency, audit and commit.
    - The request is made to wait by a row lock that the test holds in its own transaction (`LockRace.hold`). That held transaction is a real command, left uncommitted, never a statement pause inside the request, because the request does not run on a named thread.
- **What every race asserts.** Before release, the stated `pg_blocking_pids` relationship. After release:
  - each command's result or HTTP status and body;
  - **audit:** `audit.change_log` rows, by count and command name, for the campaign's world;
  - **receipt:** `security.idempotent_requests` rows for the caller, campaign and key, by count, status, body and `completed_at`;
  - **revelation:** live or ended, and `end_reason`;
  - **snapshot:** members, `removed_at` and `removal_reason`;
  - **membership:** `ended_at` and status;
  - **roles:** the live role set of each membership involved.
- **Rows required:**
  - §10.8.4 M1, M2, M3, M3′, S1–S8 (S9's reopen and insert cases included), V1, V2 and AC1–AC3;
  - §10.8.5 X1 and X2, the explicit actor lock in both orders;
  - the KEYED-L rows as HTTP races.
- **Keyed HTTP regressions.** These are A3a acceptance criterion 4 (§10.10). Each is run for both create and revoke.
  1. **Authority or deny lost after the pre-check, before the locks: no replay.**
     - First, a keyed request K commits, storing receipt R and writing one audit row.
     - The test then holds, uncommitted, one of these real commands:
       - `revoke_character_reveal_delegation` of the caller's delegation, which holds the delegation row;
       - `revoke_membership_role` of the caller's owner or `gm` row, which holds the role row;
       - `create_resource_grant` of a whole-character `campaign.view` deny to the caller's membership, which holds that membership;
       - the same deny to a group the caller belongs to, which holds the group and the campaign.
     - A second request with K and the same body passes the route pre-check, which reads without locks and so cannot see the uncommitted change. It then blocks in the command: at step 1, step 3 or step 5. The test asserts `pg_blocking_pids` names the held transaction.
     - The test commits the hold. The request gets 403 `character_reveal_required` (authority) or 404 (deny), with no receipt fields in the body.
     - Afterwards: R is unchanged (same `completed_at`); the audit count is unchanged; the revelation, snapshot, membership and role state is unchanged.
  2. **Authorized same key, different payload: conflict.** The caller's key is reused with each of these:
     - another target or kind;
     - another character;
     - the other revelation route.

     Each returns the non-disclosing 409. Nothing is written, there is no audit row, and the stored receipt is unchanged.
  3. **Concurrent same-key requests: one mutation, one audit row, one receipt.**
     - The test holds the `audit.change_actions` row for `created` (for revoke, `updated`) `FOR UPDATE`, as `test_campaign_owner_expired_recipient.py` does. Request 1 then stops at its audit insert, past its reservation and its writes.
     - Request 2, with the same key and body, blocks on request 1 at the key lock (`pg_blocking_pids`; `pg_locks` shows an `advisory` wait).
     - On release, request 1 returns 201 (or 200) and request 2 returns the identical status and body.
     - Afterwards there is exactly one revelation (or closure), one snapshot set, one audit row and one completed receipt row.
     - **Expiry variant.** The caller's finite assignment expires while request 2 waits at the key lock, using the technique of `test_campaign_owner_caller_expiry.py::test_a_caller_who_expires_during_the_lock_wait_is_refused_and_nothing_is_written`. Request 2 gets 403 from step 7, and request 1's state and receipt stand.
  4. **A rollback leaves the key available.**
     - A keyed request fails after its reservation:
       - with 409 `public_profile_not_released` (create, before any release);
       - with step 7's 403, after the caller's finite assignment expired during a key-lock wait;
       - with 409 `revelation_target_not_active` (a member target whose membership has ended).
     - The test asserts that no `security.idempotent_requests` row exists for that key, and that nothing else was written.
     - The cause is then removed: the release is made, a new delegation is granted, or the target rejoins through invitation reopen, which keeps the same membership id and therefore the same body. The same key and body then succeed (201 or 200) with exactly one receipt row and one audit row.
  5. **Cross-route keys (requires P2): one route wins, the other conflicts or is refused, and nothing deadlocks.** These are run through the real routes, with the same actor and the same key K.
     - **XR1, A3 first.**
       - The test holds the `audit.change_actions` `created` row `FOR UPDATE`. A keyed create by A then stops at its audit insert, holding the key lock, its lock phase, its reservation and its writes.
       - A keyed `POST …/memberships/{A}/end` by A with K blocks on the create at the key lock (`pg_blocking_pids`; an `advisory` wait). Variant XR1b ends N instead.
       - On release: the create returns 201 and the end returns 409.
       - Final state:
         - one revelation and its snapshot set;
         - one audit row (`create_character_revelation`);
         - one receipt for K, holding the create's body;
         - A's (or N's) membership open, and the role set unchanged.
     - **XR2, end first.**
       - The test holds A's (or N's) role row `FOR SHARE`. The keyed end by A then stops after its reservation.
       - A keyed create by A with K blocks on the end at the key lock, holding no row lock: the end's own wait is on the hold alone (`pg_blocking_pids`).
       - On commit of the hold, the end returns 200. The create then returns:
         - **ending A:** 403 `character_reveal_required` from step 7, because A's owner row is now revoked;
         - **ending N:** 409, because K holds the end's receipt.
       - Final state:
         - one audit row (`end_campaign_membership`);
         - one receipt for K, holding the end's body;
         - the membership ended and its roles revoked;
         - no revelation.
     - **XR3, the first request rolls back.**
       - A's owner row is finite, and the keyed end is of B, the last non-expiring manager. The end stops after its reservation, as in XR2, then fails its retention check (400) and rolls back.
       - The waiting create gets K fresh and returns 201.
       - Final state: no end audit row; B open; one receipt for K, the create's; one revelation.
     - **XR4.** XR1 to XR3 repeated with the revoke route in place of create.
     - **XR5, A3 create against A3 revoke, both orders.** Same key: the second waits at the key lock, then gets 409, or 403/404 if its authorization has gone.
     - **XR6, same route, same key.** Two keyed creates, ordered by the audit-row hold:
       - same body: one 201 and an identical replay;
       - different body: one 201 and one 409;
       - the first fails after its reservation: the second gets 201.

       Each case ends with one receipt and at most one audit row and one revelation.
- **P2's own tests** are listed with P2 (§10.11). A3a relies on them and does not repeat them.
- **Unchanged tests.** The §10.8.8 tests pass unchanged.
- **Not A3 tests.** The rows marked as pre-existing defects are excluded:
  - DEF-020: §10.8.1 R1, R2 and R4;
  - DEF-021: §10.8.5 G1–G4;
  - DEF-019: §10.8.6 K1, K5, K6 and K10–K12.

  No A3 test asserts that both commands commit in those rows. Their regressions belong to the fixes (§10.11).

**Response-body disclosure sweep.**

- **Markers:**
  - the revealed character's canonical name and summary;
  - a second, unrevealed character's name;
  - the revelation `reason`;
  - the draft and release text markers from A2a.
- **Readers:** P2, O, R, and a revealed-only P1.
- **Surfaces:** world search, counts and pagination across a page boundary, character detail, relationships, organization members, the session roster and travel, event explanations, encounters, Knowledge, preview (as each subject), bootstrap, the sheet, inventory and the party roster.
- **Assertions:**
  - an unrevealed or revoked character's id and name appear nowhere for a caller without another source;
  - a revealed character's id appears only where §10.7 says;
  - no audience body contains a revelation id, a kind, a target, a reason, a snapshot member or any release text;
  - counts equal listed rows;
  - after revocation, the next request shows nothing;
  - stored receipts and audit rows contain no reason text in `changed_fields`.

**Release summary (D5-c, §10.12):**

- **Authoring:**
  - save, clear and no-op of `public_summary`;
  - the length CHECK;
  - the release snapshot equals the draft at the token;
  - the copy aid cannot target it, and a request naming it as a copy field gets 422;
  - the audit names the field without its text.
- **A revelation-only reader:**
  - the card shows the latest release's summary;
  - a later release without a summary shows `null` (no fallback to an earlier release or to the canonical text);
  - a release made before 145 shows `null`.
- **Search and counts,** with a marker word only in the canonical summary and another only in the released one:
  - the revelation-only reader matches the released word and not the canonical one, and the count agrees;
  - a relationship discoverer and the GM match the canonical word, and their count agrees;
  - the name matches for both.
- **Paging:** across a page boundary the order and cursor are identical for a revelation-only reader and a relationship discoverer, and the cursor contains no summary text.
- **Two campaigns:** campaign B's release summary never appears for a campaign A reader.
- **Gaining a relationship** moves the reader to the canonical summary on the next request.

**Party roster (D4-C, §10.13):**

- **Who qualifies:**
  - a controller of a current party member (each of `owner`, `primary_controller`, `co_controller`) sees every current member;
  - a controller of a former or future member does not;
  - a controller in campaign B of the same party's character does not;
  - with no effective clock, nobody is listed;
  - a controller under a whole-character deny on their own character does not qualify through it.
- **Denies on a listed member:** a whole-character deny, or a raw `character.discover` deny, on M omits M for that reader only, and `member_count` agrees.
- **Other readers:**
  - a non-controller player and an observer see only discoverable members (a revealed M appears, an unrevealed M does not);
  - the GM's roster is unchanged.
- **No leak beyond the roster:** the containment regression in §10.13 (search, counts, relationships, organization members, events, encounters, Knowledge, session roster, detail, sheet, inventory, profile, preview). The roster's key set is pinned, and the qualifying function has a single caller.

**Released-profile readers (D11, §10.14; A4 tests, listed here so A4 inherits them):**

- **Readable:** by a revelation holder; by a `viewer` (summary tier); by a GM.
- **Not readable:** by a bare relationship discoverer (`character.discover` only) or by a D4-C roster reader.
- **Denies:**
  - a raw `character.view_public_profile` deny blocks it on every path and leaves the summary tier;
  - a whole-character deny blocks everything.

**Structural tests:**

- only the revelation command, query and resolver modules reference the new tables;
- the route manifest gains three routes;
- the classification registry covers every new text column;
- the world-gate registry lists the new commands as `world_capability=None` scopes.

### 10.10 Slices and acceptance

| Slice | Scope | Depends on | Safe between commits because |
|---|---|---|---|
| **A3a** | Migration 145 (with the `public_summary` pair and its draft-save and release fields, §10.12); the create, revoke and list commands, routes and audit, with step 4a's membership lock and both routes reserving their key, and looking up replays, only after the lock phase and the under-lock authority and deny checks, with the caller's account lock and the post-reservation re-check (§10.4); the membership-end lock and closure; the group-deactivation closure; registries; docs | D5-c, D9 (including the D9-a cutoff), D12 (approved); P2 (done, `d36d565`); P3 (§11) | `AccessContext` is not changed. No audience surface reads the tables, so a revelation is visible only in the GM list and in audit |
| **A3b** | The `AccessContext` source and `has_capability` (with `include_revelations`); `resolve_world_character_visibility` and `released_summary_ids`; the party roster under D4-C (§10.13); the explanation and overview sources; the released-summary projection in search and counts (§10.12); the §10.7 matrix, disclosure sweep and T6 tests; the ADR 0021 §6 and access-contract clarification for the roster | A3a; D4-C, D5-c, D10 (approved) | Revealed characters are listed, named and counted, but cannot be opened (the existing discover-only behaviour). No release text is served |
| **A4** | The public tier, the direct-detail public response with the released summary, `can_open`, `sections.public_profile`, the session links, D6, and the D11 reader rule (§10.14). The roster gets no links (§10.13) | A3b, D6 (open), D11 (approved) | — |

**A3a acceptance:**

1. Migration 145 behaves as §10.2 says, pinned by its migration test.
2. Every §10.9 constraint and authority test passes, as do the §10.12 authoring tests.
3. **Real concurrency tests pass.** The rules-and-receipts tests and every §10.9 concurrency test pass, as command races and as HTTP races on the real schema and request transaction. Each asserts the audit, receipt, revelation, snapshot, membership and role state listed in §10.9; A3b adds only their visibility assertions.
   - No §10.8 SQL probe counts toward this criterion.
   - The §10.8.8 tests pass unchanged.
   - No test asserts success for a row §10.8 marks as a pre-existing defect.
4. **Keyed HTTP regressions pass, for both create and revoke** (§10.9, keyed items 1–5):
   1. **No replay after a loss.** When authority loss, or a whole-character deny, commits after the route pre-check but before the command acquires its locks, the keyed retry is refused (403 or 404). It returns no replay, and the stored receipt, audit and state are unchanged.
   2. **Different payload conflicts.** An authorized caller reusing a key with a different payload, character or route gets the non-disclosing 409, and nothing is written.
   3. **Concurrent same-key requests.** They produce exactly one mutation, one audit row and one completed receipt, and both responses are identical. A caller whose assignment expires during the wait is refused by step 7.
   5. **Cross-route keys (requires P2).** The XR1–XR6 cases pass with the final receipt, audit and mutation state §10.9 states. No pairing deadlocks, and none returns a success that did not commit.
   4. **A rollback frees the key.** A request that fails after its reservation leaves no reservation row, and a later valid request with the same key and body succeeds once.
5. The audience matrix passes as **stored state**: snapshot rows, closure reasons, and resolver input rows read directly. No API response changes.
6. A sweep of the existing audience surfaces shows byte-identical bodies before and after creating each kind of revelation.
7. **P2 is merged and reviewed before A3a's keyed routes** (done: `d36d565`, PASS WITH NONBLOCKING FINDINGS). **P3 is merged and reviewed before A3a** (§11.11). The snapshot follows the approved D9-a cutoff (§10.4).
   - With P3, criterion 4's statement "none returns a success that did not commit" is enforced by the request transaction itself.
   - A3a's HTTP tests still assert persisted state.
8. Docs:
   - `DATABASE_MODEL` §19;
   - `DOMAIN_MODEL` (revelation, audience kind, snapshot);
   - the `ENTITY_LIFECYCLE` command list;
   - `PHASE13E_ACCESS_CONTRACT` (the new routes and errors);
   - the A1 §3 lock table's `end_campaign_membership` row;
   - this plan.
9. The standard checks; the focused tests, then the full suite; migration up and down; `git diff --check`. Then stop for independent review.

**A3b acceptance:**

1. The full §10.9 matrix through HTTP.
2. The T6, deny and never-grants tests.
3. The disclosure sweep.
4. The §10.13 roster tests and the containment regression.
5. The §10.12 projection tests (search, counts, paging, older releases).
6. The explanation and overview show each revelation as a distinct source and stop showing it after revocation.
7. Preview matches the subject's own request.
8. No test that passed at A3a's head changes, except where this design names the change.
9. The same checks, then independent review.

### 10.11 Gaps found while tracing (not fixed by A3)

- **Access-management commands are not re-checked under lock** (§7.9 item 1). This is unchanged by A3, because A3's commands re-check reveal authority themselves.
- **DEF-017** (the stale group join) is avoided in A3's own group and membership locks. It is not fixed in the group commands.
- **The late foreign-key locks (§7.9 item 3), now traced and probed** (2026-11-08, §10.8). The trace found three cycles that already exist at HEAD. A3 introduces none of them and widens none, and none involves A3's own commands.
  - **Proposed DEF-019: keyed campaign requests deadlock.**
    - **Mechanism.** The idempotency reservation's foreign key takes the campaign row `FOR KEY SHARE` before the command's own locks. Two keyed requests in one campaign therefore deadlock when the first later needs the campaign `FOR UPDATE`. That covers ending a membership, revoking or changing a role, the grant commands and adding a member (K1, K10–K12).
    - **With an unkeyed command.** A keyed end also deadlocks with an unkeyed command that holds the ending membership and then needs the campaign `FOR UPDATE`: a relinquishing transfer (K5) or a grant (K6).
    - **Exposure.** The portal sends a key on every one of these routes, and the existing race tests send none.
    - **Reached by an existing test since P2 (2026-11-08).** Two keyed ends by the same owner with different keys (K1) are run by P2's different-key test. They deadlock in every run, and the second request is the victim at COMMIT; at HEAD it answers 200 through DEF-022 (§11.3, P2DK). P3 adds a deterministic regression for this cycle, kept separate from P2's independent-key test (§11.8, T9).
    - **Proposed grade:** 2 + 1 + 1 + 0 + 0 = 4, Medium. It is on a normal path; one request fails with a 500 and nothing is written; it needs overlapping requests in one campaign; it is visible; it affects one request.
    - **Fix.** It needs its own design. The per-route form A3 uses (lock phase, then reservation) is one option. Deferring the foreign key was probed and rejected (§10.8.6).
  - **Proposed DEF-020: ending a membership deadlocks with the recovery that promotes it** (R1, R2, R4).
    - **Mechanism.** Recovery locks the campaign row before the membership. Every other command locks the membership first.
    - **Direction of a fix:** lock the target user's open membership before the campaign row, and re-read it after. That needs its own design, because a membership can be inserted for the same user concurrently.
    - **Proposed grade:** 0 + 1 + 1 + 0 + 0 = 2, Low. It needs an administrator's script on a stranded campaign while a finite owner acts.
  - **Proposed DEF-021: ending an actor's membership deadlocks with that actor's own write** (G1–G4; by trace also `change_character_relationship` and group-target grants).
    - **Mechanism.** The write holds the campaign row `FOR UPDATE` and then takes `KEY SHARE` on its actor through `granted_by`.
    - **Direction of a fix:** lock the actor's membership `FOR KEY SHARE` before the campaign row, the order end and P1's add already use. It is best designed together with §7.9 item 1's re-check.
    - **Proposed grade:** 1 + 1 + 1 + 0 + 0 = 3, Low.
  - **Can A3 proceed?** Yes, with §10.4's two corrections. None of the three defects is a prerequisite for A3a or A3b:
    - A3's change to end keeps each cycle's lock positions: the explicit campaign lock sits where the commit-time lock sat, after the same rows (A3-X3, X4, X5 and KEYED-K8 match their HEAD probes).
    - A3's routes form no DEF-019 cycle **only once P2 is in place**: different keys by KEYED-L1 to L3, and the same key by the key lock (§10.8.9). Until then, a same-key request on another route deadlocks with them (HEAD-X1 to X4), so the claim is not made for A3 without P2.
  - **Recommended.**
    - Fix DEF-019 before A6, because the portal is how revelations will be created and revoked.
    - Enter all three in the defect register. This revision does not edit the register.
- **The new order's own races** (the explicit actor lock in end, step 4a and the reservation position) are pinned by §10.9's A3a race tests.
- **Prerequisite P2: the idempotency key lock (shared; designed 2026-11-08; required before A3a's keyed routes).**
  - **Why it is shared.**
    - A3 cannot see another route's uncommitted reservation without waiting for it, and it cannot reserve before its locks (KEYED-K3, K4).
    - So the same-key cycle (§10.8.9) can be prevented only if *every* reserver serializes on the key before taking row locks. A lock taken by A3 alone leaves an existing route's insert free to create the uncommitted row A3 later waits on.
  - **Change.**
    - `begin_idempotent_request` takes `lock_idempotency_key` immediately before its insert.
    - The helper is public, for A3's step 0.
    - The module docstring's "no advisory lock" sentence and DATABASE_CONVENTIONS §26.4 are updated to describe the lock.
    - No schema change and no migration.
  - **Not changed.** The two other stores, `campaign_creation_reservations` and `actor_idempotent_requests`, have no A3 caller and no cross-store scope.
  - **Routes affected, all evaluated at `a9ec4c4`.** Every campaign-keyed route function was checked by syntax tree: 134 route functions in 39 modules. They reserve directly, through `_authoring.start_campaign_idempotency`, or through a module helper such as `_run`, `_write` or `_operate`.
    - **The modules:** `access_grants`, `access_groups`, `campaign_clock`, `campaign_invitations`, `campaigns`, `character_builds`, `character_public_profile`, `character_state`, `dungeon_authoring`, `encounter_preparation`, `encounters`, `entity_lifecycle`, `event_corrections`, `events`, `integration`, `interactions`, `item_authoring`, `item_definition_authoring`, `items`, `knowledge_authoring`, `knowledge_runtime`, `location_authoring`, `memberships`, `movement`, `npc_authoring`, `npc_portrayal`, `organization_authoring`, `parties`, `player_character_authoring`, `quest_authoring`, `quest_runtime`, `quests`, `relationship_authoring`, `relationships`, `session_authoring`, `session_play`, `sources`, `travel` and `world_time`.
    - **In every one,** nothing touches the database before the reservation. The only earlier calls build request models (`character_builds.create_build_endpoint`) or read an attribute (`knowledge_runtime.belief_endpoint`). Each helper reserves before calling its operation. No route takes a row lock directly, and the route dependencies only read: the release pre-check resolves reveal authority with `lock="none"`.
    - So each route takes the key lock while holding no row lock, and only the location of its same-key wait moves.
    - **Probed on the real end route:** same key and same body gives the identical replay; same key and a different target gives an identical 409 (HEAD-E1/E2 against KEYLOCK-E1/E2).
  - **Tests (P2's own acceptance).**
    - **A structural test, failing on violation:**
      - every route function that reserves, and every helper it reserves through, makes no database call before the reservation;
      - no route or dependency takes a row lock;
      - the only insert into `security.idempotent_requests` is in `begin_idempotent_request`;
      - the only other caller of `lock_idempotency_key` is a command's first statement.
    - **HTTP races on two existing routes** (membership end and role revoke):
      - same key and same body: one mutation, one audit row, one receipt and an identical replay;
      - same key and different body: 409, nothing written;
      - the first rolls back: the second runs;
      - the same key across the two routes: the second gets 409.

      Each asserts the advisory wait through `pg_locks` and `pg_blocking_pids`.
    - **The full suite passes unchanged.**
  - **What P2 does not do.** It does not fix DEF-019, whose cycles are between different keys and stay open. It does not fix DEF-022.
  - **Implemented at `d36d565` and independently reviewed (PASS WITH NONBLOCKING FINDINGS).** The tests, the results and the review's findings are in "P2 implementation and review record", below §10:
    - structural caller-order coverage;
    - the external A3 call-site guard;
    - the outer-transaction harness limitation.

    Separately, **the different-key test asserts a success that did not commit** (§11.3, P2DK). P3 corrects it (§11.8, T8) and adds the DEF-019 regression (T9).
  - **Alternatives rejected:**
    - **A3 without keys:** contrary to DATABASE_CONVENTIONS §26.4, and it loses receipts.
    - **A separate A3 key store:** loses cross-route conflict detection, because a key would no longer be shared with other routes.
    - **A `lock_timeout` on A3's late reservation, mapped to a retryable 409:** nondeterministic, and it changes the contract for ordinary same-route retries.
    - **Deferring the reservation's foreign key:** probed in §10.8.6 and rejected.
- **Proposed DEF-022: a commit failure is reported to the client as success (pre-existing, all routes).**
  - **Mechanism.** `get_connection` commits on leaving its `yield` dependency, which FastAPI 0.141 runs after the response is produced. A failure at commit therefore reaches no client: a deferred trigger such as the access-manager retention check, a deadlock detected there, or a lost connection.
  - **Probed (HEAD-C1).** An unkeyed end of the caller returned 200 while its commit-time retention trigger failed. Nothing persisted: the membership was open, and there was no audit row.
  - **Also seen (HEAD-X2).** A keyed end returned 200 and was then the deadlock victim at commit. Its receipt never existed, and K held the other request's receipt.
  - **Effect.** For a keyed request, the client holds a body that no receipt backs, and a retry runs the command again.
  - **Reproduced deterministically through the real route (§11.3):**
    - a test-only deferred trigger failing COMMIT with 23000 (keyed) or 40P01 (unkeyed) gives 200 at HEAD, with nothing persisted;
    - at HEAD the response starts before the commit, while P2's key lock is still held.
  - **Also behind a false pass.** P2's test `test_a_different_key_takes_its_own_key_lock_without_queueing_behind_a_held_request` asserts `(200, 200)`. Its second request is the DEF-019 K1 deadlock victim at COMMIT, and nothing of it persists (§11.3, P2DK).
  - **Grade, revised 2026-11-08** under the revised rubric (`docs/ISSUE_GRADING_RUBRIC.md`): 2 + 2 + 1 + 1 + 0 = **6, Medium**. It was proposed as 5. The new evidence is that the lost write can be an access change the caller is told succeeded: ending a membership leaves the member's access in place behind a 200 (D1, C1, P2DK).
    - **Exposure 2:** a normal but limited application path. Any route whose commit fails qualifies. The deferred retention triggers fire on ordinary membership and role writes, and DEF-019's cycles reach COMMIT on the portal's keyed path.
    - **Impact 2:** loss of meaningful work behind a success. Nothing partial persists, but the requested change, including an access removal, is silently not made.
    - **Triggerability 1:** it needs a commit-time failure: a deferred trigger, a deadlock at commit, or a lost connection.
    - **Detection 1:** the response is misleading. The rubric names "a misleading completed receipt" under request preservation.
    - **Blast 0:** one request.
  - **Disposition: blocking for A3a, as prerequisite P3** (owner's direction, 2026-11-08; §11). It was previously recorded as a follow-up required before deployment.
    - After A3a, `end_campaign_membership` holds the campaign row before its in-command retention check, so for end the commit-time check can no longer differ from it (by trace). Other routes, and deadlocks at commit, keep the defect until P3.
    - The grades proposed above for DEF-019 to DEF-021 predate the rubric's revision; the owner should re-check them against it.
  - **Fix: P3 (§11), revised after CHANGES REQUIRED.**
    - A single app-wide async `Depends(commit_request_transaction, scope="function")` ends the request transaction after serialization and before the response is sent, including on a cancellation.
    - `get_connection` keeps its default scope at all 174 declarations, so no class R route signature changes.
    - The eight engine-backed handlers gain `request: Request` and end their authorization transaction before engine-side effects (§11.4.3).
    - The earlier note that about 174 route signatures would be affected is withdrawn: only a per-declaration scope would need that, and §11.4.1 rejects it.
    - The first P3 draft's claim that "no route signature changes" was also wrong, for the eight engine-backed handlers.
- **No character archive command exists.** The "archived and restored" tests write the status under the entity lock, as A2a's archive race did.

### 10.12 Release summaries and the caller's projection (D5-c, approved)

**The rule.**

- The canonical name stays the live identity label, for every caller and every surface. That covers display, search matching, sorting and the cursor.
- A **revelation-only** reader of character X receives a summary only from a deliberate release. They are never given X's canonical `core.entities.summary`, and never matched against it.

**Who counts as revelation-only.** A reader is revelation-only for X when both hold:

- X is in their `AccessContext.revelations`;
- no discovery-tier capability (`character.discover`, `character.view_summary`, `character.view_full`, `canon.edit`) reaches X through any other source, with denies applied as usual.

`has_capability` gains a keyword, `include_revelations` (default `True`). This test calls it with `False`.

| Caller | Revelation-only? |
|---|---|
| GMs (role `canon.edit`, so `discover_all`) | Never |
| A relationship discoverer | No |
| A grant `allow` of `view_summary` | No |
| A player whose only path is a member, group or campaign revelation | Yes |

A revelation-only reader who later gains a relationship sees the canonical summary from their next request.

**Authoring (an A2 change carried by A3a).**

- **Columns.** Migration 145 adds `public_summary TEXT NULL` to `campaign.character_public_profiles` and to `campaign.character_public_profile_releases`, with `CHECK (public_summary IS NULL OR char_length(public_summary) <= 4000)`. That is the limit `public_appearance` and `public_background` have.
- **No provenance.** There is no origin, watermark or copy source: the field is always authored.
  - `LEGACY_COPY_SOURCES` is unchanged, so the copy aid cannot fill it.
  - The 143/144 trigger inspects only the two legacy fields.
  - Nothing ever withholds it.
- **Save.** The draft save body gains `public_summary` with the same rules as `public_appearance`: optional and partial, explicit `null` clears it, the same validation and length, and the same token, no-op comparison, idempotency fingerprint and audit. Audit names the field in `changed_fields`, never its text.
- **Release.** The release snapshots `public_summary` from the draft at `expected_draft_row_version`, together with the other fields. Release immutability already covers every column.
- **GM read.** It returns `public_summary` for the draft and each release. Beside it, read-only, it shows the canonical name and summary as "canonical, shown to readers with another path".
- **No automatic publication.** No backfill, no default from the canonical summary, and no copy action. A GM who wants the canonical text released types or pastes it. Copying needs no restriction, because the canonical summary is `PUBLIC_WORLD`.
- **Registries.**
  - Classification: the draft column is `GM_ONLY` and the release column is `CAMPAIGN_VISIBLE`, as in 142.
  - Module access: `queries/world_explorer.py` (and A4's public read) become admitted readers of the releases table, read-only.
- **Downgrade.** It drops both columns, losing data by design, like the rest of 145's downgrade. Older code never serves the column, so dropping it discloses nothing.

**Older releases, and releases without a summary.**

- **What counts.** The latest release wins as a whole snapshot. A revelation-only reader sees that release's `public_summary`, or `summary: null` when it has none. That covers every release made before 145, and a later release whose draft summary was cleared.
- **No fallback.** Nothing falls back to an earlier release's summary, or to the canonical one.
- **Search.** Such a card matches search on its name only.
- **GM side.** The GM read flags the latest release with `public_summary` null ("audiences see no summary"). A new release is the only way to give them one.

**Search, counts and sorting use the caller's projection.** The change is in `_VISIBLE_ENTITIES_SQL` and the card select ([queries/world_explorer.py:255-296](../src/dnd_ai/queries/world_explorer.py#L255-L296), [:425-434](../src/dnd_ai/queries/world_explorer.py#L425-L434)), so the list and the counts share one predicate and cannot disagree.

- **New bundle fields.** `CharacterVisibility` gains `released_summary_ids` (the caller's revelation-only characters) and the bundle gains `campaign_id`.
- **The projected summary,** as SQL:

  ```sql
  CASE WHEN e.entity_id = ANY(:disc_released_summary_ids)
       THEN latest.public_summary
       ELSE e.summary END
  ```

  `latest` is `LEFT JOIN LATERAL (SELECT r.public_summary FROM campaign.character_public_profiles p JOIN campaign.character_public_profile_releases r USING (character_public_profile_id) WHERE p.campaign_id = :disc_campaign_id AND p.character_id = e.entity_id ORDER BY r.version_number DESC LIMIT 1)`. It is served by the existing unique `(character_public_profile_id, version_number)`, and the route's own campaign is the only one read.
- **Matching.** `q` matches `canonical_name ILIKE … OR <projected summary> ILIKE …`, so a revelation-only reader's search never touches the canonical summary. Other entity kinds are unchanged.
- **Counts.** Category counts use the same `FROM … WHERE`, so they count exactly what the list would return for the same `q`.
- **Sorting and the cursor.** They are unchanged: `lower(left(canonical_name, 200))`, then `entity_id`. Neither depends on the summary, so keyset paging is stable, and the cursor carries no summary.
- **The card.** Its `summary` field is the projected value.
- **No other surface.** No other discovery consumer renders a character's summary (checked by grep at `a9ec4c4`). The A4 public tier uses the same released summary.

### 10.13 The party roster exception (D4-C, approved) and the shared discovery rule

**The rule.** One reader may see more of a party's roster than discovery gives them: someone who currently controls a character that is a current member of that party, in this campaign. They see that one party's current members, as character id and canonical name, minus explicit character denies.

That is the whole grant. It is roster visibility only:

- no summary, profile, inventory, sheet or detail tier;
- no `can_open`;
- no discovery anywhere else.

**How it fits ADR 0021 §6 ("one discovery and profile predicate for every consumer").**

- **Discovery** is still decided by one predicate, the shared bundle. The roster's discovery path uses it unchanged.
- **The exception does not decide discovery.** It is a second, named audience for one response: a party's own controllers seeing the people their character travels with, which is a fact of the fiction.
- **It never flows back.** No other consumer reads it, and the roster's results never enter `AccessContext` or the bundle.
- **To record.** A3b adds a dated, owner-approved clarification to ADR 0021 §6 and to `PHASE13E_ACCESS_CONTRACT`: "the party roster names its current members to that party's current controllers; this confers no discovery".

**Who qualifies.** All of these, evaluated per request:

- The party is attached to the route campaign (`campaign.campaign_parties`).
- The campaign's effective clock is set. With no clock, membership is undetermined: nobody qualifies and the roster lists nobody, as today.
- The caller holds a live `owner`, `primary_controller` or `co_controller` relationship to some character C. It is resolved exactly as `resolve_access_context` resolves relationships: on this campaign membership and timeline, not revoked or expired, with no closed fictional interval, and C active and canon. No relationship type confers `character.control` today, so the type codes are the test. After P03-B, a live, in-effect assignment qualifies instead, and the relationship test is retired with the legacy rows (ADR 0021 §2.10).
- C is a current member of this party at the effective clock.
- C is not under a whole-character `campaign.view` deny for the caller. A controller denied their own character does not qualify through it.

**What a qualifying reader sees.** Every current member M of the party, except:

- M not shown to them by `lifecycle_hidden_entity_ids` (unpublished definitions; the existing filter);
- M under a whole-character `campaign.view` deny for the caller (`entity_id`; existing);
- **M under a `character.discover` deny for the caller (`character_id`; new, D12).**

**What everyone else sees.** Current members the caller can discover, through `discoverable_entity_ids` with their bundle, which already applies both denies and the lifecycle filter. A GM is unchanged, because `discover_all` lists every current member as today. In both cases `member_count` counts what is listed.

**Where the exception applies: one place.** `GET /campaigns/{campaign_id}/parties/{party_id}/roster` (`get_party_roster_endpoint`, [api/parties.py:134-178](../src/dnd_ai/api/parties.py#L134-L178)). Every other reader of party membership was checked at `a9ec4c4`:

| Reader | Audience today | After A3b |
|---|---|---|
| `GET …/parties/{party_id}/members` ([api/parties.py:363](../src/dnd_ai/api/parties.py#L363)) | `canon.edit` | Unchanged; not the exception |
| `GET …/parties/{party_id}/inventory` ([api/item_authoring.py:540](../src/dnd_ai/api/item_authoring.py#L540)) | `canon.edit` | Unchanged; not the exception |
| Party list and detail (`_json`, [api/parties.py:93](../src/dnd_ai/api/parties.py#L93)) | `campaign.view`; no members | Unchanged |
| Bootstrap `authorized_parties` ([queries/bootstrap.py:427](../src/dnd_ai/queries/bootstrap.py#L427)) and the Knowledge perspective ([api/knowledge.py:482](../src/dnd_ai/api/knowledge.py#L482)) | Parties of the caller's own `view_knowledge` characters; no other members | Unchanged |
| `resolve_party_perspective` ([api/access.py:348](../src/dnd_ai/api/access.py#L348)) | Authorizes a perspective, names no one | Unchanged |
| Session roster ([api/sessions.py:184](../src/dnd_ai/api/sessions.py#L184)) | Session participants, through the bundle | Shared discovery only; the exception does not apply |

**Keeping it from becoming general discovery.**

- **Contained in one place.** The rule is one function, `party_roster_controller_qualifies(connection, access, *, party_id, membership_clock)`, in `api/parties.py`. A structural test fails if anything other than `get_party_roster_endpoint` references it.
- **Nothing fed back.** The roster's member set is never written to, or read into, `AccessContext`, `CharacterVisibility`, `WorldEntityVisibility`, `discoverable_entity_ids` or any cache.
- **Response shape fixed.** It stays `{character_id, character_name}` per member. A structural test pins the key set, so a summary, link or tier flag cannot be added without changing the test.
- **No capability.** The exception confers none. `has_capability` and the effective-access explanation never mention it. The explanation shows nothing for it, because it is a fact about the party, not an access source.
- **Regression.** A qualifying player who sees party-mate M on the roster is shown to get, for M:
  - absence from world search, counts and pagination, relationships, organization members, event explanations, encounters, Knowledge subjects and the session roster (unless discoverable otherwise);
  - 404 from M's detail, sheet and public profile;
  - `none` inventory;
  - nothing from preview as that player.

### 10.14 Who reads a released profile (D11, approved; applied by A4)

The latest release of X in the route campaign is readable when **all** of these hold:

- the caller is not under a whole-character `campaign.view` deny on X;
- the caller holds no `character.view_public_profile` deny on X (D12: honoured if present, not creatable);
- either `has_capability("character.view_public_profile", character_id=X)` holds (a revelation), **or** one of `character.view_summary`, `character.view_full` or `canon.edit` holds for X.

A `view_public_profile` deny blocks the released profile on every path, because it is the operation-specific deny for this operation. It does not remove a summary or full tier the caller holds otherwise.

Bare `character.discover` from a relationship or grant does not qualify, because publication is not revelation. Neither does the D4-C roster exception.

Revelation-only readers get the public tier, with the summary from §10.12. Readers with summary access or better see their existing tier and, in addition, a `public_profile` section holding the latest release.

### 10.15 The approved decisions, as §10 applies them (recorded 2026-11-07, from conversation)

| Decision | Approved | Applied in |
|---|---|---|
| **D4-C** | Current-campaign party controllers see their party's roster, subject to explicit character denies. Roster visibility only: no profile, inventory or wider discovery | §10.13 |
| **D5-c** | The canonical name remains the live identity label. Revelation-only readers receive a deliberately released summary. Search does not match their unreleased canonical summary | §10.12 |
| **D9** | The proposed lifecycle, D9-a to D9-g, including D9-a's candidate-statement cutoff (approved 2026-11-08, §10.4) | §10.2, §10.4, §10.5 |
| **D10** | Shared discovery across consumers, keeping each consumer's other audience and field restrictions: reader-visible relationship edges, public organization memberships, member-readable encounters, event status rules, Knowledge visibility policy, session participant rules. A revelation adds a character to the discoverable set and changes no other condition | §10.6, §10.7 |
| **D11** | Released profiles are readable by revelation holders and by readers with summary access or better, subject to applicable denies | §10.14 |
| **D12** | Honour existing operation-specific denies (`character.discover`, `character.view_public_profile`); creation controls are deferred | §10.2, §10.13, §10.14 |

---

## 11. Prerequisite P3 (before A3a): end the request transaction before the response (DEF-022)

**Designed 2026-11-08 at `c705ee7`, for Sonnet.** The owner made DEF-022's correction a requirement for A3a. It was revised the same day after an independent CHANGES REQUIRED review; the review text is not in the repository, and this revision follows the owner's summary of it. Nothing in the application was changed to produce this section. Its prototypes ran only in a throwaway copy of `c705ee7` outside the repository (design evidence).

**What the review changed.**

- **§11.2 replaces "routes that do not use the request transaction".** That claim was wrong. All eight engine-backed routes also hold a request transaction, opened by their authorization dependency, and keep it open across their engine work, including provider calls.
- **New in the design:**
  - engine-backed routes end that transaction before any engine-side effect (§11.4.3);
  - explicit treatment of serialization, rollback failure, cancellation and an uncertain commit (§11.4.4–§11.4.7);
  - transaction guarantees per route class (§11.5).
- **New tests:** an uncertain-commit test, a deterministic DEF-019 regression kept apart from T8, real-route tests for the engine-backed class, and `uv.lock`.
- **Corrected:** the failure totals of the prototype run (§11.9) and the P2 review record ("P2 implementation and review record").

### 11.1 The request lifecycle at `c705ee7`

Installed and locked: FastAPI 0.141.1, Starlette 1.3.1, SQLAlchemy 2.0.51, psycopg 3.3.4, Uvicorn 0.52.0.

**Order of a request** (`fastapi/routing.py`, `request_response` and the included-router path):

1. Two exit stacks open: `request_stack`, then `function_stack` inside it.
2. Dependencies are solved, app- and router-level ones first. A generator dependency goes on `function_stack` if its `Depends` says `scope="function"`, otherwise on `request_stack`.
3. The handler runs. Its result is validated and serialized into a `Response`, so the body bytes exist.
4. `function_stack` closes.
5. The response is sent.
6. `request_stack` closes.

`get_connection` has no scope, so it closes, and commits, at step 6. That is DEF-022.

**Routers are included lazily.** In this FastAPI version, `include_router` stores 63 `_IncludedRouter` objects rather than copying routes onto the app.

- Each route runs with an effective dependency list: the include chain's dependencies (the app's first), then the route's own.
- `fastapi.routing.iter_route_contexts(app.routes)` enumerates the 343 effective `APIRoute`s with their effective `dependant`. §11.2 and test T13 use it. A walk over `app.routes` alone finds only the 2 routes declared on the app.

**Dependency caching.**

- The cache key is the function, its security scopes and its computed scope (`fastapi/dependencies/models.py`).
- So declarations of `get_connection` with different scopes are separate cache entries, and the generator runs twice. Probe M1 shows two instances, `a is b` false.

**Exception paths.**

- **Sync generator dependencies:** FastAPI's `contextmanager_in_threadpool` runs a sync generator's exit only for `except Exception`.
  - A cancellation (`asyncio.CancelledError`, a `BaseException`) skips `get_connection`'s exit.
  - Its rollback and close then happen only when the suspended generator is finalized.
  - In CPython that was immediate in probe CX1 (reference counting, even with the cyclic collector off). It is not a guaranteed path, and it runs a blocking rollback on the event-loop thread.
- **Async generator dependencies** receive every exception at their `yield`, including a cancellation.

**Middlewares** (all ASGI and outside the routing stacks): `NoStoreMiddleware` and `CorrelationIdMiddleware` (both `BaseHTTPMiddleware`) and CORS. They only set headers.

- `BaseHTTPMiddleware` runs the inner app as a task and cancels it only if its own response path raises.
- The credible sources of cancellation are a server shutdown with a timeout, and an outer middleware failure.
- An ordinary client disconnect does not cancel a running handler. Uvicorn records it and ignores later sends.

**Responses.** No module in `src/dnd_ai/api` returns `StreamingResponse`, `FileResponse` or a server-sent-event stream, uses `BackgroundTasks`, or has a WebSocket route.

**Error mapping** (`src/dnd_ai/api/errors.py`):

- `IntegrityError` by SQLSTATE: 23505 and 23P01 give 409; 23502, 23503, 23514 and 23001 give 400; anything else gives the fixed 500 `internal_error`.
- `OperationalError`, which covers 40P01, 40001 and a lost connection, gives 500.
- `ApiError`, `ValueError` and request validation keep their own handlers.

### 11.2 Routes by dependency graph and transaction ownership

Each of the 343 effective routes of `create_app()` was classified by walking its full effective dependency graph (`iter_route_contexts`; script `classify_routes.py`).

| Class | Routes | Transactions |
|---|---:|---|
| **R:** request transaction only | 333 (322 through the authentication dependency) | One request transaction. Authorization (`get_authenticated_user_id`, `require_campaign_capability`, `world_access`, the public-profile pre-checks), the reservation, the command, the audit row and the receipt all share it |
| **A+E:** authorization request transaction plus engine-owned transactions | 8, listed below | The request transaction carries authentication and authorization only. The command opens its own transactions on the engine |
| **E:** engine only | 1 (`readyz`) | One `SELECT 1` on its own connection |
| **N:** no database | 1 (`healthz`) | none |

**The authorization transaction writes for cookie sessions.** `resolve_local_session_principal`, called by `get_authenticated_user_id` for a `__Host-dnd_ai_session` cookie, updates `security.browser_sessions` (idle expiry and `last_used_at`) in the request transaction. For a portal request, that row stays locked until the request transaction ends. A bearer or Foundry principal reads only.

**The eight A+E routes.** At HEAD the request transaction stays open, idle in transaction and holding a pooled connection, while the command runs. It commits after the response. Probe AE1 at HEAD, during the provider call: one application session idle in transaction, and one connection checked out.

| Route | Engine-side transactions | External call | Retry contract (unchanged) |
|---|---|---|---|
| `ai_npc.request_npc_conversation_turn_endpoint` | T1 locks the assignment and records the request and context. T2 records the output and proposal | `provider.generate_npc_turn`, between T1 and T2, outside any engine transaction | Not keyed. Each call is a new context request. A provider or T2 failure after T1 leaves the request row (probe AE3) |
| `ai_npc.review_proposed_change_endpoint` | one | none | Not keyed. The pending-proposal lock makes a second review refuse |
| `ai_synthesis.request_campaign_synthesis_endpoint` | T1 and T2, as for the NPC turn. Its party-perspective authorization read uses the request connection first | `provider.generate_synthesis`, between T1 and T2 | Not keyed, as for the NPC turn |
| `integration.apply_foundry_combat_sync_endpoint` | three transactions on a dedicated connection, under a session advisory lock (`commands/integration.py`) | none | Exactly once per `external_operation_id`; a retry returns the recorded outcome |
| `reference_corpus.ingest_reference_passages_endpoint`, `grant_source_to_campaign_endpoint`, `revoke_source_campaign_grant_endpoint`, `retrieve_cited_passages_endpoint` | one each | none | Not keyed. Each is a single transaction |

**Intended mid-request commits in class R** (unchanged): `local_auth._record_failed_login` commits the failed-login audit row, and `preview` commits a refused preview's audit row. In both, the route then raises, so the request ends on the rollback path.

### 11.3 The defect and the corrections, probed

All probes ran on the test suite's per-run disposable database.

- **The route is real:** `POST /campaigns/{c}/memberships/{m}/end` through `TestClient`, with its real pre-check, P2 key lock, reservation, command, audit and receipt.
- **The observer:** an ASGI wrapper outside the application reads the database from another connection at `http.response.start`.
- **Commit-time failures** come from a test-only `DEFERRABLE INITIALLY DEFERRED` trigger on `audit.change_log`, keyed by correlation id.
- **The application pool** has one connection.
- **The trees:** "HEAD" is `c705ee7`. "FIX" is prototype v2 (§11.4). Prototype v1, the earlier draft, gave the same results in every row it ran.

| # | Case | HEAD | FIX | Final state (both) |
|---|---|---|---|---|
| V1 | Keyed end of N | 200. At response start nothing is visible and **the key lock is held** | 200. At response start N is ended, the audit row and receipt are visible, and the key lock is free | N ended; audit ×1; receipt ×1 |
| D1 | Keyed end of N; COMMIT fails with 23000 | **200** | 500 `internal_error`; key lock free at response start | nothing persisted |
| D1 retry, replay | The same key and body, twice | 200, then a replay | 200, then a replay; key lock free at each response start | N ended; audit ×1; receipt ×1 |
| D2 | Unkeyed end; COMMIT fails with 40P01 | **200** | 500 | nothing persisted |
| C1 | Unkeyed end of A; the real retention trigger fails at COMMIT | **200** | 500 | A open; no audit |
| R1 | Handler error after the reservation (400) | 400; key lock free | identical | nothing persisted; the same key then succeeds |
| E1 | 404, 200, 409 | identical | identical | one receipt |
| **U1** | Keyed end of N. COMMIT succeeds on PostgreSQL, then the acknowledgement is lost (the `_commit` seam commits, invalidates the connection and raises `OperationalError`) | not runnable at HEAD (no seam) | **500 `internal_error`.** At response start: committed, and the key lock free. **The same-key retry is 200 with a body equal to the stored receipt,** and adds no audit row and no receipt | N ended; audit ×1; receipt ×1 |
| **RB1** | Handler error (400) and the rollback itself fails (seam) | not runnable | **400**, the original error. The connection is invalidated; at response start the key lock is free and no application session remains | nothing persisted; pool empty |
| **S1** | A route writes, then its `response_model` validation fails | 500 | 500 | nothing persisted |
| **CX1** | The request is cancelled while its handler is blocked; then released | cleaned up immediately (key lock free, nothing persisted), by finalization of the suspended generator, with the cyclic GC disabled | cleaned up immediately through the commit dependency: the rollback seam is called once and the `get_connection` backstop never logs | nothing persisted; pool empty |
| **L1–L4** (amendment) | **Mocked lifecycle ordering.** `commit_request_transaction` driven directly, with a fake connection, the `_commit` or `_rollback` seam held at a worker-thread barrier, and the cancellation delivered while the barrier is held | not runnable | **L1** (COMMIT): commit-enter, cancel delivered, still not closed, commit-exit, close; the cancellation is caught by the request's scope. **L2** (ROLLBACK after `ValueError`): rollback-enter, cancel delivered, still not closed, rollback-exit, close; the same `ValueError` object escapes. **L3** (rollback fails after `ValueError`): rollback-enter, rollback-exit, invalidate, close; the same `ValueError` escapes; one log line naming only `OperationalError`. **L4** (rollback fails after a cancellation): cancel, rollback, invalidate, close; the cancellation is caught, and no `OperationalError` escapes | — |
| **B1** (amendment) | **PostgreSQL:** keyed end of N, the cancellation delivered while COMMIT is held in the worker thread | not runnable | While held: the request connection not closed, 1 checked out, no pool check-in, the session idle in transaction, the key lock held. After release: commit-exit, then check-in, then the request task ends; **no message sent**; the key lock free | **committed**: N ended, audit ×1, receipt ×1. A same-key retry gets 200 with the stored body; still ×1 |
| **B2** (amendment) | **PostgreSQL:** keyed end of B with A finite (handler 400 after the reservation), the cancellation delivered while ROLLBACK is held | not runnable | While held: as B1. After release: rollback-exit, then check-in; **no message sent** (the 400 is not sent); the key lock free | nothing persisted |
| **B3** (amendment) | **PostgreSQL:** the handler blocked on a held row and cancelled, then released; ROLLBACK held | not runnable | While held: as B1. After release: rollback-exit, then check-in; no message sent; the key lock free | nothing persisted |
| **B4** (amendment) | **PostgreSQL:** as B3, with the rollback seam raising | not runnable | rollback-exit, pool `invalidate`, then check-in; the cancellation caught; no other exception; no message sent; **no application session left**; the key lock free; one log line naming only `OperationalError` | nothing persisted |
| **B5** (amendment) | **PostgreSQL:** handler 400, then the rollback seam raises (no cancellation) | not runnable | **400**, the original; pool `invalidate`, then check-in; no application session left; the key lock free; the log line as B4 | nothing persisted |
| **AE1** | NPC turn: state during the provider call | **1 session idle in transaction; 1 connection checked out** | no request session; 0 checked out | request and output rows ×1 |
| **AE2** | NPC turn: the authorization transaction's commit fails (seam) | not runnable | 500. **The provider is not called; no engine row** | nothing persisted |
| **AE3** | NPC turn: the provider raises after T1 committed | 500 | 500 | the T1 request row persists; no output |
| **P2DK** | P2's different-key test (two keyed ends by one owner; DEF-019 K1). 3 runs at HEAD, 3 on v1, 5 on v2 | `(200, 200)`, but the second **persists nothing** | `(200, 500)`. In every run the second waited at COMMIT before the hold was released, was the victim, and persisted no end, audit or receipt. One deadlock per run | player ended; O2 open; one receipt |

### 11.4 The design

#### 11.4.1 One app-wide dependency, not a scope per declaration

- `create_app` passes `dependencies=[Depends(commit_request_transaction, scope="function")]`. FastAPI puts it first in every route's effective list, including routes on included routers (343 of 343 in the prototype).
- It exits after serialization and before the response is sent.
- `get_connection` keeps its default scope at all 174 declarations. There is one cache entry and one connection per request, as today, and no route signature in class R changes.
- **A per-declaration `scope="function"` is rejected.** One missed or new declaration splits authorization and the write into two transactions (M1).

#### 11.4.2 Components (`src/dnd_ai/api/deps.py`)

- **`_RequestTransaction`:** a slot holding the connection and an `ended` flag, kept on `request.state` under one private name.
- **`_commit(connection)` and `_rollback(connection)`:** the only COMMIT and ROLLBACK of a request transaction. They are module-level so the uncertain-commit and rollback-failure tests can replace them. Production behaviour is the plain call.
- **`_discard(connection)`:**
  1. If a transaction is open, it calls `_rollback`.
  2. If that raises, it logs the exception class and invalidates the connection. The pool drops it, and PostgreSQL aborts the transaction when the session ends.
  3. It closes the connection.

  It never raises, so the original error is the one mapped.
- **`_finish(slot, commit)`:**
  - It runs once; a second call is a no-op.
  - **To commit:** it calls `_commit`, then closes. If the commit raises, it discards and re-raises.
  - **Otherwise:** it discards.
- **`commit_request_transaction(request)`** is an **async** generator. It puts an empty slot on `request.state` and yields.
  - **On a normal exit** it runs `_finish(commit=True)`.
  - **On any exception, cancellation included,** it runs `_finish(commit=False)` and re-raises.
  - Both run in a worker thread (`anyio.to_thread.run_sync`) inside a shielded cancel scope. So the blocking call never runs on the event loop, and a cancellation cannot abandon a COMMIT or ROLLBACK half done.
  - **After a successful commit,** it calls `anyio.lowlevel.checkpoint_if_cancelled()`.
    - A cancellation delivered while the shielded COMMIT ran therefore surfaces from the dependency itself, before the response stage.
    - Without it, the pending cancellation surfaced only at Starlette's later send, by accident of its internals (probe L1, amendment of 2026-11-08).
  - **On the exception path it adds no checkpoint.** The original exception is re-raised unchanged, and a pending cancellation then stops the response at the next checkpoint (L2, B2).
- **`end_request_transaction(request)`:** for class A+E only (§11.4.3). It runs `_finish(commit=True)` now, in the handler's thread, and closes the request connection. A commit failure raises from that call, so it is mapped as usual.
- **`get_connection(request, engine)`:**
  - It refuses (`RequestTransactionError`, mapped to 500, before any statement) when the slot is missing, or when the request already opened a connection.
  - It opens, begins, registers and yields.
  - Its exit is a backstop only: if the slot is not ended, it logs an error and discards. This is unreachable while the commit dependency is installed (CX1).
  - The signature gains `request: Request`. Every declaration, alias and `dependency_overrides[get_connection]` is unchanged.

**`app.py`:** the one argument above.

#### 11.4.3 Engine-backed routes: end the authorization transaction before engine-side effects

Each of the eight A+E handlers gains `request: Request` and calls `end_request_transaction(request)`:

- after its last use of the request connection or the `AccessContext`, which is authorization;
- before its first engine call.

Placement:

- **`ai_npc` turn:** after the `character.interact` check, before `_world_id` and the command.
- **`ai_npc` review:** before `review_proposed_change`.
- **`ai_synthesis`:** after the tier checks and `resolve_party_perspective`, which reads through the request connection, before the command.
- **combat sync:** after `assert_foundry_system_matches`.
- **The four reference-corpus routes:** before their command.

**Options evaluated:**

- **(a) Commit the authorization transaction with everything else, before the response** (the first P3 draft).
  - The request transaction stays open across the provider call (AE1 at HEAD).
  - For a cookie session, it keeps `security.browser_sessions` locked for the whole call, so the same browser session's other requests wait behind the provider.
  - If that late commit failed after the engine work had committed, a completed operation would answer 500.
  - Rejected.
- **(b) End it before the engine-side effects. Chosen.**
  - Authorization is decided exactly as today: the same dependency on the same snapshot, plus the handler's own checks. The engine transactions never shared that snapshot or held its locks, so nothing is weakened.
  - No database transaction is open during a provider call: the request transaction is ended, and the commands already close T1 before calling the provider.
  - A failure of the authorization commit precedes every engine-side effect (AE2).
- **(c) Give engine-backed routes an authorization dependency on its own short connection.** It changes the shared `require_campaign_capability` for 8 of 343 routes. Rejected as larger than needed.

**Behaviour change, stated:** for a cookie session on an A+E route, the session's idle-window extension commits once authorization succeeds, even if the engine work then fails. At HEAD a failed request rolled it back. The extension records activity, not an operation; no retry contract depends on it.

**After `end_request_transaction`,** the request connection is closed, and any later use of it raises and maps to 500. The commit dependency's exit is then a no-op. The combat-sync route's docstring note about holding "two separate pooled connections briefly" becomes untrue and is corrected.

#### 11.4.4 Serialization

- FastAPI validates and serializes the handler's result at step 3, before the commit dependency exits.
- A serialization or response-validation failure is therefore an exception on the rollback path. It gets 500 and commits nothing (S1).
- After the commit, only the header-setting middlewares run.
- For A+E routes, a serialization failure can follow committed engine work (§11.5).

#### 11.4.5 Rollback failure

`_discard` keeps the original exception, invalidates the connection, and relies on PostgreSQL aborting the transaction when its session ends. Locks, including the key lock, are released then (RB1).

The only residual case is a network partition in which the server has not yet seen the disconnect. The locks then last until it does. That is outside the application's control and is unchanged.

#### 11.4.6 Cancellation

- **Before the commit starts:** the commit dependency receives the cancellation, discards in a shielded worker thread, and re-raises. Nothing commits and the key lock is released (CX1). This does not depend on generator finalization or the garbage collector.
- **During the handler's threadpool call:** the call is not abandonable, so the handler finishes its statements first. The commit dependency then discards them (CX1, B3).
- **While COMMIT is running in the worker thread:**
  1. The shield keeps the COMMIT running to completion.
  2. `_finish` closes the connection, returning it to the pool, only after the COMMIT has returned.
  3. Then `checkpoint_if_cancelled()` raises the cancellation, and no response is sent.

  The transaction has committed, and its locks, P2's key lock included, are released by that commit. This is the uncertain case of §11.4.7: a same-key retry replays the stored receipt (B1).
- **While ROLLBACK is running after a handler exception:**
  1. The shield keeps the ROLLBACK running to completion.
  2. The close follows it.
  3. The handler's original exception is re-raised unchanged.
  4. The pending cancellation stops the response at the next checkpoint, so no error response is sent either.

  Nothing persists, and the locks are released by the rollback (L2, B2).
- **While ROLLBACK is running after a cancellation:** the same, with the cancellation as the propagating exception (B3).
- **Rollback failure, after a handler exception or after a cancellation:**
  - `_discard` logs the failure by exception class, invalidates the connection, then closes it. PostgreSQL aborts the transaction and releases its locks when the session ends.
  - The propagating exception is unchanged: the handler's exception (L3, B5, RB1) or the cancellation (L4, B4).
  - The cleanup failure never replaces it.

#### 11.4.7 Uncertain commit

A COMMIT whose acknowledgement is lost raises `OperationalError`, which maps to 500. The transaction may have committed.

- **For a keyed request,** the receipt and the mutation committed together, and P2's key lock was released by the commit. A same-key retry replays the stored response and adds no mutation or audit row (U1).
- **An unkeyed request** has no such protection, as today.

### 11.5 Transaction guarantees

**Class R (333 routes).**

- **Rollback is guaranteed. Nothing of the request transaction persists** for:
  - any exception raised before the COMMIT starts: dependency and authorization errors, handler and command errors, serialization and response-validation errors, and a cancellation before the commit;
  - a COMMIT that PostgreSQL answers with an error: a deferred trigger, 40P01 or 40001 at commit, or any other error reply.

  The client gets the mapping in §11.1.
- **A failed rollback** keeps that guarantee through server-side abort at disconnect (§11.4.5).
- **Exceptions by design:** the two audit commits in §11.2, which persist before their route raises.
- **Non-success can follow a committed transaction only when:**
  1. the COMMIT's acknowledgement is lost (500; U1);
  2. a cancellation arrives during the COMMIT (committed, no response);
  3. the response is lost in transport after a successful commit.

  In each, a keyed retry replays; an unkeyed retry may repeat the write.
- **A 2xx is sent only after the commit has succeeded.** At that moment the writes, audit row and receipt are visible to other connections, and the key lock is released.

**Class A+E (8 routes).**

- **Phase 1, the authorization transaction,** ends at `end_request_transaction`. Any failure up to and including its commit is non-success with no engine-side effect (AE2).
- **Phase 2, the engine transactions,** each commit on their own. A failure after the first of them can follow committed engine effects:
  - the AI routes' T1 request row (AE3);
  - combat sync's committed steps, under its `external_operation_id` contract;
  - for the single-transaction routes, only a serialization failure after the commit.

  These outcomes are the commands' existing contracts and are unchanged.
- **No transaction is held across a provider call.**

**Class E and N:** no request transaction.

### 11.6 Contract

**Changes:**

1. **A 2xx means committed.** For class R, the writes, audit row and receipt are visible, and the key lock is released, before the response is sent.
2. **A commit-time failure gets the response the same exception would get in the handler.** It is never a 2xx.
3. **An uncertain commit gets a 500** and may have committed. A keyed retry resolves it.
4. **A+E only:** the authorization transaction commits before the engine work. A cookie session's idle extension then persists even when the operation fails (§11.4.3).

**Unchanged:**

- the error envelope, codes and messages;
- authorization decisions, and the replay, conflict and key scope;
- P2's lock order;
- the commands' own retry contracts (§11.2);
- the two audit commits;
- harnesses that override `get_connection`: the commit dependency finds no registered connection and does nothing.

### 11.7 Affected code, routes and toolchain

- **`deps.py`** (§11.4.2) and **`app.py`** (one argument).
- **The 8 A+E handlers:** `request: Request` and one call each (§11.4.3). These are the only route signatures that change. The `integration` module docstring is corrected.
- **Behaviour only:** the 333 class R routes, through the app-wide dependency. None changes its source.
- **Toolchain:**
  - `pyproject.toml`: `fastapi>=0.109.0` becomes `fastapi>=0.141.1`. The old floor predates `Depends(scope=...)` and the lazy-include behaviour this design was verified against.
  - `uv.lock` changes in exactly one line, the project's `[package.metadata] requires-dist` entry, `{ name = "fastapi", specifier = ">=0.141.1" }`.
  - **Verified in the throwaway copy:**
    - `uv lock --check` passes at HEAD;
    - after the `pyproject.toml` change, it fails ("needs to be updated");
    - `uv lock` (uv 0.11.32) changes only that line, with no package version changed;
    - `uv lock --check` then passes.
  - The implementation commits both files, and the check is part of acceptance.
- **Docs:**
  - SYSTEM_ARCHITECTURE §7: its diagram already shows `Commit` before `Response`; add the mechanism, and the A+E split.
  - SYSTEM_ARCHITECTURE §20: commit-time and uncertain-commit failures.
  - DATABASE_CONVENTIONS §26.4: the receipt is visible and the key lock released before the response; an uncertain commit is resolved by a keyed retry.
  - The `deps.py`, `idempotency.py` and `integration.py` docstrings.

### 11.8 Tests (P3 acceptance)

These are HTTP tests on `create_app()` with the real `get_connection` and real request transactions, unless marked as unit tests. Every HTTP test asserts persisted state as well as the response.

- **Commit-time failures** use a test-only deferred trigger in the per-run database, created and dropped by a fixture and keyed by correlation id.
- **Response-start state** is observed by an outermost ASGI wrapper reading through a separate connection.
- **Seams:** tests replace only `_commit` and `_rollback`.

| # | Covers | Test |
|---|---|---|
| T1 | A commit failure: non-success, nothing persisted | A keyed end of N, its COMMIT failing per SQLSTATE: 23000 → 500, 23505 → 409, 23514 → 400, 40P01 → 500. At response start and after: N open, its roles live, no end audit row, no receipt. Also unkeyed 40P01, and the real retention-trigger race (C1) |
| T2 | Visible before the response | A keyed end of N, and a keyed role revoke (through `require_campaign_capability`). At `http.response.start`, another connection sees the mutation, one audit row for the correlation id, and the completed receipt with the response's status and body |
| T3 | Safe retry after a failure | After T1's 23000 case, the same key and body: 200, one mutation, audit row and receipt; a further retry replays with no new audit row. After a handler rollback (R1), the same key on another target succeeds once |
| T4 | P2 lock release | At response start the key lock is absent from `pg_locks` after a commit (T2), a handler rollback (R1), a commit failure (T1) and an uncertain commit (T10). A same-key request sent just after a 2xx is not seen waiting on the advisory lock |
| T5 | Error mapping and cleanup | `test_api_deps.py` unchanged, plus a commit-failure case. `test_api_integrity_errors.py` and the envelope tests unchanged. With a one-connection pool: nothing is checked out and the next request succeeds after a success, a handler error, a commit failure, a rollback failure and a failed login. Failed-login and refused-preview audit rows persist (`test_api_local_auth.py`, `test_api_preview.py`, unchanged) |
| T6 | Serialization (S1) | A test route writes, then fails `response_model` validation: 500, nothing persisted, the connection returned |
| T7 | Rollback failure after a handler exception (RB1, B5; real PostgreSQL) | `_rollback` raises after a handler error on a keyed end. Asserts: the original 400 and envelope; the pool `invalidate` event precedes the `checkin` event; at response start the key lock is free and no application session remains (the invalidated session ended, so PostgreSQL rolled back); nothing persisted; pool empty; one error log line naming the exception class only, with no message text. The ordering and exception-identity part is covered without a database in T11b |
| T8 | P2's independent-key test | Keep `test_a_different_key_takes_its_own_key_lock_without_queueing_behind_a_held_request`: the second key's lock is granted at once, never queued. Replace its second request with a keyed request on a route whose commit takes no campaign `FOR UPDATE`, chosen by trace, so the two share no row lock. Assert both responses and both persisted mutations, audit rows and receipts |
| T9 | **DEF-019 two-ends regression, deterministic** (separate from T8) | Two keyed ends by the same owner, different keys, on the player's and O2's memberships. The first is held at the player's membership row. The test waits until `pg_blocking_pids` shows the second waiting at COMMIT behind the first, and only then releases. Asserts: exactly one 2xx; `pg_stat_database.deadlocks` rose by one; for the non-2xx request, whichever PostgreSQL chose as victim, no end, no audit row and **no receipt** for its key; for the other, all three persisted. The victim was the second in 5/5 prototype runs, but the assertions do not depend on which. When DEF-019 is fixed, this test changes with it |
| T10 | **Uncertain commit** (U1) | `_commit` is replaced so PostgreSQL commits, then the connection is invalidated and `OperationalError` raised. The keyed end gets 500 `internal_error`. At response start the key lock is free, and the mutation, audit row and receipt are committed. A same-key retry with the real `_commit` gets 200 with a body equal to the stored receipt; there is still one mutation, one audit row and one receipt, and no key lock afterwards |
| T11a | Cancellation during the handler (CX1; kept as its own test) | The ASGI app is called directly under anyio, with the cyclic GC disabled. A keyed end is blocked on a held row, the request's cancel scope is cancelled, then the row is released. Asserts: no response sent; key lock free, nothing persisted and no application session idle in transaction, checked without running the garbage collector; `_rollback` called once by the commit dependency; the `get_connection` backstop never logs. No seam is held: this covers the handler-phase path, which T11b and T11c do not |
| T11b | **Mocked lifecycle ordering, no database** (L1–L4) | `commit_request_transaction` is driven directly through `contextlib.asynccontextmanager` under anyio, with a fake request (`state` only) and a fake connection placed in its slot, using the barrier protocol below. Cases, each asserting the recorded event order and what escapes the request's cancel scope: **(1)** COMMIT held, then cancelled: `commit-enter`, cancel delivered, still not closed, `commit-exit`, `close`; the scope reports the cancellation caught; nothing else escapes. **(2)** ROLLBACK held after the handler raises a `ValueError`, then cancelled: `rollback-enter`, cancel delivered, still not closed, `rollback-exit`, `close`; the escaping exception **is** the handler's `ValueError` object (identity, not type). **(3)** The rollback raises after a `ValueError`: `rollback-enter`, `rollback-exit`, `invalidate`, `close`; the same `ValueError` object escapes; exactly one error log record, naming `OperationalError` and no message text. **(4)** The rollback raises after a cancellation delivered while the handler awaits: cancel, `rollback-enter`, `rollback-exit`, `invalidate`, `close`; the cancellation is caught by the scope and no `OperationalError` escapes; the same log record. These tests prove ordering and exception preservation only. They make no claim about PostgreSQL |
| T11c | **Real PostgreSQL, operation in flight** (B1–B4) | The real membership-end route on `create_app()`, called directly under anyio, with a one-connection application pool instrumented by SQLAlchemy events (`engine_connect` to capture the request `Connection`; pool `checkin` and `invalidate`). The barrier protocol below holds `_commit` or `_rollback` in the worker thread. Cases: **(1)** COMMIT held on a keyed end of N, cancelled while held. **(2)** ROLLBACK held after the handler's 400 (A finite, ending B), cancelled while held. **(3)** The handler blocked on a held row and cancelled; the row released; ROLLBACK held. **(4)** As (3) with the rollback raising. While held, every case asserts from a separate connection: the captured `Connection.closed` is false, `pool.checkedout() == 1`, no `checkin` event yet, the request's backend is `idle in transaction`, and P2's key lock is still granted to it in `pg_locks`. After release: the operation's exit event precedes the `checkin` event; in (4), `invalidate` precedes `checkin`; the request task ends after both; no ASGI message was sent (neither `http.response.start` nor a body); the key lock is absent; no application session idle in transaction. Outcomes: (1) N ended, one audit row and one receipt, and a same-key retry gets 200 with a body equal to the stored receipt, adding no row; (2)–(4) nothing persisted. (4) also has no application session left, and one error log record naming only the exception class |
| T12 | **Engine-backed routes, on the real routes** | **(a)** An NPC turn with a **cookie session** and an observing fake provider. During the provider call: no request session idle in transaction; no connection checked out for the request; and an `UPDATE` of that `security.browser_sessions` row from another connection completes under `lock_timeout = '1s'`. **(b)** The same with the authorization commit failing (`_commit` seam): 500, provider not called, no `ai.context_requests` row. **(c)** The provider raising: 500, the T1 request row persists with no output (existing contract pinned). **(d)** Synthesis at `player_summary`: the party-perspective read happens before the end; then the same observation as (a). **(e)** A reference-corpus grant whose engine transaction fails (a duplicate grant): mapped error, no grant row, with the authorization transaction already ended. **(f)** Combat sync: the same `external_operation_id` sent twice gives one applied outcome, and the request connection is closed before the command's lock connection is opened |
| T13 | Wiring (unit) | Over `iter_route_contexts(create_app().routes)`: every `APIRoute`'s first effective dependency is `commit_request_transaction` with `scope="function"`; every dependant resolving `get_connection` uses the default scope and the cache. The set of routes whose graph has both `get_connection` and a direct `get_engine` equals the eight A+E routes, and each of their endpoints calls `end_request_transaction` before any name bound to the engine (by syntax tree). `get_connection` is the only sync generator dependency in `dnd_ai.api`. No `dnd_ai.api` module uses `BackgroundTasks`, `StreamingResponse`, `FileResponse` or server-sent events, which is a tripwire |
| T14 | Guards | An app without the commit dependency gets 500 on its first `get_connection` request, with no statement run. A second request connection in one request is refused |
| T15 | FastAPI and anyio behaviour P3 relies on (unit, no database) | Pure FastAPI and anyio checks, so an upgrade that changes them fails here first: **(1)** a function-scoped generator dependency exits before `http.response.start`, and a request-scoped one after it; **(2)** an async generator dependency receives a cancellation at its `yield`; **(3)** a sync generator dependency's exit is **not** run for a cancellation (`contextmanager_in_threadpool` handles `Exception` only), which documents why the commit dependency is async; **(4)** `anyio.to_thread.run_sync` inside `CancelScope(shield=True)` runs to completion when the enclosing scope is cancelled mid-call (held by a barrier), and `anyio.lowlevel.checkpoint_if_cancelled()` afterwards raises the pending cancellation |
| T16 | Lockfile | `uv lock --check` passes with the new floor |

**The barrier protocol (T11b, T11c, T15 part 4).**

1. **Observe operation entry.**
   - The test replaces the seam (`_commit` or `_rollback`) with a wrapper.
   - The wrapper appends `<op>-enter` to a lock-protected event list and sets a `threading.Event` (`entered`).
   - It then waits on a second `threading.Event` (`release`) with a bounded timeout, and only then calls the real operation.
   - It appends `<op>-exit` in a `finally`.
   - On a timeout it records the timeout and raises. It never runs the operation unreleased.

   The test waits for `entered` from the event loop with `anyio.to_thread.run_sync(entered.wait, timeout)` and fails if the wait times out. This proves the COMMIT or ROLLBACK is executing in the worker thread, not merely scheduled.
2. **Deliver the cancellation.**
   - The request runs as a task inside its own `anyio.CancelScope`, and the test calls `scope.cancel()` while `entered` is set and `release` is not.
   - For T11c (3) and (4), the cancellation is delivered earlier, while the handler is blocked on a held row (proved through `pg_blocking_pids`). The row is then released so the handler returns and the ROLLBACK starts.
3. **Hold the operation in flight.** `release` stays unset while the test observes. A short settle period (0.2–0.3 s) is allowed after the cancellation, so an implementation that wrongly closed or returned the connection on cancellation would have done so before the observation.
4. **Prove close and pool return have not occurred** (T11c):
   - the captured `Connection.closed` is false;
   - `pool.checkedout()` is 1;
   - no pool `checkin` event has been recorded;
   - `pg_stat_activity` shows the request's backend `idle in transaction`;
   - `pg_locks` shows P2's key lock granted.

   In T11b, the fake connection's `close` has not been recorded.
5. **Release and assert.**
   - The test sets `release` and lets the request task end.
   - **Order:** `<op>-exit` precedes `close` (T11b) or the pool `checkin` (T11c); `invalidate` precedes both in the rollback-failure cases.
   - **No response:** the ASGI `send` recorder holds no message.
   - **Lock release** (T11c, from a separate connection): the key lock is absent from `pg_locks`, and no application session is idle in transaction.
   - **Which exception escapes:** the handler's original exception object, or the cancellation, as each case states.
6. **Bounded and always cleaned up.**
   - **Every wait is bounded:** entry, blocking, the barrier's own wait, and the whole request under `anyio.fail_after`.
   - **A `finally` always sets `release`,** and releases any held row through `LockRace`, whose context manager commits or rolls back its holds and joins its worker. The request task is joined by its task group, under the same bound.
   - **Teardown disposes the instrumented engines** and removes the seam (pytest `monkeypatch`).
   - A failure therefore leaves no thread waiting on a barrier, no held row, and no open application session for later tests.

**What each layer establishes.**

- **T11b (mocked) establishes lifecycle ordering and exception preservation only.**
- **T11c (real PostgreSQL) establishes the transaction outcome, lock release, connection state and pool return.** Its event order is the same as T11b's, observed on the real connection.
- **T11a stays distinct:** it cancels during the handler, with no seam held, and checks that cleanup does not wait for the garbage collector.

**Rule for P3's review.** An existing test that asserts a 2xx whose transaction did not commit has a wrong expectation. It is corrected to assert the persisted outcome, never by restoring the old commit timing. T8 is the only such test found (§11.9).

### 11.9 Existing tests on the prototypes (design evidence)

The implementation must re-run everything. First runs and reruns are reported separately.

**Prototype v1, `tests/unit`, first run:** 1230 passed.

**Prototype v1, targeted database files, first run:** 357 passed, 1 failed (T8's test).

- The files: `test_api_deps`, `test_api_integrity_errors`, `test_api_local_auth`, `test_api_preview`, `test_idempotency_key_lock`, `test_actor_idempotency`, `test_api_memberships`, `test_api_auth`, `test_api_cors`, `test_api_characters_inventory_only`, `test_api_campaigns`, `test_api_access_grants`, `test_api_encounters`.

**Prototype v1, full `tests/database` and `tests/scenario`, first run, one process, 37.6 minutes:** 5812 passed, 113 failed, 9 errors.

- **The 122 non-passing entries, reconciled from the run's log alone** (`reconcile_failures.py`). Every entry matches one log section, and each is attributed only to the evidence in its section:

  | Entries | Evidence in the section | Attribution |
  |---:|---|---|
  | 67 (58 failed, 9 errors) | An alembic subprocess exited with status 3221225794 (`0xC0000142`). 54 show it as `CalledProcessError` and 13 as an assertion on the exit status | A Windows process-start failure of the test's migration subprocess. Not related to P3 |
  | 40 | `TimeoutError: background worker did not complete its startup handshake within 10.0s` (`test_entity_type_change_protection.py`) | The symptom only. The cause is **not established** by the log |
  | 14 | `test_seed_idempotency.py`: a seed file's hash differs from the one its revision recorded | `git archive` wrote LF seed files where the checkout has CRLF |
  | 1 | `assert (200, 500) == (200, 200)` | T8's test (§11.3, P2DK) |

  The earlier draft of this section said "54 alembic subprocesses", and that everything else was environmental. Both are corrected by this table.
- **Targeted reruns,** kept separate from the first run:
  - the 36 files holding the 67 and the 40 entries, prototype unchanged: **261 passed**;
  - `test_seed_idempotency.py` after copying the checkout's seed files into the throwaway tree: **48 passed**.

  A passing rerun does not establish the cause of the 40 handshake timeouts.

**Prototype v2, full `tests/unit`, `tests/database` and `tests/scenario`, first run, one process, 39.1 minutes:** 7143 passed, 2 failed, 19 errors.

- **Reconciled from the log**, with the same method: 21 entries, each matched to one section.

  | Entries | Evidence | Attribution |
  |---:|---|---|
  | 1 | `assert (200, 500) == (200, 200)` | T8's test, as expected |
  | 19 errors (`tests/unit/test_verify_sh.py`) | `FileNotFoundError` for the session's own `.tmp/pytest-tmp-…` directory, at fixture setup | The directory was removed by another pytest session in the same tree. `tests/conftest.py`'s `_cleanup_stale_pytest_run_dirs` deletes every other run's directory under `.tmp/` at session start, and my probe sessions (CX1 and the first-round probe rerun) started in the prototype tree during this run. This is a harness interaction caused by how the evidence was gathered, not by P3 |
  | 1 (`test_character_reveal_delegation.py::test_a_caller_whose_owner_assignment_expires_during_the_wait_is_refused`) | `AssertionError: no session waited on a lock; finished=True`, with the request already answered 403 | **Unattributed.** The log does not establish why the request did not wait. It is in the A1 lock-wait family whose intermittent failures are already recorded as unresolved (this plan's A1 status) |

- **Targeted rerun,** kept separate, run alone in the tree: `test_verify_sh.py` and `test_character_reveal_delegation.py`, **61 passed**. A passing rerun does not explain the delegation failure.
- **The prototype v2 diff against `c705ee7`** is kept outside the repository with the probes.

**Prototype v2 with the post-commit checkpoint** (amendment, after the full run above). These are targeted runs only; the full suite was not re-run for this one-line change.

- The barrier probes L1–L4 and B1–B5: 9 passed.
- The earlier probe modules (U1, RB1, S1, CX1, AE1–AE3, and the first-round V1–M1): 14 passed, with unchanged outcomes.
- `test_api_deps`, `test_idempotency_key_lock`, `test_api_ai_and_corpus`, `test_api_local_auth`, `test_api_preview` and `test_api_integrity_errors`: 118 passed and 1 failed, the failure being T8's test as expected.

### 11.10 Rejected alternatives

- **`scope="function"` at all 174 declarations.** A missed declaration splits the transaction (M1).
- **An explicit `connection.commit()` at the end of each handler.** That is 343 routes. It commits before serialization, and is easy to omit.
- **An ASGI middleware holding `http.response.start` until teardown.** It bypasses the exception handlers and buffers bodies.
- **A custom `APIRoute` class on 65 routers.** Same mechanism, more surface.
- **A sync commit dependency.** FastAPI skips its exit on a cancellation, so cleanup would depend on finalization.
- **Option (a) and option (c) for the A+E routes** (§11.4.3).
- **Mapping commit-time 40P01 or 40001 to a retryable status.** That is a contract change, left to DEF-019's own design.

### 11.11 P3 scope and acceptance (for Sonnet)

**Parent:** `c705ee7`, or the later head carrying this plan. It is one commit.

**Scope:**

- §11.4: `deps.py`, `app.py` and the eight A+E handlers;
- `pyproject.toml` and `uv.lock`;
- tests T1–T16;
- the docs in §11.7.

**Not in scope:**

- any class R route signature;
- the idempotency stores and P2's lock;
- DEF-019 to DEF-021;
- the error mapping;
- the AI and combat-sync commands themselves.

**Acceptance:**

1. T1–T16 pass, with persisted state asserted.
2. The full suite passes. Any test found to rely on DEF-022 is corrected under §11.8's rule and named in the commit message. First runs and reruns are reported separately; any failure not explained by its own evidence is left unattributed.
3. `ruff format --check`, `ruff check`, `mypy src`, `uv lock --check` and `git diff --check` pass.
4. An independent review names the parent and target SHAs.

A3a depends on P3 (§10.10).

---

## Decisions still needed

- **D1: Public profile scope. Approved by the owner (recorded 2026-11-07).** Public-profile drafts and releases belong to a campaign. Applied in §5.1.
- **D2: Who edits the draft. Approved by the owner (recorded 2026-11-07).**
  - Campaign `canon.edit` holders may edit drafts.
  - A release requires `character.reveal` authority.
  - Copying legacy text requires existing permission to read that text.

  Applied in §5.1, §5.7 and §5.10. D7 asks a follow-on question that D2 does not answer.
- **D3: `access.manage` can create a campaign owner.** **Resolved 2026-11-06 (owner-approved; ownership gate implemented as the first A1 change, see [the A1 design](PHASE14_15_P03A_A1_OWNERSHIP_AUTHORITY_DESIGN_2026-11-06.md) §5).** Original question: Assigning a role, adding a member and transferring ownership are all gated only on `access.manage` ([api/memberships.py:260](../src/dnd_ai/api/memberships.py#L260), [:629](../src/dnd_ai/api/memberships.py#L629)). So a custom `access.manage` holder could give themselves `campaign_owner` and with it direct reveal authority. That contradicts "custom `access.manage` alone confers no release authority."
  - Today this can't happen in practice: only `campaign_owner` holds `access.manage`, and no app path creates custom role capabilities.
  - Closing it means restricting `campaign_owner` assignment to current owners, which changes ADR 0020 transfer behavior.
  - Path trace, recommended gate, exact owner decision and regressions: [PHASE14_15_P03A_A1_OWNERSHIP_AUTHORITY_DESIGN_2026-11-06.md](PHASE14_15_P03A_A1_OWNERSHIP_AUTHORITY_DESIGN_2026-11-06.md).
- **D4: Party roster exception. Approved by the owner (recorded 2026-11-07): D4-C.** Current-campaign party controllers see their party's roster, subject to explicit character denies. This grants roster visibility only, without profile, inventory or wider discovery access. Applied in §10.13. The question as put, for the record:

  **Today.** `GET …/parties/{party_id}/roster` ([api/parties.py:134-178](../src/dnd_ai/api/parties.py#L134-L178)) gives **every** `campaign.view` member every current member's canonical name, for every party in the campaign, not only their own. It leaves out only unpublished definitions and whole-character denies.

  The built-in `player` and `observer` roles hold `campaign.view` alone (migration 086). A player therefore discovers no other character unless a relationship or grant says so. The roster is the only place they see party-mates' names. It also names any NPC the GM puts into a party to the whole campaign, which contradicts "linking into a party is not a revelation".

  - **D4-A, keep the exception (today's behaviour, documented).**
    - **Ordinary party members:** unchanged. They see party-mates' names.
    - **Everyone else:** every other member and observer also sees every party's roster.
    - **Cost:** linking an NPC into a party still names it campaign-wide. A3b changes nothing here.
  - **D4-B, apply the shared discovery policy.** A roster lists a current member only when the caller can discover it (`discoverable_entity_ids` with the bundle), and `member_count` counts only those.
    - **Ordinary party members:** a player sees their own character, which their controller relationship lets them discover, and **no party-mate** until the GM reveals each one. Under D9-d, revealing needs a release, so that is one release and one revelation per character.
    - **Observers:** see only revealed members.
    - **GMs:** unchanged.
    - **Fit:** strictest; one policy, no exception.
  - **D4-C, party-mate exception (recommended).** A caller who currently controls a character that is a current member of this party sees every current member of **this** party.
    - **Controls** means a live `owner`, `primary_controller` or `co_controller` relationship to that character, resolved as `resolve_access_context` resolves relationships. No relationship type confers `character.control` today, so the type codes are the test. After P03-B it means a live, in-effect assignment.
    - **Everyone else** gets D4-B. Whole-character denies and unpublished definitions are still left out.
    - **Ordinary party members:** unchanged for their own party. They no longer see other parties' rosters beyond what they can discover.
    - **Observers:** see only revealed members.
    - **An NPC linked into a party** is named only to that party's controllers.
    - **Scope of the exception:** it covers the roster only. It confers no discovery in search, relationships or any other surface, and no detail tier (the roster's existing "listing grants none").

  **Recommend D4-C.** It keeps what players rely on, closes the campaign-wide naming, and limits the remaining exception to people who are in the party in the fiction. The cost is one more predicate, "controls a current member", shared with nothing else. Each option is a change to A3b only.

- **D5: Names and summaries in discovery cards. Approved by the owner (recorded 2026-11-07): D5-c.** The canonical name remains the live identity label. Revelation-only readers receive a deliberately released summary, and search does not match their unreleased canonical summary. Applied in §10.12. The question as put, for the record:

  **Today.** Every discovery consumer renders `core.entities.canonical_name`. World search cards and the summary tier also render `core.entities.summary`. Both are classified `PUBLIC_WORLD` ([data_classification.py](../src/dnd_ai/domain/data_classification.py)). OD-17 says audiences receive only deliberately released versions.

  The A3 trace (§10.7) shows where each is used:
  - the **name** appears in every surface, and in the search sort key and cursor;
  - the **summary** appears only in world search cards (`WorldEntityCard`) and in the detail tiers.

  - **D5-a, the canonical label (the earlier recommendation).** A release carries no name or summary. The GM read shows the canonical pair read-only as "what audiences will see".
    - **No consumer change**, and search and sort are unchanged.
    - **The cost:** an edit to the canonical summary reaches revealed audiences with no release, and the GM cannot give a revealed character a public alias.
  - **D5-b, a released label everywhere.** Draft and release gain `public_display_name` (required for any release a revelation may use) and `public_summary`.
    - **Who sees it:** a caller whose only discovery path to X is a revelation sees the released label in every consumer. Callers with another path see the canonical one.
    - **What has to change:**
      - every §10.7 consumer computes a per-caller label;
      - search matches the label the caller sees, otherwise a search for the canonical name finds an aliased card;
      - the keyset sort and the cursor change;
      - Foundry and Discord clients follow.
    - **What it cannot fix:** the canonical name still appears in free text (event descriptions, Knowledge statements, session notes). This is the largest option and roughly doubles A3b.
  - **D5-c, canonical name with a released summary (recommended).** The name stays canonical everywhere. Draft and release gain a nullable, authored-only `public_summary`, with no legacy copy and no origin column.
    - **Who sees it:** a caller whose only path to X is a revelation sees the latest release's `public_summary`, or none, in search cards and in A4's public tier, and never the canonical summary. Other callers are unchanged.
    - **What changes:** the column pair in migration 145; the draft save and release snapshot gain the field (an additive change to A2's commands, under A2's existing token and audit rules); one CASE in the search card's select.
    - **Search and sort are unchanged.**

  **Recommend D5-c.** Releases already exist so that prose reaches audiences only deliberately, and the summary is the one piece of prose discovery shows. The name is identity: substituting it cannot be made consistent (D5-b), and it already appears in canon text. The release form shows the canonical name read-only as the name audiences will see. Each option is additive.

- **D6: Species and size in the public tier (new, 2026-11-07).** §3 and the A4 row say the public tier shows no species or size "unless released", but nothing defines how they are released. They are definition inputs, not derived mechanics, so OD-17 does not exclude them.

  **Recommend:** a per-release opt-in, off by default. The draft holds `shows_species` and `shows_size`. When a flag is set, the release snapshots `released_species_id` and `released_size_category` from the definition at release time. Later identity edits then reach audiences only through a new release.

  The alternative is never showing them in the public tier. Either answer is additive to A2a and blocks only A4.
- **D7: Copied legacy text and draft readers. Approved by the owner (recorded 2026-11-07).** The approved policy:
  1. Copying a legacy field requires current permission to read its source.
  2. Before release, copied fields retain that source-read restriction.
  3. A releaser must currently be allowed to read every field included in the release snapshot.
  4. Deliberate release makes the snapshot eligible for the later audience mechanism under its release policy.

  Applied in §9. The points D7 left open, D7-a to D7-f, were approved by the owner in conversation and are recorded in §9.10. Nothing about D7 remains open.

  *The question, as first put (2026-11-07), for the record.* Reading legacy text needs different permissions for each kind of character (§5.10 trace). An NPC's text needs campaign `canon.edit` **and** world `world.canon.read_private`; a player character's needs `canon.edit` only. Drafts are readable by every campaign `canon.edit` holder. So a GM holding `world.canon.read_private` could copy an NPC's background into the draft, and a campaign-only GM could then read world-private text the existing read refuses them. The first recommendation (withhold until released; let a restricted reader replace the field; refuse a release with `world_authority_required`) is superseded by the approved policy and §9: a restricted reader may only clear, a release is refused with `public_profile_field_withheld`, and only a release covering the field's current text lifts the restriction.
- **D8: Draft and release reads, and denies. Approved by the owner (recorded 2026-11-07), as proposed.** Policy, detailed in §5.1 and §5.7a:
  1. **Read.** A member may read the draft and the release snapshots if they hold effective character-scoped `canon.edit`, **or** current `character.reveal` authority. Reveal authority confers reading only, never editing.
  2. **Edit.** Editing requires effective character-scoped `canon.edit`: role `canon.edit`, re-checked under lock, with no whole-character deny and no `canon.edit` deny on the character. A per-character `canon.edit` *allow* grant does not confer editing without role `canon.edit`.
  3. **Release.** Releasing requires `character.reveal` authority, unchanged from D2.
  4. **Whole-character deny.** A whole-character `campaign.view` deny blocks reading, editing and releasing for every source, the owner included (ADR 0021 §2.9).
  5. **`canon.edit` deny on the character.** It blocks editing and removes only the `canon.edit` read path. Reading through reveal authority and releasing are unaffected (§2.9: "An operation-specific deny blocks only that operation").
  6. **No per-character release deny.** None exists, because A1's trigger refuses any resource grant naming `character.reveal`. Adding one is a separate extension.
  7. **D7 is separate** and unchanged.

  **Approved.** Today every reveal holder already holds role `canon.edit`, so the only practical difference from "only `canon.edit` holders read drafts" is the per-character `canon.edit` deny case in item 5.

  **The alternative** keeps reading limited to `canon.edit` holders. A reveal holder with a `canon.edit` deny on a character could then not read, and so could not release, that character's profile; the deny would block two operations.

  D8 decided A2a's route filters and its read, edit and release checks; those are now fixed as written above, including criteria 3, 4 and 14.
- **D9: Revelation lifecycle points that OD-17 does not settle. Approved by the owner as proposed (recorded 2026-11-07).** Applied in §10.2, §10.4 and §10.5. The alternatives are kept for the record.
  - **D9-a, the snapshot moment.** OD-17 says "members at release time". A revelation follows later releases, so this design reads it as **the moment the revelation is created**.
    - "Current" is the open memberships locked by the creation's membership statement, just before its campaign lock, that are `active` when read (§10.4, step 4a). The mechanism was revised on 2026-11-08 after a probed deadlock (§10.8.4).
    - **The cutoff is approved (owner, recorded 2026-11-08).** The snapshot moment is the start of that statement, so a join or reopen that commits after it is excluded even if it commits before the revelation does. The full statement is in §10.4, "D9-a candidate-statement cutoff".
    - Alternative: at the latest release. A new release would then re-snapshot every campaign-current revelation. That is not recommended, because releasing would then silently widen audiences.
  - **D9-b, who counts as current.** Open memberships with status `active`, including the GMs and the revealer. Pending invitations do not count, and neither do suspended or departed members.
  - **D9-c, a returning member.**
    - **`campaign_current_and_future`:** a returning member is a future member and is included.
    - **`campaign_current`:** they are not restored.
    - **`member` and `access_group`:** they are not restored, because a reopened membership starts with no revelations and no groups.

    This follows the existing reopen rule for roles, relationships, grants and groups.
  - **D9-d, a release is required.** A revelation cannot be created until the character has at least one release in this campaign, enforced by the database (§10.2). Releases are immutable and cannot be deleted, so this cannot later become false. Without it a revelation would show a name with an empty profile. Alternative: allow it, and show an empty public profile until a release exists.
  - **D9-e, one live revelation per audience.** One live row per (character, kind, target). That means one live `campaign_current` and one live `campaign_current_and_future` per character.
    - A repeat is a natural retry (200 `created: false`). It never refreshes a snapshot.
    - To include later joiners, the GM adds `member` or `access_group` revelations, creates a `campaign_current_and_future` one, or revokes and recreates.
    - Alternative: allow several `campaign_current` rows, so a retry with no key could silently widen the audience.
  - **D9-f, authority after the fact.**
    - A revelation survives the revealer losing reveal authority (a revoked delegation, a lost role, or a transfer), as releases do (§5, criterion 7). The provenance is the creator and `authority_source`.
    - **Any** current reveal-authority holder in the campaign may revoke it, not only its creator.
    - Alternative: close a delegated GM's revelations when the delegation ends.
  - **D9-g, an archived character.** Its revelations are inert while it is not active or not canon, and apply again on restore. That matches relationships and resource grants. Alternative: close them when the character is archived. No archive command exists yet.
- **D10: How far a revelation's discovery reaches. Approved by the owner (recorded 2026-11-07): D10-a,** using shared discovery across consumers while keeping each consumer's other audience and field restrictions (§10.15). ADR 0021 §6 requires one discovery predicate for every consumer. Revelation therefore enters the shared bundle, and a revealed character is discoverable everywhere discovery is consulted (§10.7). For a revealed-only caller that means it appears:
  - as a participant in reader-visible world relationships and public organization memberships;
  - in event explanations and session travel;
  - in member-readable encounters;
  - as a Knowledge subject label;
  - under its canonical name (D5) in each of those.

  This is exactly what `character.discover` from a relationship does today.

  - **D10-a, recommended:** accept it. Revealing a character discovers it.
  - **D10-b:** a revelation confers only the public profile and a single "revealed characters" list. It would be a second predicate, which ADR 0021 §6 rules out, so choosing it needs an ADR amendment.
- **D11: Who sees a released profile. Approved by the owner (recorded 2026-11-07): D11-a,** subject to applicable denies (§10.14). A revelation confers `character.view_public_profile`. The question was who else reads the public tier.
  - **D11-a, recommended:** a revelation, plus any caller holding `character.view_summary`, `character.view_full` or `canon.edit` for the character. The tiers are ordered public_profile < summary < full < gm, and each includes the latest release.
  - **D11-b:** revelation only.

  Either way, `character.discover` from a relationship or grant without a revelation does **not** show the profile, because publication is not revelation.
- **D12: Operation-specific denies on revelation. Approved by the owner (recorded 2026-11-07): D12-a.** Existing denies are honoured, and creation controls are deferred (§10.15). ADR 0021 §2.9 says a deny of `character.discover` alone hides only discovery. Today no such deny, and no deny of `character.view_public_profile`, can be created through the application: the resource-grant catalog excludes both codes (access.py, `CHARACTER_TARGET_CAPABILITY_CODES`). Raw rows are honoured.
  - **D12-a, recommended for A3:** honour them, test them with raw rows, and leave creating them to a separate catalog extension, like A2a-R.
  - **D12-b:** add both as deny-only codes in A3a.

  The whole-character `campaign.view` deny is creatable (A2a-R), and it covers the cases the denies must cover.

---

## Next slice: A2a acceptance criteria

A2a is the §5 design without the copy aid, D5/D6 columns, portal or revelations. It starts on top of the reviewed P0 and P1 commits, with D8 approved as proposed (criteria 3, 4 and 14 follow it). Database and API tests use namespaced fixtures, including the `Gate` fixture's custom `access.manage` holder.

1. **Migration.** `142_character_public_profiles` upgrades and downgrades on PostgreSQL 18, with a migration test in the style of `test_character_reveal_delegations_migration.py`. After the upgrade, existing characters have no draft or release.
2. **Constraints and triggers:**
   - releases refuse UPDATE, DELETE and TRUNCATE;
   - `version_number` and `from_draft_row_version` are unique per profile;
   - the composite foreign key refuses a release naming another campaign's or another character's profile;
   - the scope triggers refuse a character from another world, a membership or delegation from another campaign, and a delegation whose grantee is not the releaser;
   - the origin rules hold;
   - `test_entity_reference_classification.py` passes with the two `BLOCKING` entries, and a character with a release cannot be physically deleted.
3. **Draft save:**
   - create, update and no-op (`changed: false`, no `row_version` bump, no audit);
   - partial updates and explicit `null`;
   - 409 `stale_write` for a stale token and for a lost first-save race;
   - allowed for the owner, a GM and an assistant GM; refused for a player or observer by the route filter;
   - a `canon.edit` deny on the character (an `entity_id` grant) refuses the save. A reveal holder gets 403 `public_profile_edit_denied`; an assistant GM with no read path gets 404. Nothing is written in either case;
   - a whole-character deny refuses the save with 404;
   - a player holding only an `allow` grant of `canon.edit` on the character is refused;
   - a character outside the world, or not canon, gets 404; an archived one gets 409 `public_profile_character_not_active`;
   - an `Idempotency-Key` replay writes nothing;
   - campaign A's and campaign B's drafts for one character are independent.
4. **Release authority:**
   - the owner gets 201 with `authority_source = owner`; a delegated GM gets 201 with the delegation's id;
   - 403 `character_reveal_required`, with no row and no audit, for: an assistant GM; a GM holding `canon.edit` without a delegation; the custom `access.manage` holder; a GM whose delegation was revoked; a GM whose `gm` assignment was revoked or has expired;
   - B's owner on A's route gets 404;
   - a whole-character deny on the releaser gives 404 with nothing written, even when a release of that draft version already exists (no natural-retry disclosure);
   - a `canon.edit` deny on the character does not stop an owner or delegated GM from releasing.
5. **Release semantics:**
   - the snapshot equals the draft at `expected_draft_row_version`;
   - versions run 1..n without gaps;
   - a release leaves the draft's `row_version` unchanged;
   - a release whose fields are both null is allowed;
   - 409 `public_profile_draft_missing`; 409 `stale_write`; and a natural retry returning 200 `created: false` with `is_latest` (§5.5, §5.9).
6. **Concurrency.** Use the deterministic lock-wait harness (`pg_stat_activity` / `pg_blocking_pids`, as in A1). Cover:
   - every row of the §5.9 table;
   - revoking the delegation against a release, in both orders;
   - revoking the releaser's `gm` role against a release, in both orders;
   - a relinquishing transfer by the releasing owner;
   - a relinquishing transfer to a releasing GM;
   - the caller's finite owner assignment expiring during the release's lock wait (403, nothing written);
   - archiving the character against a release;
   - `create_resource_grant` to the releaser naming the character, against a release, in both orders. This pins the corrected lock order in §5.8; with the first design's order it deadlocks;
   - `create_resource_grant` of a whole-character deny, against a draft save and against a release. The deny that commits first is honoured (404, nothing written), and one that comes second waits for the command.
   - **Adding the releaser to an access group that holds a whole-character deny on the character, against a release, in both orders (after P1; §5.8, §7.6):**
     - **Release first.** The release is paused after its membership `FOR SHARE`, before its campaign lock. The add is blocked by the release, observed through `pg_blocking_pids`. On release: the release commits (201), then the add commits.
     - **Add first.** The add is paused after its membership locks, before its campaign lock. The release is blocked by the add. On release, the add commits, and the release's re-resolve sees the group deny: 404, no release row and no audit row.
     - Neither order deadlocks. The release must hold its membership `FOR SHARE`, not `KEY SHARE`; with `KEY SHARE` neither waits, and the add-first case can release despite the deny (probe S7/S8).
   - The same pair against a draft save, in both orders. The save is refused with 404 when the add commits first.

   No scenario deadlocks.
7. **Releases outlive authority.** After the delegation is revoked, and after the releasing owner relinquishes ownership, earlier releases are unchanged and still listed, and a new release is refused.
8. **Marker sweep of response bodies.** The draft text and the release text carry distinct markers. Read as each of these:
   - a player with only `campaign.view`;
   - a player with `view_full` through a relationship;
   - an observer;
   - campaign B's GM.

   Check these surfaces: character detail, world explorer list, search and counts, bootstrap, the sheet, inventory, relationships, the session roster, encounter reads and Knowledge. No response body contains either marker. Campaign B's GM gets 404 from A's profile routes.
9. **Structural tests:**
   - which modules may reference which table (§5.11);
   - the profile command and query modules import no sheet, calculation or rules module;
   - the classification registry covers every new column;
   - the Phase 15 route manifest lists the four new routes.
10. **Audit.** One row per real change. No profile text in `changed_fields`. No row for a no-op, a refusal or a replay. No `core.entity_revisions` row.
11. **Docs updated in the same change:**
    - `DATABASE_MODEL` (campaign schema);
    - `DOMAIN_MODEL` (public-profile draft, release, field origin);
    - `ENTITY_LIFECYCLE` command list;
    - `PHASE13E_ACCESS_CONTRACT` (release authority and `character_reveal_required`);
    - this plan's A2 status.
12. **Checks.**
    - Rerun A1's regressions: `test_character_reveal_delegation*.py`, `test_campaign_owner_*.py`.
    - Rerun P0's regressions (§6.4) and P1's (§7.8).
    - The A2a race tests use `LockRace` (§7.7).
    - Run `ruff format --check`, `ruff check` and `mypy src`.
    - Run the focused tests, then the full `pytest`, then migration up/down, then `git diff --check`.
    - Run CI on the final head.
    - Stop for an independent review that names the parent and target SHAs.
13. **Idempotency across characters (review correction).** The fingerprint covers `character_id` (§5.7).
    - **Release.** Release character X with key K and body B: 201. Then post the same K and the same B to character Y's release route: the non-disclosing idempotency 409. Y has no release row and no audit row, and its GM read shows no release. The stored X response is unchanged.
    - **Draft save.** The same check for the draft save: K and B on X, then K and B on Y, gives 409, and Y has no draft.
    - **Same character still replays.** K and B repeated on X replays X's stored receipt (status, ids, versions and flags).
14. **D8 reads.**
    - Allowed:
      - a reveal holder with a `canon.edit` deny on the character reads the draft and releases (200, `can_edit: false`, `can_release: true`);
      - an assistant GM reads (`can_release: false`).
    - Refused with 404:
      - a player;
      - an observer;
      - campaign B's GM;
      - a whole-character-denied owner.

## P2 implementation and review record (2026-11-08)

**Commit:** `d36d565` (parent `a9ec4c4`), "fix: serialize same-key campaign requests at an idempotency key lock (P03-A P2)". It is followed by `c705ee7`, a documentation-only rubric update.

**Built.**

- `lock_idempotency_key` takes `pg_advisory_xact_lock(hashtextextended(scope, 0))` on a versioned, length-prefixed `(actor, campaign, key)` scope (`idempotency_key_lock_scope`).
  - This is a 64-bit single-key form, not the two-key `(namespace, hashtext(...))` form this plan sketched.
  - No key means no lock. A transaction may take one distinct key lock; a second raises `IdempotencyKeyLockError`.
- `begin_idempotent_request` takes the lock immediately before its insert. The campaign-creation and actor-scoped stores do not take it.
- `reset_idempotency_key_lock` is used by the authoring harness between requests that share one connection.
- DATABASE_CONVENTIONS §26.4 gains a "key lock" paragraph.
- **Tests:**
  - `tests/database/test_idempotency_key_lock.py`, 10 tests: same-route and cross-route HTTP races on membership end and role revoke, the rollback case, no lock without a key, one key per transaction, scope encoding, and a different key not queueing.
  - `tests/unit/test_idempotency_key_lock_structure.py`, 5 tests.

**Independent review: PASS WITH NONBLOCKING FINDINGS.** The review text is not in the repository; this record follows the findings the owner supplied in conversation. *Corrected 2026-11-08: the first version of this record listed two limitations inferred from P2's commit message (different-key cycles and stale authorization after a key-lock wait). Those were not the review's findings. They remain true statements of P2's scope, as its commit message says.*

- **Results reported by the review:** the 15 P2 tests passed (10 database and 5 unit), and a 55-test focused run passed.
- **Findings (nonblocking):**
  1. **Structural caller-order coverage.**
     - The structural tests pin the helper: one reservation insert, after the one key-lock call, and nothing else taking the lock.
     - They do not cover the callers. The rule that every reserving route reserves before taking any row lock rests on the syntax-tree evaluation at `a9ec4c4` recorded in §10.11, not on a test that re-runs on each change.
     - A later route that takes a row lock before reserving would not be caught.
  2. **The external A3 call-site guard.**
     - `test_only_the_idempotency_module_takes_the_key_lock` admits no caller outside `api/idempotency.py`.
     - A3's step 0 (§10.4) calls `lock_idempotency_key` from its commands, so as written the guard would fail A3a.
     - A3a must widen it to name exactly A3's call sites, and pin that each is the command's first database statement, rather than drop it.
  3. **The outer-transaction harness limitation.**
     - The authoring harness (`tests/authoring_support.py`) runs many requests on one connection in one outer transaction, each in a savepoint, and calls `reset_idempotency_key_lock` between them.
     - Transaction-scoped advisory locks are not released by a savepoint's release or rollback, so key locks accumulate until the outer rollback.
     - Harness tests therefore cannot observe a key lock being released or queued on, and a second key in one harness test is not "another transaction".
     - Key-lock behaviour is established only by tests on real per-request transactions (`test_idempotency_key_lock.py`).
     - The same harness overrides `get_connection`, so it also cannot observe P3's commit timing (§11.6).

**Found after the review (2026-11-08, §11.3).** This is not a review finding.

- **The different-key test passes only because of DEF-022.** Its second request (DEF-019 K1) is the deadlock victim at COMMIT and persists nothing, yet it answers 200 at HEAD.
- P3 keeps the test's independent-key assertion, replaces its second request (§11.8, T8), and adds a separate deterministic DEF-019 regression (T9).
- The key lock's own behaviour, that a different key is granted at once, holds on both trees.

## P3 implementation record (2026-11-08)

**Commits:** baseline `c705ee7`; design `7f7aeb6` (section 11, committed on its own); implementation: the commit that carries this record. Not pushed. CI pending.

**Built (section 11.4).**

- `api/deps.py`: `commit_request_transaction` (async generator, installed once on `create_app`, function-scoped, first in every route's effective list); the `_commit` / `_rollback` seams; `_discard` (rollback, invalidate on failure, close; never raises); `_finish`; `end_request_transaction`; `get_connection` now takes the request, registers its connection and refuses (500, before any statement) when the commit dependency is missing or a second connection is requested. COMMIT and ROLLBACK run in a worker thread inside a shielded cancel scope; the connection closes only after the operation returns; a successful commit is followed by `checkpoint_if_cancelled()`.
- The eight engine-backed handlers call `end_request_transaction(request)` after authorization and before their first engine-side effect. The combat-sync docstring is corrected.
- `pyproject.toml` floor `fastapi>=0.141.1`; `uv.lock` changed in that one line; `uv lock --check` passes.
- Docs: SYSTEM_ARCHITECTURE 7.0 and 20, DATABASE_CONVENTIONS 26.4, the `deps`, `idempotency` and `integration` docstrings.

**P2's independent-key test corrected (T8).** It asserted `(200, 200)` for two keyed ends that deadlock at commit; the second used to answer 200 and persist nothing. It now pairs the held end with a keyed campaign-invitation create (campaign row `FOR SHARE`, a new row) and asserts the second finishes while the first is held, plus both receipts, the audit row and the end. The deterministic DEF-019 regression is a separate test (T9): exactly one 2xx, one deadlock counted, and for the losing request no end, audit row or receipt.

**Tests.** `tests/database/test_request_transaction.py` (T1-T7, T9, T10, T14), `test_request_transaction_cancellation.py` (T11a, T11c), `test_request_transaction_engine_routes.py` (T12 a-f), `tests/unit/test_request_transaction_lifecycle.py` (T11b, T13, T15, T16). The only existing test changed is T8's.

**Verification.** First full run (`tests/`, one process, isolated configuration, 40 min 40 s): 7205 passed, 0 failed, 0 errors. Earlier targeted runs, kept separate: the nine affected existing files, 227 passed and 1 failed on the first run (T8's test, as expected), then 10 passed after the correction. Mutation check: removing the post-commit checkpoint fails T11b(1); removing the explicit shield changes nothing, because `anyio.to_thread.run_sync` already shields its own wait. The shield is kept as the design states it. The plan's section 11.9 flake and handshake failures did not occur in this run; that establishes nothing about their cause.

**Still open.** DEF-019 (observed by T9, not fixed), DEF-020, DEF-021, stale authorization, the A1 wait-observation flake. A3 and push are not started.

---

## A2b-1 implementation record (2026-11-07)

**Parent:** `5fb2608` (the reviewed design commit; its parent is the A2a handoff `523ae5c`). One local commit; nothing is pushed and CI is pending.

**Built.**

- **Migration `143_profile_watermarks`** (§9.3): the two watermark columns, the pairing, positivity and bound CHECKs, and `campaign.enforce_public_profile_restriction_watermarks()` (INSERT: `watermark = row_version`; UPDATE of a legacy field's content: `watermark = OLD.row_version + 1`; never a decrease). The preflight refuses the upgrade, and a guard refuses the downgrade, while any draft or release carries a legacy origin; both are atomic (the revision, the schema and every row are unchanged after a refusal).
- **Domain/queries/commands/API:** the source-read rule and the restriction predicate (`domain/public_profiles.py`), `queries/public_profile_restrictions.py` (which fields are withheld from a caller; nothing stored), withholding in the profile read (`<field>: null`, `<field>_withheld`, origin and `origin_entity_row_version`; `can_release` false while any field is withheld), the save rule (token, then 403 `public_profile_field_withheld`, then the no-op comparison, then the write with watermark advance; clearing resets the lineage), and the release's world-row `FOR SHARE` first and withheld check before a new snapshot. A natural retry and a keyed replay do not consult the source read (D7-d).
- **Invariants.** I1/I2 are enforced by the database (CHECKs and trigger; I1's removal of provenance only from revision 144, see the correction below), I3/I4 are pinned by a unit model of the predicate and by HTTP scenarios, I5 by the release refusal, I6 by clearing, I7 because no request field names an origin or watermark.

**Deviations from §9.**

- **Revision id.** `143_profile_watermarks`, not `143_public_profile_restriction_watermarks`: Alembic's `version_num` is 32 characters and the longer id does not fit.
- **`COLUMN_CLASSES` does not list the two new columns.** The registry classifies text columns only and a test rejects entries for columns that are not text; both are `BIGINT`.
- **Seeding.** No copy route exists, so scenarios seed copied text with one test helper (`seed_copy`) that writes what the copy command will, subject to the CHECKs and trigger. A2b-2 replaces it.

**Races executed** (`test_character_public_profile_restriction_races.py`, with the real `end_world_membership` command; each wait observed as blocked by the intended session): the releaser's world role against a release of uncovered copied content, and the saver's world role against a save that writes text into the copied field, each with both winners; and a permitted edit of the released field against a restricted releaser's release of the earlier version, both winners. For each the text and the draft version the waiting command observed are asserted. **Not executed, because the copy command does not exist:** a copy against `update_npc`, a copy against a save and a release, and the copier's world role against a copy. They share the world-row `FOR SHARE`-then-capability and the draft `FOR UPDATE` paths exercised above; A2b-2 must add them and may not claim them passed.

**Verification** is in the commit message and the implementation report. Pending: independent review and CI.

### A2b-1 provenance correction (2026-11-07)

**Finding (independent review, CHANGES REQUIRED, conversation-supplied).** Invariant I1 was not enforced by the database as §9.3 and the record above claimed. Migration 143's trigger inspected a field only when the NEW row still carried a legacy source version, so an UPDATE that set a legacy-origin field to the authored origin, cleared its source version and watermark, and kept the text (unchanged or replaced) satisfied every CHECK and the trigger. Restricted copied text became unrestricted authored text. No application path does this, but the claim "I1/I2 are enforced by the database" was false for removal of provenance.

**Correction.** Revision `144_profile_provenance_guard` replaces the trigger function. Per field, an UPDATE whose OLD row has a legacy source version and whose NEW row has none is refused unless the NEW text is NULL (`integrity_constraint_violation`, "cannot be relabelled authored; clear the field instead"). Removing origin, source version and watermark is therefore possible only in the write that clears the field, which is what the save command already does. All 143 rules are kept.

**Why a new revision and not an edit of 143.** 143 is on no pushed branch (`origin/phase15/completion` is at `ea85b2c`), but a developer database may already be at 143, and Alembic does not re-run an edited revision: that database would keep the weaker function under the same revision id as a fresh one. A forward revision reaches both. The downgrade restores 143's function body, which lacks the relabel rule; because that would reopen the hole for mutable drafts, it first refuses (before any function or schema change, atomically) while any draft has a legacy provenance in either field (a source version, or an origin other than `authored`). Immutable releases do not block it: the function guards drafts only, and releases' own legacy rows are guarded by 143's downgrade. The independent review of `d1f463f` found the first form of this downgrade unguarded; the guard is a correction of 144's `downgrade()` itself, made in place: 144 is on no pushed branch, and Alembic runs the downgrade from the file on disk, so a database already at 144 is covered too, with no schema effect on upgrade.

**Regressions** (`test_character_public_profile_watermarks.py`, through the real trigger and CHECKs, both fields): unchanged copied text relabelled authored, and replacement text relabelled authored, are each refused with text, origins, watermark and `row_version` unchanged (full-row comparison); partial removal of provenance is refused and leaves the row unchanged; clearing text and provenance together succeeds (`row_version` 2); an authored edit of the other field, a valid copied-text edit (watermark = new version) and further authored edits keep their behaviour; and one migration test on a disposable database at 143 shows the relabel accepted before 144 and refused after the upgrade, with `alembic check` clean at head. Downgrade tests (disposable databases): a legacy-origin draft, or a draft whose origin code is legacy without a source version, refuses the downgrade and leaves the revision, the trigger function and comment, the schema and every draft and release row (all columns) and the audit count identical, with the relabel still refused; an authored draft with an immutable legacy release downgrades, restores 143's function with rows unchanged, and re-upgrades to a state identical to before.

**Stated limit.** A relabelled row written by hand at 143 before this revision is neither detected nor repaired by 144.

---

## A2b-2 implementation record (2026-11-07)

**Parent:** `c5689a32c6251dab5642ad4eaf66fb381aec7337` (revision 144's downgrade guard). One local commit; nothing is pushed and CI is pending.

**Review evidence (conversation-supplied, not in the repository).** The task that started A2b-2 stated that the independent review of A2b-1 was a PASS with a 70-test result; the A2b review handoff below records that it was at `c5689a3`. No review text or verdict wording was available to this session; the figures are recorded as relayed.

**Built.**

- **Command** `copy_legacy_text_to_public_profile_draft` and its pre-check `require_may_copy` (`commands/character_public_profile.py`); the lock order is §9.6's. The kind is read unlocked to choose the scope's world capability (`WORLD_CANON_READ_PRIVATE` for an NPC, `None` for a player character; any other kind, or a character outside the campaign's world, is 404). After `lock_authoring_scope`, the `AccessContext` is re-resolved for the D8 edit rule and the source-read rule, the entity is locked `FOR SHARE`, and the entity's `row_version` and the description text are read in separate statements under that lock: `update_npc`, the only writer of the description, holds the entity `FOR UPDATE` and bumps its `row_version` in the same transaction, so the pair is one committed state. The target field is replaced whole, the other field is untouched, and origin, source version and watermark (`row_version` after the write) are set; an insert starts at 1, an update at `OLD.row_version + 1`. Source text is stripped and a blank source is `public_profile_legacy_text_missing`.
- **Route** `POST …/public-profile/draft/copy-legacy` (`api/character_public_profile.py`), body `{expected_row_version, field}` with `field` in `{appearance, background}` and extra fields refused. The edit-and-source pre-check is a dependency, so it runs before body validation and before the idempotency lookup. The fingerprint holds `character_id`, the field and the token.
- **Read:** `legacy_copy` in the profile GET (§9.4).
- **Domain:** `LEGACY_COPY_SOURCES` (the only two sources; `notes` is never one) and `PublicProfileLegacyTextMissingError` (409 `public_profile_legacy_text_missing`).
- **No schema change.** Migrations 143 and 144 already enforce the watermark rules the copy writes under.

**Deviations from §9.**

- The `legacy_copy` value is `{appearance: bool, background: bool}` and is `null` for an inactive character as well as for a caller who may not copy.
- The copy response adds `origin_entity_row_version` (an integer) to the §9.4 receipt of ids, `row_version`, `created` and `changed`.
- The pre-check order is: D8 edit rule, kind in this world (404), source read (403). A caller who fails the edit rule gets the save's 403/404 first.
- The first-copy insert sets only the copied field; the other field is NULL and authored.

**Tests.** `test_character_public_profile_copy.py` (20, over HTTP) covers the NPC and player-character source rules, unsupported kinds, fields and provenance in the request, empty sources, denies and an inactive character, `legacy_copy`, stale and missing tokens, keyed replay, a replay refused after losing the world role, a different field or character under one key, atomic rollback of the write and its key when the audit write fails, mixed origins, clearing and recopying, the excerpt regressions through the real copy (append; restore by edit; restore by recopy), and a disclosure sweep over every response, the stored receipts and the audit rows. `test_character_public_profile_copy_races.py` (10, real commands, every wait observed as blocked by the intended session) covers a copy against `update_npc`, a save and a release, each with both winners, and the copier's world role against a copy with both winners for an end and for a downgrade; each asserts the resulting text, source version, watermark, the authorization outcome and that no command wrote an audit row. Structural pins: the route-manifest counts (244 guarded, 197 phase-15 GM), the copy's conditional world-capability argument, `LEGACY_COPY_SOURCES`, and the modules admitted as readers of the description table.

**Not done here:** audience revelations (A3/A4), the portal (A6), push. Pending: independent review and CI.

---

## A2b review outcome and handoff (2026-11-07)

Both verdicts and run counts below were relayed by the owner in conversation. The review texts and raw run output are not in the repository, so neither is reproduced.

- **A2b-1: PASS** at `c5689a3` (the head after the provenance correction `d1f463f` and the revision 144 downgrade guard), with an independent run of **70 tests**. Recorded separately from A2b-2's.
- **A2b-2: PASS WITH NONBLOCKING FINDINGS** at `46a0154`, with an independent run of **122 tests**. The findings were not relayed in detail; the one that required a change here is the receipt's `origin_entity_row_version`.
- **Receipt exception documented.** The copy receipt's integer `origin_entity_row_version` is a deliberate departure from the minimal-receipt contract (ids, `row_version`, `created`, `changed`). `DATABASE_CONVENTIONS.md` (the idempotency-replay paragraph) now names it as a specific exception for this approved provenance metadata, and says no other command may add a field and no receipt may carry copied text.
- **Still open, unchanged:** the intermittent A1 wait-observation timeout (cause unestablished), DEF-016, DEF-017 and F-1. CI on the final head is pending; nothing is pushed.
- **Next, not started:** A3 (audience revelations; designed and finalized in §10), A4 (the audience read; awaiting D6), A6 (the portal), push.

---

## A2a and A2a-R review outcome and handoff (2026-11-07)

- **Verdicts.** The independent review of A2a (`0b4704c`) and of A2a-R (`f66240a`) each returned **PASS WITH NONBLOCKING FINDINGS**. The reviewer's independent run: **80 passed**, reported by the owner from the independent review in conversation. The review text and the raw run output are not in the repository, so neither is reproduced here.
- **Release replay.** Corrected above (§5.9, §8.6): a stored release replays the minimal receipt, not the full response body.
- **The A1 timeout.** The full suites after A2a and A2a-R each failed one A1 wait test (listed in the status lines). The helper involved is `_wait_until_waiting_on` in `test_character_reveal_delegation.py`, which calls `_wait_until_waiting` and `_waiting_on_locks` in `test_campaign_owner_lock_order.py`: a count of every session in the test database waiting on any lock, whoever it is and whatever it waits for. The failing test's grant request is now observed through `LockRace.wait_blocked_by` against the held end-of-membership transaction, with early response diagnostics and cleanup; the other tests that still use the global count keep it. **Whether the request failed to reach its lock, reached it late, or waited in a way the count missed is not established**, and the cause stays recorded as unresolved.

---

## A2a implementation record (2026-11-07)

**Parent:** `3b3d637` (the design commit; its parent is P1, `edf46ca`). The implementation is one local commit on `phase15/completion`; nothing is pushed and CI is pending.

**What was built.**

- **Migration `142_character_public_profiles`** (additive, no backfill): the lookup `campaign.public_profile_field_origins`, the draft `campaign.character_public_profiles` and the append-only `campaign.character_public_profile_releases`, with the scope, origin and immutability triggers of §5.3, `ON DELETE RESTRICT` on the campaign and character foreign keys, UPDATE/DELETE/TRUNCATE revoked on releases and DELETE/TRUNCATE on drafts from the application roles, and nothing readable by `app_read_only`. Down: drops the three tables and three functions (lossy by design); up/down/up and `alembic check` are pinned by `test_character_public_profiles_migration.py`.
- **Domain** `domain/public_profiles.py` (errors and the pure D8 policy), **commands** `commands/character_public_profile.py` (`save_character_public_profile_draft`, `release_character_public_profile`, and the two route pre-checks `require_may_edit` / `require_may_release`), **queries** `queries/character_public_profile.py` (the two GM reads and `latest_character_public_profile_release`, which has no caller yet), **API** `api/character_public_profile.py` (four routes), registries (persistence metadata, `ENTITY_REFERENCE_CLASSIFICATION` `BLOCKING` entries, `COLUMN_CLASSES`, the route manifest, `test_role_grants`).

**Where the implementation settles points the plan left open or tightened.**

- **Pre-checks as dependencies.** The release's authority check (and both routes' deny checks) run in a FastAPI dependency after the capability dependency, before the body is read and before the idempotency lookup, so a player gets `403` rather than `422` and a caller who lost authority cannot replay a stored response. The whole-character deny is in the release pre-check as well as under lock, so a denied caller cannot replay a keyed release either (the owner's instruction: a deny blocks release retries).
- **`version_number` is a `str` path segment** on the release read: a non-number is the same `404` as a missing release (the route manifest's generic probes substitute a UUID).
- **A whole-character deny cannot be created through `create_resource_grant`** (it refuses `entity_id` for a character). The A2a review classed this as a defect, not a test convenience; it is corrected by A2a-R (§8). Meanwhile the "deny that commits first is honoured" races are exercised through the way a deny actually reaches a member: an access-group addition carrying a raw `entity_id` deny grant, in both orders against the release and the save (the P1 lock order). Direct deny rows in the API tests are inserted as the inventory tests do. **Superseded by A2a-R (below):** both denies are now creatable through the application, and the group-addition races create their deny with the command.
- **No character archive command exists**; the archive race holds the lock the lifecycle commands take (`FOR UPDATE` on the entity) and writes the archived status.
- **`campaign.public_profile_field_origins`** is not in the frozen reporting allowlist, so its columns are classified in `COLUMN_CLASSES` rather than listed as reference data. `save_character_public_profile_draft` is a registered `world_capability=None` scope (`test_world_gate_registry.py`): the draft is a campaign's, not shared world canon.
- **D5, D6, D7 are not applied.** A release carries no name, summary, species or size; no legacy text is copied (A2b).

**Verification.** Recorded in the commit message and the implementation report (focused and full suites, migration up/down and drift, static checks, and the configuration isolation of `docs/DEVELOPMENT.md` §6.2). Pending: independent review and CI on the final head. A real-browser check does not apply (no UI).

---

## A2a-R implementation record (2026-11-07)

**Parent:** `07d69b1` (the design commit recording the owner's Q1-Q3 answers; its parent is A2a, `0b4704c`). One local commit; nothing is pushed and CI is pending.

- **Built:** `_validate_resource_grant_target` takes the grant's `effect`; a `character`, `npc` or `player_character` entity is an accepted `entity_id` target for a deny (the catalog then leaves `campaign.view` and `canon.edit`); allows, `character.*` codes and the other own-column kinds are still refused. The access overview (member and group grants) and the effective-access explanation name the character for such a grant. Docstrings, the access contract and the register (DEF-018 fixed; DEF-016 registered, open) are updated. No schema, route, request or response shape changed.
- **Existing raw allow rows were measured, not assumed.** A raw `allow` of `campaign.view` or `canon.edit` under `entity_id` on a character changes no response of the profile, character detail, sheet, inventory, relationships, party and World Explorer search and count readers, for a player and for a manager (the party route is a 404 for both before and after, so it adds little). They are inert today, which does not change A2a-R's scope; deny-only keeps it that way.
- **Races.** Ten new races create the deny through the HTTP route (audit checked) or the command, against a save and a release, in both orders, for a membership grantee and a group grantee, and a `canon.edit` deny against a save. The command that waited resolves its access afresh and is refused with nothing written; the deny that waited commits after.
- **Not done, by decision:** portal controls (A6), DEF-016, DEF-017, A2b.

---

## A0 acceptance criteria (implemented at `fca3ac7`)

1. `get_character_view` takes `campaign_id`. `active_encounter_id` is returned only for an `active` encounter whose `campaign_id` equals the route campaign and which passes the shared encounter member-read predicate. Campaign-less encounters are never returned.
2. The filter applies to every full-tier reader: a non-GM with `view_full` from a relationship or grant, a `canon.edit` GM, and the Foundry `encounter_read` route.
3. The summary tier is unchanged: still null, still no query.
4. Database tests (namespaced fixtures):
   - same-campaign encounter returned to a full-tier member and to the GM;
   - campaign B's active encounter on the **same timeline** is not returned to A's GM or A's full-tier member;
   - a campaign-less encounter is returned to nobody;
   - when B's active encounter has the later world time, A's reader still gets A's (the filter runs before `LIMIT`);
   - a pending same-campaign encounter is ignored;
   - the AI context returns only the same-campaign encounter.
5. The existing test [test_full_tier_returns_the_active_encounter_id](../tests/database/test_api_characters.py#L651) builds a campaign-less encounter ([factories.py:3119](../tests/factories.py#L3119), `campaign_id=None`). Under the approved policy it becomes null, so update it to pass `campaign_id` and record this as the intended behavior change, not a weakened assertion.
6. No schema, API-shape or portal type change. `tests/database/test_api_encounters_query.py` passes unchanged.
7. Update the docstring in `queries/character.py` and record that the `active_encounter_id` part of DEF-009 is now implemented.
8. The standard checks plus CI pass, then stop for independent review.
