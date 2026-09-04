"""Phase 13C portal live-verification development dataset.

Creates the smallest dataset the portal's Phase 13C checkpoints (campaign
selection, campaign-context refresh, character-perspective selection) need
to be exercised by hand against a real, self-hosted/local PostgreSQL
database: one development world, two timelines, two active campaigns (one
per timeline), one already-existing local account authorized on both
campaigns, and two characters selectable as that account's perspective in
the first campaign.

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
class _UserInfo:
    user_id: uuid.UUID
    display_name: str
    login_name: str | None
    is_platform_administrator: bool


@dataclass
class _Summary:
    lines: list[str] = field(default_factory=list)

    def add(self, *, created: bool, label: str, record_id: uuid.UUID | str) -> None:
        verb = "created" if created else "reused (already existed)"
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
