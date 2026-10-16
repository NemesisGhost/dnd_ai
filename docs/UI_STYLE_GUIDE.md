# D&D AI Portal UI Style Guide

**Status:** Phase 13 design standard  
**Applies to:** `portal/`  
**Primary references:** the portal's existing themed application shell, the established campaign context panel and InfoBox patterns, and the information hierarchy of a traditional tabletop character sheet  

## 1. Purpose

This guide defines a shared visual and interaction language for the D&D AI portal. It is intended to make dense campaign information fast to scan without turning the portal into a literal copy of a printed character sheet or another application.

The core presentation model is:

1. **Collections use cards.** World entities, knowledge items, quests, campaigns, and similar browsable records appear as concise, structured cards rather than plain rows or undifferentiated text.
2. **Details use a full-page surface.** Activating a card navigates to an addressable detail route whose content is divided into clear fact groups and panels.
3. **Important numbers use stat cards.** Ability modifiers, hit points, proficiency bonus, movement, spellcasting values, and similar high-value facts receive stronger visual hierarchy than descriptive metadata.
4. **Related facts stay together.** Each list, table, or fact family has its own bounded panel with a visible heading.
5. **The server remains authoritative.** Visual organization never infers capabilities, hidden records, relationships, truth, or access from client-side labels.

This document supplements `docs/UI_DESIGN.md`. It defines presentation and interaction conventions; `UI_DESIGN.md` remains authoritative for product scope, information architecture, authorization boundaries, and feature behavior.

## 2. Design principles

### 2.1 Dense, not cluttered

The portal contains more structured information than a conventional consumer site. Density is useful when hierarchy remains clear.

- Prefer compact cards and panels over excessive whitespace.
- Use alignment, grouping, headings, and type weight before adding decoration.
- Keep labels short and values easy to compare.
- Avoid rendering every field as an equally prominent tile.
- Do not hide essential information behind hover.

### 2.2 Familiar tabletop hierarchy

The portal may borrow organizational ideas from tabletop character sheets:

- high-value numbers receive prominent treatment;
- related facts appear inside bounded sections;
- repeated mechanical values align consistently;
- long narrative content receives its own wider panel;
- dense data reflows for the web instead of retaining a fixed paper layout.

Do not reproduce proprietary logos, ornamental borders, artwork, or exact trade dress. The reference is informational hierarchy, not visual duplication.

### 2.3 Progressive detail

A collection card answers:

- What is this?
- What type or state is it?
- Why might I open it?
- What small amount of authorized context is useful before opening it?

A detail page answers the fuller set of authorized questions. Collection cards must not become miniature detail pages.

### 2.4 Perspective-safe by construction

Every displayed value comes from an audience-safe server response for the current campaign, timeline, user, and optional character perspective.

- Do not infer authorization from role display strings.
- Do not infer knowledge truth from sensitivity or status labels.
- Do not expose hidden counts, IDs, empty hidden sections, or inaccessible relationships.
- Changing campaign, timeline, or character perspective must obtain fresh authorized data.
- A card must not preload a detail record the viewer may not open.

### 2.5 Route-based detail expansion

When a card is described as “expanding,” it should visually become a full detail surface through navigation to a detail route. It should not merely enlarge in place using cached collection data.

Route-based details provide:

- bookmarkable URLs;
- correct browser Back and Forward behavior;
- reliable refresh behavior;
- a fresh server authorization check;
- direct loading, unavailable, and recoverable-error states;
- room for responsive, full-detail content.

An optional view transition may later make the card appear to expand into the detail page, but the route and authorization model must work without animation.

## 3. Existing theme system

All new surfaces must use the existing semantic variables from `portal/src/index.css`.

### 3.1 Required tokens

| Purpose | Token |
|---|---|
| Page background | `--color-background` |
| Card and panel surface | `--color-surface` |
| Section heading and inset surface | `--color-surface-muted` |
| Interactive hover surface | `--color-surface-hover` |
| Primary text | `--color-text` |
| Secondary text | `--color-text-muted` |
| Structural border | `--color-border` |
| Primary action/link | `--color-primary` |
| Primary hover | `--color-primary-hover` |
| Focus indicator | `--color-focus` |
| Low-frequency accent | `--color-accent` |
| Danger and warning states | Existing semantic danger/warning tokens |
| HP meter | Existing hit-point meter tokens |

### 3.2 Color rules

- Do not add hard-coded light or dark colors to a page component.
- Do not give every card category a different color.
- Use the primary color for links and active/selected states.
- Use the accent color sparingly for small decorative or categorical emphasis.
- Use danger and warning tokens only for meaningful state, not decoration.
- Never communicate status, proficiency, confidence, or selection using color alone.
- Verify every supported theme rather than creating one-off dark-mode overrides.

### 3.3 Surface hierarchy

Use three surface levels:

1. Page: `--color-background`
2. Card/panel: `--color-surface`
3. Panel heading, inset fact, or secondary region: `--color-surface-muted`

Hoverable cards may use `--color-surface-hover`. Avoid stacking multiple bordered cards inside one another. A detail page may contain panels, but a panel should not contain another full panel unless the nested element is a distinct, necessary subrecord such as a spellcasting profile. Which contract supplies the surface, who owns the spacing, and when a page may differ are defined in §6.7.

## 4. Typography and spacing

### 4.1 Type hierarchy

| Element | Treatment |
|---|---|
| Page title | One `h1`, normal portal heading style |
| Major detail panel | `h2` |
| Repeated subrecord | `h3` |
| Card title | Heading appropriate to its surrounding structure, usually `h2` or `h3` |
| Eyebrow/category | Small, muted, optionally uppercase |
| Primary stat | Largest value within its local card |
| Field label | Muted and concise |
| Supporting metadata | Muted, never smaller than readable body text requirements |

Do not create headings solely to make text larger. Preserve a logical heading outline independent of visual styling. Level follows the outline and size follows the contract, so peer headings always match: a panel heading is 1.125rem, a plain-section or workspace-section heading 1.25rem, a subgroup `h3` 1rem.

### 4.2 Spacing scale

Prefer the existing spacing rhythm:

- `0.25rem`: inline separation
- `0.5rem`: compact row gap
- `0.75rem`: card interior gap
- `1rem`: normal panel padding and grid gap
- `1.5rem`: separation between major groups
- `2rem`: major page-section separation

New components should draw from this scale rather than introducing isolated values.

### 4.3 Borders, radius, and shadow

- Cards and panels use a single `1px` `--color-border` boundary.
- Use the portal's existing modest border radius, normally about `0.375rem` to `0.625rem`.
- Shadows are optional and subtle. Borders and background changes should carry most of the hierarchy.
- Do not recreate the heavy ornamental framing of a paper character sheet.
- Interactive cards may gain a small shadow or background change on hover, but must not jump position.

## 5. Responsive layout

### 5.1 Collection grid

Card collections use a responsive grid rather than fixed breakpoint-specific column counts:

```css
grid-template-columns:
  repeat(auto-fit, minmax(min(100%, 18rem), 1fr));
```

Use a larger minimum, such as `20rem` or `22rem`, when a card contains several metadata rows. Every collection must become one column without horizontal overflow on a 320-pixel viewport.

### 5.2 Detail grid

Full detail pages use independently reflowing panels:

```css
grid-template-columns:
  repeat(auto-fit, minmax(min(100%, 20rem), 1fr));
```

Important narrative panels may span available columns. Do not depend on a specific panel always being “left,” “center,” or “right”; source order must remain meaningful when the layout becomes one column.

### 5.3 Stat grids

Compact peer statistics may use smaller minimum widths:

```css
grid-template-columns:
  repeat(auto-fit, minmax(min(100%, 8rem), 1fr));
```

Examples include ability scores, movement modes, spellcasting values, and a short campaign summary.

### 5.4 Tables

Use tables only for genuinely tabular comparisons. Wrap unavoidable wide tables in a local horizontal-scroll container. A page must never gain horizontal scrolling because of a table. The `TableScroll` region (`.table-scroll`) is that container: it is named like the table's caption and keyboard-focusable, `SortableTable` supplies it itself, and any other table is wrapped explicitly. `.authoring-table-scroll`, `.character-sheet__table-scroll` and the audit table wrapper are older names for the same behaviour.

On narrow screens, consider a list or card presentation when column relationships remain understandable without a table.

## 6. Shared presentation primitives

The implementation may choose final component names, but it should converge on the following small set of responsibilities.

### 6.1 `CardGrid`

Responsibilities:

- responsive layout of peer collection cards;
- consistent gap;
- no domain-specific mapping;
- semantic list structure when it represents a list.

### 6.2 `EntityCard`

Responsibilities:

- card surface and interactive states;
- category/eyebrow;
- title;
- optional short summary;
- compact authorized metadata;
- optional status;
- clear navigation affordance.

The entire card may be activated through one primary link. Do not place nested links or buttons inside a fully clickable card. If secondary actions are required later, restrict the primary link to the title/content area and provide a separate action region.

### 6.3 `DetailPanel`

Responsibilities:

- bounded surface;
- visible heading;
- optional short supporting text;
- panel body;
- optional empty state.

It must not know about campaigns, quests, characters, or authorization.

It takes a heading level (`h2` by default, `h3` when nested under a section heading), an optional heading id for hosts that label or focus the heading, and an optional `headerActions` slot beside the heading for at most two compact controls that act on the whole panel. A panel never sets its own outer margin: its container spaces it (§6.7).

### 6.4 `FactGrid`

Responsibilities:

- compact label/value facts;
- semantic `dl`, `dt`, and `dd` output;
- responsive wrapping;
- no empty rows unless “Not recorded” is a meaningful, authorized state.

### 6.5 `StatCard`

Responsibilities:

- one prominent value;
- one visible label;
- optional short secondary value or meter;
- accessible text for symbolic state.

Use only for important, quickly compared values. Do not turn every piece of metadata into a stat card.

### 6.7 Section containment

Five contracts say how a region is contained. Choose by purpose, not by counting neighbouring borders.

| Contract | Use when | Not when | Treatment |
|---|---|---|---|
| **Primary section panel** (`DetailPanel`) | Peer regions of a record page, and a distinct task region on a reading page (Run this item, Lifecycle, Sources, Relationships, Members, Inventory) | Single-column forms or reading flows; around content that already has surfaces (card grids, tables, trees, stage cards) | Surface, 1px border, 0.5rem radius, 1rem padding (0.75rem below 30rem), `h2` 1.125rem |
| **Plain section** (`.page-section`, also `.authoring-section`) | Settings, overview, form and list pages | Peers that reflow side by side | No surface, 1.5rem top margin, `h2` 1.25rem |
| **Inset group** (`.inset-group`) | A subordinate group inside a panel or form | A top-level peer of panels; inside another inset | Muted surface, no border, 0.375rem radius |
| **Workspace section panel** (`SectionPanel`) | The one visible section of a guided workspace (§10a.1) | Anywhere else | Bordered, `h2` 1.25rem, purpose line |
| **Disclosure** (`.disclosure`) | Optional detail of one item (why an action is unavailable, an objective's details) | Essential information or navigation | Native `<details>`, summary text, a text indicator ("Show +" / "Hide −", or "Expand +" / "Collapse −"), visible focus |

**Wrapper ownership.** A container (the reading grid, `.section-stack`, `.world-detail__layout`, a plain section) owns the space between its children. A component that can stand alone owns its surface. A component that is embedded in a host that already supplies the surface, heading and labelled region renders content only (`EntitySourcesSection embedded`), so there is never a panel inside a panel and never a second region with the same name.

**When an exception is justified.** Only when the semantics differ (an `article`, an `h1` header, a mode banner), the surface is itself the interaction (cards, stage cards, dialogs), the workflow documents a different width or density, or the content is structure that borders would obscure (trees, chronology). Say which in a comment beside the CSS. Preserved exceptions: Campaign Home's recent-events list and compact clock, the character sheet header reusing panel CSS for its `h1`, the guided workspace panel, Knowledge details, quest stage cards, the hierarchy context panel, the Member preview banner, and the Get started callout.

### 6.8 Operational rows, chronology and status

- **Operational list** (`.op-list`): records that carry their own commands or links (attached sources, relationships, builds, the review queue). Rows are separated by a rule, not boxed; row buttons are compact and wrap with their row and are never stretched to full width on a phone. Form actions (`.authoring-actions`) stay full width below 40rem.
- **Draft roster** (`.calendar-roster__*`): the rows of an unsaved parent (the months of a calendar being created). It uses the operational-list idiom (ruled rows, compact wrapping row buttons, a header row from 40rem), shows each row's position and its own actions, says in words that Add, Edit and Remove change the draft only, expands one row's editor at a time under that row, and keeps the panel that adds a row above the list, always open and ready for the next row (no open or close button), so nothing large is appended at the bottom.
- **Chronology / summary list** (`.record-list`): provenance, revisions, logs and read-only summaries. A numbered list keeps its numbers.
- **Status strip**: the compact campaign-time bar. **Messages** (`.authoring-message--error` / `--warning`) are for errors and warnings; a success or neutral result uses `.form-status` and is never styled as an error. A one-time secret uses the `OneTimeSecretPanel` panel with a warning rule.

### 6.6 Domain-specific wrappers

Mapping authorized API data into shared primitives remains domain-specific. Examples include:

- `WorldEntityCard`
- `KnowledgeItemCard`
- `QuestCard`
- `AbilityScoreCard`
- `SpellcastingProfilePanel`

These wrappers may select fields and format labels, but they must not grant access or infer hidden data.

## 7. Collection-card anatomy

A standard collection card contains, in order:

1. Category or type label
2. Record title
3. Short summary, when available
4. Two to four compact metadata facts
5. Status, when meaningful and authorized
6. A visible detail affordance supplied by the link semantics and styling

### 7.1 Card behavior

- Use a real link for navigation.
- The link must have a descriptive accessible name.
- Hover and focus use the same visual emphasis.
- Preserve the browser focus outline or provide an equally visible token-based outline.
- Do not animate size changes in the collection grid.
- Do not issue a detail request merely because the user hovered over a card.
- Do not render raw UUIDs.
- Truncate only optional previews; the full authorized value belongs on the detail page.

### 7.2 Card density

A collection card should normally fit within roughly five to ten lines of content. If it needs multiple tables, long descriptions, or nested collections, that content belongs on the detail page.

## 8. Full-detail page anatomy

A detail page visually continues the selected card while becoming an independent route and data request.

Recommended order:

1. Back/breadcrumb navigation to the authorized collection
2. Record title and category
3. Short authorized summary or description
4. Primary facts or stat cards
5. Responsive detail-panel grid
6. Related authorized records
7. Provenance/source information, when the current audience may see it

### 8.1 Detail navigation

- Refreshing a detail URL must reload safely.
- Browser Back returns to the collection and should preserve URL-backed search/filter state where practical.
- A missing, inaccessible, or cross-campaign ID uses the same non-disclosing unavailable state.
- Do not distinguish nonexistent from unauthorized records in user-facing output.
- Do not display the prior record while a new route's detail request is loading.
- Sidebar selection follows the address alone. A record reachable from two collections has one address per origin (an item at `/items/:id` and `/world/item/:id`), each selecting its own group; router state may restore a collection's query but never selects navigation.

### 8.2 Visual expansion

The detail page may share card colors, category labels, title treatment, and status placement so it feels as though the card expanded. Do not make functional correctness depend on animation or the View Transitions API.

## 9. Character sheet standard

The character sheet is the densest example of this visual language.

### 9.1 Header

Display:

- character name;
- species and size;
- classes, levels, and subclasses;
- build label;
- ruleset and ruleset version.

### 9.2 Primary stats

Display important current or derived values as stat cards:

- proficiency bonus;
- movement;
- current/maximum hit points using the established HP meter;
- temporary hit points when present;
- spell save DC and attack bonus inside the relevant spellcasting profile.

Do not invent armor class, initiative, hit dice, equipment, attacks, background, alignment, or personality fields until authoritative contracts exist.

### 9.3 Ability cards

Each ability receives one domain-specific card containing:

- ability name;
- prominent modifier;
- smaller underlying score;
- saving-throw modifier;
- explicit proficient/not-proficient state.

Save proficiency must not rely on color alone. If no matching saving throw exists, show a neutral “Not recorded” state rather than calculating or inventing one.

### 9.4 Character panels

Use separate panels for:

- skills;
- other proficiencies;
- languages;
- senses;
- current conditions;
- resources;
- features and traits;
- each spellcasting profile.

Skills may use a compact aligned list rather than several duplicated tables. Spell lists group spells by level and omit empty levels. Known and prepared states must have visible text or accessible labels.

## 10. World Explorer standard

### 10.1 Collection cards

Current list contracts provide:

- category;
- entity type code;
- name;
- optional summary.

World cards should therefore show only:

- human-readable category/type;
- name;
- summary when present.

Do not infer location hierarchy, relationships, population, organization membership, or visibility from identifiers or category codes.

### 10.2 Detail readiness

World cards become full detail links only when an authoritative audience-safe detail endpoint and route exist for the category. Until then, use non-interactive cards or the currently supported behavior. Do not construct a detail page solely from cached list data.

Future world detail panels may include, when supplied and authorized:

- overview;
- location and containment;
- current state;
- relationships;
- associated organizations or people;
- known history;
- related knowledge and quests;
- source/provenance.

Different categories may omit irrelevant panels. Empty omitted panels must not imply hidden information exists.

## 10a. Authoring forms, dialogs, and badges (Phase 14)

Shared primitives live in `portal/src/components/authoring/` and are styled by `authoring.css` using the existing theme tokens only (`--color-danger`, `--color-warning-*`, `--color-focus`, …).

- **Fields.** Label above the control, optional hint under the label, error under the control as plain words prefixed for screen readers ("Error: …"), never color alone. An invalid control gets a heavier border *and* the text. The character counter is a polite status shown only near the limit.
- **Buttons.** Save/confirm is the primary (or danger) button; Cancel is the plain button; both are full width below 40rem. A pending Save is disabled, `aria-busy`, and relabelled ("Saving…").
- **Error summary.** One focusable alert box above the form with a heading and a list of links to the failing fields; it takes focus on each failed submit.
- **Messages.** Error and warning boxes pair an icon with text; a stale-write warning carries the "Load latest version" action and a read-only copy of the user's unsaved values.
- **Dialog.** Native `<dialog>` with a backdrop from `--color-overlay`, max width 32rem, focus trap and Escape from the platform, initial focus on Cancel.
- **Lifecycle badge.** A rounded pill with a decorative icon and a text label (Draft, In review, Approved, Canon, Superseded, Rejected, Archived). The label is the meaning; the icon and tint are decoration.
- **Visually hidden text** uses the `.visually-hidden` utility (clipped, not `display: none`) so it is still read by assistive technology.
- **Lifecycle status and actions (one rule, every page).** A lifecycle panel shows the status (badge and words), then a compact action group: the next forward step as the primary button (Restore, or Return to draft for a rejected record, when that is the way forward) and every other action the server offers under **More**; the confirmations, reasons, supersede candidates and stale-write recovery do not change. Blocked actions are explained from the server's `blocked_actions` without discarding any: a reason a person can act on (a parent that is not published, a review in progress, and any reason the portal does not recognise) is shown next to the actions, and the reasons that only restate the status (wrong canon status, archived, not archived) sit under a collapsed **Why other actions are unavailable (N)** disclosure whose count is exactly the list inside. A page that already explains a blocker in its own words may suppress the inline copy, never the disclosure. Grouping is presentation only; it infers no eligibility.

### 10a.1 Guided workspace pages

A record whose editors do several **meaningful working phases** on one page uses a **guided workspace**: an always-visible header with the record's real status, a numbered **workflow phase** row, a **local section menu** for the current phase, and one visible section at a time. This is the rule for every such record; it is not a style choice per page. The Run Session page, the Knowledge claim page, the item workspace, the World record workspace and the Quest workspace follow it.

**What qualifies as a working phase.** A phase qualifies when all three hold: it is a distinct job with its own commands or decisions (authoring the definition, deciding publication, recording what happens in play or at the table); the server's state decides when its commands apply, so a phase that does not apply yet explains itself instead of disappearing; and a person comes back to it repeatedly and out of order. A record gets a guided workspace when it has **at least two** such phases (for example Prepare plus Review & publish, or Prepare plus Run). Having many panels, or a long page, does not qualify a record.

**When something lighter is enough.**

| Use | When |
|---|---|
| Plain sections (`.page-section`, `DetailPanel`, §6.7) | One job with several regions: reading pages, settings, lists, one form plus its history, and a record with its own exclusive status machine whose page shows only what that status allows (an event, an encounter) |
| A disclosure (§6.7) | Optional detail of one item |
| A wizard step row (`.authoring-step-nav`) | A linear creation flow in which every step commits and the next depends on it (campaign setup) |
| Local creation steps | Creating one record whose parts are best entered in separate views, with nothing committed until one final action (New calendar). Described below |
| Tabs (ARIA `tablist`) | Never for workflow phases. Reserved for switching views of the same data without changing the address; none exist today |

Non-linear workflows stay non-linear. Phases are numbered for orientation and every one stays reachable; a phase never gates another. Only the server's eligibility does, and it is explained in the section.

**Local creation steps.** A record that does not exist yet can still be entered in several views. Its steps reuse the workflow navigation (`useStagedNavigation`, `StageNav`, `SectionPanel`) with these differences: there is no record header and no status, because nothing exists on the server; the steps never send a request, so there is exactly one write, the single action on the last step ("Create calendar", on **Review & create**); the step row is labelled "New <record> workflow" and its labels are named for the work (Basics, Months, Review & create), which says plainly that Review & create is the person's own check and not the Review queue. The draft lives in one reducer above the panels, so every value and every unfinished sub-form survives any step change; unfinished sub-forms are never dropped silently (creation is refused and the form is named); the whole draft is validated whichever step shows it; an error link shows the step and opens the row before it focuses the field (`ErrorSummary onFollow`); Enter in a step's fields must not submit, so only the last step contains the creating form; and a change to what would be sent withdraws a failed attempt's Retry. Arrival uses `usePageArrival(…, "path")`, so a step change moves focus to the step's heading and not the page heading. Entered values are never written to browser storage.

**Naming.** Phases are named for the work, not for a state: Prepare, Review & publish, Use in play, Run session, Wrap up. They avoid verbs of lifecycle change (start, end, publish now). The phase row is labelled "<Record> workflow" (`"Quest workflow"`), and the words "stage" and "phase" never appear in a phase label. A domain term is never reused for navigation: a quest **stage** is part of the authored adventure, an encounter **round** and a session **status** belong to their records. Documentation says "workflow phase" in full. (The older pages' accessible labels, "Session stages", "Claim stages", "Item stages" and "Record stages", and the shared component names `StageNav` and `useStagedNavigation` predate this rule and are renamed when each is next changed.)

**Status and eligibility.** The header shows the record's real status from the server's lifecycle read, never from the phase, and shows none while it is unknown. Phases never imply, cause or block a lifecycle change. A **Next** link is navigation to the section where a step lives, derived only from `available_actions` (or the read model's own explicit flags), never an action. A section whose commands do not apply says why and links to what unlocks it. A failed status read is not eligibility: its commands are withheld.

**Default and direct links.** The current section lives in the address (`?section=…`) and the phase follows from it. With no section the default is where the record's next real step is done, from the lifecycle read: in review or approved, Review; archived or replaced, Publication; published and active, the first Use in play section where the record has one; otherwise the first Prepare section. A missing or unknown value is replaced, not pushed; a person's choice adds a history entry. Every other query parameter and the router state are kept, and each phase reopens on the section last used in it. Old addresses redirect into a section, replacing history and carrying the query and the state.

**Read-only.** People without the authoring capability get the reader: no phases, no authoring request, and a `?section=` in their address is ignored and not rewritten. Inside the workspace, a field the person may not change is text with one line saying why; a section with nothing for this person is left out, never shown disabled.

**Return context.** The header's back link follows where the record was opened from (validated router state: the collection's query, or the Review queue's filters), and that state rides on every phase, section, Next, edit and redirect link. A direct link returns to the plain collection. Sidebar selection never depends on that state.

**Drafts.** Every section stays mounted once shown, so switching never loses input. Saves are independent and report in the section that sent them; a refresh updates in place and never remounts on a row version; one page-level guard names everything unsent, and a query-only change is not leaving. Entered values are never written to browser storage.

**Keyboard and focus.** Phases and sections are links (`aria-current="step"` and `aria-current="page"`), not tabs or buttons, because choosing one changes the address. Arrival focuses the `<h1>`; a section change focuses its `<h2>`. The current item is shown by weight and a heavier border, not colour alone.

**Responsive layout.** The section menu is a left column when the workspace container is at least 48rem wide (a container query, so the sidebar and context panel are accounted for) and a wrapping row above that; a phase with one section has no menu. At 320-390px there is one column, no horizontal page scroll, and full-width form actions, while row buttons stay compact.

**Reuse.** Use `useStagedNavigation`, `StageNav`, `SectionNav`, `SectionPanel`, `UnsavedInputGuard` and the lifecycle parts (`LifecycleActionsProvider` with the Review and Publication sections), with the record header pattern (`.item-header`). Do not build another navigation component.

**Parts of the page.**

- **Page breadcrumb.** `<nav aria-label="Breadcrumb">` with an ordered list: parent list, the record (by its title, never an identifier), and the current page (`aria-current="page"`, not a link). A workspace may use a single "Back to …" link above the header instead. It is separate from the campaign context panel (world, timeline, campaign, perspective).
- **Phase navigation.** A numbered row of links, wrapping at narrow widths. The current phase is marked by weight and a heavier border, not colour alone.
- **Section menu.** Links for the current phase's sections only (`aria-label="<Phase> sections"`).
- **Section panel.** One panel visible at a time: a bordered surface with an `h2`, a one-line purpose, then the content.
- **Compact time bar.** In-world time is labelled "(in-world)" and real-world timestamps "Real-world …" so the two are never confused.

**Page families against this rule.**

| Family | Verdict |
|---|---|
| Run Session, Knowledge claim, item workspace, World record workspace, Quest workspace | Guided workspaces (this section) |
| Quest reader, Knowledge Member preview, Knowledge and World readers | One job (read); no phases |
| Session detail, encounter, event record | Plain sections; the record's own status decides what its page shows |
| Campaign setup | Wizard step row |
| New calendar | Local creation steps (this section) |
| Lists, Review queue, revision history, Campaign Home, settings, access, parties, party members, world times, worlds, timelines | One job; plain sections |
| Item definitions | Not lifecycle-managed; one form |
| Dungeon and area edit pages; NPC portrayal and character builds | Candidates to fold into the World record workspace's sections later; not part of the Quest work |
| Character sheet tabs (UI_DESIGN §5.5) | Reading views of one character; not a workflow |

## 11. Knowledge standard

### 11.1 Collection cards

Knowledge cards may display authorized fields from the current list contract:

- statement (the card's content and one link);
- knowledge type as a quiet secondary label;
- a labelled "About" area with the subject's name and type, as a separate link;
- awareness level;
- confidence when meaningful to the current audience;
- willingness to share when meaningful to the current audience;
- (scope and canonical truth are not repeated on cards; they live on the claim page).

Cards sit in a grid wide enough (about 28rem) to read a sentence comfortably.

### 11.3 Claim page

One page replaces separate view, edit and "who knows" screens. Its always-visible header holds the breadcrumb, the claim as the page heading, the prominent About block (the World subject), the actual status badge and one Next link. People who can change canon get the Guided workspace under it: **Prepare** (Claim, Sources), **Review & publish** (Review claim, Publication) and **Use in play** (Who knows this, Character knowledge), one section visible at a time (see §10a.1). Fields are controls only for people authorized to change them; others see text, and anything they may not see is absent. Canonical information (the GM's record of truth and sensitivity) is kept visibly apart from character knowledge (awareness, confidence, belief). Character knowledge is one compact **Knowledge details** panel: the claim's kind and what the selected perspective knows, each label above its value, with the origin sentence under the heading. It is a single surface in the theme's surface colour with the standard subtle border (never one card per field); its fields sit in a responsive grid of four columns, then two, then one, and values are larger than their labels while labels keep the muted text colour, which meets AA contrast on that surface in every theme. The roster follows the compact-row pattern (name and type, state, inline details; actions beside group headings; forms revealed locally) and is read-only, with one explanatory note, while the claim is not published. Copy never says publishing tells anyone and never requires a source. The claim, each source change, each knowledge action and each lifecycle step save independently, and no refresh overwrites another's unsaved input.

### 11.4 Member preview

Previewing what a member sees is a workspace of its own (**Knowledge › Member preview**), never a toggle or panel on the authoring pages. It is read-only and visibly different from authoring: a bordered "Previewing as [member]" banner stays on every preview page, names the character and party perspective, and says plainly that member access (which claims the member may open) is separate from fictional knowledge (what a character or party knows). Nothing is shown until a member is chosen, and the selectors for the previewed character and party are labelled "to preview" so they are not confused with the signed-in person's own perspective. Every value shown is the server's projection for that member; a field the member may not see is absent, never hidden by the page. An invalid selection is a clear error, never a silent fall back to the signed-in person's own data. The preview's whole context lives in its address, and leaving it carries none of that context into normal Knowledge.

Do not label a player-facing belief false merely because canonical truth differs. Do not transform null into a suggestive “hidden” label.

### 11.2 Detail readiness

A full knowledge detail page requires an explicit route and an authoritative detail contract, or a documented guarantee that the list item is itself the complete detail contract and may be fetched directly by ID. It must not depend only on a collection page's in-memory object.

Potential authorized panels include:

- statement;
- awareness and confidence;
- scope and sharing;
- discovery context;
- subject;
- related entities or quests;
- source event/interaction;
- GM truth comparison when separately authorized.

## 12. Quest standard

### 12.1 Collection cards

The current quest list contract supplies only:

- quest name;
- status.

Quest cards should remain concise and must not invent a description, objective count, reward, participant, or location from detail data not present in the list response.

Each card links to the established campaign-scoped quest detail route.

### 12.2 Detail page

This is the audience-filtered reader that every member without `canon.edit` gets. People who can edit canon get the Quest workspace (§12.4) at the same address.

The quest detail surface should include:

- title and current status;
- stages in server-provided sequence order;
- stage description when present;
- objectives grouped under their stage;
- explicit required/optional state;
- completion mode;
- quantity when present;
- current objective status.

Stages and objectives are separate bounded panels or subregions. Do not reorder them alphabetically. Do not disclose hidden stages, hidden objectives, counts, or sequence gaps.

### 12.3 Connected collapsible stage cards

Stages render as one connected vertical column of collapsible cards, in server sequence order, on both the detail page and the **Stages and objectives** section of the Quest workspace (§12.4).

- **Disclosure.** Each stage title is an `<h3>` containing one button with `aria-expanded` and `aria-controls` pointing at the stage body. Stages start collapsed and expand or collapse independently, with an Expand all / Collapse all button above the list (its label follows whether every stage is open); this is local presentation state, sends no request, and is not persisted. A stage with an open form (and so any validation or stale-write notice) stays expanded. Reordering, saving, or editing never collapses a stage.
- **Collapsed summary.** Sequence number, name, stage type, a disclosure indicator in text (`Expand +` / `Collapse −`), and a summary line. The detail page shows `Shown objectives: x of y complete` (or `No objectives shown`), counting only the objectives the server returned for this audience. That list is audience-filtered, so the portal never claims a whole-stage status (Not started, In progress, Complete) from it and never implies whether hidden objectives exist; each shown objective carries its own exact server status. The editor reads a definition, which carries no progress, so it shows the objective count and how many are required instead. The roll-up is text, never color alone.
- **Objectives** are a restrained list inside the expanded body (a left rule, no nested cards). Requirement level is stated in words (**Required** / **Optional**). Each objective's own details are a plain native disclosure inside its list item.
- **Editor ordering.** Each row is the card with a stacked arrow-only `▲` (Move up) and `▼` (Move down) pair on its right, together shorter than the collapsed card header, named for the stage in the accessible label. The buttons are the keyboard, touch, and assistive-technology path; they stay visible and are disabled at the first and last stage and while a reorder is pending. They exist only when the server lists `reorder_stages`. With that action, the card header (and its grip) is also draggable with the pointer; a bar on the target card shows the valid drop position. Both paths send one `reorder_stages` command carrying the full new `stage_ids` order and the loaded row version, and the page then shows the order the authoritative refetch returns. A drop that leaves the order unchanged sends nothing, and a failure or stale write leaves the server's order on screen with the usual recovery notice.
- **Responsive.** Rows are capped at a readable width, the side controls narrow but remain at 390 px, summaries wrap, and nothing scrolls the page horizontally.

Future related-NPC, location, discovery, dependency, outcome, or reward panels require corresponding audience-safe API fields.

### 12.4 Quest workspace

For people who can edit canon, the quest's address (`/app/:campaignId/quests/:questId`) is a guided workspace (§10a.1). It reads the quest through the authoring contract, so it also opens a draft or a quest no party has started. It keeps three things apart, in layout and in words:

| Concept | What it is | Where it appears |
|---|---|---|
| **Workflow phase** | Page navigation only: never stored, sent or a status | The "Quest workflow" row: **1. Prepare**, **2. Review & publish**, **3. Use in play** |
| **Quest stage and objective** | The authored adventure (a definition) | The **Stages and objectives** section, and objective names in Progress |
| **Progress** | Timeline state for the campaign and for each party, changed only by explicit GM commands | The **Progress** section only |

The record's real status (Draft, In review, Approved, Canon, Rejected, Superseded, Archived) is the header badge, from the lifecycle read. Progress status (Not started, Active, Suspended, Completed, Failed, Abandoned) is per scope and never appears in the header. Publication copy never says that publishing starts, activates, completes or reveals the quest, and progress copy never names a lifecycle status.

Sections: **Prepare** has Details (name and summary, and the planning notes only editors see), Stages and objectives (the connected stage cards of §12.3, with their inline forms, ordering and confirmed removals), Dependencies, Outcomes and rewards, Participants, and Sources. **Review & publish** has Review (a summary of the saved structure, the revision comparison links and the Approve or Publish step when the server offers it) and Publication (the one lifecycle rule of §10a). **Use in play** has Progress and, only with `access.manage`, Member preview (the read-only preview of what a member sees). Each section saves on its own and keeps its own errors, confirmations and stale-write recovery. A form that stays mounted while the quest is read again follows its saved fields while untouched, keeps a dirty draft, and when those fields changed elsewhere pauses saving until the person chooses the latest version or keeps the draft; a form never adopts a newer version while holding older values. A changed selection is unsent input, and a progress command refreshes the quest so locked structure is locked at once.

Defaults: draft or rejected opens Details, in review or approved opens Review, published opens Progress, replaced or archived opens Publication. **Next** is "Add stages and objectives" for a draft with nothing to publish, then the server-offered lifecycle step ("Submit for review", "Approve it", "Publish it", "Return it to draft to rework it", "Restore it"), "Use it in play" for a published quest (the name of the phase it opens), or "Replaced by X". Progress lists its scopes (everyone, then each party) down the left, with the status of each, and shows the selected scope's actions and objectives on the right (a row above the section's narrow width); choosing one is presentation only, and the objective moves have room between them. Progress is read once Use in play is first opened and then stays mounted. It offers commands only while the page's own lifecycle read says the quest is published and active, whatever the progress read offers; an unknown status withholds them. A refresh that fails keeps what is shown, says it may be out of date, and offers Try again (which only reads).

When the quest cannot be edited, the definition is text with one line saying why (in review or approved or rejected: return it to draft; archived: restore it; replaced: edit the replacement) and a link to Publication. Once progress is recorded the structure that depends on it stays locked with its reason (§12.3 and the editor's lock note), and wording, visibility, outcomes and participants stay editable. The old `/edit` and `/progress` addresses redirect into the Details and Progress sections.

## 13. State presentation

Every collection and detail route deliberately handles:

### Loading

- Preserve the page shell and context.
- Show a stable loading region.
- Do not flash stale content from the previous ID or perspective.

### Empty

- Explain that no accessible records are currently available.
- Do not imply inaccessible records exist.
- Keep filters usable when changing them may produce authorized results.

### Unavailable

- Use the same non-disclosing presentation for missing and inaccessible records.
- Do not echo internal IDs or backend diagnostics.

### Recoverable error

- Use safe user-facing wording.
- Provide a clear retry action.
- Do not expose exception messages, SQL details, URLs, or internal service names.

### Updating

- Keep existing authorized collection content visible when a search/filter update is recoverable and safe.
- Show the established updating indicator.
- Prevent stale responses from replacing newer query results.

### Disabled feature

- Keep unfinished Phase 12 features visibly disabled according to the server feature manifest.
- A disabled feature makes no related network request and reveals no cached content.

## 14. Accessibility requirements

- One `h1` identifies each page.
- Panels follow with logical `h2` headings; repeated subrecords use `h3`.
- Card collections use semantic lists when they represent lists.
- Navigating cards use native links.
- Buttons are reserved for actions, not navigation.
- Fact groups use semantic description lists.
- Tables have captions and scoped headers, and a table that can be wider than its container sits in a named, keyboard-focusable scroll region.
- Proficiency, known/prepared state, status, confidence, and selection never rely on color alone.
- Focus is always visible in every theme.
- Interactive targets remain usable on touch screens.
- Content remains readable at 200% zoom and at a 320-pixel viewport.
- Motion respects `prefers-reduced-motion`.
- Loading updates should not repeatedly steal focus or announce every keystroke.
- Page navigation should move focus or announce the new route according to the portal's eventual route-focus convention.

## 15. Content and formatting rules

- Humanize displayable codes at the presentation boundary; do not show underscore-separated database vocabulary when a display label is available.
- Keep D&D abbreviations conventional and consistent, such as `STR`, `DEX`, or `DC`.
- Use tabular numerals where aligned numeric comparison matters.
- Format signed modifiers consistently, including `+0`.
- Use “Not recorded” only when absence is itself useful and authorized. For an item's runtime state, say one "Not in play yet" instead of a field-by-field “Not recorded”, and never turn a missing value into a default: a condition no one has set is "No damage recorded", not "Undamaged" or 100%.
- Prefer omission when an optional card field contributes no information.
- Do not expose UUIDs in text, DOM IDs, URLs unless the route contract requires them, accessible names, error messages, or test-only labels.
- UUIDs may remain React keys.

## 16. Component and code boundaries

- Pages compose authorized data into domain-specific presentation.
- API modules perform requests and response handling.
- Hooks own request lifecycle and stale-request protection.
- Boundaries own loading, unavailable, and recoverable-error rendering.
- Shared visual primitives own presentation only.
- Domain wrappers map domain records into visual primitives.
- Components must not duplicate backend authorization logic.
- Avoid a broad state-management dependency unless a demonstrated need appears.
- Avoid a universal “render any API object” card. Explicit domain mapping prevents accidental disclosure.

## 17. Testing standard

### Shared primitives

Test:

- accessible structure and names;
- link or button semantics;
- optional field behavior;
- keyboard-visible state where testable;
- no raw identifier leakage where relevant.

### Domain cards

Test:

- only intended authorized contract fields are shown;
- null optional fields do not produce misleading labels;
- route targets are campaign-scoped and correct;
- status/type formatting is correct;
- cards do not trigger detail fetches before navigation.

### Detail pages

Test:

- major panel headings and fact associations;
- server-provided ordering;
- missing optional collections;
- sparse but valid records;
- no inaccessible or invented sections;
- responsive CSS through build/manual browser checks rather than brittle JSDOM layout assertions.

### Guided workspaces

Test:

- the phase and section links, direct links, defaults for every lifecycle state, and that an unknown section is replaced rather than pushed;
- that no phase or section link sends a request, and that a half-typed draft survives switching;
- that eligibility comes from the server's lifecycle and actions, not from the phase, and that a failed status read withholds commands;
- the reader (no phases, no authoring request, `?section=` ignored) beside the workspace;
- return context: Back to the collection or the Review queue, carried through every link;
- that the phase labels contain neither "stage" nor "phase" where a domain stage exists.

### Route plumbing

Test:

- missing route parameters fail closed;
- cross-campaign IDs remain unavailable;
- loading does not show prior detail content;
- unavailable and errors remain non-disclosing;
- successful data reaches the page;
- perspective changes request the new authorized data.

## 18. Implementation sequence

Use small reviewable increments even when Claude Code performs the implementation.

1. Add shared presentation primitives and focused tests.
2. Redesign character ability cards and character panels.
3. Convert World Explorer results to collection cards without changing their request behavior.
4. Convert Knowledge results to collection cards without inventing a detail route.
5. Convert Quest results to cards linked to the existing quest detail route.
6. Redesign Quest detail using the shared full-detail panel language.
7. Add world and knowledge detail routes only after their authoritative detail contracts are implemented and reviewed.
8. Perform responsive, theme, accessibility, live-authorization, and cross-campaign manual validation.

Do not combine missing world/knowledge backend detail contracts with a purely visual refactor. The collection-card conversion can proceed independently.

## 19. Acceptance checklist

A redesigned surface is complete only when:

- it uses existing theme tokens in every supported theme;
- it is usable at 320 pixels, ordinary desktop widths, and wide desktop widths;
- collection cards remain concise;
- card navigation uses real routes and links;
- detail pages reload directly and support browser Back;
- loading never shows stale detail data;
- no hidden-resource existence is disclosed;
- no capability is inferred locally;
- null fields are handled deliberately;
- focus, headings, labels, and status indicators are accessible;
- a record with several working phases follows the guided workspace rule (§10a.1), with workflow phases named apart from domain terms;
- focused tests pass;
- the complete portal test suite passes;
- lint and production build pass;
- manual live-data verification passes for both rich and sparse fixture records.

## 20. Review responsibilities

### Claude Code implementation review packet

Claude Code should report:

- exact files changed;
- shared primitives introduced;
- domain mappings changed;
- routes added or intentionally deferred;
- tests added/updated;
- commands and results;
- responsive and theme checks performed;
- any backend-contract limitation encountered.

### Codex repository review

Codex should prioritize:

- authorization and data-disclosure regressions;
- route and deep-link correctness;
- stale-data behavior;
- semantic/accessibility defects;
- theme-token violations;
- responsive overflow;
- duplicated or prematurely generalized abstractions;
- missing deployable behavior tests.

### Owner manual validation

Manual validation should cover:

- every configured theme;
- narrow, medium, and wide layouts;
- keyboard navigation and visible focus;
- campaign and character perspective changes;
- rich and sparse character sheets;
- empty World, Knowledge, and Quest results;
- quest detail refresh and Back behavior;
- cross-campaign detail URLs;
- unauthenticated and expired-session behavior.

