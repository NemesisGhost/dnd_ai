# D/P15-C01-S01 implementation plan: render the public character tier

**Status:** T01 implemented 2026-11-19; Luna found L-1 (see [§11.4](#114-independent-review-luna-2026-11-19)); corrected 2026-11-19, Luna re-review pending (see the [correction record](#115-correction-of-l-1-sonnet-2026-11-19) and the [implementation record](#113-implementation-record)). Prepared 2026-11-19 for Sonnet. Work-register row: [D/P15-C01-S01](work-register.md#p15-c01-s01), task [T01](work-register.md#p15-c01-s01-t01). Parent PR: [D/P15-C01](work-register.md#p15-c01).

**Baseline.** Read at `2a9599e89b332c8cbe0aca32ff6928433d0632f5` ("Adopt delivery hierarchy documentation") on `phase15/completion`, the expected documentation baseline. Porcelain status was clean before this plan. No `AGENTS.md` exists on the repository path. The user-level `~/.codex/AGENTS.md` was empty when the [register](work-register.md#baseline-and-authority) was adopted; this plan did not re-read it.

**What establishes each statement.** Source reading at that baseline, plus one throwaway Vitest probe (§1.3). It was run once through `npm test` in `portal/` and then deleted. No application code, test, schema or backend file changed. A first `npx vitest` attempt from Git Bash failed with a Vitest internal-state error before any test ran. The probe was then run through PowerShell `npm test`. The failed attempt is recorded, not counted.

**Contract sources.** [A4 design §12.2–§12.4](shared-characters.md#12-a4-design-the-public-profile-tier-and-published-species-and-size-d6-2026-11-10) (the tiers, the DTOs and `sections`) and the [A4 follow-up record](shared-characters.md#a4-follow-up-record-2026-11-10). Also the A6 row of the [slice table](shared-characters.md#4-slices-dependencies-and-review-boundaries), [READ_API character detail](../api/READ_API.md), [ACCESS_CONTROL §3w](../api/ACCESS_CONTROL.md#3w-character-revelations-p03-a-a3a), [portal behavior §9–§12](../reference/portal-behavior.md#9-search-lists-and-non-disclosure), [Development §6/§7](../DEVELOPMENT.md) and the [grading rubric](grading.md).

---

## 1. Verified current behavior

### 1.1 The server (A4, merged)

`GET /campaigns/{campaign_id}/characters/{character_id}` (`src/dnd_ai/api/characters.py`, `get_character_endpoint`) answers `CharacterResponse | PublicCharacterResponse`.

| Tier | Body | Key facts for the client |
|---|---|---|
| `public_profile` | `PublicCharacterResponse`: `view_tier`, `character_id`, `name` (canonical), `character_kind`, `sections`, `public_profile` | No `authoring`, `canon_status`, `lifecycle_status`, `species_code`, `size_category`, hit-point/death-save/exhaustion fields, `current_location_id`, `active_encounter_id`, `conditions` or `resources`. The keys are absent, not null. `public_profile` is always an object |
| `summary` | `CharacterResponse`, `view_tier: "summary"` | Existing summary fields (mechanics null), plus `public_profile` = latest release or `null` |
| `full` | `CharacterResponse`, `view_tier: "full"` | Existing full fields, plus `public_profile` = latest release or `null` |
| none | 404 fixed body; 403 when the caller lacks campaign `campaign.view` (the route dependency) | — |

`public_profile` (`CharacterPublicProfileResponse`) is `summary`, `appearance`, `background` (string or null), `species` and `size` (`{code, label}` or null). No release metadata is ever present. `sections` gains `public_profile: bool`. At the public tier `details` and `public_profile` are true, `sheet` and `relationships` false, and `inventory` and `parties` are decided independently by their own endpoints (§12.4). At summary/full, `sections.public_profile` is false and `public_profile` null both when no release exists and under a `view_public_profile` deny. The client cannot distinguish them, by design.

Revocation, denies and independent sources take effect on the **next request** (§12.2). The server sends no push, and the client must not infer tier from anything but the latest response.

### 1.2 The portal at the baseline

The portal types predate A4. `grep` finds no `view_tier` or `public_profile` anywhere in `portal/src`. That matches READ_API's statement that "the portal types are unchanged until A6".

| File | What it assumes |
|---|---|
| [`types/character.ts`](../../portal/src/types/character.ts) | One `CharacterDetail` shape with required live `species_code`, `size_category`, mechanics and `conditions`/`resources` arrays-or-null. `CharacterSections` has no `public_profile` |
| [`api/character.ts`](../../portal/src/api/character.ts) | `fetchCharacter` casts the JSON to `CharacterDetail` with no tier check. `cache: "no-store"`. Non-2xx → `CharacterRequestError(status)` |
| [`hooks/useCharacter.ts`](../../portal/src/hooks/useCharacter.ts) | Snapshot keyed on campaign, character and request version. It aborts on change, ignores aborted answers, maps 401 → session `reload()`, 403/404 → `unavailable` and other → `error`. Replaces state wholesale, so no field merging |
| [`components/CharacterBoundary.tsx`](../../portal/src/components/CharacterBoundary.tsx) | Loading/unavailable/error/success. Publishes `name` to the breadcrumb registry and drops it on `unavailable` |
| [`pages/CharacterDetailPage.tsx`](../../portal/src/pages/CharacterDetailPage.tsx) `CharacterPanels` | Always renders an Overview with live `species_code`/`size_category`. `hasFullDetails = conditions !== null && resources !== null`. For an absent key that is `undefined !== null`, so true, and the panel then reads `conditions.length` |
| [`pages/CharacterSheetRoutePage.tsx`](../../portal/src/pages/CharacterSheetRoutePage.tsx) | `/characters/:id`. Sheet when `sections.sheet`, else `SummaryPanels` (heading, "The full sheet is not available to you.", `CharacterPanels`) |
| [`pages/CampaignWorldDetailPage.tsx`](../../portal/src/pages/CampaignWorldDetailPage.tsx) | `/world/character/:id`. A campaign-level `canon.edit` holder gets `WorldRecordWorkspace`. Everyone else gets `CharacterBoundary` → `CharacterDetailPage` |
| [`components/characters/CharacterRecordNav.tsx`](../../portal/src/components/characters/CharacterRecordNav.tsx) | Section row from `sectionsOf`. The Characters-route main entry is labelled "Summary" when `!sections.sheet`. A Details link-out appears when `sections.details` |
| [`utils/characterSections.ts`](../../portal/src/utils/characterSections.ts) | `sectionsOf` copies five known flags. A present `sections` is authoritative. An absent one falls back to `details/sheet/relationships` true and `inventory/parties` false. It drops `public_profile` |
| [`components/CharacterContextDetails.tsx`](../../portal/src/components/CharacterContextDetails.tsx) | Selected-perspective panel. Live species/size. `hasLiveState` uses the same `!== null` test. Death saves render `?? 0` |
| [`components/world/WorldRecordWorkspace.tsx`](../../portal/src/components/world/WorldRecordWorkspace.tsx), [`worldPaths.ts`](../../portal/src/components/world/worldPaths.ts), [`NpcRuntimePanel.tsx`](../../portal/src/components/NpcRuntimePanel.tsx) | Editor surfaces. They read the same route through `useAuthoringResource` and cast to `CharacterDetail`. They reuse `CharacterPanels`. `useKeptData` clears on 403/404 and keeps the last good read only on a transport/server error |
| [`pages/CharacterSheetPage.tsx`](../../portal/src/pages/CharacterSheetPage.tsx) | Takes `CharacterDetail`, mounted only when `sections.sheet` (full tier) |
| [`components/CharacterManageLinks.tsx`](../../portal/src/components/CharacterManageLinks.tsx) | Renders nothing without campaign `canon.edit`. A missing `authoring` defaults to `NO_RECORD_AUTHORING` |
| [`components/CharactersBrowser.tsx`](../../portal/src/components/CharactersBrowser.tsx) | Cards from world search. Its `summary` is the server's D5-c projection (released summary for a revelation-only reader, A3b). The card links to `/characters/:id`. No client-side projection |

Link producers that A4 made openable for a revealed reader (session roster `can_open_character`, character-relationship participants, organization members and event explanations `can_open`) all lead to the routes above. No browser storage holds character reads. `localStorage` holds only the sidebar and theme. The breadcrumb label registry holds only the canonical name, which D5-c allows at every tier.

### 1.3 Probe result: a public-tier answer crashes the reader page

An exact `PublicCharacterResponse` body rendered through `CharacterDetailPage` throws `TypeError: Cannot read properties of undefined (reading 'length')` and renders nothing. `sectionsOf` of that body returns the five flags without `public_profile`. The portal has no React error boundary (`grep` for `getDerivedStateFromError`/`componentDidCatch`/`errorElement` is empty). In the running app an uncaught render error therefore unmounts the root, which inference says would leave a blank page; no browser run confirmed this.

A4 §12.3 ("Clients") predicted that the existing page "renders a public-tier answer with its live-definition fields blank". The probe disproves that prediction. This plan records the correction here. The historical A4 text is not edited.

**Finding F-1 (pre-existing, owned by this slice).** A revelation-only reader who opens a revealed character through any now-openable link gets a crashed page instead of the public tier. Grading ([rubric](grading.md#scoring-factors)):

- **Supported-path exposure 1.** Revelations exist only through the HTTP API; the portal has no revelation UI until [D/P15-C02-S02](work-register.md#p15-c02-s02). The caller is a revealed player on a test or development campaign.
- **Impact 1.** A bounded page failure. Nothing is disclosed, because the throw happens before any field renders.
- **Triggerability 1.** It needs a constrained authenticated setup step.
- **Detection 0.** The failure is visible, and reload or navigation recovers.
- **Blast radius 0.**

Score 3, **Low**. Disposition: corrected by T01. That is the slice's purpose, so no separate defect entry is proposed. No disclosure was observed: every rendered value would come from absent keys.

**Other observations (not in scope).**

- `CharacterContextDetails` renders death saves as `?? 0` at the full tier, so a null renders "0 / 0". It is not a disclosure: the full tier is entitled. It is a presentation inaccuracy, Informational, and left unchanged to preserve existing full behavior.
- The `WITHOUT_SECTIONS` fallback grants `sheet` and `relationships`. It applies only to bodies without `sections`, and every A4 body carries them.

### 1.4 Independent sources, denies and stale state

These cases need no client policy, because the server decides each read. The client obligation is only to render each answer as a whole and keep nothing across tiers.

- A whole-character deny gives 404 at every tier. It is indistinguishable from a nonexistent record (`CharacterBoundary` → "Character unavailable").
- A `view_public_profile` deny gives 404 for a revelation-only reader. For a summary/full reader it gives an unchanged tier with a null section.
- Revoking a revelation leaves a summary/full tier from another source. Revoking that grant leaves the public tier while a revelation lives (§12.2).

The existing session, campaign and perspective handling already prevents cross-context reuse:

- `RouteSessionProvider` remounts per campaign.
- `CampaignLayout` keys the outlet on campaign and selected perspective.
- A 401 reloads the session.
- `useCharacter` ignores aborted or superseded answers.

**No backend contract gap was found.** Every field the portal needs is in the A4 DTO, and nothing in this slice needs a new server field.

## 2. Intended outcome

After T01 the portal consumes the A4 response as a tier-discriminated value. Its rendering:

1. **Public tier.** It renders exactly the canonical name, the kind label and the released `summary`, `appearance`, `background`, `species.label` and `size.label`. A null field is omitted. It never shows a live-definition, status, mechanics or authoring value, and never a fallback placeholder ("Not recorded", "0", "—") standing in for a withheld field. The section row offers only what `sections` grants. No sheet, builds, relationships or GM public-profile request is sent.
2. **Summary and full.** These tiers render exactly as today, plus a separately headed "Public profile" panel when `sections.public_profile` is true and `public_profile` is non-null. The live Overview (species, size) stays where it is and is never merged with the released values. When the section is false or null, nothing about a public profile is shown, including no "withheld" or "not released" text, because the server deliberately makes those cases indistinguishable.
3. **Unavailable.** 403 and 404 produce the one existing non-disclosing presentation, and the breadcrumb label is dropped. Other failures produce the existing retryable error and show no character content.
4. **Every new answer replaces the previous one wholesale.** This holds on direct entry, list-to-detail, refresh, Try again, a perspective/campaign change and a tier change in either direction. No field from an earlier, higher tier survives a later lower-tier or unavailable answer.

## 3. Scope, exclusions and prerequisites

**Prerequisites (met at baseline).**

- [a4](work-register.md#a4) merged (PR #68, `b0910c4`) and [r01](work-register.md#r01) owner accepted. These are the D/P15-C01 entry criteria.
- The slice row has no further entry criteria.
- [a5c](work-register.md#a5c) is a separate review-only obligation and does not block this slice.

**In scope (T01).**

- Portal types for the three tiers.
- Fail-closed normalization of the detail response.
- `sectionsOf` gains `public_profile`.
- A public-profile panel component.
- Tier-aware rendering in every consumer of the detail route listed in §1.2.
- Disclosure and transition tests.
- The two documentation updates in §4.

**Excluded (owning slice in parentheses).**

- Effective-access source labels and list/detail reconciliation after revocation ([D/P15-C01-S02](work-register.md#p15-c01-s02)).
- Draft editing and release ([D/P15-C02-S01](work-register.md#p15-c02-s01)).
- Revelation list/create/revoke ([S02](work-register.md#p15-c02-s02)), reveal delegation ([S03](work-register.md#p15-c02-s03)) and character-scoped denies ([S04](work-register.md#p15-c02-s04)).
- The copy UI ([copy-ui](work-register.md#copy-ui)) and the audience preview ([preview](work-register.md#preview)).
- Any production player-profile writer ([profile-authority](work-register.md#profile-authority)).
- Any backend, schema, Foundry or OpenAPI change.
- Polling or push to detect revocation while a page is open. The contract is "next request".
- Changing the full-tier `?? 0` observation (§1.3).

**Stop rule.** If implementation shows that the A4 response cannot support an outcome in §2, Sonnet stops and reports evidence without changing backend code: the request, the exact body and the outcome it blocks. Opus then states the smallest disposition.

## 4. Affected files and interfaces

**Types and normalization.**

- `portal/src/types/character.ts`:
  - add `CharacterIdentityValue {code, label}` and `CharacterPublicProfile`;
  - add `public_profile?: boolean` to `CharacterSections`;
  - keep the existing interface as the summary/full shape (`view_tier?: "summary" | "full"`, `public_profile?: CharacterPublicProfile | null`);
  - add `PublicCharacterDetail` (`view_tier: "public_profile"`, `character_id`, `name`, `character_kind`, `sections`, `public_profile`) and a union `CharacterRead`;
  - add a type guard `isPublicTier`.
  - Keep the existing name `CharacterDetail` for summary/full, to bound churn.
- `portal/src/api/character.ts`: `fetchCharacter` returns `CharacterRead` through a normalizer.
  - **`view_tier: "public_profile"`:** the normalizer requires a `public_profile` object and **projects to exactly the allowlisted keys**, so a key the DTO does not define never reaches a component. This is defense in depth, not reconstruction.
  - **`"summary"`/`"full"`:** passes through.
  - **Absent `view_tier`:** read as a pre-A4 summary/full body, following the existing `sections`-absent precedent.
  - **Any other value, or a public tier without a `public_profile` object:** throws a contract error, which the hook treats as `error` (safe wording, retry). It is never `success` and never a partial render.
- `portal/src/utils/characterSections.ts`: `public_profile: sections.public_profile === true`. The fallback sets it false.

**Rendering.**

- **New `portal/src/components/characters/CharacterPublicProfilePanel.tsx`.** A `DetailPanel` titled "Public profile" with a fact list for species and size labels and paragraphs for summary, appearance and background, in that order, omitting nulls. When every field is null it shows one neutral line: "No public details have been shared."
  - It takes only `CharacterPublicProfile`, so it cannot read live fields.
- **`pages/CharacterDetailPage.tsx`.** `CharacterPanels` accepts `CharacterRead`:
  - for the public tier, the public panel only;
  - for summary/full, the existing panels, with `hasFullDetails` based on `Array.isArray` for both arrays, plus the public panel when `sections.public_profile && public_profile !== null`.
  - `CharacterDetailPage` adds a public-tier line where the summary page says what is unavailable: "Only this character's public profile is available to you."
- **`pages/CharacterSheetRoutePage.tsx`.** `SummaryPanels` accepts `CharacterRead`. The sheet branch is only reachable at `sections.sheet`, and `CharacterSheetPage` is typed to the summary/full shape, narrowed at the call site.
- **`components/characters/CharacterRecordNav.tsx`.** It accepts `CharacterRead`. The Characters-route main label at the public tier is "Profile" (decision D-1, §10). Otherwise there is no behavior change.
- **`components/CharacterContextDetails.tsx`.**
  - Public tier: name-free identity rows from the released `species`/`size` labels only, omitting nulls. No live-state block.
  - Summary/full: unchanged except the `Array.isArray` guard.
- **`components/world/WorldRecordWorkspace.tsx` and `worldPaths.ts`.** The `WorkspaceDetail` union uses `CharacterRead`. `describe`, `typeCodeOf` and `statusOf` already read only `name`/`character_kind`/optional status, so for a public read they need only the type change. `CharacterPanels` handles the tier.
  - Reaching the editor workspace at the public tier needs campaign `canon.edit` without a character view tier. Every built-in GM role holds `character.view_full`, so only a custom-role state reaches it. The change exists so the type system forces safe handling, not to add an editor feature.
- **`components/NpcRuntimePanel.tsx`.** It treats a public-tier read as "not available to run", rendering the panel's existing non-disclosing unavailable path, with no hit-point or condition controls. It sends no command.
- **`hooks/useCharacter.ts`, `components/CharacterBoundary.tsx`, `pages/CampaignWorldDetailPage.tsx`.** Type changes only. The contract error maps to `error`.

**Documentation in the same commit.**

- `docs/api/READ_API.md` (the A4 bullets near "Sections at the public tier"). Replace "The portal types are unchanged until A6" with the implemented portal consumption: the three tiers, allowlist projection, no fallback values, and a null section indistinguishable from a deny.
- `docs/reference/portal-behavior.md` §5.5. One short paragraph on public-tier rendering and the separate "Public profile" panel at summary/full.
- This plan's implementation record (§11). Sonnet appends SHAs and runs.

**Test files.** Add to or extend:

- `src/api/character.test.ts`;
- `src/utils/characterSections.test.ts`;
- `src/pages/CharacterDetailPage.test.tsx`;
- `src/components/CharacterContextDetails.test.tsx`;
- `src/hooks/useCharacter.test.ts`;
- `src/App.characterRecord.test.tsx` for the route-level cases;
- one public-tier case each in `src/components/world/WorldRecordWorkspace.test.tsx` and `src/components/NpcRuntimePanel.test.tsx`;
- a new `src/components/characters/CharacterPublicProfilePanel.test.tsx`.

Existing assertions may change only where a fixture gains `view_tier`/`public_profile`/`sections.public_profile`. Any other changed existing assertion is a finding to report.

## 5. Task commits

The adopted sizing is kept: **one task commit, T01**, "Consume the released DTO and render public/full/unavailable cases with disclosure tests". The change is one coherent client contract adoption: types, one normalizer, one new panel, tier branches in about ten consumers, tests and two doc paragraphs. Splitting types from rendering would leave an intermediate commit whose type union forces unhandled branches, or one that renders the public tier with no disclosure tests. Neither is a reviewable safe state.

If the type ripple reaches files beyond §4, Sonnet records them in the implementation record. If it would require behavior changes outside §2, Sonnet stops and reports rather than splitting or expanding.

## 6. Acceptance cases

Bodies are the exact A4 shapes. "Markers" are distinctive strings placed in fields the tier must not render. Each case asserts both the rendered DOM and the request log of the mocked server.

| # | Case | Expected |
|---|---|---|
| A1 | Direct entry `/characters/:id`, public tier (`inventory`/`parties` false) | Heading = canonical name; kind eyebrow; "Public profile" panel with released values; section row = "Profile" (+ "Details" link-out); no request to `/sheet`, `/builds`, `/relationships`, `/inventory`, `/parties`, `/public-profile` |
| A2 | Direct entry `/world/character/:id`, public tier, non-editor | Same content under "Details"; no sheet link-out (`sections.sheet` false) |
| A3 | Public tier with `inventory` true / `parties` true | Those entries appear and their own endpoints are requested only when selected. Unchanged behavior |
| A4 | Public body carrying marker keys the DTO does not define (`species_code`, `size_category`, `current_hit_points`, `conditions`, `resources`, `authoring`, `canon_status`, `active_encounter_id`) | None of the markers render anywhere. The normalized object's key set equals the allowlist (unit) |
| A5 | Public profile with some or all fields null | Null fields are omitted. All-null shows the one neutral line. No "Not recorded", "0", "—" or "unknown" text |
| A6 | Summary tier with section | Existing Overview (live species marker) and a separately headed Public profile panel (released species label). Both visible and distinct. Mechanics remain absent as today |
| A7 | Summary/full with `public_profile: null`, `sections.public_profile: false` | DOM identical to the pre-change rendering of the same body: no public-profile heading and no withheld wording |
| A8 | Full tier with section, sheet route | Sheet unchanged; Details route shows existing panels plus Public profile |
| A9 | List-to-detail from the Characters browser to a revealed character | Opens the public tier. Back returns to the list with its URL state |
| A10 | Tier change on Try again or remount, full → public | No hit points, conditions, resources or live species marker remain |
| A11 | public → 404, and public → 403 | Released text is gone; the "Character unavailable" presentation is identical for 403, 404 and a nonexistent id; the breadcrumb label is dropped |
| A12 | public → summary (grant added) and summary → public (grant revoked, revelation live) | Each renders its own tier only |
| A13 | Superseded read: navigate from X (delayed public answer) to Y (summary) | X's answer never renders under Y's URL |
| A14 | 401 on the detail read | Session reload is invoked; no character content renders |
| A15 | 500, network error, unknown `view_tier`, or a public tier missing `public_profile` | Retryable error state with safe wording; no character content |
| A16 | `CharacterContextDetails` at the public tier | Released species/size labels only. No hit points, NaN or "0 / 0" |
| A17 | Editor workspace and `NpcRuntimePanel` given a public-tier read | They render without throwing and show no runtime controls. No command is sent |
| A18 | Existing summary/full suites | Pass unchanged apart from fixture additions |

## 7. Verification

**Automated, required for the T01 commit.** Run from `portal/`:

- `npm test`
- `npm run lint`
- `npm run build` (includes `tsc -b`)

Run from the checkout root:

- `uv run python scripts/check_documentation.py`
- `git diff --check`

No backend file changes, so `ruff`, `mypy`, `alembic check` and the shard runner are not required for this slice. If any file outside `portal/` and `docs/` changes, that is out of scope (§3): stop and report. CI `portal-check` runs at the integrated head after the owner pushes. The implementer does not push.

Report first runs and reruns separately. Record the focused test files run, the total test count, and any flaky rerun with its failure output.

**Proportionality.** The A4 server matrix (`tests/database/test_character_public_tier.py`) already proves who gets which tier. The portal tests prove only that each answer is rendered as itself, without residue or fallback. They do not re-derive authorization.

## 8. Browser, accessibility and owner obligations (separate events)

None of these is claimed by T01 or by its review. Each is recorded under its own owner at its own head.

1. **Real-browser persona run.** Owned by [browser](work-register.md#browser) at the integrated head. Use namespaced fixtures on a throwaway database and the alternate ports (8001/5174), never the owner's campaign or running servers. Revelations, grants and denies are created through the existing HTTP API, because their portal UI belongs to D/P15-C02. Personas:
   - revelation-only player (A1/A2/A9);
   - revelation plus `view_summary` grant, revoking each in both orders (A12);
   - whole-character deny (A11);
   - `view_public_profile` deny with a summary grant (A7);
   - GM (A8);
   - a non-member (403).

   Hard refresh on each URL. Record status, rendered text, network requests and the absence of markers.
2. **Keyboard and accessibility.** Owned by [ax](work-register.md#ax) at the integrated head:
   - one `h1` per route;
   - the "Public profile" panel is an `h2` region reachable in reading order;
   - section-row focus on arrival and section change (existing `useFocusOnSectionChange`);
   - the unavailable page focuses its heading (`ArrivalHeadingFocus`);
   - narrow viewport and zoom reflow;
   - no information conveyed by color.
3. **Owner acceptance.** Scoped acceptance of revelation and public profiles at [actor-a](work-register.md#actor-a), after D/P15-C01 and D/P15-C02 merge and the a5c, preview and copy-ui dispositions. The corrected Sella persona run belongs there, not here.

## 9. Intermediate states, save and read recovery

- **Single commit.** There is no intermediate repository state inside the slice. Before T01 the portal crashes on a public-tier answer (F-1). After T01 it renders it. No migration, no feature flag and no server coordination is involved.
- **No writes.** This slice issues no mutation, so there is no save recovery and no idempotency concern.
- **Read recovery.**
  - Try again re-issues the GET (`no-store`) and replaces state.
  - Refresh loads independently of any list.
  - A transport/server failure on the reader path shows the error state with no retained content. `useCharacter` keeps nothing.
  - On the editor path, `useKeptData` keeps the last good read only for a transport/server error, with a stale notice, and clears it on 403/404. That is existing, unchanged behavior. The kept value is the same caller's last authorized answer, never a higher tier than the server last granted that caller.
- **Revocation while a page is open** is visible on the next read, per the §12.2 contract. Live reconciliation of list and detail after revocation is S02.

## 10. Decisions

These are the only open points. Each has a recommendation, and none blocks Sonnet if the recommendation is taken.

- **D-1. Main-section label on `/characters/:id` at the public tier.** Today the label is "Summary" whenever the sheet is absent, which would misdescribe a public-tier page. *Recommendation:* "Profile" at the public tier, "Summary" unchanged at the summary tier. This is copy only, reversible, and does not touch authorization.
- **D-2. Where summary/full readers see the released profile.** *Recommendation:* in the shared `CharacterPanels`, so the reader Details page, the Characters summary page and the editor workspace's Details all show it read-only. D11 entitles each of those readers. [D/P15-C02-S01](work-register.md#p15-c02-s01) owns the GM draft/release editor and may later place a link beside the panel without changing this rendering.
- **D-3. A body without `view_tier`.** *Recommendation:* read it as a pre-A4 summary/full body, following the `sections` precedent. The A4 server always sends `view_tier`, so this affects only an older server, and such a body cannot be at the public tier. This is technical and needs no owner input unless the owner prefers to fail closed. Failing closed would turn any older-server answer into the error state.

## 11. Handoffs

### 11.1 Sonnet implementation instructions

1. Start on `phase15/completion` at the commit that records this plan. Record that SHA as the base, and record `git status --short`. Preserve unrelated work. Do not commit, stage or modify the plan's unrelated sections.
2. Read §1.2 and §4 against the source at the base. If a listed assumption no longer holds, stop and report.
3. Implement §4 as one commit. Order of work inside the commit:
   1. types;
   2. normalizer and its unit tests (A4, A15);
   3. `sectionsOf`;
   4. the panel and its tests (A5);
   5. each consumer;
   6. route-level tests A1–A3, A6–A14 and A16–A18;
   7. the two doc paragraphs.
4. **Rules.**
   - Never read a live field for the public tier.
   - Never construct `public_profile` from other fields.
   - Never render a fallback string for an absent field.
   - Never show withheld or deny wording.
   - Never add requests at the public tier beyond those `sections` grants.
   - Do not change any backend, Foundry or migration file.
   - Use the existing `PlaceholderPage`, `DetailPanel` and `FactGrid` vocabulary and the portal's class names. Add no new CSS unless a reflow defect requires it.
5. Run §7, record first runs and reruns separately, and commit with the message `P15-C01-S01-T01: render the public character tier` followed by the attribution lines. Do not push.
6. Append to §11.3: the base SHA, the T01 SHA, the commands with pass/fail and test counts, any deviation from §4 with its reason, and any test whose existing assertion changed beyond fixture additions.

### 11.2 Luna independent review

- **Boundary.** Base = the commit that records this plan (the parent of T01). Head = the T01 SHA, or the last correcting SHA after a correction. Review the whole range, not only the final diff.
- **Required evidence.**
  1. Confirm by reading that every consumer of the character detail route in `portal/src` handles `CharacterRead`. Re-run the `grep` for `CharacterDetail`, `fetchCharacter` and `/characters/` reads.
  2. Confirm the normalizer's allowlist equals `PublicCharacterResponse`/`CharacterPublicProfileResponse` in `src/dnd_ai/api/characters.py` at the head.
  3. Run `npm test`, `npm run lint` and `npm run build`, plus the doc check and `git diff --check`. Report first runs and reruns separately.
  4. Check acceptance cases A1–A18 against the tests, including at least one mutation probe. For example, make the public panel read `species_code`, or drop the `Array.isArray` guard, and show that a test fails. Restore afterwards and record it.
  5. Check that no existing assertion changed beyond fixture additions.
  6. Check that the §3 exclusions were not entered.
- **Verdict.** Use the [rubric](grading.md#severity-and-checkpoint-disposition) terms. Grade each finding separately. Browser, accessibility and owner events (§8) are not part of this verdict.

### 11.3 Implementation record

Recorded by Sonnet, 2026-11-19. Real-browser, accessibility, checkpoint-merge and owner events (§8) are not claimed here.

**Base and head.**

- Review base (implementation base): `4645d243e3825586985926f9677ffead71e5976c` on `phase15/completion` ("Improve delivery register execution presentation"), the commit the plan names. HEAD had not advanced, and `git status --short` was clean before work. No `AGENTS.md` exists on the repository path.
- T01 head: the commit titled `P15-C01-S01-T01: render the public character tier` (the child of the base). Its SHA is not written inside itself; read it with `git log --oneline -1 --grep "P15-C01-S01-T01"` and it is reported in the handoff. Nothing was pushed.

**Source assumptions (§1.2, §4).** Re-read at the base before editing; all held. `grep` still found no `view_tier` or `public_profile` in `portal/src`. The allowlist in the normalizer equals `PublicCharacterResponse` and `CharacterPublicProfileResponse` in `src/dnd_ai/api/characters.py` at this head (`view_tier`, `character_id`, `name`, `character_kind`, `sections`, `public_profile`; `summary`, `appearance`, `background`, `species`, `size`).

**What was implemented (all under `portal/` and `docs/`).**

- Types: `CharacterIdentityValue`, `CharacterPublicProfile`, `PublicCharacterDetail`, the union `CharacterRead`, `isPublicTier`; `CharacterSections.public_profile?`; `CharacterDetail` keeps its name as the summary/full shape.
- `api/character.ts`: `normalizeCharacterRead` (fail-closed, allowlist projection) and `CharacterContractError`; `fetchCharacter` returns `CharacterRead`. `editorCharacterRead` is the lenient variant for the two raw-JSON editor paths (below).
- `sectionsOf` carries `public_profile` (true only when `=== true`; the fallback sets false).
- New `CharacterPublicProfilePanel`; `CharacterPanels` branches on tier, uses `Array.isArray` for the live-state guard, and adds the panel at summary/full when `sections.public_profile` and a non-null profile. The public tier shows the one-line "Only this character's public profile is available to you." note.
- `CharacterRecordNav` (D-1: "Profile" at the public tier), `CharacterSheetRoutePage`, `CharacterContextDetails` (released labels only at the public tier), `WorldRecordWorkspace`/`worldPaths`, `NpcRuntimePanel`, `CharacterBoundary`, `useCharacter` (type changes; a contract error reaches the existing `error` state).
- Docs: READ_API (portal consumption bullet, replacing "unchanged until A6"), portal-behavior §5.5 paragraph, this record, the register rows.

**D-3 rule used (precise).** A body is read as summary/full without `view_tier` only when ALL hold: it is an object; `character_id` and `name` are strings; `character_kind` is `npc`, `player_character` or `character`; `species_code` and `size_category` are strings; `conditions` and `resources` are each present as an array or `null`; there is no `public_profile` key; and `sections` is absent or an object. Anything else without a tier (including a public-shaped body whose `view_tier` is missing, and a body without the live definition) throws `CharacterContractError`. This matches the existing `sections`-absent precedent and the pre-tier `CharacterDetail` type, whose live definition and the two state keys were always present. With `view_tier` of `summary` or `full`, the identity fields and an object `sections` are required and a present profile must be well formed. Missing `view_tier` alone never manufactures full access.

**Deviations from §4 (each with its reason).**

1. **Editor paths use a lenient reader.** `WorldRecordWorkspace` and `NpcRuntimePanel` hold raw JSON through `useAuthoringResource` and their existing tests use partial bodies (for example no `character_kind`). A strict reader there broke 15 `NpcRuntimePanel` tests and one `App.characterBuilds` case on the first run. `editorCharacterRead` applies only the tier rules (public tier rebuilt from the allowlist; unknown tier or a public-shaped body without a tier refused; a body with no tier and no profile passes as before). Refused workspace reads show "Character information is unavailable."; the NPC panel shows "This NPC is not available to run." with no controls.
2. **`authoringOf` parameter type widened** to `object | null | undefined` (`utils/recordAuthoring.ts`) so a public-tier body, which carries no `authoring`, type-checks. Behavior is unchanged: no `authoring` means no rights.
3. **Files beyond §4's list:** `utils/recordAuthoring.ts`, the new `fixtures/publicCharacter.ts` (shared exact A4 bodies and markers), and `App.characterBuilds.test.tsx` (below).
4. **Panel structure.** Inside the profile panel the three text fields use `h3` labels (Summary, Appearance, Background) under the panel's `h2`; species and size use `FactGrid`. Plan §4 left this open.
5. A14 is asserted at route level as "no character content" and at hook level through the existing unauthorized-reload test; the route harness does not expose the session `reload` mock. A13 is asserted at hook level (superseded read), not as a route test.

**Existing assertions changed.** None weakened. Beyond fixture additions, only:

- `utils/characterSections.test.ts`: the `NONE` and `ALL` constants and the legacy-fallback expected object gained `public_profile` (false/true/false). This is an expected-value change because `sectionsOf`' output gained a key; the assertions are otherwise identical.
- `App.characterBuilds.test.tsx`: the character fixture gained `character_kind: "player_character"` (a field the real body always carries and the type requires). Without it the non-editor read is not the recognized pre-tier shape and is refused.

**Verification runs (portal/, PowerShell; Git Bash cannot run Vitest here, as the plan noted).** Focused files were run throughout (`api/character`, `characterSections`, `useCharacter`, `CharacterDetailPage`, `CharacterPublicProfilePanel`, `CharacterContextDetails`, `App.characterRecord`, `NpcRuntimePanel`, `WorldRecordWorkspace`, `App.characterBuilds`).

| Run | Result |
|---|---|
| First `npm test` after the strict editor reader | 20 failed / 5121 passed (3 files: the 4 `characterSections` expected-value changes above, 15 `NpcRuntimePanel`, 1 `App.characterBuilds`); also 1 `App.knowledgeMemberPreview` failure in the first full run that passed alone (load-sensitive, unrelated) |
| Fixes | lenient editor reader (deviation 1); fixture addition; expected-value additions |
| Second full `npm test` | 1 failed / 5215 passed: `App.readRecovery` "keeps focus on the retry button" (focus assertion on an event page, unrelated to characters); it passed alone (12/12) |
| Third full `npm test` (after a type fix in two new test files) | 426 files, 5216 tests, all passed |
| `npm run lint` | passed (first run and rerun) |
| `npm run build` | first run failed with two type errors in my new tests (`api/character.test.ts`, `App.characterRecord.test.tsx`); passed on rerun after the casts were fixed |
| Mutation probe | Replaced `Array.isArray` with `!== null` in `CharacterPanels`. The first test version did not fail (it deleted only one key); the test now deletes both and fails under the mutation, and passes restored. The probe was reverted; the working file is the unmutated source |

The documentation check and `git diff --check` results are recorded in the handoff for this commit. No backend, Foundry, migration or OpenAPI file changed.

**Acceptance coverage.** A1, A2, A3, A5, A6, A7, A8, A9, A10, A11, A12, A14 (route), A15 in `App.characterRecord.test.tsx`; A4 and A15 (normalizer, allowlist, D-3) in `api/character.test.ts`; A5 in the panel and detail-page tests; A6/A7/A8 also in `CharacterDetailPage.test.tsx`; A10–A13, A15 and the 401 reload in `useCharacter.test.ts`; A16 in `CharacterContextDetails.test.tsx`; A17 in `WorldRecordWorkspace.test.tsx` and `NpcRuntimePanel.test.tsx`; A18 by the unchanged existing suites (426 files passed).

**Remaining limitations.** The route harness does not exercise a session-expiry reload at route level (A14), and a superseded read is covered at hook level only (A13). A real-browser run, accessibility checks and owner acceptance are separate (§8). Revocation while a page is open is seen on the next request only.

## 11.4 Independent review (Luna), 2026-11-19

**Boundary and checkout.** Reviewed the complete range `4645d243e3825586985926f9677ffead71e5976c..63eda42bb8764ba236bdd8743bbfb6b9f23c2ede` on `phase15/completion`. HEAD was `63eda42bb8764ba236bdd8743bbfb6b9f23c2ede`; the checkout was clean and one commit ahead of `origin/phase15/completion`. No push or branch switch was needed. No repository-path `AGENTS.md` was present. No production changes were made.

**Verdict: CHANGES REQUIRED.** The tiered reader path meets the public-profile projection and ordinary read-transition contract. One acceptance-blocking, Low-severity finding remains in the editor adapter.

### Finding L-1 — editor adapter accepts malformed un-tiered reads

- **Track / score:** Application. Supported-path exposure 1 (authenticated `canon.edit` users on the World workspace or NPC runtime panel, when a legacy or malformed read is returned); impact 1 (incorrect editor/runtime content and available controls); triggerability 1 (requires a nonconforming response); detection/recovery 0 (visible and a fresh read recovers); blast radius 0 (one record). Score 3, Low. The current A4 server always emits `view_tier`, and the ordinary reader uses the strict normalizer, so this does not establish a current lower-tier reader disclosure.
- **Evidence and trigger:** `portal/src/api/character.ts`, `editorCharacterRead`, accepts every object with no `view_tier` and no `public_profile` at lines 175–185. It does not call the strict normalizer or require the pre-tier shape. The unit test at `portal/src/api/character.test.ts` explicitly treats `{ character_id, name }` as an accepted read at lines 233–235. `WorldRecordWorkspace` then passes that value to `CharacterPanels`; `NpcRuntimePanel` treats every non-public non-null result as runnable and mounts its controls. An incomplete body with live fields (or a `summary`-tier body carrying mechanics) can therefore be interpreted as an editor/runtime read. The runtime request still has server-side authorization; no unauthorized command or current-server response was demonstrated.
- **Expected / actual:** Only a valid public, summary/full or explicitly recognized pre-tier body should reach rendering. Unknown, incomplete and contradictory bodies should fail closed. Actual: the special editor adapter preserves partial test-fixture shapes and bypasses the stricter D-3 legacy validation. The implementation record's rationale identifies those partial fixtures as the cause; it does not establish a production compatibility requirement for incomplete legacy responses.
- **Readiness:** Blocks this slice because the read boundary accepts malformed bodies and the editor route can render them or offer runtime controls, contrary to the declared fail-closed boundary. Keep Low product severity separate from this specific acceptance failure.
- **Bounded correction:** Make editor reads accept the same recognized public and pre-tier shapes as the ordinary path, validate the `summary`/`full` envelope before rendering, and ensure the NPC runtime panel cannot offer controls for a lower-tier answer. Update partial fixtures to valid legacy bodies where they are intended to represent an old server; otherwise assert the controlled unavailable state. Add focused tests for incomplete un-tiered and contradictory lower-tier bodies in both editor surfaces, including request logs proving no command is sent. Keep the change in `portal/` and do not alter backend behavior.

### Review evidence

- **Contract and consumer review:** Compared the allowlist to `PublicCharacterResponse` and `CharacterPublicProfileResponse` in `src/dnd_ai/api/characters.py`; read the current register, A4 access/read contracts, portal behavior and the entire base-to-head diff. Public normalization projects the public envelope and each nested profile value; unknown tiers and incomplete public bodies are rejected. Ordinary fetch, both routes, context panel, navigation and section-triggered requests use the tier-aware read. No new public-profile fetch is introduced. The workspace and NPC panel are separately guarded for a public-tier answer, but the lenient non-public adapter is the finding above. Editor retained data follows the existing `useKeptData` rule: it clears on loading, 403/404 and record/owner changes, and retains the last good same-owner answer only on transport/server error with a stale notice.
- **Acceptance map:** A1–A3 route and request-log assertions; A4/A15 normalizer tests; A5 profile and null-field assertions; A6–A8 summary/full rendering; A9 list navigation and return state; A10–A12 tier/unavailable transitions; A13 hook-level superseded-read assertion; A14 route content assertion plus existing hook 401 reload assertion; A15 retry/error assertions; A16 selected-context test; A17 editor/NPC tests; A18 full existing suite. Hook-level A13 directly exercises the request ordering and stale-answer suppression, so an extra duplicate route test is not required. A14's route and hook tests jointly cover content removal and reload invocation; the route harness limitation is recorded in §11.3. Route tests inspect request logs for granted/withheld sections and commands where applicable.
- **Plan deviations:** D-1/D-2 and the panel structure are within the plan's decisions. D-3 is strict in `normalizeCharacterRead`; the editor-only leniency is not justified by an established production compatibility contract and requires correction. A13/A14 test placement is reasonable. Fixture/expected-value changes recorded in §11.3 do not weaken pre-existing assertions. No excluded backend or separate-slice work was added.
- **Verification (reviewer's independent runs):** `npm test` passed: 426 files, 5216 tests. `npm run lint` passed. `npm run build` passed with the existing Vite chunk-size warning. `uv run python scripts/check_documentation.py` passed. `git diff --check 4645d243e3825586985926f9677ffead71e5976c 63eda42bb8764ba236bdd8743bbfb6b9f23c2ede` passed. The implementation record's earlier failed runs and subsequent passes remain separate evidence; this review's first full runs passed.
- **Mutation probe:** Temporarily replaced the `Array.isArray` live-state guard in `CharacterPanels` with a null-only check. `CharacterDetailPage.test.tsx` failed on the missing-key regression with `Cannot read properties of undefined (reading 'length')`. Restored the original bytes immediately; SHA-256 before and after was `441881B480E9FD1D26F391333A2BABDD976C8BB49A7AA034A90AE9082662FBBD`. No probe change remains.
- **Remaining obligations:** Real-browser persona/network verification remains with `browser`; keyboard and accessibility checks remain with `ax`; owner acceptance remains with `actor-a`, each at its integrated-head boundary. Portal CI is still required after push/integration. This slice alone does not establish checkpoint merge readiness. A5c remains separate; P15-C01-S02 and the separate A5c review were not started.

**Correction handoff:** Sonnet: fix only L-1 in the portal editor read boundary and its focused fixtures/tests; preserve public allowlist projection, valid pre-tier compatibility, editor retained-data behavior, request boundaries and unrelated working changes. Run the focused tests plus the documented portal suite, lint, build, documentation check and diff check; record first runs and reruns. Do not change backend files, push, merge, begin S02, or perform A5c. **Luna re-review boundary:** exact correction base = `63eda42bb8764ba236bdd8743bbfb6b9f23c2ede`; head = the correction commit (or last correcting commit), reviewing the full base-to-head range and updating only this owning review record and the two register status cells.

## 11.5 Correction of L-1 (Sonnet), 2026-11-19

Luna's finding and verdict above are unchanged. This section is the correction evidence; it does not accept the slice. **Status: corrected; Luna re-review pending.**

**Base and head.** Starting HEAD `63eda42bb8764ba236bdd8743bbfb6b9f23c2ede` (the review base) on `phase15/completion`. Before work the tree held only Luna's two uncommitted edits (this plan's §11.4 and the register status cells); both are preserved and committed with the correction. No `AGENTS.md`. The correction commit is titled `P15-C01-S01: validate editor character reads and runtime eligibility`; its SHA is reported in the handoff, not inside itself. Nothing was pushed. Only `portal/` and `docs/` changed.

**What changed (portal).**

- `api/character.ts`: `editorCharacterRead` no longer has its own permissive rules. It calls `normalizeCharacterRead` and returns `null` for a `CharacterContractError`, so editor reads accept exactly the reader's recognized shapes (public, summary/full, the D-3 pre-tier shape). The public allowlist and nested projection are the same code as before.
- `normalizeCharacterRead` now refuses a **contradictory summary body**: a `summary` tier answer carrying any of the fields the server nulls at that tier (hit points, temporary hit points, exhaustion, death saves, location, encounter, conditions, resources) throws. A full tier body is unchanged.
- New `isRunnableRead`: an answer is runnable only at the `full` tier or as a recognized pre-tier body. Public and summary are not.
- `NpcRuntimePanel`: controls are offered only when the answer is recognized **and** `isRunnableRead`; otherwise the existing "This NPC is not available to run." frame is shown with no form, button or field. The `canon.edit` gate, the page's status text and the status/blocked logic are unchanged and still apply on top. The panel's `detail` and status fields now come from the recognized read.
- `WorldRecordWorkspace`: the heading name, breadcrumb name and the kind that decides which sections (Run, Player, edit links) are offered now come from the recognized read; an unrecognized answer shows "Character information is unavailable." with no name, panels, links or NPC section.

**Pre-tier rule used (unchanged, D-3).** `character_id` and `name` as text, a known `character_kind`, `species_code` and `size_category` as text, `conditions` and `resources` each present as an array or `null`, no `public_profile` key. A recognized pre-tier body is treated as the full read of a server that predates tiers, so it is runnable (the server still authorizes each command). This is the one place a body without `view_tier` can reach controls, and only when it satisfies that rule.

**Fixtures.** The NPC panel's default and re-read fixtures were partial (no `character_kind`) and are now valid pre-tier bodies (`character_kind: "npc"` added). The previous test that asserted `{ character_id, name }` is accepted was replaced by one asserting it is refused. No other existing assertion was changed or weakened.

**New tests.**

- `api/character.test.ts`: editor read refusals (incomplete body, missing live key, summary carrying hit points or conditions, full without sections) and acceptances (valid full, summary, pre-tier); `isRunnableRead` for full, pre-tier, summary and public; the contradictory-summary refusals.
- `NpcRuntimePanel.test.tsx`: incomplete un-tiered, un-tiered without live-state keys, malformed public, summary carrying live mechanics, valid summary, and full without sections each show the unavailable state with **no forms, buttons, text fields or comboboxes**, no hit-point or condition text, and no non-GET request. A valid full answer runs and sends exactly the one command asked for. A transition test runs a command from a runnable read, then the next read is a summary answer or a malformed one: the controls are withdrawn and the request log holds exactly the one earlier command, none after.
- `WorldRecordWorkspace.test.tsx`: unknown tier, incomplete un-tiered, malformed public and summary-with-mechanics bodies show the unavailable state with no name, sheet or edit link, no Current state panel and no NPC Run section, and no non-GET request; the public tier still shows only the released profile; valid full-tier and pre-tier reads still show the sheet link and heading.
- Mutation probe: loosening `isRunnableRead` to "not public" failed the three tests that assert a summary answer is not runnable; the source was restored.

**Preserved.** The exact public allowlist and nested projection; valid pre-tier compatibility; the authorized full-tier behavior; retained data (`useKeptData`: a transport/server error still keeps the last good read with the stale notice, and the existing re-read failure test passes unmodified); read-recovery and request boundaries. No backend, migration, Foundry or OpenAPI file changed.

**Docs.** `READ_API.md` (Portal consumption) and `portal-behavior.md` §5.5 now state that the editors' pages recognize an answer by the reader's rules, that a summary body carrying live fields is refused, and that the runtime panel is offered only for a full-tier or pre-tier answer.

**Verification (portal/, PowerShell).**

| Run | Result |
|---|---|
| Focused: `api/character`, `NpcRuntimePanel`, `WorldRecordWorkspace` first run | 1 failed / 171 passed: a re-read test in `NpcRuntimePanel.test.tsx` used a second partial fixture without `character_kind` (fixed to a valid pre-tier body) |
| Focused after that fix, first workspace test run | 5 failed: my new test asserted that no request for the NPC runtime options is made, which the page makes for its own reasons (removed, since it is a read), and a "Use in play" link assertion that is wrong because the section every character shares remains (replaced by assertions that no Run section or NPC form is offered) |
| Focused rerun | 3 files, 186 tests passed |
| `npm test` | 426 files, 5236 tests passed (first run; no failures) |
| `npm run lint` | passed |
| `npm run build` | passed (existing chunk-size warning) |
| `uv run python scripts/check_documentation.py` | see handoff |
| `git diff --check` | see handoff |

**Remaining limitations.** Real-browser, accessibility, integrated-head CI, checkpoint merge and owner acceptance remain separate and pending. A pre-tier body is runnable by the portal; the server remains the only authority for each command. A5c and P15-C01-S02 were not started.

**Luna re-review boundary.** Base `63eda42bb8764ba236bdd8743bbfb6b9f23c2ede`; head = the correction commit.
