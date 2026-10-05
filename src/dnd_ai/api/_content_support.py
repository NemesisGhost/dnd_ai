"""Plumbing shared by the typed content-authoring routers (Phase 15.1).

The three things every `/campaigns/{id}/authoring/<type>` router repeats and
must do identically: one audit row per real change, decoding a name-keyset
cursor for an option list, and rendering a reference-option page. Each router
keeps its own request models, commands, and read models -- this module holds no
domain behavior.
"""

import uuid
from collections.abc import Callable, Sequence
from typing import Any

from sqlalchemy import Connection

from dnd_ai.commands._content import ContentWriteResult
from dnd_ai.domain.access import AccessContext
from dnd_ai.domain.data_classification import content_receipt
from dnd_ai.queries.reference_options import ReferenceOptionRow

from .audit import record_change_log
from .errors import InvalidCursorError
from .pagination import build_page, decode_typed_cursor


def audit_content_write(
    connection: Connection,
    *,
    result: ContentWriteResult,
    command_name: str,
    access: AccessContext,
    correlation_id: str | None,
    reason: str | None,
) -> None:
    """One `audit.change_log` row for a real change: `created` with the bounded
    initial values and the provenance source, or `updated` with the bounded
    `{field: {from, to}}` diff. Attributed to the authenticated human; the
    command name is a fixed literal. A caller writes nothing for a no-op or a
    replay."""
    record_change_log(
        connection,
        change_action_code=result.action or ("created" if result.created else "updated"),
        schema_name=result.record_schema,
        table_name=result.record_table,
        record_id=result.record_id or result.entity_id,
        entity_id=result.entity_id,
        world_id=result.world_id,
        actor_user_id=access.user_id,
        correlation_id=correlation_id,
        command_name=command_name,
        event_id=None,
        changed_fields=result.changed_fields or None,
        reason=reason,
        source_id=result.source_id,
    )


def write_receipt(result: ContentWriteResult, id_field: str, *, changed: bool) -> dict[str, Any]:
    """The response and idempotency replay body of a typed authoring write: ids,
    `row_version`, and flags only (never content). The portal refetches the
    authoritative view after a write."""
    return content_receipt(
        id_field=id_field,
        entity_id=result.entity_id,
        row_version=result.row_version,
        created=result.created,
        changed=changed,
        record_id=result.record_id,
    )


def clean_note(note: str | None) -> str | None:
    return note.strip() if note and note.strip() else None


def decode_name_cursor(cursor: str | None, keyset: str) -> tuple[str, uuid.UUID] | None:
    decoded = decode_typed_cursor(cursor, keyset=keyset, fields=["str", "uuid"])
    if decoded is None:
        return None
    name, entity_id = decoded
    if not isinstance(name, str) or not isinstance(entity_id, uuid.UUID):
        raise InvalidCursorError()
    return name, entity_id


def reference_options_page(
    rows: Sequence[ReferenceOptionRow],
    *,
    limit: int,
    keyset: str,
    item: Callable[[ReferenceOptionRow], dict[str, Any]],
) -> dict[str, Any]:
    page = build_page(
        list(rows), limit=limit, keyset=keyset, cursor_key=lambda r: (r.name_sort, r.entity_id)
    )
    return {"items": [item(r) for r in page.items], "next_cursor": page.next_cursor}
