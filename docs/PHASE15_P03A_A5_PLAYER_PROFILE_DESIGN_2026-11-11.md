# P03-A slice A5: campaign-scoped player profile, GM reads and field publication

**Status (finalized 2026-11-11):** **approved design, not implemented.** The owner approved D13–D18 on 2026-11-11 (§4). The approvals are recorded here and in the P03-A plan's "Decisions still needed" section. No owner decision is open for A5. Slices A5a, A5b and A5c (§13) may start in order, each after the previous slice's independent review.

**What A5 delivers.** A5 is **infrastructure**, not delivered profile-authoring functionality. It provides storage, GM reads and a GM-side publication path. There is **no production profile writer**: until P03-B delivers controller editing, every production profile read returns no profile. P03-B must deliver the write privileges, the edit command, attribution, versioning writes and controller authorization (§6.2, §12).

**History.** The design was first committed at `d04ca57` (2026-11-11) with D13–D18 as proposals. This revision applies the approvals. The original options and recommendations are kept as a dated record in §4.8, separate from the approved rules.

**Baseline.**

- **Design.** Source, tests and migrations were read at `b0910c48a8a54e8b9b4d2283ed30d371d704f80c`, the PR #68 merge into `main`. Its post-merge `main` CI run 43113470050 succeeded (queried with `gh`).
- **Later commits.** `cfaadeb`, `d04ca57` and `f577499` on `phase15/completion` change documentation only.
- **Finalization.** This revision was made on `phase15/completion` at parent `f5774997fc47b585b908da8856ab23ebe561b3e6`.
- **Method.** Every code claim was checked by reading source. Nothing was run against a database. No application code, schema or test was changed to produce this design.

**Audience:** the owner, the A5 implementer (Claude Code Sonnet 5.5 Medium, §15) and the independent reviewer (Codex Luna Medium, §16).

**Governing documents** (read the named sections; this design does not restate them in full):

- [ADR 0021](adr/0021-shared-actor-identity-control-and-authoring-responsibility.md) (accepted):
  - OD-18 and its 2026-11-04 clarification (status block);
  - §2.5 capability routing and the narrative/profile capability table;
  - §2.8, the player-profile edit lock row;
  - §2.9 revocation scope;
  - §4.7 delegated player authoring;
  - §4.8 campaign storage;
  - §7 "Player-authored portrayal and profile";
  - the acceptance list (OD-18 clarification, T85).
- [ADR 0016](adr/0016-data-classification-and-private-data-handling.md): data classes and handling.
- [R19 foundation plan](R19_FOUNDATION_IMPLEMENTATION_PLAN.md): the OD-18 decision row; T82 and T85; §5.1 obligations (P03-A owns "the campaign-scoped player-profile storage and read").
- [P03-A plan](PHASE14_15_P03A_IMPLEMENTATION_PLAN_2026-11-06.md):
  - §4 (the A5 row);
  - §5 (A2 draft and release, D8);
  - §9 (A2b restriction and copy, D7 and D7-a–f);
  - §10.8.6 and §10.11 (keyed-request cycles, DEF-019–021);
  - §11 (P3, commit before response);
  - §12 (the A4 audience tier).
- [PLANv2](PLANv2.md): 16A (the portrayal-guidance list) and 16B/16C (private notes and collaboration, separate scope); 15H.
- [BACKLOG](BACKLOG.md): R01 (runtime authorization and transaction defects) and R02 (character-specific deny consistency).
- [DATABASE_CONVENTIONS](DATABASE_CONVENTIONS.md): §10.2/§10.3 (mutable and append-only records), §11 (lookups, not ENUM), §20.4 (local integrity triggers), §24 (classification), §26.3/§26.4 (row versions; authorization before idempotency), §31 (comments), §34 (anti-patterns).
- [DEVELOPMENT](DEVELOPMENT.md): §6.2, §6.3, §10, §11.

---

## 1. Summary

A5 adds the storage and reads for the OD-18 player profile:

- one profile per (campaign, character);
- immutable versions with editor attribution;
- a GM read route;
- a GM-side path that copies one eligible profile field into the public-profile draft.

The copy publishes nothing. Release and revelation remain separate, deliberate steps of the existing A2 draft → release → A3 revelation path.

**The central constraint.** OD-18 makes the profile player-authored: only the character's live, in-effect controllers edit it, and controllers arrive with P03-B. A5 therefore has no production writer (D18). The application roles may `SELECT` the profile tables and cannot write them. Tests populate valid versions through one identified fixture helper.

**Three slices** (§13), in the A2b order, so that no commit has a copy path without its restriction:

| Slice | Content | Migration |
|---|---|---|
| **A5a** | Profile storage; the GM read routes; classification; grants that forbid application writes; the fixture helper | `147_character_player_profiles` |
| **A5b** | The `player_profile` origin and provenance on public-profile drafts and releases; the D7 restriction generalized per origin (withholding, the save rule, the release check) | `148_player_profile_provenance` |
| **A5c** | The copy command and route; `player_profile_copy` and `source_changed` in the public-profile GM read; the copy audit row | none |

**Gating.**

- A5 is optional for entry to A6.
- DEF-019 remains a prerequisite of A6, not of A5, and is not folded into A5.
- That deferral does not waive A5's own concurrency, atomicity, source-version, authorization or disclosure criteria. §10.5 states exactly what A5 inherits and what it must verify.

---

## 2. The approved requirements

These requirements come from accepted contracts and owner decisions.

1. **A separate, campaign-scoped profile** (OD-18, ADR 0021 §7).
   - It is distinct from world canon (`character.character_descriptions`) and from GM-private portrayal (`npc_portrayal_profiles`).
   - It grants no GM portrayal access and never reads GM-private fields.
   - Campaign notes, preferences and controller briefings never live in `character.character_descriptions` (§4.8).
2. **Editing** (OD-18 clarification, 2026-11-04).
   - Only the character's live, in-effect primary and co-controllers in that campaign edit it.
   - They edit through `character.edit_player_profile`, which only a control assignment confers (§2.5). It is never issued through `security.resource_grants` (§4.7).
   - Edits are versioned, attributed to the editing member, and re-authorized under lock (§2.8).
   - An edit in campaign A never changes A's world canon or campaign B's profile.
3. **Reading** (ADR 0021 §7; T82). Readable by that campaign's GMs (`canon.edit`) and by the character's live, in-effect controllers there (`character.view_player_profile`), and by nobody else.
4. **Publication.** A field is published only when explicitly selected, through its destination's workflow:
   - to campaign audiences, by an OD-17 revelation of a released version;
   - into world canon, only through OD-5 review.

   Nothing is published automatically. A5 implements only the campaign-audience destination. OD-5 is P03-C.
5. **Narrative and profile capabilities are distinct** (§2.5 table).
6. **The P03-A boundary** (R19 plan §5.1).
   - P03-A owns "the campaign-scoped player-profile storage and read".
   - P03-B owns `CONTROL_ASSIGNMENT_CAPABILITIES`, including `character.view_player_profile` and `character.edit_player_profile`, and the locking protocol.
7. **The publication mechanism exists.**
   - A2's draft carries per-field origins, and `player_profile` is reserved for A5 (P03-A plan §5.2; migration 142 docstring; DATABASE_MODEL).
   - A2b's restriction watermark and coverage rules (D7, D7-a–f) are the approved pattern for copied text.
8. **D13–D18** (owner-approved 2026-11-11, §4).

---

## 3. Boundary

**In A5:**

- storage scoped to (campaign, character), with immutable attributed versions;
- the GM-side reads (§8);
- GM-selected copying of one eligible field into the public draft, with `player_profile` provenance and the restriction (§9);
- use of the existing release and revelation.

**Not in A5:**

- **No production profile writer**, of any kind: player, GM, interim, administrative or import (D18).
- **No controller read or edit.** A5 adds no `character.view_player_profile` or `character.edit_player_profile` vocabulary, matrix entry or grant path. These belong to P03-B and T85.
- **No player publication approval.** The GM selects fields (D14). Nothing in A5 records, requests or implies a player's consent. A player opt-in is a possible later extension, **not approved scope**.
- **No private personal notebook.** `profile_notes` is a field shared with authorized GMs and eligible controllers (§5.2). Phase 16B/16C private notes and collaboration need separate storage and authorization, with no automatic GM access, and are not designed here.
- **No A6 portal work and no A7 preview.** The profile is never added to a preview adapter (§6.6).
- **No new mechanics.** Nothing calls the sheet, calculation or rules modules.
- **No control redesign.** No assignment table, lock or capability change.
- **No world-canon mutation.** `core.entities`, `character.character_descriptions` and `npc_portrayal_profiles` are never written, and OD-5 publication is not built.
- **No authorization from PC/NPC labels.** A profile may exist for any character kind. The read rule and the copy never consult `core.entity_types` (§8.2, §9.3). This differs deliberately from A2b's legacy copy, whose source rule is keyed by kind.
- **No absorbed fixes.** DEF-016, DEF-019, DEF-021 and the R01 stale-authorization follow-up stay where the backlog schedules them (§10.5, §12).

---

## 4. Approved decisions (owner-approved 2026-11-11)

These are the current rules. §4.8 keeps the proposal record.

### 4.1 D13: fields

**The profile has the eleven Phase 16A fields**, each a nullable text field of at most 4000 characters. That limit is `PUBLIC_PROFILE_TEXT_MAX_LENGTH`, so any copy fits a public field.

| Internal code | Field | Eligible for copy |
|---|---|---|
| `portrayal_guidance` | Portrayal guidance | yes |
| `personality` | Personality | yes |
| `ideals` | Ideals | yes |
| `bonds` | Bonds | yes |
| `flaws` | Flaws | yes |
| `goals` | Goals | yes |
| `fears` | Fears | yes |
| `loyalties` | Loyalties | yes |
| `boundaries` | Boundaries | **no** |
| `speech_patterns` | Speech patterns | yes |
| `profile_notes` | Profile notes. Future UI label: **"Notes for the GM and controllers"** | **no** |

**`boundaries` and `profile_notes` are excluded from every structured publication and copy operation.** They cannot be named by a copy request (422) and cannot be the origin of any public-profile field (database backstop, §6.3). This design does **not** promise to prevent manual transcription by an authorized reader (§5.3).

**Targets.** A copy writes one eligible field into one existing public text field chosen by the GM, either `public_appearance` or `public_background`. It replaces the whole target text, and the GM then edits it before release, as with the legacy copy. `public_summary` stays authored-only (D5-c, migration 146). No public-profile field is added.

### 4.2 D14: publication selection

- **The GM selects eligible fields for copying.** A caller may copy only when they pass both:
  - the D8 public-draft edit rule (effective character-scoped `canon.edit`);
  - the D15 profile read rule.
- **Copying publishes nothing.** Audiences see copied text only after a deliberate release by a reveal-authority holder **and** an OD-17 revelation. Those remain separate steps with their own authorization.
- **No player publication approval is implied.** A5 adds no consent state and no wording that suggests player approval.
- **A player opt-in is a possible later extension, not approved scope.**

### 4.3 D15: reads

- **A5's GM read requires effective character-scoped `canon.edit`.** That is D8's `has_effective_character_canon_edit`:
  - role `canon.edit` in the route campaign;
  - no whole-character deny (`campaign.view` on the character's `entity_id`);
  - no `canon.edit` deny on the character.
- **The approved deny rules apply.** A whole-character deny refuses the read for every source. A `canon.edit` deny on the character refuses this GM path (ADR 0021 §2.9; D8).
- **Reveal authority alone confers nothing here.** An `allow` grant of `canon.edit` on a character confers nothing either (D8).
- **OD-18's future independent controller path is preserved.** P03-B adds a second, independent path for the character's eligible, live, in-effect primary and co-controllers in the route campaign, through `character.view_player_profile` conferred by control. **`canon.edit` is not a prerequisite for that path.** A5's routes are therefore filtered by `campaign.view`, not `canon.edit` (§8.1), and A5's rule is written as the GM branch of a disjunction that P03-B extends (§8.2).
- **Denies for the controller path.** A whole-character deny applies to it too. Any operation-specific deny of `character.view_player_profile` is P03-B's to define, once that capability exists.

### 4.4 D16: copied text

**Per-field provenance and restriction watermarks** apply to the `player_profile` origin. The D15 read rule is its source rule.

- **Restriction.** Copied content stays restricted until a release covers its **current** content, by per-field coverage of the watermark.
- **Withholding.** Restricted content is withheld from public-draft readers who fail the source rule.
- **Release check.** A release that would include a field withheld from the releaser is refused.
- **Edits, clearing and recopying preserve the restriction.**
  - Every content change advances the watermark.
  - Clearing ends the lineage and leaves no text to disclose.
  - A recopy starts new restricted content.
- **No relabelling.** Provenance relabelling cannot bypass the restriction. The database refuses removing restricted provenance while text remains, and refuses any content change that does not advance the watermark.
- **The D7 companions apply as for legacy text:**
  - D7-a: a restricted caller may clear but not replace;
  - D7-c: coverage is per field;
  - D7-d: retries of an existing release survive loss of source permission;
  - D7-f: origin metadata may be disclosed, never text.

### 4.5 D17: classification

- **Class.** Profile text columns are `CHARACTER_VISIBLE`, with **explicit authorization rules** (§8.2). The classification itself grants no permission.
- **Every reader passes an explicit rule** in the query or command layer:
  - D15 for GMs;
  - P03-B's controller rule later.
- **Profile content never leaks** into audit rows, idempotency receipts, logs, exception messages, error bodies, metrics, or any response other than the authorized profile read (§6.5, §11.4).
- **ADR 0016 is unchanged.** `PLAYER_PRIVATE` stays reserved and unused.

### 4.6 D18: population before P03-B

- **No production profile writer.** The application database roles can `SELECT` the profile tables and cannot write them.
- **Tests populate valid versions** through one identified fixture helper (§11.1).
- **The public-draft copy and release commands stay within their own authorized scope.** They read the profile and write only the public-profile tables, under their existing authorization.
- **P03-B must deliver:**
  - the write privileges (grants);
  - the controller edit command;
  - attribution on every write (the editing membership);
  - versioning writes (head bump and version insert);
  - controller authorization under the ADR 0021 §2.8 lock protocol.

  A5's storage defines the shape those writes must satisfy. P03-B may extend it additively.
- **A5 is infrastructure,** not delivered profile-authoring functionality.

### 4.7 Where the approvals are recorded

- **Here**, §4.1–§4.6.
- **The P03-A plan's "Decisions still needed" section** (the D13–D18 line).
- **The R19 plan's OD-18 traceability row**, which records that the P03-A field list is decided.
- **The PLANv2 16A clarification** of "player notes" as `profile_notes`, distinct from the 16B/16C private notes.
- **BACKLOG R02**, where D15 settles the player-profile deny row.

### 4.8 Proposal record (2026-11-11, superseded by §4.1–§4.6)

The design as first committed (`d04ca57`) proposed D13–D18 with options. Recorded for history only.

| Decision | Proposed | Recommendation then | Approved |
|---|---|---|---|
| D13 | (a) the 16A list, (b) a smaller set, (c) one free-text field | (a), with `boundaries` and `player_notes` never publishable | (a), with the internal name **`profile_notes`** and the UI label "Notes for the GM and controllers"; no promise against manual transcription |
| D14 | (a) GM curates, (b) controller opt-in flag, (c) defer publication | (a) | (a). Opt-in is a possible later extension, not approved scope; no player approval implied |
| D15 | (a) effective character-scoped `canon.edit`, (b) role `canon.edit` only, (c) (a) plus reveal authority | (a) | (a), plus an explicit requirement to preserve the controller path without a `canon.edit` prerequisite |
| D16 | (a) the D7 restriction for `player_profile`, (b) no restriction | (a) | (a), including the edits, clearing, recopying and anti-relabelling guarantees |
| D17 | (a) `CHARACTER_VISIBLE`, (b) `PLAYER_PRIVATE` with an ADR 0016 amendment, (c) `GM_ONLY` then reclassify | (a) | (a), with "the classification grants no permission" and the no-leak rule |
| D18 | (a) no production writer, (b) defer A5 into P03-B, (c) an interim GM write route (rejected), (d) import (rejected) | (a) | (a), framed as infrastructure, with P03-B's deliverables listed |

---

## 5. Policy: what the profile holds and what it never holds

### 5.1 Player-supplied narrative versus GM-private material

| Concern | Player profile (A5) | GM-private material |
|---|---|---|
| Stores | The D13 fields | `character.character_descriptions.notes`, `npc_portrayal_profiles`, quest and event GM notes, public-profile drafts and `release_note` |
| Authors | Controllers (P03-B); nobody in production before then (D18) | `canon.edit` holders |
| Readers | GMs (D15) and eligible controllers (P03-B) | `canon.edit` holders (and world-private readers where applicable) |
| Class | `CHARACTER_VISIBLE` (D17) | `GM_ONLY` |

**Separation rules** (structural tests, §11.6):

- No profile response includes, joins or derives from a GM-private store. When P03-B serves the same projection to a controller, it can therefore leak nothing GM-private.
- No GM-private response includes profile text. The public-profile GM read shows only copied text that a GM selected, with its provenance.
- The profile modules never reference `character.character_descriptions`, `npc_portrayal_profiles`, the sheet, calculation or rules modules, `core.entity_types` or `core.entity_revisions`. They never call `capture_revision`.

### 5.2 `profile_notes`

- **What it is.** A character-profile field: notes the controllers write for the campaign's authorized GMs and the character's eligible controllers. Its future UI label is "Notes for the GM and controllers".
- **Who reads it.** Exactly the profile's readers. It is **not** a personal notebook and is not private from the GMs.
- **What it is not.** Phase 16B ("write private notes") and 16C (player-private collaboration) need separate storage and authorization, with **no automatic GM access**. They must not reuse this field or table.
- **Publication.** Like `boundaries`, it is excluded from structured copy and publication (§4.1).

### 5.3 What the exclusion does and does not guarantee

**It guarantees** that no copy, release snapshot or audience response obtains `boundaries` or `profile_notes` through the structured path:

- the request `Literal` (422);
- the database origin backstop (§6.3);
- the absence of any other path that reads the profile into a public-profile table.

**It does not prevent manual transcription.** An authorized reader can type what they read into a public field. That text is `authored` (the D7-b analogue) and follows the ordinary draft → release → revelation path. Product copy and documentation must not claim otherwise.

---

## 6. Storage

### 6.1 Migration `147_character_player_profiles` (A5a)

This is the revision after `146_public_profile_identity` (the current head). The id has 29 characters, under Alembic's 32-character limit. The migration is additive: it inserts only lookup rows, backfills nothing, and leaves every character without a profile.

**`campaign.player_profile_fields`**: a lookup table, not an ENUM (§11).

- Columns: `player_profile_field_id` (UUID PK, as in 142's origins lookup), `code` (unique), `display_name`, `description`, `is_copy_eligible BOOLEAN NOT NULL`, `sort_order` and timestamps.
- Seeded with the eleven D13 codes; `is_copy_eligible` is false only for `boundaries` and `profile_notes`.
- The `display_name` of `profile_notes` is "Notes for the GM and controllers".
- Its text columns are registered in `COLUMN_CLASSES` as 142 registered `campaign.public_profile_field_origins`.
- A unit test pins the codes, order and eligibility against `PLAYER_PROFILE_FIELDS` and `COPY_ELIGIBLE_PLAYER_PROFILE_FIELDS` in `domain/player_profiles.py`.

**`campaign.character_player_profiles`**: the head. It is a mutable record (§10.2) and the lock anchor ADR 0021 §2.8 names.

- `character_player_profile_id` UUID PK.
- `campaign_id` FK to `campaign.campaigns`, `ON DELETE RESTRICT`.
- `character_id` FK to `character.characters`, `ON DELETE RESTRICT`.
- `row_version BIGINT NOT NULL DEFAULT 1 CHECK (row_version >= 1)`, maintained by `core.bump_row_version()` (§26.3).
- `created_at`, and `updated_at` maintained by `core.set_updated_at()`.
- `UNIQUE (campaign_id, character_id)`, and `UNIQUE (character_player_profile_id, campaign_id, character_id)` as the target of composite FKs.
- `campaign_id`, `character_id` and `created_at` are immutable (`core.enforce_immutable_columns`).
- **No text columns.** Content lives only in versions.

**`campaign.character_player_profile_versions`**: append-only (§10.3); one row per profile state.

- `character_player_profile_version_id` UUID PK.
- `character_player_profile_id`, `campaign_id`, `character_id`: a composite FK to the head's triple. A version can therefore never name another campaign's or another character's profile.
- `profile_row_version BIGINT NOT NULL`, the head `row_version` this version made current, with `UNIQUE (character_player_profile_id, profile_row_version)`.
- The eleven D13 fields, each `TEXT NULL`, guarded by `char_length <= 4000` and a CHECK refusing whitespace-only text (empty is NULL).
- `edited_by_campaign_membership_id UUID NOT NULL`, FK to `security.campaign_memberships` with no action (as releases' `released_by_membership_id`).
- `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`.
- `UNIQUE (character_player_profile_version_id, campaign_id, character_id)`, the target of 148's provenance FKs.

**Triggers** (§20.4, local integrity only):

- **Scope** (both tables): the character belongs to the world of the campaign's timeline, and the editing membership belongs to the row's campaign. This follows `campaign.enforce_public_profile_scope()`.
- **Version consistency** (`BEFORE INSERT` on versions): `NEW.profile_row_version` equals the head's current `row_version`.
- **Head has its version**: a `DEFERRABLE INITIALLY DEFERRED` constraint trigger, `AFTER INSERT OR UPDATE` on the head. At commit, a version with `profile_row_version = row_version` must exist.
- **Immutability**: versions refuse UPDATE, DELETE and TRUNCATE.

**Grants, which enforce D18:**

- On the head and versions, revoke `INSERT`, `UPDATE`, `DELETE` and `TRUNCATE` from `app_read_write` and `integration_worker`. They keep `SELECT`.
- Revoke `ALL` from `app_read_only`.
- The lookup is `SELECT` only.
- P03-B's migration grants `INSERT` (head and versions) and `UPDATE` (head).

**Comments** (§31) go on every table, column and function. They say the profile is player-authored, campaign-scoped and never canon; that `profile_notes` is shared with GMs and controllers, not a private notebook; and that the application cannot write the tables until P03-B.

**Indexes.** The unique constraints cover the lookups and the head FK. Add an FK index on `versions (edited_by_campaign_membership_id)`.

**Entity references.** Register both `character_id` FKs as `BLOCKING` in `ENTITY_REFERENCE_CLASSIFICATION` ([entity_lifecycle.py](../src/dnd_ai/commands/entity_lifecycle.py)). A character with a profile is never physically deleted (ENTITY_LIFECYCLE §14).

**Classification.** Every profile text column is `CHARACTER_VISIBLE` in `COLUMN_CLASSES` (D17). The live-schema classification test covers them.

**Downgrade (guarded).**

- If any head or version row exists, the guard refuses and changes nothing. Player-authored content cannot be recreated.
- On an empty store, the downgrade drops the triggers, functions, tables and lookup.
- Alembic runs 148's downgrade first.

### 6.2 Who writes the store

**In A5, nothing in `src/` does.** Three things pin it:

- the grants;
- a structural test confining raw writes to the fixture helper (§11.1);
- a grant test that runs as `app_read_write`.

**P03-B's writer** must follow the ADR §2.8 protocol, which A5's helper mirrors:

1. World `FOR SHARE`, then the caller's membership and role rows, then the account, then the campaign.
2. The character's `core.entities` row `FOR SHARE`.
3. The caller's live, in-effect assignment row `FOR SHARE`, re-read under lock.
4. The head `FOR UPDATE`, or an `INSERT … ON CONFLICT (campaign_id, character_id) DO NOTHING` race.
5. A head `UPDATE` that bumps `row_version`.
6. A version `INSERT` with that `row_version` and the editor's membership.
7. Audit with field names only, and a receipt-only idempotency body (ADR 0016).

### 6.3 Migration `148_player_profile_provenance` (A5b)

This migration adds the `player_profile` origin to the public profile. It generalizes migrations 142–144's per-field rules from "legacy origin" to "restricted origin". Legacy behaviour is unchanged. The revision id has 30 characters.

**Lookup row.** Insert `player_profile` into `campaign.public_profile_field_origins`, sort 40, display "Copied from the player profile".

**Provenance columns,** on both `campaign.character_public_profiles` (drafts) and `campaign.character_public_profile_releases` (snapshots), for each of the two text fields:

- `public_<field>_origin_player_profile_version_id UUID NULL`, with a composite FK `(…version_id, campaign_id, character_id)` to `character_player_profile_versions (character_player_profile_version_id, campaign_id, character_id)`.
  - Under MATCH SIMPLE it is checked only when set.
  - A draft or release can cite only **its own campaign's profile of the same character**: database-level campaign isolation.
- `public_<field>_origin_player_profile_field_id UUID NULL`, FK to `campaign.player_profile_fields`.
- These deliberately do **not** reuse `public_<field>_origin_entity_row_version`. That column means the character's `core.entities.row_version` at a legacy copy, and reusing it would give it an incorrect second meaning.
- Partial FK indexes `WHERE … IS NOT NULL` on each version-id column.
- Classified `STRUCTURAL` and commented.

**Origin rule** (`campaign.enforce_public_profile_field_origins()`, `CREATE OR REPLACE`, on drafts and releases). Per field:

- the allowed codes are `authored`, `legacy_<field>` and `player_profile`;
- `legacy_<field>` exactly when `origin_entity_row_version IS NOT NULL` (unchanged);
- `player_profile` exactly when both player-profile columns are non-NULL; otherwise both are NULL;
- **a `player_profile` origin's field must have `is_copy_eligible = true`**, the backstop that keeps `boundaries` and `profile_notes` out;
- NULL text has the `authored` origin (unchanged).

**Watermark pairing.** Drop and re-add `ck_character_public_profiles_<field>_watermark_paired` as:

```sql
(restricted_row_version IS NULL)
  = (origin_entity_row_version IS NULL AND origin_player_profile_version_id IS NULL)
```

The positive and bounded CHECKs are unchanged.

**Watermark trigger** (`campaign.enforce_public_profile_restriction_watermarks()`, `CREATE OR REPLACE`). It keeps 144's body, with "restricted provenance present" now meaning `origin_entity_row_version IS NOT NULL OR origin_player_profile_version_id IS NOT NULL`:

- **INSERT** with restricted provenance: the watermark equals `row_version`.
- **UPDATE** with restricted provenance, when the text, origin, `origin_entity_row_version`, `origin_player_profile_version_id` or `origin_player_profile_field_id` changed: the watermark must equal `OLD.row_version + 1`.
- **UPDATE** with unchanged content: the watermark never decreases.
- **Relabel guard (I1):** if OLD has restricted provenance, NEW has none, and NEW's text is not NULL, refuse.

**Downgrade (guarded).**

- If any draft or release row has a `player_profile` origin or a non-NULL player-profile column, the guard refuses and changes nothing.
- Otherwise the downgrade:
  - restores 142's origin function, 143's paired CHECK and 144's watermark function body exactly;
  - drops the columns;
  - deletes the lookup row.

**Existing rows.** No row is rewritten, no `row_version` moves, and no audit row is written.

### 6.4 Concurrency tokens

- **Profile head:** `row_version`. It is the copy's source token (§9.3) and P03-B's edit token.
- **Public draft:** `row_version`, unchanged.
- **Release retry key:** unchanged. A release neither locks nor reads the profile.

### 6.5 Audit, receipts, logs and errors (D17)

- **A5a writes nothing.**
- **The A5c copy** writes one `audit.change_log` row (`copy_player_profile_field_to_public_profile_draft`) containing `source_field`, `target_field`, `origin: "player_profile"`, `player_profile_row_version` and the new draft `row_version`.
- **A save** of a `player_profile`-origin field records field names and the new `row_version`, as today.
- **Receipts** hold ids, versions, codes and flags (§9.3).
- **Exception messages, logs and error bodies** carry ids, codes and versions only. No message is built from profile or copied text.
- **None of these ever holds profile text.**

### 6.6 Previews, exports and reporting

- **Previews.** No preview adapter may admit the profile tables or the provenance columns. A test enumerates `PREVIEW_ADAPTERS` to prove it.
- **Reporting.** `app_read_only` has no access.
- **Export.** Phase 15 has no export path.

---

## 7. Lifecycle

| Event | Effect on the profile | Effect on reads and publication |
|---|---|---|
| Campaign archived | Rows retained | Every campaign route refuses through the existing lifecycle gate |
| Campaign physical deletion | Blocked by `ON DELETE RESTRICT` while a profile exists | n/a |
| Character archived | Rows retained | The GM read is still allowed. The copy gets 409 `public_profile_character_not_active`. Restoring the character re-enables it |
| Character non-canon, or not in the campaign's world | n/a | 404 on every A5 route |
| Character physical deletion | Blocked (`BLOCKING`) | n/a |
| Editor's membership ends | Versions keep `edited_by_campaign_membership_id` | The GM read still names the editor |
| GM's role revoked or expired, or membership ended | none | The next read or copy is refused: judged at the read, or re-checked under lock (§10) |
| Control revoked or replaced (P03-B) | **The profile survives.** It belongs to (campaign, character) | Editing ends with control. Under the approved contract a later controller reads the same profile, including earlier controllers' text and `profile_notes`. P03-B's UI must say so. This is a consequence, not an A5 decision |
| Same character in campaign B | B has its own head and versions | Nothing written in A is readable through B (§8.3). Provenance FKs forbid citing another campaign's profile (§6.3) |
| Campaign on a timeline branch | The campaign has its own profile; nothing is inherited across campaigns or branches | — |
| The profile changes after a copy | The draft keeps the copied text and its version provenance | The GM read flags `source_changed` (§9.6). A release publishes the copied text only |
| A release after a profile change or retraction | Releases are immutable | Audiences see the released text until a later release replaces it or the revelation is revoked. Withdrawal is a new release with the field cleared |

---

## 8. GM reads (A5a)

### 8.1 Routes

All routes sit under `/campaigns/{campaign_id}/characters/{character_id}/player-profile`. The route dependency is `require_campaign_capability("campaign.view")`, and the read rule runs in the query.

**Why `campaign.view`.** P03-B's controller read reuses these routes, and controllers need not hold `canon.edit` (D15). A caller who fails the rule gets the same non-disclosing 404 as for a missing profile, which is the public-profile GET's pattern.

| Route | Result |
|---|---|
| `GET …/player-profile` | 200 with the current profile, or `profile: null`, when the caller passes the read rule and the character is a canon character of the campaign's world. Otherwise 404 |
| `GET …/player-profile/versions/{profile_row_version}` | 200 with one immutable version. 404 for a non-reader, a non-numeric or out-of-range segment, or a missing version |

### 8.2 The read rule

`domain/player_profiles.py` defines the rule as a disjunction of independent branches:

```python
def may_read_player_profile(access, character_id) -> bool:
    # GM branch (A5, D15): effective character-scoped canon.edit.
    # The P03-B controller branch is added as a separate `or`; it must not require canon.edit.
    return may_read_player_profile_as_gm(access, character_id)


def may_read_player_profile_as_gm(access, character_id) -> bool:
    return has_effective_character_canon_edit(access, character_id)
```

- The rule is pure. It is judged from the request's `AccessContext` at the moment of the read, with no locks.
- It never consults the kind, a relationship type, reveal authority or a world role.
- Unit tests pin `may_read_player_profile_as_gm` to `has_effective_character_canon_edit`.
- A docstring and a test note state that P03-B's branch is independent of `canon.edit`.
- The copy (§9.3) checks `may_read_player_profile_as_gm` explicitly, because the copy is a GM operation. A future controller cannot copy, since it fails the D8 edit rule anyway.

### 8.3 Effective permissions, by caller

Route campaign A, character K in A's world.

| Caller | Source of authority in A5 | `GET` result |
|---|---|---|
| Built-in Campaign Owner | role `canon.edit` (migration 085) | 200 |
| GM | role `canon.edit` (086) | 200 |
| Assistant GM | role `canon.edit` (086) | 200 |
| Delegated reveal GM | role `canon.edit` through `gm`; the delegation confers nothing | 200 |
| Custom role carrying `canon.edit` | the union of role capabilities | 200 |
| Custom role with `access.manage` only | none | 404 |
| Player or observer | `campaign.view` only | 404 |
| A legacy relationship holder (`primary_controller`, `viewer`, …) | relationship capabilities never include `canon.edit` (ADR §2.5 item 5) | 404 |
| A holder of a revelation of K | discovery and the released public profile only | 404 |
| Any caller with a whole-character deny on K | denied | 404 |
| A `canon.edit` holder with a `canon.edit` deny on K | denied (D15) | 404, **including** an Owner or delegated GM who keeps reveal authority |
| A raw `allow` grant of `canon.edit` on K | confers nothing (D8) | 404 unless the caller has role `canon.edit` |
| World owner, editor, reviewer or reader without a membership of A | no campaign access | the existing campaign gate's non-disclosing refusal |
| A world role plus a GM membership of A | the campaign role | 200, through the campaign role only |
| Platform administrator without a membership of A | none | the existing campaign gate's refusal |
| GM of campaign B (same world, timeline and K) | B's roles do not apply in A | 404 through A's route; only B's own profile through B's route |
| An ended membership, or a revoked or expired role | none | the existing gate's refusal, or 404 |
| A live controller of K in A | **not in A5** (P03-B's independent branch) | 404 in A5 |

### 8.4 Responses: the explicit field sets

Responses carry exactly these keys, and tests assert exact key sets.

`GET …/player-profile`:

```json
{
  "character_id": "<uuid>",
  "character_active": true,
  "profile": null,
  "fields_catalog": [{"code": "personality", "label": "Personality", "copy_eligible": true}]
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
  "fields": {"portrayal_guidance": "…", "personality": null, "…": "…", "profile_notes": "…"}
}
```

- `fields` always has all eleven codes, with `null` for an empty field.
- `fields_catalog` lists all eleven in `sort_order`, with each field's label (`profile_notes`: "Notes for the GM and controllers") and copy eligibility.
- No membership ids, user ids, emails or account names appear.

`GET …/player-profile/versions/{n}` returns `character_id`, `profile_row_version`, `edited_at`, `edited_by` and `fields`.

### 8.5 Errors

- **Every refusal is the generic 404 body.** That covers a non-reader, a whole-character deny, a `canon.edit` deny, the wrong world, a non-canon character and a missing version. It never says whether a profile exists.
- **No new read error code** is introduced.
- **One statement.** The current profile is read in one statement that joins the head to its current version, so no mixed state is possible (race RA1).

---

## 9. Publication (A5b and A5c)

### 9.1 What changes in A2's model

- A draft field may now have the origin `player_profile`.
- **Source rules, per origin:**
  - legacy origins use `may_read_legacy_source` (by kind, D7-e), unchanged;
  - `player_profile` uses `may_read_player_profile` (D15; in A5 its only branch is the GM branch).
- **Restricted** is unchanged: the field has text, a restricted origin, and no covering release.
- **Withheld is now per field.** A restricted field is withheld from a caller who fails that field's origin's source rule.
  - Today `withheld_fields` applies one kind-based rule to all restricted fields ([public_profile_restrictions.py](../src/dnd_ai/queries/public_profile_restrictions.py)).
  - A5b groups restricted fields by origin, and resolves world authority only when a legacy NPC field needs it.
- **D7's invariants I1–I7 hold for `player_profile`** (P03-A plan §9.2), with "legacy origin" read as "restricted origin" and the provenance pair as in §6.3:
  - I2: every content change advances the watermark;
  - I3: other fields leave it alone;
  - I4: coverage means the released text is the current text;
  - I6: clearing ends the lineage;
  - I7: no request names an origin, version or watermark.

### 9.2 Save and release (A5b)

These are A2b-1's rules, generalized. Nothing changes for legacy or authored fields.

| Operation | Behaviour with a `player_profile` field |
|---|---|
| Save, field omitted | Untouched; watermark unchanged (I3) |
| Save, explicit `null` | Clears it: text NULL, origin `authored`, the provenance pair and watermark NULL (I6). Allowed even when withheld (D7-a analogue) |
| Save, text, field not withheld | Written. Origin and provenance kept; the watermark advances to the new `row_version` (I2) |
| Save, text, field withheld | 403 `public_profile_field_withheld` for the whole request, after the token check and before the no-op comparison |
| Release, new snapshot | 403 `public_profile_field_withheld` if any field at that draft version is withheld from the releaser. Otherwise the snapshot carries each field's origin and provenance pair, and covers every field whose watermark is at or below its version |
| Release, natural retry or keyed replay | Returns the existing release with no source check (D7-d). The reveal-authority pre-check and the whole-character deny still apply |

**No lock change.** Every release takes the draft `FOR UPDATE`, so the set of releases a save or release sees is fixed. The profile rule is pure on the re-resolved `AccessContext`. The deny that changes it arrives only through `create_resource_grant`, which conflicts with the membership `FOR SHARE` both commands hold (P03-A plan §5.7a).

### 9.3 The copy (A5c)

**Route.** `POST /campaigns/{campaign_id}/characters/{character_id}/public-profile/draft/copy-player-profile`, with `Idempotency-Key` supported.

**Request** (`BaseAuthoringRequest`; extra fields are refused):

| Field | Type | Meaning |
|---|---|---|
| `expected_row_version` | `int ≥ 1` or `null` | The public draft version the caller read; `null` means there is no draft yet |
| `expected_player_profile_row_version` | `int ≥ 1` | The profile version the caller read: the **source token** |
| `source_field` | `Literal[` the nine eligible codes `]` | 422 for `boundaries`, `profile_notes` or an unknown code |
| `target_field` | `Literal["public_appearance", "public_background"]` | 422 otherwise |

**Route pre-check.** It runs before the idempotency lookup (DATABASE_CONVENTIONS §26.4):

1. the D8 edit rule (`require_may_edit`): 403 `public_profile_edit_denied` if the caller can still read the draft, otherwise 404;
2. `may_read_player_profile_as_gm`: 404.

In A5, (2) is implied by (1); a unit test pins the implication. A caller who has lost either right cannot replay a stored copy, because the source read is the copy's own authority.

**Command** `copy_player_profile_field_to_public_profile_draft`, in one transaction:

1. `lock_authoring_scope(world_capability=None)`: world `FOR SHARE` → the caller's role rows and membership `FOR SHARE` → account → campaign `FOR KEY SHARE` → role `canon.edit` re-checked from committed state.
2. Re-resolve the `AccessContext`. Apply the D8 edit rule and the GM read rule again.
3. Take the character's `core.entities` row `FOR SHARE`.
   - Not canon, or not in the world: 404.
   - Archived: 409 `public_profile_character_not_active`.
4. Take the profile head `FOR SHARE`, selected by (route campaign, character).
   - None: 409 `player_profile_missing`.
   - Its `row_version` differs from `expected_player_profile_row_version`: 409 `player_profile_source_changed`.
5. Read, in a separate statement, the immutable version with `profile_row_version = expected`. If its `source_field` is NULL: 409 `player_profile_field_empty`.
6. Take the public draft `FOR UPDATE`, or win the `INSERT … ON CONFLICT DO NOTHING` race.
   - A missing draft for a non-null token: 409 `public_profile_draft_missing`.
   - A moved token or a lost insert race: 409 `stale_write`.
7. Write the target field:
   - the text;
   - origin `player_profile`;
   - the provenance pair;
   - `origin_entity_row_version` NULL;
   - watermark = the new `row_version` (1 on insert).

   The write always changes the draft, even for identical text (I2). The other field and `public_summary` are untouched.
8. The route writes the audit row (§6.5) and finishes idempotency with a receipt. P3 commits before the response.

**Response and stored receipt:** `character_public_profile_id`, `character_id`, `row_version`, `created`, `changed: true`, `player_profile_row_version`, `source_field`, `target_field`. Never any text. 201 if the copy created the draft, else 200.

**Fingerprint:** `{"character_id": str(character_id), **body}`.

**New error codes** (safe messages, no content). They are reached only after the read rule passes:

| Code | Message |
|---|---|
| `player_profile_missing` (409) | "This character has no player profile in this campaign." |
| `player_profile_source_changed` (409) | "The player profile changed. Reload it and try again." |
| `player_profile_field_empty` (409) | "That player-profile field is empty." |

### 9.4 The public-profile GM read (A5b and A5c)

- **Draft fields (A5b).** `<field>_origin` may be `player_profile`. Each text field gains:
  - `<field>_origin_player_profile_version`: an int or null; the copied head `row_version`, never the UUID;
  - `<field>_origin_player_profile_field`: a code or null;
  - `<field>_player_profile_source_changed`: a bool or null. True when the copied field's text in the cited version is distinct from that field in the current version. It is computed only for a caller who passes the GM read rule and is `null` otherwise, because it derives from text that caller may not read.
- **Withheld fields** (D7-f analogue). `text: null` and `withheld: true`, plus the origin code, version number and source field code. Never text and never `source_changed`.
- **Releases in the GM read** gain the same provenance numbers and codes.
- **`player_profile_copy` (A5c).**
  - It is `null` unless the character is active, the caller passes the edit and GM read rules, and a profile exists.
  - Otherwise it is `{"player_profile_row_version": n, "fields": {"<eligible code>": <has text>}}`: the source token and booleans only, for the nine eligible fields.
- **The audience tier is unchanged.**
  - `read_released_profile` and `_RELEASED_PROFILE_SQL` select only released text, species and size ([character_public_profile.py](../src/dnd_ai/queries/character_public_profile.py)).
  - No origin, provenance, version or profile id reaches an audience response.
  - The existing unit test that pins the audience SQL stays unchanged.

### 9.5 Edit, clear and recopy

| Action on a `player_profile` field | Result |
|---|---|
| A GM edits it down to an excerpt | Origin and provenance are kept and the watermark advances. The field stays restricted until a covering release |
| The excerpt is released, then source text is appended | The field is restricted again (I2/I4). The release still shows only the excerpt. A release by a restricted releaser gets 403 |
| The field is edited back to exactly the released text | Restricted until released again: an accepted over-restriction |
| Clear | The lineage ends (I6). A restricted caller may clear (D7-a analogue) |
| Copy again, from the same or a newer version | New restricted content at a new watermark, even after a covering release |
| Copy over a legacy-origin field, or the reverse | Origin and provenance switch and the watermark advances. The relabel guard permits it, because NEW still has restricted provenance |
| A GM types text they read in the profile | Authored text (the D7-b analogue, accepted). Manual transcription is not prevented (§5.3) |

### 9.6 Source changes

| When the profile changes | Effect |
|---|---|
| While a copy waits on the head | The copy sees the new `row_version`: 409 `player_profile_source_changed` (race C1) |
| After a copy, before release | The draft keeps the copied text and its citation. The GM read shows `source_changed: true` when that field's text differs. The release is not blocked; it is the GM's review step |
| After release | The release is unchanged. Audiences keep the released text until a later release. The GM read flags the change |

Blocking a release while the source has changed is a possible later owner question. It is not A5 scope.

### 9.7 Retries

| Situation | Outcome |
|---|---|
| Copy retried with the same key, still permitted | The stored receipt; nothing written |
| Copy retried with the same key after losing the GM read or the edit rule | The pre-check refuses with 403 or 404 before the lookup. No replay |
| Copy retried without a key | Runs afresh. With the old draft token: 409 `stale_write` |
| A refused copy retried with the same key | Runs afresh. Refusals store nothing |
| Release of a `player_profile` field retried after the releaser lost the GM read | The receipt, or 200 `created: false` (D7-d). Refused only by the reveal pre-check or a whole-character deny |
| Same key and same body on a different character | The non-disclosing idempotency 409 |

---

## 10. Concurrency

### 10.1 Lock orders

The A1 design §3 table and P03-A plan §5.8 and §9.6 gain one row, and none is reversed.

| Command | Locks, in order |
|---|---|
| `copy_player_profile_field_to_public_profile_draft` (A5c) | `lock_authoring_scope` (world S → role rows and membership S → account S → campaign KEY SHARE) → role re-check → `AccessContext` re-resolve → character entity S → **profile head S** → version read (no lock; immutable) → public draft U, or the unique-index wait |
| Save, release | Unchanged (§9.2) |
| P03-B profile edit (reference) | ADR §2.8: world S → membership and roles → account → campaign → entity S → assignment row S → profile head U |

**Pairwise:**

- **Copy against save or release.** As A2b's copy: the draft row orders them, and neither takes the head.
- **Copy against a profile edit (P03-B, or A5's fixture helper).** The copy holds the head S and next waits only for the draft, which an edit never takes. The edit waits for the head U while holding only locks the copy does not request in a conflicting mode. No cycle.
- **Copy against control revocation (P03-B).** Revocation takes the target membership U, then the campaign U, the user and the entity U. The copy takes the campaign `KEY SHARE` before the entity. Revocation waits at the campaign holding nothing the copy wants next. No cycle.

### 10.2 Fresh authorization after waits

- **The copy** re-checks the role inside `lock_authoring_scope` after its waits, re-resolves the `AccessContext`, and judges D8 and D15 on it, as every authoring write does.
- **The release** keeps its DEF-013 fresh-instant re-check.
- **Reads** are judged at the moment of the read.

### 10.3 Transactions, receipts and audit

- **One transaction per request.** The business write, the audit row and the idempotency receipt commit together in the request transaction.
- **P3 commits before the response.** A commit-time failure answers 5xx with nothing persisted.
- **Refusals.** A refusal stores no receipt and writes no audit row.
- **A5a** has no write.

### 10.4 Races A5 must verify

These are **real HTTP races** through `TestClient` and the real routes, using `tests/lock_race_support.py` (`LockRace`, `Hold`, `Pause` and the corrected `Budget`) and request-specific blocker observation (`pg_blocking_pids`). Command-only races do not substitute.

Each race runs in both orders where an order exists, and asserts all of:

- the status codes, and no SQLSTATE 40P01 (except in §10.5's KA rows);
- the draft row: `row_version`, text, origin, provenance pair and watermark;
- the release rows;
- audit row counts and receipt presence;
- no business write, audit row or receipt for a loser.

**The profile-edit side** is the §11.1 fixture helper running the P03-B write shape in its own transaction. It stands in for a writer that does not exist yet, and is the only non-HTTP party.

| # | Slice | First | Second | Expected |
|---|---|---|---|---|
| RA1 | A5a | Helper edit holds the head U (uncommitted) | `GET …/player-profile` | 200 with the previous complete version. After commit, the new one |
| R1 | A5b | Release (unkeyed) of a draft with an uncovered `player_profile` field by a reveal holder | `canon.edit` deny on that releaser on K, through the real grant route | Release first: the grant waits and the release commits (201). Grant first: the release re-resolves and gets 403 `public_profile_field_withheld`; nothing written |
| R2 | A5b | A permitted GM edits a released `player_profile` field | A restricted releaser releases the earlier version | 409 `stale_write`, 200 `created: false`, or a release of the earlier text only. Afterwards the field is withheld from the restricted reader |
| C1 | A5c | Helper profile edit | Copy (**keyed**) naming the old profile version | Edit first: 409 `player_profile_source_changed`; nothing written; no receipt. Copy first: the edit waits, the copy commits citing the old version, the edit commits, and the GM read shows `source_changed: true` |
| C2 | A5c | Revocation of the copier's GM role | Copy (unkeyed) | Revoke first: a non-disclosing refusal. Copy first: the revoke waits and the copy commits |
| C3 | A5c | `canon.edit` deny on the copier on K, through the real grant route | Copy (unkeyed) | Grant first: 403 `public_profile_edit_denied` or 404. Copy first: the grant waits and the copy commits |
| C4 | A5c | End of the copier's membership | Copy (unkeyed) | They serialize at the membership. End first: the copy is refused. Copy first: the end waits |
| C5 | A5c | Public-draft save (keyed) | Copy (keyed, different key), same draft token | The second gets 409 `stale_write`, in both orders. Verifies the copy forms no cycle with keyed authoring routes that take no campaign `FOR UPDATE` |
| C6 | A5c | Release of draft version *n* (keyed) | Copy (keyed) with token *n* | Both commit in either order. The release holds the pre-copy text. The copy's field is restricted and uncovered |
| C7 | A5c | Archive of K | Copy | Archive first: 409 `public_profile_character_not_active`. Copy first: the archive waits on the entity |
| C8 | A5c | Copy with key K | The same copy, same key and body, concurrently | One executes. The other waits on P2's key lock, then gets the stored receipt. Exactly one draft change and one audit row |

### 10.5 Inherited behaviour, stated exactly

**DEF-019 (keyed reservation cycle; scheduled before A6, not fixed by A5).**

- **The mechanism.** A keyed copy or release reserves its key before its command locks, and the reservation's foreign key takes the campaign row `FOR KEY SHARE`.
- **The cycle.** Against a command that holds a membership or role row `FOR UPDATE` and then needs the campaign `FOR UPDATE`, that is the P03-A plan's K3/K4 and K10–K12 cycle (§10.8.6). Three such commands are:
  - ending the caller's membership;
  - revoking or changing the caller's role;
  - a resource grant naming the caller.
- **The consequence.** One request may be aborted with SQLSTATE 40P01.
- **Not A5-specific.** The same exposure exists today for A2's keyed save, legacy copy and release.
- **A5 does not move the copy's reservation** (A3's step-0 pattern). That would fix one route of DEF-019 ad hoc.

**What A5 still verifies under that inherited cycle** (A5c; the KA tests). The deferral does not waive atomicity or authorization.

| # | First | Second | Required, whichever outcome occurs |
|---|---|---|---|
| KA1 | End of the copier's membership | Copy (keyed) | **Allowed outcomes:** serialized in either order, as C4; or one request aborted by 40P01. **Required:** a copy never commits after the authority loss committed; every 2xx corresponds to committed state (P3); a non-2xx loser leaves no draft change, audit row or receipt; the test records which outcome occurred and must not require a deadlock |
| KA2 | Revocation of the copier's GM role | Copy (keyed) | The same |
| KA3 | `canon.edit` deny on the copier, through the real grant route | Copy (keyed) | The same |
| KA4 | `canon.edit` deny on a releaser of an uncovered `player_profile` field | Release (keyed) | The same, with the release's withheld rule in place of the copy's edit rule |

**Also inherited and not verified as corrected by A5:**

- **R01 / DEF-015 F-1, time-based expiry.** A role whose `expires_at` lapses during a lock wait is judged as `lock_authoring_scope` judges it for every authoring write. A5 adds no fresh-instant re-check for `canon.edit`. A5 verifies explicit revocation (C2, KA2), not expiry during a wait.
- **DEF-016.** The `canon.edit`-under-`character_id` pattern in the view-tier and inventory resolvers. A5 does not use or change it; A5 uses `has_effective_character_canon_edit`.
- **DEF-020 and DEF-021.** No A5 command takes the campaign `FOR UPDATE`, and recovery is untouched, so A5 adds no instance of either.
- **Retained A3/A4 harness findings:** best-effort thread cleanup after join timeouts, fixed-budget waits, the undiagnosed triple-runner migration failure, process freezes. A new A5 race flake is reported with its run, not retried away.

**Not inherited:** everything else in §10.4. A5 must meet those criteria itself.

---

## 11. Tests

### 11.1 The fixture helper (A5a)

`tests/player_profile_support.py`:

- `seed_player_profile(engine, *, campaign_id, character_id, editor_membership_id, fields)` creates a profile;
- `edit_player_profile(...)` adds a version.

Both run as the test superuser, in one transaction each, following the §6.2 order (minus the assignment row, which P03-B introduces), and satisfy every trigger. **This is the only raw writer of the profile tables.** A structural test confines raw writes to this module. P03-B replaces its production role with the controller command.

### 11.2 Reader matrix (A5a)

Every §8.3 row runs through the HTTP routes. Roles, grants and denies are created through the application, with denies made through A2a-R's route. Each row asserts:

- the status code;
- the exact response key set;
- for a 404, the generic body, byte-identical to the not-found response for a character with no profile.

### 11.3 Campaign isolation (A5a–A5c)

Campaigns A and B share one world, one timeline and character K. One account is GM in both; another is GM in B only.

- K has profiles in A and B with distinct markers. Each route returns only its own campaign's profile.
- With a profile only in A:
  - B's GET returns `profile: null` to B's GM and 404 to non-readers;
  - B's copy returns 409 `player_profile_missing`.
- A raw-row attempt to give B's draft or release a provenance pair citing A's version is refused by the composite FK.
- A copy, release and revelation in A change nothing in B's draft, releases or audience responses, or in B-filtered audit.

### 11.4 Disclosure (D17)

**Markers.** Every profile field carries a distinct marker, per campaign. The `boundaries` and `profile_notes` markers may appear only in the A5a GM read for a reader.

**Surfaces swept:**

- every surface of the A2a, A2b and A4 marker sweeps;
- the new routes;
- every 403, 404, 409 and 422 body;
- every stored receipt;
- the audit history;
- the audience tier (A4 detail, browse and search);
- **captured logs**: `caplog` over the copy, save, release and read flows at DEBUG.

**Callers:** player, observer, B's GM, a GM with a `canon.edit` deny on K (also when they hold reveal authority), a world-role-only account, and an assistant GM after role revocation.

**Assertions:**

- No body or log line for those callers contains a profile marker.
- No log line from any flow contains a profile marker.
- After copy, release and revelation, audience bodies contain exactly the released excerpt's markers.
- No audience body contains `player_profile`, a profile version number or a profile id.
- The `boundaries` and `profile_notes` markers never appear in a public-profile draft, release, receipt, audit row or audience response produced through any structured operation.

### 11.5 Publication and lifecycle (A5b, A5c)

- **The excerpt regressions** of P03-A plan §9.8 (copy, excerpt, release, append, restore, restore-to-released), for a `player_profile` origin. A5b seeds the copies; A5c runs them through the real copy.
- **Edit behaviour.** Unchanged-field visibility, mixed-field atomic refusal, clear, recopy, stale writes (a stale token comes before 403), and every §9.5 row.
- **Anti-relabelling** (raw SQL, refused by the database):
  - moving a `player_profile` field to `authored` while keeping its text;
  - changing its text without advancing the watermark;
  - lowering a watermark;
  - pointing a `player_profile` origin at `boundaries` or `profile_notes`.
- **Copy rules, allowed:** owner, GM, assistant GM, custom `canon.edit`.
- **Copy rules, refused:**
  - a player: 404;
  - a `canon.edit` deny: 403 or 404;
  - a whole-character deny: 404;
  - an archived character: 409;
  - no profile: 409 `player_profile_missing`;
  - an empty field: 409 `player_profile_field_empty`;
  - a stale profile token: 409 `player_profile_source_changed`;
  - a stale draft token: 409 `stale_write`;
  - a missing draft with a token: 409 `public_profile_draft_missing`;
  - `boundaries`, `profile_notes`, an unknown field or target, or an extra field: 422.
- **Kinds.** The copy behaves identically for `npc`, `player_character` and plain `character`.
- **Retries.** Every §9.7 row.
- **Rollback.** A copy forced to fail at commit (P3's test-only deferred-trigger technique) leaves no draft change, audit row or receipt, and answers 5xx.
- **T82, the player-profile clause, end to end:**
  1. a profile in A;
  2. copy `personality` to `public_background`;
  3. edit it to an excerpt;
  4. release;
  5. a `campaign_current` revelation.

  A player in A sees only the excerpt. B, and an A observer outside the audience, see nothing.

### 11.6 Schema, migration and structure

**Migration 147:**

- up, down, up, and `alembic check`;
- the downgrade guard refuses when any profile row exists and changes nothing;
- positive and negative tests for every CHECK and trigger, including that the deferred head-has-version trigger fails at COMMIT;
- grants as `app_read_write`, `integration_worker` and `app_read_only`;
- comments, the FK index, and `migration_owner` ownership.

**Migration 148:**

- up, down, up;
- the downgrade guard;
- origin-trigger acceptance and refusal per field and code, including the ineligible fields;
- the new paired CHECK;
- every watermark-trigger rule for both restricted provenances;
- the generalized relabel guard;
- **every existing 143/144 watermark test passes unchanged at head**;
- existing authored and legacy rows untouched, with no audit row.

**Schema drift.** `alembic check`, and `COLUMN_CLASSES` covers every new column.

**Structure:**

- no `src/` writer of the profile tables;
- the profile modules reference no GM-private store, `character_descriptions`, rules or sheet module, or `entity_types`;
- `_RELEASED_PROFILE_SQL` unchanged;
- `PREVIEW_ADAPTERS` admit no profile column;
- the route manifest gains three routes;
- `test_world_gate_registry.py`'s `EXPECTED_CAMPAIGN_ONLY_SCOPES` gains the copy command's `lock_authoring_scope(world_capability=None)` call site;
- `ENTITY_REFERENCE_CLASSIFICATION` covers both new `character_id` FKs;
- the domain constants match the lookup.

**Unit:**

- the GM branch equals `has_effective_character_canon_edit` over a synthetic `AccessContext` matrix;
- the edit rule implies the GM read rule;
- the per-origin source-rule dispatch;
- `field_is_restricted` over synthetic histories for both restricted origins.

### 11.7 Regression boundary

**Run unchanged at each slice boundary:**

- `test_character_public_profile_*.py`;
- `test_public_profile_identity_*.py`;
- `test_character_revelations_*.py`;
- `test_character_reveal_delegation*.py`;
- `test_data_classification_schema.py`;
- `test_request_transaction.py`;
- the P0/P1 lock suites.

**Then the full suite** with the four-shard runner (`uv run python scripts/run_sharded_tests.py`). It applies DEVELOPMENT §6.2's configuration isolation itself; report it as "defaults, `.env` override removed". Each shard uses its own disposable PostgreSQL 18 cluster. Report reruns separately.

---

## 12. Dependencies and open defects

| Item | A5 impact | Disposition |
|---|---|---|
| **DEF-019** | The A5c copy is a keyed authoring route with A2's exposure (§10.5) | Not folded into A5; scheduled before A6. Add the copy route to its R01a inventory. A5 still verifies KA1–KA4 atomicity and authorization |
| **DEF-021**, **DEF-020** | None | Unchanged |
| **R01 / DEF-015 F-1** | Expiry during a wait is the shared gap (§10.5) | Not absorbed |
| **DEF-016** | Not used by A5 | R02 |
| **R02** | D15 settles the player-profile row: a whole-character or `canon.edit` deny on the character refuses the GM read and the copy | Recorded in BACKLOG R02 |
| Retained A3/A4 harness findings | Inherited (§10.5) | Not fixed here |
| **P03-B** | Must deliver the write grants, the controller edit command, attribution, versioning writes, the controller read branch (no `canon.edit` prerequisite) and the controller authorization under §2.8; and decide any `character.view_player_profile` deny semantics | A5 must not pre-empt any of it |
| **Phase 16B/16C** | Private notes and collaboration need separate storage and authorization, with no automatic GM access | Not designed here |
| **A6** | Does not need A5 | DEF-019 first |

**Remaining design conflicts:** none known. The approvals are consistent with:

- ADR 0021 §7 ("GMs (`canon.edit`)": D15);
- ADR 0016 (`CHARACTER_VISIBLE`, with `PLAYER_PRIVATE` still reserved: D17);
- PLANv2 16A ("player notes" is clarified as `profile_notes`, distinct from 16B/16C).

---

## 13. Slices and acceptance criteria

The decisions are approved, so the slices are gated only by order and review: A5a, then A5b after A5a's review, then A5c after A5b's review.

### A5a: storage and the GM read (infrastructure)

**Code:**

- migration 147 (§6.1);
- the table metadata in `persistence/tables/campaign.py`;
- `domain/player_profiles.py` (field constants, `may_read_player_profile` with its GM branch);
- `queries/player_profiles.py`;
- `api/player_profiles.py`, registered in `create_app`;
- `COLUMN_CLASSES` and `ENTITY_REFERENCE_CLASSIFICATION` entries;
- `tests/player_profile_support.py`.

**Acceptance:**

1. The new tests fail at the parent.
2. §11.2.
3. §11.3 for reads.
4. §11.4 for the new routes and logs.
5. The §11.6 migration-147 and structure items.
6. RA1.
7. The application roles cannot write the profile tables.
8. Every pre-existing test passes unchanged.

### A5b: provenance and restriction, before any copy exists

**Code:**

- migration 148 (§6.3);
- the per-origin source-rule dispatch in `domain/public_profiles.py` and `queries/public_profile_restrictions.py`;
- the §9.2 save and release changes;
- the §9.4 draft and release fields (no `player_profile_copy` yet).

**Tests.** `player_profile`-origin draft fields are seeded through a helper that satisfies 148's trigger and CHECKs. It is the only raw seeding of drafts, and A5c replaces it.

**Acceptance:**

1. The §11.5 excerpt, mixed, clear, unchanged-field, stale and anti-relabelling cases on seeded copies.
2. R1 and R2.
3. The §11.6 migration-148 items.
4. §11.7, with every A2b test unchanged.

### A5c: the copy

**Code:**

- the command and route (§9.3);
- the three error codes;
- `player_profile_copy` and `source_changed` in the GM read;
- the audit row;
- the idempotency command name.

**Acceptance:**

1. The §11.5 copy rules, kinds, retries and rollback.
2. The excerpt regressions through the real copy.
3. T82 end to end.
4. §11.3 and §11.4 in full.
5. C1–C8.
6. KA1–KA4.

### Every slice

- Checks: `ruff format --check`, `ruff check`, `mypy src`, `uv lock --check`, `alembic upgrade head` and `alembic check` on a disposable PostgreSQL 18 database, and `git diff --check`.
- The focused tests, then the four-shard full run.
- One local commit per slice, with explicit paths.
- Stop for independent review naming the parent and target SHAs.
- No push or PR unless the owner asks.

---

## 14. Documentation the implementation updates in the same commits

| Document | Change | Slice |
|---|---|---|
| `DOMAIN_MODEL` | Player profile (campaign-scoped, player-authored, never canon); profile version; copy-eligible field; `profile_notes` (shared with GMs and controllers, not a private notebook); the `player_profile` origin; the per-origin source rule | A5a, A5b |
| `architecture/DATABASE_MODEL` | The tables, triggers and grants (147); the provenance columns and replaced functions (148); the existing "`player_profile` is added by A5" line made current | A5a, A5b |
| `PHASE13E_ACCESS_CONTRACT`, `api/ACCESS_CONTROL` | The GM read rule and routes; the reserved independent controller branch; per-origin withholding; the copy route; the three error codes | A5a–A5c |
| `ENTITY_LIFECYCLE` command list | The copy command | A5c |
| This design | An implementation record per slice | each |
| P03-A plan status, PLANv2 15H, PROJECT_STATUS, BACKLOG P03-A row | Slice state, described as infrastructure until P03-B | each |

---

## 15. Implementation prompt (Claude Code Sonnet 5.5, Medium)

> Use verbatim. Replace `<SLICE>` with A5a, A5b or A5c. Start A5b only after A5a's independent review, and A5c only after A5b's.

```text
You are implementing P03-A slice <SLICE> of the D&D AI World Platform, a persistent-world RPG
platform (Python 3.12, FastAPI, SQLAlchemy 2 Core, psycopg 3, PostgreSQL 18, Alembic, pytest).
Work in the existing repository C:\Users\nemes\dnd_ai on branch phase15/completion. Do not create
a branch, clone or worktree. Do not push, open a PR, rebase, amend, reset, stash or force anything.
Preserve any unrelated working-tree changes; stage only your own files by explicit path.

Authoritative design (approved; no owner decision is open):
docs/PHASE15_P03A_A5_PLAYER_PROFILE_DESIGN_2026-11-11.md.
Read §1–§5 in full (the decisions in §4 are binding). Then read the sections for <SLICE>:
  A5a: §6.1, §6.2, §6.5, §6.6, §7, §8, §10.1–§10.4 (RA1), §11.1–§11.4, §11.6, §11.7, §13, §14
  A5b: §6.3, §9.1, §9.2, §9.4, §9.5, §10.4 (R1, R2), §11.4, §11.5, §11.6, §11.7, §13, §14
  A5c: §9.3–§9.7, §10 (all, including §10.5 KA1–KA4), §11, §13, §14
Also read CLAUDE.md; docs/PHASE14_15_P03A_IMPLEMENTATION_PLAN_2026-11-06.md §5.5–§5.9 and §9 (the
A2/A2b patterns you extend); and the existing code you extend: src/dnd_ai/domain/public_profiles.py,
src/dnd_ai/queries/public_profile_restrictions.py, src/dnd_ai/queries/character_public_profile.py,
src/dnd_ai/commands/character_public_profile.py, src/dnd_ai/api/character_public_profile.py,
database/migrations/versions/142_* to 146_*, tests/lock_race_support.py and the existing
tests/database/test_character_public_profile_*.py. Follow their patterns exactly:
lock_authoring_scope; AccessContext re-resolve under lock; require_may_edit; route pre-checks
before start_campaign_idempotency; character_id in the idempotency fingerprint; audit written in
the route; receipts only.

Binding rules:
- A5 is infrastructure. No production writer of campaign.character_player_profiles or
  campaign.character_player_profile_versions: application roles get SELECT only; tests write them
  only through tests/player_profile_support.py.
- Fields (D13), internal codes exactly: portrayal_guidance, personality, ideals, bonds, flaws,
  goals, fears, loyalties, boundaries, speech_patterns, profile_notes. boundaries and
  profile_notes are never copy-eligible (request Literal and database backstop). profile_notes'
  display name is "Notes for the GM and controllers". Do not claim manual transcription is
  prevented.
- Reads (D15): GM branch = has_effective_character_canon_edit. Write may_read_player_profile as a
  disjunction whose only A5 branch is the GM branch, documented so P03-B adds an independent
  controller branch WITHOUT a canon.edit prerequisite. Reveal authority confers nothing. Routes
  are filtered by campaign.view; every refusal is the generic 404.
- No character.view_player_profile / character.edit_player_profile vocabulary (P03-B).
- Never authorize from character kind or relationship labels in A5 code.
- Classification (D17): CHARACTER_VISIBLE; it grants nothing by itself. Profile or copied text
  never appears in audit rows, receipts, logs, exception messages or error bodies.
- Provenance (D16): never reuse public_<field>_origin_entity_row_version for player-profile
  provenance; the watermark must advance on every content change; the database must refuse
  relabelling restricted provenance while text remains.
- Leave _RELEASED_PROFILE_SQL and the audience tier unchanged.
- Do not fix DEF-016, DEF-019, DEF-021 or R01 stale authorization; do not move the copy's
  idempotency reservation. A5c's KA1–KA4 tests must accept either a serialized outcome or a 40P01
  loser, must never require a deadlock, and must assert no copy/release commits after a committed
  authority loss and that every non-2xx loser left no draft change, audit row or receipt.
- Every race named for your slice is a real HTTP race through TestClient with
  tests/lock_race_support.py, in both orders where an order exists. Command-only races do not count.
- New tests must fail at the parent commit. Existing tests pass unchanged unless the design names
  the change.

Verification before committing (report each command and result):
  uv run ruff format --check .
  uv run ruff check .
  uv run mypy src
  uv lock --check
  uv run pytest <new test files and the §11.7 regression files> -q
  migration round trip on a disposable PostgreSQL 18 database only (never the developer's dnd_ai
    database): alembic upgrade head; downgrade to 146_public_profile_identity (A5a) or
    147_character_player_profiles (A5b); upgrade head; alembic check
  uv run python scripts/run_sharded_tests.py   (report any rerun separately, with its reason)
  git diff --check

In the same commit, update the documents listed in design §14 for your slice, and append a dated
"<SLICE> implementation record" to design §17 with the parent SHA, the exact commands, the results
(counts, durations, reruns and reasons) and any deviation from the design with its reason.

Commit once with explicit paths, message "feat(p03a): <SLICE> <short summary>", ending with the
attribution lines your harness requires. Then stop and report: parent and commit SHAs, files
changed, test evidence, deviations, and anything you could not verify.
```

---

## 16. Independent review guidance (Codex Luna, Medium)

Review one slice per pass, naming the parent and target SHAs. Run the new tests at the parent, where they must fail, and at the target. Grade findings with [ISSUE_GRADING_RUBRIC](ISSUE_GRADING_RUBRIC.md). Verdict: PASS, PASS WITH NONBLOCKING FINDINGS, or CHANGES REQUIRED.

**Every slice:**

1. **Infrastructure boundary (D18, §3).**
   - No production writer of the profile tables. Check grants as `app_read_write`, search the source, and check the route manifest.
   - No P03-B capability vocabulary.
   - No player-consent state or wording.
   - No kind- or label-based authorization.
   - No world-canon writes and no preview adapter.
2. **Reads (D15).**
   - The GM branch is exactly `has_effective_character_canon_edit`.
   - Reveal authority grants nothing.
   - `may_read_player_profile` is structured so a controller branch can be added without `canon.edit`.
   - The routes filter on `campaign.view`, and every refusal is the generic 404.
3. **Fields (D13).**
   - The eleven codes, including `profile_notes`, not `player_notes`.
   - The label "Notes for the GM and controllers".
   - `boundaries` and `profile_notes` cannot reach a draft, release or audience surface through any structured path. Check the request `Literal`, the trigger, and a raw-row attempt.
   - No text claims that manual transcription is prevented.
4. **Disclosure (D17).**
   - Open every response body for the non-reader callers of §11.4, including 4xx bodies, receipts, audit rows and captured logs.
   - Confirm no exception message is formatted from profile text.
5. **Campaign isolation.** A shared world, timeline and character; the composite provenance FK; B never sees A.
6. **Migrations.**
   - Up, down and up on PostgreSQL 18.
   - The downgrade guards refuse with data and change nothing.
   - 148's downgrade restores 142, 143 and 144 exactly: compare `pg_get_functiondef` and the constraint definitions before and after.
   - `alembic check` is clean.
   - Comments, ownership, FK indexes and grants.
7. **Tests.**
   - Races are real HTTP in both orders, with the §10.4 persistence assertions.
   - KA1–KA4 never require a deadlock.
   - No existing assertion is weakened.

**Slice-specific:**

- **A5a.**
  - The current-profile read is one statement (RA1).
  - The 404 bodies are identical.
  - The deferred head-has-version trigger fails at COMMIT.
  - The fixture helper is the only raw writer.
- **A5b.**
  - Withholding is per field and per origin. A draft with one legacy NPC field and one `player_profile` field withholds each by its own rule.
  - The watermark trigger refuses every non-advancing change of the player-profile pair.
  - The relabel guard covers both provenances.
  - Every A2b test passes unchanged.
- **A5c.**
  - The pre-check runs before the idempotency lookup, so a replay after authority loss is refused.
  - The lock order matches §10.1.
  - The source token is checked under the head's share lock.
  - Responses, receipts and audit rows carry no text.
  - C1–C8 and KA1–KA4 are present.
  - The DEF-019 inventory names the copy route.

**Out of scope for findings:** DEF-019, DEF-016, DEF-021 and R01 themselves; P03-B controller behaviour; Phase 16B/16C storage; the A6 and A7 UI. If you believe one of these blocks A5, grade it and explain why, rather than requesting that it be fixed inside A5.

---

## 17. Records

*(Implementation and review records are appended here, newest last.)*
