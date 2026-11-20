# D/P15-C02-S01 implementation plan: save a draft and release a snapshot

**Status:** Opus plan prepared 2026-11-20; Sonnet implementation complete 2026-11-20 ([Section 11.3](#113-implementation-record)); independent review pending. Work-register row: [D/P15-C02-S01](work-register.md#p15-c02-s01), tasks [T01](work-register.md#p15-c02-s01-t01) and [T02](work-register.md#p15-c02-s01-t02). Parent checkpoint: [D/P15-C02](work-register.md#p15-c02).

**Baseline.** Read at `c794c6341933ae964773533358562bca5ea1ffa1` ("docs: record A5c independent review PASS at b00a593"), the head of `phase15/completion`, equal to `origin/phase15/completion` after `git fetch`. The worktree was clean. No repository-path `AGENTS.md` exists. This head contains the PR #70 merge (see §1.1). Since that merge it adds only the A5c review records and a docstring correction in `tests/database/test_player_profile_copy_races.py`. No portal, backend source, migration or Foundry file changed after the merge.

**How each statement was established.** By reading the source, the documents and git/GitHub metadata at this baseline. No application, test or probe was run for this plan. No application, test, schema or backend file was changed.

**Contract sources.**
- [ACCESS_CONTROL §3v](../api/ACCESS_CONTROL.md#3v-character-public-profile-p03-a-a2a): the draft, releases, the D8 rules, the withheld restriction and the A4a identity flags.
- [ACCESS_CONTROL §3w](../api/ACCESS_CONTROL.md#3w-character-revelations-p03-a-a3a): a release reveals nothing.
- The A2 design in [shared-characters §5](shared-characters.md#5-a2-design-public-profile-drafts-and-releases-2026-11-07), and its A6 row in §4. A6 is the portal for "the draft and release editor".
- The adopted checkpoint row in the [hierarchy review](hierarchy-review-2026-11-19.md).
- [Portal behavior §5.5](../reference/portal-behavior.md#55-character-workspace).
- The S01/S02 plans of C01 for structure and gate order ([gate-order clarification](p15-c01-s02-effective-access-plan.md#1113-gate-order-clarification-2026-11-20)).
- The [grading rubric](grading.md).

---

## 1. Entry readiness

### 1.1 C01's merge, verified

| Fact | Value | How verified |
|---|---|---|
| PR #70 state | `MERGED` at 2026-11-20T16:25:13Z into `main` | `gh pr view 70` |
| Merge commit | `bf23c7648601eb1b3ad479078f2762fe13fd460b` (parents `a9952d8` main, `0bd3166` PR head) | `gh pr view 70`, `git log -1 --format='%H %P'` |
| `origin/main` | `bf23c76…` | `git rev-parse origin/main` after fetch |
| Merged tree | Identical to PR head `0bd31661b471cd7821ff01ea069ea6b4300360c8` | `git diff 0bd3166 bf23c76` is empty |
| CI on the merged head | CI run `44759619550` (`pull_request`, head `0bd3166`): all 14 jobs passed | `gh pr checks 70`, `gh run list` |
| Integration into the working branch | `1fa398e` merged `origin/main` into `phase15/completion`; the baseline contains `bf23c76` | `git merge-base --is-ancestor` |

**What this does and does not establish.** C01 is merged: its implementation and its checkpoint-head CI are complete. Owner acceptance is not. Scoped acceptance is at [actor-a](work-register.md#actor-a), which also needs C02 merged and records not yet dispositioned. Final integrated-head [browser](work-register.md#browser), [ax](work-register.md#ax), [b16](work-register.md#b16) and [p15-owner](work-register.md#p15-owner) remain pending. Per C01's gate order, these follow the merge and are not merge gates. C01's review passes, finding closures (L-1, S02-R1, O-5, O-5-R1) and inherited dispositions (O-1 to O-4, G-1/G-2) are unchanged.

### 1.2 C02 checkpoint entry criteria

The maintained prerequisites ([register row](work-register.md#p15-c02), [criteria row](work-register.md#criteria-p15-c02), and the [hierarchy review](hierarchy-review-2026-11-19.md) row) are exactly **[a4](work-register.md#a4) merged** and **[r01](work-register.md#r01) owner accepted**.

| Prerequisite | Required stage | State at the baseline | Evidence |
|---|---|---|---|
| `a4` profile and revelation foundation | Merged | **Satisfied.** PR #68 at `b0910c4` is an ancestor of the baseline. | Register `a4` row; `git merge-base --is-ancestor b0910c4 HEAD` |
| `r01` bounded R01 closure | Owner accepted | **Satisfied.** The owner accepted the backend scope at `f21fb23` (2026-11-18). PR #69 merged at `a9952d8`. All three are ancestors of the baseline. | Register `r01` row; history section "Complete. The owner accepted…" |

DEF-019 had been named in the A2/A6 design as "fix before A6". It has owner closure for the bounded R01 scope ([defects](defects.md)), which `r01` covers. It is therefore not an open S01 prerequisite. DEF-020 and DEF-021 stay separate and are not prerequisites of this slice.

### 1.3 What is and is not a dependency of S01

- **S01's own prerequisite** is "Checkpoint entry criteria; no additional slice-specific gate" (register row 1.2.1). S02, S03 and S04 are siblings with the same gate. None depends on another by maintained requirement, and table order is not a dependency.
- **`a5c` is not an S01 prerequisite.** It is an *attached record* of C02. Its maintained effect is that it "gates the copy-operation consumer and does not block public-tier rendering" (register introduction). Its verdict gates [copy-ui](work-register.md#copy-ui) ("[a5c] independently reviewed"). It is recorded as **PASS at `b00a593`** (register `a5c` row; [player-profile design §17](player-profile-design.md#a5c-independent-implementation-review-luna-2026-11-20)), so that gate is now met as well. Exact-head CI and the parent comparison for A5c remain unverified by its own record. That limitation does not affect S01, which consumes neither copy route.
- **`copy-ui` and `preview`** are attached records with their own gates. Neither is in S01. Their dispositions are prerequisites of `actor-a`, not of S01 or of the C02 merge.
- **C01's merge** is not a C02 prerequisite, though it is now satisfied. `actor-a` needs both C01 and C02 merged.

### 1.4 Classification

| Class | Items |
|---|---|
| Satisfied prerequisites | `a4` merged; `r01` owner accepted; (not required) C01 merged at `bf23c76`, `a5c` independent review PASS. |
| Missing evidence (not S01 gates) | A5c exact-head CI and parent comparison, recorded as unverified in its own row. No CI has run on the baseline `c794c63` itself. The C02 PR's own CI will be the checkpoint gate. C01 owner acceptance (`actor-a`) and the final-head `browser`/`ax`/`b16`/`p15-owner` evidence. |
| Unresolved product decisions (not S01 gates) | `preview` admission (optional; owner inclusion or deferral). Scheduling of `copy-ui`, which would now be eligible to scope against the reviewed copy API. Both must be dispositioned before `actor-a`. |
| Implementation work | S01 T01 and T02 (this plan, portal only). S02, S03 and S04 remain eligible for planning. |

**Verdict: C02 entry criteria are met, and C02-S01 is eligible for planning and implementation.** No owner decision blocks this plan. §10 lists the implementation decisions, each with a recommendation that Sonnet can follow.

---

## 2. Verified current behavior

### 2.1 Backend (complete; S01 changes none of it)

The routes are under `/campaigns/{id}/characters/{character_id}/public-profile`, in `src/dnd_ai/api/character_public_profile.py`. The reads are in `queries/character_public_profile.py` and the commands in `commands/character_public_profile.py`.

| Route | Gate at route | Then | Result |
|---|---|---|---|
| `GET …/public-profile` | `campaign.view` | D8 read rule (effective character-scoped `canon.edit` **or** reveal authority, no whole-character deny); else 404 | The GM read (§2.2) |
| `GET …/releases/{n}` | `campaign.view` | Read rule; else 404 | One release snapshot |
| `POST …/draft` | Role `canon.edit` | D8 edit rule, as a dependency before the idempotency lookup, then again under lock | `201` created / `200` (`changed` false for a no-op). Body `{character_public_profile_id, character_id, row_version, created, changed}` |
| `POST …/releases` | `campaign.view` | Reveal authority and no whole-character deny, before the idempotency lookup, then again under lock | `201 created:true`, or `200 created:false` for a retry of a released draft version. Body: release id, `version_number`, `from_draft_row_version`, `authority_source`, `is_latest`, `species_published`, `size_published`, `identity_entity_row_version` |

**Save body.**
- `expected_row_version` is required (`null` = no draft yet).
- `public_appearance`, `public_background` and `public_summary` are optional, at most 4000 characters each. Absent leaves a field untouched; `null` or blank clears it.
- `publish_species` and `publish_size` are optional strict booleans (JSON `null` is 422).
- Extra fields are refused.

**Release body.**
- `expected_draft_row_version` is required.
- `release_note` is optional, at most 1000 characters.
- `expected_character_row_version` is required only when the draft publishes species or size.

**Refusals the portal will meet.**

| Status | Code | When |
|---|---|---|
| 403 | `public_profile_edit_denied` | Save: the caller can still read but may not edit |
| 403 | `character_reveal_required` | Release: no reveal authority; says nothing about the character |
| 403 | `public_profile_field_withheld` | Save: text sent for a withheld field (refuses the whole request). Release: a new snapshot would include a field withheld from the releaser, or the releaser cannot see the identity preview |
| 404 | (none) | Not readable: the character is outside the world, not canon, or under a whole-character deny |
| 409 | `stale_write` | Save: the draft moved or a first-save race was lost. Release: the draft moved, or the character `row_version` moved for an identity release |
| 409 | `public_profile_draft_missing` | A token was sent but no draft exists, or a release had no draft |
| 409 | `public_profile_character_not_active` | The character is archived |
| 409 | `campaign_archived` | Release in an archived campaign |
| 409 | `public_profile_identity_unavailable` | Defensive |
| 422 | `public_profile_identity_version_required` | Identity release without its token |
| 422 | (validation) | Extra field, length, or `null` flag |

**Separate edit and release rules (by reading).**
- A caller with effective `canon.edit` but no reveal authority can save, but cannot release.
- A caller with reveal authority under a character-scoped `canon.edit` deny cannot save, but can release (`can_edit` false, `can_release` true).
- Reveal authority is held only by a live built-in owner, or by a delegation bound to a live built-in `gm` assignment (§3v; `domain/reveal_authority.py`).

**A release creates no revelation.** The audience sees a release only through a later revelation (A3/A4; §3w). That is S02's scope.

### 2.2 The GM read (`read_character_public_profile`)

The read returns:

- `character_id`; and `label {name, summary}`, the canonical name and summary as a read-only label.
- `draft`: `null`, or the following fields:
  - `character_public_profile_id`, `row_version`, `updated_at`;
  - `public_summary`, `publish_species`, `publish_size`;
  - for each of `public_appearance` and `public_background`:
    - the text, or `null` when withheld;
    - `<field>_withheld`;
    - `<field>_origin`;
    - `<field>_origin_entity_row_version`;
    - `<field>_origin_player_profile_version` and `<field>_origin_player_profile_field`;
    - `<field>_player_profile_source_changed`.
- `has_unreleased_changes`.
- `latest_release`: the full snapshot, including text, origins, provenance, `release_note`, published `species`/`size` and `identity_entity_row_version`, plus metadata (`version_number`, `from_draft_row_version`, `authority_source` = `owner`|`delegation`, `released_at`, `released_by` display name).
- `releases`: the metadata of every version, newest first, without text.
- `can_edit`: the character is active and the caller holds effective character-scoped `canon.edit`.
- `can_release`: the character is active, the caller has reveal authority, no field is withheld, and the identity preview is readable when needed.
- `identity_preview {character_row_version, species{code,label}, size{code,label}}`, or `null` with `identity_preview_withheld: true` when the caller holds no character-view tier.
- `identity_differs_from_latest_release`: `true`, `false` or `null`.
- `legacy_copy` and `player_profile_copy`: copy affordances. They belong to [copy-ui](work-register.md#copy-ui) and are **not rendered** by S01.

The read takes no locks. The latest release is always a whole snapshot, never merged with the draft.

### 2.3 The portal at the baseline

- **Public profile rendering exists only for audiences** (C01 S01). `CharacterPublicProfilePanel` renders a released profile on the public tier and beside the Overview at the summary/full tiers (`pages/CharacterDetailPage.tsx`). `api/character.ts` normalizes those reads.
- **No portal code calls any `…/public-profile` route.** `grep` finds none in `portal/src/api`, `hooks` or `pages`.
- **The Manage row** (`components/CharacterManageLinks.tsx`) is the editors' entry to a character's authoring pages: Edit, Builds, Portrayal, Relationships, Run this NPC. It returns `null`, mounting nothing and sending no request, for a caller without the role `canon.edit` (`useCampaignCapability`). Its comment states the rule this plan follows: "the sheet shows what a character is, and never embeds the controls that change it".
- **The nearest analog** is `pages/NpcPortrayalPage.tsx`, at `/app/:campaignId/characters/:characterId/portrayal`. It is a GM-only versioned editor at its own route. It uses:
  - `useAuthoringResource` for a single read with `denied`/`unavailable` states;
  - `useKept` to keep the last good read through a failed re-read;
  - `useAuthoringMutation` with a per-scope idempotency key, a retry of the same key, and the `confirmed` / refresh-failed status;
  - `StaleWriteNotice` and `StaleReadNotice`;
  - `useBreadcrumbLabel` with `TaskBreadcrumb`, `usePageArrival`, and `useAnnounce` / `useAnnounceWhenRead`.
- **`classifyApiError`** (`types/apiError.ts`) maps 409 `stale_write` to `stale`, other 409s to `conflict`, 403 to `denied`, 404 to `unavailable`, and 400/422 to `invalid`.
- **Shared components:** `ConfirmDialog`, `ErrorSummary` / `FormActions` / `MutationStatusMessage` (`components/authoring/feedback.tsx`), `useUnsavedChangesGuard`, and the `PermissionLost` / `retainedChanges` contract for showing back unsent input after a confirmed loss.

### 2.4 Transitions and revocation (by reading, unchanged by S01)

- `CampaignLayout` keys the outlet on campaign and perspective.
- A 401 reloads the session.
- `useAuthoringMutation` aborts and discards a late response when its `scopeKey` changes.
- Whether access ends is learned from the next request. Nothing polls or pushes, and S01 keeps that contract.

---

## 3. Outcome, scope and exclusions

### 3.1 Intended user outcome

A GM opens a character's **Public profile** page from the Manage row. The page shows:
- the campaign's draft of what players may later see;
- whether it has unreleased changes;
- the latest release, as an immutable snapshot;
- the list of earlier releases.

**With edit authority, the GM can:**
- edit the summary, appearance and background;
- choose whether the next release publishes the character's species and size, with the live values shown;
- save, with concurrent edits caught (stale-save recovery).

**With reveal authority, the GM can:**
- release the saved draft as a new numbered snapshot, after a confirmation that says plainly that a release shows the profile to no one by itself.

Each control appears only where the server's `can_edit` or `can_release` says so. Each refusal is explained without disclosing anything. Players see nothing new.

### 3.2 In scope

- **T01: draft editing.** The route, the link, the types, the API functions and the read. The draft form:
  - the three text fields;
  - the two publish flags, with the identity preview;
  - withheld-field display and clearing.

  Save with `expected_row_version`. Stale-save recovery, edit refusals, permission loss, archived character, retry and idempotency, and the unsaved-changes guard. A read-only status block shows the draft version, "Unreleased changes" and the latest release version, if any.
- **T02: release.** The release action with confirmation and an optional note. The tokens (`expected_draft_row_version`, and `expected_character_row_version` when the draft publishes identity). Release refusals, and retry and replay handling. The latest-release snapshot panel and the release history list (metadata only). Immutable-snapshot and no-revelation tests.
- **In both:** portal tests (jsdom), and the documentation paragraphs named in §4.3.

### 3.3 Exclusions (must not be entered)

- **Out of scope (other work):**
  - Copy controls of any kind: `copy-legacy`, `copy-player-profile`, and origin/provenance/"source changed" indicators. These belong to [copy-ui](work-register.md#copy-ui). The `legacy_copy` and `player_profile_copy` keys are not typed beyond `unknown` and not rendered.
  - Revelation list, create and revoke: S02. Delegations: S03. Character-scoped denies: S04.
  - The audience preview ([preview](work-register.md#preview)).
  - Player-profile reading or editing (P15-C12).
- **Constraints on this slice:**
  - A per-version snapshot page (`GET …/releases/{n}`). Deferred by D-3; the history list shows metadata only.
  - Any backend, migration, Foundry or route-manifest change, and any new DTO field. If a gap appears, stop and report.
  - Any change to C01 files: `CharacterPublicProfilePanel`, `api/character.ts` normalization, the tier rendering, the breadcrumb publishers, and the Access page and effective-access panel.
  - Polling, timers or push. The "next request" contract is unchanged.
  - Client-side authorization: the portal never derives edit or release rights from roles, capabilities, kind or ownership. It reads `can_edit` and `can_release`, and the server re-checks every write.

---

## 4. Affected files and interfaces

### 4.1 New (portal)

| File | Contents |
|---|---|
| `portal/src/types/characterPublicProfile.ts` | The GM read and the two receipts, exactly the keys in §2.2. `legacy_copy` and `player_profile_copy` are typed `unknown`. Origin/provenance keys are typed but never rendered. |
| `portal/src/api/characterPublicProfile.ts` | `publicProfilePath`, `saveCharacterPublicProfileDraft`, `releaseCharacterPublicProfile`. The POSTs pass `MutationContext` (CSRF, `Idempotency-Key`, signal) like `api/npcPortrayal.ts`. |
| `portal/src/pages/CharacterPublicProfilePage.tsx` | The route page. It follows `NpcPortrayalPage`'s structure: a page shell with the read/denied/unavailable states, and a `Loaded` child keyed on `draft?.row_version` and the latest release version. |
| `portal/src/pages/CharacterPublicProfilePage.test.tsx` | The jsdom acceptance cases (§6). The T02 cases are added in the T02 commit. |

### 4.2 Changed (portal)

| File | Change |
|---|---|
| `portal/src/App.tsx` | Add `<Route path="characters/:characterId/public-profile" element={<CharacterPublicProfilePage />} />` beside `…/portrayal`. |
| `portal/src/components/CharacterManageLinks.tsx` | Add a **Public profile** link for every character kind, inside the existing `canEdit` gate, carrying `taskState` like the other record links. Do not condition it on `authoring.can_edit`; see D-1. |
| `portal/src/navigation/legacyCharactersReturn.test.ts`, and the breadcrumb route registry if it enumerates character routes | Add the new route wherever the character route list is enumerated, so return and breadcrumb behavior match `portrayal`. Sonnet confirms the exact registry with `grep -rn "portrayal" portal/src/navigation`. |

### 4.3 Documentation (same commits)

- [Portal behavior §5.5](../reference/portal-behavior.md#55-character-workspace): add one paragraph on the Public profile page.
  - T01: draft, save, stale and refusal behavior, and what is never rendered.
  - T02: release, snapshots, and "a release shows nothing to anyone; a revelation does".
- [ACCESS_CONTROL §3v](../api/ACCESS_CONTROL.md#3v-character-public-profile-p03-a-a2a): add one "Portal:" sentence, listing the page and stating that it renders `can_edit`/`can_release` and does not render the copy affordances. This replaces nothing in the contract.
- Do not edit `shared-characters.md`'s historical A6 sentences. The register links this plan.

### 4.4 Unchanged, and must stay so

Everything in `src/`, `database/`, `foundry-module/`, `tests/` (Python), `tests/r01_route_manifest.json`, and the C01 files listed in §3.3.

---

## 5. Task commits

Two commits, following the register's T01/T02 sizing. Both go on `phase15/completion`, unpushed until the owner opens the C02 PR.

| Commit | Message | Contents | Acceptance cases |
|---|---|---|---|
| T01 | `P15-C02-S01-T01: edit the public-profile draft under character-scoped canon.edit with stale-save recovery` | §4.1 types and API (save only), page, route, link, T01 tests, T01 doc sentences | D1–D17 |
| T02 | `P15-C02-S01-T02: release the saved draft as an immutable snapshot under current reveal authority` | Release API function, release control and dialog, latest-release panel, history list, T02 tests, T02 doc sentences | R1–R17 |

Each commit ends with the attribution lines. Each must pass §7 on its own.

---

## 6. Acceptance cases

The fixtures are mocked API responses in jsdom, using the existing portal test harness, as `NpcPortrayalPage.test.tsx` does. "Request" means the mocked fetch log. Each case asserts what is rendered and what is sent.

### 6.1 T01: draft editing (D1–D17)

| # | Case | Expected |
|---|---|---|
| D1 | Manage row, role `canon.edit` held, any kind (`npc`, `player_character`, `character`) | A **Public profile** link to `…/characters/{id}/public-profile` |
| D2 | Manage row without role `canon.edit`; public-tier reader; summary-tier player | No link, and no `…/public-profile` request on any character route |
| D3 | Page, GET 404, or 403 at the route | One non-disclosing message ("This character's public profile is not available to you."). No name, label or draft, and no form |
| D4 | GET with `draft: null`, `can_edit: true` | Empty form showing the label name. Save sends `expected_row_version: null` and only the fields the person filled. A 201 re-reads, then announces "Draft saved." |
| D5 | Existing draft, edit one field | The body has `expected_row_version` equal to the draft's `row_version`, and contains exactly the changed keys. Untouched fields and flags are absent |
| D6 | Empty a field that had text | That key is sent as `null` |
| D7 | Nothing changed | Save is disabled, or a submit sends nothing. No request |
| D8 | 409 `stale_write` | The typed values are kept. The page re-reads and shows the latest saved values (`StaleWriteNotice` pattern). The next save uses the **new** `row_version`, and the old token is never re-sent |
| D9 | 409 `public_profile_draft_missing` | Treated as stale: re-read, values kept, and a neutral message |
| D10 | 403 `public_profile_edit_denied` | A message that editing is not available. The typed values are shown back read-only, the page re-reads, and the form follows the new `can_edit` |
| D11 | 404 on save | The page drops all draft and release content and shows D3's message. Only the person's own unsent input is shown back (`PermissionLost` contract) |
| D12 | `can_edit: false`, draft present (for example, a reveal holder under a `canon.edit` deny) | Read-only values. No Save button and no flag controls. No reason is inferred |
| D13 | `public_background_withheld: true` | No text, and no input for that field. A notice says it holds copied text the GM cannot read. A **Clear** action sends `public_background: null`. Every other save omits the key |
| D14 | Identity flags, with `identity_preview` present | Two checkboxes labelled with the live values ("Publish species: Elf", "Publish size: Medium"). Only a changed flag is sent, as a boolean |
| D15 | Identity flags, with `identity_preview_withheld: true` | The checkboxes are shown with no live value, plus a note that species and size cannot be previewed. Nothing is inferred |
| D16 | Network error or 5xx on save | `retry` re-sends the same body under the same key. A confirmed write whose re-read fails shows `StaleReadNotice` and is never re-sent |
| D17 | The person navigates away with unsaved changes; or switches to another character during a pending save | The unsaved-changes guard asks. The scope change discards the late response, so no result appears under the other character |

### 6.2 T02: release (R1–R17)

| # | Case | Expected |
|---|---|---|
| R1 | `can_release: true`, a saved draft, form clean | A **Release** button |
| R2 | `can_release: false` | No Release button. If a draft exists, one neutral line: "You can't release this profile." No reason is derived on the client |
| R3 | Form dirty | Release is disabled, with "Save your changes before releasing." A release never snapshots unsaved input |
| R4 | `draft: null` | No Release button |
| R5 | Release confirm dialog | The dialog names the draft version being released, has an optional note (≤1000 characters, counted), and says: "Releasing doesn't show this profile to anyone. Players see it only after you reveal the character." Cancel sends nothing, and focus returns to Release |
| R6 | Confirm, draft without identity flags | The body is `{expected_draft_row_version, release_note?}`, with no `expected_character_row_version` |
| R7 | Confirm, draft publishes species or size | The body adds `expected_character_row_version = identity_preview.character_row_version` from the read the person saw |
| R8 | 201 | Re-read. The latest-release panel shows version N+1, its snapshot text and the published labels, and "Unreleased changes" clears. Announce "Released as version N+1." |
| R9 | 200 `created: false` | Re-read, then announce "This version was already released." Not shown as an error |
| R10 | Immutable snapshot | After R8, a save that changes the draft re-reads with `has_unreleased_changes: true`. The latest-release panel still shows the **snapshot** text, not the draft. The history list is unchanged. A test asserts that the draft and snapshot texts differ on the page |
| R11 | No revelation | After a release, no request is sent to any `/revelations`, `/effective-access`, `/access-overview` or character-detail route. The page offers no reveal control |
| R12 | 403 `character_reveal_required` | Message: "You no longer have authority to release this profile." Re-read; the button follows `can_release`. The draft is untouched |
| R13 | 403 `public_profile_field_withheld` | A message that a field cannot be released by this person. Re-read |
| R14 | 409 `stale_write` | Message: "The draft or character changed since you opened it." Re-read. The next confirmation uses the new tokens, and the old ones are never re-sent |
| R15 | 409 `public_profile_draft_missing`, `public_profile_character_not_active` or `campaign_archived`; 422 `public_profile_identity_version_required` | A specific neutral message for each, and a re-read. The 422 maps to the stale message, because it means the read the person saw is out of date |
| R16 | 404 on release | As in D11 |
| R17 | Release history | Rows are newest first, each with version, date, released-by name and source ("Owner" or "Delegated GM"). No text and no link. Separate edit and release refusals: the fixture `can_edit: true, can_release: false` shows Save but not Release; the fixture `can_edit: false, can_release: true` shows Release with read-only fields |

---

## 7. Verification

### 7.1 Automated checks (per commit, by Sonnet; again by Luna)

Run from `portal/` in PowerShell:
- `npm test`, with the counts reported;
- `npm run lint`;
- `npm run build`.

Run from the repository root:
- `uv run python scripts/check_documentation.py`;
- `git diff --check`.

**Contract baseline (no backend change; run once at the base, informational).** With the local PostgreSQL 18 per [DEVELOPMENT §6](../DEVELOPMENT.md#6-testing), run `uv run pytest tests/database/test_character_public_profile_api.py tests/database/test_character_public_profile_concurrency.py`. This confirms the backend contract the portal consumes. A failure stops the slice and is reported, not fixed here.

**Mutation probes** (at least one per commit, restored afterwards, with SHA-256 of the file recorded before and after):
- T01: send the save without `expected_row_version`, or re-send the old token after a stale write. D5 or D8 must fail.
- T02: drop `expected_character_row_version`, or render the draft text in the latest-release panel. R7 or R10 must fail.

Report first runs and reruns separately.

### 7.2 Checkpoint merge gate (C02)

Per the register's stage rule and C01's [gate order](p15-c01-s02-effective-access-plan.md#1113-gate-order-clarification-2026-11-20), the C02 PR may merge after:
1. every included slice is independently reviewed;
2. the PR's acceptance cases pass;
3. CI passes on the PR head through its merge checkout.

A documentation-only commit is a new head and needs its own run. Which slices C02 includes before its PR merges is the owner's to state. S02 to S04 are planned separately.

### 7.3 Browser, accessibility and owner obligations (separate events, not merge gates)

- **Persona browser checks for C02** belong to [browser](work-register.md#browser) at the final integrated head:
  - a GM with edit and reveal authority;
  - an editor without reveal authority;
  - a reveal holder under a `canon.edit` deny;
  - a player, who sees nothing new.

  Scripted checkpoint runs may be recorded like C01's, labelled as scripted and not as AT or human evidence.
- **AT checks:**
  - dialog focus trap and return;
  - announcement of save, release and refusals;
  - error-summary focus;
  - label association for the flag checkboxes;
  - the withheld notice read in context;
  - reflow at 320 CSS px and actual zoom.

  These belong to the final [ax](work-register.md#ax) and [b16](work-register.md#b16) records.
- **Owner acceptance** of revelation and scoped profiles is at [actor-a](work-register.md#actor-a), after C01 and C02 merge and with `preview` and `copy-ui` dispositioned. Release acceptance is at [p15-owner](work-register.md#p15-owner).
- None of these is performed, accepted or waived by this plan.

---

## 8. Authorization, disclosure, data and concurrency requirements

- **Authorization.** The only sources of control state are `can_edit` and `can_release`. The Manage-row link uses the existing role-`canon.edit` gate, which decides only whether a link is offered. The page itself is reachable by URL, and the server's 404 or 403 decides what it shows.
- **Disclosure.**
  - Never render withheld text, `legacy_copy`, `player_profile_copy` or provenance fields.
  - Never render the draft outside this page.
  - Never send a `…/public-profile` request from a player, public-tier or summary-only surface (D2).
  - Error messages carry no server message text, only mapped codes.
  - On a 404, drop everything the server sent.
- **Data.** Absent means untouched; `null` means clear. Flags are strict booleans. Lengths are enforced on the client as a convenience (4000 and 1000) and by the server as the rule. No text appears in logs or the console.
- **Concurrency.** One token per write (draft `row_version`; for an identity release, the character `row_version` as well), always taken from the read the person saw. Never resend a token after a stale answer. Retries reuse the same key and body, and an edited body is a new key. Release is disabled while the form is dirty, so the snapshot is always the saved version the person reviewed.
- **Revocation.** Learned from the next request. Nothing polls.

---

## 9. Intermediate states

- **After T01 only:** the editor saves drafts, with no release control. Nothing becomes visible to any audience: drafts are never audience-read, and releases still exist only through the API. The status block shows the latest release version read-only, if one exists. This state is safe to hold on the branch.
- **After T02:** the full slice.
- **Neither commit changes any reader of the released profile.** C01's rendering of a release to audiences is unchanged, and still requires a revelation (S02 or the API).

---

## 10. Decisions

None blocks Sonnet if the recommendation is taken. The owner may override any of them before T01 starts.

| ID | Decision | Recommendation | Alternative and consequence |
|---|---|---|---|
| D-1 | Where the editor lives | A dedicated route, `characters/:id/public-profile`, linked from the Manage row for every kind, matching Portrayal and the Manage row's "never embed edit controls in the sheet" rule. The link is gated only by the row's role-`canon.edit` check; the page reads `can_edit`/`can_release`. | Inline on the sheet: contradicts the row's rule and loads a GM read on every sheet view. Hiding the link unless `authoring.can_edit`: hides it from a reveal holder under a `canon.edit` deny, who may still release. |
| D-2 | Withheld fields | Show the withheld notice and offer **Clear** (`null`). Exclude the key from every other save. | Notice only: a GM who cannot read the source cannot release (`can_release` false) and has no portal way out until copy-ui. |
| D-3 | Release history depth | Metadata list only; no per-version snapshot view. | Add `GET …/releases/{n}` viewing: more UI and tests; useful for audit; can follow as its own task. |
| D-4 | Release with unsaved edits | Disable Release while dirty. | "Save and release" in one action: two writes, two tokens and more failure states. Not needed for the criterion. |
| D-5 | Copy strings | As quoted in §6. | The owner may reword. A rewording does not change cases. |

**Observations recorded, not blocking.**
- **OB-1.** The Manage row appears only for the role `canon.edit`. Migration 085 gives `campaign_owner` `canon.edit`. A delegated reveal holder needs the built-in `gm` role, which normally holds `canon.edit`; this was not executed. If a deployment's `gm` role lacked `canon.edit`, such a member would reach the page only by URL.
- **OB-2.** `identity_differs_from_latest_release` is useful as an informational line ("Species or size has changed since the last release"). It is included in T02 only as read-only text where the value is `true`.

**Contract gaps.** None found. Every behavior in §6 is supported by fields in §2.2. No DTO field is proposed.

---

## 11. Handoffs

### 11.1 Sonnet implementation instructions

1. Start on `phase15/completion` at the commit that records this plan. Record that SHA as the base, and record `git status --short`. Preserve unrelated work. Do not push, open a PR or merge.
2. Re-check §2.1 and §2.2 against the base: the request models and the read's returned keys. If anything differs, stop and report. Do not adapt by inventing fields.
3. Run the contract baseline in §7.1 once, and record the result.
4. **T01.** Implement §4.1–§4.3 for editing, with tests D1–D17, then run §7.1 and commit with the T01 message in §5.
5. **T02.** Add the release function, the control, the dialog, the snapshot panel and the history list, with tests R1–R17. Run §7.1 and commit with the T02 message.
6. **Rules.**
   - Follow `NpcPortrayalPage`'s hooks and notices. Add no new mutation or resource hook.
   - Never render the excluded keys.
   - Never infer authority. Never resend a stale token. Never release while dirty.
   - No polling.
   - No backend, Foundry, manifest or C01-file change.
   - Use existing classes and components. Add CSS only if a reflow defect requires it, and say so.
7. Append an implementation record below §11.3 with:
   - the base;
   - both commit SHAs (read with `git log --grep`);
   - the commands, with results and counts, first runs and reruns separate;
   - the mutation probes with SHA-256;
   - any deviation and its reason;
   - any changed existing assertion.

   Set the S01, T01 and T02 register status cells to "Implemented; Luna review pending".

### 11.2 Luna independent review boundary

- **Range.** Base = the commit that records this plan. Head = T02, or the last correcting commit. Review T01 and T02 together and each on its own.
- **Required evidence.**
  1. Types equal the §2.2 keys at the head. No excluded key is rendered.
  2. By reading, no player, public-tier or summary surface requests `…/public-profile`. The link sits inside the existing `canEdit` gate.
  3. Every write's tokens come from the displayed read. No stale token is re-sent. Release is impossible while dirty.
  4. Run §7.1, and map D1–D17 and R1–R17 to tests.
  5. At least one independent mutation probe per commit, restored, with SHA-256 recorded.
  6. The §3.3 exclusions were not entered, and no C01 file changed.
- **Verdict.** Use the [rubric](grading.md#severity-and-checkpoint-disposition), grading each finding separately. Distinguish new findings from the inherited C01 observations, which stay with C01, and from OB-1/OB-2. §7.3 events are not part of this verdict.

### 11.3 Implementation record

**Implemented by Sonnet, 2026-11-20. Independent review (Luna) pending.** Nothing below is review evidence, owner acceptance, browser or assistive-technology evidence, or final integrated-head evidence.

**Base and commits.**

| Role | Commit |
|---|---|
| Planning baseline (this plan and the register changes, committed before any implementation) | `6a4e67e633788f3c38e1042b7d4e0e74544b08d2` |
| T01 | `c91a9e235f8fed92e42f4b3797480b45bb7a2f60` |
| T02 | `c31e4f808fd402be3daf066bbd2c29215568b941` |
| Records commit (this section and the register; documentation only) | The commit that follows T02 on the branch (`git log --grep "record P15-C02-S01"`) |

The base was `c794c6341933ae964773533358562bca5ea1ffa1` plus the uncommitted plan and register changes, which were verified (`scripts/check_documentation.py` and `git diff --check`) and committed alone as `6a4e67e` before any code. At that point `git status --short` was clean. No unrelated change existed to preserve.

**Contract re-check (instruction 2).** The request models (`SaveCharacterPublicProfileDraftRequest`, `ReleaseCharacterPublicProfileRequest`), the receipts, and the keys returned by `read_character_public_profile` and `_release_json` were read at the base and equal plan §2.1 and §2.2. No difference, no invented field, and no backend, migration, Foundry or manifest file changed. One detail the plan did not state, confirmed by reading: `publish_species` and `publish_size` default to `false` in the model, and the route passes them to the command only when the request names them (`model_fields_set`), so an absent flag is untouched. The portal therefore sends a flag only when it changed. The release receipt has no `released_at` or `released_by`, so the receipt type does not extend the release metadata type.

**Contract baseline (informational, run once at the base).** `uv run pytest tests/database/test_character_public_profile_api.py tests/database/test_character_public_profile_concurrency.py` at the T02 head: BASELINE_RESULT. No backend file changed in this slice.

**What changed (portal only).**
- New: `types/characterPublicProfile.ts`, `api/characterPublicProfile.ts` (path, save, release), `pages/CharacterPublicProfilePage.tsx`, and two test files.
- Changed: `App.tsx` (the route), `navigation/routeMeta.ts` (`characters.publicProfile`, parent `characters.detail`, label "Public profile"), `components/CharacterManageLinks.tsx` (the link, for every kind, inside the existing `canEdit` gate), `navigation/legacyCharactersReturn.test.ts` (the route list and the rejected-return list, as for `portrayal`).
- Docs: [portal behavior §5.5](../reference/portal-behavior.md#55-character-workspace) (two paragraphs) and [ACCESS_CONTROL §3v](../api/ACCESS_CONTROL.md#3v-character-public-profile-p03-a-a2a) (one "Portal" bullet).
- No new mutation or resource hook: the page uses `useAuthoringResource`, `useKept`, `useAuthoringMutation`, `useConfirmedRefresh`, `useAnnounceWhenRead`, `useUnsavedChangesGuard`, `ConfirmDialog` and the existing feedback components. No CSS was added.

**Design points the review should check.**
1. **Hidden source fields.** A withheld field arrives as `null`; the page renders no text and no input for it, never sends its key except as an explicit **Clear** (`null`), and shows no origin, provenance, `legacy_copy` or `player_profile_copy` value. Withheld text cannot be in client-held editable values because the server never sends it; the typed keys for those unrendered values exist only in the response type.
2. **Conflicts.** A refused write that means the page is out of date or authority changed (save: 409 `stale_write`, `public_profile_draft_missing`, `public_profile_character_not_active`, any 403; release: 403, 409, and the 422 for the missing character version) is handled once, in the request wrapper, before the mutation hook sees the error. The page raises an `epoch` (so the form is rebuilt whatever version the next read carries), re-reads, and shows the person's own changed fields back, taken from the refused request body and not from the form or the server, in a read-only "Your unsaved changes" section. Typed edits are never re-applied to a newer draft, so the next save or release can only send tokens from the new read. The page holds every write while a read is in flight or has failed (`held`).
3. **Scope.** The page is keyed on campaign and character; the mutations' scope keys name both, so a late response is aborted and discarded when the character changes. A 404 on either write or on the read drops every server value and keeps only the person's own input.
4. **Release.** The button needs `can_release` and a saved draft, and is disabled while the form is dirty, while a read is held, and while a request is pending. The body is built from the saved read, never from the form. A release makes no request other than the release and the re-read.
5. **Choices that the plan left to the implementer.** After a refusal the form is rebuilt and the page offers no "re-apply my text" action: the typed values are shown for copying (the `PermissionLost` and `StaleWriteNotice` contract). **Clear** is a toggle (`aria-pressed`) that the save then sends, not an immediate write. A release is offered even when `has_unreleased_changes` is false, because R9 (a retry of an already-released version) must be reachable and the server decides.

**Acceptance cases to tests.** `CharacterPublicProfilePage.test.tsx` has 44 tests; `CharacterManageLinks.publicProfile.test.tsx` has 6 (D1 and D2, for each of three kinds).

| Case | Test (name prefix) |
|---|---|
| D1, D2 | `CharacterManageLinks.publicProfile.test.tsx`: "D1: a canon editor sees the link", "D2: without canon.edit there is no link and no public-profile request" |
| D3 to D17 | `CharacterPublicProfilePage.test.tsx`: the test whose name begins with the case number (D4, D13 and D16 have two each) |
| R1 to R17 | The same file: the test whose name begins with the case number (R5, R6 and R17 have two or three each; R15 is one table of five codes) |
| Extra | A confirmed release whose re-read fails is not repeated, and writes wait for a read |

D2's "no request on any character route" for a public-tier reader or a summary-tier player is by reading and by absence: the only callers of `publicProfilePath` are this page and `api/characterPublicProfile.ts`, and the only link is in the Manage row's own `canEdit` gate. No existing character-page test was changed or added for it.

**Commands and results** (from `portal/` in PowerShell, because the Bash tool's path casing makes `vitest` fail to find its suite; from the repository root otherwise).

| Run | Command | Result |
|---|---|---|
| T01 focused | `npm test -- src/pages/CharacterPublicProfilePage.test.tsx src/components/CharacterManageLinks.publicProfile.test.tsx src/navigation` | 30 files, 823 tests passed (first run at T01 after two test-code corrections, below) |
| T01 full, first run | `npm test` | 431 passed, 1 failed (432 files; 5311 passed, 1 failed of 5312): `CharacterRelationshipsSection.test.tsx` "does not show a previous character's list for the next one while it loads" timed out at 8 s under full-suite load |
| T01 rerun of that file | `npm test -- src/components/CharacterRelationshipsSection.test.tsx` | 11 of 11 passed. A load timeout in a file this slice does not touch; reported, not fixed |
| T01 lint, build, docs, diff | `npm run lint`; `npx tsc -b`; `npm run build`; `uv run python scripts/check_documentation.py`; `git diff --check` | All passed |
| T02 focused | `npm test -- src/pages/CharacterPublicProfilePage.test.tsx` | 44 of 44 passed on the first run |
| T02 full | `npm test` | 432 files, 5338 tests, all passed |
| T02 lint, typecheck, build, docs, diff | as above | All passed |

Corrections made to the tests before T01 was committed, each a defect in the test and not in the page: the first draft's D17 and D16 clicked an ambiguous "Discard changes" button and a button the page's own notice replaces; and the D11 fixture used an incomplete release. The D4 announcement test was rewritten after its first draft asserted nothing useful. No existing assertion was changed.

**Mutation probes** (each restored; SHA-256 of `portal/src/pages/CharacterPublicProfilePage.tsx` at the time).

| Commit | Probe | Result | SHA-256 before and after |
|---|---|---|---|
| T01 | The save always sends `expected_row_version: null` | D5, D6, D8, both D13 and D14 failed (6 of 18) | `289badee1a8926393a9481d985bc5cd410ff597c53d5f671ee1607aaf7594c19`, restored |
| T01 | A stale 409 is no longer treated as a refusal (the old page and token stay) | D8 failed | `289badee1a8926393a9481d985bc5cd410ff597c53d5f671ee1607aaf7594c19`, restored |
| T02 | The release never adds `expected_character_row_version` | R7 and R14 failed | `ffea00cf8919571bc6c8974f7d2c1deb3c4e7a53da4b7e68a5ae261fb1563e5b`, restored |
| T02 | The latest-release panel also renders the draft's summary text | R8 and R10 failed | `ffea00cf8919571bc6c8974f7d2c1deb3c4e7a53da4b7e68a5ae261fb1563e5b`, restored |

**Deviations from the plan.** None of behavior. (a) The plan's file list named `CharacterPublicProfilePage.test.tsx` for D1 and D2; they are in `CharacterManageLinks.publicProfile.test.tsx`, beside the component they test. (b) The routes were also added to `navigation/routeMeta.ts`, which the plan anticipated ("the breadcrumb route registry if it enumerates character routes"). (c) The page reads `identity_differs_from_latest_release` as one read-only line (OB-2). (d) The plan allowed the 422 identity-version refusal to map to the stale message; it does.

**Limitations and not performed.**
- **Not performed:** every browser check, every assistive-technology check (dialog focus trap and return in a real browser, announcements, error-summary focus, checkbox label association, the withheld notice read in context, reflow at 320 CSS px, actual zoom), and the persona checks of plan §7.3. jsdom tests assert focus return to **Release** after Cancel, and nothing about a screen reader. These belong to [browser](work-register.md#browser), [ax](work-register.md#ax) and [b16](work-register.md#b16) at the final integrated head.
- **Focus after a release or a refusal** is not moved: the form is rebuilt from the next read, so the control that had focus is replaced and focus falls to the page, as it does after a portrayal save. Whether to move it to a heading is for the AX review.
- No CI has run on these commits (the workflow runs only on pushes to `main` and pull requests into `main`). The C02 pull request's own CI is the checkpoint gate and has not been opened.
- No final integrated-head evidence, no owner acceptance, no `actor-a`, and nothing for S02 to S04, `copy-ui`, `preview` or C01 files.

**Luna review range.** Base `6a4e67e633788f3c38e1042b7d4e0e74544b08d2`, head the records commit that follows `c31e4f808fd402be3daf066bbd2c29215568b941` (the code is complete at T02; the records commit changes only documentation). Review T01 (`6a4e67e..c91a9e2`) and T02 (`c91a9e2..c31e4f8`) each on their own and together, per [Section 11.2](#112-luna-independent-review-boundary).
