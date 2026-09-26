# Product Direction

## 1. Purpose and status of this document

This document records the platform's product vision, GM and player value propositions, and how proposed-future capabilities map onto the current architecture — so documentation and future planning stay anchored to one shared direction instead of drifting between the README, `docs/PLAN.md`, and ad hoc proposals.

**This document is not an implementation-status authority.** [docs/PLAN.md](PLAN.md) remains authoritative for delivery status, phase sequencing, and what is scheduled next. Where this document and `docs/PLAN.md` appear to disagree about what is built, `docs/PLAN.md` wins. This document instead answers *why* the platform is shaped the way it is, and *where a proposed capability would eventually fit* if and when it is scheduled.

This document reflects the direction proposed in a 2026-09 product/marketing proposal, reconciled against the platform's existing architecture and non-negotiable rules (CLAUDE.md §5). It is not authorization to build any specific feature — each capability below is built only when `docs/PLAN.md` schedules it.

## 2. Product vision

> A self-hostable, rules-aware campaign intelligence and GenAI assistance platform for human Game Masters and their players.

Primary promise:

> Help human Game Masters prepare and run richer games while helping players remember the campaign, understand their characters, collaborate, and make informed decisions.

The human GM remains authoritative. GenAI may suggest, explain, portray, summarize, and propose — it never silently changes canon (CLAUDE.md §5 rule 2). PostgreSQL, not an AI conversation, is the source of truth (CLAUDE.md §5 rule 1).

## 3. GM value proposition

Reduce preparation effort, preserve continuity, support fair rulings, and make NPCs easier to portray without surrendering authority. Import what happened, review what changed, prepare what comes next, and portray the world with a GenAI assistant that understands the campaign but never overrules the GM.

## 4. Player value proposition

Stay connected to the campaign between sessions, understand what a character knows, collaborate with the party, and receive advice grounded in how the player actually plays their character — without revealing information the character should not know.

## 5. Three core aspects

Listed in overall **product-importance** order — this is not the build order (§6):

1. **GenAI GM assistance and NPC roleplay** — what attracts users.
2. **Session-note import and campaign intelligence** — what distinguishes the platform.
3. **Rules-aware character, creature, and encounter management** — what makes its recommendations trustworthy.

## 6. Importance order vs. build order

The technical build order is different from the importance order, because each layer depends on the one before it:

1. Complete the required authoring and ownership foundations.
2. Build session-note import and structured campaign intelligence.
3. Expand rules-aware character and creature management.
4. Build grounded GenAI assistance, character advice, and NPC roleplay.
5. Add live integrations (Foundry, bots, transcription providers) where justified.

Session intelligence establishes what happened and who knows it; rules-aware management establishes what is mechanically valid; GenAI then uses both foundations to recommend what could happen next and portray it consistently. Building GenAI assistance first, without those foundations, would produce recommendations with nothing grounding them.

## 7. Capability status

Status categories used throughout this document and `docs/PROJECT_STATUS.md`:

- **Built** — implemented and covered by tests today.
- **Partial** — some supporting infrastructure exists; the user-facing capability does not yet.
- **Planned** — scheduled in `docs/PLAN.md`, not yet started.
- **Deferred** — intentionally out of scope until later; no phase currently schedules it.

### GM-facing

| Capability | Status | Notes |
|---|---|---|
| Campaign, membership, and role authorization | Built | Phase 10 (`docs/PLAN.md` §24) |
| Access/audit-history review (portal) | Built | Phase 13E-A/13E-B |
| World ownership boundary (this change) | Built (foundation only) | No authoring commands yet — see §9 |
| Core authoring commands (create world/timeline/entity/character/NPC/location/quest, canon lifecycle transitions, archive/restore, timeline branching) | Planned | Missing prerequisite identified below; see §9 |
| Session-note import, entity/claim extraction, contradiction detection, canon review | Planned | Phase 15, depends on §9 |
| GenAI preparation copilot (quests, encounters, NPCs, clues) | Planned | Depends on session intelligence and rules management |
| NPC portrayal profiles and AI-assisted NPC roleplay | Planned | Requires a creature/NPC modeling decision — ADR TBD, see §10 |
| Structured GM-controlled interaction scenes (noncombat actions, DCs, outcomes) | Planned | Depends on rules engine + NPC portrayal |
| Custom creature builder and party-specific encounter analysis | Planned | Requires the creature-model decision (§10) |

### Player-facing

| Capability | Status | Notes |
|---|---|---|
| Character-filtered campaign browsing | Partial | Portal surfaces exist for GM tools; player-facing views are earlier-phase |
| Personalized dashboard, recaps, timelines | Planned | Depends on session intelligence |
| NPC/faction/quest memory views | Planned | Depends on session intelligence |
| Player notes, bookmarks, theories | Planned | |
| Player-private discussions/threads, immutable share snapshots | Deferred (architecture only) | See §11; no schema or API exists yet |
| Rules-aware character advancement | Planned | Depends on rules-aware character management |
| Character-aware player advisor | Planned | Depends on portrayal profiles + rules management |
| Player-owned session-note imports and rules sources | Planned | Same import foundation as GM-facing imports, permission-scoped to the player |

## 8. What the platform is not

- Not an autonomous replacement for a human GM.
- Not a complete VTT replacement.
- Not a native audio-transcription service — the import API accepts text or externally generated transcripts; transcription providers submit their output into it.
- Not a commercial rulebook marketplace or a direct D&D Beyond clone. Full commercial-rulebook ingestion is gated by legal and licensing review (§12).
- Not a system in which AI can silently rewrite canon.

## 9. Missing authoring prerequisite (Platform Review finding)

The database and authorization model support worlds, timelines, entities, characters, and campaigns, but **no command layer exists to create most of them** — `core.worlds`, in particular, has never had a `create_world` command; every world in the codebase today is raw-inserted by a migration, the dev-data script, or a test factory. Session-note import (Phase 15) explicitly depends on "canonical domain commands and audit infrastructure" already existing (`docs/PLAN.md` §15 framing) — so this authoring surface is a genuine prerequisite, not an optional cleanup.

`docs/PLAN.md` records the required authoring commands (create world, create timeline, create entity, create character, create NPC, create location, create quest, canon lifecycle transitions, archive/restore, timeline branch creation) as scheduled work that must land before import promotion depends on them. This document (world ownership) delivers one narrow slice of that foundation — the ownership boundary a `create_world` command will eventually require — without building `create_world` itself.

## 10. Open architectural decision: creature/NPC modeling

The custom creature builder, NPC detail levels, and party-specific encounter analysis all depend on a decision this proposal does not settle and this change does not make: whether creatures/NPCs below full-character detail are modeled as

- **(a)** character entities with an explicit simulation/detail level (narrative-only through fully-simulated, as sketched in this README's Character Model section), or
- **(b)** rules-level creature templates plus world-level creature instances, mirroring the existing rules-definition/world-instance separation (ADR 0005).

Recording the alternatives here rather than picking one keeps the decision visible instead of settling it by accident inside an unrelated migration. It should be resolved by its own ADR when NPC portrayal / creature-builder work is actually scheduled, not deferred silently.

## 11. Future architectural workstreams (recorded, not started)

- **Player-private collaboration.** Item-specific discussion threads, GM-exclusion enforced at the authorization layer (not just hidden in the UI), and immutable share snapshots when a player chooses to disclose private material to a GM. The honest limitation: application authorization can prevent a GM-role user from reaching player-private material through supported APIs, search, exports, or AI tools, but it cannot protect that material from whoever administers the physical server or database in a self-hosted deployment. No schema exists yet; this is future work, not implemented by this change.
- **Player theory as a first-class concept**, distinct from canon, character belief, and knowledge — a fifth knowledge-adjacent category (known/believed/suspected/unknown, plus an explicitly unconfirmed player theory) that today's knowledge model does not yet represent.
- **Purpose-specific AI context declarations** — every AI request eventually declaring requesting user, campaign, acting character/NPC, purpose, applicable in-world time, and permitted/prohibited source types, so authorization happens during retrieval rather than by prompt instruction.
- **Permission inheritance for imported and derived artifacts** — a source's access restrictions propagating to its extracted text, embeddings, summaries, and citations unless the owner explicitly creates a narrower shared artifact.
- **Ownership-scope-aware row-level security.** The ownership-scope boundary this change introduces is designed so a future RLS policy could use `security.ownership_scopes`/`security.ownership_scope_memberships` to scope world administration, without needing today's schema to change. No RLS policy is implemented now (CLAUDE.md scope discipline; this change is schema/command only).
- **Billing/subscription attachment.** Future billing may attach to the ownership-scope boundary. No billing, subscription, quota, or entitlement table exists or is planned by this change.

## 12. Scope guardrails

Applied consistently across this document, `docs/PLAN.md`, and architecture docs:

- Native audio transcription stays out of scope; the platform accepts text or externally generated transcripts only.
- Full commercial-rulebook ingestion is gated by legal/licensing review before any public or commercial deployment; only openly licensed or GM/player-owned content is assumed ingestible today.
- PostgreSQL full-text search remains the retrieval baseline. Embeddings/RAG are not scheduled merely because a proposal mentions them — a real consumer and a documented ADR would need to justify that addition.
- No autonomous AI campaign control, no full VTT replacement, no automatic canon changes, no AI access to all campaign/user content by default.

## 13. Relationship to other documents

- [docs/PLAN.md](PLAN.md) — authoritative delivery phases and status; this document's future workstreams are recorded there as scheduled, deferred, or not-yet-scheduled work, never marked complete ahead of the repository.
- [docs/architecture/SYSTEM_ARCHITECTURE.md](architecture/SYSTEM_ARCHITECTURE.md), [docs/DOMAIN_MODEL.md](DOMAIN_MODEL.md), [docs/architecture/DATABASE_MODEL.md](architecture/DATABASE_MODEL.md) — the current authoritative architecture and schema; this document does not redefine any of their content.
- [docs/adr/](adr/) — individual architectural decisions, including the world-ownership-scope model (ADR 0014) this change implements.
