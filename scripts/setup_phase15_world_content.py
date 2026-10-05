"""Phase 15.1 development world content, authored through the production commands.

Adds a small, realistic body of GM-authored world content to the existing
Phase 13C development world so the Phase 15.1 portal authoring screens have
something to browse and edit:

- locations: a published region -> settlement -> building hierarchy, a draft
  district, an archived geographic feature, and a superseded location with its
  replacement;
- organizations: a published government headquartered in the settlement, a draft
  guild beneath it, and a published religion with its religious organization;
- NPCs: a published NPC originating in the settlement and a draft NPC;
- quests: a published two-stage quest with three objectives, and a draft quest;
- knowledge: a published rumor about the NPC and a draft secret.

Every record is created and moved through its lifecycle with the same commands
the HTTP routes use (`dnd_ai.commands.*`), with the same audit rows, so the data
exercises the real invariants. Nothing is inserted with raw SQL.

**It adds content only.** It requires the Phase 13C world and campaign
(`scripts/setup_phase13c_dev_data.py`) and an existing local account that holds
`canon.edit` there (every campaign owner does). It creates no world, timeline,
campaign, user, or membership and never changes a membership.

**Idempotent.** Each record is found by its `[P15 dev]` name in the world and
reused; lifecycle steps are applied only while the record is behind the target
status. A second run reports every record as reused and writes nothing.

**Safe by default.** Without `--apply` the whole run executes and is rolled back.
Like the Phase 13C fixture it refuses a production environment, a non-loopback
database host, or a production-looking database name (override only a known-safe
host with `DND_AI_ALLOW_NONLOCAL_DEV_DATA=1`).

Usage (from the repository root):

    uv run python scripts/setup_phase15_world_content.py --user-id <uuid>          # preview
    uv run python scripts/setup_phase15_world_content.py --user-id <uuid> --apply  # write
"""

import argparse
import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import cast

from setup_phase13c_dev_data import (
    _CAMPAIGN_A_NAME,
    _database_url,
    _find_world,
    _require_local_target,
    _require_non_production,
    _resolve_user,
    _safe_target_summary,
)
from sqlalchemy import Connection, create_engine, text

from dnd_ai.api._content_support import audit_content_write
from dnd_ai.api.audit import record_change_log
from dnd_ai.commands._content import ContentWriteResult
from dnd_ai.commands.entity_lifecycle import (
    EntityTransitionResult,
    approve_entity,
    archive_entity,
    publish_entity_as_canon,
    submit_entity_for_review,
    supersede_entity,
)
from dnd_ai.commands.knowledge_definitions import create_knowledge_item
from dnd_ai.commands.locations import create_location
from dnd_ai.commands.npcs import create_npc
from dnd_ai.commands.organizations import create_organization
from dnd_ai.commands.quest_definitions import add_quest_objective, add_quest_stage, create_quest
from dnd_ai.commands.religions import create_religion
from dnd_ai.config import settings
from dnd_ai.domain.access import AccessContext
from dnd_ai.domain.authoring import CampaignNotAuthorizedError
from dnd_ai.domain.knowledge_authoring import statement_to_name
from dnd_ai.queries.npc_authoring import list_species_options

_COMMAND_PREFIX = "scripts.setup_phase15_world_content"
_PREFIX = "[P15 dev] "


@dataclass
class _Summary:
    lines: list[str] = field(default_factory=list)
    report: list[str] = field(default_factory=list)

    def add(self, *, created: bool, label: str, step: str | None = None) -> None:
        verb = "created" if created else "reused (already existed)"
        suffix = f" -> {step}" if step else ""
        self.lines.append(f"  [{verb}] {label}{suffix}")


@dataclass
class _Ctx:
    connection: Connection
    summary: _Summary
    campaign_id: uuid.UUID
    world_id: uuid.UUID
    user_id: uuid.UUID
    # The audit helper only reads `user_id`; the script has no request, so a
    # one-attribute stand-in replaces the resolved `AccessContext`.
    access: AccessContext


@dataclass(frozen=True)
class _Record:
    entity_id: uuid.UUID
    created: bool


def _find_campaign(connection: Connection, world_id: uuid.UUID) -> uuid.UUID:
    rows = (
        connection.execute(
            text("""
                SELECT c.campaign_id
                FROM campaign.campaigns c
                JOIN campaign.timelines t ON t.timeline_id = c.timeline_id
                WHERE t.world_id = :w AND c.name = :name
            """),
            {"w": world_id, "name": _CAMPAIGN_A_NAME},
        )
        .scalars()
        .all()
    )
    if len(rows) != 1:
        raise SystemExit(
            f"Expected exactly one campaign named {_CAMPAIGN_A_NAME!r} in the Phase 13C world; "
            f"found {len(rows)}. Run scripts/setup_phase13c_dev_data.py first."
        )
    return cast(uuid.UUID, rows[0])


def _find(ctx: _Ctx, type_code: str, name: str) -> uuid.UUID | None:
    rows = (
        ctx.connection.execute(
            text("""
                SELECT e.entity_id FROM core.entities e
                JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id
                WHERE e.world_id = :w AND et.code = :t AND e.canonical_name = :n
                ORDER BY e.entity_id
            """),
            {"w": ctx.world_id, "t": type_code, "n": name},
        )
        .scalars()
        .all()
    )
    if len(rows) > 1:
        raise SystemExit(f"{len(rows)} {type_code} records are named {name!r}; refusing to guess.")
    return cast(uuid.UUID, rows[0]) if rows else None


def _state(ctx: _Ctx, entity_id: uuid.UUID) -> tuple[str, str, int]:
    row = ctx.connection.execute(
        text("""
            SELECT cs.code AS canon, ls.code AS lifecycle, e.row_version
            FROM core.entities e
            JOIN core.canon_statuses cs ON cs.canon_status_id = e.canon_status_id
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = e.lifecycle_status_id
            WHERE e.entity_id = :e
        """),
        {"e": entity_id},
    ).one()
    return str(row.canon), str(row.lifecycle), int(row.row_version)


def _audit_create(ctx: _Ctx, result: ContentWriteResult, command: str) -> None:
    audit_content_write(
        ctx.connection,
        result=result,
        command_name=command,
        access=ctx.access,
        correlation_id=None,
        reason=None,
    )


def _audit_transition(
    ctx: _Ctx, result: EntityTransitionResult, command: str, *, lifecycle_action: str | None = None
) -> None:
    record_change_log(
        ctx.connection,
        change_action_code=lifecycle_action or "status_changed",
        schema_name="core",
        table_name="entities",
        record_id=result.entity_id,
        entity_id=result.entity_id,
        world_id=result.world_id,
        actor_user_id=ctx.user_id,
        correlation_id=None,
        command_name=command,
        event_id=None,
        previous_status=(
            result.previous_lifecycle_status if lifecycle_action else result.previous_canon_status
        ),
        new_status=result.lifecycle_status if lifecycle_action else result.canon_status,
        changed_fields=result.changed_fields or None,
        reason=None,
    )


def _publish(ctx: _Ctx, entity_id: uuid.UUID) -> str | None:
    """draft -> proposed -> approved -> canon, only the steps still ahead."""
    canon, lifecycle, _ = _state(ctx, entity_id)
    if lifecycle != "active" or canon not in ("draft", "proposed", "approved"):
        return None
    steps = {
        "draft": [submit_entity_for_review, approve_entity, publish_entity_as_canon],
        "proposed": [approve_entity, publish_entity_as_canon],
        "approved": [publish_entity_as_canon],
    }[canon]
    for command in steps:
        _, _, version = _state(ctx, entity_id)
        result = command(
            ctx.connection,
            campaign_id=ctx.campaign_id,
            entity_id=entity_id,
            actor_user_id=ctx.user_id,
            expected_row_version=version,
        )
        _audit_transition(ctx, result, command.__name__)
    return "published"


def _archive(ctx: _Ctx, entity_id: uuid.UUID) -> str | None:
    _, lifecycle, version = _state(ctx, entity_id)
    if lifecycle != "active":
        return None
    result = archive_entity(
        ctx.connection,
        campaign_id=ctx.campaign_id,
        entity_id=entity_id,
        actor_user_id=ctx.user_id,
        expected_row_version=version,
        reason="Phase 15 development data",
    )
    _audit_transition(ctx, result, "archive_entity", lifecycle_action="archived")
    return "archived"


def _supersede(ctx: _Ctx, old: uuid.UUID, replacement: uuid.UUID) -> str | None:
    canon, lifecycle, version = _state(ctx, old)
    if canon == "superseded" or lifecycle != "active":
        return None
    _, _, replacement_version = _state(ctx, replacement)
    result = supersede_entity(
        ctx.connection,
        campaign_id=ctx.campaign_id,
        entity_id=old,
        actor_user_id=ctx.user_id,
        expected_row_version=version,
        replacement_entity_id=replacement,
        replacement_expected_row_version=replacement_version,
    )
    _audit_transition(ctx, result, "supersede_entity")
    if result.replacement is not None:
        _audit_transition(ctx, result.replacement, "supersede_entity")
    return "superseded"


def _ensure(
    ctx: _Ctx,
    *,
    type_code: str,
    name: str,
    label: str,
    command: str,
    create: Callable[[], ContentWriteResult],
    target: str,
    portal_path: str | None = None,
) -> _Record:
    """Find the record by name or create it with `create()`, then move it to
    `target` (`draft`, `published`, or `archived`; an archived record is
    published first)."""
    entity_id = _find(ctx, type_code, name)
    created = entity_id is None
    if entity_id is None:
        result = create()
        _audit_create(ctx, result, command)
        entity_id = result.entity_id
    steps: list[str] = []
    if target in ("published", "archived"):
        step = _publish(ctx, entity_id)
        if step:
            steps.append(step)
    if target == "archived":
        step = _archive(ctx, entity_id)
        if step:
            steps.append(step)
    ctx.summary.add(created=created, label=label, step=", ".join(steps) or None)
    if portal_path:
        # Names and route shapes only: record ids are not meant to be read or typed.
        ctx.summary.report.append(f"  {label}: {portal_path.format(c='<campaign>', id='<id>')}")
    return _Record(entity_id, created)


def _run(connection: Connection, *, user_id: uuid.UUID) -> _Summary:
    summary = _Summary()
    user = _resolve_user(connection, user_id)
    print(
        f"Target account: user_id={user.user_id} display_name={user.display_name!r} "
        f"login_name={user.login_name!r}"
    )
    world_id = _find_world(connection)
    if world_id is None:
        raise SystemExit(
            "The Phase 13C development world does not exist. Run "
            "scripts/setup_phase13c_dev_data.py first; this script only adds content."
        )
    campaign_id = _find_campaign(connection, world_id)
    ctx = _Ctx(
        connection=connection,
        summary=summary,
        campaign_id=campaign_id,
        world_id=world_id,
        user_id=user.user_id,
        access=cast(AccessContext, SimpleNamespace(user_id=user.user_id)),
    )
    try:
        _author(ctx)
    except CampaignNotAuthorizedError as exc:
        raise SystemExit(
            f"--user-id {user_id} does not hold canon.edit on {_CAMPAIGN_A_NAME!r}; "
            "use the world's owner account."
        ) from exc
    return summary


def _author(ctx: _Ctx) -> None:
    c, u = ctx.campaign_id, ctx.user_id
    conn = ctx.connection
    world = "/app/{c}/world"

    def loc(
        name: str, category: str, parent: uuid.UUID | None = None
    ) -> Callable[[], ContentWriteResult]:
        return lambda: create_location(
            conn,
            campaign_id=c,
            actor_user_id=u,
            category_code=category,
            name=_PREFIX + name,
            summary=f"{name} (development data).",
            parent_location_id=parent,
        )

    def place(name: str, category: str, target: str, parent: uuid.UUID | None = None) -> _Record:
        return _ensure(
            ctx,
            type_code=category,
            name=_PREFIX + name,
            label=f"{category} {_PREFIX + name!r}",
            command="create_location",
            create=loc(name, category, parent),
            target=target,
            portal_path=world + "/location/{id}",
        )

    region = place("Ashmark", "region", "published")
    settlement = place("Brindlehaven", "settlement", "published", region.entity_id)
    building = place("Customs House", "building", "published", settlement.entity_id)
    place("Harbor District", "district", "draft", settlement.entity_id)
    place("Sunken Reef", "geographic_feature", "archived", region.entity_id)
    old_keep = place("Old Keep", "building", "published", settlement.entity_id)
    new_keep = place("New Keep", "building", "published", settlement.entity_id)
    ctx.summary.add(
        created=_supersede(ctx, old_keep.entity_id, new_keep.entity_id) is not None,
        label="supersession 'Old Keep' -> 'New Keep'",
    )

    government = _ensure(
        ctx,
        type_code="government",
        name=_PREFIX + "Brindlehaven Council",
        label="government 'Brindlehaven Council'",
        command="create_organization",
        create=lambda: create_organization(
            conn,
            campaign_id=c,
            actor_user_id=u,
            kind_code="government",
            name=_PREFIX + "Brindlehaven Council",
            summary="The town's ruling council.",
            headquarters_location_id=settlement.entity_id,
        ),
        target="published",
        portal_path=world + "/organization/{id}",
    )
    _ensure(
        ctx,
        type_code="organization",
        name=_PREFIX + "Dockhands Guild",
        label="guild 'Dockhands Guild'",
        command="create_organization",
        create=lambda: create_organization(
            conn,
            campaign_id=c,
            actor_user_id=u,
            kind_code="organization",
            name=_PREFIX + "Dockhands Guild",
            summary="Dock workers, not yet approved.",
            parent_organization_id=government.entity_id,
            typed_fields={"organization_type": "guild"},
        ),
        target="draft",
        portal_path=world + "/organization/{id}",
    )
    religion = _ensure(
        ctx,
        type_code="religion",
        name=_PREFIX + "The Tidewardens",
        label="religion 'The Tidewardens'",
        command="create_religion",
        create=lambda: create_religion(
            conn,
            campaign_id=c,
            actor_user_id=u,
            name=_PREFIX + "The Tidewardens",
            summary="Sailors' faith.",
            pantheon_structure="Three tide spirits",
        ),
        target="published",
        portal_path=world + "/religion/{id}",
    )
    _ensure(
        ctx,
        type_code="religious_organization",
        name=_PREFIX + "Tidewarden Chapter",
        label="religious organization 'Tidewarden Chapter'",
        command="create_organization",
        create=lambda: create_organization(
            conn,
            campaign_id=c,
            actor_user_id=u,
            kind_code="religious_organization",
            name=_PREFIX + "Tidewarden Chapter",
            summary="The local chapter.",
            religion_id=religion.entity_id,
            headquarters_location_id=building.entity_id,
        ),
        target="published",
        portal_path=world + "/organization/{id}",
    )

    species = next(
        (s for s in list_species_options(conn, world_id=ctx.world_id) if s.name.lower() == "human"),
        None,
    )
    if species is None:
        raise SystemExit("The world's ruleset offers no canon 'Human' species for the NPCs.")

    def npc(name: str, target: str, origin: uuid.UUID | None) -> _Record:
        return _ensure(
            ctx,
            type_code="npc",
            name=_PREFIX + name,
            label=f"NPC {_PREFIX + name!r}",
            command="create_npc",
            create=lambda: create_npc(
                conn,
                campaign_id=c,
                actor_user_id=u,
                name=_PREFIX + name,
                summary=f"{name}, a development NPC.",
                species_id=species.species_id,
                size_category="medium",
                origin_location_id=origin,
                background="Written by the Phase 15 development script.",
                notes="GM-only note.",
            ),
            target=target,
            portal_path=world + "/character/{id}",
        )

    harbormaster = npc("Harbormaster Lysa", "published", settlement.entity_id)
    npc("Stowaway Pell", "draft", None)

    quest = _ensure(
        ctx,
        type_code="quest",
        name=_PREFIX + "The Missing Manifest",
        label="quest 'The Missing Manifest'",
        command="create_quest",
        create=lambda: create_quest(
            conn,
            campaign_id=c,
            actor_user_id=u,
            name=_PREFIX + "The Missing Manifest",
            summary="A ship's manifest has vanished.",
        ),
        target="draft",
        portal_path="/app/{c}/quests/{id}/edit",
    )
    if quest.created:
        _add_quest_structure(ctx, quest.entity_id, settlement.entity_id, harbormaster.entity_id)
    else:
        ctx.summary.add(created=False, label="quest structure: 2 stages, 3 objectives")
    ctx.summary.add(
        created=_publish(ctx, quest.entity_id) is not None,
        label="quest 'The Missing Manifest'",
        step="published",
    )
    _ensure(
        ctx,
        type_code="quest",
        name=_PREFIX + "Whispers on the Quay",
        label="quest 'Whispers on the Quay'",
        command="create_quest",
        create=lambda: create_quest(
            conn,
            campaign_id=c,
            actor_user_id=u,
            name=_PREFIX + "Whispers on the Quay",
            summary="An unfinished quest idea.",
        ),
        target="draft",
        portal_path="/app/{c}/quests/{id}/edit",
    )

    def claim(
        statement: str,
        kind: str,
        truth: str,
        sensitivity: str,
        subject: uuid.UUID | None,
        target: str,
    ) -> None:
        _ensure(
            ctx,
            type_code="knowledge_item",
            name=statement_to_name(_PREFIX + statement),
            label=f"{kind} {_PREFIX + statement!r}",
            command="create_knowledge_item",
            create=lambda: create_knowledge_item(
                conn,
                campaign_id=c,
                actor_user_id=u,
                statement=_PREFIX + statement,
                knowledge_type=kind,
                truth_status=truth,
                sensitivity=sensitivity,
                subject_entity_id=subject,
            ),
            target=target,
            portal_path="/app/{c}/knowledge/{id}",
        )

    claim(
        "The harbormaster takes bribes.",
        "rumor",
        "partially_true",
        "restricted",
        harbormaster.entity_id,
        "published",
    )
    claim("The customs ledger was burned.", "secret", "true", "secret", None, "draft")


def _add_quest_structure(
    ctx: _Ctx, quest_id: uuid.UUID, settlement_id: uuid.UUID, npc_id: uuid.UUID
) -> None:
    """Two stages and three objectives, written in order so each command sees the
    version the previous one left."""
    c, u, conn = ctx.campaign_id, ctx.user_id, ctx.connection

    def stage(name: str) -> uuid.UUID:
        _, _, version = _state(ctx, quest_id)
        result = add_quest_stage(
            conn,
            campaign_id=c,
            quest_id=quest_id,
            actor_user_id=u,
            expected_row_version=version,
            name=name,
            description=None,
            stage_type="sequential",
        )
        _audit_create(ctx, result, "add_quest_stage")
        assert result.record_id is not None
        return result.record_id

    def objective(stage_id: uuid.UUID, name: str, target: uuid.UUID | None) -> None:
        _, _, version = _state(ctx, quest_id)
        result = add_quest_objective(
            conn,
            campaign_id=c,
            quest_id=quest_id,
            quest_stage_id=stage_id,
            actor_user_id=u,
            expected_row_version=version,
            name=name,
            description=None,
            objective_type="other",
            requirement_level="required",
            completion_mode="automatic",
            visibility_policy="visible",
            quantity_required=None,
            target_entity_id=target,
        )
        _audit_create(ctx, result, "add_quest_objective")

    first = stage("Find the trail")
    objective(first, "Question the harbormaster", npc_id)
    objective(first, "Search the settlement", settlement_id)
    second = stage("Recover the manifest")
    objective(second, "Return the manifest", None)
    ctx.summary.add(created=True, label="quest structure: 2 stages, 3 objectives")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--user-id",
        required=True,
        type=uuid.UUID,
        help="Existing, active, local account that owns the Phase 13C world (holds canon.edit).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write changes. Without this flag the same sequence runs and is rolled back.",
    )
    args = parser.parse_args(argv)

    _require_non_production()
    _require_local_target()
    print(
        f"environment={settings.environment} "
        f"mode={'APPLY' if args.apply else 'PREVIEW (no writes committed)'}"
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
        print("\n-- Phase 15 content quick reference (portal paths; open in the campaign) --")
        print("\n".join(summary.report))
    if args.apply:
        print("\nAPPLIED - changes committed.")
    else:
        print("\nPREVIEW ONLY - every change above was rolled back. Re-run with --apply to write.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
