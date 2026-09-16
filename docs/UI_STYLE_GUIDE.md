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

Hoverable cards may use `--color-surface-hover`. Avoid stacking multiple bordered cards inside one another. A detail page may contain panels, but a panel should not contain another full panel unless the nested element is a distinct, necessary subrecord such as a spellcasting profile.

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

Do not create headings solely to make text larger. Preserve a logical heading outline independent of visual styling.

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

Use tables only for genuinely tabular comparisons. Wrap unavoidable wide tables in a local horizontal-scroll container. A page must never gain horizontal scrolling because of a table.

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

## 11. Knowledge standard

### 11.1 Collection cards

Knowledge cards may display authorized fields from the current list contract:

- knowledge type;
- statement;
- scope;
- awareness level;
- confidence when meaningful to the current audience;
- willingness to share when meaningful to the current audience;
- truth status only where the API intentionally returns it for that audience.

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

Future related-NPC, location, discovery, dependency, outcome, or reward panels require corresponding audience-safe API fields.

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
- Tables have captions and scoped headers.
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
- Use “Not recorded” only when absence is itself useful and authorized.
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

