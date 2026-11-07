# P03-A implementation plan: public profiles, revelation and audience-safe character reads

**Status:** Approved planning document. A0, A1, P0 and P1 are implemented and independently reviewed. D8 is approved (recorded 2026-11-07). A2a is implemented locally (see "A2a implementation record") and awaits independent review; the plan was committed on its own as the design commit (`3b3d637`) before A2a's code.

- **A0** is implemented at `fca3ac7`.
- **A1** is implemented at `68dc902` through `6a5773d`. That covers the D3 ownership gate, DEF-011, DEF-013 and the reveal delegation. Its record is in [the A1 design](PHASE14_15_P03A_A1_OWNERSHIP_AUTHORITY_DESIGN_2026-11-06.md) §8. The independent re-review passed at `fc20e8d`. CI is pending until push, and an intermittent race-test timeout is still unresolved.
- **D1 and D2** were approved by the owner and recorded on 2026-11-07 (see "Decisions still needed").
- **D3** was approved on 2026-11-06.
- **D8** was approved by the owner on 2026-11-07 as proposed (see "Decisions still needed").
- **Still open:** D4 and D5, plus two decisions from the A2 design: D6 and D7. D5 and D6 are additive and block A3/A4; D7 blocks A2b only.
- **Revision of 2026-11-07, after an independent CHANGES REQUIRED review.** The review text is not in the repository; this revision follows the owner's summary of it.
  - The recovery deadlock is now a prerequisite commit, P0 (§6).
  - The draft-read and deny policy is now proposed decision D8.
  - The release fingerprint now includes `character_id`.
  - Two problems in the first A2a design are fixed (§5.8):
    - the release's lock order inverted against `create_resource_grant`;
    - `canon.edit` denies on a character were read under the wrong key.
  - A second deadlock that predates A2 was found and reproduced, DEF-015 (proposed, §6.6).
- **P0** is implemented at `4dd56fd` (DEF-014). Its independent review is complete (recorded 2026-11-07); its one nonblocking harness finding is addressed by P1's `LockRace` (§7.7).
- **P1** is implemented at `edf46ca` (DEF-015) and its independent review is complete (recorded 2026-11-07). `LockRace` is in `tests/lock_race_support.py`.
- **Revision of 2026-11-07, DEF-015 design.** The correction is prerequisite commit P1 (§7), for Sonnet.
  - It was reproduced on a disposable database in both orders.
  - It also deadlocks with ending the added member's membership, ending the adding manager's membership, and the A2a release path.
  - It changes A2a in one place: the release takes the caller's membership `FOR SHARE`, not `KEY SHARE` (§5.8, §7.6).
- **Revision of 2026-11-07, after the independent A2a review.** The review text is not in the repository; this revision follows the owner's summary of it.
  - Neither D8 deny can be created through the application: `create_resource_grant` refuses a character entity under `entity_id`, the only key every reader consults (§8, proposed DEF-018).
  - The correction is A2a-R (§8), one bounded commit for Sonnet, required before A2a's review closes.
  - Three policy points that D8 does not settle are listed in §8.8 (Q1–Q3).

**Baseline:**

- §1–§4 and the A0 criteria were checked at `phase15/completion` `e1619db2aee132666705c2d7372fcc0a1769394e`.
- The A2 design (§5) was checked at `6a5773d89fc085f705c860825cb69d75de4db1dd`. No later configuration-verification commit exists.
- The DEF-015 design (§7) was checked at `4dd56fda34c5136ff1e288b7a180ba981dd7f41e`.
- The grant-target correction (§8) was checked by reading source at `0b4704cacef5a49ed24c65068938d28ad6eefc93` (A2a). Nothing was run for it.

Every code claim was checked by reading source at the stated commit. No application code, schema or committed test was changed to produce this plan. The DEF-014 and DEF-015 reproductions ran throwaway probes, deleted afterwards, on the test suite's per-run disposable PostgreSQL 18 database (§6.1, §7.1).

**Audience:** the owner, P03-A implementers and independent reviewers.

**Governing documents:**

- [PLANv2.md](PLANv2.md) §15H (P03-A checkpoint and migration boundaries).
- [R19_FOUNDATION_IMPLEMENTATION_PLAN.md](R19_FOUNDATION_IMPLEMENTATION_PLAN.md): R19-P1, §5.1 actor contract, §8 tests T6, T7, T82, T85.
- Accepted ADRs [0021](adr/0021-shared-actor-identity-control-and-authoring-responsibility.md) (§2.5, §2.7–§2.9, §4.1, §4.7–§4.8, §6, §7), [0022](adr/0022-creature-templates-combatants-and-promotion.md) and [0023](adr/0023-rules-engine-calculation-validation-and-source-authorization.md).
- [The A1 design](PHASE14_15_P03A_A1_OWNERSHIP_AUTHORITY_DESIGN_2026-11-06.md): §3 lock order and §8 implementation record. A2 must keep both unchanged.
- Design inputs: [PHASE14_15_APP_INTERACTION_INVESTIGATION_2026-11-01.md](PHASE14_15_APP_INTERACTION_INVESTIGATION_2026-11-01.md) §D6 and [PHASE14_15_REMAINING_WORK_AND_HANDOFF_2026-11-02.md](PHASE14_15_REMAINING_WORK_AND_HANDOFF_2026-11-02.md) §6, including the owner-approved 2026-11-06 reveal-authority and encounter-reference policies, which this plan treats as requirements.

---

## Recommendation

**Next: correction A2a-R (§8, for Sonnet), then the close of A2a's review, then A2b, A3.** A2a is implemented (see "A2a implementation record"). Its independent review found that the D8 denies cannot be created through the application. A2a-R makes both creatable through the normal resource-grant command and pins them with HTTP tests. It needs the owner's answer to Q1 in §8.8; Q2 and Q3 have recommended defaults. Prerequisites P0 and P1 were implemented and reviewed, and D8 is approved.

- **P0** (§6) fixes the deadlock between `lock_authoring_scope` and administrative recovery. It is implemented at `4dd56fd`; its independent review is complete.
- **P1** (§7) fixes DEF-015: adding a member to an access group deadlocks with that member's authoring write (SQLSTATE 40P01, reproduced in both orders).
  - The same command also deadlocks with ending the added member's membership, ending the adding manager's membership, and A2a's release.
  - The fix changes lock order and lock modes in one command, `add_access_group_members`. It adds deterministic regressions and a failure-safe race harness that also closes the P0 harness finding.
  - Scope and acceptance criteria are in §7.8. It is one bounded commit on top of `4dd56fd`. **Recommend landing it before any A2a code**, because A2a's release lock order (§5.8) now depends on it.
- **A2a** is the public-profile draft and release, designed in §5, with acceptance criteria in the last section. Its read and deny rules depend on D8, which is proposed below for owner approval. A2a starts now: P0 and P1 are reviewed and D8 is approved.

The rest of the A2 track:

- **A2a** covers storage, draft editing, release under `character.reveal`, and the GM reads.
- **A2b** is the legacy copy aid. It waits on D7: whether copied NPC legacy text may be shown to draft readers who could not read it at its source.
- **D5 and D6** decide whether a release carries a display name, summary, species or size. Each would be an additive column, so neither blocks A2a. Both must be answered before A4 fixes the audience response shape.
- **D4** waits until A3.

*Original recommendation (2026-11-06, done):* start with slice A0, the `active_encounter_id` filter, implemented at `fca3ac7`.

---

## 1. `character.reveal`: storage and enforcement

**What exists today.** No `character.reveal` code, table or delegation exists.

- Role capabilities are the union of `security.role_capabilities` rows ([access.py:1029-1046](../src/dnd_ai/domain/access.py#L1029-L1046)).
- The resource-grant catalog leaves out administrative codes and `character.discover` ([access.py:129-141](../src/dnd_ai/domain/access.py#L129-L141)).

**Storage.**

- Add `character.reveal` to `security.capabilities` for vocabulary, through a migration INSERT. The seed is frozen, so follow the pattern in migration 139.
- Never resolve it from `role_capabilities` or `resource_grants`. Reject such rows with a trigger, which is a local integrity rule under DATABASE_CONVENTIONS §20.4.
- This applies the same "two sources only" rule ADR 0021 §2.7 sets for `character.assign_control`.

**New table `security.character_reveal_delegations`** (append-style, never edited in place):

- `campaign_id`, `grantee_campaign_membership_id`
- **`gm_membership_role_id`**: the grantee's specific live built-in `gm` assignment
- `granted_by_membership_id`, `granted_at`, `reason`
- `revoked_at`, `revoked_by_membership_id`, `revocation_reason`, `end_reason`
- One live row per grantee, enforced with a partial unique index.

**Resolver.** Add `resolve_reveal_authority(connection, campaign_id, membership_id) -> {owner | delegation | none}` in `domain/`. It returns:

- `owner` when the membership is active and holds a live **built-in** `campaign_owner` row (template with `campaign_id IS NULL`, not revoked or expired, role active);
- `delegation` when an unrevoked delegation exists, its `gm_membership_role_id` row is still live, and the membership is active.

Commands (grant, revoke, release, reveal, revoke-revelation) re-read authority under lock and never trust a cached `AccessContext`. Lock order follows ADR 0021 §2.8 for OD-4a:

- **Grant or revoke delegation:** grantee membership and role rows `FOR UPDATE`, then the campaign `FOR UPDATE`, then re-check that the caller holds the built-in owner role, then the delegation row.
- **Release or reveal:** the caller's owner or `gm` role row and delegation row `FOR SHARE`, then the character's `core.entities` row, then the target rows.

This makes a GM role revocation or delegation revocation serialize with an in-flight release.

**Why bind to the `gm` role row.** It enforces "restoring GM status requires a fresh grant" across every path:

- re-assigning a role always inserts a new row ([memberships.py:454](../src/dnd_ai/commands/memberships.py#L454), [:743](../src/dnd_ai/commands/memberships.py#L743), [:919](../src/dnd_ai/commands/memberships.py#L919));
- there is no command that updates `expires_at`;
- `end_campaign_membership` revokes every role row ([memberships.py:1112-1123](../src/dnd_ai/commands/memberships.py#L1112-L1123)).

So a restored GM always holds a different row, and the old delegation can never come back. Close delegations explicitly (with an `end_reason`) inside the commands rather than through a trigger chain, per §20.4 and the precedent in [memberships.py:1125-1162](../src/dnd_ai/commands/memberships.py#L1125-L1162).

### Every path that changes grant eligibility

| Path | Grantor (owner) | Recipient (GM) / delegation | Required P03-A handling |
|---|---|---|---|
| `create_campaign` (creator gets owner + gm) [campaigns.py:613](../src/dnd_ai/commands/campaigns.py#L613) | gains | gains GM status, no grant | none |
| `assign_membership_role` [memberships.py:337](../src/dnd_ai/commands/memberships.py#L337) | owner may be assigned | `gm` assigned → new row, no grant | none |
| `add_campaign_member` with initial role [memberships.py:779](../src/dnd_ai/commands/memberships.py#L779) | same | same | none |
| `revoke_membership_role` [memberships.py:484](../src/dnd_ai/commands/memberships.py#L484) | owner loses | `gm` row revoked → grant ends | close delegation with `end_reason` |
| `change_membership_role` [memberships.py:591](../src/dnd_ai/commands/memberships.py#L591) | either direction | `gm`→X ends it; X→`gm` is a new row | close on the `gm` side |
| `end_campaign_membership` [memberships.py:964](../src/dnd_ai/commands/memberships.py#L964) | loses | ends | close delegations, plus member-target and snapshot revelations (§2) |
| `transfer_campaign_ownership` [memberships.py:1206](../src/dnd_ai/commands/memberships.py#L1206) | new owner gains now; relinquishing owner loses (keeps `gm`) | **existing grants survive**: grantor is provenance (ADR 0020 decision 7, OD-4a analogy); new owner may revoke | test only |
| Role `expires_at` lapsing (time-based, no write) | owner lapses | read-time liveness fails; a later re-assignment is a new row | read-time check only |
| `recover_campaign_access_manager` [recovery.py:153-195](../src/dnd_ai/commands/recovery.py#L153-L195) | admin creates an owner; can flip an open membership's status to `active` | status flip could revive a delegation bound to a still-live `gm` row | close that membership's delegations when status is changed |
| Invitation acceptance reopens a membership in place [campaign_invitations.py:247-262](../src/dnd_ai/commands/campaign_invitations.py#L247-L262) | none (roles were revoked at end) | none | none, because end already closed everything |
| Campaign archived/deleted (route refuses) / account deactivated (auth fails) | unusable meanwhile | unusable meanwhile | none; the rows are unchanged, so authority returns with no new grant. Read as "not a GM status loss"; reviewer to confirm |
| Role template `is_active` toggle; membership `suspended` | DB-only; no app path exists | fails closed while inactive | document as DB-only |

**Cross-campaign isolation.** Every row is keyed by `campaign_id`, and the resolver only reads the route campaign. Required tests:

- an owner or delegated GM of A gets nothing in B, on the same world and the same timeline;
- a delegation naming a membership or `gm` row from another campaign is refused by a same-campaign trigger, like the existing scope triggers.

---

## 2. Profiles, releases and revelations

**Storage (campaign scope, D1 approved).** The profile tables are specified in §5.3; this section keeps only their outline.

- `campaign.character_public_profiles` holds one mutable **draft** per (campaign, character), with `row_version` (§26.3). Readers are limited by the §5.7a read rule (proposed D8): effective `canon.edit` on the character, or reveal authority.
- `campaign.character_public_profile_releases` holds **immutable** releases, never updated or deleted. Each release snapshots the draft, records each field's origin, and has a gapless `version_number`.
- "Follows later releases" is implemented as "latest release wins", so no pointer is needed. Fixing a mistake means releasing a new version.
- `security.revelation_audience_kinds` is a lookup table, not an ENUM (§5.9/§11): `member`, `access_group`, `campaign_current`, `campaign_current_and_future`. There is no default.
- `security.character_revelations`:
  - campaign, character, kind, and the member or group target (CHECKs by kind);
  - creator, reason;
  - revoked/end columns;
  - same-campaign triggers.
- `security.character_revelation_members` is the `campaign_current` snapshot, written at creation under a campaign lock, with a `removed_at` column.

**Audience rules and the paths that change them:**

- **Member target:** ends when the membership ends. Invitation reactivation reuses the membership UUID, so this follows the existing precedent that a reopened membership starts with nothing.
- **Group target:** live while the group is active and the member has a live group membership.
  - [access_groups.py:597](../src/dnd_ai/commands/access_groups.py#L597) and [:806](../src/dnd_ai/commands/access_groups.py#L806) change who is covered.
  - `deactivate_access_group` [access_groups.py:408](../src/dnd_ai/commands/access_groups.py#L408) should revoke group revelations just as it revokes group grants.
- **`campaign_current`:** snapshot rows only; ended memberships get `removed_at` set.
- **`campaign_current_and_future`:** any active membership, so a returning member counts as a "future" member.

**Enforcement inside `AccessContext`.** Add a separate, source-tagged field (for example `revealed_characters`) to [AccessContext](../src/dnd_ai/domain/access.py#L248). It is resolved in `resolve_access_context` with the same character filters as relationships: lifecycle `active` and canon `canon` ([access.py:1068-1070](../src/dnd_ai/domain/access.py#L1068-L1070)).

- A revelation confers only `character.discover` and a new `character.view_public_profile`.
- It never confers `view_summary`, `view_full`, `view_inventory`, `view_knowledge` or `view_private`.
- `has_capability` adds it to the baseline, so existing denies still win. A whole-character `campaign.view` deny suppresses it, and a deny of `character.discover` alone hides only discovery (ADR 0021 §2.9).
- Revoking a revelation touches only its own row, so legacy viewer relationships and resource grants survive (T6).
- The access-overview explanation ([effective_access.py:82](../src/dnd_ai/queries/effective_access.py#L82)) must show revelation as a distinct source.

**Migration and existing records.** All additive. A1 used `141_character_reveal_delegations`, so A2a is expected to be 142.

- No backfill; no automatic revelation or release.
- `character.character_descriptions` is untouched. It stays reachable only through the authoring reads, which already keeps legacy background restricted.
- After migration, every existing character has no profile and no revelation. Discovery through roles, relationships and grants is unchanged.
- The one intended behavior change is A0.
- New columns must be registered in [data_classification.py](../src/dnd_ai/domain/data_classification.py#L128): release fields `CAMPAIGN_VISIBLE`, draft `GM_ONLY`.

---

## 3. Discovery surfaces and `active_encounter_id`

**Most consumers update together.** Almost every consumer reads the same bundle, so revelation reaches them through one change: add the revealed IDs to the `mentioned` set in [resolve_world_character_visibility](../src/dnd_ai/api/world_explorer.py#L98-L130). Consumers that inherit it:

- World search and counts ([queries/world_explorer.py:255-296](../src/dnd_ai/queries/world_explorer.py#L255-L296))
- `discoverable_entity_ids` and `all_participants_discoverable_sql` ([queries/world_explorer.py:492-620](../src/dnd_ai/queries/world_explorer.py#L492-L620))
- relationships ([api/relationships.py:366](../src/dnd_ai/api/relationships.py#L366))
- organization members ([api/organization_members.py:68](../src/dnd_ai/api/organization_members.py#L68))
- the session roster ([api/sessions.py:184](../src/dnd_ai/api/sessions.py#L184))
- event explanations ([api/event_explanations.py:197-214](../src/dnd_ai/api/event_explanations.py#L197-L214))
- Knowledge subjects ([api/knowledge.py:347](../src/dnd_ai/api/knowledge.py#L347), [:405](../src/dnd_ai/api/knowledge.py#L405))
- the encounter member projection ([api/encounters.py:428](../src/dnd_ai/api/encounters.py#L428))
- the clock reads ([api/campaign_clock.py:107](../src/dnd_ai/api/campaign_clock.py#L107))
- the subject side of preview, which resolves the subject's own `AccessContext`.

**Surfaces that need explicit change:**

- **Projection tier:** add one next to [resolve_character_view_tier](../src/dnd_ai/api/access.py#L455-L490): `public_profile` < `summary` < `full` < `gm`.
- **Link decisions:** [can_open_participant](../src/dnd_ai/api/access.py#L533) and the session roster's [_can_open_character](../src/dnd_ai/api/sessions.py#L169) must treat `public_profile` as openable. Otherwise a revealed character is listed but cannot be opened.
- **Character detail** ([api/characters.py:465](../src/dnd_ai/api/characters.py#L465)):
  - Return a public-tier response carrying the latest release.
  - `species_code` and `size_category` become null at that tier unless released.
  - `sections` gains `public_profile`; the sheet, inventory and parties sections stay false (sections at [api/characters.py:439](../src/dnd_ai/api/characters.py#L439)).
  - Direct entry and browse must agree.
- **Unchanged, regression-test only:** the inventory gate ([api/access.py:496](../src/dnd_ai/api/access.py#L496)), the sheet, and bootstrap perspectives (`view_knowledge`, [queries/bootstrap.py:107](../src/dnd_ai/queries/bootstrap.py#L107)). A revelation must open none of them.
- **Party roster** ([api/parties.py:134-147](../src/dnd_ai/api/parties.py#L134-L147)) deliberately names every current party member without discovery. See D4.
- **Derived mechanics stay outside P03-A.** The public tier never calls `character_sheet` or `character_calculations`.

**`active_encounter_id` today.** It is selected by timeline and `status='active'` only ([queries/character.py:181-193](../src/dnd_ai/queries/character.py#L181-L193)), with no campaign check. `LIMIT 1` therefore picks across campaigns that share a timeline, and campaign-less encounters (`campaign_id` is nullable with `SET NULL`) are also returned.

**The fix:**

- Add a required `campaign_id` to `get_character_view`.
- Filter `e.campaign_id = :campaign` before the `ORDER BY … LIMIT 1`.
- Apply the encounter member-read rule ([queries/encounter.py:100-115](../src/dnd_ai/queries/encounter.py#L100-L115)) through a shared, exported predicate, so the two surfaces can't drift.
- Apply it to every full-tier reader, including `canon.edit` holders and the Foundry paired-device route.

The second caller, AI NPC context ([domain/context_assembly.py:362-396](../src/dnd_ai/domain/context_assembly.py#L362-L396)), must pass the route campaign as well.

---

## 4. Slices, dependencies and review boundaries

| Slice | Scope | Depends on | Checks at the review boundary |
|---|---|---|---|
| **A0** (done, `fca3ac7`) | `active_encounter_id` filter (below) | none | below |
| **A1** (done, `68dc902`–`6a5773d`; CI pending) | `character.reveal` vocabulary, delegation table, resolver, grant/revoke commands and API (owner only), eligibility closure in the membership, ownership and recovery commands, audit | D3 (approved) | Every row of the §1 table as a database test; concurrency tests (revoke `gm` vs grant; revoke delegation vs release); assistant GM, `canon.edit` and custom `access.manage` refused; cross-campaign refusal; migration up/down; the full suite. The release race moves to A2a, because no release existed in A1 |
| **P0** (implemented at `4dd56fd`; independent review complete) | `lock_authoring_scope` takes the campaign row `FOR KEY SHARE` (DEF-014, §6) | none | §6.4–§6.5 |
| **P1** (implemented at `edf46ca`; independent review complete) | `add_access_group_members` locks memberships before the campaign row, in weaker modes (DEF-015, §7); race harness cleanup | P0 | §7.5–§7.8 |
| **A2a** (implemented; review open, correction A2a-R required) | Migration 142 (§5.3); draft save; release under A1 authority; GM reads (§5.7, §5.7a). No copy aid | A1, P0, P1, D1 and D2 (approved), D8 | The criteria in the last section |
| **A2a-R** (designed; for Sonnet) | The D8 denies become creatable: `entity_id` may name a character for a `campaign.view` or `canon.edit` deny (§8); overview and explanation name the character | A2a, Q1 (§8.8) | §8.6–§8.7 |
| **A2b** | Legacy copy aid (§5.10), with per-field origin and D7 withholding | A2a, D7 | Copy allowed exactly when the kind's authoring read is allowed (one shared rule, parity test); origin recorded and carried into the release; withheld fields per D7; legacy text never in any non-authoring response |
| **A3** | Revelations: audience kinds, snapshot, create/revoke, membership-end and group-deactivate hooks, `AccessContext` source, discovery bundle | A2 (a revelation requires an existing release, recommended), D5 | T82 audiences, including the late joiner; T6 independent-grant survival; whole vs operation deny; cross-surface matrix from investigation D6.4 (lists, counts, pagination, relationships, organizations, roster, events, encounters, Knowledge, preview), with **response-body ID assertions**; bootstrap, inventory and sheet unchanged |
| **A4** | Projection tier, public-profile read in the detail route, `sections`, `can_open` | A3 | Browse/detail agreement; public tier carries no species, size or mechanics unless released; revocation takes effect on the next request |
| **A5** | OD-18 player-profile storage plus GM read (editing is P03-B, T85); publishing a selected field via A2 provenance | A2 | Readable only by A's GMs; nothing in B; no write path for players yet |
| **A6** | Portal: reveal/delegation management, draft and release editor, revelation list and revoke, public character view, effective-access sources | A4 (A5 optional) | jsdom; type contract; non-disclosing errors; real-browser checks recorded as pending |
| **A7** | Character-profile audience preview (investigation D6.3, optional), docs reconciliation, corrected Sella acceptance (investigation D6.8) | A4, A6 | Manual T82/D6.8 on namespaced fixtures, not the owner's campaign |

Every boundary also needs:

- `ruff format --check`, `ruff check`, `mypy src`;
- the focused tests, then the full `pytest`;
- migration up/down on PostgreSQL 18;
- a CI run on the final head;
- an independent review naming the parent and target SHAs.

Docs to update in the same change: `DOMAIN_MODEL`, `DATABASE_MODEL` §19, `PHASE13E_ACCESS_CONTRACT`, `ENTITY_LIFECYCLE` command list.

---

## 5. A2 design: public-profile drafts and releases (2026-11-07)

**Status:** design only, checked against `6a5773d`. Nothing in it is implemented.

### 5.1 The approved rules, as A2 applies them

- **Campaign scope (D1).** A draft and its releases are keyed by (campaign, character).
  - Campaign B has its own draft and releases for the same character.
  - Nothing written in A changes what B's GMs or audiences see.
  - The world definition (`core.entities`, `character.character_descriptions`) is never written.
- **Editing (D2, refined by D8).** Editing requires **effective character-scoped `canon.edit`**, which means both of these:
  - the caller holds role `canon.edit` in the route campaign (assistant GMs included), re-checked under lock by `lock_authoring_scope` ([_content.py:95](../src/dnd_ai/commands/_content.py#L95)), as every authoring write does;
  - no deny removes it for this character (§5.7a).

  A `canon.edit` allow targeting the character does not by itself confer editing (D8).
- **Releasing (D2).** A release requires `character.reveal` authority from `resolve_reveal_authority`: a live built-in owner, or a live delegation bound to the caller's live built-in `gm` assignment.
  - The authority is re-read under lock and judged again at a fresh database instant after the last lock wait (the DEF-013 pattern).
  - `canon.edit` alone, assistant-GM status, a custom `access.manage` holder and a player are refused.
- **Copying legacy text (D2).** Allowed only to a caller whose existing authoring read returns that text (§5.10).
- **Reading drafts and releases (proposed, D8).** A member may read the draft and the release snapshots if they have either:
  - effective character-scoped `canon.edit`; or
  - current `character.reveal` authority, from `resolve_reveal_authority` at the time of the read.

  Reveal authority confers reading only, never editing. A whole-character deny overrides both (§5.7a).
  - Today every reveal-authority holder also holds role `canon.edit`: the owner through migration 085, a delegated GM through the built-in `gm` role in migration 086.
  - So D8 changes the outcome only when a reveal holder has a `canon.edit` deny on one character. They can still read and release that character's profile, but cannot edit it. That follows ADR 0021 §2.9: "An operation-specific deny blocks only that operation."
  - A releaser can therefore always read what they release.
- **What a release does not do.** It makes nothing visible by itself. Audiences see a release only through an A3 revelation, through the A4 read.

### 5.2 Profile fields

| Field | Draft | Release | Classification | Notes |
|---|---|---|---|---|
| `public_appearance` | `TEXT NULL`, at most 4000 characters | snapshot | draft `GM_ONLY`, release `CAMPAIGN_VISIBLE` | The limit is `NPC_TEXT_MAX_LENGTH` ([npc_authoring.py:14](../src/dnd_ai/domain/npc_authoring.py#L14)), the source field's limit, so a copied text always fits |
| `public_background` | same | snapshot | same | same |
| `<field>_origin_id` | FK to the origins lookup | snapshot | `STRUCTURAL` | `authored`, `legacy_appearance` or `legacy_background`. `player_profile` is reserved for A5 and inserted then |
| `<field>_origin_entity_row_version` | `BIGINT NULL` | snapshot | `STRUCTURAL` | The character's `core.entities.row_version` when the text was copied. Present only for a legacy origin |

- **Every field may be null.** A release whose fields are both null is allowed. It withdraws the public text in the next version.
- **Not in A2:**
  - a display name or summary (D5);
  - species and size (D6);
  - player-profile fields (A5).
- **No derived mechanics.** The release command and the profile reads never call `character_sheet`, `character_calculations` or a rules module. A structural test pins this (A2a criterion 9).

### 5.3 Storage: migration `142_character_public_profiles`

The migration is additive, with no backfill. After it runs, every existing character has no draft and no release.

**`campaign.public_profile_field_origins`.** A lookup table (§11: no ENUM) holding `authored`, `legacy_appearance` and `legacy_background`.

**`campaign.character_public_profiles`** (the draft, a mutable record, §10.2). Columns:

- `character_public_profile_id` (PK);
- `campaign_id` (FK to `campaign.campaigns`);
- `character_id` (FK to `character.characters`);
- the §5.2 draft fields;
- `row_version BIGINT NOT NULL DEFAULT 1 CHECK (row_version >= 1)`, kept current by the shared `core.bump_row_version()` trigger (§26.3);
- `created_at`, `created_by_membership_id`, `updated_at`, `updated_by_membership_id`.

Constraints:

- `UNIQUE (campaign_id, character_id)`;
- `UNIQUE (character_public_profile_id, campaign_id, character_id)`, the target of the releases' composite foreign key.

**`campaign.character_public_profile_releases`** (append-only, §10.3). Columns:

- `character_public_profile_release_id` (PK);
- `character_public_profile_id`, `campaign_id`, `character_id`, as a composite FK to the draft's triple, so a release cannot name another campaign's or another character's profile;
- `version_number INT CHECK (version_number >= 1)`;
- `from_draft_row_version BIGINT`;
- the §5.2 snapshot fields;
- `authority_source_code` (`owner` or `delegation`) and `character_reveal_delegation_id` (FK, NULL unless the source is `delegation`, with a CHECK pairing the two);
- `released_by_membership_id`, `released_at TIMESTAMPTZ`;
- `release_note TEXT NULL` (`GM_ONLY`).

Constraints:

- `UNIQUE (character_public_profile_id, version_number)`;
- `UNIQUE (character_public_profile_id, from_draft_row_version)`. A draft version is released at most once; this is also the natural retry key (§5.9).

**Triggers** (§20.4, local integrity only):

- **Scope.** The character belongs to the campaign's world. `created_by`, `updated_by` and `released_by` memberships belong to the row's campaign. A delegation belongs to the campaign and its grantee is the releaser. These follow the scope triggers of migration 141.
- **Origin.** A field's origin matches the field (`legacy_appearance` only on `public_appearance`, and so on). `origin_entity_row_version` is present exactly when the origin is a legacy origin. A null text has origin `authored`.
- **Immutability.** Releases refuse UPDATE, DELETE and TRUNCATE.

**Other database changes:**

- **Grants.** Follow migration 141's pattern. The application role gets SELECT, INSERT and UPDATE on drafts; SELECT and INSERT on releases; SELECT on the lookup. Nothing gets DELETE.
- **Entity reference classification.** Both `character_id` foreign keys are registered as `BLOCKING` in `ENTITY_REFERENCE_CLASSIFICATION` ([entity_lifecycle.py:101](../src/dnd_ai/commands/entity_lifecycle.py#L101)). A character with a profile is therefore never physically deleted (ENTITY_LIFECYCLE §14). Legal removal would need its own reviewed administrative procedure; that is outside A2.
- **Downgrade.** Lossy but supported: it drops the tables, triggers and lookup, as 141 does.

### 5.4 The draft's concurrency token

- **Saving** (`save_character_public_profile_draft`) requires `expected_row_version`.
  - `null` means "there is no draft yet". The command inserts with `INSERT … ON CONFLICT (campaign_id, character_id) DO NOTHING RETURNING`. If nothing is returned, another request created the draft first, and the save fails with 409 `stale_write`.
  - Otherwise the command locks the draft `FOR UPDATE` and compares. A mismatch is 409 `stale_write` (`StaleWriteError`), with nothing written.
- **Partial updates.** A field left out of the request is untouched. An explicit `null` clears the field and resets its origin to `authored`. This is needed for A2b's withheld fields; for A2a it just keeps saves small.
- **No real change.** Values identical to the stored ones write nothing, do not bump `row_version`, write no audit row, and return `changed: false`.
- **Releasing never writes the draft,** so a release does not make a concurrent editor's token stale.

### 5.5 The release snapshot and version allocation

`release_character_public_profile` takes `expected_draft_row_version` and an optional `release_note`. It never takes field content. It snapshots exactly the locked draft at that version, so the release is precisely what the releaser reviewed. Under the §5.8 locks:

1. **Deny.** The caller's `AccessContext` is re-resolved after the campaign lock. A whole-character deny (§5.7a) gives 404, with nothing written. This check runs before step 3, so a denied caller is never handed an existing release.
2. **Draft.** No draft gives 409 `public_profile_draft_missing`.
3. **Natural retry.** If a release with `from_draft_row_version = expected` already exists, return it: 200, `created: false`, plus `is_latest`. This happens even when the draft has since moved on (§5.9).
4. **Stale.** If the current `row_version` is not `expected`, fail with 409 `stale_write`; nothing is written.
5. **Character.** It must still be a `canon`, `active` character of the campaign's world. Otherwise: 404 when it is not in the world or not canon; 409 `public_profile_character_not_active` when it is archived.
6. **Version.** `version_number = COALESCE(MAX(version_number), 0) + 1` for this profile, read under the draft's `FOR UPDATE` lock. Every release of a profile takes that lock, and releases are never deleted, so versions are gapless; the unique constraint is only a backstop. Insert the release, write its audit row, and return 201, `created: true`.

**The current release** is the one with the highest `version_number` ("latest release wins"; OD-17 "follows later releases"). A3 and A4 read it through one query, `latest_character_public_profile_release(campaign_id, character_id)`, added in A2a and used by no audience reader until A4.

### 5.6 Provenance

- **Field origin, kept across edits.** A2b's copy sets a field's origin to its legacy origin and records the source's `core.entities.row_version`. Later edits keep that origin, so editing never removes the record that the text came from legacy material. Clearing the field resets it. Under D7, so does a blind replacement by a reader who could not see the field.
  - The rule over-attributes rather than under-attributes. A2a has no copy, so every origin is `authored`.
- **On each release:** the per-field origins, `from_draft_row_version`, `released_by_membership_id`, `released_at`, the authority source (owner or delegation), and the delegation's id when there is one.
- **Releases outlive authority.** A release made under a delegation stays after the delegation ends. The approved policy of 2026-11-06 says ending a GM's grant ends *future* release authority. A1's lifecycle hooks never touch releases.
- **Audit** (`audit.change_log`, one row per real change, none for a repeat or a no-op):
  - a draft save records changed field names and the new `row_version`;
  - a copy (A2b) records the origin and the source row version;
  - a release records `version_number`, `from_draft_row_version` and the authority source.

  Audit rows never carry profile text. It lives only in the draft and release rows. Revision snapshots (`capture_revision`) are **not** written, because `core.entity_revisions` is world-scoped and any campaign's reader with `world.canon.read_private` can read it.

### 5.7 Routes and authorization

All routes are under `/campaigns/{campaign_id}/characters/{character_id}/public-profile`. A character outside the campaign's world, a non-character entity, or a non-canon character gets 404 (not disclosed). The read, edit and release rules, and how denies apply to them, are in §5.7a.

| Route | Route filter | Authority in the handler or command | Result |
|---|---|---|---|
| `GET …/public-profile` | `campaign.view` | The §5.7a read rule; failing it gives 404 | The draft (or `null`), its `row_version` and `has_unreleased_changes`; the latest release; a list of release summaries (version, time, releaser name, authority source, draft version); `can_edit` and `can_release` (no lock); the D5 label (canonical name and summary, read-only); in A2b, `legacy_copy` availability, shown only to a caller who passes that kind's read rule |
| `GET …/public-profile/releases/{version_number}` | `campaign.view` | The §5.7a read rule; failing it gives 404 | One release snapshot |
| `POST …/public-profile/draft` | `canon.edit` (role; a coarse first filter) | `lock_authoring_scope(world_capability=None)`, then the §5.7a edit rule, re-resolved under those locks. A caller who can still read gets 403 `public_profile_edit_denied`; anyone else gets 404 | 201 created, or 200 with `changed`; supports `Idempotency-Key` |
| `POST …/public-profile/releases` | `campaign.view` | A reveal-authority pre-check before the idempotency lookup (below); then authority locked and re-judged at a fresh instant (§5.8); then the whole-character deny re-resolved under lock, which gives 404 | 201 `created: true`, or 200 `created: false` (§5.9); supports `Idempotency-Key` |
| `POST …/public-profile/draft/copy-legacy` (A2b) | `canon.edit` | The edit rule, plus the kind's legacy read rule (§5.10). D7 stays separate | 200 with the new draft `row_version`; supports `Idempotency-Key` |

**Why `campaign.view` for the reads and the release.** D8 lets a reveal holder read and release without `canon.edit`, so neither path may require `canon.edit` at the route. Players also hold `campaign.view`. They fail the read rule with a 404, which discloses nothing, and they fail the release pre-check with a 403 that names no character (next paragraph).

**Authorization runs before the idempotency lookup** (DATABASE_CONVENTIONS §26.4).

- **The pre-check.** Before `start_campaign_idempotency`, the release endpoint calls `resolve_reveal_authority(lock="none")` and refuses with 403 **`character_reveal_required`** (a new error code).
  - Reveal authority depends only on the campaign, so this 403 says nothing about the character.
  - A caller who has lost authority cannot replay a stored response.
- **The character checks come after the lookup.** The whole-character deny and the character checks give 404s, and run after it.

**Idempotency fingerprint (review correction).** All three POST routes put the path's `character_id` into the fingerprinted payload: `{"character_id": str(character_id), **body.model_dump(mode="json")}`. This is the pattern `update_player_character` already uses ([player_character_authoring.py](../src/dnd_ai/api/player_character_authoring.py), `{"player_character_id": …, **body}`).

- **Why it matters.** The store's scope is (actor, campaign, key). The release body `{expected_draft_row_version, release_note}` does not identify the character. Without `character_id`, a reused key with the same body on character Y would replay X's stored 201 for Y. Y would then appear released when it was not.
- **With it,** the fingerprints differ and the request gets the existing non-disclosing idempotency 409. This is pinned by A2a criterion 13.

### 5.7a Reading, editing and releasing under denies (proposed, D8)

**Which deny keys apply.** `campaign.view` and `canon.edit` are generic-target capabilities. A resource grant can name them for a character only through the `entity_id` target (`RESOURCE_GRANT_CAPABILITY_CATALOG`, [access.py:228](../src/dnd_ai/domain/access.py#L228)).

*Correction (A2a review, §8):* the catalog permits that key, but `create_resource_grant`'s CTI guard refuses a character entity under `entity_id`. So at `0b4704c` neither deny below can be created through the application, only by direct SQL. A2a-R (§8) removes that refusal for exactly these two denies. The read keys below are unchanged.

- **Whole-character deny:** `not access.has_capability("campaign.view", entity_id=character_id)`. This is the test `resolve_character_inventory_access` uses ([api/access.py:514](../src/dnd_ai/api/access.py#L514)).
- **`canon.edit` deny on the character:** a `deny` for `canon.edit` under `("entity_id", character_id)` in `grant_effects`. A deny under `("character_id", character_id)` counts too, so that a stray row also fails closed.
  - `has_capability("canon.edit", character_id=…)` alone is **not** enough: it consults only the `character_id` key, under which no `canon.edit` grant can be created.
  - That mistake already exists in `resolve_character_view_tier` ([api/access.py:482](../src/dnd_ai/api/access.py#L482)) and `resolve_character_inventory_access` ([:515](../src/dnd_ai/api/access.py#L515)), so neither sees a per-character `canon.edit` deny. It predates A2 and is outside it: proposed **DEF-016**. A2 must not copy the pattern.
- **Effective character-scoped `canon.edit`:** role `canon.edit`, no whole-character deny, and no `canon.edit` deny on the character. An `allow` grant of `canon.edit` on the character does **not** confer editing on a member without role `canon.edit` (D8). Otherwise a resource grant would become the first per-character authoring path, which ADR 0021 §4 reserves for stewardship and delegations.

| Deny on the caller | Read draft and releases | Edit draft | Release |
|---|---|---|---|
| None | Allowed with effective character-scoped `canon.edit` **or** reveal authority | Allowed with effective character-scoped `canon.edit` | Allowed with reveal authority |
| Whole-character (`campaign.view` on the character's entity) | **Refused**, 404, for every source, the owner included (ADR 0021 §2.9: suppresses profiles "from every source") | **Refused**, 404 | **Refused**, 404, nothing written; checked before a natural retry can return a release (§5.5 step 1) |
| `canon.edit` on the character | Only the `canon.edit` path is removed; a reveal holder still reads | **Refused**: 403 `public_profile_edit_denied` if the caller can still read, otherwise 404 | No effect: a different operation (§2.9) |
| `character.reveal` | Cannot exist: A1's trigger refuses any resource-grant row naming `character.reveal` (migration 141) | — | Per-character release denial is therefore not available. Adding it would extend A1's trigger to accept deny-only rows, which is out of scope |
| `character.view_*`, `character.discover`, A3's `character.view_public_profile` | No effect: these govern audience projections, not the GM draft | No effect | No effect |

D7's restriction on copied legacy fields is separate. It applies after this table, on top of it, and is unchanged by D8.

**Under lock.**

- **Edits** re-resolve the `AccessContext` after `lock_authoring_scope` has taken all its locks.
- **Releases** re-resolve it after taking the caller's membership `FOR SHARE` and the campaign row `KEY SHARE` (§5.8).
- **Why that is enough.** A deny reaches a member in three ways, and each one conflicts with a lock the command already holds when it re-resolves:
  - **`create_resource_grant` naming the member.** It takes the member's membership `FOR UPDATE` and the campaign row `FOR UPDATE`, which conflict with the command's membership `FOR SHARE` and campaign `KEY SHARE`.
  - **`create_resource_grant` naming a group the member belongs to.** It takes the campaign row `FOR UPDATE`, which conflicts with `KEY SHARE`.
  - **Adding the member to a group that holds a deny.** After P1 (§7) this no longer takes the campaign row `FOR UPDATE`. It takes each added member's membership `FOR NO KEY UPDATE`, which conflicts with the `FOR SHARE` that `lock_authoring_scope` and the release take on the caller's membership. This is why the release takes its membership `FOR SHARE`, not `KEY SHARE`: `KEY SHARE` would not wait for the add (§7.6, probe S7/S8 against S7b/S8b).

  So a concurrent deny either commits before the re-resolve and is seen, or waits for the command to commit. P0 keeps the campaign conflict, since `KEY SHARE` still conflicts with `FOR UPDATE`, and P1 moves the group-add conflict to the membership row.
- **Reads** are judged at the moment of the read.

### 5.8 Transactions and locks

Each command is one transaction, and the audit row commits with the write. The orders below add to the A1 design's §3 table and reverse none of its rows. They assume P0 (§6): `lock_authoring_scope` takes the campaign row `FOR KEY SHARE`. They also assume P1 (§7): `add_access_group_members` takes the added members' memberships `FOR NO KEY UPDATE` before the campaign row, and the campaign `KEY SHARE`.

| Command | Locks, in order |
|---|---|
| `save_character_public_profile_draft` | `lock_authoring_scope`: world (S) → caller's role rows and membership (S) → account (S) → campaign (**KEY SHARE**, after P0), then the role `canon.edit` re-check → the `AccessContext` re-resolved for the §5.7a edit rule → character's `core.entities` row (S) → the draft row (U), or the insert's unique-index wait |
| `release_character_public_profile` (**corrected**) | Caller's authority rows, as in `resolve_reveal_authority(lock="share")`: the owner assignment (S), or else the `gm` assignment (S) then the delegation row (S) → **caller's membership (S; `KEY SHARE` in the first revision, changed by P1, §7.6) → campaign row (KEY SHARE) → character's `core.entities` row (KEY SHARE)** → the draft row (U) → `clock_timestamp()` → `resolve_reveal_authority(as_of=<that instant>)`, which must return the **same** source as the locked read, or the release is refused with 403 `character_reveal_required` → the `AccessContext` re-resolved for the whole-character deny → write |
| `copy_legacy_text_to_public_profile_draft` (A2b) | As for a draft save, with the world capability resolved under the world lock. The source text and the character's `row_version` are read in one statement, after the entity lock |

**Correction to the first A2a design.** The first design locked the character's entity before the caller's membership. `create_resource_grant` locks the grantee's membership `FOR UPDATE`, then the campaign `FOR UPDATE`, then the target entity `FOR UPDATE` ([access_grants.py:1341](../src/dnd_ai/commands/access_grants.py#L1341)). A grant to the releaser naming the character would therefore hold the membership and wait for the entity, while the release held the entity and waited for the membership: a deadlock.

The release now takes membership, then campaign, then entity. That is the order `create_resource_grant`, `grant_character_relationship` and `lock_authoring_scope` already use. The last lock wait is still the draft row, so the fresh-instant re-check (DEF-013 pattern) still follows every wait.

**Release, case by case.**

- **Same-source rule.** If the owner row expires during a wait and only a delegation remains, the delegation's rows were never locked. Refusing is fail-closed, and a retry resolves the delegation freshly.
- **Revoking the releaser's `gm` role, ending their membership, or re-granting their delegation.** Each takes the releaser's role rows `FOR UPDATE` first; the release takes them `FOR SHARE` first. Whichever gets there first goes first.
- **Revoking the delegation.** The revocation queues on the delegation row, and the release waits for nothing the revocation holds.
- **A resource grant to the releaser on this character.** Both take the releaser's membership first (`FOR UPDATE` against `FOR SHARE`), so the first to lock it goes first.
- **A resource grant *by* the releaser.** The grant's insert takes `KEY SHARE` on the releaser's membership through `granted_by_membership_id`, which is compatible with the release's `FOR SHARE`. Neither waits for the other there.
- **Relinquishing transfer by the releasing owner.** Ordered by the owner row: U against S.
- **Relinquishing transfer to a releasing GM.** The transfer locks that GM's membership `FOR UPDATE`. The release waits for it at the membership `FOR SHARE` while holding only its authority rows, which the transfer does not request.
- **A delegation re-grant to the releasing GM.** The grant locks the grantee's `gm` assignment `FOR UPDATE` before the grantee's membership `FOR NO KEY UPDATE`. The release takes that assignment `FOR SHARE` first, so whichever reaches the `gm` row first goes first. The release's membership `FOR SHARE` conflicts with the grant's `FOR NO KEY UPDATE` only after that point. A release by an owner locks no `gm` row. It waits at the membership while holding only its owner assignment, which the grant locks at most `FOR SHARE`.
- **Administrative recovery.**
  - Recovery holds the campaign `FOR NO KEY UPDATE`, which is compatible with the release's campaign `KEY SHARE`. When recovery waits for the promoted member's membership, the release holding it can still finish.
  - Recovery closes a delegation only for a membership that was not `active`. For such a membership the release's authority read returns no row and locks nothing.
- **Adding the releaser to an access group.** Before P1 this deadlocks, as it does for every authoring write (DEF-015, reproduced: §7.1, S7/S8). After P1 the add takes the releaser's membership `FOR NO KEY UPDATE` before the campaign row, and that conflicts with the release's membership `FOR SHARE`. So the first to reach the membership goes first. If the add commits first, the release's re-resolve sees the new group membership and any deny it carries. Neither holds the campaign row in a mode the other's wait conflicts with (probe S7b/S8b).
- **Archiving the character.** Archiving locks the entity `FOR UPDATE`, which conflicts with the release's `KEY SHARE`. Either the release commits first, or it reads the archived state after its lock and refuses.

**Saving the draft.**

- **Against a release.** A save takes no role rows `FOR UPDATE` and holds only shared locks before the draft row. The release's membership `FOR SHARE` and campaign `KEY SHARE` are compatible with the save's locks (`FOR SHARE` on its own membership, `KEY SHARE` on the campaign). So the draft row alone orders the two.
- **Against GM-role revocation, membership end, campaign archive and resource-grant creation.** This is the existing `lock_authoring_scope` order: role rows and membership first. P0 preserves it.

### 5.9 Concurrent edits, stale requests and retries

| Situation | Outcome |
|---|---|
| Two saves with the same `expected_row_version` | The first commits (`row_version` + 1). The second waits on the draft row, then gets 409 `stale_write`; nothing is written |
| Two first saves (no draft yet) | One gets 201. The other waits on the unique index, then gets 409 `stale_write` |
| A save commits before a release of the previous version | The release is 409 `stale_write`, with no release row. The releaser reloads, reviews and releases the new version |
| A release commits before a save | The save proceeds, because its token is unchanged. The release holds the earlier content |
| Two releases of the same draft version, under different keys or no key, including one by the owner and one by a delegated GM | One gets 201 with version *n*. The other waits on the draft row, then gets 200 `created: false` with the same release, and the first releaser as provenance. Exactly one row and one audit row |
| The response to a successful release is lost; retried with the same `Idempotency-Key` | The stored 201 body is replayed, and nothing is written, after the authority pre-check (§5.7). If the caller has lost authority meanwhile, 403; the release is still visible in the GM read (releaser, time, draft version) |
| The same, retried without a key or with a new key | 200 `created: false`, with the release made from that draft version. `is_latest` says whether a later release exists. This is never a false `stale_write`, even when the draft has since moved on |
| The same key with a different body | The existing non-disclosing idempotency 409 |
| The same key **and the same body** on a different character's path (release, draft save or copy) | The existing non-disclosing idempotency 409, because `character_id` is in the fingerprint (§5.7). Nothing is written for the second character, and the first character's stored response is never replayed for it |
| The caller's finite owner assignment, or their `gm` assignment, expires while the release waits | 403 `character_reveal_required` from the fresh-instant re-check (DEF-013 pattern); nothing is written |

### 5.10 The legacy copy aid: read trace and design (A2b)

**Where legacy text is read today** (traced at `6a5773d`):

| Reader | Gate | Returns legacy text? |
|---|---|---|
| `GET …/authoring/player-characters/{id}` ([player_character_authoring.py:191](../src/dnd_ai/api/player_character_authoring.py#L191)) through `get_character_authoring` ([queries/npc_authoring.py:85](../src/dnd_ai/queries/npc_authoring.py#L85)) | campaign `canon.edit`; any character of the campaign's world (ADR 0021 §4.1) | `background`, `appearance`, and the GM-only `notes` |
| `GET …/authoring/npcs/{id}` ([npc_authoring.py:192](../src/dnd_ai/api/npc_authoring.py#L192)) | campaign `canon.edit` **and** world `world.canon.read_private` | the same three fields |
| Revision history and comparison ([review_queue.py:120](../src/dnd_ai/api/review_queue.py#L120), [:150](../src/dnd_ai/api/review_queue.py#L150)) | `canon.edit` and `world.canon.read_private` | yes, as diffs of the authoring snapshot (`capture_revision`) |
| Audit history ([audit_history.py](../src/dnd_ai/api/audit_history.py)) | `access.manage` | no: an allowlist of commands, and only `previous_membership_role_id` is read from `changed_fields` |
| Provenance ([provenance.py](../src/dnd_ai/queries/provenance.py)) | `canon.edit` | no: lifecycle actor and time, "never the free-text reason or the changed fields" |
| Character detail, world explorer, bootstrap, sheet, inventory, relationships, sessions, encounters, Knowledge, AI context, Foundry routes | various | **no.** Only [commands/npcs.py](../src/dnd_ai/commands/npcs.py) and [queries/npc_authoring.py](../src/dnd_ai/queries/npc_authoring.py) reference `character.character_descriptions` in `src/` |

**Design.**

- **One shared read rule per kind.** Put the rule for each kind in one place: `player_character` needs no world capability; `npc` needs `WORLD_CANON_READ_PRIVATE`. Both authoring GET routes, the copy command and D7's withholding read it, and a parity test pins that they agree.
- **Choosing the kind and locking.** The command reads the entity's type without a lock (a character's type never changes, as with A1's unlocked campaign-of-membership read). It then calls `lock_authoring_scope` with that kind's world capability. A caller without it gets the existing 403 `world_authority_required`.
- **What may be copied.** Only `appearance` → `public_appearance` and `background` → `public_background`. `notes` is never copyable.
- **How the copy writes.** It replaces the target field with the whole source text. The GM then cuts it down to the safe excerpt. It requires `expected_row_version`, sets the origin (§5.6), and bumps `row_version`. An empty source gives 409 `public_profile_legacy_text_missing`.
- **Copying is done on the server,** so the origin is a fact about the copy. Text a GM pastes by hand is `authored`. The origin is a record, not a safety label: nothing is published without a release.
- **D7.** With the recommended answer, the GM read and the release apply the withholding rule (see D7). The release then also takes the world row `FOR SHARE` before its authority rows, the same position `lock_authoring_scope` uses.

### 5.11 Drafts and legacy text stay out of audience responses

- **No audience reader in A2.** A2 adds only GM-side routes: every one requires the §5.7a read, edit or release rule, which no player or observer meets. No audience reader selects the new tables, and none selects `character.character_descriptions` (trace above).
- **Releases.** A release becomes an audience field only through A4's read of the latest release for a revealed character. A2a's tests show that a release alone appears in no audience response.
- **Guards added in A2a:**
  - **Structural tests.** Pin which `src/` modules reference each table: the draft table only from the profile command and query modules; `character.character_descriptions` only from the modules listed above, plus A2b's copy command.
  - **Registry entries.** `data_classification` entries for every new text column: draft text `GM_ONLY`, release text `CAMPAIGN_VISIBLE`, `release_note` `GM_ONLY`.
  - **A marker sweep of response bodies** (A2a criterion 8).
- **Mechanics.** These stay outside the profile (§5.2).

### 5.12 A1's guarantees, preserved

- **No new authority source.** `resolve_reveal_authority` and the live-owner and live-`gm` predicates are reused unchanged.
  - Assistant GM, `canon.edit` alone, custom `access.manage`, a lapsed or revoked delegation, and the owner or delegated GM of another campaign are all refused, and tested in A2a.
- **No change to the commands A1 reviewed.** The membership, ownership-transfer, recovery and delegation commands and their lifecycle hooks are unchanged, and A2 adds no lifecycle hook.
- **Ending authority leaves releases alone.** A release outlives the authority that made it. Revocation stays independent (ADR 0021 §2.9), and A3 owns revelations.
- **Lock order.** Only rows are added to the A1 design's §3 table (§5.8), and none is reversed. A1's deadlock and race regressions are rerun at A2a's review boundary.

---

## 6. Prerequisite commit P0 (for Sonnet, before A2a): `lock_authoring_scope` against recovery

**Status:** designed 2026-11-07 against `6a5773d`; **implemented at `4dd56fd`** (DEF-014 in the defect register) and awaiting independent review. It is one bounded commit on `phase15/completion` and touches no schema and no API shape. A nonblocking finding about its race harness, that failure cleanup must release blockers and join worker commands before fixture teardown, is addressed in P1 (§7.7).

### 6.1 The defect (proposed DEF-014, reproduced)

**The two lock sequences.**

- `lock_authoring_scope` ([_content.py:95](../src/dnd_ai/commands/_content.py#L95)) takes, in order:
  1. the world `FOR SHARE`;
  2. the caller's unrevoked role rows and open membership `FOR SHARE`;
  3. the account `FOR SHARE`;
  4. the campaign row `FOR SHARE` ([_content.py:169](../src/dnd_ai/commands/_content.py#L169)).
- `recover_campaign_access_manager` ([recovery.py:153](../src/dnd_ai/commands/recovery.py#L153)) takes the campaign row `FOR NO KEY UPDATE`, then asks for the promoted user's open membership `FOR UPDATE` ([recovery.py:166-170](../src/dnd_ai/commands/recovery.py#L166-L170)).

**The cycle.** `FOR SHARE` conflicts with `FOR NO KEY UPDATE`. So an authoring write by the member being promoted can hold the membership while waiting for the campaign, while recovery holds the campaign and waits for the membership. PostgreSQL aborts one with SQLSTATE 40P01, which the API reports as a 500.

**Reproduction.**

- **The review's probe.** It survives only as compiled bytecode: `tests/database/__pycache__/test_review_a2a_recovery_inversion_tmp…pyc`, whose source is not in the tree. It:
  1. used the Gate fixture and `_strand_the_campaign_for_recovery`;
  2. paused `lock_authoring_scope` just before its campaign statement;
  3. started recovery for the same user;
  4. confirmed through `pg_blocking_pids` that recovery was blocked by the author;
  5. released the author, and got `REPRODUCED SQLSTATE 40P01`.
- **Re-run independently on 2026-11-07** with a throwaway probe (deleted afterwards) on local PostgreSQL 18:
  - **Unchanged (`FOR SHARE`):** recovery is blocked on the author, and then 40P01.
  - **Patched by rewriting the statement to `FOR KEY SHARE`:** recovery is blocked on the author, the author commits, and then recovery commits. No error.

**Scope.** Every command that goes through `lock_authoring_scope` is affected (§6.3). The window requires an administrator to recover a stranded campaign while the member being promoted is in the middle of an authoring write. Recovery runs only when no non-expiring access manager exists.

### 6.2 The correction: one lock mode

Change the campaign statement in `lock_authoring_scope` from `FOR SHARE` to **`FOR KEY SHARE`**. Nothing else in the helper changes.

**Why this is the smallest correct change:**

- `FOR KEY SHARE` conflicts only with `FOR UPDATE`. `FOR SHARE` also conflicts with `FOR NO KEY UPDATE` and with plain non-key `UPDATE`s.
- Weakening one lock can only remove waits; it adds none. So the change cannot introduce a new deadlock.
- The only waits it removes are against the campaign row's `FOR NO KEY UPDATE` and non-key `UPDATE` takers, and the trace below shows recovery is the only one.

**What it preserves, and why:**

| Protection | Mechanism | After P0 |
|---|---|---|
| Campaign archive, reactivate and settings edit serialize with an authoring write | `archive_campaign`, `reactivate_campaign` and `update_campaign` all take the campaign row `FOR UPDATE` first, through `_lock_campaign_for_manage` ([campaigns.py:682](../src/dnd_ai/commands/campaigns.py#L682)). These are the only application `UPDATE`s of `campaign.campaigns` (`campaigns.py:723`, `:801`); migration 024's `UPDATE`s are a one-time backfill | `FOR UPDATE` conflicts with `KEY SHARE`, so this is preserved. In READ COMMITTED, an author who waited reads the archived status after its lock and fails with `CampaignArchivedError` |
| Role loss (`revoke_membership_role`, `change_membership_role`) and membership end (`end_campaign_membership`) serialize with an authoring write | The role rows and membership `FOR SHARE`, taken before the campaign row; the deferred retention trigger takes the campaign `FOR UPDATE` at commit | Unchanged. The helper's comment about why the membership comes before the campaign still holds, because `KEY SHARE` still conflicts with the trigger's `FOR UPDATE` |
| Account deactivation | The account `FOR SHARE` | Unchanged |
| World archive, end of a world role, world ownership transfer and world recovery | The world `FOR SHARE` | Unchanged |
| Resource-grant, relationship and access-group writes that take the campaign row `FOR UPDATE` | `FOR UPDATE` against the author's campaign lock | Preserved. This is also what orders D8's deny re-check (§5.7a). *Superseded for access-group member additions by P1 (§7):* those no longer take the campaign `FOR UPDATE`, and serialize with an author at the member's membership row instead |
| Recovery serializes with another recovery, `add_campaign_member`, a relinquishing transfer and the retention trigger | Recovery's own campaign `FOR NO KEY UPDATE`, which conflicts with every `FOR UPDATE` and with another `FOR NO KEY UPDATE` | Unchanged; recovery is not edited |
| Recovery against an in-flight authoring write | Previously the author waited for recovery at the campaign row, the inverted order that deadlocks | Recovery now waits for the author at the membership `FOR UPDATE`, as `end_campaign_membership` does. Recovery only adds authority (an owner role, a status change to `active`, closing a delegation for a membership that was not active), so the author's earlier authorization stays valid at its commit |

**Rejected alternatives.**

- *Reorder recovery to lock the membership before the campaign.* The membership may not exist yet: recovery inserts it under the campaign lock. A membership created concurrently would still be locked after the campaign. This also edits a command A1 reviewed.
- *Take the campaign row first in `lock_authoring_scope`.* This reintroduces the deadlock against the retention trigger that the helper's comment records.
- *Drop the campaign lock.* This loses archive serialization.

### 6.3 Callers of the shared helper (traced at `6a5773d`)

There are 64 call sites across 28 command modules. `lock_operation_scope` ([_operations.py:30](../src/dnd_ai/commands/_operations.py#L30)) delegates to `lock_authoring_scope` (`:43`) and adds only the read of the campaign's timeline id.

**Direct calls of `lock_authoring_scope`** (29, in 13 modules):

- `dungeons`, `entity_lifecycle`, `item_definitions`, `item_instances`, `knowledge_definitions`, `locations`, `npc_portrayal`, `npcs`, `organizations`, `quest_definitions`, `religions`, `sources`, `world_relationships`.
- Player-character identity writes reach it through `player_characters` → `npcs.create_character_identity` / `update_character_identity`.

**Calls of `lock_operation_scope`** (35, in 15 modules):

- `campaign_clock`, `character_builds`, `dungeon_state`, `encounter_operations`, `encounter_preparation`, `event_corrections`, `item_operations`, `knowledge_runtime`, `parties`, `party_members`, `quest_runtime`, `session_authoring`, `session_play`, `travel`, `world_time`.

**What each caller does after the helper, checked by grep across all of them:**

- None locks `campaign.campaigns`, `security.campaign_memberships` or `security.membership_roles` again, in any mode. So no caller upgrades from the new mode later.
- Three read campaign columns without a lock: `character_builds.py:85` and `item_definitions.py:138` read `ruleset_version_id`; `item_instances.py:47` joins on it. `ruleset_version_id` and `timeline_id` are not editable by any application command (`update_campaign` writes only `name` and `description`), so a non-key `UPDATE` can't change them under the author.
- Every caller's later locks (entities, sessions, encounters, clock rows, advisory locks) are below the campaign row in the existing order and are unaffected.

Behavior change for callers: none, except that a concurrent recovery no longer makes them wait or fail.

### 6.4 Deterministic regressions (P0)

All of these run against PostgreSQL 18. Each uses the lock-wait harness already in the tree:

- `race(engine, hold, racer, blocked_on)` and `_wait_until_blocked` in `tests/database/test_content_authoring_concurrency.py`, which wait on a `pg_stat_activity` predicate;
- `_PidHold`, `_run_command` and `_wait_until_blocked_by` in `test_character_reveal_delegation_deadlocks.py`, which check `pg_blocking_pids`.

Where a test must stop a command *between two of its own statements*, it uses a `before_cursor_execute` listener on that command's connection. The listener blocks on a `threading.Event` when it sees the statement that marks the pause point, as the review probe did. Every test releases held locks on failure and reports a racer that finished before blocking, instead of waiting out a timeout.

1. **Author first, recovery second (the reproduced case).**
   - Setup: `_strand_the_campaign_for_recovery`, so the promoted member is a finite owner with `canon.edit`.
   - The author's real authoring command (for example `create_location`) is paused just before its campaign statement, while holding its membership `FOR SHARE`.
   - Start `recover_campaign_access_manager` for that user, and wait until `pg_blocking_pids` shows recovery blocked by the author. Then resume the author.
   - Expect: the author commits its write, then recovery commits; no 40P01; the promoted member holds the recovered role.
   - On `6a5773d` this test fails with 40P01.
2. **Recovery first, author second.**
   - Recovery is paused after its campaign `FOR NO KEY UPDATE`, before its membership statement.
   - The author's command runs to completion while recovery is paused. That directly shows `KEY SHARE` does not wait for `FOR NO KEY UPDATE`. Then resume recovery.
   - Expect: both commit.
   - On `6a5773d` the author blocks on the campaign row, and the test fails because the author is not complete while recovery is paused.
3. **Campaign archive still serializes, in both orders.**
   - (a) This is the existing `test_a_creation_waits_for_an_in_flight_campaign_archive_and_is_refused`, but its wait predicate `'%FROM campaign.campaigns WHERE campaign_id = %FOR SHARE%'` must become `'%FOR KEY SHARE%'`. `FOR KEY SHARE` does not contain the text `FOR SHARE`. Keep the assertions: `CampaignArchivedError`, nothing written.
   - (b) New: the author is paused after its campaign lock, and `archive_campaign` blocks on it (`pg_blocking_pids`). The author commits, then the archive commits.
4. **Role loss still serializes.** The existing tests `test_a_creation_waits_for_an_in_flight_role_revocation_and_is_refused` and `test_a_role_revocation_waits_for_an_in_flight_creation_and_the_write_stands` must pass unchanged. Add the variant where the revoked role is the built-in owner (the retention trigger fires at commit), with the author waiting at its role-row lock. Expect: refused with `CampaignNotAuthorizedError`, no deadlock.
5. **Membership end still serializes, in both orders (new).** `end_campaign_membership` against an authoring write by that member:
   - an end in flight makes the write wait at the membership lock, then refuse (404), with nothing written;
   - a write in flight makes the end wait, and the write stands.
6. **A deny is still ordered (new; protects D8 later).** `create_resource_grant` of a whole-character `campaign.view` deny for the author, held in flight, makes the author's command wait at the campaign `KEY SHARE`. That test asserts only the wait and the ordering. It asserts no outcome, because existing authoring commands don't consult per-character denies.
7. **Recovery serialization is unchanged.** Rerun `test_character_reveal_delegation_deadlocks.py` and `test_stranding_and_recovery.py` unchanged.

### 6.5 P0 acceptance and boundary

- **Code:** one line in `_content.py` (the lock mode), the helper's docstring and lock-order comment updated to name `KEY SHARE` and why, and the test changes in §6.4.
- **Docs:**
  - [SYSTEM_ARCHITECTURE.md](architecture/SYSTEM_ARCHITECTURE.md): line 315 ("campaign `FOR SHARE` (required `active`)"), and line 321 (the "takes `FOR SHARE` on the parent" rule, noting the campaign exception and its reason);
  - a DEF-014 entry in the defect register (reproduction, fix, regressions).
- **Checks:**
  - the new and modified tests;
  - `test_content_authoring_concurrency.py`, `test_scoped_roles_concurrency.py`, `test_authoring_concurrency.py`, the A1 suites (`test_campaign_owner_*.py`, `test_character_reveal_delegation*.py`) and `test_stranding_and_recovery.py`;
  - the full `pytest`;
  - `ruff format --check`, `ruff check`, `mypy src`, `git diff --check`.
- **Not in P0:** DEF-015, DEF-016, any A2 code, the four untracked plans, and push.
- **Commit locally and stop for independent review,** naming the parent and target SHAs.

### 6.6 Related findings that P0 does not fix

- **DEF-015 (proposed; reproduced 2026-11-07): adding a member to an access group against that member's authoring write.** Designed in §7 as prerequisite commit P1. The first candidate recorded here, membership locks before a campaign `FOR UPDATE`, was tested and **rejected**: it deadlocks with recovery (§7.4).
- **DEF-016 (proposed; found by reading, not tested): a per-character `canon.edit` deny is unreachable in the view-tier and inventory resolvers.** See §5.7a. Its fix is to read the `entity_id` key. That would reduce a GM's view of a character they are denied, so it needs its own decision and tests. It is outside P0 and A2.

---

## 7. Prerequisite commit P1 (for Sonnet, before A2a): DEF-015, adding an access-group member

**Status:** designed 2026-11-07 against `4dd56fd`; not implemented. It is one bounded commit on `phase15/completion`, reviewed on its own before any A2a code. It changes no schema, no API shape and no response body.

### 7.1 The defect (proposed DEF-015, reproduced)

**How it was reproduced.**

- **The probe.** A throwaway pytest module, deleted afterwards and never committed, ran on the suite's own disposable database. `postgres_engine` creates a fresh database per run, upgrades it to head and drops it afterwards. The server was local PostgreSQL 18.
- **Fixtures.** The probe reused P0's fixtures: an author whose only campaign role is a custom one with `canon.edit`, and `stranded` for recovery.
- **Each scenario:**
  1. Start the first command and pause it at a named statement, using a `before_cursor_execute` listener on its thread.
  2. Start the second command.
  3. Record whether `pg_blocking_pids` shows the second blocked by the first, or whether it finished while the first was paused.
  4. Release the first command and join both threads.
- **Variants.** The same scenarios ran against HEAD, the proposed correction (§7.3) and two rejected variants (§7.4).

| # | First command (paused) | Second command | HEAD `4dd56fd` | P1 (§7.3) |
|---|---|---|---|---|
| S1 | An author, holding its membership `FOR SHARE`, just before its campaign lock | Add that author to a group | Add blocked by the author, then **40P01** | Both commit |
| S2 | Add, before its second lock (HEAD: holds the campaign; P1: holds the memberships) | That member's authoring write | Author blocked by the add, then **40P01** | Both commit |
| S3 | Recovery of the member, holding the campaign `FOR NO KEY UPDATE`, before its membership statement | Add that member | Both commit (the add waits at the campaign) | Both commit (the add finishes while recovery is paused) |
| S4 | Add, before its second lock | Recovery of that member | Both commit | Both commit (recovery waits at the membership) |
| S5 | End of the added member's membership, after its role and membership locks | Add that member | **40P01** | The end commits; the add is refused with `MembershipNotActiveError` (409), nothing written |
| S6 | Add, before its second lock | End of that member's membership | **40P01** | Both commit; the end closes the new group row |
| S7 | A2a release lock prefix (authority rows S, membership `KEY SHARE`), before its campaign lock | Add the releaser | **40P01** | Both commit, **but the add does not wait for the release** |
| S8 | Add, before its second lock | The release prefix | **40P01** | Both commit; the release does not wait |
| S7b | As S7, with the release's membership `FOR SHARE` | Add the releaser | **40P01** | The add waits for the release; both commit; the release saw no group row |
| S8b | Add, before its second lock | The release prefix with membership `FOR SHARE` | **40P01** | The release waits for the add; both commit; **the release sees the new group row** |
| S9 | Add made by a second owner, just before its insert | End of that owner's membership | **40P01** | Both commit |
| S10 | End of the second owner's membership, after its locks | Add made by that owner | **40P01** | Both commit (see §7.9, residual 1) |
| S11 | `create_resource_grant` made by the member being added, after its campaign lock | Add that member | Both commit | Both commit |
| S12 | Add, before its second lock | That grant | Both commit | Both commit |
| S13 | Add, holding the campaign, before its account lock | Revocation of that member's role (retention trigger at commit) | Both commit | Both commit |
| S14 | Add by the owner of member M to group G1 | Add by M of the owner to group G2 | Both commit (serialized at the campaign) | Both commit (no wait) |
| S15 | Group deactivation, after its status update | Add to that group | The add is refused with `AccessGroupNotInCampaignError` (404, wrong class: §7.9, residual 2) | Unchanged; this statement is not edited |

**The original report understated the scope.** At HEAD, adding a member deadlocks with:

- that member's authoring write (S1, S2);
- ending that member's membership (S5, S6);
- ending the adding manager's own membership (S9, S10);
- A2a's release (S7, S8).

Recovery (S3, S4) works, because both commands take the campaign row first.

**Origin.** Commit `1a46b87` (the batch add) moved the campaign lock ahead of the membership locks. Before it, `6cbd12a` locked group, membership, campaign, then account. The module docstring and `test_access_group_concurrency.py`'s docstring still describe that older order.

**Grade (proposed):** 0 + 1 + 1 + 0 + 1 = **3, Low**.

- Exposure 0: not deployed.
- Impact 1: one request of the pair fails with an unclassified 500. A retry succeeds, nothing is written and nothing is disclosed.
- Triggerability 1: two ordinary manager or member actions with narrow timing.
- Detection 0.
- Blast radius 1: every authoring and operation command, and membership end.

### 7.2 Both lock sequences, traced at `4dd56fd`

**Adding members** (`POST …/access-groups/{group}/members`, [api/access_groups.py:528](../src/dnd_ai/api/access_groups.py#L528) → [access_groups.py:597](../src/dnd_ai/commands/access_groups.py#L597)):

1. With an `Idempotency-Key`, `begin_idempotent_request` inserts first. Its foreign keys take `KEY SHARE` on the actor's account and on the campaign row. Without a key, it takes nothing.
2. The group: `FOR UPDATE OF ag` (`:634`).
3. The campaign: `FOR UPDATE OF c` (`:660`).
4. For each member, in UUID order: the membership `FOR UPDATE OF cm`, joined to `membership_statuses` (`:685`); then the account `FOR UPDATE OF u` (`:722`).
5. For each member, an `INSERT INTO security.access_group_memberships`. Its foreign keys take `KEY SHARE` on the group and the member's membership (both already held) and on the **actor's membership**, through `added_by_membership_id`. That is the first lock on the actor's membership, and it comes after the campaign. The `BEFORE INSERT` scope trigger only reads.
6. The endpoint then:
   - reads `timeline_world_id` without a lock;
   - inserts one `audit.change_log` row per member, whose foreign key takes `KEY SHARE` on the actor's account;
   - updates its own idempotency row.
7. At commit, nothing more is locked. `access_group_memberships`, `audit.change_log` and `idempotent_requests` have no deferred trigger.

**The commands it meets:**

| Command | Locks, in order (commit-time locks last) |
|---|---|
| Authoring and operation writes (`lock_authoring_scope`, after P0) | Idempotency insert (`KEY SHARE` on the campaign and account) → world (S) → the actor's role rows and membership (S) → account (S) → campaign (`KEY SHARE`) → entities and the rest → audit insert (`KEY SHARE` on the account). Nothing further at commit for these rows |
| `end_campaign_membership` | The target's role rows (U) → its membership (U) → `UPDATE`s (the `ended_by_membership_id` foreign key takes `KEY SHARE` on the ender's membership) → closes the target's open `access_group_memberships` rows → delegation rows → at commit, the retention trigger takes the campaign row `FOR UPDATE` |
| `recover_campaign_access_manager` | Campaign (`FOR NO KEY UPDATE`) → the member's membership (U), or an insert → a status `UPDATE` when the status changes → role insert → at commit, the retention trigger takes the campaign `FOR UPDATE` only if a membership row was updated |
| `revoke_membership_role` / `change_membership_role` | Role row (U; `change` also takes the membership and role U) → at commit, the retention trigger takes the campaign `FOR UPDATE` |
| `create_resource_grant` | The grantee's membership (U) or group (U) → campaign (U) → the grantee's account (U) → target (U) → capability (U) → insert (the foreign key takes `KEY SHARE` on the **granter's** membership) |
| `remove_access_group_member` | The `access_group_memberships` row (U) only. Its `UPDATE` of `removed_at` changes no foreign-key column and takes no other lock |
| `deactivate_access_group`, `update_access_group`, `reactivate_access_group` | The group (U); reactivate then takes the campaign (U) |
| `create_access_group` | Campaign (U); the insert's foreign key is on the campaign row it already holds |

**The cycles at HEAD.**

- **S1/S2.** The add holds the campaign `FOR UPDATE` and wants the member's membership. The author holds that membership `FOR SHARE` and wants the campaign `KEY SHARE`, which conflicts with `FOR UPDATE`.
- **S5/S6.** The add holds the campaign and wants the membership. The end holds the membership and wants the campaign at commit.
- **S9/S10.** The add holds the campaign and wants `KEY SHARE` on the actor's membership for its insert. Ending the actor's membership holds that row `FOR UPDATE` and wants the campaign at commit.
- **S7/S8.** The same shape as S1/S2, with the release.

### 7.3 The correction: three lock changes in one command

**What changes.** Only `add_access_group_members`. Its new order:

1. **The group:** `FOR UPDATE OF ag`, with the group checks unchanged.
2. **The members' memberships,** in the existing UUID order, each `FOR NO KEY UPDATE`, in a **locking statement without a join**:

   ```sql
   SELECT campaign_id, ended_at, user_id, membership_status_id
   FROM security.campaign_memberships
   WHERE campaign_membership_id = :membership
   FOR NO KEY UPDATE
   ```

3. **The actor's membership** (`added_by_membership_id`): `FOR KEY SHARE`, the mode its foreign key takes anyway. This mirrors `_lock_foreign_key_targets` in [character_reveal.py](../src/dnd_ai/commands/character_reveal.py). It is harmless when the actor is also a member being added.
4. **The campaign:** `FOR KEY SHARE OF c`, with the `active` check and `CampaignNotActiveError` unchanged.
5. **Validation, per member, in UUID order, from the locked rows:**
   1. a row that is missing or belongs to another campaign → `MembershipNotInCampaignError`;
   2. the status, from an unlocked read of `security.membership_statuses` by id → `MembershipNotActiveError`;
   3. the account `FOR UPDATE OF u`, and its check, unchanged.
6. **The inserts,** unchanged.

**Error precedence is unchanged:** group, then campaign, then each member in UUID order (in the campaign, then active, then account active). The same request gets the same error class it gets today. The only differences are which rows are locked before the error is raised, and that a waiting request no longer fails with a 500.

**Why each piece is needed:**

| Piece | Without it | Evidence |
|---|---|---|
| Memberships before the campaign | The authoring, membership-end and release cycles remain (§7.2) | S1, S2, S5–S8 at HEAD |
| Campaign `KEY SHARE`, not `FOR UPDATE` | With memberships first and the campaign `FOR UPDATE`, recovery (campaign `FOR NO KEY UPDATE` → membership) deadlocks in both orders | S3/S4 under the variant "memberships first, campaign `FOR UPDATE`": 40P01 |
| Members `FOR NO KEY UPDATE`, not `FOR UPDATE` | `create_resource_grant` made *by* a member being added takes `KEY SHARE` on that member's membership at its insert, after its campaign `FOR UPDATE`. A `FOR UPDATE` held by the add while it waits for the campaign deadlocks with it. The reveal-delegation grant chose `FOR NO KEY UPDATE` for the same reason | S11/S12 under the variant "memberships `FOR UPDATE`, actor `KEY SHARE`, campaign `KEY SHARE`": 40P01 |
| The actor's membership locked before the campaign | The insert's foreign-key `KEY SHARE` on the actor comes after the campaign, so ending the actor's membership deadlocks with it | S9/S10 without it: 40P01 in every variant |
| A locking statement without a join | In READ COMMITTED, a `FOR … OF cm` statement joined to `membership_statuses` that waited on an updated row re-checks the join against the old status row and returns **no row**. An add that waited behind an end was then refused with `MembershipNotInCampaignError` (404) instead of `MembershipNotActiveError` (409). The reorder makes this wait reachable; at HEAD it ended in a deadlock instead | S5 under every joined variant: `MembershipNotInCampaignError`; P1: `MembershipNotActiveError` |

**What each mode still excludes:**

- **A member's `FOR NO KEY UPDATE`** conflicts with:
  - `FOR UPDATE`: ending the membership, recovery, role assignment and change, and a resource or relationship grant to that member;
  - `FOR NO KEY UPDATE`: a status `UPDATE`, a reveal-delegation grant to the member, and another add of the same member;
  - `FOR SHARE`: that member's authoring and operation writes, and A2a's release.

  It does not conflict with `KEY SHARE`, which the foreign keys of rows the member creates or is named in take.
- **The actor's `KEY SHARE`** conflicts only with `FOR UPDATE`: ending the actor's membership, recovery or role changes for the actor, and a grant to the actor.
- **The campaign `KEY SHARE`** conflicts with every campaign `FOR UPDATE` taker:
  - archive, reactivate and settings edits;
  - the retention trigger at commit;
  - `create_resource_grant` and `grant_character_relationship`;
  - `create_access_group` and `reactivate_access_group`;
  - `add_campaign_member` and a relinquishing transfer.

  So an add still cannot commit into an archived campaign. It does not conflict with recovery's `FOR NO KEY UPDATE`, nor with the `KEY SHARE` that authoring, delegation and the idempotency foreign key take.

**Preserved behaviour:**

| Protection | After P1 |
|---|---|
| **Group membership authorization:** the route requires `access.manage`; the group must be in the campaign and active; each member must be in the campaign, open, active and on an active account; the batch is atomic | Unchanged. The same checks run in the same order on rows locked before they are read. Fingerprint, response and audit are unchanged |
| **Membership end against an add** | Serialized at the member's membership in both orders (S5, S6). An add that waited is refused with 409. An end that waited closes the row the add inserted, because its `UPDATE` takes a fresh snapshot after its lock wait |
| **Role loss** | A revoked member's role rows are not locked by the add, and the revocation's commit-time campaign `FOR UPDATE` waits for the add's `KEY SHARE` while the add needs nothing the revocation holds (S13). `change_membership_role` takes the membership `FOR UPDATE`, so it serializes at the membership |
| **Recovery** | Its campaign `FOR NO KEY UPDATE` is compatible with the add's `KEY SHARE`. The two serialize at the promoted member's membership, in both orders (S3, S4). Recovery's code is unchanged |
| **Authoring** | Serialized at the member's membership (`FOR NO KEY UPDATE` against `FOR SHARE`) in both orders (S1, S2). The author's authorization is still re-checked under its own locks, so a deny added by the group is seen by an author that waited |
| **Account deactivation** | The account `FOR UPDATE` is unchanged and taken after the campaign, as today |
| **Overlapping adds** | The same group still serializes on the group row. For different groups, members are locked in UUID order, so no cycle is possible (`FOR NO KEY UPDATE` conflicts with itself). The actor's `KEY SHARE` conflicts with neither mode used by another add (S14) |
| **Archive** | The campaign `KEY SHARE` still waits for, and is waited on by, `FOR UPDATE` |

### 7.4 Rejected alternatives

- **Memberships first with the campaign still `FOR UPDATE`** (the candidate in the first §6.6 note). This deadlocks with recovery in both orders (S3, S4: 40P01), the same cycle A1 removed for the delegation grant.
- **Campaign `KEY SHARE` first, keeping its position.** The cycle with membership end remains, because the end's commit-time campaign `FOR UPDATE` conflicts with `KEY SHARE`. Found by trace, not probed.
- **Memberships `FOR UPDATE`, actor `KEY SHARE`, campaign `KEY SHARE`.** This deadlocks with a resource grant made by a member being added (S11, S12: 40P01).
- **Taking the campaign first in `lock_authoring_scope`.** This reverses P0's helper and its recorded retention-trigger deadlock.
- **Weakening authoring's membership lock to `KEY SHARE`.** That loses serialization against role and membership-status changes, and the D8 deny ordering.

### 7.5 Callers and neighbours checked

- **Callers of the changed function.**
  - `add_access_group_members` has one production caller: the add endpoint ([api/access_groups.py:572](../src/dnd_ai/api/access_groups.py#L572)).
  - `add_access_group_member` is a thin wrapper used only by tests.
  - The endpoint's idempotency insert, audit inserts and receipt keep their positions (§7.2).
  - `queries/access_overview.py` and `queries/audit_history.py` only name the command.
- **Removing a group member** (`remove_access_group_member`) is unaffected and is not edited. It locks only its own row and writes no foreign-key column.
  - Against an add of the same pair, the insert's partial unique index waits for the remover's transaction while the remover waits for nothing.
  - It needs no campaign or membership lock, because closing access stays available regardless of lifecycle, as the module docstring requires.
- **Group lifecycle.** `deactivate_access_group`, `update_access_group`, `reactivate_access_group` and `create_access_group` are unchanged. The first three serialize with an add on the group row. `create_access_group` locks no membership.
- **`create_resource_grant` with a group grantee** takes the group and then the campaign `FOR UPDATE`. That serializes with an add to the same group at the group row. With an add to another group, it serializes at the campaign (`FOR UPDATE` against `KEY SHARE`), and neither waits for anything else the other holds.
- **`end_campaign_membership`** closes the member's `access_group_memberships` rows. Covered by S5/S6, and by S9/S10 for the actor.
- **Documentation and comments that name the add's campaign `FOR UPDATE`** become inaccurate and change in P1 (§7.8):
  - P0's comment in [_content.py](../src/dnd_ai/commands/_content.py) ("the resource-grant, relationship and access-group writes");
  - [SYSTEM_ARCHITECTURE.md](architecture/SYSTEM_ARCHITECTURE.md) line 315;
  - [PHASE13E_ACCESS_CONTRACT.md](PHASE13E_ACCESS_CONTRACT.md) line 554;
  - the `access_groups.py` module docstring ("Lock ordering");
  - item 2 of `test_access_group_concurrency.py`'s docstring.
- **Existing tests that must pass unchanged:**
  - `test_access_group_concurrency.py` (every add test there runs the add to completion first, then shows the competitor blocked);
  - `test_api_access_groups.py`, including error-precedence and idempotency cases;
  - `test_resource_grant_concurrency.py`;
  - `test_authoring_scope_recovery_locks.py`;
  - `test_content_authoring_concurrency.py`;
  - `test_character_reveal_delegation_deadlocks.py`;
  - `test_stranding_and_recovery.py`.

### 7.6 Consequence for A2a: the release takes its membership `FOR SHARE`

With P1, an add no longer conflicts with any campaign lock a release holds.

- **With `KEY SHARE`** on the releaser's membership, a release does not conflict with the add's `FOR NO KEY UPDATE`. So an add of the releaser to a group carrying a deny could commit between the release's re-resolve and its write (S7, S8: neither waits).
- **With `FOR SHARE`**, they serialize at the membership and neither deadlocks (S7b, S8b). If the add commits first, the release's re-resolve sees the group row.

`FOR SHARE` is the mode `lock_authoring_scope` already takes on the same row. §5.8 records the release's other pairings under this mode; none of them inverts.

### 7.7 Race harness: failure cleanup (addresses the nonblocking P0 harness finding)

**The finding**, as the owner summarized it (its text is not in the repository): failure cleanup must release blockers and join worker commands before fixture teardown. In P0's module:

- `_paused` releases the pause on exit, but the worker threads started inside it are joined only on the success path.
- `observed_race` rolls the holder back on failure, but never joins its racer.

So after a failed assertion, `editor`, `stranded` and `fx` can tear down, deleting rows with `session_replication_role = replica`, while a worker transaction is still open or blocked. Teardown can then wait on that worker, or a daemon worker can outlive the test.

**P1 adds one test helper module**, `tests/lock_race_support.py`, alongside `tests/content_support.py`. It is used as a context manager inside the test body, so it exits before pytest begins any fixture teardown, whatever order the fixtures were requested in:

```python
with LockRace(engine) as race:
    pause = race.pause(thread_name="add", pattern=..., after=None)
    add = race.start("add", operation)
    pause.wait_reached(add)
    author = race.start("author", other_operation)
    race.wait_blocked_by(pause, author)
    pause.release()
    race.join_all()
```

**Its contract:**

1. `start` runs the operation in its own `engine.begin()` transaction on a named thread. It records the backend pid at the first statement, and its result or exception.
2. `pause` registers the `before_cursor_execute` listener as P0's `_Pause` does, keyed by thread name.
3. `hold` opens a held row lock on its own connection.
4. **On exit, success or failure, in this order:**
   1. Every pause that was not released by the test is put into abort mode and released. The paused worker raises inside its own transaction and rolls back, rather than committing half a scenario.
   2. Every hold is rolled back and closed.
   3. Every worker is joined, each with the existing 15-second bound.
   4. A worker still alive gets `pg_cancel_backend`, then `pg_terminate_backend`, on its recorded pid through a separate connection, and is joined again.
   5. The listeners are removed.
5. **Reporting.**
   - If the body raised, that exception propagates unchanged, and any cleanup problem is attached as a note, never replacing it.
   - If the body passed but a worker had to be cancelled or terminated, or never finished, the exit raises `AssertionError` naming the worker and `_waiting_sessions()`. A passing scenario with a stuck worker is a failure.
6. `wait_blocked_by` and `wait_reached` keep P0's behaviour. They follow the `pg_blocking_pids` chain, and report a worker that finished before blocking as it ended, instead of waiting out the clock.

**P1 also does two retrofits:**

- `test_authoring_scope_recovery_locks.py` uses `LockRace` in place of its own `_start` and `_paused`, with its 12 tests otherwise unchanged.
- `observed_race` (`test_content_authoring_concurrency.py`) joins its racer in a `finally`, after rolling the holder back, with the same bound.

**No committed test exercises the harness itself** (CLAUDE.md §6, §7.9). The implementer checks once by hand that a forced assertion failure inside a `LockRace` block leaves no session of the test database `idle in transaction` or waiting on a lock, and records that in the commit evidence.

### 7.8 P1 scope and acceptance criteria (for Sonnet)

**Code (one command):** `add_access_group_members` as specified in §7.3; its docstring states the lock order, the modes and why. Nothing else in `src/` changes, apart from the comment in `_content.py` (§7.5).

**New tests.** These go in `tests/database/test_access_group_member_add_locks.py`, using `LockRace` and real commands. Each wait is observed through `pg_blocking_pids` as blocked by the intended session, or the scenario asserts the second command finished while the first was paused. No longer timeouts are used, and no assertion relies on `lock_timeout`.

1. **The author first** (S1). `create_location` by a `canon.edit` member is paused before its campaign statement. Adding that member is blocked by the author. On release, both commit: the location exists, and the member's group row is open. At `4dd56fd` this fails with 40P01.
2. **The add first** (S2). The add is paused before its campaign statement (after its membership locks), and the author is blocked by the add. Both commit. At `4dd56fd` this fails with 40P01.
3. **Recovery, both orders** (S3, S4), with the `stranded` fixture.
   - Recovery paused after its campaign lock: an add of the promoted member finishes while recovery is paused, then recovery commits.
   - The add paused before its campaign statement: recovery is blocked by the add, and both commit.
   - The promoted member holds the owner role and the group row.
   - These pass at HEAD. They fail for the rejected variant with the campaign `FOR UPDATE`, which is what they guard against.
4. **Ending the added member's membership, both orders** (S5, S6).
   - End first: the add is blocked by the end, then refused with `MembershipNotActiveError`. No group row is written.
   - Add first: the end is blocked by the add, then both commit. The new group row is closed and listed in `removed_access_group_membership_ids`.
   - At `4dd56fd` both fail with 40P01. End-first asserts the error class, which pins the locking statement without a join.
5. **Ending the actor's membership, both orders** (S9, S10). The actor is a second built-in owner, and the original owner stays a non-expiring manager. Both commit in both orders. At `4dd56fd` both fail with 40P01. The end-first case records §7.9 residual 1 in its docstring.
6. **A resource grant made by a member being added, both orders** (S11, S12). `create_resource_grant` with `granted_by_membership_id` set to the member being added. Both commit. This guards the member mode against `FOR UPDATE`.
7. **Role revocation of the added member** (S13). The add is paused while holding the campaign; the revocation is blocked by the add at its commit-time campaign lock; both commit.
8. **Crossed adds** (S14). An add by A of B, and an add by B of A into another group: both commit.
9. **Through the API, one case.** `POST …/members` with an `Idempotency-Key`, against an author paused before its campaign lock. 201, one audit row and one receipt; the author's write stands. This covers the idempotency and audit foreign-key locks in §7.2.
10. **The existing suites pass unchanged** (§7.5). The docstring wording updated in `test_access_group_concurrency.py` is the only edit there.

**Docs, in the same commit:**

- the `access_groups.py` module and function docstrings;
- the `_content.py` comment;
- [SYSTEM_ARCHITECTURE.md](architecture/SYSTEM_ARCHITECTURE.md) line 315, saying that access-group member additions serialize with an author at the member's membership row, not the campaign row;
- [PHASE13E_ACCESS_CONTRACT.md](PHASE13E_ACCESS_CONTRACT.md) line 554 (the order and modes);
- a **DEF-015** entry in the defect register, with this reproduction, the grade, the fix and the regressions. DEF-016 and DEF-017 stay proposed in this plan until the owner decides whether to register them.

**Checks:**

- the new tests, which must fail at `4dd56fd` where the criteria above say so (run once against the parent and recorded);
- the suites in §7.5, plus `test_character_reveal_delegation*.py` and `test_campaign_owner_*.py`;
- the full `pytest`;
- `ruff format --check`, `ruff check`, `mypy src` and `git diff --check`.

**Not in P1:**

- A2a code; DEF-016; residuals 1 and 3 below;
- `create_resource_grant`, `grant_character_relationship`, recovery and every other command;
- the four untracked plans; push.

**Commit locally and stop for independent review,** naming the parent (`4dd56fd`, or P0's reviewed successor) and the target SHA.

### 7.9 Residuals found while tracing (not fixed by P1)

1. **The add's authorization is not re-checked under lock.**
   - **What happens.** The route judges `access.manage` before the command, without locks. An add that waits behind the end of the adding manager's own membership (S10), or behind the revocation of that manager's role, still commits, and `added_by_membership_id` then names an ended membership.
   - **Is it new?** No. It predates P1: at HEAD those pairs deadlock instead. `create_resource_grant` and the other `access.manage` commands behave the same way.
   - **What fixing it needs.** The DEF-013 pattern, applied to the access-management commands as a set: lock the actor's role rows and membership, then re-check at a fresh instant. This needs its own design. It is recorded here and not proposed as a DEF.
2. **Proposed DEF-017: a stale join in the group lock misclassifies a race.**
   - **What happens.** `add_access_group_members`, `update_access_group`, `deactivate_access_group` and `reactivate_access_group` lock the group with `FOR UPDATE OF ag` joined to `lifecycle_statuses`. A command that waited behind a deactivation gets no row and reports `AccessGroupNotInCampaignError` (404) instead of `AccessGroupNotActiveError` (409).
   - **Evidence.** Reproduced at HEAD as S15.
   - **Grade (proposed):** 0 + 0 + 1 + 0 + 0 = 1, Low.
   - **Fix.** Use the same pattern as §7.3: lock without a join, then read the status.
   - **Not fixed by P1.** P1 does not edit the group statement, so the defect is unchanged.
3. **Other late foreign-key locks on an actor's membership.** `create_resource_grant` (`granted_by_membership_id`) and `end_campaign_membership` (`ended_by_membership_id`) take `KEY SHARE` on the actor's membership after their target or campaign locks. P1 does not change them.
   - **Against an add.** P1's member mode `FOR NO KEY UPDATE` makes those late locks compatible with an add (S11, S12).
   - **Elsewhere.** Whether they cycle with other commands was not traced. That is a candidate for a later lock-order audit, not part of DEF-015.

---

## 8. A2a review correction A2a-R: making the D8 denies creatable (proposed DEF-018)

**Status:** designed 2026-11-07 by reading source at `0b4704c`. Not implemented, and no probe was run. It is one bounded commit on `phase15/completion`, on top of A2a, and the A2a review cannot close until it lands. It changes no schema, no route and no request or response shape: one response field is filled in where it was `null`. The owner answered Q1, Q2 and Q3 on 2026-11-07 (§8.8); the answers are applied below.

### 8.1 The defect

**The readers.** D8 and every existing character reader look for both denies under the `("entity_id", character_id)` key:

- [public_profiles.py:88](../src/dnd_ai/domain/public_profiles.py#L88) (`whole_character_denied`) and `:94` (`canon_edit_denied_for_character`, which also counts a stray `character_id` row);
- character detail, parties, relationships and sheet: [api/characters.py](../src/dnd_ai/api/characters.py) `:498`, `:625`, `:721`, `:875`;
- inventory: [api/access.py:513](../src/dnd_ai/api/access.py#L513);
- party rosters: [api/parties.py:167](../src/dnd_ai/api/parties.py#L167);
- event explanations: [api/event_explanations.py:200](../src/dnd_ai/api/event_explanations.py#L200);
- World Explorer search and reference mode: `_grant_denied_entity_ids` in [api/world_explorer.py:133](../src/dnd_ai/api/world_explorer.py#L133).

**The writer refuses both keys.**

- **`character_id` target.** The catalog allows only the nine `character.*` codes ([access.py:131](../src/dnd_ai/domain/access.py#L131), `:229`). `campaign.view` and `canon.edit` are refused with `ResourceGrantCapabilityNotGrantableError` (404).
- **`entity_id` target.** The catalog allows `campaign.view` and `canon.edit`. But the P-8 CTI guard ([access_grants.py:1063](../src/dnd_ai/commands/access_grants.py#L1063), applied at `:1192`–`:1214`) refuses any entity whose type is `character`, `npc` or `player_character`, with `TargetNotInCampaignWorldError` (404).

**The database permits it.** `ck_resource_grants_exactly_one_target`, the `entity_id → core.entities` foreign key and `enforce_resource_grant_scope()`, which checks only the world, all accept such a row. That is how the inventory tests and A2a's tests create these denies: directly, with `make_resource_grant`.

**Why the guard is wrong here, and only here.** Its rationale is that the read side keys off the dedicated column, so a grant in `entity_id` would be inert. That holds for `character.*` codes, which readers check under `character_id`. It is false for `campaign.view` and `canon.edit` on a character:

- every reader above checks them under `entity_id`;
- `character_id` cannot carry them at all.

So the guard blocks the only representation the readers use. The other own-column kinds (`event`, `quest`, `knowledge_item`) are unaffected: their readers do key the dedicated column, for example `resource_grant_targets(cap, "event_id")`.

**Consequence.** ADR 0021 §2.9's whole-character deny and D8's per-character `canon.edit` deny exist only as raw SQL. An owner cannot apply either through the API, and A2a's deny tests and races prove behaviour that no application path can reach.

**Grade (proposed):** 0 + 1 + 2 + 0 + 1 = **4, Medium**.

- Exposure 0: not deployed.
- Impact 1: a documented access restriction cannot be applied; nothing leaks.
- Triggerability 2: every attempt fails.
- Detection 0: the refusal is visible.
- Blast radius 1: every character.

### 8.2 The correction, and the alternatives rejected

**Recommended: narrow the CTI guard for exactly these two denies.** In `_validate_resource_grant_target`, an `entity_id` target whose entity is a character is accepted when the effect is `deny`. The capability catalog then confines it, as today, to `campaign.view` and `canon.edit`. Everything else the guard refuses stays refused.

- **The change:**
  - `create_resource_grant` passes `effect` to `_validate_resource_grant_target`;
  - add `_CHARACTER_ENTITY_TYPE_CODES = frozenset({"character", "npc", "player_character"})`, the subset of `_OWN_COLUMN_ENTITY_TYPE_CODES` with a `character.characters` row;
  - the guard raises unless `entity_type_code in _CHARACTER_ENTITY_TYPE_CODES and effect == "deny"`.
- **Lock order and error precedence are unchanged:** grantee, campaign, account, target `FOR UPDATE`, capability.
- **The resulting refusals:**
  - an allow on a character entity is still refused at the target step (404);
  - a `character.*` deny under `entity_id` passes the target step and is refused at the capability step (404);
  - both are non-disclosing and write nothing.

**Rejected alternatives.**

| Alternative | Why rejected |
|---|---|
| **B.** Add `campaign.view` and `canon.edit` to the `character_id` catalog, and have readers, or `resolve_access_context`, read both keys | Two representations of one fact. `ux_resource_grants_active` cannot detect a deny duplicated across keys. Ten or more readers, or a resolver-wide remap, change, as do `resource_grant_targets(…, "entity_id")` sets, World Explorer search, the portal's duplicate detection and the overview's `target_type` |
| **C.** Accept the request under `character_id` and store it under `entity_id` | The stored row and the audit's `target_kind` would contradict the request; the portal's duplicate detection compares the request's target type |
| **D.** Remove the guard for characters entirely, allows included | Creates allow rows that every reader ignores today and that would silently become authority under a careless DEF-016 fix (§8.4). See Q1 |

### 8.3 Valid combinations after the correction

| Target column | Target entity | Capability | Effect | Before | After |
|---|---|---|---|---|---|
| `entity_id` | character, npc or player character | `campaign.view` | `deny` | Refused, 404 | **Accepted**: the whole-character deny (ADR 0021 §2.9; D8 item 4) |
| `entity_id` | character, npc or player character | `canon.edit` | `deny` | Refused, 404 | **Accepted**: the `canon.edit` deny on the character (D8 item 5) |
| `entity_id` | character, npc or player character | `campaign.view` or `canon.edit` | `allow` | Refused, 404 | Refused, 404 (Q1) |
| `entity_id` | character, npc or player character | any `character.*` code | either | Refused, 404 | Refused, 404 (catalog) |
| `entity_id` | event, quest or knowledge item | any | either | Refused, 404 | Unchanged |
| `entity_id` | any other entity (location, item, organization, …) | `campaign.view` or `canon.edit` | either | Accepted | Unchanged |
| `character_id` | a character | a `character.*` code | either | Accepted | Unchanged |
| `character_id` | a character | `campaign.view` or `canon.edit` | either | Refused, 404 | Unchanged (the catalog) |
| any | any | `character.reveal`, `access.manage`, `import.approve`, `rules_source.manage` | either | Refused | Unchanged (the catalog; A1's trigger for `character.reveal`) |

### 8.4 Who, scope, lifecycle, duplicates, revocation, existing rows

- **Who may create a deny.** Any caller who passes the route filter `access.manage`, on `POST /campaigns/{id}/resource-grants`, for a membership or an access-group grantee. Today that means the built-in owners: custom `access.manage` has no application path (A1 F1). No new gate is added.
  - An owner may deny a co-owner, or themselves. D8 item 4 already says the whole-character deny binds an owner.
  - A denied owner keeps `access.manage` (a resource deny never touches it, migration 080's comment on `effect`), so they can still revoke the deny.
- **Grantee eligibility is unchanged:** an open, active membership on an active account, or an active group, in the route campaign.
- **Campaign scope.** The row carries the route campaign, and `resolve_access_context` reads only that campaign's grants. A deny in campaign A has no effect on the same character's profile or reads in campaign B of the same world.
- **World scope.** The character must belong to the campaign's world. The command checks it, and the scope trigger checks it again; a character from another world is 404.
- **Timeline scope.** The command writes `timeline_id = NULL`, so the deny applies on the campaign's own timeline.
- **Lifecycle.**
  - **At creation:** the character must be active, as for every entity target today (archived → 404). A non-canon character is accepted; the profile routes already 404 it.
  - **Later:** the resolver ignores grants whose target is not active. A deny on a character archived later stops applying while it is archived, and applies again on reactivation. For a deny that is fail-closed. A save or release of an archived character is refused anyway (409 `public_profile_character_not_active`).
- **Duplicates.** `ux_resource_grants_active` (grantee, all target columns, `timeline_id`, capability, effect; `NULLS NOT DISTINCT`) makes an identical active deny a 409. These are distinct rows, and all of them count, with deny winning in `grant_effects`:
  - a deny next to a raw row that has `timeline_id` set;
  - a deny next to a stray `character_id` `canon.edit` deny;
  - one membership deny plus one group deny.
- **Revocation.** It is unchanged, by id, through `POST …/resource-grants/{id}/revoke`, and takes effect on the next request (`AccessContext` is resolved per request).
- **Existing rows.** None can have come from the command since checkpoint 12 introduced the guard. Rows written before that, or by direct SQL, keep their present meaning:
  - their denies already apply;
  - allows on a character under `entity_id` stay inert (below);
  - the overview now names their character (§8.5).

  No migration and no backfill.
- **Access-group changes take effect on the next request.** The resolver counts a group deny only through an open `access_group_memberships` row of an active group. So:
  - adding a member to the group denies them on their next request;
  - removing them, or deactivating the group (which revokes its grants), lifts the deny;
  - reactivating the group does not restore the revoked grants.
- **Does the correction enable new allow grants? No.** Under Q1's recommended answer it creates no allow path. If the owner instead permits allows:
  - a `campaign.view` allow under `entity_id` makes `has_capability` true where the baseline is false, which is inert today, because every route also requires role `campaign.view`;
  - a `canon.edit` allow is read today only by `has_effective_character_canon_edit`, which ignores allows (D8 item 2 is kept either way);
  - but DEF-016's view-tier and inventory checks would turn such an allow into GM-tier visibility if they were ever switched to `entity_id` without restricting them to denies.

  The deny-only rule removes that trap.
- **D8 item 2 is preserved.** `has_effective_character_canon_edit` requires role `canon.edit`, and no change here touches it. The existing test `test_an_allow_grant_of_canon_edit_does_not_confer_editing_or_reading` keeps its raw allow row (stray-row defence) and stays.

### 8.5 Affected routes, options, explanations, resolvers

| Surface | Change |
|---|---|
| `POST /campaigns/{id}/resource-grants` ([api/access_grants.py:457](../src/dnd_ai/api/access_grants.py#L457)), membership and group grantees | Accepts the two new combinations. Request, response, fingerprint (`campaign_id` plus body) and audit (`target_kind: "entity_id"`, `effect: "deny"`) are unchanged |
| `POST …/resource-grants/{id}/revoke` | Unchanged |
| Grant options (`list_grantable_resource_capabilities`, [queries/access_overview.py:553](../src/dnd_ai/queries/access_overview.py#L553)) | Unchanged. `(campaign.view, entity)` and `(canon.edit, entity)` are already listed, and the character-and-deny sub-rule is finer than its `(code, target_type)` grain. Its docstring gains one sentence naming the sub-rule |
| `GET …/access-overview`: member grants (`:404`) and group grants (`:790`) | `target_display_name` is filled in for an `entity_id` target that is a character (`LEFT JOIN character.characters` on `rg.entity_id`), using the same audience-safe `canonical_name` rule as a `character_id` target. `target_type` stays `"entity"`, so the portal's duplicate detection keeps working |
| `GET …/members/{id}/effective-access`: the direct-grant query (`:230`) and the group-grant query (`:300`) of [queries/effective_access.py](../src/dnd_ai/queries/effective_access.py), each feeding both sources and denials | The same rule. A whole-character deny lists as `campaign.view — <character>`; a `canon.edit` deny as `canon.edit — <character>` |
| Resolvers: `resolve_access_context`, `has_capability`, `resource_grant_targets`, `public_profiles`, and the readers in §8.1 | No change. They already read `entity_id`; the deny becomes reachable for them |
| DEF-016 sites (`resolve_character_view_tier` at [api/access.py:482](../src/dnd_ai/api/access.py#L482); inventory at `:515`) | No change (Q3). They read `canon.edit` under `character_id`, so a `canon.edit` deny does not lower a GM's view tier or inventory access. This is now reachable, not hypothetical |
| Audit history | No change; it labels grants by capability, effect and grantee, never by target |
| Portal | No change in A2a-R (Q2). Its `entity` selector deliberately excludes characters ([ResourceTargetSelector.tsx:38](../portal/src/components/ResourceTargetSelector.tsx#L38)); its `character` type maps to `character_id`, whose catalog refuses these codes. So the portal cannot create these denies until it changes |
| Docs | `access_grants.py` module docstring and the guard comment; the catalog comment in `domain/access.py` (for characters, `campaign.view` and `canon.edit` are read under `entity_id`); `test_resource_grant_target_column.py`'s docstring; [PHASE13E_ACCESS_CONTRACT.md](PHASE13E_ACCESS_CONTRACT.md) resource-grant section and §3v ("creatable through `POST …/resource-grants` with `entity_id`, effect `deny`"); this plan's A2a record; a **DEF-018** entry in the defect register |

### 8.6 Tests

**Command level** (`tests/database/test_resource_grant_target_column.py`):

1. `entity_id` naming a `character`, an `npc` and a `player_character` entity:
   - a `campaign.view` deny and a `canon.edit` deny are each accepted;
   - the row has the entity in `entity_id`, `character_id` null, `timeline_id` null and `effect = 'deny'`.
2. The same targets with `allow` are refused with `TargetNotInCampaignWorldError`. The existing `test_entity_id_rejects_a_character_target` stays, and a `canon.edit` variant is added.
3. A `character.view_full` deny under `entity_id` on a character is refused with `ResourceGrantCapabilityNotGrantableError`.
4. Quest, event and knowledge-item entities are still refused under `entity_id`, for a deny too.
5. An archived character, and a character from another world, are refused.
6. An identical second active deny is a unique-index `IntegrityError`. After the first is revoked, the same deny can be created again.

**HTTP** (new `tests/database/test_character_public_profile_grant_denies.py`, on the `Gate`/`Members` fixtures used by `test_character_public_profile_api.py`):

- Every deny in this file is created with `POST /campaigns/{id}/resource-grants` by an access manager, never with `make_resource_grant`, and lifted with `POST …/resource-grants/{id}/revoke`.
- "Nothing written" means no draft or release row change and no audit row.

1. **The grant route itself.**
   - A whole-character deny for a member: 201, with the row and the audit `changed_fields` as above.
   - The same `Idempotency-Key` and body replays the same `resource_grant_id`, with one row and one audit row.
   - The same key with another body is the idempotency 409.
   - Without a key, a duplicate is 409.
   - The `allow` body is 404, with nothing written.
   - A `character.view_full` deny under `entity_id` is 404.
   - A group grantee gets 201.
   - A player's attempt is refused by the route filter.
2. **A whole-character deny on an owner (`o1`, created by `o2`).**
   - `GET` profile and `GET` release are 404.
   - Draft save is 404, and release is 404, with nothing written.
   - A release retried with an `Idempotency-Key` first used before the deny is 404, not a replay.
   - After revocation: `GET` is 200, and that key replays the stored 201 (same release, no new row).
3. **The same for a delegated GM**, and for the deny created by the owner against themselves; the owner can still revoke it.
4. **A `canon.edit` deny on an owner.**
   - `GET` is 200 with `can_edit: false` and `can_release: true`.
   - Draft save is 403 `public_profile_edit_denied`, with nothing written. A save retried with a pre-deny key is also 403, not a replay.
   - Release is 201.
   - After revocation, the save key replays.
5. **A `canon.edit` deny on an assistant GM** (no reveal authority): `GET` 404 and save 404.
6. **Campaign scope.** A deny in campaign A leaves campaign B's GM free to read, save and release B's profile of the same character.
7. **The deny is the one other readers honour.** `GET /campaigns/{id}/characters/{character}` is 404 for the denied member and 200 for an undenied GM. This pins that the created key matches an existing reader.
8. **Explanations.**
   - The access overview shows the deny (member and group) with `target_type: "entity"` and the character's name.
   - The effective-access explanation lists it under `denials` with the name.
   - A non-character `entity_id` grant still has `target_display_name: null`.

**Access-group changes take effect on the next request (HTTP).**

9. **A group holding a whole-character deny** (created through the route with `grantee_access_group_id`). A delegated GM outside it reads (200). Then:
   - `POST …/access-groups/{group}/members` adds them, and the next `GET`, save and release are 404; a keyed release retry is 404.
   - `POST …/access-group-memberships/{id}/remove` removes them, and the next `GET` is 200, the keyed retry replays, and a new release is 201.
10. **Deactivating that group** lifts the deny on the next request. Reactivating it does not restore the deny, because its grant stays revoked. A new grant restores it.
11. **A group holding a `canon.edit` deny.** Adding an owner makes the next save 403 while release stays 201; removing them makes the next save 200.

**Concurrency** (`tests/database/test_character_public_profile_concurrency.py`, `LockRace`):

12. `_group_with_a_whole_character_deny` creates its grant with `create_resource_grant`, not `make_resource_grant`. The races themselves are unchanged.
13. **The races A2a criterion 6 had to substitute, now possible:** `create_resource_grant` of a whole-character deny naming the character, against a release and against a draft save, in both orders, for a membership grantee and for a group the actor belongs to. Expected:
    - **deny first:** the command waits, then is refused (404) with nothing written;
    - **command first:** the grant waits, then both commit.

    **Lock trace, with no cycle:**
    - **The grant:** grantee membership U (or group U) → campaign U → account U → character entity U → capability → insert.
    - **The release:** authority rows S → membership S → campaign KS → entity KS → draft U.
    - **The save:** `lock_authoring_scope` (… → campaign KS) → entity S → draft U.
    - **Where they meet:** a membership grantee serializes at the membership; a group grantee serializes at the campaign row.

**Existing suites, passing unchanged except where named:**

- `test_resource_grant_target_column.py` (the docstring and the added cases);
- `test_api_access_grants.py`, `test_resource_grant_concurrency.py`, `test_access_resolution.py`;
- `test_api_characters_inventory.py`;
- the A2a suites. In `test_character_public_profile_api.py`, the `deny()` helper switches to the route for `entity_id` denies and keeps direct SQL only for a stray `character_id` row and an allow row, which the application cannot create.

### 8.7 A2a-R scope and acceptance (for Sonnet)

- **Code.**
  - `create_resource_grant` / `_validate_resource_grant_target` (the `effect` parameter, `_CHARACTER_ENTITY_TYPE_CODES`, the narrowed guard and its comment);
  - the two `access_overview` queries and the two `effective_access` queries (the character name for a character under `entity_id`);
  - the docstrings and comments listed in §8.5.
  - Nothing else in `src/`.
- **Not in A2a-R:**
  - the portal (Q2), DEF-016 (Q3), DEF-017, A2b and later slices;
  - any migration; any change to D8's policy code;
  - push.
- **Tests:** §8.6. The new command and HTTP tests must fail at `0b4704c` where they create a deny through the command. Run them once against the parent and record the result.
- **Docs:** §8.5, plus the DEF-018 register entry. If the owner answers Q3 by registering DEF-016, that entry is recorded too, unfixed.
- **Checks:**
  - the focused suites, then the full `pytest`;
  - `ruff format --check`, `ruff check`, `mypy src`, `git diff --check`.
- **Commit locally and stop for independent review,** naming the parent (`0b4704c`) and the target SHA. Then rerun the A2a review's open items.

### 8.8 Policy points D8 does not settle

- **Q1 — May allow grants of `campaign.view` / `canon.edit` name a character? Owner's answer (2026-11-07): no, deny-only, as recommended.**
  - D8 settles only that an allow cannot confer draft editing. It is silent on whether an allow row may exist.
  - Deny-only keeps the CTI guard's purpose (no inert grants shown as active) and creates no allow path anywhere. It leaves no allow rows for a future reader to promote by mistake (§8.4).
  - The alternative accepts allows that do nothing today.
- **Q2 — Must the portal offer these denies in this correction? Owner's answer (2026-11-07): no; the portal controls wait for A6.** The application API offers them in A2a-R; the portal control follows with A6, which already owns the profile and effective-access UI. If the owner wants the portal control now, A2a-R grows by a portal change: the `entity` selector admits characters for a deny of these two codes, and requests map to `entity_id`.
- **Q3 — Should a `canon.edit` deny on a character also lower a GM's view tier or inventory access (DEF-016), or block other character authoring? Owner's answer (2026-11-07): not in A2a-R. The deny's contract here covers public-profile drafting only; DEF-016 is registered for a separate decision about other character authoring, view tiers and inventory.**
  - D8 limits the deny to the profile draft's edit and read path.
  - The view tier, inventory and identity authoring keep their current behaviour, which A2a-R makes reachable. So register DEF-016 now, and decide it separately.
  - The contract text in §3v and the explanation label should say the deny applies to the public-profile draft, so an owner does not expect more.

---

## Decisions still needed

- **D1: Public profile scope. Approved by the owner (recorded 2026-11-07).** Public-profile drafts and releases belong to a campaign. Applied in §5.1.
- **D2: Who edits the draft. Approved by the owner (recorded 2026-11-07).**
  - Campaign `canon.edit` holders may edit drafts.
  - A release requires `character.reveal` authority.
  - Copying legacy text requires existing permission to read that text.

  Applied in §5.1, §5.7 and §5.10. D7 asks a follow-on question that D2 does not answer.
- **D3: `access.manage` can create a campaign owner.** **Resolved 2026-11-06 (owner-approved; ownership gate implemented as the first A1 change, see [the A1 design](PHASE14_15_P03A_A1_OWNERSHIP_AUTHORITY_DESIGN_2026-11-06.md) §5).** Original question: Assigning a role, adding a member and transferring ownership are all gated only on `access.manage` ([api/memberships.py:260](../src/dnd_ai/api/memberships.py#L260), [:629](../src/dnd_ai/api/memberships.py#L629)). So a custom `access.manage` holder could give themselves `campaign_owner` and with it direct reveal authority. That contradicts "custom `access.manage` alone confers no release authority."
  - Today this can't happen in practice: only `campaign_owner` holds `access.manage`, and no app path creates custom role capabilities.
  - Closing it means restricting `campaign_owner` assignment to current owners, which changes ADR 0020 transfer behavior.
  - Path trace, recommended gate, exact owner decision and regressions: [PHASE14_15_P03A_A1_OWNERSHIP_AUTHORITY_DESIGN_2026-11-06.md](PHASE14_15_P03A_A1_OWNERSHIP_AUTHORITY_DESIGN_2026-11-06.md).
- **D4: Party roster exception.** P03-A requires one policy for every roster, and linking into a party is not a revelation. But the roster deliberately shows names without discovery, and applying discovery would hide party-mates' names from players.
- **D5: Names in discovery cards.** Every discovery consumer renders `core.entities.canonical_name` and `summary`. These are classified `PUBLIC_WORLD` ([data_classification.py:143](../src/dnd_ai/domain/data_classification.py#L143)), but OD-17 says audiences see only deliberately released versions.

  **Recommend:** accept the canonical name and summary as the discovery label, and show them on the release form. The alternative is substituting a released display name across every consumer.

  **What D5 decides for A2:**
  - **(a), recommended:** a release carries no name or summary. The GM read returns the canonical name and summary read-only as "the label audiences will see", so the releaser sees it before releasing.
  - **(b):** add `public_display_name` and possibly `public_summary` to both profile tables as nullable columns. Decide whether a release requires the name. A3 and A4 then substitute it in every consumer listed in §3, which is the large part.

  Either answer is additive to A2a's tables, so D5 does not block A2a. It blocks A3's discovery bundle and A4's response shape.
- **D6: Species and size in the public tier (new, 2026-11-07).** §3 and the A4 row say the public tier shows no species or size "unless released", but nothing defines how they are released. They are definition inputs, not derived mechanics, so OD-17 does not exclude them.

  **Recommend:** a per-release opt-in, off by default. The draft holds `shows_species` and `shows_size`. When a flag is set, the release snapshots `released_species_id` and `released_size_category` from the definition at release time. Later identity edits then reach audiences only through a new release.

  The alternative is never showing them in the public tier. Either answer is additive to A2a and blocks only A4.
- **D7: Copied NPC legacy text and draft readers (new, 2026-11-07).** Reading legacy text needs different permissions for each kind of character (§5.10 trace). An NPC's text needs campaign `canon.edit` **and** world `world.canon.read_private`; a player character's needs `canon.edit` only. Drafts are readable by every campaign `canon.edit` holder. Under D2, a GM who holds `world.canon.read_private` may copy an NPC's background into the draft. A campaign-only GM without that world capability could then read world-private text the existing read refuses them. D2 says who may copy, but not who may read the copy.

  **Recommend:** withhold until released.
  - A draft field whose origin is an NPC legacy field is withheld from any draft reader who fails that kind's read rule. The reader sees `withheld: true` and the origin, never the text.
  - Such a reader may only clear the field or replace it entirely. A replacement resets the origin to `authored`.
  - A release requires the releaser to be able to read every field it publishes. Otherwise it is refused with 403 `world_authority_required` and nothing is written.

  The alternative is that a copy is a deliberate disclosure to the campaign's draft readers. Player-character text is unaffected under either answer, because its read rule equals the draft-edit rule. D7 blocks A2b only.
- **D8: Draft and release reads, and denies. Approved by the owner (recorded 2026-11-07), as proposed.** Policy, detailed in §5.1 and §5.7a:
  1. **Read.** A member may read the draft and the release snapshots if they hold effective character-scoped `canon.edit`, **or** current `character.reveal` authority. Reveal authority confers reading only, never editing.
  2. **Edit.** Editing requires effective character-scoped `canon.edit`: role `canon.edit`, re-checked under lock, with no whole-character deny and no `canon.edit` deny on the character. A per-character `canon.edit` *allow* grant does not confer editing without role `canon.edit`.
  3. **Release.** Releasing requires `character.reveal` authority, unchanged from D2.
  4. **Whole-character deny.** A whole-character `campaign.view` deny blocks reading, editing and releasing for every source, the owner included (ADR 0021 §2.9).
  5. **`canon.edit` deny on the character.** It blocks editing and removes only the `canon.edit` read path. Reading through reveal authority and releasing are unaffected (§2.9: "An operation-specific deny blocks only that operation").
  6. **No per-character release deny.** None exists, because A1's trigger refuses any resource grant naming `character.reveal`. Adding one is a separate extension.
  7. **D7 is separate** and unchanged.

  **Approved.** Today every reveal holder already holds role `canon.edit`, so the only practical difference from "only `canon.edit` holders read drafts" is the per-character `canon.edit` deny case in item 5.

  **The alternative** keeps reading limited to `canon.edit` holders. A reveal holder with a `canon.edit` deny on a character could then not read, and so could not release, that character's profile; the deny would block two operations.

  D8 decided A2a's route filters and its read, edit and release checks; those are now fixed as written above, including criteria 3, 4 and 14.

---

## Next slice: A2a acceptance criteria

A2a is the §5 design without the copy aid, D5/D6 columns, portal or revelations. It starts on top of the reviewed P0 and P1 commits, with D8 approved as proposed (criteria 3, 4 and 14 follow it). Database and API tests use namespaced fixtures, including the `Gate` fixture's custom `access.manage` holder.

1. **Migration.** `142_character_public_profiles` upgrades and downgrades on PostgreSQL 18, with a migration test in the style of `test_character_reveal_delegations_migration.py`. After the upgrade, existing characters have no draft or release.
2. **Constraints and triggers:**
   - releases refuse UPDATE, DELETE and TRUNCATE;
   - `version_number` and `from_draft_row_version` are unique per profile;
   - the composite foreign key refuses a release naming another campaign's or another character's profile;
   - the scope triggers refuse a character from another world, a membership or delegation from another campaign, and a delegation whose grantee is not the releaser;
   - the origin rules hold;
   - `test_entity_reference_classification.py` passes with the two `BLOCKING` entries, and a character with a release cannot be physically deleted.
3. **Draft save:**
   - create, update and no-op (`changed: false`, no `row_version` bump, no audit);
   - partial updates and explicit `null`;
   - 409 `stale_write` for a stale token and for a lost first-save race;
   - allowed for the owner, a GM and an assistant GM; refused for a player or observer by the route filter;
   - a `canon.edit` deny on the character (an `entity_id` grant) refuses the save. A reveal holder gets 403 `public_profile_edit_denied`; an assistant GM with no read path gets 404. Nothing is written in either case;
   - a whole-character deny refuses the save with 404;
   - a player holding only an `allow` grant of `canon.edit` on the character is refused;
   - a character outside the world, or not canon, gets 404; an archived one gets 409 `public_profile_character_not_active`;
   - an `Idempotency-Key` replay writes nothing;
   - campaign A's and campaign B's drafts for one character are independent.
4. **Release authority:**
   - the owner gets 201 with `authority_source = owner`; a delegated GM gets 201 with the delegation's id;
   - 403 `character_reveal_required`, with no row and no audit, for: an assistant GM; a GM holding `canon.edit` without a delegation; the custom `access.manage` holder; a GM whose delegation was revoked; a GM whose `gm` assignment was revoked or has expired;
   - B's owner on A's route gets 404;
   - a whole-character deny on the releaser gives 404 with nothing written, even when a release of that draft version already exists (no natural-retry disclosure);
   - a `canon.edit` deny on the character does not stop an owner or delegated GM from releasing.
5. **Release semantics:**
   - the snapshot equals the draft at `expected_draft_row_version`;
   - versions run 1..n without gaps;
   - a release leaves the draft's `row_version` unchanged;
   - a release whose fields are both null is allowed;
   - 409 `public_profile_draft_missing`; 409 `stale_write`; and a natural retry returning 200 `created: false` with `is_latest` (§5.5, §5.9).
6. **Concurrency.** Use the deterministic lock-wait harness (`pg_stat_activity` / `pg_blocking_pids`, as in A1). Cover:
   - every row of the §5.9 table;
   - revoking the delegation against a release, in both orders;
   - revoking the releaser's `gm` role against a release, in both orders;
   - a relinquishing transfer by the releasing owner;
   - a relinquishing transfer to a releasing GM;
   - the caller's finite owner assignment expiring during the release's lock wait (403, nothing written);
   - archiving the character against a release;
   - `create_resource_grant` to the releaser naming the character, against a release, in both orders. This pins the corrected lock order in §5.8; with the first design's order it deadlocks;
   - `create_resource_grant` of a whole-character deny, against a draft save and against a release. The deny that commits first is honoured (404, nothing written), and one that comes second waits for the command.
   - **Adding the releaser to an access group that holds a whole-character deny on the character, against a release, in both orders (after P1; §5.8, §7.6):**
     - **Release first.** The release is paused after its membership `FOR SHARE`, before its campaign lock. The add is blocked by the release, observed through `pg_blocking_pids`. On release: the release commits (201), then the add commits.
     - **Add first.** The add is paused after its membership locks, before its campaign lock. The release is blocked by the add. On release, the add commits, and the release's re-resolve sees the group deny: 404, no release row and no audit row.
     - Neither order deadlocks. The release must hold its membership `FOR SHARE`, not `KEY SHARE`; with `KEY SHARE` neither waits, and the add-first case can release despite the deny (probe S7/S8).
   - The same pair against a draft save, in both orders. The save is refused with 404 when the add commits first.

   No scenario deadlocks.
7. **Releases outlive authority.** After the delegation is revoked, and after the releasing owner relinquishes ownership, earlier releases are unchanged and still listed, and a new release is refused.
8. **Marker sweep of response bodies.** The draft text and the release text carry distinct markers. Read as each of these:
   - a player with only `campaign.view`;
   - a player with `view_full` through a relationship;
   - an observer;
   - campaign B's GM.

   Check these surfaces: character detail, world explorer list, search and counts, bootstrap, the sheet, inventory, relationships, the session roster, encounter reads and Knowledge. No response body contains either marker. Campaign B's GM gets 404 from A's profile routes.
9. **Structural tests:**
   - which modules may reference which table (§5.11);
   - the profile command and query modules import no sheet, calculation or rules module;
   - the classification registry covers every new column;
   - the Phase 15 route manifest lists the four new routes.
10. **Audit.** One row per real change. No profile text in `changed_fields`. No row for a no-op, a refusal or a replay. No `core.entity_revisions` row.
11. **Docs updated in the same change:**
    - `DATABASE_MODEL` (campaign schema);
    - `DOMAIN_MODEL` (public-profile draft, release, field origin);
    - `ENTITY_LIFECYCLE` command list;
    - `PHASE13E_ACCESS_CONTRACT` (release authority and `character_reveal_required`);
    - this plan's A2 status.
12. **Checks.**
    - Rerun A1's regressions: `test_character_reveal_delegation*.py`, `test_campaign_owner_*.py`.
    - Rerun P0's regressions (§6.4) and P1's (§7.8).
    - The A2a race tests use `LockRace` (§7.7).
    - Run `ruff format --check`, `ruff check` and `mypy src`.
    - Run the focused tests, then the full `pytest`, then migration up/down, then `git diff --check`.
    - Run CI on the final head.
    - Stop for an independent review that names the parent and target SHAs.
13. **Idempotency across characters (review correction).** The fingerprint covers `character_id` (§5.7).
    - **Release.** Release character X with key K and body B: 201. Then post the same K and the same B to character Y's release route: the non-disclosing idempotency 409. Y has no release row and no audit row, and its GM read shows no release. The stored X response is unchanged.
    - **Draft save.** The same check for the draft save: K and B on X, then K and B on Y, gives 409, and Y has no draft.
    - **Same character still replays.** K and B repeated on X replays X's stored response.
14. **D8 reads.**
    - Allowed:
      - a reveal holder with a `canon.edit` deny on the character reads the draft and releases (200, `can_edit: false`, `can_release: true`);
      - an assistant GM reads (`can_release: false`).
    - Refused with 404:
      - a player;
      - an observer;
      - campaign B's GM;
      - a whole-character-denied owner.

## A2a implementation record (2026-11-07)

**Parent:** `3b3d637` (the design commit; its parent is P1, `edf46ca`). The implementation is one local commit on `phase15/completion`; nothing is pushed and CI is pending.

**What was built.**

- **Migration `142_character_public_profiles`** (additive, no backfill): the lookup `campaign.public_profile_field_origins`, the draft `campaign.character_public_profiles` and the append-only `campaign.character_public_profile_releases`, with the scope, origin and immutability triggers of §5.3, `ON DELETE RESTRICT` on the campaign and character foreign keys, UPDATE/DELETE/TRUNCATE revoked on releases and DELETE/TRUNCATE on drafts from the application roles, and nothing readable by `app_read_only`. Down: drops the three tables and three functions (lossy by design); up/down/up and `alembic check` are pinned by `test_character_public_profiles_migration.py`.
- **Domain** `domain/public_profiles.py` (errors and the pure D8 policy), **commands** `commands/character_public_profile.py` (`save_character_public_profile_draft`, `release_character_public_profile`, and the two route pre-checks `require_may_edit` / `require_may_release`), **queries** `queries/character_public_profile.py` (the two GM reads and `latest_character_public_profile_release`, which has no caller yet), **API** `api/character_public_profile.py` (four routes), registries (persistence metadata, `ENTITY_REFERENCE_CLASSIFICATION` `BLOCKING` entries, `COLUMN_CLASSES`, the route manifest, `test_role_grants`).

**Where the implementation settles points the plan left open or tightened.**

- **Pre-checks as dependencies.** The release's authority check (and both routes' deny checks) run in a FastAPI dependency after the capability dependency, before the body is read and before the idempotency lookup, so a player gets `403` rather than `422` and a caller who lost authority cannot replay a stored response. The whole-character deny is in the release pre-check as well as under lock, so a denied caller cannot replay a keyed release either (the owner's instruction: a deny blocks release retries).
- **`version_number` is a `str` path segment** on the release read: a non-number is the same `404` as a missing release (the route manifest's generic probes substitute a UUID).
- **A whole-character deny cannot be created through `create_resource_grant`** (it refuses `entity_id` for a character). The A2a review classed this as a defect, not a test convenience; it is corrected by A2a-R (§8). Meanwhile the "deny that commits first is honoured" races are exercised through the way a deny actually reaches a member: an access-group addition carrying a raw `entity_id` deny grant, in both orders against the release and the save (the P1 lock order). Direct deny rows in the API tests are inserted as the inventory tests do.
- **No character archive command exists**; the archive race holds the lock the lifecycle commands take (`FOR UPDATE` on the entity) and writes the archived status.
- **`campaign.public_profile_field_origins`** is not in the frozen reporting allowlist, so its columns are classified in `COLUMN_CLASSES` rather than listed as reference data. `save_character_public_profile_draft` is a registered `world_capability=None` scope (`test_world_gate_registry.py`): the draft is a campaign's, not shared world canon.
- **D5, D6, D7 are not applied.** A release carries no name, summary, species or size; no legacy text is copied (A2b).

**Verification.** Recorded in the commit message and the implementation report (focused and full suites, migration up/down and drift, static checks, and the configuration isolation of `docs/DEVELOPMENT.md` §6.2). Pending: independent review and CI on the final head. A real-browser check does not apply (no UI).

---

## A0 acceptance criteria (implemented at `fca3ac7`)

1. `get_character_view` takes `campaign_id`. `active_encounter_id` is returned only for an `active` encounter whose `campaign_id` equals the route campaign and which passes the shared encounter member-read predicate. Campaign-less encounters are never returned.
2. The filter applies to every full-tier reader: a non-GM with `view_full` from a relationship or grant, a `canon.edit` GM, and the Foundry `encounter_read` route.
3. The summary tier is unchanged: still null, still no query.
4. Database tests (namespaced fixtures):
   - same-campaign encounter returned to a full-tier member and to the GM;
   - campaign B's active encounter on the **same timeline** is not returned to A's GM or A's full-tier member;
   - a campaign-less encounter is returned to nobody;
   - when B's active encounter has the later world time, A's reader still gets A's (the filter runs before `LIMIT`);
   - a pending same-campaign encounter is ignored;
   - the AI context returns only the same-campaign encounter.
5. The existing test [test_full_tier_returns_the_active_encounter_id](../tests/database/test_api_characters.py#L651) builds a campaign-less encounter ([factories.py:3119](../tests/factories.py#L3119), `campaign_id=None`). Under the approved policy it becomes null, so update it to pass `campaign_id` and record this as the intended behavior change, not a weakened assertion.
6. No schema, API-shape or portal type change. `tests/database/test_api_encounters_query.py` passes unchanged.
7. Update the docstring in `queries/character.py` and record that the `active_encounter_id` part of DEF-009 is now implemented.
8. The standard checks plus CI pass, then stop for independent review.
