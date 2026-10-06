"""One-time privacy remediation: scrub narrative stored in audit and replay rows

Revision ID: 135_scrub_narrative_text
Revises: 134_entity_source_links
Create Date: 2026-10-07 14:00:00.000000

*** IRREVERSIBLE DATA CHANGE. Take a fresh backup immediately before running `upgrade`. ***

Purpose:
    Phase 15 checkpoint 15.2A-4, decisions D-2 and D-28, decided in writing by the owner
    (in the working session): scrub existing audit narrative (`changed_fields` prose; the `reason` note is
    kept) and rewrite existing idempotency response bodies to receipts, with a marker on every
    modified row and one bounded maintenance audit row.

    Before checkpoint 15.2A-3 the typed authoring commands copied up to 1,000 characters of
    narrative per field into `audit.change_log.changed_fields`, and the authoring routes stored
    the full authoring view (including GM-only notes) in `security.idempotent_requests`. New
    writes no longer do either: audit is default-deny and replay storage keeps only a minimal
    receipt (`dnd_ai.domain.data_classification.replay_body`). This revision remediates the
    rows already stored.

What it changes (and only this):
    1. `audit.change_log.changed_fields` of rows whose `command_name` is in the frozen list
       below: every prose key's value becomes `{"redacted": true}` (for the update shape,
       `{"from": ..., "to": ...}` with each side redacted; a `null` side stays `null`), and the
       row's `changed_fields` gains `"_redacted_by": "<this revision id>"`. A row whose prose
       values are already redacted is not touched and not counted.
    2. `security.idempotent_requests.response_body` of completed rows whose body has the shape
       of an authoring view (the frozen predicate below): rewritten to the receipt shape (ids,
       flags, numbers and short closed codes; `created` is derived from the stored status code
       when the view had none), with the same `"_redacted_by"` marker. `request_fingerprint`,
       key, status code, actor and timestamps are unchanged, so a replay still matches and now
       returns the receipt.
    3. One maintenance row in `audit.change_log` (`actor_service = 'migration'`) records the
       revision id, the count of modified rows per command name, the count of rewritten replay
       rows, and the time.

Never touched:
    `change_log_id`, action, schema, table and record ids, entity and world ids, actor columns,
    `command_name`, correlation and causation ids, event id, `previous_status`, `new_status`,
    `reason`, `recorded_at`, and every non-prose key and value of `changed_fields`.

Preconditions (checked inside the transaction before any UPDATE; any failure raises and changes
nothing):
    every candidate audit row's `changed_fields` is an object whose keys are all in the frozen
    known-key list for its command, and every prose value is a string, the bounded
    `{"value", "truncated"}` shape, the update shape of those, or already redacted; every
    candidate replay row has an object body with at least one UUID-valued `*_id` key. The frozen
    lists in this file are the contract; nothing is inferred from the current registry.

Rollback:
    Not possible. `downgrade()` removes nothing and restores nothing; scrubbed values cannot be
    recovered from the database. Backups taken before this revision still hold the narrative until
    they are retired under the backup-retention policy in ADR 0016.

Data implications:
    Rewrites only rows matching the frozen lists. Development and test databases behave
    identically; take a dump first if the old values are wanted.

Locking considerations:
    Row updates in two tables inside one transaction; the maintenance row is one insert. The
    candidate sets are small (authoring commands only).
"""

import json
import logging
import re
import uuid
from typing import Any

from alembic import op
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = "135_scrub_narrative_text"
down_revision = "134_entity_source_links"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")

REDACTED = {"redacted": True}
MARKER_KEY = "_redacted_by"
MAINTENANCE_COMMAND = "scrub_pre_15_2a_3_narrative"

# The non-narrative audit keys as of checkpoint 15.2A-3 (a frozen copy; never read from code).
STRUCTURAL_KEYS = frozenset(
    {
        "name",
        "category",
        "kind",
        "population",
        "size_category",
        "species_id",
        "origin_location_id",
        "parent_location_id",
        "parent_organization_id",
        "headquarters_location_id",
        "religion_id",
        "subject_entity_id",
        "target_entity_id",
        "knowledge_type",
        "sensitivity",
        "truth_status",
        "completion_mode",
        "objective_type",
        "requirement_level",
        "sequence_number",
        "stage_type",
        "quantity_required",
        "visibility_policy",
        "objectives_removed",
        "organization_type",
        "operating_status",
        "reputation",
        "superseded_by_entity_id",
    }
)

_ORGANIZATION_PROSE = frozenset(
    {
        "summary",
        "internal_description",
        "public_description",
        "business_type",
        "government_form",
        "unit_type",
        "ideology",
    }
)

# command name -> the keys of its audit `changed_fields` that held narrative before 15.2A-3.
AUDIT_PROSE_KEYS: dict[str, frozenset[str]] = {
    "create_location": frozenset({"summary", "building_use"}),
    "update_location": frozenset({"summary", "building_use"}),
    "create_npc": frozenset({"summary", "background", "appearance", "notes"}),
    "update_npc": frozenset({"summary", "background", "appearance", "notes"}),
    "create_organization": _ORGANIZATION_PROSE,
    "update_organization": _ORGANIZATION_PROSE,
    "create_religion": frozenset({"summary", "pantheon_structure"}),
    "update_religion": frozenset({"summary", "pantheon_structure"}),
    "create_quest": frozenset({"summary"}),
    "update_quest": frozenset({"summary"}),
    "add_quest_stage": frozenset({"summary", "description"}),
    "update_quest_stage": frozenset({"summary", "description"}),
    "add_quest_objective": frozenset({"summary", "description"}),
    "update_quest_objective": frozenset({"summary", "description"}),
    "create_knowledge_item": frozenset({"statement"}),
    "update_knowledge_item": frozenset({"statement"}),
    "update_world": frozenset({"description"}),
    "update_timeline": frozenset({"description"}),
    "update_campaign": frozenset({"description"}),
}

# An authoring view stored for replay is recognised by its shape: any one of these key sets.
REPLAY_VIEW_SHAPES: tuple[frozenset[str], ...] = (
    frozenset({"available_actions"}),
    frozenset({"field_labels"}),
    frozenset({"origin_notes"}),
    frozenset({"is_homebrew"}),
    frozenset({"source_type", "reference"}),
    frozenset({"origin", "links"}),
    frozenset({"rounds", "participants"}),
)

_REPLAY_CODE_KEYS = frozenset(
    {
        "status",
        "previous_status",
        "new_status",
        "previous_status_code",
        "new_status_code",
        "status_code",
        "canon_status",
        "lifecycle_status",
        "operation",
        "action",
        "kind",
        "side",
        "detail_level",
        "entity_type_code",
    }
)
_REPLAY_CODE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")

_CLEAN = "clean"
_SCRUB = "scrub"


class UnexpectedShape(Exception):
    """A candidate row does not look like what the frozen lists describe."""


def _is_uuid(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


def _is_bounded(value: object) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == {"value", "truncated"}
        and isinstance(value["value"], str)
        and value["truncated"] is True
    )


def _is_text(value: object) -> bool:
    return isinstance(value, str) or _is_bounded(value)


def _is_safe_scalar(value: object) -> bool:
    return (
        value is None
        or value == REDACTED
        or isinstance(value, bool | int | float)
        or _is_uuid(value)
    )


def _is_safe_value(value: object) -> bool:
    if isinstance(value, dict) and set(value) == {"from", "to"}:
        return _is_safe_scalar(value["from"]) and _is_safe_scalar(value["to"])
    return _is_safe_scalar(value)


def _redact_side(value: object) -> Any:
    return None if value is None else dict(REDACTED)


def _scrub_prose_value(value: object) -> tuple[str, Any]:
    """`(state, replacement)` for one prose value; raises `UnexpectedShape` for anything else."""
    if value == REDACTED:
        return _CLEAN, value
    if _is_text(value):
        return _SCRUB, dict(REDACTED)
    if isinstance(value, dict) and set(value) == {"from", "to"}:
        sides = (value["from"], value["to"])
        if not all(s is None or s == REDACTED or _is_text(s) for s in sides):
            raise UnexpectedShape(f"unexpected update shape {value!r}")
        if all(s is None or s == REDACTED for s in sides):
            return _CLEAN, value
        return _SCRUB, {"from": _redact_side(value["from"]), "to": _redact_side(value["to"])}
    raise UnexpectedShape(f"unexpected prose value of type {type(value).__name__}")


def plan_audit_row(command: str, changed_fields: object) -> dict[str, Any] | None:
    """The new `changed_fields` for one audit row, or `None` when nothing needs scrubbing."""
    if changed_fields is None:  # a JSON null holds nothing to scrub
        return None
    if not isinstance(changed_fields, dict):
        raise UnexpectedShape("changed_fields is not an object")
    prose = AUDIT_PROSE_KEYS[command]
    known = STRUCTURAL_KEYS | prose
    for key in set(changed_fields) - known - {MARKER_KEY}:
        # A key added after 15.2A-3 (the redacting builder wrote it) is accepted only when its
        # value is already safe: redacted, null, a number, a boolean, or an id.
        if not _is_safe_value(changed_fields[key]):
            raise UnexpectedShape(f"unexpected key {key!r} holding a value that may be narrative")
    updated = dict(changed_fields)
    scrubbed = False
    for key in prose & set(changed_fields):
        state, replacement = _scrub_prose_value(changed_fields[key])
        if state == _SCRUB:
            updated[key] = replacement
            scrubbed = True
    if not scrubbed:
        return None
    updated[MARKER_KEY] = revision
    return updated


def _replay_receipt(body: dict[str, Any]) -> dict[str, Any]:
    kept: dict[str, Any] = {}
    for key, value in body.items():
        if value is None or isinstance(value, bool | int | float):
            kept[key] = value
        elif isinstance(value, str):
            if (key.endswith("_id") and _is_uuid(value)) or (
                key in _REPLAY_CODE_KEYS and _REPLAY_CODE.match(value)
            ):
                kept[key] = value
        elif isinstance(value, list) and all(_is_uuid(item) for item in value):
            kept[key] = list(value)
    return kept


def plan_replay_row(status_code: int, body: object) -> dict[str, Any] | None:
    """The receipt that replaces one replay body, or `None` when the row is not an authoring view."""
    if not isinstance(body, dict) or MARKER_KEY in body:
        return None
    if not any(shape <= set(body) for shape in REPLAY_VIEW_SHAPES):
        return None
    receipt = _replay_receipt(body)
    if not any(k.endswith("_id") and _is_uuid(v) for k, v in receipt.items()):
        raise UnexpectedShape("an authoring view with no id to build a receipt from")
    if "created" not in receipt:
        receipt["created"] = status_code == 201
    if "changed" not in receipt:
        receipt["changed"] = True
    receipt[MARKER_KEY] = revision
    return receipt


def upgrade() -> None:
    bind = op.get_bind()

    # --- 1. Plan everything first; any unexpected shape raises before any UPDATE. -----------
    audit_updates: list[tuple[int, dict[str, Any]]] = []
    per_command: dict[str, int] = {}
    problems: list[str] = []
    audit_rows = bind.execute(
        text(
            "SELECT change_log_id, command_name, changed_fields FROM audit.change_log "
            "WHERE command_name = ANY(:commands) AND changed_fields IS NOT NULL "
            "ORDER BY change_log_id"
        ),
        {"commands": sorted(AUDIT_PROSE_KEYS)},
    ).all()
    for row in audit_rows:
        try:
            new = plan_audit_row(row.command_name, row.changed_fields)
        except UnexpectedShape as exc:
            problems.append(f"audit.change_log {row.change_log_id} ({row.command_name}): {exc}")
            continue
        if new is not None:
            audit_updates.append((int(row.change_log_id), new))
            per_command[row.command_name] = per_command.get(row.command_name, 0) + 1

    replay_updates: list[tuple[uuid.UUID, dict[str, Any]]] = []
    replay_rows = bind.execute(
        text(
            "SELECT idempotent_request_id, response_status_code, response_body "
            "FROM security.idempotent_requests "
            "WHERE response_body IS NOT NULL AND response_status_code IN (200, 201) "
            "ORDER BY created_at, idempotent_request_id"
        )
    ).all()
    for row in replay_rows:
        try:
            receipt = plan_replay_row(int(row.response_status_code), row.response_body)
        except UnexpectedShape as exc:
            problems.append(f"security.idempotent_requests {row.idempotent_request_id}: {exc}")
            continue
        if receipt is not None:
            replay_updates.append((row.idempotent_request_id, receipt))

    if problems:
        shown = "; ".join(problems[:10])
        raise RuntimeError(
            f"{revision}: {len(problems)} candidate row(s) have an unexpected shape and nothing "
            f"was changed. First: {shown}"
        )

    # --- 2. Apply. -----------------------------------------------------------------------------
    for change_log_id, new_fields in audit_updates:
        bind.execute(
            text(
                "UPDATE audit.change_log SET changed_fields = CAST(:fields AS jsonb) "
                "WHERE change_log_id = :id"
            ),
            {"fields": json.dumps(new_fields), "id": change_log_id},
        )
    for request_id, receipt in replay_updates:
        bind.execute(
            text(
                "UPDATE security.idempotent_requests "
                "SET response_body = CAST(:body AS jsonb) WHERE idempotent_request_id = :id"
            ),
            {"body": json.dumps(receipt), "id": request_id},
        )

    # --- 3. The one bounded maintenance record. ---------------------------------------------
    bind.execute(
        text("""
            INSERT INTO audit.change_log
                (change_action_id, schema_name, table_name, actor_service, command_name,
                 changed_fields)
            VALUES (
                (SELECT change_action_id FROM audit.change_actions WHERE code = 'updated'),
                'audit', 'change_log', 'migration', :command,
                CAST(:fields AS jsonb)
            )
        """),
        {
            "command": MAINTENANCE_COMMAND,
            "fields": json.dumps(
                {
                    "revision": revision,
                    "audit_rows_modified": dict(sorted(per_command.items())),
                    "audit_rows_modified_total": len(audit_updates),
                    "replay_rows_rewritten": len(replay_updates),
                }
            ),
        },
    )
    logger.info(
        "%s: scrubbed %d audit row(s) %s and rewrote %d replay row(s). Take a fresh backup now "
        "and retire older ones under the backup-retention policy (ADR 0016).",
        revision,
        len(audit_updates),
        dict(sorted(per_command.items())),
        len(replay_updates),
    )


def downgrade() -> None:
    logger.warning(
        "%s: downgrade removes nothing and restores nothing; scrubbed values cannot be "
        "recovered from the database. Restore a pre-scrub backup if they are needed.",
        revision,
    )
