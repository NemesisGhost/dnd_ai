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

Also supports the Phase 13D character Sheet-panel live-verification
checkpoint: Character A carries a fully populated `character.
character_builds` (a multiclass Fighter/Wizard build with a subclass,
every ability score, a proficient and an expertise skill, a proficient
saving throw, two free-text proficiencies, two granted features, and a
spellcasting profile with independent known/prepared spells) plus one
language, one sense, and one movement mode; Character B carries a
legitimate *minimal* build (one class level, three of six ability scores,
one movement mode, and no proficiencies/features/spellcasting/languages/
senses at all) — see the "Phase 13D Sheet-panel fixture" constants block
below for the exact content and `_ensure_character_sheet_fixture` for how
it is created/reconciled. Both builds are selected as each character's
*active* build on Phase13C Timeline A via `campaign.character_state.
character_build_id` (`_ensure_active_build_selection`) — never a "current"
flag on the build itself, matching `dnd_ai.queries.character_sheet`'s own
documented active-build resolution rule. Every `rules.*` id this fixture
references (classes, subclasses, features, spells, abilities, skills,
proficiency types, languages) is looked up by code against the already-
seeded dnd5e/2024 content (migration 022) — this fixture creates no
`rules.*` rows of its own.

Not a general-purpose seeding framework — every name and shape here is
specific to this one fixture (see the `_WORLD_*`/`_CAMPAIGN_*`/`_CHARACTER_*`
constants below), and nothing about this script generalizes to seeding
arbitrary content.

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

# ---------------------------------------------------------------------------
# Phase 13D character Sheet-panel live-verification fixture data.
#
# Character A ("Fighter 2 / Wizard 1", champion subclass) exercises every
# populated sheet section this fixture can build from already-seeded rules
# content (migration 022's dnd5e/2024 content — no new rules.* rows are
# created here, only referenced by code): all six ability scores, a
# multiclass build with a subclass, a proficient skill, an expertise skill
# (a fixture liberty — nothing in this schema restricts expertise to
# specific classes), a proficient saving throw, a free-text weapon and
# armor proficiency, two granted features (one per class), one language,
# one sense, one movement mode, and a spellcasting profile with both
# known-only and prepared-only spells (proving the two associations are
# independent, per character.character_known_spells/_prepared_spells' own
# documented shape).
#
# Character B ("Fighter 1") exercises a legitimate *minimal* sheet: an
# active build with only three of six ability scores (so a skill/saving
# throw governed by an absent ability renders its documented "ability
# score missing" null-modifier state), one class level, and exactly one
# populated collection (movement) — every other build-owned and character-
# level collection (proficiencies, features, spellcasting, languages,
# senses) is deliberately left empty.
# ---------------------------------------------------------------------------

_BUILD_LABEL = "Phase13D Dev Build"

_CHARACTER_A_CLASS_CODE = "fighter"
_CHARACTER_A_CLASS_LEVEL = 2
_CHARACTER_A_SUBCLASS_CODE = "champion"
_CHARACTER_A_SECOND_CLASS_CODE = "wizard"
_CHARACTER_A_SECOND_CLASS_LEVEL = 1

_CHARACTER_A_ABILITY_SCORES = {
    "strength": 16,
    "dexterity": 13,
    "constitution": 14,
    "intelligence": 12,
    "wisdom": 10,
    "charisma": 8,
}
_CHARACTER_B_ABILITY_SCORES = {"strength": 12, "dexterity": 14, "constitution": 13}

_CHARACTER_A_PROFICIENT_SKILL_CODE = "athletics"
_CHARACTER_A_EXPERTISE_SKILL_CODE = "perception"
_CHARACTER_A_PROFICIENT_SAVING_THROW_CODE = "strength"
_CHARACTER_A_WEAPON_PROFICIENCY_LABEL = "Martial Weapons"
_CHARACTER_A_ARMOR_PROFICIENCY_LABEL = "Heavy Armor"

_CHARACTER_A_FEATURE_CODES = ("second_wind", "wizard_spellcasting")

_CHARACTER_A_LANGUAGE_CODE = "common"
_CHARACTER_A_SENSE_TYPE = "darkvision"
_CHARACTER_A_SENSE_RANGE_FEET = 60
_CHARACTER_A_MOVEMENT_TYPE = "walk"
_CHARACTER_A_MOVEMENT_SPEED_FEET = 30
_CHARACTER_B_MOVEMENT_TYPE = "walk"
_CHARACTER_B_MOVEMENT_SPEED_FEET = 30

_CHARACTER_A_SPELLCASTING_ABILITY_CODE = "intelligence"
_CHARACTER_A_KNOWN_SPELL_CODES = ("fire_bolt", "mage_hand", "magic_missile")
_CHARACTER_A_PREPARED_SPELL_CODES = ("magic_missile", "cure_wounds")


@dataclass(frozen=True)
class _UserInfo:
    user_id: uuid.UUID
    display_name: str
    login_name: str | None
    is_platform_administrator: bool


@dataclass
class _Summary:
    lines: list[str] = field(default_factory=list)

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


# ---------------------------------------------------------------------------
# Phase 13D Sheet-panel fixture: character builds and their ruleset-scoped
# content. Every rules.* id resolved below is looked up by code against the
# already-seeded dnd5e/2024 content (migration 022) — this fixture creates
# no rules.* rows of its own, matching this module's own "only reuses
# existing ruleset/rules content" convention (see _get_ruleset's docstring).
# ---------------------------------------------------------------------------


def _resolve_ruleset_code_id(
    connection: Connection, table: str, pk_column: str, *, ruleset_version_id: uuid.UUID, code: str
) -> uuid.UUID:
    """A pre-seeded rules.<table> row's id, resolved by code scoped to
    ruleset_version_id (code is unique only per ruleset version, not
    globally — the same scoping every other rules.* lookup in this script
    already applies)."""
    value = connection.execute(
        text(
            f"SELECT {pk_column} FROM rules.{table} "
            "WHERE ruleset_version_id = :ruleset_version AND code = :code"
        ),
        {"ruleset_version": ruleset_version_id, "code": code},
    ).scalar()
    if value is None:
        raise SystemExit(
            f"expected an existing rules.{table} row (code={code!r}) for ruleset version "
            f"{ruleset_version_id} — none found. Seed database/seeds/rules.{table}.yaml before "
            "running this fixture; this script only reuses existing rules content."
        )
    assert isinstance(value, uuid.UUID)
    return value


def _resolve_subclass_id(connection: Connection, *, class_id: uuid.UUID, code: str) -> uuid.UUID:
    """rules.subclasses.code is unique per class_id, not per ruleset
    version — scoped accordingly, unlike every other rules.* lookup here."""
    value = connection.execute(
        text(
            "SELECT subclass_id FROM rules.subclasses WHERE class_id = :class_id AND code = :code"
        ),
        {"class_id": class_id, "code": code},
    ).scalar()
    if value is None:
        raise SystemExit(
            f"expected an existing rules.subclasses row (code={code!r}) for class {class_id} — "
            "none found. Seed database/seeds/rules.subclasses.yaml before running this fixture."
        )
    assert isinstance(value, uuid.UUID)
    return value


def _ensure_character_build(
    connection: Connection,
    summary: _Summary,
    *,
    character_id: uuid.UUID,
    character_label: str,
    ruleset_version_id: uuid.UUID,
) -> uuid.UUID:
    """The fixture's one build per character, identified by its fixed
    _BUILD_LABEL (character_builds carries no other natural key)."""
    existing = connection.execute(
        text(
            "SELECT character_build_id FROM character.character_builds "
            "WHERE character_id = :character AND label = :label"
        ),
        {"character": character_id, "label": _BUILD_LABEL},
    ).scalar()
    label = f"build {_BUILD_LABEL!r}: {character_label}"
    if existing is not None:
        assert isinstance(existing, uuid.UUID)
        summary.add(created=False, label=label, record_id=existing)
        return existing

    build_id = connection.execute(
        text("""
            INSERT INTO character.character_builds (character_id, ruleset_version_id, label)
            VALUES (:character, :ruleset_version, :label)
            RETURNING character_build_id
        """),
        {"character": character_id, "ruleset_version": ruleset_version_id, "label": _BUILD_LABEL},
    ).scalar()
    assert isinstance(build_id, uuid.UUID)
    summary.add(created=True, label=label, record_id=build_id)
    return build_id


def _ensure_character_ability_score(
    connection: Connection,
    summary: _Summary,
    *,
    character_build_id: uuid.UUID,
    character_label: str,
    ability_id: uuid.UUID,
    ability_code: str,
    score: int,
) -> None:
    existing = connection.execute(
        text(
            "SELECT score FROM character.character_ability_scores "
            "WHERE character_build_id = :build AND ability_id = :ability"
        ),
        {"build": character_build_id, "ability": ability_id},
    ).scalar()
    label = f"ability score {ability_code!r} ({score}): {character_label}"
    if existing is None:
        connection.execute(
            text("""
                INSERT INTO character.character_ability_scores
                    (character_build_id, ability_id, score)
                VALUES (:build, :ability, :score)
            """),
            {"build": character_build_id, "ability": ability_id, "score": score},
        )
        summary.add(created=True, label=label, record_id=character_build_id)
        return
    if existing == score:
        summary.add(created=False, changed=False, label=label, record_id=character_build_id)
        return
    connection.execute(
        text("""
            UPDATE character.character_ability_scores SET score = :score, updated_at = now()
            WHERE character_build_id = :build AND ability_id = :ability
        """),
        {"build": character_build_id, "ability": ability_id, "score": score},
    )
    summary.add(created=False, changed=True, label=label, record_id=character_build_id)


def _ensure_character_class_level(
    connection: Connection,
    summary: _Summary,
    *,
    character_build_id: uuid.UUID,
    character_label: str,
    class_id: uuid.UUID,
    class_code: str,
    level: int,
    subclass_id: uuid.UUID | None = None,
) -> None:
    existing = (
        connection.execute(
            text("""
                SELECT level, subclass_id FROM character.character_class_levels
                WHERE character_build_id = :build AND class_id = :class_id
            """),
            {"build": character_build_id, "class_id": class_id},
        )
        .mappings()
        .one_or_none()
    )
    label = f"class level {class_code!r} {level}: {character_label}"
    if existing is None:
        connection.execute(
            text("""
                INSERT INTO character.character_class_levels
                    (character_build_id, class_id, level, subclass_id)
                VALUES (:build, :class_id, :level, :subclass_id)
            """),
            {
                "build": character_build_id,
                "class_id": class_id,
                "level": level,
                "subclass_id": subclass_id,
            },
        )
        summary.add(created=True, label=label, record_id=character_build_id)
        return
    if existing["level"] == level and existing["subclass_id"] == subclass_id:
        summary.add(created=False, changed=False, label=label, record_id=character_build_id)
        return
    connection.execute(
        text("""
            UPDATE character.character_class_levels
            SET level = :level, subclass_id = :subclass_id, updated_at = now()
            WHERE character_build_id = :build AND class_id = :class_id
        """),
        {
            "build": character_build_id,
            "class_id": class_id,
            "level": level,
            "subclass_id": subclass_id,
        },
    )
    summary.add(created=False, changed=True, label=label, record_id=character_build_id)


def _ensure_character_skill_proficiency(
    connection: Connection,
    summary: _Summary,
    *,
    character_build_id: uuid.UUID,
    character_label: str,
    proficiency_type_id: uuid.UUID,
    skill_id: uuid.UUID,
    skill_code: str,
    is_expertise: bool,
) -> None:
    existing = connection.execute(
        text(
            "SELECT is_expertise FROM character.character_proficiencies "
            "WHERE character_build_id = :build AND skill_id = :skill"
        ),
        {"build": character_build_id, "skill": skill_id},
    ).scalar()
    label = f"skill proficiency {skill_code!r} (expertise={is_expertise}): {character_label}"
    if existing is None:
        connection.execute(
            text("""
                INSERT INTO character.character_proficiencies
                    (character_build_id, proficiency_type_id, skill_id, is_expertise)
                VALUES (:build, :type, :skill, :expertise)
            """),
            {
                "build": character_build_id,
                "type": proficiency_type_id,
                "skill": skill_id,
                "expertise": is_expertise,
            },
        )
        summary.add(created=True, label=label, record_id=character_build_id)
        return
    if existing == is_expertise:
        summary.add(created=False, changed=False, label=label, record_id=character_build_id)
        return
    connection.execute(
        text(
            "UPDATE character.character_proficiencies SET is_expertise = :expertise "
            "WHERE character_build_id = :build AND skill_id = :skill"
        ),
        {"build": character_build_id, "skill": skill_id, "expertise": is_expertise},
    )
    summary.add(created=False, changed=True, label=label, record_id=character_build_id)


def _ensure_character_saving_throw_proficiency(
    connection: Connection,
    summary: _Summary,
    *,
    character_build_id: uuid.UUID,
    character_label: str,
    proficiency_type_id: uuid.UUID,
    ability_id: uuid.UUID,
    ability_code: str,
) -> None:
    existing = connection.execute(
        text(
            "SELECT 1 FROM character.character_proficiencies "
            "WHERE character_build_id = :build AND saving_throw_ability_id = :ability"
        ),
        {"build": character_build_id, "ability": ability_id},
    ).scalar()
    label = f"saving throw proficiency {ability_code!r}: {character_label}"
    if existing is not None:
        summary.add(created=False, label=label, record_id=character_build_id)
        return
    connection.execute(
        text("""
            INSERT INTO character.character_proficiencies
                (character_build_id, proficiency_type_id, saving_throw_ability_id)
            VALUES (:build, :type, :ability)
        """),
        {"build": character_build_id, "type": proficiency_type_id, "ability": ability_id},
    )
    summary.add(created=True, label=label, record_id=character_build_id)


def _ensure_character_free_text_proficiency(
    connection: Connection,
    summary: _Summary,
    *,
    character_build_id: uuid.UUID,
    character_label: str,
    proficiency_type_id: uuid.UUID,
    target_label: str,
) -> None:
    existing = connection.execute(
        text(
            "SELECT 1 FROM character.character_proficiencies "
            "WHERE character_build_id = :build AND target_label = :target_label"
        ),
        {"build": character_build_id, "target_label": target_label},
    ).scalar()
    label = f"proficiency {target_label!r}: {character_label}"
    if existing is not None:
        summary.add(created=False, label=label, record_id=character_build_id)
        return
    connection.execute(
        text("""
            INSERT INTO character.character_proficiencies
                (character_build_id, proficiency_type_id, target_label)
            VALUES (:build, :type, :target_label)
        """),
        {"build": character_build_id, "type": proficiency_type_id, "target_label": target_label},
    )
    summary.add(created=True, label=label, record_id=character_build_id)


def _ensure_character_feature(
    connection: Connection,
    summary: _Summary,
    *,
    character_build_id: uuid.UUID,
    character_label: str,
    feature_id: uuid.UUID,
    feature_code: str,
) -> None:
    existing = connection.execute(
        text(
            "SELECT 1 FROM character.character_features "
            "WHERE character_build_id = :build AND feature_id = :feature"
        ),
        {"build": character_build_id, "feature": feature_id},
    ).scalar()
    label = f"feature {feature_code!r}: {character_label}"
    if existing is not None:
        summary.add(created=False, label=label, record_id=character_build_id)
        return
    connection.execute(
        text("""
            INSERT INTO character.character_features (character_build_id, feature_id)
            VALUES (:build, :feature)
        """),
        {"build": character_build_id, "feature": feature_id},
    )
    summary.add(created=True, label=label, record_id=character_build_id)


def _ensure_character_spellcasting_profile(
    connection: Connection,
    summary: _Summary,
    *,
    character_build_id: uuid.UUID,
    character_label: str,
    class_id: uuid.UUID,
    spellcasting_ability_id: uuid.UUID,
) -> uuid.UUID:
    existing = connection.execute(
        text(
            "SELECT character_spellcasting_profile_id FROM character.character_spellcasting_profiles "
            "WHERE character_build_id = :build AND class_id = :class_id"
        ),
        {"build": character_build_id, "class_id": class_id},
    ).scalar()
    label = f"spellcasting profile: {character_label}"
    if existing is not None:
        assert isinstance(existing, uuid.UUID)
        summary.add(created=False, label=label, record_id=existing)
        return existing
    profile_id = connection.execute(
        text("""
            INSERT INTO character.character_spellcasting_profiles
                (character_build_id, class_id, spellcasting_ability_id)
            VALUES (:build, :class_id, :ability)
            RETURNING character_spellcasting_profile_id
        """),
        {"build": character_build_id, "class_id": class_id, "ability": spellcasting_ability_id},
    ).scalar()
    assert isinstance(profile_id, uuid.UUID)
    summary.add(created=True, label=label, record_id=profile_id)
    return profile_id


def _ensure_character_known_spell(
    connection: Connection,
    summary: _Summary,
    *,
    character_spellcasting_profile_id: uuid.UUID,
    character_label: str,
    spell_id: uuid.UUID,
    spell_code: str,
) -> None:
    existing = connection.execute(
        text(
            "SELECT 1 FROM character.character_known_spells "
            "WHERE character_spellcasting_profile_id = :profile AND spell_id = :spell"
        ),
        {"profile": character_spellcasting_profile_id, "spell": spell_id},
    ).scalar()
    label = f"known spell {spell_code!r}: {character_label}"
    if existing is not None:
        summary.add(created=False, label=label, record_id=character_spellcasting_profile_id)
        return
    connection.execute(
        text("""
            INSERT INTO character.character_known_spells
                (character_spellcasting_profile_id, spell_id)
            VALUES (:profile, :spell)
        """),
        {"profile": character_spellcasting_profile_id, "spell": spell_id},
    )
    summary.add(created=True, label=label, record_id=character_spellcasting_profile_id)


def _ensure_character_prepared_spell(
    connection: Connection,
    summary: _Summary,
    *,
    character_spellcasting_profile_id: uuid.UUID,
    character_label: str,
    spell_id: uuid.UUID,
    spell_code: str,
) -> None:
    existing = connection.execute(
        text(
            "SELECT 1 FROM character.character_prepared_spells "
            "WHERE character_spellcasting_profile_id = :profile AND spell_id = :spell"
        ),
        {"profile": character_spellcasting_profile_id, "spell": spell_id},
    ).scalar()
    label = f"prepared spell {spell_code!r}: {character_label}"
    if existing is not None:
        summary.add(created=False, label=label, record_id=character_spellcasting_profile_id)
        return
    connection.execute(
        text("""
            INSERT INTO character.character_prepared_spells
                (character_spellcasting_profile_id, spell_id)
            VALUES (:profile, :spell)
        """),
        {"profile": character_spellcasting_profile_id, "spell": spell_id},
    )
    summary.add(created=True, label=label, record_id=character_spellcasting_profile_id)


def _ensure_character_language(
    connection: Connection,
    summary: _Summary,
    *,
    character_id: uuid.UUID,
    character_label: str,
    language_id: uuid.UUID,
    language_code: str,
) -> None:
    """character.character_languages is character-level, not build-owned —
    keyed by character_id alone, matching dnd_ai.queries.character_sheet's
    own documented distinction."""
    existing = connection.execute(
        text(
            "SELECT 1 FROM character.character_languages "
            "WHERE character_id = :character AND language_id = :language"
        ),
        {"character": character_id, "language": language_id},
    ).scalar()
    label = f"language {language_code!r}: {character_label}"
    if existing is not None:
        summary.add(created=False, label=label, record_id=character_id)
        return
    connection.execute(
        text(
            "INSERT INTO character.character_languages (character_id, language_id) "
            "VALUES (:character, :language)"
        ),
        {"character": character_id, "language": language_id},
    )
    summary.add(created=True, label=label, record_id=character_id)


def _ensure_character_sense(
    connection: Connection,
    summary: _Summary,
    *,
    character_id: uuid.UUID,
    character_label: str,
    sense_type: str,
    range_feet: int,
) -> None:
    """character.character_senses is character-level, not build-owned."""
    existing = connection.execute(
        text(
            "SELECT range_feet FROM character.character_senses "
            "WHERE character_id = :character AND sense_type = :sense_type"
        ),
        {"character": character_id, "sense_type": sense_type},
    ).scalar()
    label = f"sense {sense_type!r} ({range_feet} ft): {character_label}"
    if existing is None:
        connection.execute(
            text(
                "INSERT INTO character.character_senses (character_id, sense_type, range_feet) "
                "VALUES (:character, :sense_type, :range_feet)"
            ),
            {"character": character_id, "sense_type": sense_type, "range_feet": range_feet},
        )
        summary.add(created=True, label=label, record_id=character_id)
        return
    if existing == range_feet:
        summary.add(created=False, changed=False, label=label, record_id=character_id)
        return
    connection.execute(
        text(
            "UPDATE character.character_senses SET range_feet = :range_feet "
            "WHERE character_id = :character AND sense_type = :sense_type"
        ),
        {"character": character_id, "sense_type": sense_type, "range_feet": range_feet},
    )
    summary.add(created=False, changed=True, label=label, record_id=character_id)


def _ensure_character_movement(
    connection: Connection,
    summary: _Summary,
    *,
    character_id: uuid.UUID,
    character_label: str,
    movement_type: str,
    speed_feet: int,
) -> None:
    """character.character_movements is character-level, not build-owned."""
    existing = connection.execute(
        text(
            "SELECT speed_feet FROM character.character_movements "
            "WHERE character_id = :character AND movement_type = :movement_type"
        ),
        {"character": character_id, "movement_type": movement_type},
    ).scalar()
    label = f"movement {movement_type!r} ({speed_feet} ft): {character_label}"
    if existing is None:
        connection.execute(
            text(
                "INSERT INTO character.character_movements "
                "(character_id, movement_type, speed_feet) "
                "VALUES (:character, :movement_type, :speed_feet)"
            ),
            {"character": character_id, "movement_type": movement_type, "speed_feet": speed_feet},
        )
        summary.add(created=True, label=label, record_id=character_id)
        return
    if existing == speed_feet:
        summary.add(created=False, changed=False, label=label, record_id=character_id)
        return
    connection.execute(
        text(
            "UPDATE character.character_movements SET speed_feet = :speed_feet "
            "WHERE character_id = :character AND movement_type = :movement_type"
        ),
        {"character": character_id, "movement_type": movement_type, "speed_feet": speed_feet},
    )
    summary.add(created=False, changed=True, label=label, record_id=character_id)


def _ensure_active_build_selection(
    connection: Connection,
    summary: _Summary,
    *,
    timeline_id: uuid.UUID,
    character_id: uuid.UUID,
    character_label: str,
    character_build_id: uuid.UUID,
) -> None:
    """Selects character_build_id as the active build for character_id on
    timeline_id — campaign.character_state.character_build_id is the sole
    active-build resolution rule (dnd_ai.queries.character_sheet's own
    docstring); this fixture's own campaign.character_state row already
    exists by the time this runs (_ensure_character_state, above)."""
    existing = connection.execute(
        text(
            "SELECT character_build_id FROM campaign.character_state "
            "WHERE timeline_id = :timeline AND character_id = :character"
        ),
        {"timeline": timeline_id, "character": character_id},
    ).scalar()
    label = f"active build selection: {character_label}"
    if existing == character_build_id:
        summary.add(created=False, changed=False, label=label, record_id=character_id)
        return
    # existing is NULL the first time this fixture runs (_ensure_character_
    # state never sets character_build_id) — selecting a build for the
    # first time is this row's "creation" from the fixture's point of view,
    # not a reconciliation of a previously-wrong value.
    was_unset = existing is None
    connection.execute(
        text("""
            UPDATE campaign.character_state SET character_build_id = :build, updated_at = now()
            WHERE timeline_id = :timeline AND character_id = :character
        """),
        {"timeline": timeline_id, "character": character_id, "build": character_build_id},
    )
    summary.add(created=was_unset, changed=not was_unset, label=label, record_id=character_id)


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
    _get_or_create_campaign(
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

    _ensure_character_sheet_fixture(
        connection,
        summary,
        ruleset_version_id=ruleset_version_id,
        timeline_id=timeline_a_id,
        character_a_id=character_a_id,
        character_b_id=character_b_id,
    )

    return summary


def _ensure_character_sheet_fixture(
    connection: Connection,
    summary: _Summary,
    *,
    ruleset_version_id: uuid.UUID,
    timeline_id: uuid.UUID,
    character_a_id: uuid.UUID,
    character_b_id: uuid.UUID,
) -> None:
    """Phase 13D character Sheet-panel live-verification data — see this
    module's own constants block above ("Phase 13D Sheet-panel fixture")
    for what each character ends up exercising and why."""
    ability_ids = {
        code: _resolve_ruleset_code_id(
            connection, "abilities", "ability_id", ruleset_version_id=ruleset_version_id, code=code
        )
        for code in {
            *_CHARACTER_A_ABILITY_SCORES,
            *_CHARACTER_B_ABILITY_SCORES,
        }
    }

    # --- Character A: populated build ---------------------------------
    build_a_id = _ensure_character_build(
        connection,
        summary,
        character_id=character_a_id,
        character_label=_CHARACTER_A_NAME,
        ruleset_version_id=ruleset_version_id,
    )
    for ability_code, score in _CHARACTER_A_ABILITY_SCORES.items():
        _ensure_character_ability_score(
            connection,
            summary,
            character_build_id=build_a_id,
            character_label=_CHARACTER_A_NAME,
            ability_id=ability_ids[ability_code],
            ability_code=ability_code,
            score=score,
        )

    fighter_class_id = _resolve_ruleset_code_id(
        connection,
        "classes",
        "class_id",
        ruleset_version_id=ruleset_version_id,
        code=_CHARACTER_A_CLASS_CODE,
    )
    champion_subclass_id = _resolve_subclass_id(
        connection, class_id=fighter_class_id, code=_CHARACTER_A_SUBCLASS_CODE
    )
    wizard_class_id = _resolve_ruleset_code_id(
        connection,
        "classes",
        "class_id",
        ruleset_version_id=ruleset_version_id,
        code=_CHARACTER_A_SECOND_CLASS_CODE,
    )
    _ensure_character_class_level(
        connection,
        summary,
        character_build_id=build_a_id,
        character_label=_CHARACTER_A_NAME,
        class_id=fighter_class_id,
        class_code=_CHARACTER_A_CLASS_CODE,
        level=_CHARACTER_A_CLASS_LEVEL,
        subclass_id=champion_subclass_id,
    )
    _ensure_character_class_level(
        connection,
        summary,
        character_build_id=build_a_id,
        character_label=_CHARACTER_A_NAME,
        class_id=wizard_class_id,
        class_code=_CHARACTER_A_SECOND_CLASS_CODE,
        level=_CHARACTER_A_SECOND_CLASS_LEVEL,
    )

    skill_proficiency_type_id = _resolve_ruleset_code_id(
        connection,
        "proficiency_types",
        "proficiency_type_id",
        ruleset_version_id=ruleset_version_id,
        code="skill",
    )
    saving_throw_proficiency_type_id = _resolve_ruleset_code_id(
        connection,
        "proficiency_types",
        "proficiency_type_id",
        ruleset_version_id=ruleset_version_id,
        code="saving_throw",
    )
    weapon_proficiency_type_id = _resolve_ruleset_code_id(
        connection,
        "proficiency_types",
        "proficiency_type_id",
        ruleset_version_id=ruleset_version_id,
        code="weapon",
    )
    armor_proficiency_type_id = _resolve_ruleset_code_id(
        connection,
        "proficiency_types",
        "proficiency_type_id",
        ruleset_version_id=ruleset_version_id,
        code="armor",
    )

    proficient_skill_id = _resolve_ruleset_code_id(
        connection,
        "skills",
        "skill_id",
        ruleset_version_id=ruleset_version_id,
        code=_CHARACTER_A_PROFICIENT_SKILL_CODE,
    )
    _ensure_character_skill_proficiency(
        connection,
        summary,
        character_build_id=build_a_id,
        character_label=_CHARACTER_A_NAME,
        proficiency_type_id=skill_proficiency_type_id,
        skill_id=proficient_skill_id,
        skill_code=_CHARACTER_A_PROFICIENT_SKILL_CODE,
        is_expertise=False,
    )
    expertise_skill_id = _resolve_ruleset_code_id(
        connection,
        "skills",
        "skill_id",
        ruleset_version_id=ruleset_version_id,
        code=_CHARACTER_A_EXPERTISE_SKILL_CODE,
    )
    _ensure_character_skill_proficiency(
        connection,
        summary,
        character_build_id=build_a_id,
        character_label=_CHARACTER_A_NAME,
        proficiency_type_id=skill_proficiency_type_id,
        skill_id=expertise_skill_id,
        skill_code=_CHARACTER_A_EXPERTISE_SKILL_CODE,
        is_expertise=True,
    )
    _ensure_character_saving_throw_proficiency(
        connection,
        summary,
        character_build_id=build_a_id,
        character_label=_CHARACTER_A_NAME,
        proficiency_type_id=saving_throw_proficiency_type_id,
        ability_id=ability_ids[_CHARACTER_A_PROFICIENT_SAVING_THROW_CODE],
        ability_code=_CHARACTER_A_PROFICIENT_SAVING_THROW_CODE,
    )
    _ensure_character_free_text_proficiency(
        connection,
        summary,
        character_build_id=build_a_id,
        character_label=_CHARACTER_A_NAME,
        proficiency_type_id=weapon_proficiency_type_id,
        target_label=_CHARACTER_A_WEAPON_PROFICIENCY_LABEL,
    )
    _ensure_character_free_text_proficiency(
        connection,
        summary,
        character_build_id=build_a_id,
        character_label=_CHARACTER_A_NAME,
        proficiency_type_id=armor_proficiency_type_id,
        target_label=_CHARACTER_A_ARMOR_PROFICIENCY_LABEL,
    )

    for feature_code in _CHARACTER_A_FEATURE_CODES:
        feature_id = _resolve_ruleset_code_id(
            connection,
            "features",
            "feature_id",
            ruleset_version_id=ruleset_version_id,
            code=feature_code,
        )
        _ensure_character_feature(
            connection,
            summary,
            character_build_id=build_a_id,
            character_label=_CHARACTER_A_NAME,
            feature_id=feature_id,
            feature_code=feature_code,
        )

    profile_id = _ensure_character_spellcasting_profile(
        connection,
        summary,
        character_build_id=build_a_id,
        character_label=_CHARACTER_A_NAME,
        class_id=wizard_class_id,
        spellcasting_ability_id=ability_ids[_CHARACTER_A_SPELLCASTING_ABILITY_CODE],
    )
    for spell_code in _CHARACTER_A_KNOWN_SPELL_CODES:
        spell_id = _resolve_ruleset_code_id(
            connection,
            "spells",
            "spell_id",
            ruleset_version_id=ruleset_version_id,
            code=spell_code,
        )
        _ensure_character_known_spell(
            connection,
            summary,
            character_spellcasting_profile_id=profile_id,
            character_label=_CHARACTER_A_NAME,
            spell_id=spell_id,
            spell_code=spell_code,
        )
    for spell_code in _CHARACTER_A_PREPARED_SPELL_CODES:
        spell_id = _resolve_ruleset_code_id(
            connection,
            "spells",
            "spell_id",
            ruleset_version_id=ruleset_version_id,
            code=spell_code,
        )
        _ensure_character_prepared_spell(
            connection,
            summary,
            character_spellcasting_profile_id=profile_id,
            character_label=_CHARACTER_A_NAME,
            spell_id=spell_id,
            spell_code=spell_code,
        )

    language_id = _resolve_ruleset_code_id(
        connection,
        "languages",
        "language_id",
        ruleset_version_id=ruleset_version_id,
        code=_CHARACTER_A_LANGUAGE_CODE,
    )
    _ensure_character_language(
        connection,
        summary,
        character_id=character_a_id,
        character_label=_CHARACTER_A_NAME,
        language_id=language_id,
        language_code=_CHARACTER_A_LANGUAGE_CODE,
    )
    _ensure_character_sense(
        connection,
        summary,
        character_id=character_a_id,
        character_label=_CHARACTER_A_NAME,
        sense_type=_CHARACTER_A_SENSE_TYPE,
        range_feet=_CHARACTER_A_SENSE_RANGE_FEET,
    )
    _ensure_character_movement(
        connection,
        summary,
        character_id=character_a_id,
        character_label=_CHARACTER_A_NAME,
        movement_type=_CHARACTER_A_MOVEMENT_TYPE,
        speed_feet=_CHARACTER_A_MOVEMENT_SPEED_FEET,
    )
    _ensure_active_build_selection(
        connection,
        summary,
        timeline_id=timeline_id,
        character_id=character_a_id,
        character_label=_CHARACTER_A_NAME,
        character_build_id=build_a_id,
    )

    # --- Character B: legitimate minimal build -------------------------
    build_b_id = _ensure_character_build(
        connection,
        summary,
        character_id=character_b_id,
        character_label=_CHARACTER_B_NAME,
        ruleset_version_id=ruleset_version_id,
    )
    for ability_code, score in _CHARACTER_B_ABILITY_SCORES.items():
        _ensure_character_ability_score(
            connection,
            summary,
            character_build_id=build_b_id,
            character_label=_CHARACTER_B_NAME,
            ability_id=ability_ids[ability_code],
            ability_code=ability_code,
            score=score,
        )
    _ensure_character_class_level(
        connection,
        summary,
        character_build_id=build_b_id,
        character_label=_CHARACTER_B_NAME,
        class_id=fighter_class_id,
        class_code=_CHARACTER_A_CLASS_CODE,
        level=1,
    )
    # Deliberately no proficiencies, features, or spellcasting profile for
    # Character B — see this module's constants-block comment above for
    # why that is a legitimate minimal state, not an oversight.
    _ensure_character_movement(
        connection,
        summary,
        character_id=character_b_id,
        character_label=_CHARACTER_B_NAME,
        movement_type=_CHARACTER_B_MOVEMENT_TYPE,
        speed_feet=_CHARACTER_B_MOVEMENT_SPEED_FEET,
    )
    _ensure_active_build_selection(
        connection,
        summary,
        timeline_id=timeline_id,
        character_id=character_b_id,
        character_label=_CHARACTER_B_NAME,
        character_build_id=build_b_id,
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
