# D/P15-C01-S01 implementation plan: render the public character tier

**Status:** proposal, prepared 2026-11-19 for Sonnet. Nothing in this plan is implemented. Work-register row: [D/P15-C01-S01](work-register.md#p15-c01-s01), task [T01](work-register.md#p15-c01-s01-t01). Parent PR: [D/P15-C01](work-register.md#p15-c01).

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

*Empty. Sonnet appends here.*
