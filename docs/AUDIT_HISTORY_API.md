# Campaign audit-history read API (Phase 13E-B audit-history workstream)

Independent foundation for a future Access-page "Audit history" panel.
Read-only — no new command, no new mutation, no new capability. This
document records the discovered `audit.change_log` contract and the exact
endpoint this workstream adds. It does not change, and is not a substitute
for, [docs/PHASE13E_ACCESS_CONTRACT.md](PHASE13E_ACCESS_CONTRACT.md) (which
remains the authoritative record of the Access-page mutation/read contract
this endpoint is designed to sit alongside, once a later PR wires it in).

## 1. Discovered data model

- **Table:** `audit.change_log` (revision `007_audit_change_log`;
  `src/dnd_ai/persistence/tables/audit.py`). Append-only, immutable to
  normal application roles (docs/DATABASE_CONVENTIONS.md §24.2). Every row
  is written by `dnd_ai.api.audit.record_change_log`, on the same
  transaction as the command/state change it describes (docs/architecture/
  SYSTEM_ARCHITECTURE.md's "events and their typed-state updates commit
  atomically" rule — CLAUDE.md rule 6).
- **Event identifier:** `change_log_id` (`BIGINT IDENTITY`), monotonically
  increasing in insertion order — the documented tie-breaker for a
  deterministic newest-first order (§4 below).
- **No `campaign_id` column.** `audit.change_log` carries `world_id`
  (the change's world) — not a campaign. This is deliberate, not a gap:
  most audited tables (character state, quests, relationships,
  interactions, ...) are world/entity-scoped and shared across every
  campaign playing that world's timeline(s); `campaign.campaigns` itself
  documents that it "does not own world entities." Filtering by
  `world_id` alone would leak a *different* campaign's history whenever
  two campaigns share a timeline (`campaign.campaigns.timeline_id`'s own
  comment: "Several campaigns may share one timeline").
- **Campaign scope, resolved exactly.** This endpoint's query
  (`dnd_ai.queries.audit_history`) instead joins each row back to the
  *real* table its own `schema_name`/`table_name` columns name, via
  `record_id = <that table>.<primary key>`, and reads that table's own
  `campaign_id` — directly (`security.campaign_memberships`,
  `.resource_grants`, `.campaign_invitations`, `campaign.campaigns`) or one
  hop through `security.campaign_memberships.campaign_id`
  (`security.membership_roles`, `.membership_character_relationships`).
  This join is exact, not approximate, because none of these six tables is
  ever physically deleted by an application command (CLAUDE.md rule 9 —
  each one closes a row instead: `revoked_at`/`ended_at`).
- **Actor identity:** `actor_user_id` (FK `security.users`, `ON DELETE SET
  NULL`) XOR `actor_service` (free text, set only for a non-human actor
  with no linked user — `dnd_ai.api.audit.record_change_log` enforces
  exactly one is present). Every command this endpoint surfaces is
  `access.manage`-gated and requires a human principal
  (`require_campaign_capability`), so `actor_service` is never actually
  populated for the categories this endpoint currently resolves — the API
  still declares an `"unknown"` actor type defensively (see §3).
- **Event-type representation:** `command_name` — a fixed literal every
  call site supplies (never derived from request data;
  `dnd_ai.api.audit.record_change_log`'s own docstring). This endpoint's
  category/action-label vocabulary is keyed directly off a closed allowlist
  of these literals (§2), not off `change_action_id`/`change_actions.code`
  (`created`/`updated`/...), which is too coarse to distinguish, e.g.,
  "member added" from "invitation accepted" (both write `table_name =
  'campaign_memberships'`, `change_action_code = 'created'`/`'updated'`
  respectively, but from different commands).
- **Retention:** none. `audit.change_log` has no pruning job of its own
  (unlike disposable operational tables such as
  `security.idempotent_requests`) — rows persist for the life of the
  database. This endpoint imposes no retention or export behavior; that is
  explicitly out of scope for this workstream.
- **Older events and campaigns:** every row this endpoint can return
  resolves its campaign via a live join to a row that still exists (see
  above) — there is no "orphaned campaign reference" case for the six
  tables in scope. A `command_name` outside this endpoint's closed
  allowlist (e.g. a quest, item, or narrative-event change) is never
  attempted and never surfaced — see §6.

## 2. Category / command allowlist

| `category` | `command_name` values | Source table |
|---|---|---|
| `membership` | `add_campaign_member`, `end_campaign_membership` | `security.campaign_memberships` |
| `role` | `assign_membership_role`, `revoke_membership_role`, `change_membership_role` | `security.membership_roles` |
| `character_relationship` | `grant_character_relationship`, `change_character_relationship`, `revoke_character_relationship` | `security.membership_character_relationships` |
| `resource_grant` | `create_resource_grant`, `revoke_resource_grant` | `security.resource_grants` |
| `invitation` | `create_campaign_invitation`, `accept_campaign_invitation` | `security.campaign_invitations` |
| `campaign` | `create_campaign` | `campaign.campaigns` |

Every `command_name` value above is copied verbatim from the literal each
command's own `dnd_ai.api.audit.record_change_log(...)` call site passes
today (`dnd_ai.api.memberships`/`.access_grants`/`.campaign_invitations`/
`.campaigns`). A `command_name` outside this set is never selected by any
branch of the query and never appears in a response.

## 3. Safe-presentation allowlist (server-generated projection)

Every returned item (`dnd_ai.api.audit_history.AuditHistoryItemResponse`)
carries only:

| Field | Source | Notes |
|---|---|---|
| `change_log_id` | `audit.change_log.change_log_id` | Identity only — a React list key, never rendered as page text. |
| `occurred_at` | `audit.change_log.recorded_at` | |
| `category` | Derived from `command_name` (§2) | Closed enum. |
| `action_label` | Derived from `command_name`, a fixed server-owned string (e.g. `"Member added"`) | Never free text. |
| `actor_label` | `security.users.display_name` (current), or `audit.change_log.actor_service`, or a fixed `"Unknown actor"`/`"Removed account"` fallback | Never email, never a login identifier. |
| `actor_type` | `"user"` \| `"service"` \| `"unknown"` | |
| `target_label` | `security.users.display_name` (account target), `core.entities.canonical_name` (character target), or an access group's `name` — current values, resolved per category (§2's source table) | `null` when the category has no single discrete target (`invitation`, `campaign`). |
| `target_type` | `"account"` \| `"character"` \| `"access_group"` \| `null` | |
| `change_summary` | Server-generated from role/relationship-type/capability display names (and, for a `change_*` action, `audit.change_log.previous_status`/`.new_status` — the old/new **codes**, resolved to display names where possible) | Never `changed_fields` (JSONB) verbatim. |
| `outcome` | Reserved, always `null` today | No category in scope has a fail/deny outcome yet. |

**Never returned**, even internally selected by the query: `audit.
change_log.changed_fields` (arbitrary JSONB), `.reason`, `.correlation_id`,
`.causation_id`, `.ai_proposal_id`, `.acting_foundry_actor_id`, `.acting_
foundry_connection_id`, `.acting_foundry_device_id`, `.acting_external_
system_id`, `.source_id`, `.event_id`, `.entity_id`, `.world_id`, or any
password/session/token/credential column from any joined table. None of
these columns appear anywhere in `dnd_ai.queries.audit_history`'s `SELECT`
list at all — not merely dropped at the response boundary.

## 4. Endpoint contract

`GET /campaigns/{campaign_id}/audit-history`

**Capability:** `access.manage`, via the identical `dnd_ai.api.access.
require_campaign_capability` dependency every other campaign-access-
management route already uses (docs/PHASE13E_ACCESS_CONTRACT.md §2/§3). No
dedicated audit-viewing capability exists in this codebase yet, and none is
invented here.

**Query parameters:**

| Param | Type | Notes |
|---|---|---|
| `category` | one of §2's six category codes, optional | A value outside the closed set is a 422 (FastAPI `Literal` validation) before the handler runs. |
| `actor_user_id` | UUID, optional | A malformed UUID is a 422. |
| `occurred_from` | ISO-8601 datetime, optional | |
| `occurred_to` | ISO-8601 datetime, optional | A range with `occurred_from > occurred_to` is not rejected — it simply matches no rows. |
| `limit` | integer, `1..100`, default `25` | Same bounds as `dnd_ai.api.pagination.DEFAULT_PAGE_SIZE`/`MAX_PAGE_SIZE`. |
| `cursor` | opaque string, optional | From a prior response's `next_cursor`. A malformed/tampered/wrong-endpoint cursor is a fixed 422 `invalid_cursor` (`dnd_ai.api.pagination.decode_cursor`). |

**Response `200`:**

```json
{
  "items": [
    {
      "change_log_id": 12345,
      "occurred_at": "2026-09-18T21:04:11.123456+00:00",
      "category": "role",
      "action_label": "Role changed",
      "actor_label": "GM Alex",
      "actor_type": "user",
      "target_label": "Player Sam",
      "target_type": "account",
      "change_summary": "Player → Observer",
      "outcome": null
    }
  ],
  "next_cursor": "eyJ2Ijox..."
}
```

**Status codes:**

- `200` — always, including an empty-history or filters-match-nothing
  page (`{"items": [], "next_cursor": null}`). Never an error.
- `403` — an authenticated campaign member who does not hold
  `access.manage`.
- `404` — no active, authorizing membership in the campaign at all, or the
  campaign does not exist — indistinguishable, matching every other
  `access.manage`-gated route in this codebase.
- `422` — a malformed `category`/`actor_user_id`/datetime query parameter,
  or a malformed/wrong-endpoint pagination cursor.

## 5. Ordering and pagination

Newest first: `ORDER BY recorded_at DESC, change_log_id DESC`. The
`change_log_id` tie-breaker (a monotonically increasing `BIGINT IDENTITY`)
makes this a strict total order even when two rows share the same
`recorded_at` timestamp (a genuine possibility under concurrent writes),
matching the workstream's "timestamp + event id" requirement.

Keyset (cursor) pagination via `dnd_ai.api.pagination` — the identical
mechanism the Phase 13D World Explorer/Knowledge browse endpoints already
use. The cursor is opaque, validated, and carries `(occurred_at,
change_log_id)` of the last row on the current page; it is bound to this
endpoint's own `keyset` name (`campaign_audit_history`) and rejected by a
different endpoint. No total count is returned (matching the same
Phase 13D precedent) — a page reports only whether a `next_cursor` exists.

## 6. Known limitations

- **Scope is curated, not exhaustive.** Only the six categories in §2 are
  covered. A generalized "every audited table, scoped by campaign"
  history is a materially harder feature — most audited tables (character
  state, quests, interactions, narrative events, ...) have no reliable
  `campaign_id` at all (they are world/entity-scoped, shared across
  sibling campaigns on the same timeline) — and is explicitly out of scope
  for this foundation.
- **Actor/target name fidelity.** Every label (actor, account/character
  target, role/relationship-type/capability display name) is resolved
  against that record's **current** row — this schema keeps no
  point-in-time snapshot for any of them. A renamed account, character,
  role, or capability shows its current name against a historical event,
  not the name it had at the time. This matches the existing precedent
  `docs/PHASE13E_ACCESS_CONTRACT.md` §3 already sets for the access
  overview's own role/relationship-type/character labels.
- **Deleted/disabled actors and targets.** No application command in this
  codebase physically deletes a `security.users`, `core.entities`
  (character), `security.roles`, `security.character_relationship_types`,
  `security.capabilities`, or `security.access_groups` row (CLAUDE.md rule
  9 plus each of these tables' own "closed, not deleted" migration
  comments). This turns out to be enforced by the database itself, not
  merely by convention: `audit.change_log`'s own `ck_change_log_actor_
  present` CHECK constraint (confirmed by deliberately attempting it during
  this workstream's own development) makes PostgreSQL *refuse* to delete a
  `security.users` row that is the sole actor identifier of an existing
  `change_log` row — the `ON DELETE SET NULL` cascade that would otherwise
  null `actor_user_id` is itself rejected before it can complete. Every
  target column this endpoint reads is similarly either `ON DELETE
  RESTRICT` or `ON DELETE CASCADE` from a jointly-referenced row, so a
  "deleted target" removes the *whole* audit row from the result set
  rather than surfacing it with a missing label. The "falls back to a fixed
  placeholder" branches (`"Removed account"`, `"Removed character"`,
  `"Removed role"`, `"Removed relationship type"`, `"Removed capability"`,
  `"Removed access group"`, `"Unknown actor"`) remain in the code as
  defense in depth against a direct, out-of-band data repair — but are
  provably unreachable through any FK-respecting write path today, and are
  covered by unit tests against the pure resolver functions rather than a
  database fixture, since no realistic fixture can reach them.
- **No export, deletion, or retention behavior.** Explicitly out of scope
  — see the top of this document and the workstream's own task scope.
