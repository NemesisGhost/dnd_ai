# Phase 15 Manual Acceptance

This is the manual acceptance matrix for Phase 15 (checkpoint 15.4, plan item 20). **It is blank on purpose: every result below must be recorded by the owner (or a person the owner names) using a real browser and assistive technology.** Automated tests cannot stand in for it. The implementation notes in [PHASE15_VERIFICATION.md](PHASE15_VERIFICATION.md) list, checkpoint by checkpoint, what each page needs checked; this file turns those into one pass.

**Phase 15 is not complete until this matrix is filled in, each failure is fixed or accepted by the owner in writing, and a CI run on the final head is green.**

## Setup (use a throwaway database and your own ports)

Do not use the running development servers or database.

1. Create a throwaway database (for example `dnd_ai_acceptance`) on the local PostgreSQL 18 server and set `DATABASE_URL` for the shell you start the servers from.
2. Run `uv run alembic -c database/alembic.ini upgrade head` against it. **This applies migration 135, which scrubs old audit and replay text; on a database with no old rows it is harmless, but take a backup first if you point it at anything that matters.**
3. Start the API on port **8001** and the portal dev server on **5174** (not 8000 and 5173).
4. Create an account that can create a world and a campaign through the portal's own screens (a platform administrator, or a user holding the built-in GM role in some campaign — ADR 0018) (no seed script, no SQL), and a second account to be the player. Use the same flow the exit scenario uses: world, campaign, calendar and times, an NPC, a player character, a party, a session, a quest, a knowledge item, a dungeon with two areas, a relationship, a route, an item, an encounter, a source.
5. When you finish, stop both servers and drop the throwaway database.

## What to check on every page below

For each page, at **390 px**, **1280 px** and **2560 px** wide:

- **Layout:** no horizontal page scroll (a table may scroll inside its own box); nothing is cut off or overlaps; the form is usable.
- **Keyboard only:** every control is reachable in a sensible order, has a visible focus ring, and can be operated (including dialogs, comboboxes and the compare form); Escape closes a dialog and focus returns to what opened it.
- **Screen reader (NVDA or Narrator):** the page title and headings are announced; fields have names; errors are announced and linked to their field; the result of a command is announced (the live region); a table or a list reads sensibly.
- **200% zoom:** still usable.
- **Reduced motion:** with the operating system setting on, nothing animates in a way that is distracting.

Record **Pass**, **Fail** (with a note and the issue), or **Accepted** (with the owner's reason) in the three result columns. Leave a cell empty if it was not checked.

## Pages and panels

| # | Page or panel | Route | 390 px | 1280 px | 2560 px | Keyboard | Screen reader | Zoom 200% | Reduced motion | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Calendar creation | `/worlds/:worldId/calendars/new` | | | | | | | | |
| 2 | World times and the clock card | `/app/:campaignId/world-times`, Campaign Home | | | | | | | | |
| 3 | Location create and edit | `/app/:campaignId/world/location/new`, `…/edit` | | | | | | | | |
| 4 | Organization and religion create and edit | `…/world/{organization,religion}/new`, `…/edit` | | | | | | | | |
| 5 | NPC and player-character create and edit | `…/characters/npc/new`, `…/characters/pc/new`, `…/characters/:id/edit` | | | | | | | | |
| 6 | Character builds | `…/characters/:id/builds`, `…/builds/new` | | | | | | | | |
| 7 | NPC portrayal and the Run this NPC panel | `…/characters/:id/portrayal`, a character's World page | | | | | | | | |
| 8 | Parties and party members | `…/parties`, `…/parties/:id`, `…/parties/:id/edit` | | | | | | | | |
| 9 | Session create and edit | `…/sessions/new`, `…/sessions/:id` (edit in place) | | | | | | | | |
| 10 | Session run page: stages (Prepare, Run session, Wrap up), participants, encounter preparation, log, travel, award item, encounters, review, start/end, in-world time bar | `…/sessions/:id/run[?section=…]` | | | | | | | | |
| 11 | Events: record and correct | `…/events/new`, `…/events/:id` | | | | | | | | |
| 12 | Quest editor and quest progress | `…/quests/new`, `…/quests/:id/edit`, `…/quests/:id/progress` | | | | | | | | |
| 13 | Knowledge claim page (claim, About, canonical information, character knowledge, Who knows this roster) and the New claim form | `…/knowledge/new`, `…/knowledge/:id` (`/edit` and `/audience` redirect here) | | | | | | | | |
| 14 | Dungeon, areas, connections, features, hazards, interactables | `…/world/dungeon/new`, `…/dungeon/:id/edit`, `…/areas/:id/edit` | | | | | | | | |
| 15 | Relationships panel and editor | the Relationships panel on location, organization, religion and character pages | | | | | | | | |
| 16 | Organization members and offices | `…/world/organization/:id` | | | | | | | | |
| 17 | Item definitions | `…/item-definitions`, `…/new`, `…/:id` | | | | | | | | |
| 18 | Items and the Run this item panel; inventories | `…/items`, `…/items/new`, `…/items/:id/edit`, an item's World page, a character's Inventory, a party's Party inventory | | | | | | | | |
| 19 | Prepare and operate an encounter (compact participant roster: add, change side with Save only when changed, remove; no initiative) | `…/sessions/:id/encounters/new`, `…/encounters/:id` | | | | | | | | |
| 20 | Sources section and provenance | a record's Sources section, `…/world/:category/:id/provenance` | | | | | | | | |
| 21 | Review queue | `…/review` | | | | | | | | |
| 22 | Revision history and comparison (check the table at 2560 px and at 390 px, and with a screen reader) | `…/world/:category/:id/history` | | | | | | | | |
| 23 | Lifecycle panel (submit, approve, publish, supersede, archive, confirmation dialogs) | on any record | | | | | | | | |
| 24 | Sidebar and navigation, including the capability-gated links (Review, Items, Item definitions) for a GM and for a player | every page | | | | | | | | |

### Row 10 detail: the staged Run Session page

Check at 390, 1280 and 2560 px, with the keyboard only, at 200% zoom, and with a screen reader. Use one scheduled, one in-progress and one completed session.

1. The session list's "Run …" link opens Prepare › Participants for a scheduled session, Run session › Session log for one in progress, and Wrap up › Session review for a completed or archived one.
2. The breadcrumb reads "Sessions › [title] › Run session": Sessions opens the list, the title opens the session page, "Run session" is not a link. The campaign context panel (world, timeline, campaign, perspective) is the same before and after.
3. Choosing each stage never starts, ends or changes the session (no POST in the network tab). The section menu lists only the current stage's sections, and exactly one section is shown, with a heading, a purpose line and a visible border.
4. Type a log entry and GM notes, switch to Prepare and back: the text is still there. The same for the Travel and Award choices, the Add-participant choice and a half-entered Advance time. Back and Forward move between visited sections without losing it; reloading `?section=travel` reopens Travel; `?section=bogus` opens the default with no extra Back step.
5. Participants: add with each role (Player character, NPC, Guest); remove one and see them under "Left". Encounter preparation: prepare an encounter, return with "Run the session", start it, return again and find it under Run session › Encounters.
6. Travel: individual travelers versus a whole party, with the optional route. Award item: only eligible items; recipients are present participants. Session log: the two audience hints read "Visible to everyone in the campaign." and "Visible only to people who can edit canon."; the optional "When" and "Record a new time" work.
7. The "Campaign time (in-world)" bar shows in every stage; Advance/Correct appear only in Run session, and the correction confirmation works. Real-world times are labelled "Real-world start/end".
8. Start session appears only at the top of Run session for a scheduled session and needs its button. End session (Wrap up) opens a confirmation (recap, "Ends at"); Cancel leaves the session in progress; confirming completes it and every section then explains why it is read-only.
9. Session review shows the overview, participants, log and encounters; each "go to" link opens the right section, or a reason is shown instead.
10. A member without `canon.edit` sees the "no permission" message and none of the stage controls.

### Row 13 detail: the Knowledge claim page

Check at 390, 1280 and 2560 px, keyboard only, and with a screen reader, as a GM, as a player with a selected character, and as a member with `campaign.view` only.

1. Knowledge cards: the claim text leads, the kind is a quiet label, a labelled About area names the subject and type, and the card and its subject open separately (Tab reaches each). The grid never squeezes cards narrower than readable; search, view, party/character selection, public filter and Load more still work.
2. A card opens the claim page with the same character and party. The header shows the breadcrumb (Knowledge › Claim, the Knowledge crumb keeping the perspective), the claim as the heading, the About this World entry block and the real status badge. Under it, as a GM, the stages 1. Prepare, 2. Review & publish and 3. Use in play, with the section menu of the current stage; the stage links never show a status.
3. Navigation: every stage and section link (and the header Next link) only changes the address: nothing is saved, no status changes, no draft is discarded. Back and Forward walk the sections; `character_id` and `party_id` survive every link; one section is visible at a time and focus moves to its heading; each stage reopens on the section last used.
4. GM, draft: fields are controls at once. Change the claim: "Unsaved changes" appears and Save claim enables; Discard restores it; Save stays on the page and "Claim saved" appears only after the save succeeds. A published claim asks for confirmation first. After someone knows the claim, claim, kind and subject are disabled with the reason.
5. Sources: the copy says they are optional, can change at any status and do not affect review or publication. Write and attach a source with the network panel open: two requests with two different `Idempotency-Key` values (`<key>.create`, `<key>.attach`), both accepted. (Reproduced before the fix: with one key for both, the attach is refused with 409.) View provenance returns to the Sources section with the perspective. A typed source blocks leaving the page with the "Discard unsaved changes?" dialog.
6. Review and publication: submit a draft for review (with an unsaved claim edit it asks first and the edit stays, shown as "Unsaved changes not applied" with Discard); in Review claim read the summary and Approve; in Publication publish. An approved claim whose subject is unpublished says "Publish its subject first" in the header and Publication, links to the subject and offers only Return to draft (under More). The copy never says publishing tells anyone and never asks for a source.
7. Who knows this: the three groups stay separate; each action is beside its heading and opens a compact form; Details expands a knower inline. Tell a party, record that someone learned it or told another, make it public, change a belief: each succeeds on its own, closes its form, and never touches an unsaved claim edit. A refused action keeps the form and shows its error under that group. With every active party told, "Every active party already knows this" replaces the button.
8. Restrictions: for a draft, in review, approved or rejected claim one note names the status and the real next step, no action button is offered and recorded rows stay readable. An archived claim says what was recorded is kept and nothing new can be recorded until it is restored (Restore is the primary button in Publication and asks for a reason); a superseded claim links to its replacement and says to record knowledge there; belief details of both are text only.
9. Exceptional states: rejected (Return to draft is offered directly and makes the claim editable again), deprecated (no step offered, no Next link), archived (Archived badge beside Canon), superseded (Replaced by banner).
10. Player or reader: the same values as text, no stages, no Save/Discard, no Who knows this, no status badge, and canonical truth and sensitivity absent unless the server returned them. A `?section=` in the address is ignored. A member with only a targeted `canon.edit` allow on the claim sees the same read-only page. With no character selected, Character knowledge is one message asking for a perspective.
11. Widths: 360, 768, 1280 and 1920 px have no horizontal page scroll, the stage links wrap and the section menu is a left column from 64rem and a wrapping row below it. Closing the tab with an unsaved draft shows the browser's own prompt.
12. Old addresses `…/knowledge/:id/edit` and `…/knowledge/:id/audience` land on `?section=claim` and `?section=who-knows` with character and party unchanged; `#claim` and `#who-knows` map to the same sections.

### Knowledge Member preview

Check at 360, 768, 1280 and 1920 px, keyboard only, and with a screen reader, as a GM or owner (`access.manage`) and as a player.

1. Sidebar: for the GM, Knowledge expands into Claims and Member preview (the group opens on a Knowledge route; the active child is marked); for a player it is the plain Knowledge link with no Member preview. The normal Knowledge collection and claim pages have no "Preview as member" control.
2. Member preview before a choice: only the "Choose a member to preview" state and the member list (open, active members); no Knowledge is shown and no Knowledge request is made.
3. Choose a member: the bordered banner reads "Previewing as [member] ([roles])", says read-only and separates member access from fictional character and party knowledge; the URL holds `?member=`. Only that member's own characters are offered, and a party only for a character that may use it. The collection lists only what that member would see (compare it with the GM's own Knowledge page: drafts and unpublished claims are absent for a player).
4. Open a claim from the preview: it stays in the preview (breadcrumb Knowledge › Member preview › Claim, the same banner), shows the member's projection as text (no truth or sensitivity unless the member's own request would include them), has no edit, source, lifecycle or knowledge-management control, and the subject is not a link. With a party selected the knowledge section is headed "Party knowledge: [party]"; with only a character it is "Character knowledge: [character]"; when the projection includes no awareness, confidence or sharing details it says so neutrally rather than claiming no knowledge is recorded. Back returns to the same filters, page and perspective.
5. Invalid or stale selections: an unknown member, a character the member does not have, or a party without a usable character each give a clear error and no Knowledge request; changing the member clears the previous member's claims immediately; reload reproduces the same preview from the address.
6. Return to Knowledge (banner link or Claims) lands on the ordinary collection with no member, perspective or filter from the preview; the GM's own Knowledge page is unchanged.
7. A player who types the preview address is told they may not preview, and no preview or member-list request is made.
8. Keyboard: the sidebar group, the child links, every selector and the cards are reachable and operable; focus is visible; no horizontal page scroll at 360 px.

## Carried items from earlier phases

| Item | Result | Notes |
|---|---|---|
| Phase 14: sidebar and hierarchy correction (navigation between worlds, timelines, campaigns) | | |
| Phase 15.1: the typed authoring forms' unsaved-change guard, server-code to field-error mapping, `no-store` reads after a back navigation | | |
| Player account: every GM page above is absent from the navigation and a typed URL shows "no permission" or "not found", never a partial page | | |

## Summary (fill in last)

| | |
|---|---|
| Date and tester | |
| Browser and version; screen reader and version | |
| Failures found | |
| Failures fixed (commit) | |
| Failures accepted by the owner (reason) | |
| CI run on the final head (link) | |
| Owner's decision: Phase 15 accepted as complete | |
