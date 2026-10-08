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
| 10 | Session run page: start, participants, log, end, Travel, Award an item, Encounters | `…/sessions/:id/run` | | | | | | | | |
| 11 | Events: record and correct | `…/events/new`, `…/events/:id` | | | | | | | | |
| 12 | Quest editor and quest progress | `…/quests/new`, `…/quests/:id/edit`, `…/quests/:id/progress` | | | | | | | | |
| 13 | Knowledge editor and Who knows this | `…/knowledge/new`, `…/knowledge/:id/edit`, `…/knowledge/:id/audience` | | | | | | | | |
| 14 | Dungeon, areas, connections, features, hazards, interactables | `…/world/dungeon/new`, `…/dungeon/:id/edit`, `…/areas/:id/edit` | | | | | | | | |
| 15 | Relationships panel and editor | the Relationships panel on location, organization, religion and character pages | | | | | | | | |
| 16 | Organization members and offices | `…/world/organization/:id` | | | | | | | | |
| 17 | Item definitions | `…/item-definitions`, `…/new`, `…/:id` | | | | | | | | |
| 18 | Items and the Run this item panel; inventories | `…/items`, `…/items/new`, `…/items/:id/edit`, an item's World page, a character's Inventory, a party's Party inventory | | | | | | | | |
| 19 | Prepare and operate an encounter | `…/sessions/:id/encounters/new`, `…/encounters/:id` | | | | | | | | |
| 20 | Sources section and provenance | a record's Sources section, `…/world/:category/:id/provenance` | | | | | | | | |
| 21 | Review queue | `…/review` | | | | | | | | |
| 22 | Revision history and comparison (check the table at 2560 px and at 390 px, and with a screen reader) | `…/world/:category/:id/history` | | | | | | | | |
| 23 | Lifecycle panel (submit, approve, publish, supersede, archive, confirmation dialogs) | on any record | | | | | | | | |
| 24 | Sidebar and navigation, including the capability-gated links (Review, Items, Item definitions) for a GM and for a player | every page | | | | | | | | |

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
