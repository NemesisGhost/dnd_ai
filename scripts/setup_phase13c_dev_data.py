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

Not a general-purpose seeding framework — every name and shape here is
specific to this one fixture (see the `_WORLD_*`/`_CAMPAIGN_*`/`_CHARACTER_*`/
`_CAMPAIGN_A_SESSIONS`/`_CAMPAIGN_B_SESSIONS` constants below), and nothing
about this script generalizes to seeding arbitrary content.

Connects using the same resolution the running API itself uses
(`dnd_ai.config.settings.database_url`) — never a hardcoded connection
string or a separately-guessed URL, so this always targets whatever
database the local `uvicorn dnd_ai.api.app:app` process is actually reading
from (`DND_AI_DATABASE_URL`/`DATABASE_URL`, resolved the identical way).
Refuses to run at all when `DND_AI_ENVIRONMENT=production` (`settings.
environment`) — this script is a development-data convenience and must
never be pointed at a real deployment.

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
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import Connection, create_engine, text

from dnd_ai.api.audit import record_change_log
from dnd_ai.commands._shared import lookup_id
from dnd_ai.commands.access_grants import grant_character_relationship
from dnd_ai.commands.campaigns import create_campaign, grant_timeline_bootstrap
from dnd_ai.config import settings
from dnd_ai.queries.bootstrap import get_session_bootstrap

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

    def note(self, line: str) -> None:
        self.report.append(line)

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

    return summary


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

    print(
        f"environment={settings.environment} mode={'APPLY' if args.apply else 'PREVIEW (no writes committed)'}"
    )

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
    if args.apply:
        print("\nAPPLIED - changes committed.")
        _print_bootstrap_verification(user_id=args.user_id)
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


if __name__ == "__main__":
    raise SystemExit(main())
