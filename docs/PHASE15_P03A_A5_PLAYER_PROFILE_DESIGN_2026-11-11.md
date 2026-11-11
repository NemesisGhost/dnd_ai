# P03-A slice A5: campaign-scoped player profile, GM reads and field publication

**Status (2026-11-11):** detailed design, **proposed**. Nothing in it is implemented. Six owner decisions (D13–D18, §4) must be recorded before the slices that depend on them start (§13). Each has a recommended option. No accepted contract is changed by this document.

**Baseline.**

- `phase15/completion` at `cfaadeb` (local documentation commit on top of the PR #68 merge `b0910c48a8a54e8b9b4d2283ed30d371d704f80c`). `cfaadeb` changes documentation only, so the source, tests and migrations read for this design are those of `b0910c4`.
- PR #68 merged into `main` on 2026-11-11 at 22:38:32 UTC as `b0910c4` (head `d51e38a`). The post-merge `main` push CI run 43113470050 completed with conclusion success on `b0910c4` (queried with `gh` for this design).
- Every code claim was checked by reading source at that baseline. Nothing was run against a database, and no application code, schema or test was changed to produce this design.

**Audience:** the owner (decisions in §4), the A5 implementer (Claude Code Sonnet 5.5 Medium, §15) and the independent reviewer (Codex Luna Medium, §16).

**Governing documents** (read the named sections; this design does not restate them in full):

- [ADR 0021](adr/0021-shared-actor-identity-control-and-authoring-responsibility.md) (accepted): OD-18 and its 2026-11-04 clarification (status block); §2.5 capability routing and the narrative/profile capability table; §2.8 player-profile edit lock row; §2.9 revocation scope; §4.7 delegated player authoring; §4.8 campaign storage; §7 "Player-authored portrayal and profile"; acceptance list (OD-18 clarification, T85).
- [ADR 0016](adr/0016-data-classification-and-private-data-handling.md): data classes and handling.
- [R19 foundation plan](R19_FOUNDATION_IMPLEMENTATION_PLAN.md): OD-18 decision row, T82 and T85, §5.1 obligations (P03-A owns "the campaign-scoped player-profile storage and read").
- [P03-A plan](PHASE14_15_P03A_IMPLEMENTATION_PLAN_2026-11-06.md): §4 (A5 row), §5 (A2 draft/release, D8), §9 (A2b restriction and copy, D7 and D7-a–f), §10.8.6 and §10.11 (keyed-request cycles, DEF-019–021), §11 (P3 commit before response), §12 (A4 audience tier).
- [PLANv2](PLANv2.md) 16A (the portrayal-guidance list) and 15H.
- [BACKLOG](BACKLOG.md) R01 (runtime authorization and transaction defects) and R02 (character-specific deny consistency).
- [DATABASE_CONVENTIONS](DATABASE_CONVENTIONS.md) §10.2/§10.3 (mutable and append-only records), §11 (lookups, not ENUM), §20.4 (local integrity triggers), §24 (classification), §26.3/§26.4 (row versions, authorization before idempotency), §31 (comments), §34 (anti-patterns); [DEVELOPMENT](DEVELOPMENT.md) §6.2, §6.3, §10, §11.

---

## 1. Summary and recommendation

A5 adds the OD-18 player profile: one profile per (campaign, character), versioned and attributed to its editor, readable through a GM route, and a way to publish one selected profile field through the existing A2 draft → release → A3 revelation path.

**The central constraint.** OD-18 makes the profile *player-authored*: only the character's live, in-effect controllers edit it, through `character.edit_player_profile`. Controllers do not exist until P03-B. So A5 cannot have a production writer without inventing an undocumented GM or temporary write route, which OD-18 and this task forbid.

**Recommended shape (D18-a):** A5 ships the storage, the GM read and the publication path **inert in production**. The application roles get `SELECT` only on the profile tables, so no production code can write them. Tests seed profiles through one test helper that performs exactly the write P03-B's command will perform (the A2b-1 precedent, P03-A plan §9.9). P03-B later adds the controller edit command, its grants and the controller read; it changes none of A5's storage.

**Three slices** (§13), in the A2b order, so no commit has a copy path without its restriction:

| Slice | Content | Migration |
|---|---|---|
| **A5a** | Profile storage, the GM read routes, classification, grants that forbid production writes, the seeding helper | `147_character_player_profiles` |
| **A5b** | `player_profile` origin and provenance on public-profile drafts and releases; the D7 restriction generalized per origin (withholding, save rule, release check) | `148_player_profile_provenance` |
| **A5c** | The copy command and route, `player_profile_copy` in the public-profile GM read, the copy audit row | none |

**A5 is optional for entry to A6** (P03-A plan status; BACKLOG priority 3). DEF-019 remains a prerequisite of A6, not of A5 (§12).

**Owner decisions (§4):** D13 field list and publishability; D14 who selects a field for publication; D15 the GM read rule; D16 restriction of copied player-profile text; D17 data classification; D18 population before P03-B. Implementation is **conditional** on their resolution (§13).

---

## 2. The approved requirements

These are owner-approved and accepted. A5 applies them and does not reopen them.

1. **Separate, campaign-scoped profile** (OD-18, ADR 0021 §7). It is distinct from world canon (`character.character_descriptions`) and from GM-private portrayal (`npc_portrayal_profiles`). It grants no GM portrayal access and never reads GM-private fields. Campaign notes, preferences and controller briefings never live in `character.character_descriptions` (§4.8).
2. **Editing** (OD-18 clarification, 2026-11-04). Only the character's live, in-effect primary and co-controllers in that campaign edit it, through `character.edit_player_profile`, conferred only by a control assignment (§2.5) and never through `security.resource_grants` (§4.7). "Nobody else edits it through a player path." Edits are versioned and attributed to the editing member and re-authorized under lock (§2.8 player-profile row). An edit in A never changes A's world canon or B's profile.
3. **Reading.** "Readable by that campaign's GMs (`canon.edit`) and by the character's live, in-effect controllers in that campaign (`character.view_player_profile`), and by nobody else" (§7). T82: "readable by A's GMs and K's controllers in A only".
4. **Publication.** "A field is published only when explicitly selected, through the existing workflow for its destination: to campaign audiences by an OD-17 revelation of a released version, or into world canon only through OD-5 world-authorized review. Nothing is published automatically" (§7). A5 implements only the campaign-audience destination. OD-5 world-canon review is P03-C and out of scope.
5. **Narrative and profile capabilities are distinct** (§2.5 table). `character.edit_player_profile` is never `character.edit_narrative`; neither implies the other.
6. **The P03-A boundary** (R19 plan §5.1): P03-A owns "the campaign-scoped player-profile storage and read". P03-B owns `CONTROL_ASSIGNMENT_CAPABILITIES`, including `character.view_player_profile` and `character.edit_player_profile`, and the locking protocol.
7. **The publication mechanism already exists.** A2's draft carries per-field origins; `player_profile` is reserved for A5 (P03-A plan §5.2; migration 142 docstring; DATABASE_MODEL "`player_profile` is added by A5"). A2b's restriction watermark and coverage rules (D7, D7-a–f) are the approved pattern for copied text.

**What OD-18 does not say**, and §4 therefore proposes: the field list; whether a GM may publish a field without the controller's consent; whether per-character denies or reveal authority affect the GM read; whether D7's restriction applies to player-profile text; the data class; and how the store is populated before P03-B.

---

## 3. Boundary

**In A5:**

- storage scoped to (campaign, character), with immutable attributed versions;
- the GM-side reads (§8);
- publication of one selected field into the public-profile draft, with `player_profile` provenance, then the existing release and revelation (§9).

**Not in A5:**

- **No player editing route and no controller read.** These are P03-B and T85. A5 adds no `character.view_player_profile` or `character.edit_player_profile` vocabulary, matrix entry or grant path.
- **No GM write of profile content.** No interim, administrative or import write path (D18).
- **No A6 portal work, no A7 preview.** The profile is never added to a preview adapter (§6.6).
- **No new mechanics** and no call to the sheet, calculation or rules modules.
- **No control redesign.** No assignment table, lock or capability change.
- **No world-canon mutation.** `core.entities`, `character.character_descriptions` and `npc_portrayal_profiles` are never written. OD-5 world-canon publication is not built.
- **No authorization from PC/NPC labels.** A profile may exist for any character kind (a player-controlled monster is an ordinary character, ADR 0021 §1). The read rule and the copy never consult `core.entity_types` (§8.2, §9.3). This differs deliberately from A2b's legacy copy, whose source rule is keyed by kind because the legacy authoring reads are.
- **No absorbed fixes.** DEF-016, DEF-019, DEF-021 and the R01 stale-authorization follow-up stay where the backlog schedules them (§12).

---

## 4. Owner decisions (proposed)

Each decision is **proposed** until the owner records it. Recommended options are listed first.

### D13 — Field list and publishability

PLANv2 16A lists what a controller maintains: "portrayal guidance, personality, ideals, bonds, flaws, goals, fears, loyalties, boundaries, speech patterns, and player notes". OD-18 does not fix a list.

| Option | Fields | Consequence |
|---|---|---|
| **D13-a (recommended)** | The 16A list as eleven nullable text fields: `portrayal_guidance`, `personality`, `ideals`, `bonds`, `flaws`, `goals`, `fears`, `loyalties`, `boundaries`, `speech_patterns`, `player_notes`. Each at most 4000 characters (`PUBLIC_PROFILE_TEXT_MAX_LENGTH`, so any copy fits a public field). **`boundaries` and `player_notes` are never publishable**; the other nine are. | Matches the approved roadmap text. The never-publishable pair are player-to-GM content (safety limits, out-of-character notes), the analogue of legacy `notes`, which A2b never copies. Adding a field later is an additive migration |
| D13-b | A smaller set, for example `portrayal_guidance`, `personality`, `goals`, `boundaries`, `player_notes` | Less schema now; P03-B or Phase 16 extends it |
| D13-c | One free-text `guidance` field | Simplest; publication becomes all-or-nothing, which weakens "explicitly selected fields" |

**Targets.** Under every option, publication copies one publishable source field into **one existing public text field** chosen by the GM: `public_appearance` or `public_background`. The copy replaces the target's whole text, and the GM edits it down before release, exactly as with the legacy copy. `public_summary` stays authored-only (D5-c, migration 146). No new public-profile field is added. The owner may instead fix a mapping (for example `personality` → `public_background` only); the recommendation keeps the GM's choice, because 16A's fields do not correspond one-to-one with the two public fields.

### D14 — Who selects a field for publication

| Option | Rule | Consequence |
|---|---|---|
| **D14-a (recommended)** | The GM curates. A caller who may edit the public draft (D8) **and** read the player profile (D15) may copy a publishable field into it. Publication still needs a deliberate release by a reveal-authority holder and an OD-17 revelation. | Uses the approved OD-17 workflow as written: selection, release and revelation are each deliberate and attributed. No player content exists before P03-B, so A5 creates no immediate privacy exposure. A controller opt-in can be added additively in P03-B (D14-b) without changing A5's storage |
| D14-b | A controller must first mark a field "may be published" (a per-field consent flag on the version). The copy refuses unmarked fields. | Stronger player control. Requires the P03-B writer, so the A5c copy would accept nothing in production until then; the flag column can be added in A5a and enforced from A5c |
| D14-c | Defer publication (A5b and A5c) to P03-B | A5 becomes storage and read only; T82's "a field reaches other audiences only through a revelation" is then tested later |

The trade-off in D14-a: a player could write something for the GM's eyes only in a publishable field, and the GM could publish it. The never-publishable fields of D13-a are the mitigation for content that must never be published. If the owner wants consent for every field, choose D14-b.

### D15 — The GM read rule

ADR 0021 §7 names "that campaign's GMs (`canon.edit`)". It does not say whether per-character denies or reveal authority change this.

| Option | Rule |
|---|---|
| **D15-a (recommended)** | **Effective character-scoped `canon.edit`**, the D8 test `has_effective_character_canon_edit`: role `canon.edit` in the route campaign, no whole-character deny (`campaign.view` on the character's `entity_id`), and no `canon.edit` deny on the character. Reveal authority confers nothing here. An `allow` grant of `canon.edit` on a character confers nothing (D8). |
| D15-b | Role `canon.edit` only (the D7-e pattern). Per-character `canon.edit` denies do not enter; a whole-character deny still refuses |
| D15-c | D15-a, plus current reveal authority (the D8 public-draft read rule) |

**Why D15-a.** It is the narrowest reading of the approved text and fails closed. A manager who denies a GM `canon.edit` on one character would reasonably expect that GM to lose that character's private player material too. It also gives BACKLOG R02's "controller mechanics/player profile" row a recorded, D8-consistent answer (§12). D15-c would let a reveal holder who is denied `canon.edit` on the character read the player's private text, which OD-18 does not grant.

P03-B extends the rule with `character.view_player_profile` for live, in-effect controllers in the route campaign.

### D16 — Restriction of copied player-profile text in the public draft

Readers of the public draft are D8 readers: effective `canon.edit` **or** reveal authority. Under D15-a, a reveal holder with a `canon.edit` deny on the character reads the draft but not the player profile.

| Option | Rule |
|---|---|
| **D16-a (recommended)** | Apply D7 to the `player_profile` origin, with the D15 read rule as its source rule. Copied text is restricted until a release covers its watermark. It is withheld from public-draft readers who fail the source rule. A release that would include a field withheld from the releaser is refused (403 `public_profile_field_withheld`). The D7-a (clear allowed, replace refused), D7-c (coverage per field), D7-d (retries survive loss of source permission) and D7-f (origin metadata disclosed, never text) analogues apply. |
| D16-b | No restriction for `player_profile`: copied text is ordinary draft text |

**Why D16-a.** Without it, the reveal holder above could read, and release, player text the profile rule denies them. D16-a reuses the reviewed watermark machinery and changes nothing for legacy origins.

### D17 — Data classification of profile text

[ADR 0016](adr/0016-data-classification-and-private-data-handling.md) table: `PLAYER_PRIVATE` is "owner/participants only; GM roles never" and is reserved ("no Phase 15 column carries it"). `GM_ONLY` is "`canon.edit` holders only". `CHARACTER_VISIBLE` is "holders of a character's matching capability", projected "only through the matching perspective".

| Option | Class |
|---|---|
| **D17-a (recommended)** | `CHARACTER_VISIBLE` for every profile text column. GMs read it through `canon.edit` (D15); controllers will read it through `character.view_player_profile` (P03-B). Audit is field names only; idempotency storage is receipt-only; never previewable (no adapter admits it, pinned by a test). No ADR change |
| D17-b | `PLAYER_PRIVATE`, with an ADR 0016 amendment admitting GM reads for this one store and lifting the Phase 15 reservation |
| D17-c | `GM_ONLY` in A5, reclassified by P03-B |

**Why D17-a.** `PLAYER_PRIVATE` as defined forbids the GM read that OD-18 requires. `GM_ONLY` would become wrong at P03-B and mis-describe player-authored content. `CHARACTER_VISIBLE`'s handling rules are at least as strict as A5 needs: no values in audit, receipts only, no reporting access.

### D18 — Population before player editing exists

| Option | Consequence |
|---|---|
| **D18-a (recommended)** | No production writer. The application roles hold `SELECT` only. Tests seed through one helper (§11.1). In production every GM read returns `profile: null` until P03-B, and the copy answers 409 `player_profile_missing` |
| D18-b | Defer all of A5 into P03-B, delivering storage, edit, reads and publication together. A6 does not need A5. This removes the inert period but makes P03-B larger |
| D18-c | An interim GM-authored write route | **Rejected.** It contradicts OD-18 ("player-authored"; "Nobody else edits it through a player path") and is the undocumented temporary production write route this task excludes |
| D18-d | Import from existing data | **Rejected.** No source exists. Legacy `character.character_descriptions` is canon, and copying it would collapse definition into campaign state |

---

## 5. Policy: what the profile holds and what it never holds

**Private, player-supplied narrative.** The profile is the controller's own campaign-scoped material: how they intend to portray the character, and notes to the GM. It is not canon and it is not GM-private.

| Concern | Player profile (A5) | GM-private material |
|---|---|---|
| Stores | the D13 fields | `character.character_descriptions.notes`, `npc_portrayal_profiles`, quest and event GM notes, public-profile drafts and `release_note` |
| Authors | controllers (P03-B); nobody in production before then (D18) | `canon.edit` holders |
| Readers | GMs (D15) and controllers (P03-B) | `canon.edit` holders (and world-private readers where applicable) |
| Class | `CHARACTER_VISIBLE` (D17) | `GM_ONLY` |

**Separation rules** (structural tests in §11.6):

- No profile response includes, joins or derives from any GM-private store. When P03-B serves the same projection to a controller, it can therefore leak nothing GM-private.
- No GM-private response includes profile text. The public-profile GM read shows only copied text that the GM chose, with its provenance.
- The profile query and command modules never reference `character.character_descriptions`, `npc_portrayal_profiles`, the sheet, calculation or rules modules, or `core.entity_revisions`. As with A2, nothing calls `capture_revision`, because `core.entity_revisions` is world-scoped.

**Never-publishable fields** (D13-a: `boundaries`, `player_notes`) cannot be named by the copy request (422), cannot be the origin of any public-profile field (database trigger, §6.3), and never reach a release.

---

## 6. Storage

### 6.1 Migration `147_character_player_profiles` (A5a)

The revision after `146_public_profile_identity` (the current head). The revision id has 29 characters (the Alembic limit is 32). It is additive. It inserts only lookup rows and backfills nothing; after it runs, every character has no profile.

**`campaign.player_profile_fields`**: a lookup, not an ENUM (§11).

- `player_profile_field_id` (UUID PK, as 142's origins lookup), `code` (unique), `display_name`, `description`, `is_publishable BOOLEAN NOT NULL`, `sort_order`, timestamps.
- Seeded with the D13 fields, `is_publishable` per D13.
- Its text columns are registered in `COLUMN_CLASSES` as 142 registered `campaign.public_profile_field_origins`.
- A unit test pins the codes and the publishable set against the domain constants (`PLAYER_PROFILE_FIELDS`, `PUBLISHABLE_PLAYER_PROFILE_FIELDS`).

**`campaign.character_player_profiles`**: the head, a mutable record (§10.2) and the lock anchor ADR 0021 §2.8 names ("the route campaign's player-profile row `FOR UPDATE`").

- `character_player_profile_id` UUID PK.
- `campaign_id` FK → `campaign.campaigns` `ON DELETE RESTRICT`; `character_id` FK → `character.characters` `ON DELETE RESTRICT`.
- `row_version BIGINT NOT NULL DEFAULT 1 CHECK (row_version >= 1)`, kept by `core.bump_row_version()` (§26.3).
- `created_at`, `updated_at` (`core.set_updated_at()`).
- `UNIQUE (campaign_id, character_id)` and `UNIQUE (character_player_profile_id, campaign_id, character_id)`, the target of the composite foreign keys below.
- `campaign_id`, `character_id` and `created_at` are immutable (`core.enforce_immutable_columns`).
- **No text columns.** Content lives only in versions, so there is one copy of each text.

**`campaign.character_player_profile_versions`**: append-only (§10.3). One row per state of the profile.

- `character_player_profile_version_id` UUID PK.
- `character_player_profile_id`, `campaign_id`, `character_id`: a composite FK to the head's triple, so a version cannot name another campaign's or another character's profile.
- `profile_row_version BIGINT NOT NULL`: the head `row_version` this version made current. `UNIQUE (character_player_profile_id, profile_row_version)`.
- The D13 fields, each `TEXT NULL` with `char_length <= 4000` CHECKs. Empty text is stored as NULL (normalized by the writer; a CHECK refuses `btrim(x) = ''`).
- `edited_by_campaign_membership_id UUID NOT NULL` FK → `security.campaign_memberships` (no action, as releases' `released_by_membership_id`).
- `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`.
- `UNIQUE (character_player_profile_version_id, campaign_id, character_id)`, the target of 148's provenance FKs.

**Triggers** (§20.4, local integrity only):

- **Scope** (both tables): the character is in the world of the campaign's timeline, and the editing membership belongs to the row's campaign. This is the pattern of `campaign.enforce_public_profile_scope()`.
- **Version consistency** (`BEFORE INSERT` on versions): `NEW.profile_row_version` equals the head's current `row_version`. The writer updates the head (bumping `row_version`) or inserts it, then inserts the version, in one transaction.
- **Head has its version** (a `DEFERRABLE INITIALLY DEFERRED` constraint trigger, `AFTER INSERT OR UPDATE` on the head): at commit, a version with `profile_row_version = row_version` exists. No committed head state lacks its snapshot.
- **Immutability**: versions refuse UPDATE, DELETE and TRUNCATE (the 142 release pattern).

**Grants.** This is the enforcement point for D18-a.

- On the head and the versions tables, revoke `INSERT`, `UPDATE`, `DELETE` and `TRUNCATE` from `app_read_write` and `integration_worker`; they keep `SELECT`.
- Revoke `ALL` from `app_read_only` (deny-by-default reporting, migration 115).
- The lookup: `SELECT` only.
- P03-B's migration grants `INSERT` on both tables and `UPDATE` on the head when the controller command lands.

**Comments** (§31) on every table, every column and every function. The comments must say that the profile is player-authored, campaign-scoped and never canon, and that it is unwritable by the application until P03-B.

**Indexes.** The unique constraints cover the head lookups and the version FK. Add an index on `versions (edited_by_campaign_membership_id)` as the FK index.

**Entity reference classification.** Register `("campaign", "character_player_profiles", "character_id")` and `("campaign", "character_player_profile_versions", "character_id")` as `BLOCKING` in `ENTITY_REFERENCE_CLASSIFICATION` ([entity_lifecycle.py](../src/dnd_ai/commands/entity_lifecycle.py)). A character with a profile is therefore never physically deleted (ENTITY_LIFECYCLE §14), as with 142.

**Data classification.** Every profile text column is `CHARACTER_VISIBLE` (D17-a) in `COLUMN_CLASSES`. The live-schema classification test then covers the new columns. The docstring reservation of `PLAYER_PRIVATE` is unchanged.

**Downgrade (guarded).**

- The guard runs first. If any head or version row exists, it refuses and changes nothing, because player-authored content cannot be recreated (the 143 pattern).
- On an empty store, it drops the triggers, functions, tables and lookup. It is lossless then.
- Alembic order makes 148's downgrade run first (§6.3).

### 6.2 Who writes the store

No `src/` module in A5 writes either table, and the grants make that impossible for the application roles. Three tests pin it:

- a structural test: no `src/` module issues `INSERT`, `UPDATE` or `DELETE` against them;
- a grant test that runs as `app_read_write`: an insert is refused;
- the route manifest: no route writes them.

The P03-B write, for reference (A5's tests reproduce it in the helper, §11.1):

- ADR §2.8 prefix: world `FOR SHARE` → membership and role rows → account → campaign → the character's `core.entities` row `FOR SHARE` → the caller's assignment row `FOR SHARE`.
- Then the head `FOR UPDATE`, or an `INSERT … ON CONFLICT (campaign_id, character_id) DO NOTHING` race.
- Then the head `UPDATE`, which bumps `row_version`.
- Then the version `INSERT` with that `row_version` and the editor's membership.
- Audit (field names only) and a receipt-only idempotency body (ADR 0016).

### 6.3 Migration `148_player_profile_provenance` (A5b)

It adds the `player_profile` origin to the public profile and generalizes migrations 142–144's per-field rules from "a legacy origin" to "a restricted origin". Legacy behaviour is unchanged. The revision id has 30 characters.

**Lookup row.** Insert `player_profile` into `campaign.public_profile_field_origins` (sort 40; display "Copied from the player profile").

**Provenance columns.** These go on both `campaign.character_public_profiles` (drafts) and `campaign.character_public_profile_releases` (snapshots), for each of the two text fields:

- `public_<field>_origin_player_profile_version_id UUID NULL`. Composite FK `(…version_id, campaign_id, character_id)` → `character_player_profile_versions (character_player_profile_version_id, campaign_id, character_id)`. With MATCH SIMPLE, it is checked only when set. A draft or release can therefore cite only **its own campaign's profile of the same character**, which is database-level campaign isolation for provenance.
- `public_<field>_origin_player_profile_field_id UUID NULL` FK → `campaign.player_profile_fields`.
- These deliberately do **not** reuse `public_<field>_origin_entity_row_version`. That column means "the character's `core.entities.row_version` when legacy text was copied". Storing a profile version in it would give it a second, incorrect meaning.
- Partial indexes `WHERE … IS NOT NULL` on each version-id column (FK indexes).
- `STRUCTURAL` in `COLUMN_CLASSES`. Comments on all of them.

**Origin rule** (`campaign.enforce_public_profile_field_origins()`, `CREATE OR REPLACE`; drafts and releases). Per field:

- Allowed codes: `authored`, `legacy_<field>`, `player_profile`.
- `legacy_<field>` ⇔ `origin_entity_row_version IS NOT NULL` (unchanged).
- `player_profile` ⇔ both player-profile columns `IS NOT NULL`, and otherwise both are NULL.
- A `player_profile` origin's field must have `is_publishable = true`. This is a backstop for D13's never-publishable fields.
- NULL text has origin `authored` (unchanged).

**Watermark pairing.** Drop and re-add `ck_character_public_profiles_<field>_watermark_paired` as `(restricted_row_version IS NULL) = (origin_entity_row_version IS NULL AND origin_player_profile_version_id IS NULL)`. The positive and bounded CHECKs are unchanged.

**Watermark trigger** (`campaign.enforce_public_profile_restriction_watermarks()`, `CREATE OR REPLACE`). It is the 144 body with "restricted provenance present" meaning `origin_entity_row_version IS NOT NULL OR origin_player_profile_version_id IS NOT NULL`:

- **INSERT** with restricted provenance: the watermark equals `row_version`.
- **UPDATE** with restricted provenance where the text, origin, `origin_entity_row_version`, `origin_player_profile_version_id` or `origin_player_profile_field_id` changed: the watermark equals `OLD.row_version + 1`.
- **UPDATE**, unchanged content: the watermark never decreases.
- **Relabel guard** (I1): OLD has restricted provenance, NEW has none, and NEW text is not NULL → refuse.

**Downgrade (guarded).**

- The guard runs first. If any draft or release row has a `player_profile` origin or a non-NULL player-profile column, it refuses and changes nothing. Down-level code would otherwise treat copied player text as authored and show it to every D8 reader.
- On clean data it does the following:
  - restores 142's origin function, 143's paired CHECK and 144's watermark function body exactly;
  - drops the four columns per table;
  - deletes the lookup row.

**Existing rows.** No row is rewritten. Every existing draft and release has NULL player-profile columns, which satisfies the new CHECK and trigger. No `row_version` moves and no audit row is written.

### 6.4 Concurrency tokens

- **Profile head:** `row_version`. It is the source token the copy names (§9.3), and it is P03-B's edit token.
- **Public draft:** `row_version`, unchanged.
- **Release retry key:** `(profile, from_draft_row_version, identity row version)`, unchanged. A release does not lock or read the player profile.

### 6.5 Audit

- **A5a writes nothing**, so it writes no audit rows.
- **The A5c copy** writes one `audit.change_log` row (`copy_player_profile_field_to_public_profile_draft`) with `source_field`, `target_field`, `origin: "player_profile"`, `player_profile_row_version` and the new draft `row_version`. Never text.
- **A save** of a `player_profile`-origin field records field names and the new `row_version`, as today.

### 6.6 Previews, exports and reporting

- **Previews.** No preview adapter may admit the profile tables or the new provenance columns. A test enumerates `PREVIEW_ADAPTERS` and fails if any adapter's sources include them.
- **Reporting.** `app_read_only` has no access (§6.1).
- **Export.** Phase 15 has none.

---

## 7. Lifecycle

| Event | Effect on the profile | Effect on reads and publication |
|---|---|---|
| Campaign archived | Rows retained | Every campaign route refuses through the existing lifecycle gate, as for all campaign routes |
| Campaign physical deletion | Blocked by `ON DELETE RESTRICT` while a profile exists (as 142) | n/a |
| Character archived | Rows retained | The GM read is still allowed (history). The copy gets 409 `public_profile_character_not_active`, as the legacy copy does. Restoring the character re-enables it |
| Character non-canon, or not in the campaign's world | n/a | 404 on every A5 route |
| Character physical deletion | Blocked (`BLOCKING` references, §6.1) | n/a |
| Editor's membership ends | Versions keep `edited_by_campaign_membership_id` (memberships are never deleted) | The GM read still names the editor |
| GM's role revoked or expired, or membership ended | none | That GM's next read or copy is refused, judged at the read or re-checked under lock (§10) |
| Control revoked or replaced (P03-B) | **The profile survives.** It belongs to (campaign, character), not to a controller | Editing ends with control (ADR §2.8, T85). Under the approved contract, a later controller reads the same profile, including earlier controllers' text. P03-B must surface this in its UI. It is recorded here as a consequence, not an A5 decision |
| Same character in campaign B | B has its own head and versions | Nothing written in A is readable through B (§8.3). Provenance FKs forbid cross-campaign citation (§6.3) |
| Campaign on a timeline branch | The campaign has its own profile; nothing is inherited across campaigns or branches | Campaigns are fixed to one timeline (ADR 0021 §2.4 item 5 analogue) |
| Copied text after a source edit | The draft keeps the copied text and its version provenance | The GM read flags `source_changed` (§9.6). A release publishes the copied text only |
| A release after a source edit or retraction | Releases are immutable | Audiences keep seeing the released text until a later release replaces it, or the revelation is revoked (OD-17, "latest release wins"). Withdrawal is a new release with the field cleared |

---

## 8. GM reads (A5a)

### 8.1 Routes

All routes are under `/campaigns/{campaign_id}/characters/{character_id}/player-profile`. The route dependency is `require_campaign_capability("campaign.view")`, and the read rule runs in the query.

**Why `campaign.view`.** P03-B's controller read will reuse these routes, and controllers do not hold `canon.edit`. A player who fails the rule gets the same non-disclosing 404 as a missing profile. This is the public-profile GET's pattern.

| Route | Result |
|---|---|
| `GET …/player-profile` | 200 with the current profile (or `profile: null`), when the caller passes the D15 rule and the character is a canon character of the campaign's world. Otherwise 404 |
| `GET …/player-profile/versions/{profile_row_version}` | 200 with one immutable version. 404 for a non-reader, a non-numeric or out-of-range segment, or a missing version (the A2 release-route pattern) |

### 8.2 The read rule (D15-a)

`may_read_player_profile(access, character_id) = has_effective_character_canon_edit(access, character_id)` lives in `domain/player_profiles.py`.

- It is pure, judged from the request's `AccessContext` at the moment of the read, and takes no locks (as A2's reads).
- It never consults the character's kind, a relationship type, reveal authority or a world role.
- A unit test pins it to `has_effective_character_canon_edit`.
- P03-B adds `or access.has_capability("character.view_player_profile", character_id=…)` from control only.

### 8.3 Effective permissions, by caller

Route campaign A, character K in A's world.

| Caller | Source of authority in A5 | `GET` result |
|---|---|---|
| Built-in Campaign Owner | role `canon.edit` (migration 085) | 200 |
| GM | role `canon.edit` (086) | 200 |
| Assistant GM | role `canon.edit` (086) | 200 |
| Delegated reveal GM | role `canon.edit` through `gm`. The delegation confers nothing here | 200 |
| Custom role carrying `canon.edit` | role capability union | 200 |
| Custom role with `access.manage` only | none | 404 |
| Player or observer | `campaign.view` only | 404 |
| Holder of a legacy relationship (`primary_controller`, `viewer`, …) | relationship capabilities never include `canon.edit` (ADR §2.5 item 5) | 404 |
| Holder of a revelation of K | discovery and the released public profile only | 404 |
| Any caller with a whole-character deny on K | denied | 404 |
| A `canon.edit` holder with a `canon.edit` deny on K | denied (D15-a) | 404, **including** an Owner or delegated GM who keeps reveal authority |
| A raw `allow` grant of `canon.edit` on K (not creatable through the application) | confers nothing (D8) | 404 unless role `canon.edit` |
| World owner, editor, reviewer or reader with no membership of A | no campaign access | the existing campaign gate's non-disclosing refusal |
| World role plus a GM membership of A | the campaign role | 200, through the campaign role only |
| Platform administrator without a membership of A | none (recovery creates an owner, a separate audited path) | the existing campaign gate's refusal |
| GM of campaign B (same world, timeline and K) | B's roles do not apply in A | 404 through A's route. Through B's route, B's own profile only |
| Ended membership, or a revoked or expired role | none | the existing gate's refusal or 404 |
| Live controller of K in A | **not in A5** (P03-B adds `character.view_player_profile`) | 404 in A5 |

### 8.4 Responses: the explicit field sets

Responses carry exactly these keys. Tests assert exact key sets, not subsets.

`GET …/player-profile`:

```json
{
  "character_id": "<uuid>",
  "character_active": true,
  "profile": null,
  "fields_catalog": [{"code": "personality", "label": "Personality", "publishable": true}]
}
```

When a profile exists, `profile` is:

```json
{
  "character_player_profile_id": "<uuid>",
  "row_version": 3,
  "updated_at": "<timestamptz>",
  "edited_at": "<timestamptz of the current version>",
  "edited_by": "<display name of the editing member>",
  "fields": {"portrayal_guidance": "…", "personality": null, "…": "…"}
}
```

- `fields` always has every D13 code, with `null` for empty.
- `fields_catalog` lists every D13 field in `sort_order` (static lookup data).
- No membership UUIDs, user ids, emails or account names are returned. `edited_by` is the display name, as the public-profile read's `released_by` is.

`GET …/player-profile/versions/{n}`: `character_id`, `profile_row_version`, `edited_at`, `edited_by`, `fields`.

### 8.5 Errors

- **Every refusal is the generic 404 body.** That covers a non-reader, a whole-character deny, a `canon.edit` deny, the wrong world, non-canon and a missing version. It never says whether a profile exists.
- **No new read error code.**
- **Query shape.** The current profile is read in one statement that joins the head to the version whose `profile_row_version = row_version`, so a concurrent edit never yields a mixed state (§10.4, race RA1).

---

## 9. Publication (A5b and A5c)

### 9.1 What changes in A2's model

- A draft field may now have the origin `player_profile`.
- Each origin has its own **source rule**:
  - `legacy_appearance` and `legacy_background`: `may_read_legacy_source` (by kind, D7-e), unchanged;
  - `player_profile`: `may_read_player_profile` (D15).
- **Restricted** is unchanged: text, a restricted origin, and no covering release.
- **Withheld** becomes per field. A restricted field is withheld from a caller who fails **that field's** origin's source rule. Today `withheld_fields` applies one kind-based rule to all restricted fields ([public_profile_restrictions.py](../src/dnd_ai/queries/public_profile_restrictions.py)). A5b changes it to group restricted fields by origin, and resolves world authority only when a legacy NPC field needs it.
- **D7's invariants I1–I7 hold for `player_profile` unchanged**, with "legacy origin" read as "restricted origin" and the provenance pair read as the player-profile pair (§6.3). In particular, I2: every content change advances the watermark. I3: editing another field never moves it. I6: clearing ends the lineage. I7: no request names an origin, a version or a watermark.

### 9.2 Save and release (A5b)

These are A2b-1's rules, generalized. Nothing changes for legacy or authored fields.

| Operation | Behaviour with a `player_profile` field |
|---|---|
| Save, field omitted | Untouched; the watermark is unchanged (I3) |
| Save, explicit `null` | Clears it: text NULL, origin `authored`, the provenance pair and the watermark NULL (I6). Allowed even when withheld (D7-a analogue) |
| Save, text, field not withheld | Written. The origin and provenance are kept, and the watermark advances to the new `row_version` (I2) |
| Save, text, field withheld | 403 `public_profile_field_withheld` for the whole request, after the token check and before the no-op comparison (§9.4 of the P03-A plan) |
| Release, new snapshot | Refused with 403 `public_profile_field_withheld` if any field at that draft version is withheld from the releaser (D16-a). Otherwise the snapshot carries each field's origin and provenance pair. The new release covers every field whose watermark is at or below its version |
| Release, natural retry or keyed replay | Returns the existing release with no source check (D7-d analogue). The reveal-authority pre-check and the whole-character deny still apply |

**Lock change: none.** The save and the release already hold the draft `FOR UPDATE`. Every release takes it, so the set of releases a save or release sees is fixed. The player-profile rule is pure on the re-resolved `AccessContext` and needs no new row lock. The deny that changes it arrives only through `create_resource_grant`, which conflicts with the membership `FOR SHARE` both commands hold (P03-A plan §5.7a, "Under lock").

### 9.3 The copy (A5c)

**Route:** `POST /campaigns/{campaign_id}/characters/{character_id}/public-profile/draft/copy-player-profile`. It supports `Idempotency-Key`.

**Request** (`BaseAuthoringRequest`; extra fields refused):

| Field | Type | Meaning |
|---|---|---|
| `expected_row_version` | `int ≥ 1` or `null` | the public draft version the caller read; `null` means "there is no draft yet" |
| `expected_player_profile_row_version` | `int ≥ 1` | the profile version the caller read (the source token) |
| `source_field` | `Literal[<publishable codes>]` | 422 for a never-publishable or unknown field |
| `target_field` | `Literal["public_appearance", "public_background"]` | 422 otherwise |

**Route pre-check** (before the idempotency lookup, DATABASE_CONVENTIONS §26.4):

1. The D8 edit rule (`require_may_edit`): 403 `public_profile_edit_denied` for a caller who can still read the draft, otherwise 404.
2. `may_read_player_profile`: 404.

Under D15-a, the second is implied by the first today. It is kept explicit so that P03-B's broadening of the read rule cannot widen the copy, and a unit test pins the implication. A caller who has lost either right cannot replay a stored copy: the source read is the copy's own authority (D7-d analogue for the copy).

**Command** `copy_player_profile_field_to_public_profile_draft`, in one transaction:

1. `lock_authoring_scope(world_capability=None)`: world `FOR SHARE` → the caller's role rows and membership `FOR SHARE` → account → campaign `FOR KEY SHARE` → the role `canon.edit` re-checked from committed state.
2. Re-resolve the `AccessContext`. Apply the D8 edit rule and the D15 read rule again.
3. The character's `core.entities` row `FOR SHARE`. Canon and world checks give 404; archived gives 409 `public_profile_character_not_active`.
4. The profile head `FOR SHARE`, selected by (route campaign, character). None gives 409 `player_profile_missing`. A head `row_version` ≠ `expected_player_profile_row_version` gives 409 `player_profile_source_changed`.
5. Read, in a separate statement, the version with `profile_row_version = expected`. It is immutable, and the head's share lock pins it as current. If `source_field` is NULL, 409 `player_profile_field_empty`.
6. The public draft `FOR UPDATE`, or the `INSERT … ON CONFLICT DO NOTHING` race. A missing draft for a non-null token gives 409 `public_profile_draft_missing`. A moved token or a lost insert race gives 409 `stale_write`.
7. Write the target field:
   - the text;
   - origin `player_profile`;
   - `origin_player_profile_version_id` and `origin_player_profile_field_id`;
   - `origin_entity_row_version` NULL;
   - watermark = the new `row_version` (1 on insert).

   This always changes the draft, even for identical text: a copy starts new restricted content (I2). The other field and `public_summary` are untouched.
8. The route writes the audit row (§6.5) and finishes idempotency with a receipt. P3 commits before the response.

**Response** (and stored receipt): `character_public_profile_id`, `character_id`, `row_version`, `created`, `changed: true`, `player_profile_row_version`, `source_field`, `target_field`. Never text. 201 if it created the draft, else 200.

**Fingerprint:** `{"character_id": str(character_id), **body}`, as every public-profile POST. The same key and body on another character, field or target is the non-disclosing idempotency 409.

**New error codes** (safe messages, no content):

- `player_profile_missing` (409): "This character has no player profile in this campaign."
- `player_profile_source_changed` (409): "The player profile changed. Reload it and try again."
- `player_profile_field_empty` (409): "That player-profile field is empty."

A caller only reaches these after passing the read rule, so they disclose nothing that caller could not read.

### 9.4 The public-profile GM read (A5b and A5c)

**Draft fields** (A5b). The per-field `<field>_origin` may be `player_profile`, and each text field gains:

- `<field>_origin_player_profile_version` (int or null): the head `row_version` that was copied, not the version UUID;
- `<field>_origin_player_profile_field` (code or null);
- `<field>_player_profile_source_changed` (bool or null). True when the copied field's text in the cited version is distinct from the same field in the head's current version. It is computed only for a caller who passes D15, and is `null` otherwise, because it derives from text that caller may not read.

**Withheld fields** (D16-a, D7-f analogue): `text: null`, `withheld: true`, and the origin code, version number and source field code. Never text, and never `source_changed`.

**Releases in the GM read** gain the same provenance numbers and codes per field.

**`player_profile_copy`** (A5c) is `null` unless the character is active, the caller passes the edit and read rules, and a profile exists. Then it is `{"player_profile_row_version": n, "fields": {"<publishable code>": <has text>}}`: the token the copy needs, and booleans only.

**The audience tier is unchanged.** `read_released_profile` and its SQL select only released text, species and size ([character_public_profile.py](../src/dnd_ai/queries/character_public_profile.py), `_RELEASED_PROFILE_SQL`). No origin, provenance, version or profile identifier reaches an audience response. The existing unit test that pins the audience SQL stays unchanged.

### 9.5 Edit, clear and recopy

| Action on a `player_profile` field | Result |
|---|---|
| GM edits it down to an excerpt | Origin and provenance kept; the watermark advances. It stays restricted until a covering release |
| Excerpt released, then the GM appends more source text | Restricted again (I2/I4). The release still shows only the excerpt. A release by a restricted releaser is 403 |
| Edited back to exactly the released text | Restricted (accepted over-restriction, P03-A plan §9.2) until released again |
| Clear | Lineage ends (I6). A restricted caller may clear (D7-a analogue) |
| Copy again, same or newer version | New restricted content at a new watermark, even from the same version and even after a covering release |
| Copy over a legacy-origin field, or the reverse | The origin and provenance switch; the watermark advances. The relabel guard permits it because NEW still has restricted provenance |
| GM types text by hand that they read in the profile | Authored text (the D7-b analogue, accepted): the rule protects server-copied content and its edits, not what an entitled reader knows |

### 9.6 Source changes

| When the profile changes | Effect |
|---|---|
| Before the copy commits, while the copy waits on the head | The copy sees the new `row_version` and refuses with 409 `player_profile_source_changed` (race C1) |
| After the copy, before release | The draft keeps the copied text and cites the copied version. The GM read sets `source_changed: true` for that field if its text differs. Release is **not** blocked: the release is the GM's review step (§13 notes a possible owner follow-up) |
| After release | The release is unchanged and immutable. Audiences see the released text until a later release. The GM read flags the field as changed. Withdrawal is a new release |

### 9.7 Retries

| Situation | Outcome |
|---|---|
| Copy retried with the same key, caller still permitted | The stored receipt; nothing written |
| Copy retried with the same key after losing D15 or the edit rule (a `canon.edit` deny, a whole-character deny, a revoked role) | The pre-check refuses (403 or 404) before the lookup; no replay |
| Copy retried without a key | Runs afresh. With the old draft token, 409 `stale_write` (the draft moved); with a fresh token, a new copy |
| A copy refused 409, retried with the same key | Runs afresh, because refusals store nothing |
| Release of a `player_profile` field, retried after the releaser lost D15 | Receipt or 200 `created: false` (D7-d analogue); refused only by the reveal pre-check or a whole-character deny |
| Same key, same body, different character | Non-disclosing idempotency 409 |

---

## 10. Concurrency

### 10.1 Lock orders

The A1 design §3 table and P03-A plan §5.8 and §9.6 gain one row and one head step. No row is reversed.

| Command | Locks, in order |
|---|---|
| `copy_player_profile_field_to_public_profile_draft` (A5c) | `lock_authoring_scope`: world (S) → the caller's role rows and membership (S) → account (S) → campaign (KEY SHARE); then role re-check → `AccessContext` re-resolve → character entity (S) → **profile head (S)** → version read (no lock; immutable) → public draft (U) or the unique-index wait |
| Save, release | Unchanged (§9.2) |
| P03-B profile edit (reference only) | ADR §2.8: world (S) → membership and role rows → account → campaign → character entity (S) → assignment row (S) → profile head (U) |

**Pairwise reasoning.**

- **Copy against save or release.** These are A2b's copy against save or release, plus a head lock that neither of them takes. The draft row orders them.
- **Copy against the P03-B edit, or A5's seeding helper.** The copy holds the head `FOR SHARE` and next waits only for the draft, which the edit never takes. The edit waits for the head `FOR UPDATE` and holds only shared locks the copy does not request in a conflicting mode. There is no cycle.
- **Copy against control revocation (P03-B).** Revocation takes the target membership (U), then the campaign (U), user and entity (U). The copy takes campaign `KEY SHARE` before the entity. Revocation waits at the campaign while holding nothing the copy wants next, so either can finish first. There is no cycle.

### 10.2 Fresh authorization after waits

- **The copy.** The role is re-checked from committed state inside `lock_authoring_scope` after its waits. The `AccessContext` is re-resolved after them, and D8 and D15 are judged on it. This is the same position as every authoring write and A2b's copy.
- **Time-based expiry.** A role whose `expires_at` lapses during a wait is judged as `lock_authoring_scope` judges it for all authoring writes. A5 does not add a fresh-instant re-check for `canon.edit`. That gap is BACKLOG R01's DEF-015 F-1 stale-authorization follow-up, which covers every authoring write and is not absorbed here (§12).
- **The release** keeps its DEF-013 fresh-instant re-check unchanged.
- **Reads** are judged at the moment of the read.

### 10.3 Transactions, receipts and audit

- Each command is one request transaction: the business write, the audit row and the idempotency receipt commit together.
- P3 commits before the response, so a commit-time failure answers 5xx with nothing persisted. A refusal stores no receipt and writes no audit row.
- A5a has no write. Its GET routes hold the request transaction for the read only.

### 10.4 Required races

Every race in this section is a **real HTTP race through the application** (`TestClient` against the real routes), using the existing harness (`tests/lock_race_support.py`: `LockRace`, `Hold`, `Pause`, the corrected `Budget`) and request-specific blocker observation (`pg_blocking_pids`). Command-only races do not substitute for these. Each is run in both orders, where an order exists. Each asserts:

- status codes and the absence of SQLSTATE 40P01;
- the draft row: `row_version`, text, origin, provenance pair and watermark;
- the release rows;
- the count of audit rows and the presence of a receipt;
- that no business write, audit row or receipt remains for a loser.

The profile-edit side of a race is the §11.1 seeding helper running the P03-B write shape in its own transaction, because no route writes the profile in A5. That is the only non-HTTP party, and it stands in for a writer that does not yet exist.

| # | Slice | First | Second | Expected |
|---|---|---|---|---|
| RA1 | A5a | Helper edit holds the head `FOR UPDATE` (uncommitted) | `GET …/player-profile` | 200 with the previous complete version (no mix); after commit, the new one |
| R1 | A5b | Release (unkeyed) of a draft with an uncovered `player_profile` field by a reveal holder | `canon.edit` deny on that releaser on K through the real grant route | Release first: the grant waits; the release commits (201). Grant first: the release waits at the membership, re-resolves, and gets 403 `public_profile_field_withheld`; nothing written |
| R2 | A5b | A permitted GM edits a released `player_profile` field | A restricted releaser releases the earlier draft version | Either 409 `stale_write`, or 200 `created: false`, or a release of the earlier text only. Afterwards the field is withheld from the restricted reader |
| C1 | A5c | Helper edit of the profile | Copy (keyed) naming the old profile version | Edit first: the copy waits at the head and gets 409 `player_profile_source_changed`; nothing written, no receipt. Copy first: the edit waits; the copy commits citing the old version; then the edit commits; the GM read shows `source_changed: true` |
| C2 | A5c | Revocation of the copier's GM role | Copy (unkeyed) | Revoke first: the copy is refused, non-disclosingly. Copy first: the revoke waits; the copy commits |
| C3 | A5c | `canon.edit` deny on the copier on K, through the real grant route | Copy (unkeyed) | Grant first: the copy re-resolves; 403 `public_profile_edit_denied` (copier still reads the draft through reveal authority) or 404. Copy first: the grant waits; the copy commits |
| C4 | A5c | End of the copier's membership | Copy (unkeyed) | They serialize at the membership. End first: the copy is refused. Copy first: the end waits |
| C5 | A5c | Public-draft save | Copy, same draft token | The second gets 409 `stale_write`, in both orders |
| C6 | A5c | Release of draft version *n* | Copy with token *n* | Both commit, in either order. The release holds the pre-copy text; the copy's field is restricted and uncovered |
| C7 | A5c | Archive of K | Copy | Archive first: 409 `public_profile_character_not_active`. Copy first: the archive waits on the entity |

**Keyed authority-loss races are deliberately not in A5.** A keyed copy reserves its key (taking `KEY SHARE` on the campaign through the reservation's foreign key) before its command locks. Against the end of the copier's own membership, a role revocation or change, or a grant naming the copier, it forms the cycle the P03-A plan records as K3/K4 and K10–K12 (§10.8.6): proposed **DEF-019**. That cycle exists today for A2's keyed save and legacy copy.

- A5 does not move the copy's reservation (A3's step-0 pattern), because that would fix one route of DEF-019 ad hoc.
- A5 adds the copy route to DEF-019's route inventory (BACKLOG R01a).
- The DEF-019 correction must add the keyed HTTP races for every keyed authoring route, including this one.
- A5 tests no expectation that requires a deadlock.

---

## 11. Tests

### 11.1 Seeding helper (A5a)

`tests/player_profile_support.py`:

- `seed_player_profile(engine, *, campaign_id, character_id, editor_membership_id, fields)` creates a profile;
- `edit_player_profile(...)` adds a version.

Both run as the test superuser, in one transaction, in the exact P03-B order of §6.2 (minus the assignment row, which does not exist yet), and respect every trigger. This is the **only** raw writer. It is replaced by P03-B's command, as A2b-2 replaced A2b-1's helper. A structural test confines raw inserts into the profile tables to this module.

### 11.2 Reader matrix (A5a)

Every §8.3 row, through the HTTP routes, with roles, grants and denies created through the application (A2a-R's deny route). Each row asserts:

- the status code;
- the exact response key set;
- for 404s, the generic body, byte-identical to the not-found response for a character with no profile.

### 11.3 Campaign isolation (A5a, A5b, A5c)

Campaigns A and B share one world, one timeline and character K. One account is GM in both, another is GM in B only.

- K has distinct-marker profiles in A and B. Each route returns only its own campaign's profile; B's route never returns an A marker, and the reverse.
- With a profile only in A: B's GET gives `profile: null` (to B's GM) or 404 (to non-readers); B's copy gives 409 `player_profile_missing`.
- A raw-row attempt to give B's draft a provenance pair citing A's version is refused by the composite FK. The same holds for releases.
- A copy, release and revelation in A change nothing in B's draft, releases, audience responses or audit filtered by B.

### 11.4 Response-body disclosure

- **Markers.** Every profile field carries a distinct marker, per campaign. `boundaries` and `player_notes` carry markers that must never appear outside the A5a GM read for a reader.
- **Sweep.** Every surface of the A2a, A2b and A4 marker sweeps, the new routes, every 403, 404, 409 and 422 body, every stored receipt, the audit history (`access.manage`) and the audience tier (A4 detail, browse and search).
- **Callers.** Player, observer, B's GM, a GM with a `canon.edit` deny on K (including when they hold reveal authority), a world-role-only account, and an assistant GM after role revocation.

**Assertions:**

- No body for those callers contains any profile marker.
- After copy → release → revelation, audience bodies contain exactly the released excerpt's markers and no other field's.
- No audience body contains `player_profile`, a profile version number or a profile id.

### 11.5 Publication and lifecycle (A5b and A5c)

- **The excerpt regressions of P03-A plan §9.8**, rerun for a `player_profile` origin: copy, excerpt, release, append, restore, and restore-to-released. Seeded in A5b; through the real copy in A5c.
- **Unchanged-field visibility, mixed-field atomic refusal, clear, recopy, stale writes** (stale token before 403), and the §9.5 table rows.
- **Copy rules.** Owner, GM, assistant GM and custom `canon.edit` are allowed. Refusals:
  - a player gets 404;
  - a `canon.edit` deny gets 403 or 404;
  - a whole-character deny gets 404;
  - an archived character gets 409;
  - no profile gets 409 `player_profile_missing`;
  - an empty field gets 409 `player_profile_field_empty`;
  - a stale profile token gets 409 `player_profile_source_changed`;
  - a stale draft token gets 409 `stale_write`;
  - a missing draft with a token gets 409 `public_profile_draft_missing`;
  - `source_field: "boundaries"` or `"player_notes"` gets 422, and so does an unknown target or an extra field.
- **Kinds.** Copy works identically for `npc`, `player_character` and plain `character` kinds (no label-based authorization).
- **Retries.** Every §9.7 row.
- **Rollback.** A forced commit-time failure of a copy (the P3 deterministic failure technique) leaves no draft change, no audit row and no receipt, and the client gets 5xx.
- **The T82 player-profile clause end to end** (a scenario or HTTP test): a profile in A; copy `personality` to `public_background`; edit to an excerpt; release; `campaign_current` revelation. A player in A sees only the excerpt. B, and A's observer without the revelation, see nothing.

### 11.6 Schema, migration and structure

**Migration 147:**

- up, down, up; `alembic check` clean;
- the downgrade guard refuses with any profile row and changes nothing;
- positive and negative tests for every CHECK and trigger in §6.1 (scope, version consistency, deferred head-has-version, immutability, empty-text CHECK, length);
- grants as `app_read_write`, `integration_worker` and `app_read_only`;
- comments present; FK index present; object ownership by `migration_owner` (DEVELOPMENT §11).

**Migration 148:**

- up, down, up;
- the downgrade guard refuses with any `player_profile` provenance;
- origin-trigger acceptance and refusal per field and code (including a never-publishable field id);
- the new paired CHECK, and every watermark-trigger rule for both restricted provenances;
- the generalized relabel guard;
- **every existing 143/144 watermark test passes unchanged at head**;
- existing authored and legacy rows untouched (`row_version`, text, origins), with no audit row.

**Schema drift:** `alembic check`, plus `COLUMN_CLASSES` covering every new column (the live-schema test).

**Structure:**

- no `src/` writer of the profile tables;
- the profile modules reference no GM-private store, no `character_descriptions`, no rules or sheet module, and no `entity_types`;
- `_RELEASED_PROFILE_SQL` unchanged;
- `PREVIEW_ADAPTERS` admit no profile column;
- the route manifest gains the three routes;
- `test_world_gate_registry.py`'s `EXPECTED_CAMPAIGN_ONLY_SCOPES` gains the copy command's `lock_authoring_scope(world_capability=None)` call site (a campaign draft, not shared canon, as the draft save already is);
- `ENTITY_REFERENCE_CLASSIFICATION` covers the two new `character_id` FKs;
- the policy and copy domain constants match the lookup.

**Unit:**

- `may_read_player_profile` is equal to `has_effective_character_canon_edit` over a synthetic `AccessContext` matrix;
- edit rule ⇒ read rule;
- the per-origin source-rule dispatch;
- `field_is_restricted` over synthetic histories for both restricted origins.

### 11.7 Regression boundary

Run unchanged, focused, at each slice boundary:

- A2: `test_character_public_profile_*.py`;
- A4: `test_public_profile_identity_*.py`;
- A3: `test_character_revelations_*.py`;
- A1: `test_character_reveal_delegation*.py`;
- `test_data_classification_schema.py`, `test_request_transaction.py` (P3), and the P0/P1 lock suites.

Then run the full suite with the four-shard runner (`uv run python scripts/run_sharded_tests.py`). It applies DEVELOPMENT §6.2's configuration isolation itself, so report the run as "defaults, `.env` override removed". Each shard runs on its own throwaway PostgreSQL 18 cluster. Report any rerun separately.

---

## 12. Dependencies and open defects

| Item | A5 impact | Disposition |
|---|---|---|
| **DEF-019** (keyed requests deadlock through the reservation's campaign `KEY SHARE`) | A5c's copy is a new keyed authoring route with the same exposure as A2's keyed save and legacy copy (§10.4) | **Not absorbed.** It stays scheduled before A6. Add the copy route to its R01a inventory; its correction adds the keyed HTTP races |
| **DEF-021** (a write holding the campaign `FOR UPDATE` against the end of its actor's membership) | None: the copy never takes the campaign `FOR UPDATE` | Unchanged |
| **DEF-020** (recovery against membership end) | None | Unchanged |
| **DEF-015 F-1 / R01** stale authorization after waits | The copy re-checks exactly as every authoring write does; time-based role expiry during a wait is the shared gap | Not absorbed; R01 covers all authoring writes, including the copy |
| **DEF-016** (`canon.edit` checked under `character_id` in view-tier and inventory resolvers) | A5 must not copy the pattern; it uses `has_effective_character_canon_edit` | Unchanged; R02 |
| **R02** character-specific deny consistency | A5 records the player-profile row: whole-character deny refuses; a `canon.edit` deny refuses the GM read (D15-a) and the copy | R02's table gains this row as "decided by D15" once the owner records D15 |
| **DEF-017, DEF-002** | None | Unchanged |
| Retained A3/A4 harness findings (best-effort thread cleanup, fixed-budget waits, the undiagnosed triple-runner migration failure, process freezes) | A5's races use the same harness and inherit them | Not fixed here; a new A5 race flake is reported with its run, not retried away |
| **P03-B** | Consumes A5's storage unchanged: adds the capabilities, the edit command, grants and the controller read | A5 must not pre-empt any of it |
| **A6** | Does not need A5 | DEF-019 first |

---

## 13. Slices and acceptance criteria

The decision gates are the owner's to record. Until then, the slice does not start. **If the owner chooses a non-recommended option, this design must be revised for that option before implementation.**

| Slice | Requires recorded decisions |
|---|---|
| A5a | D13, D15, D17, D18 |
| A5b | A5a reviewed; D16 |
| A5c | A5b reviewed; D14 (and D13's publishable set) |

**A5a — storage and the GM read.**

- **Code:**
  - migration 147 (§6.1);
  - the table metadata in `persistence/tables/campaign.py`;
  - `domain/player_profiles.py` (vocabulary, `may_read_player_profile`);
  - `queries/player_profiles.py` (the two reads);
  - `api/player_profiles.py` (the two GET routes), registered in `create_app`;
  - `COLUMN_CLASSES`, `ENTITY_REFERENCE_CLASSIFICATION`;
  - `tests/player_profile_support.py`.
- **Acceptance:**
  1. The new tests fail at the parent.
  2. §11.2 matrix, §11.3 for reads, the §11.4 sweep for the new routes, the §11.6 migration-147 and structure items, and race RA1.
  3. As `app_read_write`, the application cannot write a profile.
  4. Every pre-existing test passes unchanged.

**A5b — provenance and restriction, before any copy exists.**

- **Code:**
  - migration 148 (§6.3);
  - the per-origin source-rule dispatch in `domain/public_profiles.py` and `queries/public_profile_restrictions.py`;
  - the save, release and GM-read changes of §9.2 and §9.4 (draft fields and releases; no `player_profile_copy`).
- **Tests:** `player_profile`-origin draft fields are seeded through a helper that writes rows satisfying 148's trigger and CHECKs (the only raw-row seeding of drafts; A5c replaces it).
- **Acceptance:**
  1. The §11.5 excerpt, mixed, clear, unchanged-field and stale cases on seeded copies.
  2. Races R1 and R2.
  3. The §11.6 migration-148 items.
  4. The §11.7 regression boundary, including every A2b test unchanged.

**A5c — the copy.**

- **Code:**
  - the command and route (§9.3);
  - the three error codes;
  - `player_profile_copy` and `source_changed` in the GM read;
  - the audit row;
  - the idempotency command name.
- **Acceptance:**
  1. The §11.5 copy rules, kinds, retries and rollback.
  2. The excerpt regressions rerun through the real copy.
  3. The T82 clause end to end.
  4. §11.3 and §11.4 in full.
  5. Races C1–C7.

**Every slice:**

- `ruff format --check`, `ruff check`, `mypy src`, `uv lock --check`, `alembic upgrade head` and `alembic check` on a disposable PostgreSQL 18 database, and `git diff --check`;
- the focused tests, then the four-shard full run;
- one local commit per slice, with explicit paths;
- stop for independent review naming the parent and target SHAs;
- no push and no PR unless the owner asks;
- CI on the pushed head is recorded when the owner pushes.

**A possible later owner follow-up (not an A5 decision):** whether a release should be blocked while a copied `player_profile` field's source has changed (§9.6). A5 shows an indicator only.

---

## 14. Documentation the implementation updates in the same commits

| Document | Change | Slice |
|---|---|---|
| `DOMAIN_MODEL` | Player profile, profile version, publishable field, the `player_profile` origin, per-origin source rule | A5a, A5b |
| `architecture/DATABASE_MODEL` | The three tables, triggers and grants (147); the provenance columns and replaced functions (148); the existing line "`player_profile` is added by A5" made current | A5a, A5b |
| `PHASE13E_ACCESS_CONTRACT` and `api/ACCESS_CONTROL` | The GM read rule and routes, the per-origin withholding, the copy route and the three error codes | A5a, A5b, A5c |
| `ENTITY_LIFECYCLE` command list | The copy command | A5c |
| ADR 0016 | Nothing under D17-a. An amendment only if the owner chooses D17-b | — |
| This design | An implementation record per slice (SHAs, commands, results, deviations) | each |
| P03-A plan status line, PLANv2 15H status, PROJECT_STATUS and the BACKLOG P03-A row | Slice state | each |

---

## 15. Implementation prompt (Claude Code Sonnet 5.5, Medium)

> Use this prompt verbatim once the owner has recorded the decisions for the slice being started. Replace `<SLICE>` with A5a, A5b or A5c.

```text
You are implementing P03-A slice <SLICE> of the D&D AI World Platform in the existing repository
C:\Users\nemes\dnd_ai on branch phase15/completion. Do not create a branch, clone or worktree.
Do not push, open a PR, rebase, amend, reset, stash or force anything.

Authoritative design: docs/PHASE15_P03A_A5_PLAYER_PROFILE_DESIGN_2026-11-11.md. Read §1–§3, §4
(and the owner's recorded answers for D13–D18 in the P03-A plan's "Decisions still needed"
section), then the sections for <SLICE>: A5a §5, §6.1–§6.2, §6.5–§6.6, §7, §8, §10, §11.1–§11.4,
§11.6–§11.7, §13; A5b §6.3, §9.1–§9.2, §9.4–§9.6, §10, §11.5–§11.7, §13; A5c §9.3–§9.7, §10,
§11, §13. If any decision your slice needs is not recorded, or was recorded as an option other
than the recommended one, stop and report; do not implement a guess.

Also read CLAUDE.md; docs/PHASE14_15_P03A_IMPLEMENTATION_PLAN_2026-11-06.md §5.5–§5.9 and §9
(the A2 and A2b patterns you are extending); the existing code in
src/dnd_ai/domain/public_profiles.py, src/dnd_ai/queries/public_profile_restrictions.py,
src/dnd_ai/queries/character_public_profile.py, src/dnd_ai/commands/character_public_profile.py,
src/dnd_ai/api/character_public_profile.py and migrations 142–146. Follow their patterns exactly
(lock_authoring_scope, AccessContext re-resolve, require_may_edit, idempotency pre-checks before
start_campaign_idempotency, character_id in the fingerprint, audit in the route, receipts only).

Hard rules:
- No production write path to campaign.character_player_profiles or
  campaign.character_player_profile_versions. The application roles get SELECT only.
- No character.view_player_profile / character.edit_player_profile vocabulary (that is P03-B).
- Never authorize from character kind or relationship labels in A5 code.
- Never put profile text in audit rows, receipts, logs or error bodies.
- Never reuse public_<field>_origin_entity_row_version for player-profile provenance.
- Leave _RELEASED_PROFILE_SQL and the audience tier unchanged.
- Do not fix DEF-016, DEF-019, DEF-021 or R01 stale authorization; do not move the copy's
  idempotency reservation. Do not add keyed authority-loss races (they belong to DEF-019).
- Every race named for your slice in §10.4 is a real HTTP race through TestClient using
  tests/lock_race_support.py, in both orders. Command-only races do not satisfy it.
- New tests must fail at the parent commit. Existing tests must pass unchanged unless the design
  names the change.

Verification before committing:
  uv run ruff format --check . ; uv run ruff check . ; uv run mypy src ; uv lock --check
  focused: uv run pytest <the new and §11.7 regression files> -q
  migration: alembic upgrade head, downgrade to 146 (A5a) or 147 (A5b), upgrade head, alembic check,
    on a disposable PostgreSQL 18 database only, never the developer's dnd_ai database
  full: uv run python scripts/run_sharded_tests.py   (report reruns separately)
  git diff --check

Update the documents listed in design §14 for your slice in the same commit. Add a dated
"<SLICE> implementation record" to the design document with the parent SHA, the commit SHA,
the exact commands run, the results (counts, durations, any reruns and their reasons) and
any deviation from the design with its reason.

Commit once, with explicit paths, message "feat(p03a): <SLICE> <short summary>", ending with
the attribution lines your harness requires. Then stop and report: parent and commit SHAs,
files changed, the test evidence, deviations, and anything you could not verify.
```

---

## 16. Independent review guidance (Codex Luna, Medium)

Review one slice per pass, naming the parent and target SHAs. Run the new tests at the parent to confirm that they fail, then at the target. Record the verdict as PASS, PASS WITH NONBLOCKING FINDINGS, or CHANGES REQUIRED, grading findings with [ISSUE_GRADING_RUBRIC](ISSUE_GRADING_RUBRIC.md).

**Check in every slice:**

1. **Boundary** (§3).
   - No production writer of the profile tables. Confirm with grants as `app_read_write`, a source search, and the route manifest.
   - No P03-B capability vocabulary.
   - No kind- or label-based authorization in A5 code.
   - No world-canon writes. No preview adapter.
2. **Disclosure.**
   - Open every response body for the non-reader callers of §11.4. Check 4xx bodies, receipts and audit rows too, not only 200s.
   - Confirm `boundaries` and `player_notes` cannot reach a draft, a release or any audience surface. That covers the request `Literal`, the trigger, and a raw-row attempt.
3. **Campaign isolation.** Shared world, timeline and character; the composite provenance FK; B never sees A.
4. **Migrations.**
   - Up, down and up on PostgreSQL 18. The guards refuse with data and change nothing.
   - 148's downgrade restores 142, 143 and 144's exact function bodies and CHECK (compare `pg_get_functiondef` before and after).
   - `alembic check` is clean.
   - Comments, ownership, FK indexes and grants.
5. **Tests prove production invariants.**
   - Races are real HTTP in both orders, with the persistence assertions of §10.4.
   - No test expects a deadlock or an unauthorized success.
   - No assertion is weakened in an existing test.

**Slice-specific:**

- **A5a.**
  - The read rule is exactly D15 as recorded, judged without locks.
  - The current-profile query is one statement (RA1).
  - 404 bodies are identical for "not a reader" and "no such character".
  - The deferred head-has-version trigger really fires at commit: a head insert without a version fails at COMMIT.
- **A5b.**
  - Withholding is per field and per origin. A draft holding one legacy NPC field and one `player_profile` field withholds each by its own rule.
  - The watermark trigger refuses every non-advancing change of the player-profile pair.
  - The relabel guard covers both provenances.
  - Every A2b test passes unchanged.
- **A5c.**
  - The pre-check runs before the idempotency lookup, so a replay after authority loss is refused.
  - Lock order as in §10.1.
  - The source token is checked under the head's share lock.
  - The response, receipt and audit row carry no text.
  - Races C1–C7.
  - Keyed authority-loss races are absent by design. The DEF-019 inventory mentions the copy route.

**Out of scope for findings:** DEF-019, DEF-016, DEF-021 and R01 themselves; P03-B controller behaviour; A6/A7 UI. If you believe one of these blocks A5, grade it and say why, rather than requesting it be fixed inside A5.

---

## 17. Records

*(Implementation and review records are appended here, newest last.)*
