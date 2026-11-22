# P15-C02 checkpoint readiness assessment (2026-11-22)

**Status: assessment only.** It performs no merge, grants no owner, `actor-a`, persona, browser, assistive-technology (AT) or human acceptance, and waives or relocates no gate. PR #71 stays a draft and unmerged. Scripted results below are labelled as scripted; none is browser, AT or human evidence.

**Assessed head.** Code and tests are as of `a7ef391de64931e1a4a24030b441c338045ea89c` (branch `phase15/completion`, base `main` at `bf23c7648601eb1b3ad479078f2762fe13fd460b`, unchanged since the branch point). Later commits on the branch are documentation only; CI for the final head is read from GitHub, not recorded here (a record of its own result would be a new head).

## 1. Governing requirements

| Rule | Source | What it says |
|---|---|---|
| Merge gate | [Execution stages and review gates](work-register.md#execution-stages-and-review-gates) | Merge requires all included slice reviews, the PR acceptance cases and CI on the integration head. Merge, cut-over, browser verification and owner acceptance are distinct events with their own head, actor and evidence. |
| Gate order | [C01 plan §11.13](p15-c01-s02-effective-access-plan.md#1113-gate-order-clarification-2026-11-20) | Checkpoint merge precedes integrated-head browser/AX, human and owner evidence; those need `p15-integration`, which needs the checkpoint merged. |
| C02 scope | [S02 plan §1.3](p15-c02-s02-revelations-plan.md#13-does-c02-merge-only-with-s01-to-s04-together), [S04 plan §1.3](p15-c02-s04-character-denies-plan.md#13-c02-merge-scope-unchanged) | C02 merges only with S01 to S04 together (owner's OD-2, 2026-11-21). A smaller checkpoint needs a register re-size, not an exception. |
| Slice gates | [S01 §7.2](p15-c02-s01-draft-release-plan.md#72-checkpoint-merge-gate-c02), S02 §7.2, S03 §7.2, [S04 §7.2](p15-c02-s04-character-denies-plan.md#72-c02-checkpoint-integration-not-s04s-verdict) | The same three conditions. S04 adds that readiness must account for CI failures `44951144761` and `44965989830` and show whether the focus failure repeats before it is called non-repeatable. |
| Separate events | S01 §7.3, S02 §7.3, S03 §7.3, S04 §7.3 | Persona browser checks (`browser`), AT checks (`ax`, `b16`) and owner acceptance (`actor-a`, `p15-owner`) are "separate events, not merge gates". |
| Docs-only head | S01 §7.2 | A documentation-only commit is a new head and needs its own CI run. |

## 2. Which cases are merge requirements and which are not

**Merge requirements (checkpoint gate).** (a) Independent review of S01, S02, S03 and S04. (b) The PR acceptance cases of the four slices. These are the slice criteria rows in the [register](work-register.md#criteria-p15-c02-s01) and each plan's §6: S01 D1 to D17 and R1 to R17; S02 V1 to V30; S03 L1 to L12 and M1 to M21 plus the backend read cases; S04 O1 to O16, R1 to R18, BD1 to BD9. The S03 and S04 criteria rows name the integration behaviors this assessment exercises ("the next reveal attempt"; "revoke through the existing grant API, then re-read effective sources and remaining denies"). (c) CI on the PR head through its merge checkout. (d) Entry criteria (`a4` merged, `r01` owner accepted), recorded in the register. The merge itself is the owner's decision.

**Not merge requirements (separate events at the final integrated head, after the required checkpoints merge).**

| Case | Belongs to | Cited by |
|---|---|---|
| Persona browser checks: GM with edit and reveal; editor without reveal; reveal holder under a `canon.edit` deny; player who sees nothing new (S01); owner reveals then revokes; delegated GM reveals then loses the delegation; player sees the public tier appear and disappear (S02); owner grants to a GM, GM's next reveal succeeds, owner revokes, next reveal refused, role revoked on the management tab and the delegation gone on the Reveal authority tab, custom manager reads only (S03); delegated GM under a `canon.edit` deny still reveals and releases but cannot save, whole-character deny hides the character from the GM's pages, self-deny removable by the owner, group deny follows membership (S04) | [browser](work-register.md#browser) at the final integrated head | S01 §7.3, S02 §7.3, S03 §7.3, S04 §7.3 |
| AT checks: dialog focus trap and return, announcements, error-summary focus, label association, hint association, snapshot disclosure, reflow at 320 CSS px and actual zoom | [ax](work-register.md#ax), [b16](work-register.md#b16) | same |
| Owner acceptance of scoped A | [actor-a](work-register.md#actor-a) | register C02 criteria row |
| Final Phase 15 verification and release acceptance | [p15-integration](work-register.md#p15-integration), `release-review`, [p15-owner](work-register.md#p15-owner) | C01 §11.13 step 4 |

The scripted cases below exercise the same *behaviors* the persona lists name, through the public routes. They are an automatable check of the slice acceptance cases at the integrated head. They do not replace the persona browser checks, which are about what a person sees and does in a real browser, and which stay where the register put them.

## 3. Scripted integration cases completed

File: `tests/database/test_p15_c02_checkpoint_integration.py` (new; commit `a7ef391de64931e1a4a24030b441c338045ea89c`). Disposable database, real HTTP routes through the test client, every write made by a route (grant, revoke, release, create, deny, group, membership), never a seeded row. **Scripted evidence. Not browser, AT, human, persona-in-browser or owner evidence.**

| Case | Test | Result |
|---|---|---|
| Owner grants reveal authority, that GM's next reveal succeeds; before the grant the GM can read and edit but not reveal or release; delegated GM cannot redelegate; owner revokes, the GM's next reveal and release are refused; the earlier revelation stands and only an owner can end it; the revealed-to player sees the character and then no longer does | `test_the_owner_grants_reveal_authority_and_that_gms_next_reveal_succeeds_until_revoked` | passed |
| The delegation ends with the GM role; the next reveal is refused; a regrant needs a live built-in GM assignment | `test_a_delegation_ends_with_the_gm_role_and_the_next_reveal_is_refused` | passed |
| Non-owners (assistant, custom-role look-alike, custom manager, player) cannot grant; they cannot revoke; the delegation is unaffected | `test_a_stale_owner_and_a_non_owner_cannot_grant_or_revoke` | passed |
| Character denies and their revocation across owner, delegated GM, editor and revealed-to player, for a member source and a group source: edit-only deny keeps reveal and release; member whole-character deny removes the character for that GM only; a group deny reaches the player through membership and follows removal and re-adding; revoking the member deny leaves the group deny; the explanation names the remaining deny and then none; the delegation is untouched throughout | `test_character_denies_and_their_revocation_across_personas_and_sources` | passed |
| Self-deny by an owner, removable by that owner through the existing route, naming nobody else | `test_a_self_deny_is_removable_by_an_owner_and_names_nobody_else` | passed |
| A player with no revelation sees nothing new, and a `canon.edit` deny does not change that | `test_a_player_without_a_revelation_sees_nothing_new` | passed |

**Full portal run (separate, at `a7ef391`, default concurrency, from PowerShell):** 440 files passed, 1 failed; 5526 passed, 1 failed (the F2 focus test above); the failed file alone, 58 of 58. Recorded as a failed full run; the isolated rerun is not a suite pass.

**Verification run.** First and only run of the new file after two test-side corrections (the delegation source code is `delegation`, and `revoke_membership_role` takes no actor or plan): 6 passed. At the committed tree `a7ef391` (clean worktree), the new file with `test_character_denies_and_reveal_authority.py`, `test_r01_s5e6_reveal_delegation_routes.py` and `test_character_revelations.py`: 116 passed in 88 s. `ruff format --check` and `ruff check` pass on the new file (`mypy` is configured for `src`, as CLAUDE.md states; running it on the test file reports only errors in other, existing test modules).

**Mutation probe.** With `AND revoked_at IS NULL` in `domain/reveal_authority.py`'s delegation lookup replaced by `AND TRUE`, the grant, reveal and revoke case failed (1 failed, 5 passed); the file was restored (SHA-256 prefix `381255bf5a283def` before and after). No probe was made against the deny case; its sensitivity rests on the existing BD tests' probes and the explicit baseline and after-revoke assertions.

**Limits.** No backend shard run was made for this change (a new test file adds a file to the round-robin and so changes shard membership; CI exercises the real eight-way split). Cases the persona lists name that are about rendering (tab navigation, the Reveal authority tab, "a custom manager reads only" as a page) are covered by the portal tests of S03 and not repeated here. The expired-assignment and lock-order cases stay with the existing race tests.

## 4. The provisional Cancel-focus issue against the checkpoint criteria

**Observed.** Run `44951144761` (head `3381f7e`): the portal job failed one test, `CharacterPublicProfilePage.test.tsx` "Cancel still returns focus to Release" (focus on `h1#public-profile-heading` where the Release button was expected). Run `44965989830` (head `0d8d494`), which S04 §7.2 required be accounted for, **also failed the portal job**, in a different test: `terminalStates.test.tsx` "gives a missing world and a hidden world the same output" (an expected document title `Not available · portal` was not present); all other jobs, including all eight backend shards, passed. Run `44979295720` attempt 1 (head `225a4af`) failed `ItemDefinitionPages.save.test.tsx` and passed on re-run. The runs for the heads before and after (`fe88842`, `98b0238`, `499e90f`, `7f965c3`) passed.

**Repetition.** In CI the Cancel-focus failure has not recurred (the suite passed on `98b0238`, `499e90f` and `7f965c3`). **The same symptom has now recurred locally, in a different S01 test.** A full portal run at default concurrency at `a7ef391` (this assessment's run; 440 files passed, 1 failed; 5526 of 5527 tests) failed `CharacterPublicProfilePage.test.tsx` "a release that returns a new snapshot returns focus to the Release button" (F2): after the test had opened the release dialog, confirmed it and seen the new latest-release region, focus was on `h1#public-profile-heading` where `#public-profile-release` was expected. The same file then passed 58 of 58 when run alone. This is the same failure shape as `44951144761` (focus on the page heading instead of the Release button), seen twice on the same page across two tests. It is therefore **not** correct to call the focus symptom a one-off or non-repeatable, and this record no longer says so. The other portal failures seen in CI (`terminalStates.test.tsx` in `44965989830`; `ItemDefinitionPages.save.test.tsx` in `44979295720`) are different tests and remain separate. A full run at default concurrency fails differently placed tests from run to run (S04 §11.3), so load-sensitivity of the portal suite is established; which of those failures reflect product behavior is not.

**What is and is not established.** A natural-load probe recorded in S04 §11.3 reproduced the symptom (2 of 36 runs; the active element was `body` when Release was found), which shows the test can interact before the page-arrival focus (`usePageArrival`) has settled. That is a hypothesis about the test's ordering, consistent with the log. The new failure weakens it as a complete explanation: the heading took focus *after* the test had already opened and confirmed a dialog and seen the release land, so the late focus was not only an early-interaction artifact of the Cancel test. Either the arrival-focus effect ran very late under load, or something re-ran it after the release; the run did not distinguish these. It does not exclude a product exposure: if a person activates a control in the interval between the commit and the passive arrival-focus effect, the page-arrival focus can move focus off what they just activated. Nothing here measures how large that interval is in a real browser, and no real-browser run has been made. This assessment does **not** resolve the question, does not call it non-repeatable on the strength of green CI, and does not call it a product defect.

**Against the checkpoint criteria.** The maintained merge gate (slice reviews, PR acceptance cases, CI on the head) does not list this item, and CI on the assessed heads passed. S04 §7.2 requires it to be *accounted for*: this section does that. Whether the residual uncertainty is acceptable for the merge is the owner's judgment; I make no recommendation to dismiss it. It is carried as an open provisional item (now with a second occurrence of the symptom), with two concrete homes that are separate events: (1) the integrated-head browser/AX check (does arrival focus override an early real interaction, and for how long), and (2) a separate, owner-approved correction if that check shows an effect. No fix, sleep or assertion change was made.

## 5. Readiness table

| Requirement | Evidence | Status | Remaining action |
|---|---|---|---|
| S01 independently reviewed | S01 plan §11.4 to §11.8: F1, F2, F1-R1 closed; T01, T02, combined PASS WITH VERIFICATION LIMITS | Met | None for the gate. Its verification limits stay recorded. |
| S02 independently reviewed | S02 plan §11.4 to §11.14: R-S02-1, 4, 4a, 4b, 5 closed; T01, T02, combined PASS WITH VERIFICATION LIMITS | Met | None for the gate. |
| S03 independently reviewed | S03 plan §11.4: T01, T02, combined PASS WITH VERIFICATION LIMITS; no correction identified | Met | None for the gate. |
| S04 independently reviewed | S04 plan §11.4 and §11.6: S04-R1 closed; T01 and combined S04 PASS WITH VERIFICATION LIMITS; T02 PASS WITH VERIFICATION LIMITS; expiry-test correction PASS WITH VERIFICATION LIMITS | Met | None for the gate. DEF-016 stays open and separate. |
| PR acceptance cases: S01 to S04 slice cases | Recorded as passing in each reviewed range (D1 to D17, R1 to R17; V1 to V30; L1 to L12, M1 to M21 and backend read cases; O1 to O16, R1 to R18, BD1 to BD9) | Met on the reviewed ranges | Reviewers' verification limits stand. |
| PR acceptance cases: C02 integration behaviors (grant to next reveal; revoke; role end; denies across personas and sources) | Section 3: 6 scripted tests passed at `a7ef391`; 116 passed with the related existing suites | Met by scripted evidence | None for the gate. Browser persona versions remain a separate event. |
| CI on the integration head through the merge checkout | `45001046629` passed (14 of 14 jobs) for `7f965c3`, synthetic merge `1d8e3d956b9333184fba835263c7b5ec0f34076d`. The records and test commits after it are new heads. | **Open for the final head** | Read CI for the final pushed head. Each later commit, documentation-only included, needs its own run. |
| Entry criteria `a4` merged, `r01` owner accepted | Register: recorded | Met | None. |
| Base unchanged since branch point | `origin/main` is `bf23c7648601eb1b3ad479078f2762fe13fd460b`, the merge base | Met | If `main` moves, re-review affected ranges. |
| Accounting for CI failures `44951144761`, `44965989830` (S04 §7.2); repetition of the focus failure | Section 4: the focus symptom recurred once locally in a different S01 test (full run at `a7ef391`, 5526/5527; the file alone 58/58) | Accounted for; **repeats under load; uncertainty preserved** | Owner judgment whether the open focus item is acceptable at merge; browser/AX check at the final head. |
| Historical failures and test-only corrections | Plan §11.3a records run `44979295720` (both attempts failed), the diagnosis and the profile-copy test correction; the expiry-test correction passed independent review | Preserved | None. |
| Owner decision to merge | Not made. OD-2 (S01 to S04 together) is recorded. | **Open** | Owner decides the merge. PR #71 is a draft until then. |
| Persona browser checks at the final integrated head | None performed. | Separate event, not a merge gate | `browser` at `p15-integration`. |
| AT, zoom, screen-reader, human checks | None performed. | Separate event, not a merge gate | `ax`, `b16` at `p15-integration`. |
| Owner acceptance of scoped A | None granted. | Separate event | `actor-a`. |
| Final Phase 15 verification and release acceptance | None. | Separate event | `p15-integration`, `release-review`, `p15-owner`. |

## 6. Remaining merge blockers

1. **CI on the final pushed head** of PR #71 (a documentation-only commit is its own head).
2. **The owner's decision to merge**, and marking the PR ready, which is theirs and not done here.
3. The focus-return item (two S01 tests, three observed failures across CI and the local full run) is **not** a stated gate; it is an open, accounted-for uncertainty the owner should weigh, with a diagnosis step (is `usePageArrival` able to take focus after a user interaction?) that has not been done. I do not recommend dismissing it.

Everything else the gate lists is met. Browser/AX, `actor-a` and owner acceptance are separate and unperformed.
