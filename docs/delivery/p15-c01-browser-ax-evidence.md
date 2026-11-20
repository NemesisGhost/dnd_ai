# D/P15-C01 browser and accessibility evidence

**Status:** recorded 2026-11-19 by Sonnet. Scripted real-browser and structural accessibility evidence for [D/P15-C01](work-register.md#p15-c01) (S01 public tier, S02 effective access). **Not** a human run, **not** an assistive-technology run, and **not** owner acceptance. The register's [browser](work-register.md#browser), [ax](work-register.md#ax) and [actor-a](work-register.md#actor-a) obligations keep their own scope and status; this record is the C01 slice of them.

## 1. What was tested

- **Tested commit:** `efe5a77d4fe0d668d7e8aed6e74864b46ce8f57f` ("docs: record P15-C01-S02 independent review pass") on `phase15/completion`. Its portal and API source is the S02 review head `df74749` plus documentation only; no source file changed afterwards. The portal was a **production build** (`vite build`, then `vite preview`) of that tree, not the dev server, so React StrictMode did not double the reads (the dev server shows two identical character GETs on a hard load; the production build shows one).
- **Stack:** API `uvicorn dnd_ai.api.app:app` on `127.0.0.1:8001` and the portal on `127.0.0.1:5174`, never the owner's 8000/5173 servers. Throwaway PostgreSQL 18 database `dnd_ai_c01_browser_20261119` on the local cluster (migrated to head 149, seeded with `scripts/setup_phase13c_dev_data.py`), dropped after the run. Chrome 158.0.8127.36 (headless, Playwright-core 1.49.1 driving the installed Chrome), Node 24.13.1.
- **Fixtures** (namespaced `C01`, in the throwaway database only): Campaign A of the 13C dev dataset; the GM is a new admin account with `access.manage`; Player A (`phase13e.player_a`, owner of Character A) is the persona. Character B (not visible to Player A before the run: 404) and Character A each have a released public profile ("C01 released summary…"). Revelations, summary grants and revocations were created through the HTTP API as the GM. **Two kinds of row cannot be created over HTTP and were written directly into the throwaway database with the repository's own test factory (`tests.factories.make_resource_grant`), exactly as the repository's database tests write them:** the whole-character `campaign.view` deny and the `character.view_public_profile` deny (the grant API refuses a character through `entity_id`, and `view_public_profile` is not a grantable capability).
- **Sign-in:** one sign-in per persona; no credential is printed or recorded. A non-member persona (`phase13e.player_b`, a Campaign B member) was used.
- **Network evidence:** every check also records the requests the page made. For the player personas the character read was the only request for that character, and no request went to `/effective-access` or `/access-overview`.
- **Artifacts (outside the repository):** `C:\Users\nemes\dnd_ai_evidence_20261119\c01\` holds the scripts (`lib.mjs`, `setup.mjs`, `setup2.mjs`, `s01.mjs`, `ax.mjs`, `s02.mjs`, `denytool.py`), the raw logs and result JSON, 27 screenshots (`shots\`) and two accessibility-tree snapshots (`aria-*.yml`). The tables below are generated from the result JSON.

## 2. Result summary

| Run | Checks | Passed | Failed |
|---|---|---|---|
| S01 personas | 29 | 29 | 0 |
| Structure, keyboard, viewport, zoom | 18 | 18 | 0 |
| S02 Access page | 30 | 30 | 0 |

Of the 30 S02 checks, three (`G1-obs`) pass because they **record** behavior that differs from what S02's plan and tests state for a mutation; see finding C01-B1 in §4. The first run of each script on a freshly rebuilt database is the run recorded; earlier runs were used to debug the harness and the fixture reset (§5).

## 3. Results

Each row is one scripted check on the recorded run. 'Observed' is what the page or network showed (trimmed).

### S01 personas (public character tier)

| # | Check | Result | Observed |
|---|---|---|---|
| 1 | P1 characters: GET character 200 public tier | pass | status 200 |
| 2 | P1 characters: one h1 "Phase13C Character B" | pass | ["Phase13C Character B"] |
| 3 | P1 characters: "Public profile" h2 and released text | pass | ["Public profile"] |
| 4 | P1 characters: no live data, no source wording | pass | clean |
| 5 | P1 characters: only the character read, nothing else requested for it | pass | ["GET /campaigns/{A}/characters/{B}"] |
| 6 | P1 characters: no request to access endpoints | pass |  |
| 7 | P1 world: GET character 200 public tier | pass | status 200 |
| 8 | P1 world: one h1 "Phase13C Character B" | pass | ["Phase13C Character B"] |
| 9 | P1 world: "Public profile" h2 and released text | pass | ["Public profile"] |
| 10 | P1 world: no live data, no source wording | pass | clean |
| 11 | P1 world: only the character read, nothing else requested for it | pass | ["GET /campaigns/{A}/characters/{B}"] |
| 12 | P1 world: no request to access endpoints | pass |  |
| 13 | P1 A9: revealed character is in the list; opening and Back returns to the list URL | pass | http://127.0.0.1:5174/app/{A}/characters/all?type=player_character |
| 14 | P2 setup: summary grant created | pass | status 201 {"resource_grant_id":"d1fd9f0a-be0f-40c1-b9ab-708abbf53993"} |
| 15 | P2 summary tier: Overview + separate Public profile; summary tier read | pass | ["Overview","Public profile"] |
| 16 | P2 summary tier: no source wording | pass |  |
| 17 | P2 grant revoked -> public tier again (no Overview, profile only) | pass | ["Public profile"] |
| 18 | P2 setup: revelation revoked while grant held | pass | status 200 |
| 19 | P2 grant only (revelation gone): summary tier, live Overview, no source wording | pass | ["Overview","Public profile"] |
| 20 | P2 link arrival at the unavailable page focuses its heading (ArrivalHeadingFocus) | pass | h1:Character unavailable |
| 21 | P2 both revoked: non-disclosing unavailable page (404), no character text | pass | status 404 h1=["Character unavailable"] |
| 22 | P3 setup: whole-character deny row (fixture, as the repo database tests write it) | pass | 0e92da20-e36c-4261-959f-f0ebe3692c91 |
| 23 | P3 whole deny beats revelation: 404, unavailable page, no released text | pass | status 404 |
| 24 | P4 setup: summary grant (API) and public-profile deny row (fixture) | pass | 201/94f46103-e2cc-4302-81f0-cac8d4570018 |
| 25 | P4 summary tier without Public profile panel and no wording about it | pass | ["Overview"] |
| 26 | P5 GM characters: full tier; Sheet/Details row; no source wording | pass | ["Current State","Ability Scores & Saving Throws","Skills","Other Proficiencies","Languages","Senses","Conditions","Resources","Features & Traits","Spellcasting"] |
| 27 | P5 GM world: full tier; Sheet/Details row; no source wording | pass | ["Details","Overview","Public profile","Current state","Conditions","Resources","Sources","Relationships","Review","Publication","Player","Inventory"] |
| 28 | P5 GM world route shows live Overview/Current state beside Public profile | pass | ["Details","Overview","Public profile","Current state","Conditions","Resources","Sources","Relationships","Review","Publication","Player","Inventory"] |
| 29 | P6 non-member: character read refused (404/403), no character text | pass | status undefined; h1=["Campaign not found"] |

29 of 29 checks passed.

### Structure, keyboard, viewport and zoom

| # | Check | Result | Observed |
|---|---|---|---|
| 1 | AX public tier characters: exactly one h1 | pass | ["h1:Phase13C Character B"] |
| 2 | AX public tier characters: "Public profile" is an h2 after the h1 in reading order, fields are h3 | pass | ["h1:Phase13C Character B","h2:Public profile","h3:Summary","h3:Appearance","h3:Background"] |
| 3 | AX public tier characters: the panel is a labelled section (region named "Public profile") | pass | {"labelled":true,"hasRole":"SECTION"} |
| 4 | AX public tier world: exactly one h1 | pass | ["h1:Phase13C Character B"] |
| 5 | AX public tier world: "Public profile" is an h2 after the h1 in reading order, fields are h3 | pass | ["h1:Phase13C Character B","h2:Public profile","h3:Summary","h3:Appearance","h3:Background"] |
| 6 | AX public tier world: the panel is a labelled section (region named "Public profile") | pass | {"labelled":true,"hasRole":"SECTION"} |
| 7 | AX section change (Profile -> Details link, PUSH): where focus lands | pass | focus=h1:Phase13C Character B |
| 8 | AX no information by colour alone: the public tier is text and headings only (no status colours, no meters); rendered in achromatopsia emulation for review | pass | screenshot ax-public-achromatopsia.png |
| 9 | AX reflow public tier at 320px (400% zoom equivalent): no horizontal page scroll | pass | {"sw":320,"cw":320} |
| 10 | AX reflow public tier at 640px (200% zoom equivalent): no horizontal page scroll | pass | {"sw":640,"cw":640} |
| 11 | AX reflow public tier at 360px phone: no horizontal page scroll | pass | {"sw":360,"cw":360} |
| 12 | AX keyboard: the card opens with Enter on its summary, and the explanation with Enter on its toggle | pass |  |
| 13 | AX Access card: Revealed characters h3 follows Direct resource access and precedes the explanation h4 in reading order | pass | ["h3:Roles","h3:Character access","h3:Direct resource access","h3:Revealed characters","h4:Why Phase13E Dev Player A can see this"] |
| 14 | AX keyboard: the Refresh access button shows a focus indicator | pass | solid 3px / shadow none |
| 15 | AX keyboard: Enter on Refresh access, then focus returns to the explanation toggle and aria-expanded stays true | pass | focus=explain-toggle |
| 16 | AX the announcement region is role=status aria-live=polite and carries 'Access list refreshed.' | pass | {"role":"status","live":"polite","text":"Access list refreshed."} |
| 17 | AX reflow Access card (Revealed characters + open explanation) at 320px (400% zoom equivalent): no horizontal page scroll and nothing wider than the card | pass | {"sw":321,"cw":320} overflowing=0 |
| 18 | AX reflow Access card (Revealed characters + open explanation) at 640px (200% zoom equivalent): no horizontal page scroll and nothing wider than the card | pass | {"sw":640,"cw":640} overflowing=0 |

18 of 18 checks passed.

### S02 Access page (explanation and Refresh access)

| # | Check | Result | Observed |
|---|---|---|---|
| 1 | G1 explanation lists a Revelation source per character and the relationship | pass | Hide access explanation \| Why Phase13E Dev Player A can see this \| View Campaign \| Role: Player \| Discover Character \| Character access: Owner (Phase13C Character A) |
| 2 | G1 Revealed characters section lists both, read-only (no button/link inside) | pass | Revealed charactersPhase13C Character A — MemberPhase13C Character B — Member |
| 3 | G1 no id, audience-kind code or revelation id rendered | pass | scanned main text for codes and uuids |
| 4 | G1 request order: revoke, then the list is read again | pass | ["POST POST revoke","GET overview"] |
| 5 | G1 revoked source gone from Character access; Revealed characters unchanged | pass |  |
| 6 | G1-obs the mutation's session reload() remounts the page: the open explanation is closed again (differs from plan E5 'still open') | pass | aria-expanded after=false |
| 7 | G1-obs the persistent announcement does not survive that remount (differs from plan E5 'announced') | pass | "" |
| 8 | G1-obs focus after the mutation reload (inherited O-3) | pass | focus=BODY |
| 9 | G1 reopened explanation shows the surviving revelation sources and no relationship source | pass | Hide access explanation \| Why Phase13E Dev Player A can see this \| View Campaign \| Role: Player \| Discover Character \| Revelation: Member (Phase13C Character A) \| R |
| 10 | G2 refresh re-reads the list then the explanation | pass | ["GET overview","GET explain:a38edc"] |
| 11 | G2 the revoked revelation is gone from both list and explanation; survivor remains | pass | Revealed charactersPhase13C Character B — Member |
| 12 | G2 'Access list refreshed.' announced only after the list was read | pass | Access list refreshed. |
| 13 | G2 success: focus restored to that member's explanation toggle (Refresh control was removed by the reload) | pass | button[explain-toggle:a38edc40]:Hide access explanation |
| 14 | G2 explanation still open, aria-expanded=true | pass |  |
| 15 | G4 while pending: the loading page is shown, no explanation or member content is in the DOM | pass |  |
| 16 | G4 focus stays on the control the manager moved to ("Invitations" tab link) after the refresh completes | pass | moved to a:Invitations; after: a:Invitations |
| 17 | G4 the refresh still completed (announcement and explanation reloaded, list intact) | pass | Access list refreshed. |
| 18 | G5a failed list read: the error page shows with a Try again button; no member, source or explanation content remains | pass |  |
| 19 | G5a no 'refreshed' announcement for the failed read | pass | "" |
| 20 | G5a Try again: refreshed is announced only now; the open explanation was re-read (list first) | pass | ["GET overview","GET explain:a38edc"] |
| 21 | G5a focus after the retry | pass | focus=button[explain-toggle:a38edc40]:Hide access explanation |
| 22 | G5b list refreshed (announced) but the explanation says it could not load, with Retry, and shows no source or Refresh button from before | pass | Hide access explanation \| Why Phase13E Dev Player A can see this \| \| The access explanation could not be loaded. Retry |
| 23 | G5b Retry re-reads only the explanation (no list request) | pass | ["GET explain:a38edc"] |
| 24 | G6 explanation shows the revelation sources and the existing denial line, no new wording | pass | Hide access explanation \| Why Phase13E Dev Player A can see this \| View Campaign \| Role: Player \| Discover Character \| Revelation: Member (Phase13C Character B) \| V |
| 25 | G3 the removed member's card and explanation are gone; no trace of them in the page | pass |  |
| 26 | G3 fallback focus is the status line (the member's own toggle no longer exists) | pass | p[status-line]:Access list refreshed. |
| 27 | G3 the other member's open explanation survived and was re-read | pass |  |
| 28 | G7 setup: GM2's Campaign Owner role revoked by the admin | pass | status 200 |
| 29 | G7 authority lost: the refresh shows the unavailable page and no member, revelation or explanation content | pass | Access unavailable |
| 30 | G7 after the 403 only the refresh's list read was made; no explanation request followed | pass | GET overview |

30 of 30 checks passed.

## 4. Findings

**C01-B1 / O-5 — an Access mutation reloads the session, which remounts the Access page (inherited; not caused by S02; found in the real browser).** Removing character access through the existing control (`useRevokeCharacterRelationship`) calls the session `reload()` after the revoke succeeds, as the other Access mutation hooks do. `useSessionBootstrap.reload()` sets the session to `loading`, and `AuthenticatedSessionBoundary` replaces every protected child with "Loading portal". The Access page unmounts and mounts again, so (a) every open card and explanation starts closed, and (b) the page's persistent status-line announcement (`Character access removed.`) is lost before it can be observed. Observed (S02 check G1-obs): after the revoke, `aria-expanded="false"`, announcement `""`, focus on the page body. The files involved are unchanged since `cdfdf21` (`git diff cdfdf21 HEAD` over the hook, `useSessionBootstrap.ts`, `AuthenticatedSessionBoundary.tsx` and `layouts/` is empty), so this predates S02; before S02 explanations also closed on every reload.
  - **What it does to S02's statements.** The S02 plan (§2.3, E5) and its jsdom integration test state that an open explanation survives a reload caused by a mutation and that the mutation's announcement is observable. The jsdom test supplies a session whose `reload` does nothing, so it cannot see this. The behavior S02 delivers does hold for **Refresh access** and for **Try again** after a failed list read (G2, G4, G5a, G5b, G3 below), which use the overview boundary's retry and never reload the session. The documentation this slice added (ACCESS_CONTROL §3q, portal-behavior §8.3) is corrected in the same commit to say so.
  - **Severity (grading.md):** Low. Exposure 1 (an access manager after any Access mutation), impact 1 (an explanation must be reopened; a polite announcement is not spoken, which is also an existing accessibility gap), triggerability 1 (every such mutation), detection 0 (visible, recoverable by reopening), blast radius 0. Score 3.
  - **Disposition:** not fixed here. A fix is a design choice that touches authority handling for about twenty mutation hooks: replace `reload()` with the in-place `refresh()` the session hook already provides for "after a mutation changes bootstrap-visible state", or hold the Access page's disclosure and announcement above `AuthenticatedSessionBoundary`. Either needs an owner decision and its own review, and belongs with O-3 (focus after reload). Recorded as inherited observation O-5 next to O-1 to O-4; it does not block C01's read-only explanation and refresh behavior, which the run confirms.

**Observations that are not findings.**

- **A non-member** (Campaign B member) opening a Campaign A character URL sees "Campaign not found" and the portal makes no character request; a direct API read returns the non-disclosing 404, not 403. (S01 §8.1 expected "403"; the shipped contract is the non-disclosing not-found.)
- **Dev server versus production build:** the dev server (React StrictMode) sends each read twice; the production build once. The checks above were taken on the production build.
- **320 px reflow of the Access page:** `scrollWidth` 321 against `clientWidth` 320 (one CSS pixel). Nothing is wider than its card and no content is clipped (screenshot `ax-access-320.png`); recorded, not treated as a defect.
- **Focus after Refresh access** was restored to the member's toggle in the no-intervening-move case, and was **not** moved when the manager had tabbed to another control while the read was pending (G4). The fallback to the status line when the member disappears was observed (G3). Focus after a mutation reload is the page body (O-3, unchanged).

## 5. Harness notes (first failures and reruns, separate)

- Dev-server run first: two identical character GETs per hard load (StrictMode), so the network assertion was moved to a production build; the page-level text scan first matched "Hit points" in the right-hand context panel, which legitimately shows the viewer's own selected perspective (Character A); the assertions were scoped to the character section and to Character B's live markers.
- First S01 run: the whole-character and `view_public_profile` denies could not be created over HTTP (404 `not_found`, because those capabilities are not grantable per character); they were written as fixture rows as described in §1. The unavailable-page heading focus is a link-arrival behavior (`ArrivalHeadingFocus`; a reload moves nothing), so it was checked by following the in-page "Details" link, not on a hard load.
- First S02 runs: a stale fixture id after a reset and a revelation-list key mistake in the harness (not product behavior); a strict-mode locator matched two capability lines; the member card's closed `<details>` made `innerText` empty (`textContent` used); a focus check used an id from the previous database. A truncated pipeline once cut the fixture setup short and the Character A revelation was missing for one pass. The database was rebuilt and S01, the accessibility run and S02 were run again in full in that order; those are the recorded results. No product defect was behind any of these.
- Sign-in throttle (10 per 15 minutes per account) was not reached: each persona signs in once per database build.

## 6. What is not covered (remains pending)

- **Assistive technology.** No screen reader (NVDA, JAWS, VoiceOver, TalkBack) was run. Heading order, regions, `aria-expanded`, `role="status"` and the live-region text were checked in Chrome's accessibility tree and DOM; whether a screen reader speaks the announcements is **not established**. This keeps the [ax](work-register.md#ax) obligation open.
- **A human run.** No person drove the pages; the run is scripted. Human review of focus visibility, wording and layout is not claimed.
- **Zoom** was checked as equivalent viewport widths (640 px for 200%, 320 px for 400%) and not with browser zoom; **other browsers** (Firefox, Safari) were not run.
- **Integrated head.** The register's `browser` and `ax` obligations are owned at the integrated P15 head; this record is at the C01 head. Owner acceptance ([actor-a](work-register.md#actor-a)), the corrected Sella persona run, and D/P15-C02 are outside it. A5c and P15-C02 were not started.
