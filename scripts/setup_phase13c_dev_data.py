"""Phase 13C portal live-verification development dataset.

Creates the smallest dataset the portal's Phase 13C checkpoints (campaign
selection, campaign-context refresh, character-perspective selection) need
to be exercised by hand against a real, self-hosted/local PostgreSQL
database: one development world, two timelines, two active campaigns (one
per timeline), one already-existing local account authorized on both
campaigns, and two characters selectable as that account's perspective in
the first campaign.

Also supports the Phase 13D character Current State live-verification
checkpoint: both characters carry deterministic `campaign.character_state`
on Phase13C Timeline A (Character A partially hurt with temporary HP,
exhaustion, and death saves recorded; Character B at a full, all-zero
baseline), and Character A additionally carries one fixture-owned
`campaign.character_conditions` row (`poisoned`) and one fixture-owned
`campaign.character_resources` row (`spell_slot`, 2/3) — see the
`_CHARACTER_A_STATE`/`_CHARACTER_B_STATE`/`_CONDITION_*`/`_RESOURCE_*`
constants below. Character B deliberately gets neither, so the portal's
empty-conditions/empty-resources states are also exercisable. These three
kinds of row are reconciled (reset to the documented values), not merely
created-once: a live-testing session against this fixture is expected to
change them via the real `dnd_ai.commands.character_state` commands (taking
damage, spending a spell slot, ...), and re-running this script resets
them back to the documented starting point for the next session — see
`_ensure_character_state`/`_ensure_character_condition`/
`_ensure_character_resource` below, and `_Summary.add` for how a
reconciling update is distinguished from a plain create/reuse in this
script's own summary output.

Also supports the Phase 13D Sessions list/detail live-verification
checkpoint (docs/UI_DESIGN.md §5.7-§5.8, read back through the real
`GET /campaigns/{id}/sessions` and `.../sessions/{id}` endpoints). Campaign
A gets three fixture-owned `campaign.sessions` rows — see
`_CAMPAIGN_A_SESSIONS`:

  #1 "The Sealed Descent" and #2 "The Warden's Bargain": completed
  sessions (`lifecycle_status = active` + a non-null `started_at`/
  `ended_at`; `core.lifecycle_statuses` has no "ended" code and
  `end_session` represents ending with `ended_at`, not a lifecycle
  transition), each with a recap and two linked `recorded`
  `narrative.events`. #2's timestamps are later than #1's so the list's
  newest-first ordering is visible. In #1 the two events' chronological
  order (by `core.world_times.sort_key`, which the detail query's
  `ORDER BY wt.sort_key, e.created_at` sorts on) is the reverse of their
  alphabetical name order, so the owner can confirm the portal preserves
  backend order instead of re-sorting.

  #3: `lifecycle_status = pending`, `title`/`started_at`/`ended_at`/
  `summary` all NULL, and no linked events — the portal's "Session 3"
  fallback heading, "Not recorded" timestamps, and neutral empty
  recap/events states, plus null-timestamps-sort-last in the list.

Campaign B gets one completed fixture-owned session ("Smoke Over
Hollowmere", `_CAMPAIGN_B_SESSIONS`) with one linked event. It exists so
the owner can take its session id and request it under Campaign A's URL:
the API must return the same non-disclosing "unavailable" response as a
nonexistent session. The exact id and the ready-made cross-campaign
request are printed in the "Session fixture quick reference" block at the
end of every run.

Sessions are reconciled like the character rows above: `campaign.sessions`
carries no immutability trigger, so title, summary, lifecycle, timestamps
and the world-time endpoint ids are reset to the documented values on
every re-run (a live-testing session may legitimately have ended a session
or revised a recap). Their world times and linked events are *not*
reconciled because the schema makes them immutable: `core.world_times.
sort_key` is frozen once set (revision 030), and a linked event is
`recorded` and therefore immutable (docs/ENTITY_LIFECYCLE.md §15 — content
frozen, only `recorded -> voided/corrected`, no deletion). That
immutability *is* the guarantee — nothing a live-testing session can do
will move an event or change its content — so a re-run only
create-or-reuses those rows by their (frozen) label/name. If a fixture
event was voided or repointed during testing, or a non-fixture row has
taken a fixture world-time label, the script aborts with guidance rather
than attempting an impossible in-place fix — see `_ensure_session`/
`_ensure_session_event`/`_get_or_create_world_time`.

Each fixture event is inserted directly at `recorded` rather than through
`dnd_ai.commands.events.record_event`: that command has no parameter for
the event's short `summary` (the portal's Session-detail Summary column),
which this fixture must populate. Every other column is set exactly as its
`_insert_event_row` would — this is the same "mirror the command's row
shape where the command itself doesn't fit" boundary the world/timeline/
character inserts below already document.

Also supports the Phase 13D Quest list/detail live-verification checkpoint
(the portal's read-only `GET /campaigns/{id}/quests` and
`.../quests/{quest_id}` screens, read back through
`dnd_ai.queries.quest.list_campaign_quests`/`get_quest_view`). Campaign A
gets three fixture-owned quests — see `_CAMPAIGN_A_QUESTS` and the long
comment above that constant for the full rationale, the exact supported
lookup vocabularies used, and the visibility semantics:

  "Restore the Glass Ossuary" (active): three stages whose alphabetical
  order is the reverse of their `sequence_number` order (so the owner can
  confirm the portal keeps the backend's order), objectives exercising
  required/optional, both `automatic` and `gm_confirmed` completion modes,
  completed/current/untracked objective statuses, set and null
  descriptions, a quantity requirement and none, several objectives under
  one stage, a stage with no objectives, plus a `hidden_until_discovered`
  (stateless) and a `gm_only` objective that a non-GM audience would not
  see. "Gather the Hollow Verses" (completed): no stages — the completed
  badge and the neutral empty-stage state. "Wake the Tide Beneath Vheil":
  tracked only through one party's own `campaign.quest_state` row, so the
  owner (a GM) sees it listed with a NULL resolved status — the one
  legitimate way the production query yields a null quest status for this
  account.

Campaign B gets one fixture-owned quest ("Chart the Sunken Marches",
`_CAMPAIGN_B_QUEST`) with a stage and objective, tracked on Timeline B.
Both `list_campaign_quests` and `get_quest_view` are now timeline/audience
scoped through one shared rule (`dnd_ai.queries.quest.
_QUEST_STATE_MATCHES_AUDIENCE`): this quest never surfaces in Campaign A's
list, and requesting its id under Campaign A's URL raises
`QuestNotFoundError` → the same non-disclosing 404 a nonexistent quest
produces, even though both campaigns share one world. The database/query
verification block requests it exactly that way and prints the real
result — see the module comment above `_CAMPAIGN_B_QUEST` and
`_print_quest_verification`.

Quests, stages, objectives, and their `campaign.quest_state`/
`.objective_state` rows are inserted directly and, on a re-run, the
mutable portal-visible columns (including each fixture-owned state row's
status) are reconciled — no quest table carries an immutability trigger,
`dnd_ai.commands.quests.advance_objective` only advances an already-tracked
objective and needs a narrative event this fixture data never caused, and
`tests/factories.py` already documents "pre-campaign / world content has
no authoring command" as the standing boundary. `last_event_id` on a
reconciled state row is left untouched (a live-testing advance may have
set it to a real recorded event; only the status matters to the portal).

Also supports the Phase 13D World Explorer and Knowledge screen
live-verification checkpoints (the portal's read-only
`GET /campaigns/{id}/world/search`, `.../world/{locations,religions,items,
events}/{id}`, `.../world/relationships`, `GET /campaigns/{id}/knowledge`
and `.../knowledge/{id}` screens — docs/UI_DESIGN.md §5.4/§5.6,
docs/PHASE13D_BACKEND_READINESS.md §10 — read back through
`dnd_ai.queries.world_explorer` and `dnd_ai.queries.knowledge_browse`).
See `_ensure_world_and_knowledge_fixtures` and the long block comment
above the `_WK_*` / `_CAMPAIGN_A_LOCATIONS` / `_CAMPAIGN_A_EVENTS` /
`_CAMPAIGN_A_KNOWLEDGE` constants for the full rationale. Campaign A gets:

  A four-level containment hierarchy (continent "Auremar" -> region "The
  Ashen Vale" -> settlement "Hollowmere" -> building "The Sunken Archive")
  plus the dungeon "The Tidebound Crypt" and its area "The Lantern
  Antechamber", with `campaign.location_state` on Hollowmere; one entity
  of every World Explorer category (NPC "Archivist Sella Vane", guild "The
  Cartographers' Guild" with a GM-only `internal_description`, government
  "The Hollowmere Magistracy", religion "The Tidefather Communion" and its
  lay order, a character-held item "The Warden's Lantern" and a loose item
  "The Drowned Crown", two recorded historical events plus one `draft`
  event only a GM may see, and a `membership` relationship between the NPC
  and the guild); and knowledge records for every Knowledge-screen view —
  a known fact, a rumor, a materially distorted party belief (interpretation
  differs from canon), a recently discovered item with a fictional
  world-time and a source event, character-private knowledge for Character
  A and different character-private knowledge for Character B, public lore,
  a quest-subject knowledge item, and one canonical-only secret no ordinary
  player can reach. The knowledge party "The Lantern-Bearers" is created
  with Character A and Character B as current members so
  `resolve_party_perspective` authorizes the owner's `known`/`rumors`/
  `party_shared` reads.

Campaign B (Timeline B) gets one distinct location, one recorded event,
and one public-lore knowledge item — all timeline-scoped, so they never
surface through Campaign A's `/world/search` (events), knowledge views, or
location state, proving cross-campaign isolation for the concerns the
documented world-scoped visibility model can isolate. The world-canon
location entity itself is visible in both campaigns by that model; its
state, events, and knowledge are Campaign B only.

Unlike the character-state / session / quest fixtures above, the World and
Knowledge screens are read-only — no Phase 13D screen that consumes this
data has a write path (docs/PHASE13D_BACKEND_READINESS.md §10.2), so a
live-testing session cannot drift any of these rows. They are therefore
pure create-or-reuse by their own fixed names / natural keys, with no
reconciliation branch.

`_print_world_knowledge_verification` runs the real merged query functions
after an applied run, both as the GM's real access context resolves them
and with the non-GM `include_ground_truth=False` + resolved-perspective
inputs a player's request produces, and prints both — never a hand-written
lookalike query.

Not a general-purpose seeding framework — every name and shape here is
specific to this one fixture (see the `_WORLD_*`/`_CAMPAIGN_*`/`_CHARACTER_*`/
`_CAMPAIGN_A_SESSIONS`/`_CAMPAIGN_B_SESSIONS`/`_CAMPAIGN_A_QUESTS`/
`_CAMPAIGN_B_QUEST` constants below), and nothing about this script
generalizes to seeding arbitrary content.

Connects using the same resolution the running API itself uses
(`dnd_ai.config.settings.database_url`) — never a hardcoded connection
string or a separately-guessed URL, so this always targets whatever
database the local `uvicorn dnd_ai.api.app:app` process is actually reading
from (`DND_AI_DATABASE_URL`/`DATABASE_URL`, resolved the identical way).
Refuses to run at all when `DND_AI_ENVIRONMENT=production` (`settings.
environment`) — this script is a development-data convenience and must
never be pointed at a real deployment. Before any mutation it also prints a
password-redacted summary of the resolved target (host/port/database) and
refuses a non-loopback `DATABASE_URL` host or a production-looking database
name unless `DND_AI_ALLOW_NONLOCAL_DEV_DATA=1` acknowledges an
intentionally non-standard but still-safe target — the developer's native
PostgreSQL is `127.0.0.1:5432` (docs/DEVELOPMENT.md §3.1), not the Compose
hostname `db` and not host port `5433`.

Preview by default; `--apply` is required to write anything. Both modes run
the identical sequence of checks and inserts inside one transaction —
preview's only difference is a `ROLLBACK` instead of a `COMMIT` at the very
end, so a clean preview run is a reliable predictor of what `--apply` will
do, including surfacing any constraint/trigger rejection before anything is
ever committed.

Idempotent by construction: every step first checks for an already-existing
row (by the fixture's own fixed name/slug) and reuses it instead of
inserting again, so running this script twice against the same database
with the same `--user-id` produces the same end state as running it once —
no duplicate campaigns, memberships, characters, or grants. A conflicting
row (e.g. the fixture's campaign name already exists on a timeline this
script did not create) is treated as ambiguous and aborts rather than
guessing.

`--user-id` is required and never defaulted or guessed — the caller
confirms the exact `security.users.user_id` to authorize (see
docs/PLAN.md's own "do not use UUID secrecy as authorization" posture,
which applies here just as much to picking the *right* account as to
external authorization). The account must already exist, be active, and
carry a local (`security.external_identities(issuer='local')`) identity
with a password credential — this script never creates a user, sets a
password, or changes `is_platform_administrator`.

Reused production paths, not reimplemented here:

- `dnd_ai.commands.campaigns.grant_timeline_bootstrap` /
  `.create_campaign` — the real first-campaign entitlement and campaign/
  membership/owner-role bootstrap. This script is the "trusted world-
  authoring/import infrastructure" caller that module's own docstring
  describes; it never bypasses `_authorize_timeline_reuse()` or
  `_check_ruleset_allowed()`.
- `dnd_ai.commands.access_grants.grant_character_relationship` — the real
  character-relationship grant, including its same-world/same-campaign
  pre-checks.
- `dnd_ai.api.audit.record_change_log` — the same `audit.change_log`
  writer `dnd_ai.api.campaigns`/`.access_grants` call after those two
  commands, with the confirmed `--user-id` as `actor_user_id`.

core.worlds/campaign.timelines/rules.world_rulesets/core.entities/
character.characters/character.player_characters rows are inserted
directly: there is no production authoring command for any of them yet
(confirmed by inspecting src/dnd_ai/commands/ and src/dnd_ai/api/ — the
same "pre-campaign world content has no command" boundary
tests/factories.py's own module docstring already documents). Every
inserted row's shape mirrors tests/factories.py's `make_world`/
`make_timeline`/`make_character` exactly (schema, required columns,
lookup-code resolution), not a reinvention of it.

`campaign.character_state`/`.character_conditions`/`.character_resources`
are also inserted (and, on a later run, reconciled) directly, the same
"initial development state" reasoning: `dnd_ai.commands.character_state`
exists, but every command there mutates an *already-tracked* row (it has
no notion of first establishing one) and would require fabricating a
narrative event this fixture data was never actually caused by — exactly
what the task this script supports says not to do. Every inserted/
reconciled row's shape mirrors tests/factories.py's `make_character_state`/
`make_character_condition`/`make_character_resource` exactly.

One notable, pre-existing gap this script works around rather than papers
over: `security.character_relationship_type_capabilities` (the table
`dnd_ai.domain.access.resolve_access_context`'s own character-capability
join depends on) ships with **zero rows** in every environment — no
migration or seed file populates it (confirmed: only
`security.character_relationship_types`/`.capabilities` have seed files;
grep across database/migrations/versions finds no INSERT into the
capabilities join table). Without at least one row there, no character
relationship of any type is ever selectable as a perspective, on any
campaign, regardless of how it's granted — campaign ownership alone does
not imply it either (`campaign_owner`'s own capabilities are
`access.manage`/`campaign.view`/`canon.edit`, none of them `character.*`).
This script seeds the `owner` relationship type with the full
`character.*` capability set (all nine `security.capabilities` rows whose
code starts with `character.`) the FIRST time it finds that join table
completely empty, and leaves it untouched otherwise — global, one-time
config, not per-fixture data, and exactly what the platform needs before
*any* character perspective can work anywhere. Flagged in this script's own
CLI output every time it runs so it is never silently assumed.
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import Connection, create_engine, text
from sqlalchemy.engine import make_url

from dnd_ai.api.access import resolve_party_perspective
from dnd_ai.api.audit import record_change_log
from dnd_ai.api.world_explorer import resolve_world_character_visibility
from dnd_ai.commands._shared import lookup_id
from dnd_ai.commands.access_grants import grant_character_relationship
from dnd_ai.commands.campaigns import create_campaign, grant_timeline_bootstrap
from dnd_ai.config import settings
from dnd_ai.domain.access import resolve_access_context
from dnd_ai.queries.bootstrap import get_session_bootstrap
from dnd_ai.queries.knowledge_browse import KnowledgeListItem, list_knowledge
from dnd_ai.queries.quest import QuestNotFoundError, get_quest_view, list_campaign_quests
from dnd_ai.queries.world_explorer import (
    WORLD_CATEGORY_TYPE_CODES,
    WorldEntityCard,
    WorldResourceNotFoundError,
    get_event_view,
    get_location_view,
    search_world_entities,
)

_COMMAND_NAME = "scripts.setup_phase13c_dev_data"

_WORLD_SLUG = "phase13c-dev-world"
_WORLD_NAME = "Phase13C Dev World"
_FIXTURE_DESCRIPTION = "Phase 13C portal live-verification fixture. Not real campaign content."

_TIMELINE_A_NAME = "Phase13C Timeline A"
_TIMELINE_B_NAME = "Phase13C Timeline B"

_CAMPAIGN_A_NAME = "Phase13C Campaign A"
_CAMPAIGN_B_NAME = "Phase13C Campaign B"

_CHARACTER_A_NAME = "Phase13C Character A"
_CHARACTER_A_SPECIES_CODE = "human"
_CHARACTER_B_NAME = "Phase13C Character B"
_CHARACTER_B_SPECIES_CODE = "elf"
_CHARACTER_SIZE_CATEGORY = "medium"

_RULESET_CODE = "dnd5e"
_RELATIONSHIP_TYPE_CODE = "owner"

_CREATED_CHANGE_ACTION = "created"


@dataclass(frozen=True)
class _CharacterStateFixture:
    current_hit_points: int
    maximum_hit_points: int
    temporary_hit_points: int
    exhaustion_level: int
    death_save_successes: int
    death_save_failures: int


_CHARACTER_A_STATE = _CharacterStateFixture(
    current_hit_points=6,
    maximum_hit_points=12,
    temporary_hit_points=2,
    exhaustion_level=1,
    death_save_successes=1,
    death_save_failures=0,
)
_CHARACTER_B_STATE = _CharacterStateFixture(
    current_hit_points=20,
    maximum_hit_points=20,
    temporary_hit_points=0,
    exhaustion_level=0,
    death_save_successes=0,
    death_save_failures=0,
)

_CONDITION_CODE = "poisoned"
_CONDITION_SOURCE_DESCRIPTION = "Phase 13D portal development fixture"

_RESOURCE_CODE = "spell_slot"
_RESOURCE_CURRENT_AMOUNT = 2
_RESOURCE_MAXIMUM_AMOUNT = 3

# --------------------------------------------------------------------------
# Phase 13D Sessions list/detail live-verification fixtures
# --------------------------------------------------------------------------
# Deterministic sessions and linked narrative events for the portal's
# Sessions list (docs/UI_DESIGN.md §5.7) and Session detail (§5.8) screens,
# read back by the owner through the real `GET /campaigns/{id}/sessions`
# and `GET /campaigns/{id}/sessions/{id}` endpoints (dnd_ai.queries.session).
#
# Lifecycle status: `core.lifecycle_statuses` has no "completed"/"ended"
# code — its vocabulary is pending/active/inactive/archived/deleted, and
# dnd_ai.commands.sessions.end_session is explicit that an ended session is
# represented by `ended_at IS NOT NULL`, not a lifecycle transition (the
# row stays `active`). So the two finished sessions carry `active` + a
# non-null `ended_at`; the not-yet-started session carries `pending` and
# no timestamps. Those are the schema-supported codes, not invented ones.
#
# Event ordering: the session-detail query sorts linked events by
# `ORDER BY wt.sort_key, e.created_at` (dnd_ai.queries.session). Each event
# gets its own `core.world_times` row with a deliberately chosen sort_key,
# and in Session 1 the chronological order (by sort_key) is the reverse of
# the events' alphabetical name order — so a live tester can confirm the
# portal preserves the backend's order instead of re-sorting the table.
_SESSION_SORT_KEY_BASE = 13_000_000
_SESSION_WORLD_TIME_LABEL_PREFIX = "Phase13D session fixture"


@dataclass(frozen=True)
class _SessionEventFixture:
    """One `narrative.events` row linked to a fixture session.

    `summary` lands on the event's inherited `core.entities.summary` (the
    portal's event Summary column); `details` on `narrative.events.details`
    (the Details column). `world_time_offset` is added to
    `_SESSION_SORT_KEY_BASE` to get the event's `core.world_times.sort_key`
    — the value the detail query actually orders on.
    """

    name: str
    summary: str
    details: str
    event_type_code: str
    world_time_offset: int


@dataclass(frozen=True)
class _SessionFixture:
    """One `campaign.sessions` row plus its linked events. `title=None`
    models the not-yet-titled session the portal renders as `Session
    <number>`; `started_at=None`/`ended_at=None`/`summary=None` model its
    empty timing/recap states. `*_world_time_offset` is `None` for that
    same session (no fictional-time endpoints) and an int offset from
    `_SESSION_SORT_KEY_BASE` otherwise.
    """

    session_number: int
    title: str | None
    summary: str | None
    lifecycle_status_code: str
    started_at: datetime | None
    ended_at: datetime | None
    start_world_time_offset: int | None
    end_world_time_offset: int | None
    events: tuple[_SessionEventFixture, ...]

    @property
    def portal_heading(self) -> str:
        """What the portal shows as the session's H1 — its title, or the
        `Session <number>` fallback when untitled."""
        return self.title if self.title is not None else f"Session {self.session_number}"


def _fixture_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    assert parsed.tzinfo is not None, "fixture timestamps must be timezone-aware"
    return parsed


_CAMPAIGN_A_SESSIONS: tuple[_SessionFixture, ...] = (
    _SessionFixture(
        session_number=1,
        title="The Sealed Descent",
        summary=(
            "The party forced the ossuary doors, ignored Tolek's warning, and woke the first "
            "warden when they breached the lantern chamber."
        ),
        lifecycle_status_code="active",
        started_at=_fixture_timestamp("2026-01-10T18:00:00+00:00"),
        ended_at=_fixture_timestamp("2026-01-10T22:30:00+00:00"),
        start_world_time_offset=10,
        end_world_time_offset=20,
        events=(
            _SessionEventFixture(
                name="Tolek's Warning Unheeded",
                summary=(
                    "Tolek's letter begging the party to turn back was read aloud and dismissed."
                ),
                details=(
                    "Read at the threshold before anyone stepped inside. The party voted to "
                    "proceed and Tolek's courier left without an answer."
                ),
                event_type_code="session_narrative",
                world_time_offset=12,
            ),
            _SessionEventFixture(
                name="Lantern Chamber Breached",
                summary="Forcing the warded lantern chamber woke the first warden.",
                details=(
                    "Two of the three binding glyphs were disarmed; the third discharged and the "
                    "warden rose. This happened after Tolek's warning even though it sorts before "
                    "it alphabetically."
                ),
                event_type_code="mechanism_activated",
                world_time_offset=15,
            ),
        ),
    ),
    _SessionFixture(
        session_number=2,
        title="The Warden's Bargain",
        summary=(
            "Negotiation with the head warden bought the party passage past the antechamber, "
            "moments before grave-hounds sprang at the third vault."
        ),
        lifecycle_status_code="active",
        started_at=_fixture_timestamp("2026-01-24T18:00:00+00:00"),
        ended_at=_fixture_timestamp("2026-01-24T23:15:00+00:00"),
        start_world_time_offset=30,
        end_world_time_offset=40,
        events=(
            _SessionEventFixture(
                name="Vault Antechamber Mapped",
                summary="The party charted the antechamber and its four sealed side-vaults.",
                details="A full sketch of the antechamber and its vault seals went into the records.",
                event_type_code="location_discovered",
                world_time_offset=32,
            ),
            _SessionEventFixture(
                name="Ambush at the Third Vault",
                summary="Grave-hounds sprang the instant the third vault seal cracked.",
                details="Two hounds were put down and one fled deeper; the seal stayed half open.",
                event_type_code="session_narrative",
                world_time_offset=36,
            ),
        ),
    ),
    _SessionFixture(
        session_number=3,
        title=None,
        summary=None,
        lifecycle_status_code="pending",
        started_at=None,
        ended_at=None,
        start_world_time_offset=None,
        end_world_time_offset=None,
        events=(),
    ),
)

_CAMPAIGN_B_SESSIONS: tuple[_SessionFixture, ...] = (
    _SessionFixture(
        session_number=1,
        title="Smoke Over Hollowmere",
        summary="The Timeline B party answered the beacon and reached Hollowmere already ablaze.",
        lifecycle_status_code="active",
        started_at=_fixture_timestamp("2026-02-07T19:00:00+00:00"),
        ended_at=_fixture_timestamp("2026-02-07T22:00:00+00:00"),
        start_world_time_offset=50,
        end_world_time_offset=60,
        events=(
            _SessionEventFixture(
                name="Beacon Fire Answered",
                summary="The party rode through the night the signal fire was lit.",
                details="They reached the ridge above Hollowmere by dawn and saw the smoke column.",
                event_type_code="session_narrative",
                world_time_offset=52,
            ),
        ),
    ),
)

# --------------------------------------------------------------------------
# Phase 13D Quest list/detail live-verification fixtures
# --------------------------------------------------------------------------
# Deterministic quests, stages, objectives, and timeline-scoped state for
# the portal's read-only Quest list (`GET /campaigns/{id}/quests`,
# `dnd_ai.queries.quest.list_campaign_quests`) and Quest detail
# (`GET /campaigns/{id}/quests/{quest_id}`, `dnd_ai.queries.quest.
# get_quest_view`) screens, read back by the owner through those real
# endpoints.
#
# Supported vocabularies (all taken from the production schema — migrations
# 073/074 — never invented here):
#
#   quest status (campaign.quest_statuses):      unavailable, available,
#                                                active, suspended,
#                                                completed, failed, abandoned
#   stage type (narrative.quest_stages.          sequential, optional,
#     stage_type CHECK):                         conditional, mutually_exclusive
#   objective type (narrative.objective_types):  reach_location, acquire_item,
#                                                defeat_entity, protect_entity,
#                                                activate_mechanism,
#                                                discover_knowledge,
#                                                persuade_npc, survive_condition,
#                                                complete_before_deadline, other
#   requirement level (narrative.quest_          required, optional, hidden
#     objectives.requirement_level CHECK):
#   completion mode (…completion_mode CHECK):    automatic, gm_confirmed
#   visibility policy (…visibility_policy CHECK): visible, hidden_until_active,
#                                                hidden_until_discovered, gm_only
#   objective status (campaign.objective_        hidden, available, active,
#     statuses):                                 completed, failed, skipped,
#                                                superseded
#
# A quest is only listed by `list_campaign_quests` if it has at least one
# `campaign.quest_state` row on the timeline (docs/PHASE13D_BACKEND_
# READINESS.md §5). So every fixture quest that must appear in the portal's
# list gets a `campaign.quest_state` row:
#
#   - "Restore the Glass Ossuary": one campaign-wide row (party_id NULL),
#     status 'active' — the detailed quest.
#   - "Gather the Hollow Verses": one campaign-wide row, status 'completed',
#     and NO stages — exercises the completed-status badge and the portal's
#     neutral empty-stage state.
#   - "Wake the Tide Beneath Vheil": tracked ONLY through one party's own
#     `campaign.quest_state` row (party_id set, no campaign-wide row). For
#     the supplied account — a campaign owner / GM — `list_campaign_quests`
#     runs with `include_all_parties=True` and `party_id=None`, so this
#     quest IS listed (a GM sees every tracked quest across every party) but
#     its status resolves to NULL (no campaign-wide row, and the GM resolves
#     no party perspective). This is the one legitimate way the production
#     query yields a null quest status for this account — `campaign.quest_
#     state.quest_status_id` itself is NOT NULL, so a campaign-wide row can
#     never carry a null status. Exercises the portal's null-status
#     rendering and null-sorts-last behavior.
#
# Stage ordering: `get_quest_view` returns stages `ORDER BY sequence_number,
# quest_stage_id`. "Restore the Glass Ossuary"'s three stage names are
# deliberately chosen so alphabetical order ("Aftermath…", "Reassemble…",
# "The Warden's Vigil") is the reverse of sequence order (1 "The Warden's
# Vigil", 2 "Reassemble the Reliquary", 3 "Aftermath in the Nave") — a live
# tester can confirm the portal preserves the backend's order rather than
# re-sorting.
#
# Objective visibility for the supplied account: the account holds
# `canon.edit` in Campaign A (every campaign owner does — migration 085), so
# `get_quest_endpoint` sets `include_hidden=True` and `get_quest_view`
# returns EVERY objective regardless of `visibility_policy`, and resolves
# NO party perspective (`authorized_party_id=None`). The fixture still
# includes a `hidden_until_discovered` objective with no state row and a
# `gm_only` objective specifically so the difference is real data — a
# non-GM player perspective would NOT see those two — but this script
# cannot prove their absence for THIS account without weakening its
# authority, which the task forbids. The database/query verification block
# calls `get_quest_view` with the real inputs for this account
# (`include_hidden=True`) and also, separately, with `include_hidden=False`
# to show the filtered (non-GM-audience) result, and prints both — see
# `_print_quest_verification`.
#
# Reconciliation: `narrative.quest_stages`/`.quest_objectives` and
# `campaign.quest_state`/`.objective_state` carry no immutability trigger,
# and a live-testing session is expected to advance objectives (via the
# real `POST …/quests/objectives/{id}/advance` command, which also records
# a `narrative.events` row and sets `last_event_id`). So a re-run reconciles
# the mutable, portal-visible columns back to the documented values —
# stage `sequence_number`/`stage_type`/`description`; objective
# `requirement_level`/`completion_mode`/`visibility_policy`/`description`/
# `quantity_required`/`objective_type_id`; and the `quest_status_id`/
# `objective_status_id` of each fixture-owned state row — and leaves
# `last_event_id` untouched (the causing event, if any, is real recorded
# history and only the status matters to the portal). Fixture quests,
# stages, and objectives are located by their own fixed names (a quest by
# `(world_id, canonical_name)` among `quest`-typed entities); a name found
# on a non-`quest` entity, on a `quest` entity with no `narrative.quests`
# row, or on more than one entity at once is treated as a collision with
# non-fixture/incompatible data and aborts with guidance rather than
# guessing ownership.
#
# Campaign B quest ("Chart the Sunken Marches", `_CAMPAIGN_B_QUEST`): one
# stage, one objective, a campaign-wide `campaign.quest_state` row on
# Timeline B. Its purpose is cross-campaign non-disclosure testing, and it
# reproduces the exact shape that exposed the Phase 13D detail-disclosure
# defect: one world, two timelines, one campaign per timeline, Campaign B's
# quest state only on Timeline B.
#
#   - `list_campaign_quests` is timeline/audience scoped, so this quest
#     never appears in Campaign A's list — verified, and asserted by the
#     focused tests.
#   - `get_quest_view`, called by `get_quest_endpoint` with
#     `require_campaign_tracking=True` and `include_all_parties=<account
#     holds baseline canon.edit>`, now applies the *same* shared
#     timeline/party audience rule (`dnd_ai.queries.quest.
#     _QUEST_STATE_MATCHES_AUDIENCE`). `narrative.quests` is still world
#     canon with no `campaign_id`, but campaign exposure is established by
#     a qualifying `campaign.quest_state` row on the campaign's exact
#     timeline — and Campaign B's quest has none on Timeline A. So
#     requesting this quest's id under Campaign A's URL raises
#     `QuestNotFoundError` → the identical non-disclosing 404 a nonexistent
#     quest id produces. The verification block requests it exactly that
#     way and prints the real result so a live tester sees the behavior
#     directly; the focused query/API tests assert it.

_QUEST_A_ACTIVE_NAME = "Restore the Glass Ossuary"
_QUEST_A_COMPLETED_NAME = "Gather the Hollow Verses"
_QUEST_A_NULL_STATUS_NAME = "Wake the Tide Beneath Vheil"
_CAMPAIGN_B_QUEST_NAME = "Chart the Sunken Marches"

# The party that carries "Wake the Tide Beneath Vheil"'s only quest_state
# row (see the module comment above). Created in Campaign A's world and
# associated with Campaign A via campaign.campaign_parties — no party
# membership rows, since the supplied account never resolves a party
# perspective for quests anyway (it is a GM).
_QUEST_A_PARTY_NAME = "The Ashen Vigil"


@dataclass(frozen=True)
class _ObjectiveFixture:
    """One `narrative.quest_objectives` row plus, optionally, its
    `campaign.objective_state` row. `objective_status_code=None` means no
    state row at all — the portal's "no tracked status yet" rendering, and
    (for `hidden_until_discovered`/`gm_only`) the audience-filtered-out
    case. `description=None` and `quantity_required=None` are the schema's
    real nullable states."""

    name: str
    objective_type_code: str
    requirement_level: str
    completion_mode: str
    visibility_policy: str
    description: str | None
    quantity_required: int | None
    objective_status_code: str | None


@dataclass(frozen=True)
class _StageFixture:
    name: str
    sequence_number: int
    stage_type: str
    description: str | None
    objectives: tuple[_ObjectiveFixture, ...]


@dataclass(frozen=True)
class _QuestFixture:
    """One `narrative.quests` entity plus its stages/objectives and its
    `campaign.quest_state` tracking. `campaign_wide_status_code=None` with
    `party_scoped_status_code` set is the "listed for a GM but null status"
    case (see the module comment); exactly one of the two is expected to be
    set for a quest that must appear in the portal's list."""

    name: str
    campaign_wide_status_code: str | None
    party_scoped_status_code: str | None
    stages: tuple[_StageFixture, ...]


_GLASS_OSSUARY_OBJECTIVES_STAGE_1: tuple[_ObjectiveFixture, ...] = (
    _ObjectiveFixture(
        name="Light the three vigil lanterns",
        objective_type_code="activate_mechanism",
        requirement_level="required",
        completion_mode="automatic",
        visibility_policy="visible",
        description=(
            "Every lantern in the antechamber must burn before the wardens unseal the inner doors."
        ),
        quantity_required=3,
        objective_status_code="completed",
    ),
    _ObjectiveFixture(
        name="Answer the warden's challenge",
        objective_type_code="persuade_npc",
        requirement_level="required",
        completion_mode="gm_confirmed",
        visibility_policy="visible",
        description=None,
        quantity_required=None,
        objective_status_code="active",
    ),
    _ObjectiveFixture(
        name="Recover the sexton's iron key",
        objective_type_code="acquire_item",
        requirement_level="optional",
        completion_mode="automatic",
        visibility_policy="visible",
        description="Optional: the sexton's key opens the reliquary vault without forcing the seals.",
        quantity_required=None,
        objective_status_code=None,
    ),
)

_GLASS_OSSUARY_OBJECTIVES_STAGE_2: tuple[_ObjectiveFixture, ...] = (
    _ObjectiveFixture(
        name="Set the ossuary keystone",
        objective_type_code="other",
        requirement_level="required",
        completion_mode="automatic",
        visibility_policy="visible",
        description="The keystone must be seated before any relic is returned to its niche.",
        quantity_required=None,
        objective_status_code="active",
    ),
    _ObjectiveFixture(
        name="Catalogue the recovered relics",
        objective_type_code="other",
        requirement_level="optional",
        completion_mode="gm_confirmed",
        visibility_policy="hidden_until_discovered",
        description=None,
        quantity_required=5,
        objective_status_code=None,
    ),
    _ObjectiveFixture(
        name="Brief Archivist Vell in private",
        objective_type_code="persuade_npc",
        requirement_level="required",
        completion_mode="automatic",
        visibility_policy="gm_only",
        description="GM-only: Vell must hear of the breach before the players report it publicly.",
        quantity_required=None,
        objective_status_code=None,
    ),
)

_CAMPAIGN_A_QUESTS: tuple[_QuestFixture, ...] = (
    _QuestFixture(
        name=_QUEST_A_ACTIVE_NAME,
        campaign_wide_status_code="active",
        party_scoped_status_code=None,
        stages=(
            _StageFixture(
                name="The Warden's Vigil",
                sequence_number=1,
                stage_type="sequential",
                description="Earn the wardens' leave to enter the ossuary proper.",
                objectives=_GLASS_OSSUARY_OBJECTIVES_STAGE_1,
            ),
            _StageFixture(
                name="Reassemble the Reliquary",
                sequence_number=2,
                stage_type="sequential",
                description="Rebuild the shattered reliquary from the recovered fragments.",
                objectives=_GLASS_OSSUARY_OBJECTIVES_STAGE_2,
            ),
            _StageFixture(
                name="Aftermath in the Nave",
                sequence_number=3,
                stage_type="optional",
                description="Optional follow-up once the reliquary is whole.",
                objectives=(),
            ),
        ),
    ),
    _QuestFixture(
        name=_QUEST_A_COMPLETED_NAME,
        campaign_wide_status_code="completed",
        party_scoped_status_code=None,
        stages=(),
    ),
    _QuestFixture(
        name=_QUEST_A_NULL_STATUS_NAME,
        campaign_wide_status_code=None,
        party_scoped_status_code="active",
        stages=(),
    ),
)

_CAMPAIGN_B_QUEST: _QuestFixture = _QuestFixture(
    name=_CAMPAIGN_B_QUEST_NAME,
    campaign_wide_status_code="active",
    party_scoped_status_code=None,
    stages=(
        _StageFixture(
            name="Sound the Shallows",
            sequence_number=1,
            stage_type="sequential",
            description="Chart a safe passage across the tidal flats.",
            objectives=(
                _ObjectiveFixture(
                    name="Map the tidal causeway",
                    objective_type_code="reach_location",
                    requirement_level="required",
                    completion_mode="automatic",
                    visibility_policy="visible",
                    description="Walk the causeway at low tide and record the safe line.",
                    quantity_required=None,
                    objective_status_code="active",
                ),
            ),
        ),
    ),
)


# --------------------------------------------------------------------------
# Phase 13D World Explorer + Knowledge screen live-verification fixtures
# --------------------------------------------------------------------------
# Deterministic world hierarchy, world-canon entities of every World
# Explorer category, and knowledge records for every Knowledge-screen view,
# read back by the owner through the real merged endpoints
# (`GET /campaigns/{id}/world/search`, `.../world/{locations,religions,items,
# events}/{id}`, `.../world/relationships`, `GET /campaigns/{id}/knowledge`,
# `.../knowledge/{id}`) and their query modules
# (`dnd_ai.queries.world_explorer`, `.knowledge_browse`, `.knowledge`).
#
# Everything below is READ-ONLY portal data. Unlike the character-state /
# session / quest fixtures above, no Phase 13D screen that consumes it has a
# write path (the World and Knowledge screens are read-only —
# docs/PHASE13D_BACKEND_READINESS.md §10.2), so a live-testing session
# cannot drift any of these rows. They are therefore pure create-or-reuse
# by their own fixed names / natural keys (`_get_or_create_*`), with no
# reconciliation branch — the same idempotency `_get_or_create_quest`
# already relies on for a quest entity, applied throughout.
#
# Visibility model (owner decision, docs/PHASE13D_BACKEND_READINESS.md
# §10.1): World Explorer mirrors the existing detail endpoints — a
# `campaign.view` baseline, world-canon entities (locations, organizations,
# religions, items, characters) visible to every `campaign.view` holder on
# the world, `narrative.events` additionally timeline-scoped and
# draft/voided-split, characters additionally gated by the
# `character.discover`/`.view_*` tiers. So cross-campaign isolation is
# demonstrable only for the timeline-scoped concerns — `narrative.events`,
# and every `knowledge.*` row — which is exactly what the Campaign B block
# below exercises. A world-canon location entity created for Campaign B's
# scenario is visible in Campaign A's `/world/search` by that documented
# model; its `campaign.location_state`, the events at it, and all knowledge
# about it are Timeline B only. The verification block states this
# explicitly rather than pretending otherwise.
#
# Audience: the supplied `--user-id` is the campaign owner / GM on both
# campaigns (holds `canon.edit`), and additionally controls Character A and
# Character B (the two `character_perspectives` the bootstrap already
# exposes). A GM's `canon.edit` authority does not change when a
# `character_id` query parameter does, so this one account cannot exercise
# the *non-GM* HTTP path directly — the same limitation
# `_print_quest_verification` already documents. `_print_world_knowledge_
# verification` therefore calls the real query functions both as the GM
# resolves them (`resolve_access_context` -> the real
# `dnd_ai.api.world_explorer` / `dnd_ai.api.knowledge` resolution helpers)
# and, separately, with the non-GM `include_ground_truth=False` +
# resolved-party / resolved-character-knower inputs a player's request
# would produce, and prints both — never a hand-written lookalike query.

_WK_SORT_KEY_BASE = 14_000_000
_WK_WORLD_TIME_LABEL_PREFIX = "Phase13D world/knowledge fixture"

# The knowledge party (Campaign A / Timeline A). Reuses the existing Phase
# 13 users/characters: Character A and Character B are both current members,
# so `resolve_party_perspective` authorizes the owner to read `known` /
# `rumors` / `party_shared` through it for either character, and the two
# characters' `character_private` views differ.
_WK_PARTY_NAME = "The Lantern-Bearers"


@dataclass(frozen=True)
class _LocationFixture:
    """One `world.locations` row (plus the matching subtype row for a
    settlement / building / dungeon / dungeon_area) and its children. The
    tree is walked depth-first with `parent_location_id` threaded through,
    so the containment hierarchy — and the World Explorer's breadcrumb
    trail — is whatever this nesting says."""

    name: str
    entity_type_code: str
    summary: str
    # settlement.population / building.building_use / dungeon.danger_level —
    # exactly one is meaningful per `entity_type_code`, the rest stay None.
    population: int | None = None
    building_use: str | None = None
    danger_level: int | None = None
    children: tuple[_LocationFixture, ...] = ()


# Campaign A world hierarchy: continent -> region -> settlement -> building
# (four containment levels), plus a dungeon (child of the region) with one
# dungeon area. Names are distinct enough to exercise case-insensitive
# search and type filtering.
_CAMPAIGN_A_LOCATIONS = _LocationFixture(
    name="Auremar",
    entity_type_code="continent",
    summary="The western continent; the Ashen Vale is its storm-battered southern coast.",
    children=(
        _LocationFixture(
            name="The Ashen Vale",
            entity_type_code="region",
            summary="A tide-scoured coastal region of salt marsh, drowned ruins, and old crypts.",
            children=(
                _LocationFixture(
                    name="Hollowmere",
                    entity_type_code="settlement",
                    summary="A fishing town rebuilt on the drowned ruins of an older city.",
                    population=4200,
                    children=(
                        _LocationFixture(
                            name="The Sunken Archive",
                            entity_type_code="building",
                            summary="Hollowmere's half-flooded library and records hall.",
                            building_use="library and records hall",
                        ),
                    ),
                ),
                _LocationFixture(
                    name="The Tidebound Crypt",
                    entity_type_code="dungeon",
                    summary="A sea-cave ossuary below the vale; its lower vault floods at high tide.",
                    danger_level=6,
                    children=(
                        _LocationFixture(
                            name="The Lantern Antechamber",
                            entity_type_code="dungeon_area",
                            summary="The first chamber past the crypt doors, ringed with dead lanterns.",
                        ),
                    ),
                ),
            ),
        ),
    ),
)

# Campaign B (Timeline B) — one distinct world-canon location. See the block
# comment above: the entity itself is world canon and appears in Campaign
# A's search too; its state / events / knowledge are Timeline B only, and
# those are what prove isolation.
_CAMPAIGN_B_LOCATION = _LocationFixture(
    name="Saltreach Harbor",
    entity_type_code="settlement",
    summary="A Timeline-B harbor town north of the vale; its beacon guides ships past the reefs.",
    population=2600,
)

_HOLLOWMERE_STATE = {
    "is_searched": True,
    "is_destroyed": False,
    "alarm_level": 1,
    "condition_notes": "Docks quarter still rebuilding after the last flood tide.",
}
_SALTREACH_STATE = {
    "is_searched": False,
    "is_destroyed": False,
    "alarm_level": 0,
    "condition_notes": "Beacon tower reported dark for three nights running.",
}

# --- World Explorer non-location entities (Campaign A) ---------------------

_NPC_NAME = "Archivist Sella Vane"
_NPC_SPECIES_CODE = "human"
_NPC_SUMMARY = (
    "The Sunken Archive's senior archivist; keeps a private ledger of what leaves the stacks."
)

_GUILD_NAME = "The Cartographers' Guild"
_GUILD_PUBLIC_DESCRIPTION = "Hollowmere's chartered guild of mapmakers and tide-readers."
_GUILD_INTERNAL_DESCRIPTION = (
    "GM-only: the Guild quietly sells the Magistracy advance copies of every survey it files."
)

_GOVERNMENT_NAME = "The Hollowmere Magistracy"
_GOVERNMENT_PUBLIC_DESCRIPTION = "The elected council that governs Hollowmere and the lower vale."
_GOVERNMENT_FORM = "elected council"

_RELIGION_NAME = "The Tidefather Communion"
_RELIGION_PANTHEON = "monolatry"
_RELIGION_SUMMARY = (
    "The vale's dominant faith; venerates the Tidefather, who is said to rule the drowned."
)
_RELIGIOUS_ORG_NAME = "The Wardens of the Tide"
_RELIGIOUS_ORG_PUBLIC_DESCRIPTION = (
    "The Communion's lay order; tends the crypts and the shore shrines."
)

_HELD_ITEM_NAME = "The Warden's Lantern"
_HELD_ITEM_ORIGIN = (
    "Recovered from the Lantern Antechamber; lights only for someone of Warden blood."
)
_LOOSE_ITEM_NAME = "The Drowned Crown"
_LOOSE_ITEM_ORIGIN = "Still resting in the Tidebound Crypt's lower vault; no living claimant."


@dataclass(frozen=True)
class _EventFixture:
    """One `narrative.events` row for the World Explorer historical-event
    category. `status_code` is `recorded` for the two visible events and
    `draft` for the one only a GM may see (the World Explorer draft/voided
    split — docs/PHASE13D_BACKEND_READINESS.md §10.1). Participants and
    locations are resolved by fixture name at insert time."""

    name: str
    summary: str
    details: str
    event_type_code: str
    status_code: str
    world_time_offset: int
    participant_names: tuple[tuple[str, str], ...]  # (entity name, role code)
    location_names: tuple[str, ...]  # occurred_at


_CAMPAIGN_A_EVENTS: tuple[_EventFixture, ...] = (
    _EventFixture(
        name="The Sundering of the Vale",
        summary="The storm-year that split the old coast road and drowned half of Aurell.",
        details=(
            "A season of impossible tides. The outer city went under in a night; the survivors "
            "founded Hollowmere on the high ground above the ruin."
        ),
        event_type_code="other",
        status_code="recorded",
        world_time_offset=100,
        participant_names=((_NPC_NAME, "witness"),),
        location_names=("The Ashen Vale",),
    ),
    _EventFixture(
        name="The Sealing of the Sluice-Gates",
        summary="The Magistracy ordered Hollowmere's old sluice-gates welded shut.",
        details=(
            "Framed publicly as flood control. The Archive's copy of the order cites the salvage "
            "levy the open gates were costing the treasury."
        ),
        event_type_code="other",
        status_code="recorded",
        world_time_offset=400,
        participant_names=((_NPC_NAME, "witness"), (_CHARACTER_A_NAME, "actor")),
        location_names=("Hollowmere",),
    ),
    _EventFixture(
        name="The Magistrate's Secret Accord",
        summary="GM-only draft: a private pact between the Magistracy and the Wardens of the Tide.",
        details=(
            "Not yet canon. Records the Magistrate agreeing to leave the lower vault undisturbed "
            "in exchange for the Wardens' silence about the sluice-gate order."
        ),
        event_type_code="other",
        status_code="draft",
        world_time_offset=450,
        participant_names=(),
        location_names=("The Tidebound Crypt",),
    ),
)

_CAMPAIGN_B_EVENT = _EventFixture(
    name="The Darkening of the Saltreach Beacon",
    summary="Timeline B: the harbor beacon went dark and a grain ship struck the reef.",
    details="The beacon-keeper was later found to have been paid to let the fire die.",
    event_type_code="other",
    status_code="recorded",
    world_time_offset=600,
    participant_names=(),
    location_names=("Saltreach Harbor",),
)

# --- Knowledge records (Campaign A / Timeline A) --------------------------
# Every combination the Knowledge screen's views and audience-safe DTO need
# to be visible at once. `owner` = which belief carries the row:
#   party      -> campaign.party_knowledge for _WK_PARTY_NAME
#   character_a -> knowledge.entity_knowledge, knower = Character A
#   character_b -> knowledge.entity_knowledge, knower = Character B
#   public     -> knowledge.public_knowledge on Timeline A
#   canonical  -> knowledge_items only (no belief row) -> only a GM sees it
# `discovered` adds a knowledge.party_discoveries row (party-owned) with a
# fictional world time + source event, so the item appears in `recent` and
# carries visible source provenance.


@dataclass(frozen=True)
class _KnowledgeFixture:
    statement: str
    knowledge_type_code: str
    truth_status_code: str
    sensitivity: str
    owner: str
    subject_name: str | None
    awareness_level: str | None = None
    confidence: int | None = None
    interpretation: str | None = None
    willing_to_share: bool = True
    discovered: bool = False
    discovery_world_time_offset: int | None = None
    discovery_source_event_name: str | None = None


_CAMPAIGN_A_KNOWLEDGE: tuple[_KnowledgeFixture, ...] = (
    # known fact — settled type, no interpretation -> canonical text shown
    _KnowledgeFixture(
        statement="The Tidebound Crypt's lower vault floods completely at every high tide.",
        knowledge_type_code="fact",
        truth_status_code="true",
        sensitivity="public",
        owner="party",
        subject_name="The Tidebound Crypt",
        awareness_level="aware",
        confidence=90,
    ),
    # rumor — rumor-set type
    _KnowledgeFixture(
        statement="A drowned king still holds court in the vault and answers to no living crown.",
        knowledge_type_code="rumor",
        truth_status_code="false",
        sensitivity="public",
        owner="party",
        subject_name="The Tidebound Crypt",
        awareness_level="rumored",
        confidence=20,
    ),
    # materially distorted party belief — interpretation differs from canon
    _KnowledgeFixture(
        statement="The Magistracy sealed the sluice-gates to cut the treasury's salvage-levy losses.",
        knowledge_type_code="secret",
        truth_status_code="true",
        sensitivity="restricted",
        owner="party",
        subject_name=_GOVERNMENT_NAME,
        awareness_level="suspected",
        confidence=55,
        interpretation=(
            "The Magistracy sealed the sluice-gates to appease the Tidefather after the Sundering."
        ),
        willing_to_share=False,
    ),
    # recently discovered — party discovery + belief, fictional timestamp,
    # visible source provenance (discovered_via_event_id)
    _KnowledgeFixture(
        statement="The Sunken Archive has a sealed sub-basement below the flood line.",
        knowledge_type_code="claim",
        truth_status_code="partially_true",
        sensitivity="restricted",
        owner="party",
        subject_name="The Sunken Archive",
        awareness_level="aware",
        confidence=70,
        interpretation="Sella let slip there's a sub-basement the Magistracy had bricked over.",
        discovered=True,
        discovery_world_time_offset=800,
        discovery_source_event_name="The Sealing of the Sluice-Gates",
    ),
    # character-private for Character A
    _KnowledgeFixture(
        statement="Sella Vane keeps a private ledger of everything the Magistracy removed from the Archive.",
        knowledge_type_code="secret",
        truth_status_code="true",
        sensitivity="secret",
        owner="character_a",
        subject_name=_NPC_NAME,
        awareness_level="aware",
        confidence=80,
        interpretation="Sella showed me the ledger — three crates went straight to the Magistrate's house.",
        willing_to_share=False,
    ),
    # different character-private for Character B
    _KnowledgeFixture(
        statement="The Warden's Lantern only takes flame for someone of Warden blood.",
        knowledge_type_code="memory",
        truth_status_code="true",
        sensitivity="public",
        owner="character_b",
        subject_name=_HELD_ITEM_NAME,
        awareness_level="aware",
        confidence=100,
        interpretation="I held the lantern in the antechamber and it flared the moment I touched it.",
    ),
    # public lore connected to a world resource
    _KnowledgeFixture(
        statement="Hollowmere is built directly over the drowned ruins of the older city of Aurell.",
        knowledge_type_code="fact",
        truth_status_code="partially_true",
        sensitivity="public",
        owner="public",
        subject_name="Hollowmere",
        awareness_level="aware",
    ),
    # knowledge related to a quest (subject is the quest entity)
    _KnowledgeFixture(
        statement="The Glass Ossuary can only be re-consecrated at slack tide, never on the flood.",
        knowledge_type_code="instruction",
        truth_status_code="true",
        sensitivity="public",
        owner="party",
        subject_name=_QUEST_A_ACTIVE_NAME,
        awareness_level="aware",
        confidence=75,
    ),
    # intentionally undiscovered by the ordinary player: canonical only,
    # no party/character belief -> a GM's canonical `known` view shows it,
    # the player's party/character views never do.
    _KnowledgeFixture(
        statement="The Wardens of the Tide answer to the thing in the vault, not to the Communion.",
        knowledge_type_code="secret",
        truth_status_code="true",
        sensitivity="dangerous",
        owner="canonical",
        subject_name=_RELIGIOUS_ORG_NAME,
    ),
)

_CAMPAIGN_B_KNOWLEDGE = _KnowledgeFixture(
    statement="The Saltreach beacon-keeper was bribed to let the signal fire go out.",
    knowledge_type_code="claim",
    truth_status_code="true",
    sensitivity="restricted",
    owner="public",
    subject_name="Saltreach Harbor",
    awareness_level="aware",
)

# A visible relationship between two visible world resources: Sella Vane is
# a member of the Cartographers' Guild.
_WK_RELATIONSHIP_TYPE_CODE = "membership"
_WK_RELATIONSHIP_DESCRIPTION = "Archivist Sella Vane is the Cartographers' Guild's senior member."


@dataclass(frozen=True)
class _UserInfo:
    user_id: uuid.UUID
    display_name: str
    login_name: str | None
    is_platform_administrator: bool


@dataclass
class _Summary:
    lines: list[str] = field(default_factory=list)
    # A human-readable quick reference (session/event ids, portal headings,
    # the cross-campaign test hint) printed after `lines` in both preview
    # and apply mode — see `_note_session`/`main`. Never carries a
    # created/reused/reconciled verb; that stays in `lines`.
    report: list[str] = field(default_factory=list)
    # The same kind of quick reference, for the Phase 13D quest fixtures —
    # printed under its own header (see `main`). Kept separate from
    # `report` only so the two blocks stay visually distinct in the output.
    quest_report: list[str] = field(default_factory=list)
    # The same kind of quick reference, for the Phase 13D World Explorer +
    # Knowledge fixtures — printed under its own header (see `main`).
    world_report: list[str] = field(default_factory=list)

    def note(self, line: str) -> None:
        self.report.append(line)

    def note_quest(self, line: str) -> None:
        self.quest_report.append(line)

    def note_world(self, line: str) -> None:
        self.world_report.append(line)

    def add(
        self,
        *,
        created: bool,
        label: str,
        record_id: uuid.UUID | str,
        changed: bool = False,
    ) -> None:
        """`changed` only ever matters when `created` is False: it
        distinguishes an already-matching row (plain "reused") from one
        this run just reset back to the fixture's documented values
        ("reconciled") — see `_ensure_character_state`/
        `_ensure_character_condition`/`_ensure_character_resource`, the
        only callers that ever pass it. Every other call site here never
        reconciles an existing row (it either matches by construction —
        the fixture's own fixed name/slug — or is left untouched), so
        omitting `changed` keeps their unchanged "created"/"reused"
        behavior exactly as before."""
        if created:
            verb = "created"
        elif changed:
            verb = "reconciled (updated to match fixture)"
        else:
            verb = "reused (already existed)"
        self.lines.append(f"  [{verb}] {label}: {record_id}")


def _require_non_production() -> None:
    if settings.environment == "production":
        print(
            "Refusing to run: DND_AI_ENVIRONMENT=production. This script is a "
            "development-data convenience and must never target a real deployment.",
            file=sys.stderr,
        )
        raise SystemExit(2)


_LOCAL_DB_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", ""})


def _safe_target_summary() -> str:
    """Host / port / database of the resolved `DATABASE_URL`, password
    redacted — printed before any mutation so the operator can confirm the
    target. Never returns or logs the credential."""
    url = make_url(_database_url())
    user = f"{url.username}@" if url.username else ""
    return f"{url.drivername} {user}{url.host or '<none>'}:{url.port or 5432}/{url.database}"


def _require_local_target() -> None:
    """Refuse a remote / production-looking database. The developer's native
    PostgreSQL is `127.0.0.1:5432` (docs/DEVELOPMENT.md §3.1); the Compose
    database is reachable as `localhost` on the host. A non-loopback host,
    or a database name that looks like a real deployment, aborts unless
    `DND_AI_ALLOW_NONLOCAL_DEV_DATA=1` is set to acknowledge an
    intentionally non-standard but still-safe target."""
    if settings.environment not in (None, "", "local", "development", "dev", "test"):
        print(
            f"Refusing to run: DND_AI_ENVIRONMENT={settings.environment!r} is not a "
            "local/development environment.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    if os.environ.get("DND_AI_ALLOW_NONLOCAL_DEV_DATA") == "1":
        return
    url = make_url(_database_url())
    host = (url.host or "").lower()
    database = (url.database or "").lower()
    if host not in _LOCAL_DB_HOSTS:
        print(
            f"Refusing to run: DATABASE_URL host {url.host!r} is not a loopback address. "
            "This fixture only targets a local/self-hosted development database. Set "
            "DND_AI_ALLOW_NONLOCAL_DEV_DATA=1 to override for a known-safe non-standard host.",
            file=sys.stderr,
        )
        raise SystemExit(2)
    if any(marker in database for marker in ("prod", "production", "live")):
        print(
            f"Refusing to run: DATABASE_URL database name {url.database!r} looks like a real "
            "deployment. Set DND_AI_ALLOW_NONLOCAL_DEV_DATA=1 to override.",
            file=sys.stderr,
        )
        raise SystemExit(2)


def _database_url() -> str:
    """`settings.database_url` is always resolved to a real value by the
    time `Settings()` finishes construction (`dnd_ai.config.Settings.
    _resolve_database_url`) — its `str | None` annotation only reflects
    the field's un-validated default. `_require_non_production` has
    already run by every call site here, so this can only be the
    resolved local/legacy database URL, never a production one."""
    url = settings.database_url
    assert url is not None
    return url


def _resolve_user(connection: Connection, user_id: uuid.UUID) -> _UserInfo:
    row = (
        connection.execute(
            text("""
                SELECT u.user_id, u.display_name, u.is_platform_administrator, ls.code AS lifecycle,
                       ei.subject AS login_name,
                       (lc.local_credential_id IS NOT NULL) AS has_password
                FROM security.users u
                JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = u.lifecycle_status_id
                LEFT JOIN security.external_identities ei
                    ON ei.user_id = u.user_id AND ei.issuer = 'local' AND ei.revoked_at IS NULL
                LEFT JOIN security.local_credentials lc ON lc.user_id = u.user_id
                WHERE u.user_id = :user_id
            """),
            {"user_id": user_id},
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise SystemExit(f"--user-id {user_id} does not exist in security.users.")
    if row["lifecycle"] != "active":
        raise SystemExit(
            f"--user-id {user_id} is not active (lifecycle status: {row['lifecycle']})."
        )
    if row["login_name"] is None or not row["has_password"]:
        raise SystemExit(
            f"--user-id {user_id} has no active local (issuer='local') login credential — "
            "this script only authorizes an existing local account, never creates one."
        )
    return _UserInfo(
        user_id=row["user_id"],
        display_name=row["display_name"],
        login_name=row["login_name"],
        is_platform_administrator=row["is_platform_administrator"],
    )


def _get_or_create_world(connection: Connection, summary: _Summary) -> uuid.UUID:
    existing = connection.execute(
        text("SELECT world_id FROM core.worlds WHERE slug = :slug"), {"slug": _WORLD_SLUG}
    ).scalar()
    if existing is not None:
        assert isinstance(existing, uuid.UUID)
        summary.add(created=False, label=f"world {_WORLD_NAME!r}", record_id=existing)
        return existing

    active_status = lookup_id(
        connection, "core", "lifecycle_statuses", "lifecycle_status_id", "active"
    )
    world_id = connection.execute(
        text("""
            INSERT INTO core.worlds (name, slug, description, lifecycle_status_id)
            VALUES (:name, :slug, :description, :status)
            RETURNING world_id
        """),
        {
            "name": _WORLD_NAME,
            "slug": _WORLD_SLUG,
            "description": _FIXTURE_DESCRIPTION,
            "status": active_status,
        },
    ).scalar()
    assert isinstance(world_id, uuid.UUID)
    summary.add(created=True, label=f"world {_WORLD_NAME!r}", record_id=world_id)
    return world_id


def _get_ruleset(connection: Connection) -> tuple[uuid.UUID, uuid.UUID]:
    """Returns (ruleset_id, current ruleset_version_id) for the pre-existing
    `_RULESET_CODE` ruleset. Never creates a ruleset — this script only
    reuses whatever the database already has, per the task's own
    "reuse the existing ruleset version only after verifying compatibility"
    instruction."""
    row = connection.execute(
        text("""
            SELECT r.ruleset_id, rv.ruleset_version_id
            FROM rules.rulesets r
            JOIN rules.ruleset_versions rv ON rv.ruleset_id = r.ruleset_id
            WHERE r.code = :code AND rv.is_current
        """),
        {"code": _RULESET_CODE},
    ).one_or_none()
    if row is None:
        raise SystemExit(
            f"expected an existing rules.rulesets row (code={_RULESET_CODE!r}) with a current "
            "rules.ruleset_versions row — none found. This script only reuses an existing "
            "ruleset; it does not create one."
        )
    ruleset_id, ruleset_version_id = row
    assert isinstance(ruleset_id, uuid.UUID)
    assert isinstance(ruleset_version_id, uuid.UUID)
    return ruleset_id, ruleset_version_id


def _ensure_world_ruleset(
    connection: Connection, summary: _Summary, *, world_id: uuid.UUID, ruleset_id: uuid.UUID
) -> None:
    existing = connection.execute(
        text(
            "SELECT 1 FROM rules.world_rulesets WHERE world_id = :world AND ruleset_id = :ruleset"
        ),
        {"world": world_id, "ruleset": ruleset_id},
    ).scalar()
    if existing is not None:
        summary.add(
            created=False, label="world/ruleset association", record_id=f"{world_id}/{ruleset_id}"
        )
        return
    connection.execute(
        text("INSERT INTO rules.world_rulesets (world_id, ruleset_id) VALUES (:world, :ruleset)"),
        {"world": world_id, "ruleset": ruleset_id},
    )
    connection.execute(
        text(
            "UPDATE core.worlds SET default_ruleset_id = :ruleset "
            "WHERE world_id = :world AND default_ruleset_id IS NULL"
        ),
        {"world": world_id, "ruleset": ruleset_id},
    )
    summary.add(
        created=True, label="world/ruleset association", record_id=f"{world_id}/{ruleset_id}"
    )


def _get_or_create_timeline(
    connection: Connection, summary: _Summary, *, world_id: uuid.UUID, name: str
) -> uuid.UUID:
    existing = connection.execute(
        text("SELECT timeline_id FROM campaign.timelines WHERE world_id = :world AND name = :name"),
        {"world": world_id, "name": name},
    ).scalar()
    if existing is not None:
        assert isinstance(existing, uuid.UUID)
        summary.add(created=False, label=f"timeline {name!r}", record_id=existing)
        return existing

    active_status = lookup_id(
        connection, "core", "lifecycle_statuses", "lifecycle_status_id", "active"
    )
    timeline_id = connection.execute(
        text("""
            INSERT INTO campaign.timelines (world_id, name, is_primary, lifecycle_status_id)
            VALUES (:world, :name, false, :status)
            RETURNING timeline_id
        """),
        {"world": world_id, "name": name, "status": active_status},
    ).scalar()
    assert isinstance(timeline_id, uuid.UUID)
    summary.add(created=True, label=f"timeline {name!r}", record_id=timeline_id)
    return timeline_id


def _ensure_relationship_type_capabilities(connection: Connection, summary: _Summary) -> None:
    """One-time global seed for `security.character_relationship_type_
    capabilities` — see this module's own docstring for why this table
    ships empty and why that blocks every character perspective, not just
    this fixture's. Only ever adds rows when the whole table is empty;
    never touches it again once any row exists (even for an unrelated
    relationship type), since that would mean some other process — a future
    real seed migration — has since taken ownership of this configuration."""
    already_configured = connection.execute(
        text("SELECT 1 FROM security.character_relationship_type_capabilities LIMIT 1")
    ).scalar()
    if already_configured is not None:
        summary.add(
            created=False,
            label="security.character_relationship_type_capabilities (global)",
            record_id="already configured, left untouched",
        )
        return

    relationship_type_id = lookup_id(
        connection,
        "security",
        "character_relationship_types",
        "character_relationship_type_id",
        _RELATIONSHIP_TYPE_CODE,
    )
    capability_ids = (
        connection.execute(
            text(
                "SELECT capability_id FROM security.capabilities WHERE code LIKE 'character.%' AND is_active"
            )
        )
        .scalars()
        .all()
    )
    if not capability_ids:
        raise SystemExit("no active security.capabilities rows found with code LIKE 'character.%'.")
    for capability_id in capability_ids:
        connection.execute(
            text(
                "INSERT INTO security.character_relationship_type_capabilities "
                "(character_relationship_type_id, capability_id) VALUES (:type, :capability)"
            ),
            {"type": relationship_type_id, "capability": capability_id},
        )
    summary.add(
        created=True,
        label=(
            f"security.character_relationship_type_capabilities (global): all "
            f"{len(capability_ids)} character.* capabilities -> '{_RELATIONSHIP_TYPE_CODE}'"
        ),
        record_id=relationship_type_id,
    )


def _get_or_create_campaign(
    connection: Connection,
    summary: _Summary,
    *,
    timeline_id: uuid.UUID,
    ruleset_version_id: uuid.UUID,
    name: str,
    user: _UserInfo,
) -> tuple[uuid.UUID, uuid.UUID]:
    """Returns (campaign_id, campaign_membership_id) for `user` in the named
    campaign on `timeline_id`, creating it (via the real `create_campaign`
    command, after issuing the real `grant_timeline_bootstrap` entitlement)
    only if no campaign with this fixture's exact name already exists on
    this timeline."""
    existing_campaign_id = connection.execute(
        text(
            "SELECT campaign_id FROM campaign.campaigns WHERE timeline_id = :timeline AND name = :name"
        ),
        {"timeline": timeline_id, "name": name},
    ).scalar()
    if existing_campaign_id is not None:
        membership_id = connection.execute(
            text(
                "SELECT campaign_membership_id FROM security.campaign_memberships "
                "WHERE campaign_id = :campaign AND user_id = :user"
            ),
            {"campaign": existing_campaign_id, "user": user.user_id},
        ).scalar()
        if membership_id is None:
            raise SystemExit(
                f"campaign {name!r} already exists ({existing_campaign_id}) but "
                f"--user-id {user.user_id} has no membership in it — ambiguous, refusing to "
                "proceed rather than guessing."
            )
        summary.add(created=False, label=f"campaign {name!r}", record_id=existing_campaign_id)
        summary.add(
            created=False, label=f"  membership for {user.display_name!r}", record_id=membership_id
        )
        return existing_campaign_id, membership_id

    grant_timeline_bootstrap(connection, timeline_id=timeline_id, granted_to_user_id=user.user_id)
    result = create_campaign(
        connection,
        timeline_id=timeline_id,
        ruleset_version_id=ruleset_version_id,
        name=name,
        creator_user_id=user.user_id,
        description=_FIXTURE_DESCRIPTION,
    )
    record_change_log(
        connection,
        change_action_code=_CREATED_CHANGE_ACTION,
        schema_name="campaign",
        table_name="campaigns",
        record_id=result.campaign_id,
        entity_id=None,
        world_id=result.world_id,
        actor_user_id=user.user_id,
        correlation_id=None,
        command_name=_COMMAND_NAME,
        event_id=None,
    )
    summary.add(created=True, label=f"campaign {name!r}", record_id=result.campaign_id)
    summary.add(
        created=True,
        label=f"  owning membership for {user.display_name!r}",
        record_id=result.campaign_membership_id,
    )
    return result.campaign_id, result.campaign_membership_id


def _get_or_create_character(
    connection: Connection,
    summary: _Summary,
    *,
    world_id: uuid.UUID,
    name: str,
    species_code: str,
    ruleset_version_id: uuid.UUID,
    owner_user_id: uuid.UUID,
) -> uuid.UUID:
    existing = connection.execute(
        text(
            "SELECT entity_id FROM core.entities WHERE world_id = :world AND canonical_name = :name"
        ),
        {"world": world_id, "name": name},
    ).scalar()
    if existing is not None:
        assert isinstance(existing, uuid.UUID)
        summary.add(created=False, label=f"character {name!r}", record_id=existing)
        return existing

    species_id = connection.execute(
        text(
            "SELECT species_id FROM rules.species WHERE ruleset_version_id = :ruleset_version AND code = :code"
        ),
        {"ruleset_version": ruleset_version_id, "code": species_code},
    ).scalar()
    if species_id is None:
        raise SystemExit(
            f"expected an existing rules.species row (code={species_code!r}) for ruleset version "
            f"{ruleset_version_id} — none found. This script only reuses existing species content."
        )

    player_character_type_id = lookup_id(
        connection, "core", "entity_types", "entity_type_id", "player_character"
    )
    canon_status_id = lookup_id(connection, "core", "canon_statuses", "canon_status_id", "canon")
    active_status_id = lookup_id(
        connection, "core", "lifecycle_statuses", "lifecycle_status_id", "active"
    )

    entity_id = connection.execute(
        text("""
            INSERT INTO core.entities
                (world_id, entity_type_id, canonical_name, canon_status_id, lifecycle_status_id,
                 created_by_user_id)
            VALUES (:world, :entity_type, :name, :canon, :lifecycle, :created_by)
            RETURNING entity_id
        """),
        {
            "world": world_id,
            "entity_type": player_character_type_id,
            "name": name,
            "canon": canon_status_id,
            "lifecycle": active_status_id,
            "created_by": owner_user_id,
        },
    ).scalar()
    assert isinstance(entity_id, uuid.UUID)

    connection.execute(
        text("""
            INSERT INTO character.characters (character_id, species_id, size_category)
            VALUES (:character, :species, :size)
        """),
        {"character": entity_id, "species": species_id, "size": _CHARACTER_SIZE_CATEGORY},
    )
    connection.execute(
        text("""
            INSERT INTO character.player_characters (player_character_id, player_user_id)
            VALUES (:character, :player_user)
        """),
        {"character": entity_id, "player_user": owner_user_id},
    )
    summary.add(created=True, label=f"character {name!r} ({species_code})", record_id=entity_id)
    return entity_id


def _ensure_character_state(
    connection: Connection,
    summary: _Summary,
    *,
    timeline_id: uuid.UUID,
    character_id: uuid.UUID,
    character_label: str,
    state: _CharacterStateFixture,
) -> None:
    """Create-or-reconcile `campaign.character_state` for `character_id` on
    `timeline_id`: inserted if absent, reset to `state`'s exact values if
    present but different (e.g. after a live-testing session adjusted HP
    via the real commands), left untouched (and reported as "reused") if
    already matching. Direct insert/update, no narrative event — see this
    module's own docstring for why that is correct here rather than a gap."""
    existing = (
        connection.execute(
            text("""
                SELECT current_hit_points, maximum_hit_points, temporary_hit_points,
                       exhaustion_level, death_save_successes, death_save_failures
                FROM campaign.character_state
                WHERE timeline_id = :timeline AND character_id = :character
            """),
            {"timeline": timeline_id, "character": character_id},
        )
        .mappings()
        .one_or_none()
    )

    label = f"character state: {character_label}"
    params = {
        "timeline": timeline_id,
        "character": character_id,
        "current": state.current_hit_points,
        "maximum": state.maximum_hit_points,
        "temporary": state.temporary_hit_points,
        "exhaustion": state.exhaustion_level,
        "successes": state.death_save_successes,
        "failures": state.death_save_failures,
    }

    if existing is None:
        connection.execute(
            text("""
                INSERT INTO campaign.character_state
                    (timeline_id, character_id, current_hit_points, maximum_hit_points,
                     temporary_hit_points, exhaustion_level, death_save_successes,
                     death_save_failures)
                VALUES (:timeline, :character, :current, :maximum, :temporary, :exhaustion,
                        :successes, :failures)
            """),
            params,
        )
        summary.add(created=True, label=label, record_id=character_id)
        return

    matches = (
        existing["current_hit_points"] == state.current_hit_points
        and existing["maximum_hit_points"] == state.maximum_hit_points
        and existing["temporary_hit_points"] == state.temporary_hit_points
        and existing["exhaustion_level"] == state.exhaustion_level
        and existing["death_save_successes"] == state.death_save_successes
        and existing["death_save_failures"] == state.death_save_failures
    )
    if matches:
        summary.add(created=False, changed=False, label=label, record_id=character_id)
        return

    connection.execute(
        text("""
            UPDATE campaign.character_state
            SET current_hit_points = :current, maximum_hit_points = :maximum,
                temporary_hit_points = :temporary, exhaustion_level = :exhaustion,
                death_save_successes = :successes, death_save_failures = :failures,
                updated_at = now()
            WHERE timeline_id = :timeline AND character_id = :character
        """),
        params,
    )
    summary.add(created=False, changed=True, label=label, record_id=character_id)


def _resolve_condition_id(
    connection: Connection, *, ruleset_version_id: uuid.UUID, code: str
) -> uuid.UUID:
    """`rules.conditions.code` is unique only per `ruleset_version_id` — an
    unscoped lookup by code alone could resolve an arbitrary row from an
    unrelated ruleset, the same reasoning `dnd_ai.commands.character_state`'s
    own docstring gives for taking `condition_id` rather than a bare code."""
    condition_id = connection.execute(
        text(
            "SELECT condition_id FROM rules.conditions "
            "WHERE ruleset_version_id = :ruleset_version AND code = :code"
        ),
        {"ruleset_version": ruleset_version_id, "code": code},
    ).scalar()
    if condition_id is None:
        raise SystemExit(
            f"expected an existing rules.conditions row (code={code!r}) for ruleset version "
            f"{ruleset_version_id} — none found. Seed database/seeds/rules.conditions.yaml "
            "before running this fixture; this script only reuses existing rules content."
        )
    assert isinstance(condition_id, uuid.UUID)
    return condition_id


def _ensure_character_condition(
    connection: Connection,
    summary: _Summary,
    *,
    timeline_id: uuid.UUID,
    character_id: uuid.UUID,
    character_label: str,
    condition_id: uuid.UUID,
    condition_code: str,
    source_description: str,
) -> None:
    """Create-or-reconcile the single fixture-owned `campaign.
    character_conditions` row for `character_id`/`condition_id` on
    `timeline_id` — reset to `source_description` if the row exists with a
    different one (e.g. removed and reapplied during live testing with a
    different note), left untouched if already matching. Does not touch any
    other condition a character may have picked up during live testing —
    only this fixture's own exact `(timeline_id, character_id,
    condition_id)` row."""
    existing = (
        connection.execute(
            text("""
                SELECT source_description FROM campaign.character_conditions
                WHERE timeline_id = :timeline AND character_id = :character
                  AND condition_id = :condition
            """),
            {"timeline": timeline_id, "character": character_id, "condition": condition_id},
        )
        .mappings()
        .one_or_none()
    )

    label = f"condition {condition_code!r}: {character_label}"

    if existing is None:
        connection.execute(
            text("""
                INSERT INTO campaign.character_conditions
                    (timeline_id, character_id, condition_id, source_description)
                VALUES (:timeline, :character, :condition, :source)
            """),
            {
                "timeline": timeline_id,
                "character": character_id,
                "condition": condition_id,
                "source": source_description,
            },
        )
        summary.add(created=True, label=label, record_id=character_id)
        return

    if existing["source_description"] == source_description:
        summary.add(created=False, changed=False, label=label, record_id=character_id)
        return

    connection.execute(
        text("""
            UPDATE campaign.character_conditions
            SET source_description = :source
            WHERE timeline_id = :timeline AND character_id = :character
              AND condition_id = :condition
        """),
        {
            "timeline": timeline_id,
            "character": character_id,
            "condition": condition_id,
            "source": source_description,
        },
    )
    summary.add(created=False, changed=True, label=label, record_id=character_id)


def _resolve_resource_definition_id(
    connection: Connection, *, ruleset_version_id: uuid.UUID, code: str
) -> uuid.UUID:
    """`rules.resource_definitions.code` is unique only per
    `ruleset_version_id` — the same scoping `_resolve_condition_id` applies,
    for the same reason."""
    resource_definition_id = connection.execute(
        text(
            "SELECT resource_definition_id FROM rules.resource_definitions "
            "WHERE ruleset_version_id = :ruleset_version AND code = :code"
        ),
        {"ruleset_version": ruleset_version_id, "code": code},
    ).scalar()
    if resource_definition_id is None:
        raise SystemExit(
            f"expected an existing rules.resource_definitions row (code={code!r}) for ruleset "
            f"version {ruleset_version_id} — none found. Seed "
            "database/seeds/rules.resource_definitions.yaml before running this fixture; this "
            "script only reuses existing rules content."
        )
    assert isinstance(resource_definition_id, uuid.UUID)
    return resource_definition_id


def _ensure_character_resource(
    connection: Connection,
    summary: _Summary,
    *,
    timeline_id: uuid.UUID,
    character_id: uuid.UUID,
    character_label: str,
    resource_definition_id: uuid.UUID,
    resource_code: str,
    current_amount: int,
    maximum_amount: int,
) -> None:
    """Create-or-reconcile the single fixture-owned `campaign.
    character_resources` row for `character_id`/`resource_definition_id` on
    `timeline_id` — reset to `current_amount`/`maximum_amount` if the row
    exists with different amounts (e.g. a spell slot spent during live
    testing), left untouched if already matching."""
    existing = (
        connection.execute(
            text("""
                SELECT current_amount, maximum_amount FROM campaign.character_resources
                WHERE timeline_id = :timeline AND character_id = :character
                  AND resource_definition_id = :resource
            """),
            {
                "timeline": timeline_id,
                "character": character_id,
                "resource": resource_definition_id,
            },
        )
        .mappings()
        .one_or_none()
    )

    label = f"resource {resource_code!r}: {character_label}"
    params = {
        "timeline": timeline_id,
        "character": character_id,
        "resource": resource_definition_id,
        "current": current_amount,
        "maximum": maximum_amount,
    }

    if existing is None:
        connection.execute(
            text("""
                INSERT INTO campaign.character_resources
                    (timeline_id, character_id, resource_definition_id, current_amount,
                     maximum_amount)
                VALUES (:timeline, :character, :resource, :current, :maximum)
            """),
            params,
        )
        summary.add(created=True, label=label, record_id=character_id)
        return

    matches = (
        existing["current_amount"] == current_amount
        and existing["maximum_amount"] == maximum_amount
    )
    if matches:
        summary.add(created=False, changed=False, label=label, record_id=character_id)
        return

    connection.execute(
        text("""
            UPDATE campaign.character_resources
            SET current_amount = :current, maximum_amount = :maximum, updated_at = now()
            WHERE timeline_id = :timeline AND character_id = :character
              AND resource_definition_id = :resource
        """),
        params,
    )
    summary.add(created=False, changed=True, label=label, record_id=character_id)


def _get_or_create_world_time(
    connection: Connection,
    summary: _Summary,
    *,
    world_id: uuid.UUID,
    label: str,
    sort_key: int,
) -> uuid.UUID:
    """Create-or-reuse one fixture-owned `core.world_times` row, located by
    its distinctive `(world_id, label)` — `core.world_times` has no natural
    key, so the fixture's own fixed label is what makes this idempotent.
    `core.world_times.sort_key` is immutable once set (revision 030,
    `core.enforce_immutable_columns`), so this never reconciles a drifted
    row: event ordering is guaranteed stable by the schema, and a row found
    under the fixture's label with a *different* sort_key means a non-fixture
    row has taken that label — ambiguous, so it aborts. `year` is derived
    from the offset only to satisfy `ck_world_times_year_or_label`; nothing
    reads it."""
    existing = (
        connection.execute(
            text(
                "SELECT world_time_id, sort_key FROM core.world_times "
                "WHERE world_id = :world AND label = :label"
            ),
            {"world": world_id, "label": label},
        )
        .mappings()
        .one_or_none()
    )
    report_label = f"world time {label!r}"

    if existing is None:
        precision_id = lookup_id(
            connection, "core", "world_time_precisions", "world_time_precision_id", "exact"
        )
        world_time_id = connection.execute(
            text("""
                INSERT INTO core.world_times
                    (world_id, world_time_precision_id, year, label, sort_key)
                VALUES (:world, :precision, :year, :label, :sort_key)
                RETURNING world_time_id
            """),
            {
                "world": world_id,
                "precision": precision_id,
                "year": 1000 + (sort_key - _SESSION_SORT_KEY_BASE),
                "label": label,
                "sort_key": sort_key,
            },
        ).scalar()
        assert isinstance(world_time_id, uuid.UUID)
        summary.add(created=True, label=report_label, record_id=world_time_id)
        return world_time_id

    world_time_id = existing["world_time_id"]
    assert isinstance(world_time_id, uuid.UUID)
    if existing["sort_key"] != sort_key:
        raise SystemExit(
            f"world time {label!r} ({world_time_id}) already exists with sort_key "
            f"{existing['sort_key']}, not the fixture's {sort_key}. core.world_times.sort_key is "
            "immutable (revision 030), so a non-fixture row is using the fixture's label — "
            "investigate before re-running."
        )
    summary.add(created=False, changed=False, label=report_label, record_id=world_time_id)
    return world_time_id


def _session_world_time_label(campaign_name: str, session_number: int, slot: str) -> str:
    return f"{_SESSION_WORLD_TIME_LABEL_PREFIX}: {campaign_name} session {session_number} {slot}"


def _ensure_session(
    connection: Connection,
    summary: _Summary,
    *,
    campaign_id: uuid.UUID,
    campaign_name: str,
    world_id: uuid.UUID,
    fixture: _SessionFixture,
) -> uuid.UUID:
    """Create-or-reconcile one fixture-owned `campaign.sessions` row,
    located by `(campaign_id, session_number)` in the fixture's own
    campaign. That campaign is created by this script, and a fresh campaign
    has no sessions, so a row at one of the fixture's own session numbers
    (1-3 for Campaign A, 1 for Campaign B) is fixture-owned by
    construction. title/summary/lifecycle/started_at/ended_at and the
    world-time endpoints are all reconciled: `campaign.sessions` carries no
    immutability trigger, and a live-testing session may legitimately have
    ended a session or revised its recap through the real commands.

    Aborts rather than guessing if a row at this number carries a
    `source_id` — an imported/externally-sourced session is never
    something this fixture creates."""
    start_world_time_id = (
        _get_or_create_world_time(
            connection,
            summary,
            world_id=world_id,
            label=_session_world_time_label(campaign_name, fixture.session_number, "start"),
            sort_key=_SESSION_SORT_KEY_BASE + fixture.start_world_time_offset,
        )
        if fixture.start_world_time_offset is not None
        else None
    )
    end_world_time_id = (
        _get_or_create_world_time(
            connection,
            summary,
            world_id=world_id,
            label=_session_world_time_label(campaign_name, fixture.session_number, "end"),
            sort_key=_SESSION_SORT_KEY_BASE + fixture.end_world_time_offset,
        )
        if fixture.end_world_time_offset is not None
        else None
    )

    lifecycle_status_id = lookup_id(
        connection,
        "core",
        "lifecycle_statuses",
        "lifecycle_status_id",
        fixture.lifecycle_status_code,
    )

    report_label = f"session {campaign_name} #{fixture.session_number} {fixture.portal_heading!r}"
    params = {
        "campaign": campaign_id,
        "number": fixture.session_number,
        "lifecycle": lifecycle_status_id,
        "title": fixture.title,
        "summary": fixture.summary,
        "started": fixture.started_at,
        "ended": fixture.ended_at,
        "start_wt": start_world_time_id,
        "end_wt": end_world_time_id,
    }

    existing = (
        connection.execute(
            text("""
                SELECT session_id, source_id, title, summary, lifecycle_status_id,
                       started_at, ended_at, start_world_time_id, end_world_time_id
                FROM campaign.sessions
                WHERE campaign_id = :campaign AND session_number = :number
            """),
            {"campaign": campaign_id, "number": fixture.session_number},
        )
        .mappings()
        .one_or_none()
    )

    if existing is None:
        session_id = connection.execute(
            text("""
                INSERT INTO campaign.sessions
                    (campaign_id, session_number, lifecycle_status_id, title, summary,
                     started_at, ended_at, start_world_time_id, end_world_time_id)
                VALUES (:campaign, :number, :lifecycle, :title, :summary, :started, :ended,
                        :start_wt, :end_wt)
                RETURNING session_id
            """),
            params,
        ).scalar()
        assert isinstance(session_id, uuid.UUID)
        summary.add(created=True, label=report_label, record_id=session_id)
        return session_id

    session_id = existing["session_id"]
    assert isinstance(session_id, uuid.UUID)
    if existing["source_id"] is not None:
        raise SystemExit(
            f"session #{fixture.session_number} in {campaign_name!r} ({session_id}) has a "
            "source_id — it was imported from elsewhere, not created by this fixture. Refusing "
            "to reconcile it rather than overwrite non-fixture data."
        )

    matches = (
        existing["title"] == fixture.title
        and existing["summary"] == fixture.summary
        and existing["lifecycle_status_id"] == lifecycle_status_id
        and existing["started_at"] == fixture.started_at
        and existing["ended_at"] == fixture.ended_at
        and existing["start_world_time_id"] == start_world_time_id
        and existing["end_world_time_id"] == end_world_time_id
    )
    if matches:
        summary.add(created=False, changed=False, label=report_label, record_id=session_id)
        return session_id

    connection.execute(
        text("""
            UPDATE campaign.sessions
            SET lifecycle_status_id = :lifecycle, title = :title, summary = :summary,
                started_at = :started, ended_at = :ended, start_world_time_id = :start_wt,
                end_world_time_id = :end_wt
            WHERE session_id = :session
        """),
        {**params, "session": session_id},
    )
    summary.add(created=False, changed=True, label=report_label, record_id=session_id)
    return session_id


def _ensure_session_event(
    connection: Connection,
    summary: _Summary,
    *,
    world_id: uuid.UUID,
    timeline_id: uuid.UUID,
    campaign_id: uuid.UUID,
    campaign_name: str,
    session_id: uuid.UUID,
    session_number: int,
    position: int,
    fixture: _SessionEventFixture,
) -> uuid.UUID:
    """Create-or-reuse one fixture-owned `recorded` `narrative.events` row
    (entity + event pair), located by `(world_id, canonical_name)` among
    event-typed entities — an event's name is frozen once recorded, so it
    is a stable key. Created directly at `recorded` rather than through
    `dnd_ai.commands.events.record_event` because that command has no
    parameter for the event's short `summary` (the portal's Session-detail
    Summary column), which this fixture must populate; every other column
    is set exactly as `_insert_event_row` would.

    A `recorded` event is immutable by schema design (docs/ENTITY_LIFECYCLE.md
    §15 — content frozen, only `recorded -> voided/corrected` allowed, no
    deletion), and its chronological position is frozen too
    (`core.world_times.sort_key` is immutable, revision 030). That schema
    guarantee *is* the reconciliation story for these rows: nothing a
    live-testing session can do will change an event's content or its order,
    so a re-run only create-or-reuses each event by its (frozen) name. If a
    fixture event was voided or repointed during testing, or its frozen
    content no longer matches, this aborts with guidance rather than
    attempting an impossible in-place fix."""
    world_time_id = _get_or_create_world_time(
        connection,
        summary,
        world_id=world_id,
        label=_session_world_time_label(
            campaign_name, session_number, f"event {position} ({fixture.name})"
        ),
        sort_key=_SESSION_SORT_KEY_BASE + fixture.world_time_offset,
    )

    event_type_id = lookup_id(
        connection, "narrative", "event_types", "event_type_id", fixture.event_type_code
    )
    event_entity_type_id = lookup_id(connection, "core", "entity_types", "entity_type_id", "event")

    report_label = (
        f"session event {campaign_name} #{session_number} (chronological #{position}) "
        f"{fixture.name!r}"
    )

    existing = (
        connection.execute(
            text("""
                SELECT e.event_id, e.session_id, e.event_type_id, e.world_time_id, e.details,
                       ce.summary, es.code AS status_code
                FROM core.entities ce
                JOIN narrative.events e ON e.event_id = ce.entity_id
                JOIN narrative.event_statuses es ON es.event_status_id = e.event_status_id
                WHERE ce.world_id = :world AND ce.canonical_name = :name
                  AND ce.entity_type_id = :etype
            """),
            {"world": world_id, "name": fixture.name, "etype": event_entity_type_id},
        )
        .mappings()
        .one_or_none()
    )

    if existing is None:
        canon_status_id = lookup_id(
            connection, "core", "canon_statuses", "canon_status_id", "canon"
        )
        active_status_id = lookup_id(
            connection, "core", "lifecycle_statuses", "lifecycle_status_id", "active"
        )
        recorded_status_id = lookup_id(
            connection, "narrative", "event_statuses", "event_status_id", "recorded"
        )
        event_id = connection.execute(
            text("""
                INSERT INTO core.entities
                    (world_id, entity_type_id, canonical_name, summary, canon_status_id,
                     lifecycle_status_id)
                VALUES (:world, :etype, :name, :summary, :canon, :lifecycle)
                RETURNING entity_id
            """),
            {
                "world": world_id,
                "etype": event_entity_type_id,
                "name": fixture.name,
                "summary": fixture.summary,
                "canon": canon_status_id,
                "lifecycle": active_status_id,
            },
        ).scalar()
        assert isinstance(event_id, uuid.UUID)
        connection.execute(
            text("""
                INSERT INTO narrative.events
                    (event_id, timeline_id, campaign_id, session_id, event_type_id,
                     event_status_id, world_time_id, details)
                VALUES (:id, :timeline, :campaign, :session, :etype, :status, :world_time,
                        :details)
            """),
            {
                "id": event_id,
                "timeline": timeline_id,
                "campaign": campaign_id,
                "session": session_id,
                "etype": event_type_id,
                "status": recorded_status_id,
                "world_time": world_time_id,
                "details": fixture.details,
            },
        )
        summary.add(created=True, label=report_label, record_id=event_id)
        return event_id

    event_id = existing["event_id"]
    assert isinstance(event_id, uuid.UUID)

    if existing["status_code"] == "voided":
        raise SystemExit(
            f"fixture event {fixture.name!r} ({event_id}) is voided. A recorded/voided event is "
            "immutable (docs/ENTITY_LIFECYCLE.md §15) and cannot be restored by this fixture — "
            "rename or void-and-replace it, or recreate the dev database, then re-run."
        )
    if existing["session_id"] != session_id:
        raise SystemExit(
            f"fixture event {fixture.name!r} ({event_id}) is linked to session "
            f"{existing['session_id']}, not the fixture's session {session_id}. A recorded "
            "event's session_id is frozen and cannot be reconciled — rename or replace the "
            "row, then re-run."
        )

    drifted = (
        existing["summary"] != fixture.summary
        or existing["details"] != fixture.details
        or existing["event_type_id"] != event_type_id
        or existing["world_time_id"] != world_time_id
    )
    if drifted:
        raise SystemExit(
            f"fixture event {fixture.name!r} ({event_id}) exists as a recorded event whose "
            "frozen content no longer matches the fixture. Recorded events are immutable "
            "(docs/ENTITY_LIFECYCLE.md §15), so this cannot be reset in place — recreate the "
            "dev database, or void-and-rename the row, then re-run."
        )

    summary.add(created=False, changed=False, label=report_label, record_id=event_id)
    return event_id


def _note_session(
    summary: _Summary,
    *,
    fixture: _SessionFixture,
    session_id: uuid.UUID,
    event_ids: list[uuid.UUID],
) -> None:
    if fixture.title is not None:
        title_desc = repr(fixture.portal_heading)
    else:
        title_desc = f"untitled (portal shows {fixture.portal_heading!r})"

    if fixture.started_at is None:
        timing = "no start/end timestamps"
    else:
        assert fixture.ended_at is not None
        timing = f"{fixture.started_at.isoformat()} -> {fixture.ended_at.isoformat()}"

    if event_ids:
        events_desc = "events, chronological order: " + ", ".join(str(e) for e in event_ids)
    else:
        events_desc = "no linked events"

    summary.note(
        f"  #{fixture.session_number} {title_desc}  {session_id}  "
        f"[{fixture.lifecycle_status_code}; {timing}; {events_desc}]"
    )


def _ensure_campaign_sessions(
    connection: Connection,
    summary: _Summary,
    *,
    campaign_id: uuid.UUID,
    campaign_name: str,
    timeline_id: uuid.UUID,
    world_id: uuid.UUID,
    fixtures: tuple[_SessionFixture, ...],
) -> dict[int, uuid.UUID]:
    """Reconcile every session fixture for one campaign and append its
    quick-reference block to `summary.report`. Returns
    `{session_number: session_id}` so the caller can name a specific
    session (Campaign B's, for the cross-campaign test hint)."""
    summary.note(f"{campaign_name}:")
    session_ids: dict[int, uuid.UUID] = {}
    for fixture in fixtures:
        session_id = _ensure_session(
            connection,
            summary,
            campaign_id=campaign_id,
            campaign_name=campaign_name,
            world_id=world_id,
            fixture=fixture,
        )
        session_ids[fixture.session_number] = session_id
        event_ids = [
            _ensure_session_event(
                connection,
                summary,
                world_id=world_id,
                timeline_id=timeline_id,
                campaign_id=campaign_id,
                campaign_name=campaign_name,
                session_id=session_id,
                session_number=fixture.session_number,
                position=position,
                fixture=event_fixture,
            )
            for position, event_fixture in enumerate(fixture.events, start=1)
        ]
        _note_session(summary, fixture=fixture, session_id=session_id, event_ids=event_ids)
    return session_ids


# --------------------------------------------------------------------------
# Phase 13D Quest list/detail fixtures
# --------------------------------------------------------------------------


def _objective_visible_to_non_gm(objective: _ObjectiveFixture) -> bool:
    """Whether the production quest-detail query returns this objective to a
    non-GM audience (`include_hidden=False`) — mirrors
    `dnd_ai.queries.quest.get_quest_view`'s own WHERE clause exactly:
    `visible` always; `hidden_until_active`/`hidden_until_discovered` only
    once a `campaign.objective_state` row exists; `gm_only` never. Used only
    to describe the fixture in the quick-reference/verification output — the
    real filtering is always done by the real query, never re-derived for
    an actual access decision."""
    if objective.visibility_policy == "visible":
        return True
    if objective.visibility_policy in ("hidden_until_active", "hidden_until_discovered"):
        return objective.objective_status_code is not None
    return False


def _get_or_create_party(
    connection: Connection, summary: _Summary, *, world_id: uuid.UUID, name: str
) -> uuid.UUID:
    """Create-or-reuse one fixture-owned `campaign.parties` row, located by
    its distinctive `(world_id, name)`. No party-membership rows are
    created: the supplied account is a campaign owner / GM and never
    resolves a party perspective for quests (`get_quest_endpoint` forces
    `authorized_party_id=None` for a `canon.edit` holder), so this party
    exists only to carry the one party-scoped `campaign.quest_state` row
    that gives `_QUEST_A_NULL_STATUS_NAME` a null resolved status in the
    portal's list (see the module comment)."""
    existing = (
        connection.execute(
            text("SELECT party_id FROM campaign.parties WHERE world_id = :world AND name = :name"),
            {"world": world_id, "name": name},
        )
        .scalars()
        .all()
    )
    if len(existing) > 1:
        raise SystemExit(
            f"more than one campaign.parties row named {name!r} in world {world_id} — "
            "ambiguous, refusing to guess which is the fixture's. Investigate before re-running."
        )
    if existing:
        party_id = existing[0]
        assert isinstance(party_id, uuid.UUID)
        summary.add(created=False, label=f"party {name!r}", record_id=party_id)
        return party_id
    party_id = connection.execute(
        text(
            "INSERT INTO campaign.parties (world_id, name) VALUES (:world, :name) RETURNING party_id"
        ),
        {"world": world_id, "name": name},
    ).scalar()
    assert isinstance(party_id, uuid.UUID)
    summary.add(created=True, label=f"party {name!r}", record_id=party_id)
    return party_id


def _ensure_campaign_party(
    connection: Connection,
    summary: _Summary,
    *,
    campaign_id: uuid.UUID,
    party_id: uuid.UUID,
    party_name: str,
) -> None:
    existing = connection.execute(
        text("SELECT 1 FROM campaign.campaign_parties WHERE campaign_id = :c AND party_id = :p"),
        {"c": campaign_id, "p": party_id},
    ).scalar()
    label = f"campaign/party association ({party_name!r})"
    if existing is not None:
        summary.add(created=False, label=label, record_id=f"{campaign_id}/{party_id}")
        return
    connection.execute(
        text("INSERT INTO campaign.campaign_parties (campaign_id, party_id) VALUES (:c, :p)"),
        {"c": campaign_id, "p": party_id},
    )
    summary.add(created=True, label=label, record_id=f"{campaign_id}/{party_id}")


def _get_or_create_quest(
    connection: Connection, summary: _Summary, *, world_id: uuid.UUID, name: str
) -> uuid.UUID:
    """Create-or-reuse one fixture-owned `narrative.quests` entity, located
    by `(world_id, canonical_name)` among `quest`-typed entities. A name
    found on more than one entity, on a non-`quest` entity, or on a `quest`
    entity with no `narrative.quests` subtype row is treated as a collision
    with non-fixture/incompatible data and aborts with guidance rather than
    guessing ownership (the task's own rule). Direct insert — there is no
    production authoring command for a quest entity yet (same boundary
    `tests/factories.py`'s `make_quest` documents), and the row shape
    mirrors it exactly."""
    rows = (
        connection.execute(
            text("""
                SELECT e.entity_id, et.code AS entity_type_code,
                       (q.quest_id IS NOT NULL) AS has_quest_row
                FROM core.entities e
                JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id
                LEFT JOIN narrative.quests q ON q.quest_id = e.entity_id
                WHERE e.world_id = :world AND e.canonical_name = :name
            """),
            {"world": world_id, "name": name},
        )
        .mappings()
        .all()
    )
    if len(rows) > 1:
        raise SystemExit(
            f"more than one core.entities row named {name!r} in world {world_id} — a name "
            "collision with non-fixture data. Refusing to guess which is the fixture's quest; "
            "rename or remove the conflicting row, then re-run."
        )
    if rows:
        row = rows[0]
        entity_id = row["entity_id"]
        assert isinstance(entity_id, uuid.UUID)
        if row["entity_type_code"] != "quest" or not row["has_quest_row"]:
            detail = (
                f"is a {row['entity_type_code']!r} entity"
                if row["entity_type_code"] != "quest"
                else "is a 'quest' entity with no narrative.quests subtype row"
            )
            raise SystemExit(
                f"an entity named {name!r} already exists in world {world_id} but {detail} — "
                "incompatible with this fixture's quest. Rename or remove it, then re-run."
            )
        summary.add(created=False, label=f"quest {name!r}", record_id=entity_id)
        return entity_id

    quest_type_id = lookup_id(connection, "core", "entity_types", "entity_type_id", "quest")
    canon_status_id = lookup_id(connection, "core", "canon_statuses", "canon_status_id", "canon")
    active_status_id = lookup_id(
        connection, "core", "lifecycle_statuses", "lifecycle_status_id", "active"
    )
    entity_id = connection.execute(
        text("""
            INSERT INTO core.entities
                (world_id, entity_type_id, canonical_name, canon_status_id, lifecycle_status_id)
            VALUES (:world, :etype, :name, :canon, :lifecycle)
            RETURNING entity_id
        """),
        {
            "world": world_id,
            "etype": quest_type_id,
            "name": name,
            "canon": canon_status_id,
            "lifecycle": active_status_id,
        },
    ).scalar()
    assert isinstance(entity_id, uuid.UUID)
    connection.execute(
        text("INSERT INTO narrative.quests (quest_id) VALUES (:id)"), {"id": entity_id}
    )
    summary.add(created=True, label=f"quest {name!r}", record_id=entity_id)
    return entity_id


def _ensure_quest_stage(
    connection: Connection,
    summary: _Summary,
    *,
    quest_id: uuid.UUID,
    quest_name: str,
    fixture: _StageFixture,
) -> uuid.UUID:
    """Create-or-reconcile one fixture-owned `narrative.quest_stages` row,
    located by `(quest_id, name)` on the fixture's own quest. `sequence_
    number`, `stage_type`, and `description` are reconciled — the table has
    no immutability trigger and the portal renders all three."""
    report_label = f"quest stage {quest_name!r} / {fixture.name!r} (seq {fixture.sequence_number})"
    existing = (
        connection.execute(
            text("""
                SELECT quest_stage_id, sequence_number, stage_type, description
                FROM narrative.quest_stages
                WHERE quest_id = :quest AND name = :name
            """),
            {"quest": quest_id, "name": fixture.name},
        )
        .mappings()
        .all()
    )
    if len(existing) > 1:
        raise SystemExit(
            f"more than one narrative.quest_stages row named {fixture.name!r} on quest "
            f"{quest_name!r} — ambiguous, refusing to guess which is the fixture's."
        )
    params = {
        "quest": quest_id,
        "name": fixture.name,
        "seq": fixture.sequence_number,
        "type": fixture.stage_type,
        "description": fixture.description,
    }
    if not existing:
        stage_id = connection.execute(
            text("""
                INSERT INTO narrative.quest_stages
                    (quest_id, name, sequence_number, stage_type, description)
                VALUES (:quest, :name, :seq, :type, :description)
                RETURNING quest_stage_id
            """),
            params,
        ).scalar()
        assert isinstance(stage_id, uuid.UUID)
        summary.add(created=True, label=report_label, record_id=stage_id)
        return stage_id

    row = existing[0]
    stage_id = row["quest_stage_id"]
    assert isinstance(stage_id, uuid.UUID)
    matches = (
        row["sequence_number"] == fixture.sequence_number
        and row["stage_type"] == fixture.stage_type
        and row["description"] == fixture.description
    )
    if matches:
        summary.add(created=False, changed=False, label=report_label, record_id=stage_id)
        return stage_id
    connection.execute(
        text("""
            UPDATE narrative.quest_stages
            SET sequence_number = :seq, stage_type = :type, description = :description
            WHERE quest_stage_id = :id
        """),
        {**params, "id": stage_id},
    )
    summary.add(created=False, changed=True, label=report_label, record_id=stage_id)
    return stage_id


def _ensure_quest_objective(
    connection: Connection,
    summary: _Summary,
    *,
    quest_stage_id: uuid.UUID,
    quest_name: str,
    stage_name: str,
    fixture: _ObjectiveFixture,
) -> uuid.UUID:
    """Create-or-reconcile one fixture-owned `narrative.quest_objectives`
    row, located by `(quest_stage_id, name)`. Every portal-visible column —
    `objective_type_id`, `requirement_level`, `completion_mode`,
    `visibility_policy`, `description`, `quantity_required` — is reconciled;
    the table has no immutability trigger. `completion_rule` is left NULL
    (the fixture needs no structured completion metadata), matching
    `tests/factories.py`'s `make_quest_objective` default."""
    report_label = f"quest objective {quest_name!r} / {stage_name!r} / {fixture.name!r}"
    objective_type_id = lookup_id(
        connection, "narrative", "objective_types", "objective_type_id", fixture.objective_type_code
    )
    existing = (
        connection.execute(
            text("""
                SELECT quest_objective_id, objective_type_id, requirement_level, completion_mode,
                       visibility_policy, description, quantity_required
                FROM narrative.quest_objectives
                WHERE quest_stage_id = :stage AND name = :name
            """),
            {"stage": quest_stage_id, "name": fixture.name},
        )
        .mappings()
        .all()
    )
    if len(existing) > 1:
        raise SystemExit(
            f"more than one narrative.quest_objectives row named {fixture.name!r} on stage "
            f"{stage_name!r} of quest {quest_name!r} — ambiguous, refusing to guess."
        )
    params = {
        "stage": quest_stage_id,
        "name": fixture.name,
        "otype": objective_type_id,
        "requirement": fixture.requirement_level,
        "completion": fixture.completion_mode,
        "visibility": fixture.visibility_policy,
        "description": fixture.description,
        "quantity": fixture.quantity_required,
    }
    if not existing:
        objective_id = connection.execute(
            text("""
                INSERT INTO narrative.quest_objectives
                    (quest_stage_id, objective_type_id, name, requirement_level, completion_mode,
                     visibility_policy, description, quantity_required)
                VALUES (:stage, :otype, :name, :requirement, :completion, :visibility,
                        :description, :quantity)
                RETURNING quest_objective_id
            """),
            params,
        ).scalar()
        assert isinstance(objective_id, uuid.UUID)
        summary.add(created=True, label=report_label, record_id=objective_id)
        return objective_id

    row = existing[0]
    objective_id = row["quest_objective_id"]
    assert isinstance(objective_id, uuid.UUID)
    matches = (
        row["objective_type_id"] == objective_type_id
        and row["requirement_level"] == fixture.requirement_level
        and row["completion_mode"] == fixture.completion_mode
        and row["visibility_policy"] == fixture.visibility_policy
        and row["description"] == fixture.description
        and row["quantity_required"] == fixture.quantity_required
    )
    if matches:
        summary.add(created=False, changed=False, label=report_label, record_id=objective_id)
        return objective_id
    connection.execute(
        text("""
            UPDATE narrative.quest_objectives
            SET objective_type_id = :otype, requirement_level = :requirement,
                completion_mode = :completion, visibility_policy = :visibility,
                description = :description, quantity_required = :quantity
            WHERE quest_objective_id = :id
        """),
        {**params, "id": objective_id},
    )
    summary.add(created=False, changed=True, label=report_label, record_id=objective_id)
    return objective_id


def _ensure_quest_state(
    connection: Connection,
    summary: _Summary,
    *,
    timeline_id: uuid.UUID,
    quest_id: uuid.UUID,
    quest_name: str,
    party_id: uuid.UUID | None,
    party_label: str | None,
    status_code: str,
) -> None:
    """Create-or-reconcile one fixture-owned `campaign.quest_state` row for
    `(timeline_id, quest_id, party_id)` — located by exactly that triple
    (the table's own partial unique indexes). Only `quest_status_id` is
    reconciled; `last_event_id` is left untouched (a live-testing advance
    may have set it to a real recorded event, and only the status matters
    to the portal). `last_event_id` is NULL on a fresh insert — the
    "administrative/import-driven change with no causing event" case
    `campaign.enforce_state_event_timeline()` explicitly allows."""
    scope = "campaign-wide" if party_id is None else f"party {party_label!r}"
    report_label = f"quest state {quest_name!r} ({scope}) -> {status_code!r}"
    status_id = lookup_id(connection, "campaign", "quest_statuses", "quest_status_id", status_code)
    existing = (
        connection.execute(
            text("""
                SELECT quest_state_id, quest_status_id
                FROM campaign.quest_state
                WHERE timeline_id = :timeline AND quest_id = :quest
                  AND party_id IS NOT DISTINCT FROM :party
            """),
            {"timeline": timeline_id, "quest": quest_id, "party": party_id},
        )
        .mappings()
        .one_or_none()
    )
    if existing is None:
        state_id = connection.execute(
            text("""
                INSERT INTO campaign.quest_state
                    (timeline_id, quest_id, party_id, quest_status_id)
                VALUES (:timeline, :quest, :party, :status)
                RETURNING quest_state_id
            """),
            {"timeline": timeline_id, "quest": quest_id, "party": party_id, "status": status_id},
        ).scalar()
        assert isinstance(state_id, uuid.UUID)
        summary.add(created=True, label=report_label, record_id=state_id)
        return
    state_id = existing["quest_state_id"]
    assert isinstance(state_id, uuid.UUID)
    if existing["quest_status_id"] == status_id:
        summary.add(created=False, changed=False, label=report_label, record_id=state_id)
        return
    connection.execute(
        text(
            "UPDATE campaign.quest_state SET quest_status_id = :status, updated_at = now() "
            "WHERE quest_state_id = :id"
        ),
        {"status": status_id, "id": state_id},
    )
    summary.add(created=False, changed=True, label=report_label, record_id=state_id)


def _ensure_objective_state(
    connection: Connection,
    summary: _Summary,
    *,
    timeline_id: uuid.UUID,
    quest_objective_id: uuid.UUID,
    objective_label: str,
    party_id: uuid.UUID | None,
    status_code: str,
) -> None:
    """Create-or-reconcile one fixture-owned `campaign.objective_state` row
    for `(timeline_id, quest_objective_id, party_id)` — same contract as
    `_ensure_quest_state`, reconciling only `objective_status_id`."""
    report_label = f"objective state {objective_label} -> {status_code!r}"
    status_id = lookup_id(
        connection, "campaign", "objective_statuses", "objective_status_id", status_code
    )
    existing = (
        connection.execute(
            text("""
                SELECT objective_state_id, objective_status_id
                FROM campaign.objective_state
                WHERE timeline_id = :timeline AND quest_objective_id = :objective
                  AND party_id IS NOT DISTINCT FROM :party
            """),
            {"timeline": timeline_id, "objective": quest_objective_id, "party": party_id},
        )
        .mappings()
        .one_or_none()
    )
    if existing is None:
        state_id = connection.execute(
            text("""
                INSERT INTO campaign.objective_state
                    (timeline_id, quest_objective_id, party_id, objective_status_id)
                VALUES (:timeline, :objective, :party, :status)
                RETURNING objective_state_id
            """),
            {
                "timeline": timeline_id,
                "objective": quest_objective_id,
                "party": party_id,
                "status": status_id,
            },
        ).scalar()
        assert isinstance(state_id, uuid.UUID)
        summary.add(created=True, label=report_label, record_id=state_id)
        return
    state_id = existing["objective_state_id"]
    assert isinstance(state_id, uuid.UUID)
    if existing["objective_status_id"] == status_id:
        summary.add(created=False, changed=False, label=report_label, record_id=state_id)
        return
    connection.execute(
        text(
            "UPDATE campaign.objective_state SET objective_status_id = :status, updated_at = now() "
            "WHERE objective_state_id = :id"
        ),
        {"status": status_id, "id": state_id},
    )
    summary.add(created=False, changed=True, label=report_label, record_id=state_id)


def _note_quest(summary: _Summary, *, quest: _QuestFixture, quest_id: uuid.UUID) -> None:
    if quest.campaign_wide_status_code is not None:
        status_desc = f"status {quest.campaign_wide_status_code!r} (campaign-wide)"
    elif quest.party_scoped_status_code is not None:
        status_desc = (
            f"status null for the owner (tracked only by party "
            f"{_QUEST_A_PARTY_NAME!r} as {quest.party_scoped_status_code!r})"
        )
    else:
        status_desc = "not tracked on this timeline"

    if quest.stages:
        ordered = sorted(quest.stages, key=lambda s: (s.sequence_number, s.name))
        stage_desc = "stages in sequence order: " + ", ".join(
            f"{s.name!r} (seq {s.sequence_number})" for s in ordered
        )
    else:
        stage_desc = "no stages"

    summary.note_quest(f"  {quest.name!r}  {quest_id}  [{status_desc}; {stage_desc}]")

    for stage in sorted(quest.stages, key=lambda s: (s.sequence_number, s.name)):
        if not stage.objectives:
            summary.note_quest(f"      stage {stage.name!r}: no objectives")
            continue
        for objective in stage.objectives:
            audience = (
                "any campaign.view holder"
                if _objective_visible_to_non_gm(objective)
                else "canon.edit (GM) audience only"
            )
            qty = (
                f", quantity {objective.quantity_required}"
                if objective.quantity_required is not None
                else ""
            )
            status = objective.objective_status_code or "no tracked status"
            summary.note_quest(
                f"      objective {objective.name!r}: {objective.requirement_level}/"
                f"{objective.completion_mode}, visibility {objective.visibility_policy} "
                f"({audience}), status {status}{qty}"
            )


def _ensure_campaign_quests(
    connection: Connection,
    summary: _Summary,
    *,
    campaign_name: str,
    timeline_id: uuid.UUID,
    world_id: uuid.UUID,
    quests: tuple[_QuestFixture, ...],
    party_id: uuid.UUID | None = None,
) -> dict[str, uuid.UUID]:
    """Reconcile every quest fixture for one campaign and append its
    quick-reference block to `summary.quest_report`. Returns
    `{quest_name: quest_id}` for the caller's own reference block."""
    summary.note_quest(f"{campaign_name}:")
    quest_ids: dict[str, uuid.UUID] = {}
    for quest in quests:
        quest_id = _get_or_create_quest(connection, summary, world_id=world_id, name=quest.name)
        quest_ids[quest.name] = quest_id
        for stage in quest.stages:
            stage_id = _ensure_quest_stage(
                connection, summary, quest_id=quest_id, quest_name=quest.name, fixture=stage
            )
            for objective in stage.objectives:
                objective_id = _ensure_quest_objective(
                    connection,
                    summary,
                    quest_stage_id=stage_id,
                    quest_name=quest.name,
                    stage_name=stage.name,
                    fixture=objective,
                )
                if objective.objective_status_code is not None:
                    _ensure_objective_state(
                        connection,
                        summary,
                        timeline_id=timeline_id,
                        quest_objective_id=objective_id,
                        objective_label=f"{quest.name} / {objective.name}",
                        party_id=None,
                        status_code=objective.objective_status_code,
                    )
        if quest.campaign_wide_status_code is not None:
            _ensure_quest_state(
                connection,
                summary,
                timeline_id=timeline_id,
                quest_id=quest_id,
                quest_name=quest.name,
                party_id=None,
                party_label=None,
                status_code=quest.campaign_wide_status_code,
            )
        if quest.party_scoped_status_code is not None:
            assert party_id is not None, (
                "a party-scoped quest fixture requires a party — this is a bug in the fixture wiring"
            )
            _ensure_quest_state(
                connection,
                summary,
                timeline_id=timeline_id,
                quest_id=quest_id,
                quest_name=quest.name,
                party_id=party_id,
                party_label=_QUEST_A_PARTY_NAME,
                status_code=quest.party_scoped_status_code,
            )
        _note_quest(summary, quest=quest, quest_id=quest_id)
    return quest_ids


def _ensure_character_relationship(
    connection: Connection,
    summary: _Summary,
    *,
    campaign_id: uuid.UUID,
    campaign_membership_id: uuid.UUID,
    character_id: uuid.UUID,
    character_label: str,
    world_id: uuid.UUID,
    actor_user_id: uuid.UUID,
) -> None:
    relationship_type_id = lookup_id(
        connection,
        "security",
        "character_relationship_types",
        "character_relationship_type_id",
        _RELATIONSHIP_TYPE_CODE,
    )
    existing = connection.execute(
        text("""
            SELECT 1 FROM security.membership_character_relationships
            WHERE campaign_membership_id = :membership
              AND character_id = :character
              AND character_relationship_type_id = :type
              AND revoked_at IS NULL
        """),
        {
            "membership": campaign_membership_id,
            "character": character_id,
            "type": relationship_type_id,
        },
    ).scalar()
    if existing is not None:
        summary.add(
            created=False,
            label=f"'{_RELATIONSHIP_TYPE_CODE}' relationship: {character_label}",
            record_id=character_id,
        )
        return

    result = grant_character_relationship(
        connection,
        campaign_membership_id=campaign_membership_id,
        character_id=character_id,
        relationship_type_code=_RELATIONSHIP_TYPE_CODE,
        campaign_id=campaign_id,
        expected_world_id=world_id,
        granted_by_membership_id=campaign_membership_id,
    )
    record_change_log(
        connection,
        change_action_code=_CREATED_CHANGE_ACTION,
        schema_name="security",
        table_name="membership_character_relationships",
        record_id=result.membership_character_relationship_id,
        entity_id=None,
        world_id=world_id,
        actor_user_id=actor_user_id,
        correlation_id=None,
        command_name=_COMMAND_NAME,
        event_id=None,
    )
    summary.add(
        created=True,
        label=f"'{_RELATIONSHIP_TYPE_CODE}' relationship: {character_label}",
        record_id=result.membership_character_relationship_id,
    )


# --------------------------------------------------------------------------
# Phase 13D World Explorer + Knowledge fixtures
# --------------------------------------------------------------------------


def _wk_world_time(
    connection: Connection, summary: _Summary, *, world_id: uuid.UUID, suffix: str, offset: int
) -> uuid.UUID:
    return _get_or_create_world_time(
        connection,
        summary,
        world_id=world_id,
        label=f"{_WK_WORLD_TIME_LABEL_PREFIX}: {suffix}",
        sort_key=_WK_SORT_KEY_BASE + offset,
    )


def _entity_by_name(
    connection: Connection, *, world_id: uuid.UUID, name: str
) -> tuple[uuid.UUID, str] | None:
    """(entity_id, entity_type_code) for a `(world_id, canonical_name)` — or
    None. Raises if the name is used more than once in the world (a
    collision with non-fixture data — refuse to guess)."""
    rows = connection.execute(
        text("""
            SELECT e.entity_id, et.code AS type_code
            FROM core.entities e
            JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id
            WHERE e.world_id = :world AND e.canonical_name = :name
        """),
        {"world": world_id, "name": name},
    ).all()
    if len(rows) > 1:
        raise SystemExit(
            f"more than one core.entities row named {name!r} in world {world_id} — a name "
            "collision with non-fixture data. Rename or remove the conflicting row, then re-run."
        )
    if not rows:
        return None
    entity_id, type_code = rows[0]
    assert isinstance(entity_id, uuid.UUID)
    return entity_id, str(type_code)


def _new_world_entity(
    connection: Connection,
    *,
    world_id: uuid.UUID,
    name: str,
    summary_text: str,
    entity_type_code: str,
) -> uuid.UUID:
    """A `core.entities` row for a world-canon entity — mirrors
    `tests.factories.make_entity` plus the `summary` this fixture needs
    (canon + active; no `created_by_user_id`, matching `_get_or_create_quest`)."""
    entity_type_id = lookup_id(
        connection, "core", "entity_types", "entity_type_id", entity_type_code
    )
    canon_status_id = lookup_id(connection, "core", "canon_statuses", "canon_status_id", "canon")
    active_status_id = lookup_id(
        connection, "core", "lifecycle_statuses", "lifecycle_status_id", "active"
    )
    entity_id = connection.execute(
        text("""
            INSERT INTO core.entities
                (world_id, entity_type_id, canonical_name, summary, canon_status_id,
                 lifecycle_status_id)
            VALUES (:world, :etype, :name, :summary, :canon, :lifecycle)
            RETURNING entity_id
        """),
        {
            "world": world_id,
            "etype": entity_type_id,
            "name": name,
            "summary": summary_text,
            "canon": canon_status_id,
            "lifecycle": active_status_id,
        },
    ).scalar()
    assert isinstance(entity_id, uuid.UUID)
    return entity_id


def _ensure_location_tree(
    connection: Connection,
    summary: _Summary,
    *,
    world_id: uuid.UUID,
    fixture: _LocationFixture,
    parent_location_id: uuid.UUID | None,
) -> dict[str, uuid.UUID]:
    """Create-or-reuse one `world.locations` row (plus its settlement /
    building / dungeon / dungeon_area subtype row) and recurse into
    `fixture.children`, threading `parent_location_id`. Returns
    `{location name: location_id}` for the whole subtree."""
    ids: dict[str, uuid.UUID] = {}
    existing = _entity_by_name(connection, world_id=world_id, name=fixture.name)
    if existing is not None:
        location_id, type_code = existing
        if type_code != fixture.entity_type_code:
            raise SystemExit(
                f"location {fixture.name!r} already exists as a {type_code!r} entity, not the "
                f"fixture's {fixture.entity_type_code!r} — rename or remove it, then re-run."
            )
        summary.add(
            created=False, label=f"location {fixture.name!r} ({type_code})", record_id=location_id
        )
    else:
        location_id = _new_world_entity(
            connection,
            world_id=world_id,
            name=fixture.name,
            summary_text=fixture.summary,
            entity_type_code=fixture.entity_type_code,
        )
        connection.execute(
            text("INSERT INTO world.locations (location_id, parent_location_id) VALUES (:l, :p)"),
            {"l": location_id, "p": parent_location_id},
        )
        if fixture.entity_type_code == "settlement":
            connection.execute(
                text("INSERT INTO world.settlements (settlement_id, population) VALUES (:l, :pop)"),
                {"l": location_id, "pop": fixture.population},
            )
        elif fixture.entity_type_code == "building":
            connection.execute(
                text("INSERT INTO world.buildings (building_id, building_use) VALUES (:l, :u)"),
                {"l": location_id, "u": fixture.building_use},
            )
        elif fixture.entity_type_code == "dungeon":
            connection.execute(
                text("INSERT INTO world.dungeons (dungeon_id, danger_level) VALUES (:l, :d)"),
                {"l": location_id, "d": fixture.danger_level},
            )
        elif fixture.entity_type_code == "dungeon_area":
            connection.execute(
                text("INSERT INTO world.dungeon_areas (dungeon_area_id) VALUES (:l)"),
                {"l": location_id},
            )
        summary.add(
            created=True,
            label=f"location {fixture.name!r} ({fixture.entity_type_code})",
            record_id=location_id,
        )
    ids[fixture.name] = location_id
    for child in fixture.children:
        ids.update(
            _ensure_location_tree(
                connection,
                summary,
                world_id=world_id,
                fixture=child,
                parent_location_id=location_id,
            )
        )
    return ids


def _ensure_location_state(
    connection: Connection,
    summary: _Summary,
    *,
    timeline_id: uuid.UUID,
    location_id: uuid.UUID,
    location_name: str,
    state: dict[str, object],
) -> None:
    label = f"location state: {location_name!r}"
    existing = connection.execute(
        text("SELECT 1 FROM campaign.location_state WHERE timeline_id = :t AND location_id = :l"),
        {"t": timeline_id, "l": location_id},
    ).scalar()
    if existing is not None:
        summary.add(created=False, label=label, record_id=location_id)
        return
    connection.execute(
        text("""
            INSERT INTO campaign.location_state
                (timeline_id, location_id, is_searched, is_destroyed, alarm_level, condition_notes)
            VALUES (:t, :l, :searched, :destroyed, :alarm, :notes)
        """),
        {
            "t": timeline_id,
            "l": location_id,
            "searched": state["is_searched"],
            "destroyed": state["is_destroyed"],
            "alarm": state["alarm_level"],
            "notes": state["condition_notes"],
        },
    )
    summary.add(created=True, label=label, record_id=location_id)


def _ensure_npc(
    connection: Connection,
    summary: _Summary,
    *,
    world_id: uuid.UUID,
    ruleset_version_id: uuid.UUID,
) -> uuid.UUID:
    existing = _entity_by_name(connection, world_id=world_id, name=_NPC_NAME)
    if existing is not None:
        summary.add(created=False, label=f"NPC {_NPC_NAME!r}", record_id=existing[0])
        return existing[0]
    species_id = connection.execute(
        text("SELECT species_id FROM rules.species WHERE ruleset_version_id = :v AND code = :c"),
        {"v": ruleset_version_id, "c": _NPC_SPECIES_CODE},
    ).scalar()
    if species_id is None:
        raise SystemExit(
            f"expected an existing rules.species row (code={_NPC_SPECIES_CODE!r}) for ruleset "
            f"version {ruleset_version_id} — none found."
        )
    npc_id = _new_world_entity(
        connection,
        world_id=world_id,
        name=_NPC_NAME,
        summary_text=_NPC_SUMMARY,
        entity_type_code="npc",
    )
    connection.execute(
        text(
            "INSERT INTO character.characters (character_id, species_id, size_category) "
            "VALUES (:c, :s, :size)"
        ),
        {"c": npc_id, "s": species_id, "size": _CHARACTER_SIZE_CATEGORY},
    )
    connection.execute(text("INSERT INTO character.npcs (npc_id) VALUES (:c)"), {"c": npc_id})
    summary.add(created=True, label=f"NPC {_NPC_NAME!r}", record_id=npc_id)
    return npc_id


def _ensure_organization(
    connection: Connection,
    summary: _Summary,
    *,
    world_id: uuid.UUID,
    name: str,
    summary_text: str,
    organization_type_code: str,
    entity_type_code: str,
    public_description: str | None,
    internal_description: str | None,
    headquarters_location_id: uuid.UUID | None = None,
) -> uuid.UUID:
    existing = _entity_by_name(connection, world_id=world_id, name=name)
    if existing is not None:
        summary.add(created=False, label=f"organization {name!r}", record_id=existing[0])
        return existing[0]
    organization_id = _new_world_entity(
        connection,
        world_id=world_id,
        name=name,
        summary_text=summary_text,
        entity_type_code=entity_type_code,
    )
    connection.execute(
        text("""
            INSERT INTO world.organizations
                (organization_id, organization_type_id, headquarters_location_id,
                 public_description, internal_description)
            VALUES (
                :id,
                (SELECT organization_type_id FROM world.organization_types WHERE code = :otc),
                :hq, :public_desc, :internal_desc
            )
        """),
        {
            "id": organization_id,
            "otc": organization_type_code,
            "hq": headquarters_location_id,
            "public_desc": public_description,
            "internal_desc": internal_description,
        },
    )
    summary.add(created=True, label=f"organization {name!r}", record_id=organization_id)
    return organization_id


def _ensure_government(
    connection: Connection,
    summary: _Summary,
    *,
    world_id: uuid.UUID,
    hq_location_id: uuid.UUID | None,
) -> uuid.UUID:
    org_id = _ensure_organization(
        connection,
        summary,
        world_id=world_id,
        name=_GOVERNMENT_NAME,
        summary_text=_GOVERNMENT_PUBLIC_DESCRIPTION,
        organization_type_code="government",
        entity_type_code="government",
        public_description=_GOVERNMENT_PUBLIC_DESCRIPTION,
        internal_description=None,
        headquarters_location_id=hq_location_id,
    )
    already = connection.execute(
        text("SELECT 1 FROM world.governments WHERE government_id = :id"), {"id": org_id}
    ).scalar()
    if already is None:
        connection.execute(
            text(
                "INSERT INTO world.governments (government_id, government_form) VALUES (:id, :form)"
            ),
            {"id": org_id, "form": _GOVERNMENT_FORM},
        )
        summary.add(created=True, label="government subtype row", record_id=org_id)
    else:
        summary.add(created=False, label="government subtype row", record_id=org_id)
    return org_id


def _ensure_religion(
    connection: Connection, summary: _Summary, *, world_id: uuid.UUID
) -> uuid.UUID:
    existing = _entity_by_name(connection, world_id=world_id, name=_RELIGION_NAME)
    if existing is not None:
        summary.add(created=False, label=f"religion {_RELIGION_NAME!r}", record_id=existing[0])
        return existing[0]
    religion_id = _new_world_entity(
        connection,
        world_id=world_id,
        name=_RELIGION_NAME,
        summary_text=_RELIGION_SUMMARY,
        entity_type_code="religion",
    )
    connection.execute(
        text(
            "INSERT INTO world.religions (religion_id, pantheon_structure) VALUES (:id, :structure)"
        ),
        {"id": religion_id, "structure": _RELIGION_PANTHEON},
    )
    summary.add(created=True, label=f"religion {_RELIGION_NAME!r}", record_id=religion_id)
    return religion_id


def _ensure_religious_organization(
    connection: Connection,
    summary: _Summary,
    *,
    world_id: uuid.UUID,
    religion_id: uuid.UUID,
) -> uuid.UUID:
    org_id = _ensure_organization(
        connection,
        summary,
        world_id=world_id,
        name=_RELIGIOUS_ORG_NAME,
        summary_text=_RELIGIOUS_ORG_PUBLIC_DESCRIPTION,
        organization_type_code="religious_organization",
        entity_type_code="religious_organization",
        public_description=_RELIGIOUS_ORG_PUBLIC_DESCRIPTION,
        internal_description=None,
    )
    already = connection.execute(
        text("SELECT 1 FROM world.religious_organizations WHERE religious_organization_id = :id"),
        {"id": org_id},
    ).scalar()
    if already is None:
        connection.execute(
            text(
                "INSERT INTO world.religious_organizations (religious_organization_id, religion_id) "
                "VALUES (:id, :religion)"
            ),
            {"id": org_id, "religion": religion_id},
        )
        summary.add(created=True, label="religious-organization subtype row", record_id=org_id)
    else:
        summary.add(created=False, label="religious-organization subtype row", record_id=org_id)
    return org_id


def _get_or_create_item_definition(
    connection: Connection, summary: _Summary, *, ruleset_version_id: uuid.UUID
) -> uuid.UUID:
    """One shared `rules.item_definitions` row for the fixture's item
    instances, located by its own fixed code."""
    code = "phase13d_dev_wondrous_item"
    existing = connection.execute(
        text("SELECT item_definition_id FROM rules.item_definitions WHERE code = :c"),
        {"c": code},
    ).scalar()
    if existing is not None:
        assert isinstance(existing, uuid.UUID)
        summary.add(created=False, label="item definition (shared)", record_id=existing)
        return existing
    category_id = connection.execute(
        text("SELECT item_category_id FROM rules.item_categories WHERE code = 'wondrous_item'")
    ).scalar()
    if category_id is None:
        raise SystemExit("expected a seeded rules.item_categories row (code='wondrous_item').")
    item_definition_id = connection.execute(
        text("""
            INSERT INTO rules.item_definitions
                (ruleset_version_id, item_category_id, code, display_name, rarity,
                 requires_attunement)
            VALUES (:v, :cat, :code, 'Phase 13D Dev Wondrous Item', 'rare', false)
            RETURNING item_definition_id
        """),
        {"v": ruleset_version_id, "cat": category_id, "code": code},
    ).scalar()
    assert isinstance(item_definition_id, uuid.UUID)
    summary.add(created=True, label="item definition (shared)", record_id=item_definition_id)
    return item_definition_id


def _ensure_item_instance(
    connection: Connection,
    summary: _Summary,
    *,
    world_id: uuid.UUID,
    name: str,
    origin_notes: str,
    item_definition_id: uuid.UUID,
) -> uuid.UUID:
    existing = _entity_by_name(connection, world_id=world_id, name=name)
    if existing is not None:
        summary.add(created=False, label=f"item {name!r}", record_id=existing[0])
        return existing[0]
    item_id = _new_world_entity(
        connection,
        world_id=world_id,
        name=name,
        summary_text=origin_notes,
        entity_type_code="item_instance",
    )
    connection.execute(
        text(
            "INSERT INTO world.item_instances (item_instance_id, item_definition_id, origin_notes) "
            "VALUES (:id, :def, :notes)"
        ),
        {"id": item_id, "def": item_definition_id, "notes": origin_notes},
    )
    summary.add(created=True, label=f"item {name!r}", record_id=item_id)
    return item_id


def _ensure_item_state(
    connection: Connection,
    summary: _Summary,
    *,
    timeline_id: uuid.UUID,
    item_instance_id: uuid.UUID,
    item_name: str,
    charges_current: int,
    charges_maximum: int,
) -> None:
    label = f"item state: {item_name!r}"
    existing = connection.execute(
        text("SELECT 1 FROM campaign.item_state WHERE timeline_id = :t AND item_instance_id = :i"),
        {"t": timeline_id, "i": item_instance_id},
    ).scalar()
    if existing is not None:
        summary.add(created=False, label=label, record_id=item_instance_id)
        return
    connection.execute(
        text("""
            INSERT INTO campaign.item_state
                (timeline_id, item_instance_id, quantity, charges_current, charges_maximum)
            VALUES (:t, :i, 1, :cur, :max)
        """),
        {"t": timeline_id, "i": item_instance_id, "cur": charges_current, "max": charges_maximum},
    )
    summary.add(created=True, label=label, record_id=item_instance_id)


def _ensure_inventory_entry(
    connection: Connection,
    summary: _Summary,
    *,
    timeline_id: uuid.UUID,
    item_instance_id: uuid.UUID,
    item_name: str,
    holder_entity_id: uuid.UUID | None,
    location_id: uuid.UUID | None,
) -> None:
    where = "holder_entity_id = :h" if holder_entity_id is not None else "location_id = :l"
    label = f"inventory entry: {item_name!r}"
    existing = connection.execute(
        text(
            f"SELECT 1 FROM campaign.inventory_entries "
            f"WHERE timeline_id = :t AND item_instance_id = :i AND {where}"
        ),
        {"t": timeline_id, "i": item_instance_id, "h": holder_entity_id, "l": location_id},
    ).scalar()
    if existing is not None:
        summary.add(created=False, label=label, record_id=item_instance_id)
        return
    connection.execute(
        text("""
            INSERT INTO campaign.inventory_entries
                (timeline_id, item_instance_id, holder_entity_id, location_id)
            VALUES (:t, :i, :h, :l)
        """),
        {"t": timeline_id, "i": item_instance_id, "h": holder_entity_id, "l": location_id},
    )
    summary.add(created=True, label=label, record_id=item_instance_id)


def _ensure_historical_event(
    connection: Connection,
    summary: _Summary,
    *,
    world_id: uuid.UUID,
    timeline_id: uuid.UUID,
    campaign_id: uuid.UUID,
    fixture: _EventFixture,
    entity_ids: dict[str, uuid.UUID],
) -> uuid.UUID:
    """Create-or-reuse one `narrative.events` row (recorded or draft) for
    the World Explorer historical-event category, plus its
    `event_participants` / `event_locations`. Located by
    `(world_id, canonical_name)` among event-typed entities."""
    label = f"historical event {fixture.name!r} ({fixture.status_code})"
    existing = _entity_by_name(connection, world_id=world_id, name=fixture.name)
    world_time_id = _wk_world_time(
        connection,
        summary,
        world_id=world_id,
        suffix=f"event {fixture.name}",
        offset=fixture.world_time_offset,
    )
    if existing is not None:
        event_id = existing[0]
        summary.add(created=False, label=label, record_id=event_id)
    else:
        event_id = _new_world_entity(
            connection,
            world_id=world_id,
            name=fixture.name,
            summary_text=fixture.summary,
            entity_type_code="event",
        )
        event_type_id = lookup_id(
            connection, "narrative", "event_types", "event_type_id", fixture.event_type_code
        )
        status_id = lookup_id(
            connection, "narrative", "event_statuses", "event_status_id", fixture.status_code
        )
        connection.execute(
            text("""
                INSERT INTO narrative.events
                    (event_id, timeline_id, campaign_id, event_type_id, event_status_id,
                     world_time_id, details)
                VALUES (:id, :timeline, :campaign, :etype, :status, :world_time, :details)
            """),
            {
                "id": event_id,
                "timeline": timeline_id,
                "campaign": campaign_id,
                "etype": event_type_id,
                "status": status_id,
                "world_time": world_time_id,
                "details": fixture.details,
            },
        )
        for participant_name, role_code in fixture.participant_names:
            connection.execute(
                text("""
                    INSERT INTO narrative.event_participants
                        (event_id, participant_entity_id, participant_role_id)
                    VALUES (
                        :e, :p,
                        (SELECT event_participant_role_id FROM narrative.event_participant_roles
                         WHERE code = :rc)
                    )
                """),
                {"e": event_id, "p": entity_ids[participant_name], "rc": role_code},
            )
        for location_name in fixture.location_names:
            connection.execute(
                text("""
                    INSERT INTO narrative.event_locations (event_id, location_id, event_location_role)
                    VALUES (:e, :l, 'occurred_at')
                """),
                {"e": event_id, "l": entity_ids[location_name]},
            )
        summary.add(created=True, label=label, record_id=event_id)
    return event_id


def _ensure_world_relationship(
    connection: Connection,
    summary: _Summary,
    *,
    world_id: uuid.UUID,
    member_entity_id: uuid.UUID,
    organization_entity_id: uuid.UUID,
) -> uuid.UUID:
    """One `world.relationships` row (type `membership`) between two visible
    world resources, located by `(world_id, type, description)`."""
    label = f"relationship {_WK_RELATIONSHIP_TYPE_CODE!r}: {_WK_RELATIONSHIP_DESCRIPTION}"
    existing = connection.execute(
        text("""
            SELECT r.relationship_id
            FROM world.relationships r
            JOIN world.relationship_types rt ON rt.relationship_type_id = r.relationship_type_id
            WHERE r.world_id = :w AND rt.code = :tc AND r.description = :d
        """),
        {"w": world_id, "tc": _WK_RELATIONSHIP_TYPE_CODE, "d": _WK_RELATIONSHIP_DESCRIPTION},
    ).scalar()
    if existing is not None:
        assert isinstance(existing, uuid.UUID)
        summary.add(created=False, label=label, record_id=existing)
        return existing
    relationship_id = connection.execute(
        text("""
            INSERT INTO world.relationships (world_id, relationship_type_id, description)
            VALUES (
                :w,
                (SELECT relationship_type_id FROM world.relationship_types WHERE code = :tc),
                :d
            )
            RETURNING relationship_id
        """),
        {"w": world_id, "tc": _WK_RELATIONSHIP_TYPE_CODE, "d": _WK_RELATIONSHIP_DESCRIPTION},
    ).scalar()
    assert isinstance(relationship_id, uuid.UUID)
    for entity_id, role_code in (
        (member_entity_id, "member"),
        (organization_entity_id, "organization"),
    ):
        connection.execute(
            text("""
                INSERT INTO world.relationship_participants
                    (relationship_id, entity_id, participant_role_id)
                VALUES (
                    :r, :e,
                    (SELECT relationship_participant_role_id FROM world.relationship_participant_roles
                     WHERE code = :rc)
                )
            """),
            {"r": relationship_id, "e": entity_id, "rc": role_code},
        )
    summary.add(created=True, label=label, record_id=relationship_id)
    return relationship_id


def _get_or_create_knowledge_item(
    connection: Connection,
    summary: _Summary,
    *,
    world_id: uuid.UUID,
    fixture: _KnowledgeFixture,
    subject_entity_id: uuid.UUID | None,
) -> uuid.UUID:
    """One `knowledge.knowledge_items` entity, located by
    `(world_id, canonical_name == statement)` among knowledge-item-typed
    entities (a knowledge item's entity name is its statement — the same
    key `tests.factories.make_knowledge_item` uses)."""
    label = f"knowledge item {fixture.statement[:60]!r}"
    existing = _entity_by_name(connection, world_id=world_id, name=fixture.statement)
    if existing is not None:
        if existing[1] != "knowledge_item":
            raise SystemExit(
                f"an entity named like knowledge statement {fixture.statement[:40]!r} exists as a "
                f"{existing[1]!r} entity — rename or remove it, then re-run."
            )
        summary.add(created=False, label=label, record_id=existing[0])
        return existing[0]
    knowledge_item_id = _new_world_entity(
        connection,
        world_id=world_id,
        name=fixture.statement,
        summary_text=fixture.statement,
        entity_type_code="knowledge_item",
    )
    connection.execute(
        text("""
            INSERT INTO knowledge.knowledge_items
                (knowledge_item_id, knowledge_type_id, truth_status_id, canonical_statement,
                 sensitivity, subject_entity_id)
            VALUES (
                :id,
                (SELECT knowledge_type_id FROM knowledge.knowledge_types WHERE code = :kt),
                (SELECT truth_status_id FROM knowledge.truth_statuses WHERE code = :ts),
                :statement, :sensitivity, :subject
            )
        """),
        {
            "id": knowledge_item_id,
            "kt": fixture.knowledge_type_code,
            "ts": fixture.truth_status_code,
            "statement": fixture.statement,
            "sensitivity": fixture.sensitivity,
            "subject": subject_entity_id,
        },
    )
    summary.add(created=True, label=label, record_id=knowledge_item_id)
    return knowledge_item_id


def _ensure_party_knowledge(
    connection: Connection,
    summary: _Summary,
    *,
    timeline_id: uuid.UUID,
    party_id: uuid.UUID,
    knowledge_item_id: uuid.UUID,
    fixture: _KnowledgeFixture,
    label: str,
) -> None:
    existing = connection.execute(
        text(
            "SELECT 1 FROM campaign.party_knowledge "
            "WHERE timeline_id = :t AND party_id = :p AND knowledge_item_id = :k"
        ),
        {"t": timeline_id, "p": party_id, "k": knowledge_item_id},
    ).scalar()
    if existing is not None:
        summary.add(created=False, label=label, record_id=knowledge_item_id)
        return
    connection.execute(
        text("""
            INSERT INTO campaign.party_knowledge
                (timeline_id, party_id, knowledge_item_id, awareness_level, confidence,
                 interpretation, willing_to_share)
            VALUES (:t, :p, :k, :aware, :conf, :interp, :share)
        """),
        {
            "t": timeline_id,
            "p": party_id,
            "k": knowledge_item_id,
            "aware": fixture.awareness_level or "aware",
            "conf": fixture.confidence,
            "interp": fixture.interpretation,
            "share": fixture.willing_to_share,
        },
    )
    summary.add(created=True, label=label, record_id=knowledge_item_id)


def _ensure_entity_knowledge(
    connection: Connection,
    summary: _Summary,
    *,
    timeline_id: uuid.UUID,
    knower_entity_id: uuid.UUID,
    knowledge_item_id: uuid.UUID,
    fixture: _KnowledgeFixture,
    label: str,
) -> None:
    existing = connection.execute(
        text(
            "SELECT 1 FROM knowledge.entity_knowledge "
            "WHERE timeline_id = :t AND knower_entity_id = :e AND knowledge_item_id = :k"
        ),
        {"t": timeline_id, "e": knower_entity_id, "k": knowledge_item_id},
    ).scalar()
    if existing is not None:
        summary.add(created=False, label=label, record_id=knowledge_item_id)
        return
    connection.execute(
        text("""
            INSERT INTO knowledge.entity_knowledge
                (timeline_id, knowledge_item_id, knower_entity_id, awareness_level, confidence,
                 interpretation, willing_to_share)
            VALUES (:t, :k, :e, :aware, :conf, :interp, :share)
        """),
        {
            "t": timeline_id,
            "k": knowledge_item_id,
            "e": knower_entity_id,
            "aware": fixture.awareness_level or "aware",
            "conf": fixture.confidence,
            "interp": fixture.interpretation,
            "share": fixture.willing_to_share,
        },
    )
    summary.add(created=True, label=label, record_id=knowledge_item_id)


def _ensure_public_knowledge(
    connection: Connection,
    summary: _Summary,
    *,
    timeline_id: uuid.UUID,
    knowledge_item_id: uuid.UUID,
    location_id: uuid.UUID,
    fixture: _KnowledgeFixture,
    label: str,
    known_since_world_time_id: uuid.UUID | None = None,
) -> None:
    existing = connection.execute(
        text(
            "SELECT 1 FROM knowledge.public_knowledge "
            "WHERE timeline_id = :t AND knowledge_item_id = :k AND location_id = :l"
        ),
        {"t": timeline_id, "k": knowledge_item_id, "l": location_id},
    ).scalar()
    if existing is not None:
        summary.add(created=False, label=label, record_id=knowledge_item_id)
        return
    connection.execute(
        text("""
            INSERT INTO knowledge.public_knowledge
                (timeline_id, knowledge_item_id, location_id, awareness_level,
                 known_since_world_time_id)
            VALUES (:t, :k, :l, :aware, :since)
        """),
        {
            "t": timeline_id,
            "k": knowledge_item_id,
            "l": location_id,
            "aware": fixture.awareness_level or "aware",
            "since": known_since_world_time_id,
        },
    )
    summary.add(created=True, label=label, record_id=knowledge_item_id)


def _ensure_party_discovery(
    connection: Connection,
    summary: _Summary,
    *,
    timeline_id: uuid.UUID,
    party_id: uuid.UUID,
    knowledge_item_id: uuid.UUID,
    discovered_at_world_time_id: uuid.UUID | None,
    discovered_via_event_id: uuid.UUID | None,
    label: str,
) -> None:
    existing = connection.execute(
        text(
            "SELECT 1 FROM knowledge.party_discoveries "
            "WHERE timeline_id = :t AND party_id = :p AND knowledge_item_id = :k"
        ),
        {"t": timeline_id, "p": party_id, "k": knowledge_item_id},
    ).scalar()
    if existing is not None:
        summary.add(created=False, label=label, record_id=knowledge_item_id)
        return
    connection.execute(
        text("""
            INSERT INTO knowledge.party_discoveries
                (timeline_id, knowledge_item_id, party_id, discovered_at_world_time_id,
                 discovered_via_event_id)
            VALUES (:t, :k, :p, :at, :via)
        """),
        {
            "t": timeline_id,
            "k": knowledge_item_id,
            "p": party_id,
            "at": discovered_at_world_time_id,
            "via": discovered_via_event_id,
        },
    )
    summary.add(created=True, label=label, record_id=knowledge_item_id)


def _ensure_party_membership(
    connection: Connection,
    summary: _Summary,
    *,
    timeline_id: uuid.UUID,
    party_id: uuid.UUID,
    member_entity_id: uuid.UUID,
    member_label: str,
    effective_from_world_time_id: uuid.UUID,
) -> None:
    label = f"party membership: {member_label} in {_WK_PARTY_NAME!r}"
    existing = connection.execute(
        text("""
            SELECT 1 FROM campaign.party_memberships
            WHERE timeline_id = :t AND party_id = :p AND member_entity_id = :m
              AND effective_to_world_time_id IS NULL
        """),
        {"t": timeline_id, "p": party_id, "m": member_entity_id},
    ).scalar()
    if existing is not None:
        summary.add(created=False, label=label, record_id=member_entity_id)
        return
    connection.execute(
        text("""
            INSERT INTO campaign.party_memberships
                (timeline_id, party_id, member_entity_id, effective_from_world_time_id)
            VALUES (:t, :p, :m, :from_time)
        """),
        {
            "t": timeline_id,
            "p": party_id,
            "m": member_entity_id,
            "from_time": effective_from_world_time_id,
        },
    )
    summary.add(created=True, label=label, record_id=member_entity_id)


def _ensure_world_and_knowledge_fixtures(
    connection: Connection,
    summary: _Summary,
    *,
    world_id: uuid.UUID,
    ruleset_version_id: uuid.UUID,
    timeline_a_id: uuid.UUID,
    timeline_b_id: uuid.UUID,
    campaign_a_id: uuid.UUID,
    campaign_b_id: uuid.UUID,
    character_a_id: uuid.UUID,
    character_b_id: uuid.UUID,
) -> None:
    summary.note_world("Campaign A (Timeline A):")

    # --- world hierarchy + location state -------------------------------
    a_locations = _ensure_location_tree(
        connection,
        summary,
        world_id=world_id,
        fixture=_CAMPAIGN_A_LOCATIONS,
        parent_location_id=None,
    )
    _ensure_location_state(
        connection,
        summary,
        timeline_id=timeline_a_id,
        location_id=a_locations["Hollowmere"],
        location_name="Hollowmere",
        state=_HOLLOWMERE_STATE,
    )

    # --- non-location world entities ------------------------------------
    npc_id = _ensure_npc(
        connection, summary, world_id=world_id, ruleset_version_id=ruleset_version_id
    )
    guild_id = _ensure_organization(
        connection,
        summary,
        world_id=world_id,
        name=_GUILD_NAME,
        summary_text=_GUILD_PUBLIC_DESCRIPTION,
        organization_type_code="guild",
        entity_type_code="organization",
        public_description=_GUILD_PUBLIC_DESCRIPTION,
        internal_description=_GUILD_INTERNAL_DESCRIPTION,
        headquarters_location_id=a_locations["The Sunken Archive"],
    )
    _ensure_government(
        connection, summary, world_id=world_id, hq_location_id=a_locations["Hollowmere"]
    )
    religion_id = _ensure_religion(connection, summary, world_id=world_id)
    _ensure_religious_organization(connection, summary, world_id=world_id, religion_id=religion_id)

    item_definition_id = _get_or_create_item_definition(
        connection, summary, ruleset_version_id=ruleset_version_id
    )
    held_item_id = _ensure_item_instance(
        connection,
        summary,
        world_id=world_id,
        name=_HELD_ITEM_NAME,
        origin_notes=_HELD_ITEM_ORIGIN,
        item_definition_id=item_definition_id,
    )
    _ensure_item_state(
        connection,
        summary,
        timeline_id=timeline_a_id,
        item_instance_id=held_item_id,
        item_name=_HELD_ITEM_NAME,
        charges_current=3,
        charges_maximum=3,
    )
    _ensure_inventory_entry(
        connection,
        summary,
        timeline_id=timeline_a_id,
        item_instance_id=held_item_id,
        item_name=_HELD_ITEM_NAME,
        holder_entity_id=character_a_id,
        location_id=None,
    )
    loose_item_id = _ensure_item_instance(
        connection,
        summary,
        world_id=world_id,
        name=_LOOSE_ITEM_NAME,
        origin_notes=_LOOSE_ITEM_ORIGIN,
        item_definition_id=item_definition_id,
    )
    _ensure_item_state(
        connection,
        summary,
        timeline_id=timeline_a_id,
        item_instance_id=loose_item_id,
        item_name=_LOOSE_ITEM_NAME,
        charges_current=1,
        charges_maximum=1,
    )
    _ensure_inventory_entry(
        connection,
        summary,
        timeline_id=timeline_a_id,
        item_instance_id=loose_item_id,
        item_name=_LOOSE_ITEM_NAME,
        holder_entity_id=None,
        location_id=a_locations["The Tidebound Crypt"],
    )

    # --- historical events + a relationship ----------------------------
    entity_lookup: dict[str, uuid.UUID] = {
        _NPC_NAME: npc_id,
        _CHARACTER_A_NAME: character_a_id,
        _CHARACTER_B_NAME: character_b_id,
        **a_locations,
    }
    event_ids: dict[str, uuid.UUID] = {}
    for event_fixture in _CAMPAIGN_A_EVENTS:
        event_ids[event_fixture.name] = _ensure_historical_event(
            connection,
            summary,
            world_id=world_id,
            timeline_id=timeline_a_id,
            campaign_id=campaign_a_id,
            fixture=event_fixture,
            entity_ids=entity_lookup,
        )
    _ensure_world_relationship(
        connection,
        summary,
        world_id=world_id,
        member_entity_id=npc_id,
        organization_entity_id=guild_id,
    )

    # --- knowledge party + memberships --------------------------------
    party_id = _get_or_create_party(connection, summary, world_id=world_id, name=_WK_PARTY_NAME)
    _ensure_campaign_party(
        connection, summary, campaign_id=campaign_a_id, party_id=party_id, party_name=_WK_PARTY_NAME
    )
    membership_start = _wk_world_time(
        connection, summary, world_id=world_id, suffix="party membership start", offset=10
    )
    _ensure_party_membership(
        connection,
        summary,
        timeline_id=timeline_a_id,
        party_id=party_id,
        member_entity_id=character_a_id,
        member_label=_CHARACTER_A_NAME,
        effective_from_world_time_id=membership_start,
    )
    _ensure_party_membership(
        connection,
        summary,
        timeline_id=timeline_a_id,
        party_id=party_id,
        member_entity_id=character_b_id,
        member_label=_CHARACTER_B_NAME,
        effective_from_world_time_id=membership_start,
    )

    # --- knowledge records -------------------------------------------
    subject_lookup: dict[str, uuid.UUID] = dict(entity_lookup)
    subject_lookup[_GOVERNMENT_NAME] = _entity_by_name(
        connection, world_id=world_id, name=_GOVERNMENT_NAME
    )[0]  # type: ignore[index]
    subject_lookup[_HELD_ITEM_NAME] = held_item_id
    subject_lookup[_RELIGIOUS_ORG_NAME] = _entity_by_name(
        connection, world_id=world_id, name=_RELIGIOUS_ORG_NAME
    )[0]  # type: ignore[index]
    quest_entity = _entity_by_name(connection, world_id=world_id, name=_QUEST_A_ACTIVE_NAME)
    if quest_entity is not None:
        subject_lookup[_QUEST_A_ACTIVE_NAME] = quest_entity[0]

    for kf in _CAMPAIGN_A_KNOWLEDGE:
        subject_id = subject_lookup.get(kf.subject_name) if kf.subject_name else None
        knowledge_item_id = _get_or_create_knowledge_item(
            connection, summary, world_id=world_id, fixture=kf, subject_entity_id=subject_id
        )
        label = f"{kf.owner} knowledge {kf.statement[:48]!r}"
        if kf.owner == "party":
            _ensure_party_knowledge(
                connection,
                summary,
                timeline_id=timeline_a_id,
                party_id=party_id,
                knowledge_item_id=knowledge_item_id,
                fixture=kf,
                label=label,
            )
        elif kf.owner == "character_a":
            _ensure_entity_knowledge(
                connection,
                summary,
                timeline_id=timeline_a_id,
                knower_entity_id=character_a_id,
                knowledge_item_id=knowledge_item_id,
                fixture=kf,
                label=label,
            )
        elif kf.owner == "character_b":
            _ensure_entity_knowledge(
                connection,
                summary,
                timeline_id=timeline_a_id,
                knower_entity_id=character_b_id,
                knowledge_item_id=knowledge_item_id,
                fixture=kf,
                label=label,
            )
        elif kf.owner == "public":
            _ensure_public_knowledge(
                connection,
                summary,
                timeline_id=timeline_a_id,
                knowledge_item_id=knowledge_item_id,
                location_id=a_locations["Hollowmere"],
                fixture=kf,
                label=label,
            )
        # owner == "canonical": knowledge_items row only, no belief row.

        if kf.discovered:
            assert kf.discovery_world_time_offset is not None
            discovery_time = _wk_world_time(
                connection,
                summary,
                world_id=world_id,
                suffix=f"discovery {kf.statement[:32]}",
                offset=kf.discovery_world_time_offset,
            )
            source_event_id = (
                event_ids.get(kf.discovery_source_event_name)
                if kf.discovery_source_event_name
                else None
            )
            _ensure_party_discovery(
                connection,
                summary,
                timeline_id=timeline_a_id,
                party_id=party_id,
                knowledge_item_id=knowledge_item_id,
                discovered_at_world_time_id=discovery_time,
                discovered_via_event_id=source_event_id,
                label=f"party discovery {kf.statement[:40]!r}",
            )

    # --- Campaign B isolation data (Timeline B) -----------------------
    summary.note_world("")
    summary.note_world("Campaign B (Timeline B):")
    b_location_ids = _ensure_location_tree(
        connection,
        summary,
        world_id=world_id,
        fixture=_CAMPAIGN_B_LOCATION,
        parent_location_id=None,
    )
    saltreach_id = b_location_ids["Saltreach Harbor"]
    _ensure_location_state(
        connection,
        summary,
        timeline_id=timeline_b_id,
        location_id=saltreach_id,
        location_name="Saltreach Harbor",
        state=_SALTREACH_STATE,
    )
    _ensure_historical_event(
        connection,
        summary,
        world_id=world_id,
        timeline_id=timeline_b_id,
        campaign_id=campaign_b_id,
        fixture=_CAMPAIGN_B_EVENT,
        entity_ids={"Saltreach Harbor": saltreach_id},
    )
    b_knowledge_id = _get_or_create_knowledge_item(
        connection,
        summary,
        world_id=world_id,
        fixture=_CAMPAIGN_B_KNOWLEDGE,
        subject_entity_id=saltreach_id,
    )
    _ensure_public_knowledge(
        connection,
        summary,
        timeline_id=timeline_b_id,
        knowledge_item_id=b_knowledge_id,
        location_id=saltreach_id,
        fixture=_CAMPAIGN_B_KNOWLEDGE,
        label=f"public knowledge (Campaign B) {_CAMPAIGN_B_KNOWLEDGE.statement[:40]!r}",
    )

    _note_world_knowledge_reference_block(
        summary,
        campaign_a_id=campaign_a_id,
        campaign_b_id=campaign_b_id,
        character_a_id=character_a_id,
        character_b_id=character_b_id,
        party_id=party_id,
        world_entity_ids={
            "npc": npc_id,
            "guild": guild_id,
            "religion": religion_id,
            "held_item": held_item_id,
            "loose_item": loose_item_id,
            "building": a_locations["The Sunken Archive"],
            "settlement": a_locations["Hollowmere"],
            "dungeon": a_locations["The Tidebound Crypt"],
            "dungeon_area": a_locations["The Lantern Antechamber"],
            "saltreach": saltreach_id,
        },
        event_ids=event_ids,
    )


def _note_world_knowledge_reference_block(
    summary: _Summary,
    *,
    campaign_a_id: uuid.UUID,
    campaign_b_id: uuid.UUID,
    character_a_id: uuid.UUID,
    character_b_id: uuid.UUID,
    party_id: uuid.UUID,
    world_entity_ids: dict[str, uuid.UUID],
    event_ids: dict[str, uuid.UUID],
) -> None:
    n = summary.note_world
    n("")
    n(f"Campaign A id:  {campaign_a_id}")
    n(f"Campaign B id:  {campaign_b_id}")
    n(f"Character A id: {character_a_id}")
    n(f"Character B id: {character_b_id}")
    n(f"{_WK_PARTY_NAME!r} party id: {party_id}  (Character A and B are current members)")
    n("")
    n("World Explorer fixture entities (Campaign A):")
    n(f"  NPC {_NPC_NAME!r}: {world_entity_ids['npc']}")
    n(f"  organization {_GUILD_NAME!r}: {world_entity_ids['guild']}")
    n(f"  religion {_RELIGION_NAME!r}: {world_entity_ids['religion']}")
    n(f"  settlement 'Hollowmere': {world_entity_ids['settlement']}")
    n(f"  building 'The Sunken Archive': {world_entity_ids['building']}")
    n(f"  dungeon 'The Tidebound Crypt': {world_entity_ids['dungeon']}")
    n(f"  dungeon area 'The Lantern Antechamber': {world_entity_ids['dungeon_area']}")
    n(f"  held item {_HELD_ITEM_NAME!r} (Character A): {world_entity_ids['held_item']}")
    n(f"  loose item {_LOOSE_ITEM_NAME!r} (in the crypt): {world_entity_ids['loose_item']}")
    n("")
    n("Historical events (Campaign A / Timeline A):")
    for name, event_id in event_ids.items():
        n(f"  {name!r}: {event_id}")
    n("  -- 'The Magistrate's Secret Accord' is a DRAFT event: a GM sees it in")
    n("     /world/search?category=event and /world/events/{id}; a plain player does not.")
    n("")
    n(f"Campaign B distinct location 'Saltreach Harbor': {world_entity_ids['saltreach']}")
    n("  -- world-canon: it also appears in Campaign A's /world/search by the documented")
    n("     world-scoped visibility model (readiness §10.1). Its location_state, the event")
    n("     at it, and the knowledge about it are Timeline B only and never surface in")
    n("     Campaign A. Isolation is proven through those timeline-scoped rows.")
    n("")
    n("Ready-to-use request paths (cookie-authenticated HTTP -- run these yourself; this")
    n("script never performs them and never claims one passed):")
    n(f"  World search (all):        GET /campaigns/{campaign_a_id}/world/search")
    n(f"  World search (case-insens): GET /campaigns/{campaign_a_id}/world/search?q=hollowmere")
    n(
        f"  World search (type filter): GET /campaigns/{campaign_a_id}/world/search?category=religion"
    )
    n(f"  World search (paginate):   GET /campaigns/{campaign_a_id}/world/search?limit=2")
    n(
        f"  Location + breadcrumbs:    GET /campaigns/{campaign_a_id}/world/locations/{world_entity_ids['building']}"
    )
    n(
        f"  Religion detail:           GET /campaigns/{campaign_a_id}/world/religions/{world_entity_ids['religion']}"
    )
    n(
        f"  Loose item detail:         GET /campaigns/{campaign_a_id}/world/items/{world_entity_ids['loose_item']}"
    )
    n(
        f"  Event detail:              GET /campaigns/{campaign_a_id}/world/events/"
        f"{event_ids.get('The Sundering of the Vale', '<id>')}"
    )
    n(f"  Relationships:             GET /campaigns/{campaign_a_id}/world/relationships")
    n("")
    n(
        f"  Knowledge known (party):   GET /campaigns/{campaign_a_id}/knowledge?view=known&character_id={character_a_id}&party_id={party_id}"
    )
    n(
        f"  Knowledge rumors:          GET /campaigns/{campaign_a_id}/knowledge?view=rumors&character_id={character_a_id}&party_id={party_id}"
    )
    n(
        f"  Knowledge party_shared:    GET /campaigns/{campaign_a_id}/knowledge?view=party_shared&character_id={character_a_id}&party_id={party_id}"
    )
    n(
        f"  Knowledge recent:          GET /campaigns/{campaign_a_id}/knowledge?view=recent&character_id={character_a_id}&party_id={party_id}"
    )
    n(
        f"  Knowledge private (A):     GET /campaigns/{campaign_a_id}/knowledge?view=character_private&character_id={character_a_id}"
    )
    n(
        f"  Knowledge private (B):     GET /campaigns/{campaign_a_id}/knowledge?view=character_private&character_id={character_b_id}"
    )
    n(f"  Knowledge public:          GET /campaigns/{campaign_a_id}/knowledge?view=public")
    n(f"  Knowledge public (B only): GET /campaigns/{campaign_b_id}/knowledge?view=public")
    n("")
    n("  -- The distorted party belief: view=known shows the party's interpretation")
    n("     ('...to appease the Tidefather...'); a GM (canon.edit) sees the canonical")
    n("     statement ('...to cut the treasury's salvage-levy losses...') plus truth_status.")


def _run(connection: Connection, *, user_id: uuid.UUID) -> _Summary:
    summary = _Summary()

    user = _resolve_user(connection, user_id)
    print(
        f"Target account: user_id={user.user_id} display_name={user.display_name!r} "
        f"login_name={user.login_name!r} is_platform_administrator={user.is_platform_administrator}"
    )

    ruleset_id, ruleset_version_id = _get_ruleset(connection)

    world_id = _get_or_create_world(connection, summary)
    _ensure_world_ruleset(connection, summary, world_id=world_id, ruleset_id=ruleset_id)
    _ensure_relationship_type_capabilities(connection, summary)

    timeline_a_id = _get_or_create_timeline(
        connection, summary, world_id=world_id, name=_TIMELINE_A_NAME
    )
    timeline_b_id = _get_or_create_timeline(
        connection, summary, world_id=world_id, name=_TIMELINE_B_NAME
    )

    campaign_a_id, campaign_a_membership_id = _get_or_create_campaign(
        connection,
        summary,
        timeline_id=timeline_a_id,
        ruleset_version_id=ruleset_version_id,
        name=_CAMPAIGN_A_NAME,
        user=user,
    )
    campaign_b_id, _campaign_b_membership_id = _get_or_create_campaign(
        connection,
        summary,
        timeline_id=timeline_b_id,
        ruleset_version_id=ruleset_version_id,
        name=_CAMPAIGN_B_NAME,
        user=user,
    )

    character_a_id = _get_or_create_character(
        connection,
        summary,
        world_id=world_id,
        name=_CHARACTER_A_NAME,
        species_code=_CHARACTER_A_SPECIES_CODE,
        ruleset_version_id=ruleset_version_id,
        owner_user_id=user.user_id,
    )
    character_b_id = _get_or_create_character(
        connection,
        summary,
        world_id=world_id,
        name=_CHARACTER_B_NAME,
        species_code=_CHARACTER_B_SPECIES_CODE,
        ruleset_version_id=ruleset_version_id,
        owner_user_id=user.user_id,
    )

    _ensure_character_relationship(
        connection,
        summary,
        campaign_id=campaign_a_id,
        campaign_membership_id=campaign_a_membership_id,
        character_id=character_a_id,
        character_label=_CHARACTER_A_NAME,
        world_id=world_id,
        actor_user_id=user.user_id,
    )
    _ensure_character_relationship(
        connection,
        summary,
        campaign_id=campaign_a_id,
        campaign_membership_id=campaign_a_membership_id,
        character_id=character_b_id,
        character_label=_CHARACTER_B_NAME,
        world_id=world_id,
        actor_user_id=user.user_id,
    )

    _ensure_character_state(
        connection,
        summary,
        timeline_id=timeline_a_id,
        character_id=character_a_id,
        character_label=_CHARACTER_A_NAME,
        state=_CHARACTER_A_STATE,
    )
    _ensure_character_state(
        connection,
        summary,
        timeline_id=timeline_a_id,
        character_id=character_b_id,
        character_label=_CHARACTER_B_NAME,
        state=_CHARACTER_B_STATE,
    )

    condition_id = _resolve_condition_id(
        connection, ruleset_version_id=ruleset_version_id, code=_CONDITION_CODE
    )
    _ensure_character_condition(
        connection,
        summary,
        timeline_id=timeline_a_id,
        character_id=character_a_id,
        character_label=_CHARACTER_A_NAME,
        condition_id=condition_id,
        condition_code=_CONDITION_CODE,
        source_description=_CONDITION_SOURCE_DESCRIPTION,
    )

    resource_definition_id = _resolve_resource_definition_id(
        connection, ruleset_version_id=ruleset_version_id, code=_RESOURCE_CODE
    )
    _ensure_character_resource(
        connection,
        summary,
        timeline_id=timeline_a_id,
        character_id=character_a_id,
        character_label=_CHARACTER_A_NAME,
        resource_definition_id=resource_definition_id,
        resource_code=_RESOURCE_CODE,
        current_amount=_RESOURCE_CURRENT_AMOUNT,
        maximum_amount=_RESOURCE_MAXIMUM_AMOUNT,
    )

    _ensure_campaign_sessions(
        connection,
        summary,
        campaign_id=campaign_a_id,
        campaign_name=_CAMPAIGN_A_NAME,
        timeline_id=timeline_a_id,
        world_id=world_id,
        fixtures=_CAMPAIGN_A_SESSIONS,
    )
    campaign_b_session_ids = _ensure_campaign_sessions(
        connection,
        summary,
        campaign_id=campaign_b_id,
        campaign_name=_CAMPAIGN_B_NAME,
        timeline_id=timeline_b_id,
        world_id=world_id,
        fixtures=_CAMPAIGN_B_SESSIONS,
    )

    summary.note("")
    summary.note(
        "Cross-campaign / invalid-id manual test: request "
        f"GET /campaigns/{campaign_a_id}/sessions/{campaign_b_session_ids[1]} "
        "(Campaign B's session under Campaign A's URL). The API must return the same "
        "non-disclosing 'unavailable' response as a nonexistent session id."
    )

    # ----------------------------------------------------------------------
    # Phase 13D quest list/detail fixtures
    # ----------------------------------------------------------------------
    quest_party_id = _get_or_create_party(
        connection, summary, world_id=world_id, name=_QUEST_A_PARTY_NAME
    )
    _ensure_campaign_party(
        connection,
        summary,
        campaign_id=campaign_a_id,
        party_id=quest_party_id,
        party_name=_QUEST_A_PARTY_NAME,
    )
    campaign_a_quest_ids = _ensure_campaign_quests(
        connection,
        summary,
        campaign_name=_CAMPAIGN_A_NAME,
        timeline_id=timeline_a_id,
        world_id=world_id,
        quests=_CAMPAIGN_A_QUESTS,
        party_id=quest_party_id,
    )
    campaign_b_quest_ids = _ensure_campaign_quests(
        connection,
        summary,
        campaign_name=_CAMPAIGN_B_NAME,
        timeline_id=timeline_b_id,
        world_id=world_id,
        quests=(_CAMPAIGN_B_QUEST,),
    )

    _note_quest_reference_block(
        summary,
        campaign_a_id=campaign_a_id,
        campaign_b_id=campaign_b_id,
        character_a_id=character_a_id,
        character_b_id=character_b_id,
        campaign_a_quest_ids=campaign_a_quest_ids,
        campaign_b_quest_id=campaign_b_quest_ids[_CAMPAIGN_B_QUEST_NAME],
    )

    # ----------------------------------------------------------------------
    # Phase 13D World Explorer + Knowledge fixtures
    # ----------------------------------------------------------------------
    _ensure_world_and_knowledge_fixtures(
        connection,
        summary,
        world_id=world_id,
        ruleset_version_id=ruleset_version_id,
        timeline_a_id=timeline_a_id,
        timeline_b_id=timeline_b_id,
        campaign_a_id=campaign_a_id,
        campaign_b_id=campaign_b_id,
        character_a_id=character_a_id,
        character_b_id=character_b_id,
    )

    return summary


def _glass_ossuary_stage_names_in_order() -> list[str]:
    active = next(q for q in _CAMPAIGN_A_QUESTS if q.name == _QUEST_A_ACTIVE_NAME)
    return [s.name for s in sorted(active.stages, key=lambda s: (s.sequence_number, s.name))]


def _glass_ossuary_visible_objectives(*, non_gm: bool) -> list[str]:
    active = next(q for q in _CAMPAIGN_A_QUESTS if q.name == _QUEST_A_ACTIVE_NAME)
    return [
        o.name
        for stage in active.stages
        for o in stage.objectives
        if (not non_gm) or _objective_visible_to_non_gm(o)
    ]


def _note_quest_reference_block(
    summary: _Summary,
    *,
    campaign_a_id: uuid.UUID,
    campaign_b_id: uuid.UUID,
    character_a_id: uuid.UUID,
    character_b_id: uuid.UUID,
    campaign_a_quest_ids: dict[str, uuid.UUID],
    campaign_b_quest_id: uuid.UUID,
) -> None:
    """The task's "quest fixture reference" block — IDs, the expected
    ordered stage names, which objectives the real API returns for the
    supplied account vs. a non-GM audience, and ready-to-use request paths.
    Every "expected" line here describes what the real production query
    should return; it is not itself proof. `main()` runs the real queries
    after an applied run (`_print_quest_verification`) and prints that
    separately, clearly labelled as database/query verification — never as
    an HTTP result."""
    n = summary.note_quest
    n("")
    n(f"Campaign A id:  {campaign_a_id}")
    n(f"Campaign B id:  {campaign_b_id}")
    n(f"Character A id: {character_a_id}")
    n(f"Character B id: {character_b_id}")
    n("")
    n("Fixture quests:")
    for name, quest_id in campaign_a_quest_ids.items():
        n(f"  [Campaign A] {name!r}: {quest_id}")
    n(f"  [Campaign B] {_CAMPAIGN_B_QUEST_NAME!r}: {campaign_b_quest_id}")
    n("")
    n(
        f"{_QUEST_A_ACTIVE_NAME!r} expected stage order (backend order, NOT alphabetical): "
        + " -> ".join(repr(s) for s in _glass_ossuary_stage_names_in_order())
    )
    n(
        f"{_QUEST_A_ACTIVE_NAME!r} objectives the real API returns for the supplied account "
        "(campaign owner / GM, include_hidden=True): "
        + ", ".join(repr(o) for o in _glass_ossuary_visible_objectives(non_gm=False))
    )
    n(
        f"{_QUEST_A_ACTIVE_NAME!r} objectives a non-GM player perspective would see "
        "(include_hidden=False): "
        + ", ".join(repr(o) for o in _glass_ossuary_visible_objectives(non_gm=True))
        + " -- the gm_only and stateless hidden_until_discovered objectives are filtered out "
        "for that audience; this account holds canon.edit, so it is NOT filtered for the "
        "supplied user, and this script does not weaken that authority to prove otherwise."
    )
    n("")
    n("Ready-to-use request paths (cookie-authenticated HTTP -- run these yourself; this")
    n("script never performs them and never claims one passed):")
    n(
        f"  Campaign A quest list (Character A):   GET /campaigns/{campaign_a_id}/quests?character_id={character_a_id}"
    )
    n(
        f"  Campaign A quest list (Character B):   GET /campaigns/{campaign_a_id}/quests?character_id={character_b_id}"
    )
    n(
        f"  {_QUEST_A_ACTIVE_NAME!r} detail (Character A): "
        f"GET /campaigns/{campaign_a_id}/quests/{campaign_a_quest_ids[_QUEST_A_ACTIVE_NAME]}"
        f"?character_id={character_a_id}"
    )
    n(
        f"  {_QUEST_A_ACTIVE_NAME!r} detail (Character B): "
        f"GET /campaigns/{campaign_a_id}/quests/{campaign_a_quest_ids[_QUEST_A_ACTIVE_NAME]}"
        f"?character_id={character_b_id}"
    )
    n(
        f"  empty-stage quest detail:              "
        f"GET /campaigns/{campaign_a_id}/quests/{campaign_a_quest_ids[_QUEST_A_COMPLETED_NAME]}"
    )
    n(
        f"  null-status quest detail:              "
        f"GET /campaigns/{campaign_a_id}/quests/{campaign_a_quest_ids[_QUEST_A_NULL_STATUS_NAME]}"
    )
    n(
        f"  cross-campaign (Campaign B quest under Campaign A): "
        f"GET /campaigns/{campaign_a_id}/quests/{campaign_b_quest_id}"
    )
    n(
        f"  nonexistent quest (baseline for the above): "
        f"GET /campaigns/{campaign_a_id}/quests/{uuid.uuid4()}"
    )
    n("")
    n(
        "Note on the cross-campaign request: the quest LIST endpoint is timeline/audience "
        f"scoped and does NOT include {_CAMPAIGN_B_QUEST_NAME!r} in Campaign A. The DETAIL "
        "endpoint applies the same shared tracking rule, so requesting Campaign B's quest id "
        "under Campaign A returns the standard non-disclosing 404 (identical to a nonexistent "
        "quest) — quests are world canon with no campaign_id, but campaign exposure requires "
        "a qualifying campaign.quest_state row on the campaign's exact timeline, and Campaign "
        "B's quest has none on Timeline A. See the module docstring and the query verification "
        "block below."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--user-id",
        required=True,
        type=uuid.UUID,
        help="Existing, active, local security.users.user_id to authorize on both campaigns "
        "and both character perspectives. Never guessed — confirm the exact account first.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write changes. Without this flag, the identical sequence runs and is then "
        "rolled back (a reliable preview, including any constraint/trigger rejection) and "
        "nothing is committed.",
    )
    args = parser.parse_args(argv)

    _require_non_production()
    _require_local_target()

    print(
        f"environment={settings.environment} mode={'APPLY' if args.apply else 'PREVIEW (no writes committed)'}"
    )
    print(f"target database (password redacted): {_safe_target_summary()}")

    engine = create_engine(_database_url())
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            summary = _run(connection, user_id=args.user_id)
        except BaseException:
            transaction.rollback()
            raise
        if args.apply:
            transaction.commit()
        else:
            transaction.rollback()

    print("\n".join(summary.lines))
    if summary.report:
        print("\n-- Session fixture quick reference (for manual portal verification) --")
        print("\n".join(summary.report))
    if summary.quest_report:
        print("\n-- Quest fixture quick reference (for manual portal verification) --")
        print("\n".join(summary.quest_report))
    if summary.world_report:
        print(
            "\n-- World Explorer + Knowledge fixture quick reference "
            "(for manual portal verification) --"
        )
        print("\n".join(summary.world_report))
    if args.apply:
        print("\nAPPLIED - changes committed.")
        _print_bootstrap_verification(user_id=args.user_id)
        _print_quest_verification(user_id=args.user_id)
        _print_world_knowledge_verification(user_id=args.user_id)
    else:
        print("\nPREVIEW ONLY - every change above was rolled back. Re-run with --apply to write.")
    return 0


def _print_bootstrap_verification(*, user_id: uuid.UUID) -> None:
    """Re-opens a fresh, read-only connection and runs the real `GET
    /auth/session` bootstrap query for `user_id` — proof the write actually
    persisted and that the bootstrap query itself recognizes it, not merely
    that this script's own inserts succeeded. This is a direct database
    check, not the browser/cookie-authenticated HTTP path — it does not by
    itself prove `/auth/session` will behave identically over HTTP."""
    engine = create_engine(_database_url())
    with engine.connect() as connection:
        connection.execute(text("SET default_transaction_read_only = on"))
        view = get_session_bootstrap(connection, user_id=user_id)
    print(f"\n-- get_session_bootstrap(user_id={user_id}) --")
    print(f"display_name={view.display_name!r} selected_campaign_id={view.selected_campaign_id}")
    for campaign in view.campaigns:
        perspectives = ", ".join(
            f"{p.character_name} ({p.character_id})" for p in campaign.character_perspectives
        )
        print(
            f"  campaign={campaign.campaign_name!r} ({campaign.campaign_id}) "
            f"timeline={campaign.timeline_name!r} ({campaign.timeline_id}) "
            f"roles={campaign.roles} capabilities={campaign.capabilities} "
            f"perspectives=[{perspectives}]"
        )


def _print_quest_verification(*, user_id: uuid.UUID) -> None:
    """Re-opens a fresh, read-only connection and runs the REAL production
    quest list/detail query functions (`dnd_ai.queries.quest.
    list_campaign_quests` / `get_quest_view`) with the real audience/access
    inputs they require for the supplied account — never a re-implementation
    of the visibility rules. This is database/query verification, not the
    browser/cookie-authenticated HTTP path; it does not by itself prove the
    `/campaigns/{id}/quests[...]` endpoints behave identically over HTTP.

    The supplied account is a campaign owner and therefore holds
    `canon.edit` in Campaign A, so `get_quest_endpoint` would run with
    `include_hidden=True` and resolve no party perspective. This function
    calls `get_quest_view` both that way (the real inputs for this account)
    and, separately, with `include_hidden=False` to show the non-GM-audience
    result — testing "both character perspectives" produces the identical
    result for this account because its `canon.edit` authority does not
    change when a `character_id` query parameter does, and that is stated
    explicitly below rather than pretended otherwise."""
    engine = create_engine(_database_url())
    with engine.connect() as connection:
        connection.execute(text("SET default_transaction_read_only = on"))
        view = get_session_bootstrap(connection, user_id=user_id)
        campaign_a = next(c for c in view.campaigns if c.campaign_name == _CAMPAIGN_A_NAME)
        campaign_b = next(c for c in view.campaigns if c.campaign_name == _CAMPAIGN_B_NAME)
        assert campaign_a.timeline_id is not None and campaign_b.timeline_id is not None
        is_gm = "canon.edit" in campaign_a.capabilities
        world_a = connection.execute(
            text("SELECT world_id FROM campaign.timelines WHERE timeline_id = :t"),
            {"t": campaign_a.timeline_id},
        ).scalar()
        assert isinstance(world_a, uuid.UUID)

        a_list = list_campaign_quests(
            connection,
            timeline_id=campaign_a.timeline_id,
            party_id=None,
            include_all_parties=is_gm,
        )
        b_list = list_campaign_quests(
            connection,
            timeline_id=campaign_b.timeline_id,
            party_id=None,
            include_all_parties=is_gm,
        )

        glass = next(i for i in a_list if i.name == _QUEST_A_ACTIVE_NAME)
        glass_view = get_quest_view(
            connection,
            quest_id=glass.quest_id,
            timeline_id=campaign_a.timeline_id,
            expected_world_id=world_a,
            party_id=None,
            include_hidden=is_gm,
            require_campaign_tracking=True,
            include_all_parties=is_gm,
        )
        glass_view_non_gm = get_quest_view(
            connection,
            quest_id=glass.quest_id,
            timeline_id=campaign_a.timeline_id,
            expected_world_id=world_a,
            party_id=None,
            include_hidden=False,
            require_campaign_tracking=True,
            include_all_parties=False,
        )

        empty = next(i for i in a_list if i.name == _QUEST_A_COMPLETED_NAME)
        empty_view = get_quest_view(
            connection,
            quest_id=empty.quest_id,
            timeline_id=campaign_a.timeline_id,
            expected_world_id=world_a,
            party_id=None,
            include_hidden=is_gm,
            require_campaign_tracking=True,
            include_all_parties=is_gm,
        )

        b_quest = next(i for i in b_list if i.name == _CAMPAIGN_B_QUEST_NAME)
        cross_in_a_list = any(i.quest_id == b_quest.quest_id for i in a_list)
        # The exact shape that exposed the Phase 13D disclosure defect: one
        # world, two timelines, one campaign per timeline, Campaign B's
        # quest state only on Timeline B, requested through Campaign A's
        # resolved timeline/audience — mirroring get_quest_endpoint's own
        # call (require_campaign_tracking=True, include_all_parties=is_gm).
        try:
            cross_view = get_quest_view(
                connection,
                quest_id=b_quest.quest_id,
                timeline_id=campaign_a.timeline_id,
                expected_world_id=world_a,
                party_id=None,
                include_hidden=is_gm,
                require_campaign_tracking=True,
                include_all_parties=is_gm,
            )
            cross_detail_result = (
                f"RETURNED quest {cross_view.name!r} "
                f"(status={cross_view.status_code!r}, {len(cross_view.stages)} stage(s)) -- "
                "UNEXPECTED: a same-world/other-timeline quest must be non-disclosing"
            )
        except QuestNotFoundError:
            cross_detail_result = "raised QuestNotFoundError (API -> non-disclosing 404)"

        try:
            get_quest_view(
                connection,
                quest_id=uuid.uuid4(),
                timeline_id=campaign_a.timeline_id,
                expected_world_id=world_a,
                party_id=None,
                include_hidden=is_gm,
                require_campaign_tracking=True,
                include_all_parties=is_gm,
            )
            nonexistent_result = "did NOT raise (unexpected)"
        except QuestNotFoundError:
            nonexistent_result = "raised QuestNotFoundError (API -> non-disclosing 404)"

    print("\n-- Quest production-query verification (database/query only, NOT HTTP) --")
    print(f"account holds canon.edit in Campaign A: {is_gm} (include_all_parties/include_hidden)")
    print(
        "Campaign A list (list_campaign_quests): "
        + ", ".join(f"{i.name!r}={i.status_code!r}" for i in a_list)
    )
    a_list_names = [i.name for i in a_list]
    print(
        "  ordering matches production contract (canonical_name ASC): "
        f"{a_list_names == sorted(a_list_names)}"
    )
    print(
        f"  {_QUEST_A_NULL_STATUS_NAME!r} present with null status: "
        f"{any(i.name == _QUEST_A_NULL_STATUS_NAME and i.status_code is None for i in a_list)}"
    )
    print(
        f"{_QUEST_A_ACTIVE_NAME!r} stage order (get_quest_view): "
        + " -> ".join(f"{s.name!r}(seq {s.sequence_number})" for s in glass_view.stages)
    )
    print(
        "  stage order preserved (sequence, not alphabetical): "
        f"{[s.name for s in glass_view.stages] == _glass_ossuary_stage_names_in_order()}"
    )
    print(
        f"{_QUEST_A_ACTIVE_NAME!r} objectives for THIS account (include_hidden=True): "
        + ", ".join(repr(o.name) for st in glass_view.stages for o in st.objectives)
    )
    print(
        f"{_QUEST_A_ACTIVE_NAME!r} objectives for a non-GM audience (include_hidden=False): "
        + ", ".join(repr(o.name) for st in glass_view_non_gm.stages for o in st.objectives)
        + " -- the difference is the gm_only + stateless hidden_until_discovered objectives; "
        "this account's canon.edit authority is unchanged by any character_id parameter, so "
        "both character perspectives yield the include_hidden=True result for this user."
    )
    print(
        f"{_QUEST_A_COMPLETED_NAME!r} (empty-stage quest) via get_quest_view: "
        f"status={empty_view.status_code!r}, stages={empty_view.stages!r}"
    )
    print(
        f"Campaign B quest {_CAMPAIGN_B_QUEST_NAME!r} in Campaign A's list: {cross_in_a_list} "
        "(must be False -- timeline-scoped non-disclosure holds for the list)"
    )
    print(f"Campaign B quest requested under Campaign A (get_quest_view): {cross_detail_result}")
    print(f"nonexistent quest id (get_quest_view): {nonexistent_result}")


def _print_world_knowledge_verification(*, user_id: uuid.UUID) -> None:
    """Re-opens a fresh, read-only connection and runs the REAL merged
    World Explorer / Knowledge query functions
    (`dnd_ai.queries.world_explorer.search_world_entities` /
    `get_location_view` / `get_event_view`,
    `dnd_ai.queries.knowledge_browse.list_knowledge`) with the access
    inputs the real API layer resolves for them — `resolve_access_context`,
    `resolve_world_character_visibility`, `resolve_party_perspective` — not
    a re-implementation of the visibility rules and never a hand-written
    lookalike query. Database/query verification only, not the
    browser/cookie-authenticated HTTP path.

    The supplied account is a GM (`canon.edit`) on both campaigns, so its
    World Explorer search runs with `include_draft_events=True` and its
    Knowledge reads run with `include_ground_truth=True`. Where the
    player-facing path differs, the real query is also called with the
    non-GM inputs a player's request resolves to (`include_ground_truth=
    False` + the `resolve_party_perspective` / character-knower result) and
    both are printed — the same stance `_print_quest_verification` takes."""
    engine = create_engine(_database_url())
    with engine.connect() as connection:
        connection.execute(text("SET default_transaction_read_only = on"))
        boot = get_session_bootstrap(connection, user_id=user_id)
        campaign_a = next(c for c in boot.campaigns if c.campaign_name == _CAMPAIGN_A_NAME)
        campaign_b = next(c for c in boot.campaigns if c.campaign_name == _CAMPAIGN_B_NAME)
        assert campaign_a.timeline_id is not None and campaign_b.timeline_id is not None
        world_a = connection.execute(
            text("SELECT world_id FROM campaign.timelines WHERE timeline_id = :t"),
            {"t": campaign_a.timeline_id},
        ).scalar()
        assert isinstance(world_a, uuid.UUID)

        access_a = resolve_access_context(
            connection, user_id=user_id, campaign_id=campaign_a.campaign_id
        )
        access_b = resolve_access_context(
            connection, user_id=user_id, campaign_id=campaign_b.campaign_id
        )
        assert access_a is not None and access_b is not None
        is_gm = access_a.has_capability("canon.edit")

        character_a_id = next(
            p.character_id
            for p in campaign_a.character_perspectives
            if p.character_name == _CHARACTER_A_NAME
        )
        character_b_id = next(
            p.character_id
            for p in campaign_a.character_perspectives
            if p.character_name == _CHARACTER_B_NAME
        )
        party_id = connection.execute(
            text("SELECT party_id FROM campaign.parties WHERE world_id = :w AND name = :n"),
            {"w": world_a, "n": _WK_PARTY_NAME},
        ).scalar()
        assert isinstance(party_id, uuid.UUID)

        all_codes = [c for codes in WORLD_CATEGORY_TYPE_CODES.values() for c in codes]
        char_vis = resolve_world_character_visibility(access_a)
        entity_denied, _ = access_a.resource_grant_targets("campaign.view", "entity_id")
        event_denied_grants, _ = access_a.resource_grant_targets("campaign.view", "event_id")
        cv_denied = entity_denied | event_denied_grants
        draft_denied, draft_allowed = access_a.resource_grant_targets("canon.edit", "event_id")

        def _search(
            codes: list[str], *, q: str | None, include_draft: bool
        ) -> tuple[WorldEntityCard, ...]:
            return search_world_entities(
                connection,
                world_id=world_a,
                timeline_id=campaign_a.timeline_id,  # type: ignore[arg-type]
                category_type_codes=codes,
                query_text=q,
                campaign_view_denied_entity_ids=cv_denied,
                character_visibility=char_vis,
                include_draft_events=include_draft,
                draft_event_allowed_ids=draft_allowed,
                draft_event_denied_ids=draft_denied,
                limit=100,
                after_name=None,
                after_entity_id=None,
            )

        every = _search(all_codes, q=None, include_draft=is_gm)
        categories_present = sorted({c.category for c in every})
        case_hits = [c.name for c in _search(all_codes, q="hollowmere", include_draft=is_gm)]
        religion_only = _search(
            list(WORLD_CATEGORY_TYPE_CODES["religion"]), q=None, include_draft=is_gm
        )

        first_two = search_world_entities(
            connection,
            world_id=world_a,
            timeline_id=campaign_a.timeline_id,
            category_type_codes=all_codes,
            query_text=None,
            campaign_view_denied_entity_ids=cv_denied,
            character_visibility=char_vis,
            include_draft_events=is_gm,
            draft_event_allowed_ids=draft_allowed,
            draft_event_denied_ids=draft_denied,
            limit=2,
            after_name=None,
            after_entity_id=None,
        )
        page_two_first: str | None = None
        if len(first_two) >= 2:
            page_two = search_world_entities(
                connection,
                world_id=world_a,
                timeline_id=campaign_a.timeline_id,
                category_type_codes=all_codes,
                query_text=None,
                campaign_view_denied_entity_ids=cv_denied,
                character_visibility=char_vis,
                include_draft_events=is_gm,
                draft_event_allowed_ids=draft_allowed,
                draft_event_denied_ids=draft_denied,
                limit=2,
                after_name=first_two[1].name_sort,
                after_entity_id=first_two[1].entity_id,
            )
            page_two_first = page_two[0].name if page_two else None

        building_id = connection.execute(
            text("SELECT entity_id FROM core.entities WHERE world_id = :w AND canonical_name = :n"),
            {"w": world_a, "n": "The Sunken Archive"},
        ).scalar()
        assert isinstance(building_id, uuid.UUID)
        crumbs = get_location_view(
            connection,
            location_id=building_id,
            timeline_id=campaign_a.timeline_id,
            expected_world_id=world_a,
            denied_entity_ids=cv_denied,
        )

        saltreach_event_id = connection.execute(
            text("SELECT entity_id FROM core.entities WHERE world_id = :w AND canonical_name = :n"),
            {"w": world_a, "n": _CAMPAIGN_B_EVENT.name},
        ).scalar()
        assert isinstance(saltreach_event_id, uuid.UUID)
        a_event_names = {c.name for c in _search(["event"], q=None, include_draft=is_gm)}
        try:
            get_event_view(
                connection,
                event_id=saltreach_event_id,
                timeline_id=campaign_a.timeline_id,
                expected_world_id=world_a,
                denied_entity_ids=cv_denied,
                include_draft=is_gm,
                draft_allowed=False,
                draft_denied=False,
                character_visibility=char_vis,
            )
            cross_event = "RETURNED (unexpected -- must be non-disclosing across timelines)"
        except WorldResourceNotFoundError:
            cross_event = "raised WorldResourceNotFoundError (API -> non-disclosing 404)"

        draft_name = _CAMPAIGN_A_EVENTS[2].name
        gm_draft = {c.name for c in _search(["event"], q=None, include_draft=True)}
        player_draft = {c.name for c in _search(["event"], q=None, include_draft=False)}

        def _knowledge(
            view: str, *, ground_truth: bool, party: uuid.UUID | None, knower: uuid.UUID | None
        ) -> tuple[KnowledgeListItem, ...]:
            return list_knowledge(
                connection,
                view=view,
                timeline_id=campaign_a.timeline_id,  # type: ignore[arg-type]
                world_id=world_a,
                include_ground_truth=ground_truth,
                authorized_party_id=party,
                authorized_knower_id=knower,
                query_text=None,
                knowledge_type_code=None,
                denied_item_ids=frozenset(),
                limit=100,
                after_statement=None,
                after_time_sort=None,
                after_record_id=None,
            )

        authorized_party = resolve_party_perspective(
            connection,
            access=access_a,
            campaign_id=campaign_a.campaign_id,
            character_id=character_a_id,
            party_id=party_id,
        )
        gm_known = _knowledge("known", ground_truth=True, party=None, knower=None)
        player_known = _knowledge("known", ground_truth=False, party=authorized_party, knower=None)
        private_a = _knowledge(
            "character_private", ground_truth=False, party=None, knower=character_a_id
        )
        private_b = _knowledge(
            "character_private", ground_truth=False, party=None, knower=character_b_id
        )
        recent = _knowledge(
            "recent", ground_truth=False, party=authorized_party, knower=character_a_id
        )
        public_a = _knowledge("public", ground_truth=is_gm, party=None, knower=None)
        public_b = list_knowledge(
            connection,
            view="public",
            timeline_id=campaign_b.timeline_id,
            world_id=world_a,
            include_ground_truth=access_b.has_capability("canon.edit"),
            authorized_party_id=None,
            authorized_knower_id=None,
            query_text=None,
            knowledge_type_code=None,
            denied_item_ids=frozenset(),
            limit=100,
            after_statement=None,
            after_time_sort=None,
            after_record_id=None,
        )

    distorted = "sluice-gates"
    gm_distorted = next((i for i in gm_known if distorted in i.statement.lower()), None)
    player_distorted = next((i for i in player_known if distorted in i.statement.lower()), None)
    canonical_only = "answer to the thing in the vault"

    print(
        "\n-- World Explorer + Knowledge production-query verification (database/query only, NOT HTTP) --"
    )
    print(f"account holds canon.edit in Campaign A: {is_gm}")
    print(f"World search categories present: {categories_present} (expect all six)")
    print(f"case-insensitive q='hollowmere' -> {case_hits} (expect 'Hollowmere' among them)")
    print(
        f"category=religion filter -> {[c.name for c in religion_only]} "
        f"(all category=='religion': {all(c.category == 'religion' for c in religion_only)})"
    )
    print(
        f"pagination limit=2: page-1 last = {first_two[-1].name!r}; page-2 first = {page_two_first!r} "
        f"(distinct, no overlap: {page_two_first not in {c.name for c in first_two}})"
    )
    print(
        f"breadcrumbs for 'The Sunken Archive' -> {[c.name for c in crumbs.breadcrumbs]} "
        "(expect ['Auremar', 'The Ashen Vale', 'Hollowmere'])"
    )
    print(
        f"Campaign B event {_CAMPAIGN_B_EVENT.name!r} in Campaign A event search: "
        f"{_CAMPAIGN_B_EVENT.name in a_event_names} (must be False)"
    )
    print(f"Campaign B event via get_event_view under Campaign A: {cross_event}")
    print(
        f"draft event {draft_name!r}: GM search sees it ({draft_name in gm_draft}), "
        f"player search does not ({draft_name not in player_draft})"
    )
    print(
        f"Knowledge 'known': GM sees {len(gm_known)} items (canonical-only secret present: "
        f"{any(canonical_only in i.statement.lower() for i in gm_known)}); "
        f"player party-perspective sees {len(player_known)} items (canonical-only secret present: "
        f"{any(canonical_only in i.statement.lower() for i in player_known)} -- must be False)"
    )
    if gm_distorted is not None and player_distorted is not None:
        print(
            f"distorted belief -- GM statement: {gm_distorted.statement!r} "
            f"(truth_status={gm_distorted.truth_status_code!r}); "
            f"player statement: {player_distorted.statement!r} "
            f"(truth_status={player_distorted.truth_status_code!r} -- must be None)"
        )
    print(
        f"character_private: A sees {sorted(i.statement[:30] for i in private_a)}; "
        f"B sees {sorted(i.statement[:30] for i in private_b)} (disjoint: "
        f"{not ({i.knowledge_item_id for i in private_a} & {i.knowledge_item_id for i in private_b})})"
    )
    recent_src = [
        (i.statement[:30], i.discovery_world_time_id is not None, i.source_event_id is not None)
        for i in recent
    ]
    print(f"recent (party+character): {recent_src} (expect a row with both provenance flags True)")
    print(
        f"public: Campaign A sees {len(public_a)} lore item(s) "
        f"(Campaign-B beacon lore present: "
        f"{any('beacon-keeper' in i.statement.lower() for i in public_a)} -- must be False); "
        f"Campaign B sees {len(public_b)} "
        f"(beacon lore present: {any('beacon-keeper' in i.statement.lower() for i in public_b)})"
    )


if __name__ == "__main__":
    raise SystemExit(main())
