# D/P15-C02-S03 implementation plan: manage reveal-authority delegations

**Status:** Opus plan prepared 2026-11-21; **refined and owner decisions recorded 2026-11-21; T01 and T02 implemented (Section 11.3) and independently reviewed: PASS WITH VERIFICATION LIMITS (Section 11.4)** (§10.1): OD-S03-1 = option A and OD-S03-2 = the default. The refinements (§10.2) were made before implementation: an open delegation row is distinguished from an effective one (G-F), repeated-write semantics are stated without claiming replay safety (§2.1, §8), and owner status, eligibility and effective state are derived on the server. No implementation had started at the commit that recorded this plan (`9d410b69246e86776964a1fe90bfd8978aebfdac`). Work-register row: [D/P15-C02-S03](work-register.md#p15-c02-s03), tasks [T01](work-register.md#p15-c02-s03-t01) and [T02](work-register.md#p15-c02-s03-t02). Parent checkpoint: [D/P15-C02](work-register.md#p15-c02).

**Baseline.** This plan was read at `3381f7e69ba17d8dc9ef20008c047569056d4e00` ("docs: record P15-C02-S02 R-S02-4a/4b confirmation (11.14); T02 and S02 pass with verification limits"). That is the finalized S02 records commit.
- It is the head of `phase15/completion` and equals `origin/phase15/completion` (fetched 2026-11-21). The worktree was clean. No repository-path `AGENTS.md` exists.
- It is also the head of **PR #71**: open, draft, base `main`. That head's CI run `44951144761` was **in progress** when read (shard 4/8 pending; the others reported had passed). It is not recorded as a pass. The earlier runs `44835164789` (head `97f75b6`) and `44946172550` (head `fe88842`, synthetic merge `0c5d6ec`) stay as recorded. This plan does not change PR #71.
- **Preserved review records.** S01's pass with verification limits ([S01 plan §11.4 to §11.8](p15-c02-s01-draft-release-plan.md#118-f1-r1-independent-confirmation)) and S02's T01, T02 and combined passes with verification limits ([S02 plan §11.4 to §11.14](p15-c02-s02-revelations-plan.md#1114-independent-confirmation-of-r-s02-4a-and-r-s02-4b-codex-2026-11-21)) are unchanged. So are every historical local full-suite failure, its isolated reruns, and §11.13's unread run, which remains unknown.

**How each statement was established.** By reading source, documents and git/GitHub metadata at the baseline. No application, test or probe was run, and no application, test, schema or backend file changed.

**Contract sources.**
- [ACCESS_CONTROL §3u](../api/ACCESS_CONTROL.md#3u-reveal-delegation-p03-a-a1): reveal delegation.
- `src/dnd_ai/api/character_reveal.py`, `commands/reveal_delegation_plans.py`, `commands/character_reveal.py`, `commands/reveal_delegation_lifecycle.py`, `domain/reveal_authority.py` and `domain/access.py` (`find_live_builtin_owner_assignment`, `find_live_builtin_gm_assignment`).
- `persistence/tables/security.py` (`character_reveal_delegations`).
- `api/access_overview.py` and `queries/access_overview.py`; `queries/bootstrap.py`.
- The [A1 design](ownership-design.md) and [shared characters §1 and §4](shared-characters.md#4-slices-dependencies-and-review-boundaries).
- The [operation catalog](../api/identity-and-access.md).
- The portal's Access pages (`pages/CampaignAccessPage.tsx`, `pages/AccessPage.tsx`, `components/AccessTabNav.tsx`, `components/AccessNavGroup.tsx`, `navigation/routeMeta.ts`, `App.tsx`) and S02's `hooks/useAuthoringMutation.ts`.
- The register's [execution stages and review gates](work-register.md#execution-stages-and-review-gates), and the [grading rubric](grading.md).

---

## 1. Entry readiness

### 1.1 Prerequisites

| Requirement | Source | State at the baseline |
|---|---|---|
| Checkpoint entry criteria: `a4` merged, `r01` owner accepted | [C02 criteria](work-register.md#criteria-p15-c02) | Met; confirmed in [S01 plan §1](p15-c02-s01-draft-release-plan.md#1-entry-readiness). Nothing since changes them |
| Slice-specific gate | S03 row: "Checkpoint entry criteria; no additional slice-specific gate" | None |
| Task gates | T01, T02: "Completed Opus plan for P15-C02-S03 and its required slice prerequisites" | This plan. It is complete except for OD-S03-1 |
| Other slices | None named | S01 and S02 are reviewed. S03 needs neither, though S02's `can_reveal` is how a grantee sees the effect (§2.4). S04 is independent |

`a5c`, `copy-ui` and `preview` are not prerequisites of S03.

### 1.2 Readiness verdict

- **S03 is eligible.**
- **Neither task can start** until OD-S03-1 is recorded. §2.3 shows that the existing contracts cannot say who holds a delegation, who may receive one, or whether the caller may grant or revoke. Building T01 on them would make the portal decide authority on the client, which is not admissible (§10, option C).
- **After OD-S03-1:** T01, then T02, with no further owner decision required. OD-S03-2 has a recommended default that applies unless the owner chooses otherwise.

### 1.3 C02 merge scope (unchanged)

C02 merges only with S01 to S04 together. Every included slice must be independently reviewed, the PR acceptance cases must pass, and CI must pass on the integration head ([register execution stages](work-register.md#execution-stages-and-review-gates); [S02 plan §1.3](p15-c02-s02-revelations-plan.md#13-does-c02-merge-only-with-s01-to-s04-together)). The owner retained that scope on 2026-11-21 (OD-2, [S02 plan §10.1](p15-c02-s02-revelations-plan.md#101-owner-decisions-recorded-2026-11-21)). This plan neither changes nor relies on it. S03's review is one input to that merge, and S04 is still unplanned.

---

## 2. Verified current behavior

### 2.1 Write routes (A1; R01 S5-E6)

| Route | Gate | Body | Result |
|---|---|---|---|
| `POST /campaigns/{campaign_id}/reveal-delegations` | `access.manage` route capability (a coarse filter); then the command requires a **live built-in `campaign_owner`** assignment | `{grantee_campaign_membership_id, reason}` (`reason` 1–1000 characters) | `200 {grantee_campaign_membership_id, character_reveal_delegation_id, granted}`; `granted: false` when a delegation bound to the grantee's current `gm` assignment already exists |
| `POST /campaigns/{campaign_id}/reveal-delegations/{grantee_campaign_membership_id}/revoke` | As above | `{reason}` | `200 {grantee_campaign_membership_id, revoked}`; `revoked: false` when none was live |

**Refusals.**

| Status | Code | When |
|---|---|---|
| 401 | — | Not signed in |
| 403 or 404 | (capability gate) | No `access.manage`. A non-member, or an archived or deleted campaign, gets 404 |
| 403 | `campaign_owner_required` | The caller is not a live built-in owner, at discovery, at the lock or at the fresh instant. This includes a custom `access.manage` holder and a delegated GM, so **a delegated GM cannot redelegate**. The server's `safe_message` reads "Only a campaign owner may grant the campaign owner role.", which is wrong in this context (G-D) |
| 404 | (non-disclosing) | The grantee membership is not in this campaign |
| 409 | `reveal_delegation_recipient_not_gm` | Grant only: the grantee holds no live built-in `gm` assignment (open, `active` membership; active account; assignment neither revoked nor expired; the built-in template, not a campaign-scoped role coded `gm` or `assistant_gm`) |
| 409 | `reveal_delegation_recipient_changed` | Grant only: the `gm` assignment or live delegations changed while the grant waited. Nothing was written and a retry is safe |
| 422 | (validation) | Shape or reason length |

**Semantics.**
- **Unkeyed.** An `Idempotency-Key` header is ignored, and there is no reservation or receipt replay. A repeat is idempotent **by state**: `granted: false` and `revoked: false` write nothing and no audit row. A repeat therefore **re-executes the command against whatever the state is by then**; it does not replay the first command's outcome. If another owner revoked (or granted) in between, a repeated grant (or revoke) would make a **new change the person did not just choose**. This plan therefore never presents a repeat as safe replay: an uncertain outcome is resolved by an authorized read of the current state, and any further write is a new, deliberate action (§8). Only the server's two refusals that say "nothing was written" (`reveal_delegation_recipient_changed`, 403, 404, 409 not-GM, 422) are known not to have changed anything.
- **Binding and ending.** A delegation is bound to one specific `gm` assignment. It is closed with an `end_reason` (`revoked_by_owner`, `gm_role_revoked`, `gm_role_changed`, `membership_ended`, `membership_status_changed`, `gm_assignment_lapsed`) by the revoke, by the role and membership commands, and by recovery. Regaining GM status needs a fresh grant.
- **An expired `gm` assignment is not closed when it expires.** Its delegation row stays unrevoked but authorizes nothing (`resolve_reveal_authority` compares it with the live assignment). It is closed as `gm_assignment_lapsed` only by a later grant (G-C).
- **Other rules.** Delegations survive an ownership transfer, and the new owner may revoke those the former owner granted. An owner who is also a GM may delegate to themselves (`test_an_owner_who_is_also_a_gm_can_delegate_to_themselves`).
- **Effect.** Reveal authority (`character.reveal`) is not a role capability. It is not in the bootstrap's `capabilities` and changes no bootstrap value. The grantee sees the change through S01's `can_release` and S02's `can_reveal` on their next read, and their next release or reveal is judged at a fresh instant.

### 2.2 Backend proofs that already exist (slice criteria)

| Criterion | Existing database test |
|---|---|
| A live built-in owner grants to a live built-in GM assignment | `test_character_reveal_delegation.py`: `test_an_owner_grants_revokes_and_regrants_with_one_audit_row_each`, `test_only_a_member_holding_the_builtin_gm_role_can_receive_a_delegation`, `test_a_gm_whose_membership_ended_or_account_is_inactive_cannot_receive_one` |
| A delegated GM cannot redelegate | `test_nobody_but_a_live_owner_can_grant_or_revoke`; route form in `test_r01_s5e6_reveal_delegation_routes.py` |
| A grant ends with its bound role | `test_a_delegation_binds_to_the_gm_assignment_and_cannot_be_revived`, `test_changing_a_gm_to_another_role_ends_the_delegation`, `test_ending_the_membership_ends_the_delegation_but_not_ones_it_granted`, `test_an_expired_gm_assignment_ends_authority_and_does_not_block_a_fresh_grant` |
| Stale-owner refusal | `test_a_caller_whose_owner_assignment_expires_during_the_wait_is_refused`, `test_a_grant_that_waits_on_a_relinquishing_transfer_is_refused_afterwards`; `test_r01_s5e6_final_authority.py` |
| Membership or role ending during a grant | `test_a_grant_that_waits_on_a_gm_role_revocation_is_refused`, `test_a_gm_role_revocation_that_waits_on_a_grant_closes_the_new_delegation`, `test_a_grant_that_waits_on_ending_the_gms_membership_is_refused`, `test_ending_the_gms_membership_while_a_grant_is_in_flight_closes_the_delegation` |
| Revocation, then the next reveal attempt | `test_character_revelations.py::test_a_revoked_delegation_and_an_outsider_are_refused`; `test_character_public_profile_api.py::test_a_revoked_delegation_or_gm_role_ends_future_release_but_keeps_earlier_releases`; `test_character_public_profile_concurrency.py::test_a_release_that_waited_for_a_delegation_revocation_is_refused_and_writes_nothing` |

S03 does not re-prove these. It adds portal cases (and, under OD-S03-1, read-route cases) that bind the UI to these outcomes.

### 2.3 What the client can learn today: the gaps

- **G-A: no read of delegation state.** No route returns delegations: the catalog has only the two POSTs, and `/access-overview` has no delegation field. The only evidence the portal can get is a write receipt. It cannot show who holds reveal authority, offer Revoke only where something is live, or show that a grant ended with its role.
- **G-B: no server value for eligibility or for the caller's authority.**
  - **Eligibility.** The overview's `members[].roles[]` carries `role_id`, `code` and `display_name`, with no built-in marker. A campaign-scoped role coded `gm` is allowed by the schema (`uq_roles_campaign_code` is per campaign, and templates have `campaign_id IS NULL`). No command creates one today, but the predicate `find_live_builtin_gm_assignment` deliberately excludes it. A client would also have to re-derive "live" from membership status, account activity and expiry.
  - **The caller's authority.** `access.manage` is not ownership: a custom manager is refused `403 campaign_owner_required`. The bootstrap's per-campaign `roles` are role **codes**, read when the session was read, with the same built-in ambiguity.
  - So any client rule would be a client-side authorization decision.
- **G-C: an unrevoked row is not necessarily live.** A row bound to an expired `gm` assignment stays unrevoked. Even a raw row read would need the server's comparison to say whether it authorizes.
- **G-F: an open row is not an effective delegation, and the owner needs to see both.** Today's revoke acts on **any open row of the grantee in the campaign** (`REVOKE_DELEGATION_LOCK` filters on `revoked_at IS NULL`, not on the live `gm` assignment), so an owner can already close a delegation whose bound `gm` assignment has expired. The only way such a row stays open is the expiry case of G-C: nothing closes it when it expires. A list of live GMs alone would hide it: the member is not listed (no live `gm` assignment), so the owner could not find the row to revoke it, and would learn of it only when a fresh grant closes it as `gm_assignment_lapsed`. S03 must not invent a lifecycle rule (no auto-close, no new end reason). It surfaces the state the server already holds, as **lapsed delegations**: open rows of members who hold no live built-in `gm` assignment. They authorize nothing (`resolve_reveal_authority` compares the bound row with the live assignment) and can be closed by the existing revoke route, with its existing semantics (`end_reason` `revoked_by_owner`). A member who **does** hold a live `gm` assignment and has a stale open row is listed with `delegation: null` (they cannot reveal); the next grant closes the stale row as `gm_assignment_lapsed`, as today, and the portal shows no separate entry for it.
- **G-D: misleading server message.** `campaign_owner_required`'s `safe_message` names the owner role. The portal must map by code and never render that message. No backend change is proposed, because the same error class serves the owner-role paths.
- **G-E (outside S03): no effective-access source.** The effective-access explanation does not list `character.reveal` sources. It is not proposed here (§3.3).

### 2.4 Portal at the baseline

- **No portal code calls `/reveal-delegations`** (grep of `portal/src`).
- **Access section.**
  - Three routes share `AccessTabNav`: `access` (management), `access/invitations` and `access/audit`. Each is registered in `App.tsx` and `navigation/routeMeta.ts` (`access.*`, parent `access.overview`) and listed in `AccessNavGroup`.
  - Each page mounts only while `useCampaignCapability(campaignId, "access.manage")` holds. Losing it unmounts the content and aborts its reads (C01 O-5 pattern, `CampaignAccessPage.tsx`).
  - The management page keeps one persistent `role="status"` announcement region above the overview boundary so that announcements survive the re-read.
- **Access write hooks** (`useRevokeMembershipRole` and others) finish through `useAccessWriteCompletion`. That helper reloads or refreshes the session because those writes can change the caller's bootstrap. A delegation write cannot (§2.1).
- **S02's `useAuthoringMutation`** gives per-scope attempts:
  - an owner-guarded settlement, so a superseded confirmation runs only `onSupersededSuccess`;
  - `discard()`, which leaves a target-free `withdrawn` unknown-outcome state;
  - retry of the same body;
  - an `idempotencyKey` handed to the request function. An unkeyed API function may decline to send it.

---

## 3. Outcome, scope and exclusions

### 3.1 User outcome

A new **Reveal authority** tab in the Access section serves anyone who may manage campaign access (subject to OD-S03-2). It lists every member who currently holds the built-in GM role and says, for each, whether they can reveal characters through a delegation, since when, and who granted it. It states that campaign owners can always reveal. Below that, any **lapsed delegation** (an open delegation of someone who no longer holds a live built-in GM role; it gives no authority) is listed separately, so it can be found and closed.

A **live campaign owner** can also:
- **grant** reveal authority to a listed GM, with a required private reason;
- **revoke** a live or lapsed delegation, with a reason.

Everyone else, including a custom access manager or a delegated GM who manages access, sees the list and one neutral line: "Only a campaign owner can grant or revoke reveal authority."

The list changes only when the server says so. A GM whose role ends drops out of the list on the next read, and their delegation is gone. If they become GM again they are listed as unable to reveal, with Grant offered.

### 3.2 In scope

- **The read contract chosen by OD-S03-1.** It must be read-only, with no table, lock, migration, write path or authorization rule.
- **T01 (read and offer).**
  - The types and API for the read.
  - The new tab route, route metadata, navigation entries and page.
  - The list, the owner explanation, the offer state (text only; no controls yet; see D-5), and read-failure, denial and scope handling.
- **T02 (grant and revoke).**
  - Keyless API functions for both POSTs.
  - Grant and revoke dialogs, receipts with their idempotent wording, and the mapped refusals.
  - Unknown-outcome handling, authority loss, supersession, focus and announcements.
- **Docs:**
  - ACCESS_CONTROL §3u (the read row, plus one "Portal:" sentence);
  - the catalog row in `identity-and-access.md` (the documentation check requires one row per registered route) and the count in `operations.md`;
  - one paragraph in [portal-behavior §6.4](../reference/portal-behavior.md#64-access-management).

### 3.3 Exclusions

- **Other work, not started here.**
  - S04 (denies), `copy-ui` and `preview`.
  - Any change to S01's or S02's behavior, records or tests.
  - Any change to the management tab's member cards, or to the overview contract unless OD-S03-1 chooses option B.
  - Effective-access sources for `character.reveal` (G-E).
  - A history of ended delegations (D-2).
- **Constraints on this slice.**
  - No change to either delegation write route, its locks, its refusals or its messages (G-D is handled by mapping).
  - No client-side authorization. The portal never decides eligibility or ownership from role codes, bootstrap roles or receipts.
  - No polling, push or timers.
  - No session reload or refresh after a confirmed delegation write; it changes no bootstrap value.
  - No `Idempotency-Key` header on the delegation POSTs. The server ignores it, and sending it would imply replay protection that does not exist.
  - The reason is never rendered after submission, because the server never returns it. Only the person's own unsent typing may be shown back.

---

## 4. Affected files and interfaces

Shown for OD-S03-1 = **A** (recommended). The §10 option B column lists what changes instead.

| File | T01 | T02 |
|---|---|---|
| `src/dnd_ai/queries/reveal_delegations.py` (new) | The read (§10, option A); one statement set, no locks, no writes | — |
| `src/dnd_ai/api/character_reveal.py` | `GET /campaigns/{campaign_id}/reveal-delegations`, same `access.manage` gate as the POSTs; DTOs | — |
| `tests/database/test_reveal_delegations_read.py` (new) | BD1–BD11 | — |
| `docs/api/ACCESS_CONTROL.md` §3u, `docs/api/identity-and-access.md`, `docs/api/operations.md` | Read row and catalog row; operation count | "Portal:" sentence |
| `portal/src/types/revealDelegations.ts` (new) | Read types: exactly the response keys | Request bodies and receipts |
| `portal/src/api/revealDelegations.ts` (new) | `getRevealDelegations` | `grantRevealDelegation` and `revokeRevealDelegation`, with no `Idempotency-Key`; errors carry status and code |
| `portal/src/pages/CampaignRevealAuthorityPage.tsx` (new) and `.test.tsx` | Page, list, offer text, L1–L12 | Dialogs and mutations, M1–M21 |
| `portal/src/App.tsx`, `navigation/routeMeta.ts`, `components/AccessTabNav.tsx`, `components/AccessNavGroup.tsx` | Route `access/reveal-authority`, meta `access.revealAuthority` (parent `access.overview`), tab, navigation child | — |
| `docs/reference/portal-behavior.md` §6.4 | — | One paragraph |

The C01 management page, its overview hook and its fixtures do not change under option A. Existing route-metadata and navigation tests that enumerate Access children may need one added entry. That is additive, and it is the only permitted change to existing tests.

---

## 5. Task commits

| Commit | Message | Cases |
|---|---|---|
| T01 | `P15-C02-S03-T01: show eligible built-in GM assignments and owner-only delegation availability from a server read` | BD1–BD11 (option A), L1–L12 |
| T02 | `P15-C02-S03-T02: grant and revoke reveal delegations through the existing endpoints with refreshed authority and role-loss handling` | M1–M21 |

The backend read is the first part of T01, in the same commit as its only consumer, so that no head exposes a field nothing reads. T01 renders the offer as text only, with no Grant or Revoke control (D-5), so no head carries a control with nothing behind it. Each commit passes §7.1 on its own and ends with the attribution lines.

---

## 6. Acceptance cases

Portal cases use jsdom with a mocked fetch, as S01 and S02 do. "Sent" means the fetch log. The response shape is OD-S03-1's (option A unless decided otherwise). Wording is D-3.

### 6.1 T01: read and offer (L1–L12)

| # | Case | Expected |
|---|---|---|
| L1 | Navigation | The **Reveal authority** tab appears in `AccessTabNav` and `AccessNavGroup` beside the others. A direct load of `/app/:campaignId/access/reveal-authority` works. The page sends exactly one `GET …/reveal-delegations` per mount, and no `/access-overview`, invitation or audit request. The other Access tabs never send it |
| L2 | Bootstrap without `access.manage` | The page shows the existing "Access unavailable" placeholder and sends nothing. If the capability is lost in place (O-5), the content unmounts, an in-flight read is aborted and nothing is published |
| L3 | Empty list | "No member currently holds the GM role." The static owner line still shows: "Campaign owners can always reveal characters." |
| L4 | Rows | One row per listed member, in server order. A delegated member shows "Can reveal characters", the grant date and "granted by {name}" (or "granted by a former member" when the name is null). Others show "Cannot reveal characters". No id, reason or role id is rendered |
| L5 | `can_manage: true` | The line "You can grant or revoke reveal authority." (The T02 controls attach here) |
| L6 | `can_manage: false` | The neutral line "Only a campaign owner can grant or revoke reveal authority." No control. Nothing is inferred from roles or the bootstrap |
| L7 | GET 403 or 404 | All content (names, dates, granters) is dropped and the unavailable placeholder is shown. One in-place session refresh is requested, so a lost `access.manage` also removes the tab. No retry loop |
| L8 | GET network error or 5xx | `StaleReadNotice` with Retry. A kept earlier list stays, marked out of date, and shows **no offer** (T02: no controls) until a read succeeds |
| L9 | Scope change | Moving to another campaign discards a late response. No row from campaign A appears under campaign B |
| L10 | Role ending reflected | The server's next answer omits a member whose GM role ended, and the page drops them. Mocked sequence: listed and delegated; then absent; then listed again with `delegation: null` (a new `gm` assignment, as after regaining the role) |
| L11 | No other surfaces | No `…/reveal-delegations` request from member cards, character pages, the public-profile page or the bootstrap path |
| L12 | Lapsed delegations | Each `lapsed_delegations` entry is listed apart from the GM rows under "Delegations that no longer apply": "{name} no longer holds the GM role, so this gives no authority.", the grant date and granter as in L4. An empty array renders no such section. Nothing says it was revoked or removed. Its Revoke control follows `can_manage` (T02) |

### 6.2 T02: grant and revoke (M1–M21)

**Offer rule.** Grant appears on a listed row with `delegation: null`, and Revoke on a row with a delegation. Both appear only when the last successful read returned `can_manage: true` and is not stale.

| # | Case | Expected |
|---|---|---|
| M1 | Grant dialog | A dialog naming the member, with a required reason (1–1000 characters, counted) and an error summary. Cancel sends nothing and returns focus to that row's Grant |
| M2 | Grant `granted: true` | Re-read, then announce in the page's persistent status region: "{name} can now reveal characters." The reason clears. Focus moves to that row's Revoke, or to the status region if the row is gone |
| M3 | Grant `granted: false` | Re-read, then "{name} already had reveal authority." Not an error |
| M4 | Revoke dialog | As in M1, with Revoke wording |
| M5 | Revoke `revoked: true` | Re-read, then "Reveal authority revoked for {name}." Focus moves to that row's Grant, or to the status region |
| M6 | Revoke `revoked: false` | Re-read, then "That member's reveal authority had already ended." |
| M7 | 403 `campaign_owner_required` (ownership transferred or relinquished, owner role revoked or expired, or a custom manager or delegated GM forcing the call) | Re-read. Controls follow the new `can_manage`. Message: "Only a campaign owner can grant or revoke reveal authority. Nothing was changed." The typed reason is shown back read-only. The server's `safe_message` is never rendered (G-D) |
| M8 | Other 403, or 404 | As L7: content is dropped, the dialog closes and its typed reason is discarded, and the session is refreshed in place. Announce "Reveal authority isn't available." |
| M9 | Grant 409 `reveal_delegation_recipient_not_gm` (GM role revoked or changed, or membership ended while the dialog was open) | Re-read. "That member no longer holds the GM role. Nothing was changed." The dialog closes |
| M10 | Grant 409 `reveal_delegation_recipient_changed` | Re-read. "Their GM assignment changed while this was being saved. Nothing was changed; review and grant again." The dialog stays open with the reason. Nothing is sent again automatically |
| M11 | 422 | The error summary. Nothing else changes |
| M12 | Network error or 5xx (unknown outcome), still authorized | The dialog closes and its typed reason is dropped. An alert: "We couldn't confirm whether your last change to reveal authority was applied." It names no member. **There is no Retry and no automatic re-send** (§2.1: a repeat would be a new change against whatever the state is by then). **Check current reveal authority** sends only the GET. After a good read: "The list shows current reveal authority. It doesn't show whether your last attempt made the change." After a failed read: "That says nothing about whether the change was applied." **Dismiss** clears the alert. The owner may then open a dialog and act again, as a new deliberate action (a new attempt) |
| M13 | Authority loss around an uncertain attempt: pending, then loss (re-read gives `can_manage: false`, or the member leaves the list), or an already-ambiguous attempt, then loss | A pending attempt is withdrawn (`discard()`) and, if its answer is then lost, shows the same target-free alert; an already-ambiguous attempt keeps the alert (the hook keeps it as a withdrawn unknown outcome). Check stays (a read only, while authorized to read). Restoring authority restores nothing: no controls return until a successful read says `can_manage`, and no old intent is repeated. Loss of the page's read right (L2, L7) drops the page, including the alert |
| M14 | Pending, then navigation or a campaign change | The response is discarded: no announcement, no row change, no focus move. Scope keys are `reveal-delegation-grant:{campaign}:{membership}` and `reveal-delegation-revoke:{campaign}:{membership}` |
| M15 | Superseded confirmation | An older confirmed attempt after a same-scope reset and replacement runs only `onSupersededSuccess`, which re-reads. The replacement's form, announcement, focus and status stay its own (the R-S02-4b contract). Real callbacks are supplied in the test |
| M16 | Requests | Grant sends exactly `{grantee_campaign_membership_id, reason}` and revoke sends exactly `{reason}`, to the §2.1 paths. Neither sends an `Idempotency-Key` header. After an unknown outcome the next write is sent only after the owner opens the dialog and submits it again (M12); the same request is never re-sent by the page |
| M17 | No session churn | A confirmed grant or revoke triggers no session reload or refresh, and no `/access-overview`, `/effective-access` or bootstrap request; only the page's re-read |
| M18 | Self-delegation | An owner who is also a listed GM may grant to themselves; the row behaves like any other. The portal adds no self-marker (no field carries one) |
| M19 | Delegated GM cannot redelegate | A session whose read returns `can_manage: false` (a delegated GM with a custom manager role) sees no controls. A forced call's 403 is handled by M7 |
| M21 | Revoking a lapsed delegation | Revoke on a lapsed entry sends the same revoke request; `revoked: true` re-reads, then announces "Reveal authority revoked for {name}." and the entry leaves the list. `revoked: false` announces "That member's reveal authority had already ended." It follows the owner-only rule (M7 on refusal). Nothing is described as an automatic ending |
| M20 | The next reveal attempt | Not a portal case on this page. It is covered by the §2.2 backend tests and S02 V18 (a 403 `character_reveal_required` withdraws the reveal controls). The persona check is in §7.3 |

### 6.3 Backend read cases (OD-S03-1 = A; database tests)

| # | Case | Expected |
|---|---|---|
| BD1 | A live owner reads | 200, `can_manage: true`. `members` is exactly the members with a live built-in `gm` assignment |
| BD2 | A custom `access.manage` holder who is not an owner | 200, `can_manage: false`, same members (under the OD-S03-2 default) |
| BD3 | Gate | A delegated GM without `access.manage`, or a player: refused by the gate (403). A non-member, or an archived campaign: 404 |
| BD4 | Eligibility | Not listed: `assistant_gm`; a campaign-scoped role coded `gm` (fixture); an expired or revoked `gm` assignment; an ended or non-`active` membership; an inactive account |
| BD5 | Delegation is shown only when it is effective | `delegation` is non-null exactly when an unrevoked row is bound to the member's live `gm` assignment, which for a non-owner is `resolve_reveal_authority(member) == "delegation"` (an owner who is also a GM resolves to `owner` first, so the case compares the bound row, and the oracle for owners is the row itself). A member whose bound assignment expired is not in `members`. After they get a new `gm` assignment they are listed with `delegation: null` while the old unrevoked row remains, and that stale row is **not** in `lapsed_delegations` |
| BD11 | Lapsed delegations | An unrevoked row of a member with no live built-in `gm` assignment (expired assignment; inactive account) appears in `lapsed_delegations` with the member's name, grant date and granter, and the member is absent from `members`. A closed row never appears. A stale row of a member who holds a new live `gm` assignment is excluded. After the existing revoke route closes it, the next read omits it. The set is campaign-scoped |
| BD6 | Endings | After a revoke, a GM-role revoke or change, or a membership end, the member's delegation is null or the member is absent |
| BD7 | Transfer | Delegations survive. `granted_by_name` is the former owner. The new owner reads `can_manage: true`, and the former owner reads `can_manage: false` |
| BD8 | Disclosure | The response keys are exactly the contract's, at every level. No reason, revocation reason, `gm_membership_role_id`, delegation id, user id or ended row |
| BD9 | Campaign isolation | Another campaign's members and delegations never appear |
| BD10 | Read-only | The read writes nothing (no row change, no audit row) and takes no row lock |

Under option B the same cases apply to the overview fields, plus the existing overview tests unchanged apart from fixtures.

---

## 7. Verification

### 7.1 Automated checks (per commit, by Sonnet; again by the independent reviewer)

- **From `portal/` in PowerShell:** `npm test` (with counts), `npm run lint` and `npm run build`. Also run `npx vitest run src/pages/CampaignRevealAuthorityPage.test.tsx` plus the touched navigation and route-metadata tests, and report the counts separately. S01's and S02's focused suites must still pass unchanged (the 150 tests of [S02 §11.14](p15-c02-s02-revelations-plan.md#1114-independent-confirmation-of-r-s02-4a-and-r-s02-4b-codex-2026-11-21)).
- **Backend (T01):**
  - `uv run pytest tests/database/test_reveal_delegations_read.py tests/database/test_character_reveal_delegation.py tests/database/test_r01_s5e6_reveal_delegation_routes.py`;
  - `ruff format --check`, `ruff check` and `mypy src`;
  - the shard runner `uv run python scripts/run_sharded_tests.py`, because a route is added. Include `tests/unit` route-manifest tests: if a unit test classifies every registered route, add the GET where reads belong and report it.
- **From the repository root:** `uv run python scripts/check_documentation.py` (it fails without the new catalog row) and `git diff --check`.
- **Mutation probes** (at least one per commit, restored, with SHA-256 recorded before and after):
  - T01: derive `can_manage` on the client, or render a kept stale list with its offer. L6 or L8 must fail. A backend probe: return an unrevoked row bound to an expired assignment as live. BD5 must fail.
  - T02: send an `Idempotency-Key`, or keep Retry after authority loss. M16 or M13 must fail.
- **Recording runs:** report first runs and reruns separately. A full-suite failure is recorded as it happened, and an isolated rerun is not a suite pass (as in S01 and S02).

### 7.2 Checkpoint gate (C02)

C02 merges only as in §1.3, with S01 to S04 each independently reviewed, the PR acceptance cases passing, and CI on the integration head. This plan claims no merge readiness. A green PR #71 run belongs to its head only.

### 7.3 Separate events (not this slice's review verdict, and not C02 merge gates)

- **Persona browser checks** at the final integrated head, under [browser](work-register.md#browser):
  - the owner grants to a GM, and that GM's next reveal succeeds;
  - the owner revokes, and the GM's next reveal is refused;
  - the GM's role is revoked on the management tab, and the delegation is gone on the Reveal authority tab;
  - a custom manager reads only.
- **AT checks** under [ax](work-register.md#ax) and [b16](work-register.md#b16): tab navigation; dialog focus trap and return; the reason error summary; announcements in the persistent region; the unknown-outcome alert; reflow at 320 CSS px and at actual zoom.
- **Owner acceptance** at [actor-a](work-register.md#actor-a) and [p15-owner](work-register.md#p15-owner).

None of these is performed, accepted or waived here.

---

## 8. Authorization, disclosure, concurrency and cleanup

- **Server-authoritative availability.**
  - The page mounts only while the bootstrap grants `access.manage`.
  - The read is gated by the server. Controls follow `can_manage` from the last successful read, and rows follow the server's eligibility.
  - Every write is judged again by the server at a fresh instant (§2.1).
  - Owner status, built-in GM eligibility and effective-delegation state are computed on the server with the same predicates the commands use, at read time. The portal never derives them.
  - The client never decides from role codes, bootstrap roles, receipts or ownership records.
- **Disclosure.**
  - Render only the names the read carries; never ids, reasons or role ids. The read carries no delegation id.
  - Error text comes only from mapped codes (G-D).
  - The 404 causes are not told apart.
  - Under the OD-S03-2 default, delegation status is visible to `access.manage` holders, who already see roles and revelations.
- **Stale responses and navigation.**
  - Reads are scoped by campaign, and mutations by campaign and member.
  - A late answer for another scope is discarded, and the page remounts on a campaign change.
  - A superseded confirmation only re-reads (M15).
  - Every write re-reads, so the owner never acts on a row the server has changed.
- **Authority loss.**
  - Bootstrap loss unmounts everything (L2).
  - A read 403/404 drops everything and refreshes the session in place (L7).
  - A write 403 `campaign_owner_required` withdraws the controls after the re-read (M7).
  - Another 403/404 follows L7 (M8).
  - A role or membership ending shows up as the member leaving the list (L10, M9).
- **Pending and uncertain writes; retry ownership.**
  - One `useAuthoringMutation` instance per scope owns its attempt. Only the owning attempt publishes status, announcement and focus.
  - Unkeyed means a repeat re-executes against the current state and does not replay (§2.1). So the page offers **no Retry**: an attempt that ends in a network error or a 5xx is made non-retryable at once (`discard()`, which keeps a target-free `withdrawn` unknown outcome), with an alert, an authorized state check and Dismiss (M12, M13).
  - A further write is a new attempt chosen deliberately after the owner has looked at the current state. Nothing is retried automatically, including `reveal_delegation_recipient_changed` (M10), whose message says nothing was changed and leaves the choice to the owner.
- **Protected-state cleanup.**
  - On read 403/404 or capability loss, drop the members, names, dates, granters, open dialogs and typed reasons.
  - On a re-read that no longer lists a dialog's member, close that dialog.
  - Show back only the person's own typing, and only while they stay authorized to read the page (M7). Never show it after a drop (M8).
- **Focus and announcements.**
  - One persistent `role="status"` region above the read boundary, as on the management tab, carries success and refusal text and survives the re-read.
  - The unknown-outcome text is an alert.
  - Focus moves to the acting row's counterpart control, or to the status region when the row is gone.
  - Dialogs trap focus and return it on cancel.
  - Starting a new operation clears a stale announcement.

---

## 9. Intermediate states

- **After T01:** a read-only tab and the backend read. Nothing changes for any authority, and there are no controls.
- **After T02:** the full slice.
- **Neither task** changes S01, S02, the management tab's member cards (under option A), the write routes, or any audience read.

---

## 10. Decisions

### OD-S03-1 (owner decision, blocking both tasks): the read contract for delegation state, eligibility and owner authority

**Option A (selected, §10.1): a new read-only `GET /campaigns/{campaign_id}/reveal-delegations`.** Same `access.manage` route gate as the two POSTs. The concrete contract (the refined one, §10.2):

```
{
  "can_manage": bool,
  "members": [
    {
      "campaign_membership_id": uuid,
      "display_name": str,
      "delegation": null | { "granted_at": timestamptz, "granted_by_name": str | null }
    }
  ],
  "lapsed_delegations": [
    {
      "campaign_membership_id": uuid,
      "display_name": str,
      "granted_at": timestamptz,
      "granted_by_name": str | null
    }
  ]
}
```

- **`can_manage`:** the caller holds a live built-in owner assignment (`find_live_builtin_owner_assignment`, unlocked, at read time), the predicate the D3 gate uses.
- **`members`:** every membership with a live built-in `gm` assignment (the `find_live_builtin_gm_assignment` definition, as one set query, the lowest `membership_role_id` per member as that function chooses), ordered by display name, then membership id. `display_name` is the account's display name, as in the access overview.
- **`delegation`:** non-null only when an unrevoked row is bound to that live assignment, so the delegation authorizes (for a non-owner, exactly `resolve_reveal_authority == "delegation"`); otherwise null. `granted_by_name` is the granting membership's account display name, or null when that membership no longer exists.
- **`lapsed_delegations`:** every unrevoked row of this campaign whose grantee holds **no** live built-in `gm` assignment (G-F). It authorizes nothing and can be closed by the existing revoke route. A stale row of a member who does hold a live `gm` assignment is not listed (the member is in `members` with `delegation: null`). Order: display name, then membership id.
- **Not returned:** reasons, revocation reasons, delegation ids, `gm_membership_role_id`, user ids, ended rows and end reasons.
- **What it is not:** it adds no table, lock, migration, write or authorization rule, and it is read-only. It invents no lifecycle rule: it reports what the server already holds.
- **Cost:**
  - a query module, a route and DTOs, BD1–BD11, and a shard run;
  - a catalog row, which the documentation check requires, the `operations.md` count, and a §3u row.
- **Why this one:** only S03 consumes it. The C01-reviewed overview contract and its roughly 20 portal fixture files stay untouched. It follows the Access sub-tab rule that "neither sibling route fetches another's data".

**Option B: the same fields on `GET /access-overview`.** A top-level `can_manage_reveal_delegations`, and a per-member `reveal_delegation: {eligible, delegation}`.
- **Gain:** one read, and the management tab's existing re-read after a role change refreshes delegation status too. S03's UI would sit in each member card instead of a tab.
- **Cost:**
  - it changes C01's reviewed contract, which the overview's other consumers also read (S02's target options among them);
  - about 20 portal fixture files and the overview's backend tests must change;
  - the payload grows for every consumer.

**Option C (not admissible): no backend change.**
- **How it would work:** eligibility from overview role codes (`code === "gm"`) plus `status_code` and `account_is_active`; ownership from bootstrap `roles`; state from receipts only.
- **Why not:** it makes the client decide authority, contrary to [Phase 15 exit criterion](roadmap.md#159-phase-15-exit-criteria) "All portal write options come from server-authoritative catalogs and capabilities". It cannot tell a built-in `gm` from a campaign-scoped `gm` (G-B) or a lapsed row from a live one (G-C). It cannot show who holds a delegation (G-A), so it cannot meet the slice criterion that "a grant ends with its bound role" as the user sees it.

**Consequence of each.** A gives correct behavior plus a small, isolated backend read. B gives the same correctness with wider churn in reviewed C01 surfaces. C is not admissible.

### 10.1 Owner decisions recorded 2026-11-21

- **OD-S03-1 = option A.** The dedicated read-only `GET /campaigns/{campaign_id}/reveal-delegations` endpoint.
- **OD-S03-2 = retain `access.manage` for reading and the existing current-owner authorization for writes.** The default below applies.
- **Scope of these decisions.** They authorize the bounded backend read contract and its portal consumption only. They add **no write authority**, change neither write route, and add no lifecycle rule.

### OD-S03-2 (owner decision, default applies): who may read the delegation state

- **Default (recommended):** every `access.manage` holder may read, the same gate as the POSTs and the overview. Custom managers already see roles and revelations there. Only `can_manage` holders get controls.
- **Alternative:** the read is owner-only, and other callers get 403. Custom managers then see nothing and need another signal to hide the tab, which this plan would have to add.

### Plan decisions (recommendations; not blocking)

| ID | Decision | Recommendation |
|---|---|---|
| D-1 | Placement | Under option A: a fourth Access tab, **Reveal authority**, at `access/reveal-authority`. Under option B: a "Reveal authority" line in each member card's Roles section |
| D-2 | Ended delegations | Not listed in S03. Grant and revoke audit rows remain in Access audit. A history list is a follow-up candidate |
| D-3 | Wording | As quoted in §6. The owner may reword without changing the cases |
| D-4 | G-D message | Map `campaign_owner_required` to this page's own wording and never render the server message. No backend message change |
| D-5 | T01 "owner-only delegation actions" | T01 renders the offer (L5/L6) as text and the backend's `can_manage`, but no buttons, so no head has a dead control. T02 attaches the controls |

### 10.2 Refinements made before implementation

1. **Open versus effective (G-F).** The earlier contract listed only live GMs, so an open delegation row of a member whose `gm` assignment expired could not be identified or revoked from the portal, although the revoke route can close it. The read now returns `lapsed_delegations` beside `members`. This surfaces existing state and uses the existing revoke semantics; it adds no end reason, no auto-close and no authorization rule. Cases L12, BD11 and M21 cover it.
2. **Repeated writes (§2.1).** Both writes ignore `Idempotency-Key`, so a repeat re-executes against the current state. The earlier text offered Retry as a same-command replay. That is dropped: an unknown outcome gets an alert, an authorized state check and Dismiss, with no Retry and no automatic re-send (M12, M13, M16). The hook's `discard()` makes every ambiguous attempt non-retryable at once, and its withdrawn-error state carries the target-free notice.
3. **Server derivation.** `can_manage`, GM eligibility and the effective delegation are all server-computed with the commands' own predicates (§8). The delegation id is dropped from the read (the portal revokes by membership), and `lapsed_delegations` is derived the same way.
4. **BD5 wording.** An owner who is also a GM resolves to `owner` in `resolve_reveal_authority`, so `delegation` is defined by the bound row for owners (M18), and by `resolve_reveal_authority == "delegation"` for everyone else.

### Gaps

- **G-A, G-B and G-C:** disposition is OD-S03-1 (option A, recorded in §10.1).
- **G-F:** disposition is §10.2 item 1 (`lapsed_delegations`).
- **G-D:** disposition is D-4.
- **G-E:** out of scope, and a follow-up candidate.

No other DTO field is proposed.

---

## 11. Handoffs

### 11.1 Sonnet implementation instructions

1. Start on `phase15/completion` at the commit that records this plan **and** OD-S03-1. Record that SHA as the base, and record `git status --short`. Preserve unrelated work. Do not push, change PR #71, merge, or start S04, `copy-ui` or `preview`.
2. Re-check §2.1 to §2.4 at the base. If anything differs, stop and report.
3. **T01.**
   - The backend read per the recorded OD-S03-1 option, with BD1–BD11.
   - Then the portal: §4's T01 column, with L1–L12.
   - Run §7.1, including the shard runner, and commit.
4. **T02.**
   - §4's T02 column, with M1–M21.
   - Reuse `useAuthoringMutation`: its `onSupersededSuccess` and `discard()`, and a request function that ignores the key.
   - Reuse `StaleReadNotice`, the persistent status-region pattern and the focus handoff.
   - Run §7.1 and commit.
5. **Rules.**
   - Never infer eligibility or ownership.
   - Never render server messages, ids or reasons.
   - No `Idempotency-Key` header on the delegation POSTs.
   - No session reload after delegation writes.
   - No polling.
   - No change to S01 or S02 behavior or tests, or to the write routes.
   - Existing classes only, unless a reflow defect requires CSS.
6. Append §11.3 with:
   - the base and the commit SHAs;
   - the commands, with counts, first runs and reruns separate;
   - the probes with SHA-256;
   - any deviation and its reason.

   Set the S03, T01 and T02 register cells to "Implemented; independent review pending".

### 11.2 Independent review boundary

- **Range.** Base = the commit that records this plan and OD-S03-1. Head = T02, or the last correcting commit. Review the slice whole, and each commit on its own.
- **Required evidence.**
  1. The read matches the recorded OD-S03-1 contract, with no lock, write or authorization change. BD1–BD11 pass, including BD5 against `resolve_reveal_authority`.
  2. By reading, the controls follow only `can_manage`, and the rows only the server list (no client rule), and nothing renders a server message, id or reason.
  3. The cleanup and authority-loss paths of §8 (L2, L7, M7, M8, M13).
  4. Unkeyed retry ownership: M12 and M13. No key is sent, and a withdrawn attempt cannot be replayed.
  5. Run §7.1 and map L1–L12, M1–M21 and BD1–BD11 to tests.
  6. At least one independent mutation probe per commit, restored, with SHA-256 recorded.
  7. The §3.3 exclusions were not entered, and S01's and S02's tests are unchanged.
- **Verdict.** Use the [rubric](grading.md#severity-and-checkpoint-disposition). Keep new findings distinct from S01's and S02's closed findings (F1, F2, F1-R1, R-S02-1 to R-S02-5, R-S02-4a, R-S02-4b). §7.3 events are not part of the verdict.

### 11.3 Implementation record (Sonnet; independent review pending)

**Base and commits.** Planning and implementation-review baseline: `9d410b69246e86776964a1fe90bfd8978aebfdac` (this plan, refined, with OD-S03-1 = option A and OD-S03-2 recorded; the head of `phase15/completion` before it was `3381f7e69ba17d8dc9ef20008c047569056d4e00`; the worktree held only this plan and the register edits). Commits after it, in order:

| Commit | SHA |
|---|---|
| T01: `P15-C02-S03-T01: show eligible built-in GM assignments and owner-only delegation availability from a server read` | `7f175dd90625ef7f71185613579c36d63ffbd00c` |
| T01 correction found by the shard run (the Phase 15 acceptance guard pins the number of `access.manage` routes: 247 to 248) | `5e1a22e2e8fb0c6876d9c669684b4151c2974f61` |
| T02: `P15-C02-S03-T02: grant and revoke reveal delegations through the existing endpoints with refreshed authority and role-loss handling` | `08b51444f68ebecbef6416e89952034499667c89` |

The records commit and the final head are reported in the report for this task (a record cannot name its own commit). Review range: `9d410b69246e86776964a1fe90bfd8978aebfdac..<records head>`; each commit is also reviewable alone. The records commit changes documentation only.

**Re-check of Sections 2.1 to 2.4 at the base.** Unchanged, with one added fact (G-F, now Section 2.3): the revoke route closes any open delegation of the grantee, so a lapsed delegation can be closed through the existing route. S01, S02, the write routes and their tests were not changed.

**What was built.**
- Backend (T01): `queries/reveal_delegations.py` (one set read, no lock, no write) and `GET /campaigns/{campaign_id}/reveal-delegations` in `api/character_reveal.py`, with the Section 10 contract: `can_manage`, `members` (live built-in GMs with an effective `delegation` or null) and `lapsed_delegations` (G-F). The catalog row, the operation count (349 on 333 paths), ACCESS_CONTROL §3u and `tests/scenario/test_phase15_acceptance_guards.py` (pinned count) were updated.
- Portal (T01): types, the `access/reveal-authority` route, route metadata, tab and navigation entries, and the read-only page. (T02): grant and revoke API functions that send no `Idempotency-Key`, the dialogs, receipts, refusals, unknown-outcome handling and focus; `portal-behavior.md` §6.4.

**Deviations from the plan, with the reason.**
1. **Mutation scope keys** are per campaign (`reveal-delegation-grant:{campaign}`, `…-revoke:{campaign}`), not per member. The unknown-outcome notice must outlive the dialog that closes when the member changes, and one write is in flight at a time. The page is keyed on the campaign.
2. **Announcements** use the shell's existing announcer (`useAnnounce`, the convention S01 and S02 reviewed), not a page-owned status region, because the page does not unmount across its re-read. Focus falls back to the page heading, not a status region.
3. **Controls** use an `aria-label` that contains the visible word ("Grant reveal authority to {name}") rather than visually hidden text, because the accessible name of the hidden-span form lost its separating space.
4. **L8's kept-stale list and L10's role-ending sequence** are tested in the write suite (they need a re-read, which only a write or Check triggers); L10 is exercised by the dialog-closing case and by T01's remount sequence. **M15** (a superseded confirmation) is a hook lifecycle case that this page cannot produce (it never resets and replaces a write); the page supplies `onSupersededSuccess` (re-read only) and the hook's own tests cover the contract with real callbacks. **M20** is not a page case (Section 6.2).
5. **Authority loss while a write is pending** is reachable only through the loss of `access.manage`, which unmounts the page and aborts the request (tested). A read that returns `can_manage: false` while a write is pending cannot occur, because nothing re-reads then. An earlier draft had an effect for it; it was removed as dead code.

**Acceptance coverage.** Backend `tests/database/test_reveal_delegations_read.py` (11 tests): BD1 to BD11. Portal `CampaignRevealAuthorityPage.test.tsx` (14): L1 to L12 (L2 twice, L7 for 403 and 404, L8 first read, L11 by a source scan). `CampaignRevealAuthorityPage.write.test.tsx` (23): M1, M2 (with M16, M17), M3, M4, M5, M6, M7, M8 (403 and 404), M9, M10, M11, M12 (network error, 500, revoke), M13 (already-ambiguous, then loss and restoration; pending then loss of `access.manage`), M14, M18, M19, M21, the confirmed-write failed re-read, and the closing of a dialog whose member leaves the list. Required unknown-outcome behavior is covered: no Retry, a target-free alert, Check reads only, Dismiss then a fresh submission without a key, and no replay.

**Verification (first runs and reruns recorded separately).**
- Backend, T01: `uv run pytest tests/database/test_reveal_delegations_read.py` 11 passed (also at the final head with the guard change, in the 45-test run below). `ruff format --check`, `ruff check` and `mypy src` passed. `scripts/check_documentation.py` and `git diff --check` passed at each commit. `tests/unit`: 2407 passed and 1 failed, `test_config.py::test_local_session_allowed_origins_defaults_to_dev_topology_outside_production`; it fails identically with all S03 changes stashed (a local environment setting), so it is not caused by S03.
- Portal, T01 head: focused page tests 14/14; `npm run lint`, `tsc -b` and `npm run build` passed; full `npm test` 436 files, 5434 tests passed.
- Portal, T02 head: focused S02/S01/hook/S03 suites (7 files) 187 passed (the 150 of S02 §11.14, unchanged, plus 14 and 23); `npm run lint`, `tsc -b` and `npm run build` passed; full `npm test` 437 files, 5457 tests passed on its first run.
- **Sharded backend, run 1** (`uv run python scripts/run_sharded_tests.py`, four shards, at the T01 commit with the T02 portal work in the tree; a portal test run overlapped it): FAILED, 11321 passed, 6 skipped, 3 failed. `tests/scenario/test_phase15_acceptance_guards.py::test_the_manifest_covers_every_phase15_family_and_its_size_is_pinned` (a real consequence of the new route: 248 guarded routes against a pinned 247; fixed in `5e1a22e`), `tests/database/test_deadline_diagnostics.py::test_a_gate_that_is_never_reached_reports_the_stalled_request_before_teardown` and `tests/database/test_r01_s5b_invitation_acceptance_lock_order.py::test_an_open_membership_created_while_acceptance_holds_an_ended_one_is_used_not_the_ended_one`. The 45 tests of those three files then passed in isolation (not a suite pass).
- **Sharded backend, run 2** (at the T02 commit, nothing else running): FAILED, 11321 passed, 6 skipped, 3 failed: `tests/database/test_deadline_diagnostics.py::test_a_gate_that_is_never_reached_reports_the_stalled_request_before_teardown` again, and two timing-gate tests in `tests/database/test_r01_e4_reference_corpus.py` (`test_a_lapse_before_the_final_check_refuses_rolls_everything_back_and_a_retry_succeeds[revoke-campaign_archived-final]` and `test_a_role_or_membership_change_arriving_during_the_request_commits_after_it[role_revoked-query]`: "gate not reached after 16 s", no backend non-idle). Those two files then passed in isolation, 102 tests. The pinned-count failure did not recur. **There is no fully passing sharded run**; the isolated reruns are not a suite pass, and the deadline-diagnostics test failed in both runs (it passes alone, and S03 touches nothing it covers). No shard was rerun a third time.
- **Mutation probes (restored, SHA-256 recorded before and after).** `queries/reveal_delegations.py` (`59AF05C6622C675C6E8A07C1A42496E0D08387156545688846BF0F556D9FEF1F`) with the effective-delegation join condition removed: BD5 failed (1 failed, 10 passed); restored to the same hash. `pages/CampaignRevealAuthorityPage.tsx` at T01 (`2758981D18828BD4DC17F316E94F62B31F0FBB3530C3315ADAB299624E69ABBA`) showing the owner line for every caller: L6 failed; restored to the same hash. T02: `api/revealDelegations.ts` (`4F97DC7E4AF68F2DAC425A26B096D459285AECACE6B9327A7AE0FD74BA3F084B`) sending an `Idempotency-Key`: 4 write tests failed (M2/M16, M5, M12 among them); `pages/CampaignRevealAuthorityPage.tsx` (`70D47B14DEAF2B70D06B99B19057E82E9D66242F8136A7580996C936F3151743`) without making an ambiguous failure non-retryable: 3 failed (both M12 cases and one more); each restored to the same hash.

**Limits.** No browser, zoom, screen-reader or assistive-technology check (the alerts are tested through their `alert` role and text); no persona, human, `actor-a`, owner or final integrated-head evidence; the persona flow of Section 7.3 (an owner grants, the GM's next reveal succeeds) is not exercised here. Existing backend tests (Section 2.2) establish the unchanged grant, revoke and authority behavior; no write route, lock or authorization rule changed. The unrelated `test_config.py` failure is a local environment issue on this machine. PR #71 stays draft and unmerged.

### 11.4 Independent implementation review of T01, T02 and combined S03 (Codex, 2026-11-21)

**Boundary and state.** Reviewed the planning baseline and complete range `9d410b69246e86776964a1fe90bfd8978aebfdac..98b023895f6a3ac58aec40c524a7e40180f06d70`, including the T01 implementation `7f175dd90625ef7f71185613579c36d63ffbd00c`, route-count correction `5e1a22e2e8fb0c6876d9c669684b4151c2974f61`, and T02 implementation `08b51444f68ebecbef6416e89952034499667c89`. The final records/head commit is `98b023895f6a3ac58aec40c524a7e40180f06d70`. Branch `phase15/completion`; HEAD matched that full SHA; worktree was clean before this record edit. No applicable `AGENTS.md` was present. No production code was changed in this review.

**Verdict: T01 PASS WITH VERIFICATION LIMITS; T02 PASS WITH VERIFICATION LIMITS; combined S03 PASS WITH VERIFICATION LIMITS.** No implementation finding meeting the grading rubric was established. The two historical local sharded runs remain failed runs; neither is represented as a pass. Current exact-head PR CI completed successfully across all eight shards, which is the available full sharded result for this reviewed range. S01/S02 behavior and records remain intact.

**T01 — read contract and route guard.** The new GET has the existing `access.manage` route dependency. Its `can_manage` flag calls the same `find_live_builtin_owner_assignment` used by the write authorization, so a custom access manager may read under OD-S03-2 but receives `false` and no controls. `_LIVE_GM` matches `find_live_builtin_gm_assignment`: built-in template (`roles.campaign_id IS NULL`), active role, unrevoked/unexpired assignment, open active membership and active account; it chooses the lowest assignment id as the shared predicate does. Effective delegation is projected only for an open row bound to that exact assignment. The separate lapsed projection includes open rows whose member has no live built-in GM assignment, letting an owner find and revoke expired/inactive grantees without inventing an automatic close or new lifecycle state. The DTO omits reasons, delegation/role ids, user ids and ended rows.

The handler calls a read-only query: no command, lock, insert, update or audit. Documentation lists the GET as an additional method/path operation (349 total on 333 paths); the Phase 15 guarded-route total rises by one (247 to 248). The one-line correction in `5e1a22e` updates the existing pinned count for that actual route. It is supported by OpenAPI/route-manifest classification and is not an arbitrary test adjustment.

**T02 — owner operations and lifecycle.** The page gates the entire data body by the currently applied campaign `access.manage` capability and keys it by campaign. Losing that capability unmounts the body, clearing names, dialogs, typed reasons and mutation state; a restored capability mounts a fresh page and read. Within the authorized read, `can_manage` comes from the server and independently gates controls. The UI never infers owner or GM eligibility from role labels, bootstrap roles or receipts. Current-list entries and lapsed entries expose the expected grant/revoke actions; lapsed revocation uses the existing route and accurately says the delegation already grants no authority.

The grant/revoke API functions submit only the contracted body and do not forward the shared hook's generated idempotency key. No Retry control or automatic write replay exists. Network/5xx outcomes discard the body/key and show target-free unknown-outcome feedback; Check issues only the authorized GET and explicitly does not establish the write outcome. Dismiss followed by a new deliberate form submission sends a new request. Definitive refusals retain their distinct messages, and confirmed receipts trigger a list re-read without session/bootstrap churn. A read denial or lost `access.manage` drops the protected page; a loss of owner operation authority is handled by the server's `campaign_owner_required` refusal and a fresh read. Pending route changes/unmount abort the writes. Grant and revoke each provide their own read-only `onSupersededSuccess`, and the campaign-keyed page prevents cross-campaign callback reuse.

**Interaction and recorded deviations.** Native `ConfirmDialog` provides the required reason, Escape/cancel behavior and disabled pending actions; its cancel tests verify return to the invoking Grant/Revoke control. Success tests verify the member counterpart focus, shell announcements, and named action buttons. For a removed row, the page focuses its connected, programmatically focusable Reveal authority heading if focus fell to `body`; if focus remains on another element it leaves that focus alone. This deliberately differs from the plan's proposed status-region focus fallback. The shell announcer is a persistent `aria-live="polite"` region and survives the list re-read; it is not `role="status"`, and the implementation does not provide a page-owned status region. I accept these as nonblocking interaction deviations: the shell region announces the outcome, while the heading supplies meaningful context when the original action no longer exists. Actual screen-reader behavior remains unverified.

The five implementation deviations were assessed as follows: (1) campaign-level, rather than per-member, mutation scopes are appropriate because the page is campaign-keyed, permits one write at a time, and must retain an unknown outcome after its dialog closes; (2) the persistent shell live region survives the re-read, with the heading fallback noted above; (3) explicit accessible names retain the visible Grant/Revoke verb and target name; (4) L8/L10 refresh sequences are in the write/remount tests and M15 is covered by the shared-hook callback test plus actual section callback inspection; (5) loss of `access.manage` unmounts the page, while owner-only authority loss is discovered by the existing write refusal/read path. These deviations add no authorization, lifecycle or replay rule.

**Owner-to-GM integration.** The existing backend contract and tests establish that a live built-in owner can grant a delegation, that authority is bound to the specific built-in GM assignment, and that S01/S02 evaluate the resulting authority on subsequent requests. The new page's submit/re-read behavior was tested with a fake server, not a real owner/GM session. The planned owner-grant then GM-next-reveal persona/browser run has not been performed; this is a remaining integration acceptance check, not evidence of a runtime defect.

**Shard failures and evidence.** §11.3 records both local sharded runs separately and in detail. Run 1 failed 3 of 11,330 collected tests: the pinned route count (real and corrected by `5e1a22e`), `test_deadline_diagnostics.py::test_a_gate_that_is_never_reached_reports_the_stalled_request_before_teardown`, and an R01 S5b invitation-lock timing test. Run 2, with no other task running, again failed the deadline-diagnostics gate and two R01 E4 gate-arrival tests; the pinned count did not recur. The recorded symptoms were gates not reached within 16 seconds/no backend non-idle, not S03 assertion failures. The implementer reports the affected files passed isolated reruns; in this review the four named failure cases also passed together in isolation (4 passed). The S03 commits do not touch those deadline/R01 tests or their command paths. No raw shard log artifacts were retained beyond the detailed §11.3 run summaries, so I cannot attribute the repeated local gate failure to a specific timing or environment cause. I do not call either local shard run passed or diagnose timing solely from isolated success.

**Independent verification.** From the repository root, focused backend verification passed **143 tests** across the new read test, delegation/write route tests, route-shape unit tests and Phase 15 acceptance guards. The four named historical shard failures passed in a separate targeted rerun (**4 passed**). `ruff format --check`, `ruff check` on affected Python files and `mypy src` passed. From `portal/` in PowerShell, the S03 read/write and route metadata tests plus S01/S02/hook regressions passed **8 files, 205 tests**; `npm run lint` and `npm run build` passed (the existing large-chunk warning remains). From the root, `uv run python scripts/check_documentation.py` and `git diff --check` passed after this entry.

**CI.** Fresh PR run `44961622195` completed successfully for exact PR head `98b023895f6a3ac58aec40c524a7e40180f06d70`. Its completed logs show all eight PostgreSQL shards and the portal/lint/build jobs passing. The shard jobs checked out `refs/remotes/pull/71/merge` at full synthetic SHA `2b43d1c2fb03ddcd1d220442e8644bed632b5ba9`, which merges the exact reviewed head into base `bf23c7648601eb1b3ad479078f2762fe13fd460b`. This is current CI evidence for the synthetic merge checkout containing the exact head, not an isolated head checkout.

**Limits and remaining acceptance.** No browser, zoom, screen-reader/AT, owner/GM persona, human or owner-acceptance check was performed. In particular, the real owner-grant then GM-next-reveal path remains to be checked by the designated persona/integration acceptance. PR #71 remains draft and unmerged; final integrated-head browser/AX, human and owner acceptance remain pending. No S04, consumer UI or preview work was started.
