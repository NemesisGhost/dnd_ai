"""Helpers shared across command handlers."""

import uuid

from sqlalchemy import Connection, text

from dnd_ai.domain.errors import DomainAuthorizationError


class LookupCodeNotFoundError(ValueError):
    """Raised when a command references a lookup-table code that doesn't exist."""


def lookup_id(
    connection: Connection, schema: str, table: str, pk_column: str, code: str
) -> uuid.UUID:
    """Resolve a lookup table's stable `code` to its surrogate id.

    Every lookup table in this schema follows the shape in
    docs/DATABASE_CONVENTIONS.md §11: a `code` column with a unique
    constraint. Commands reference codes (readable, stable across
    environments) rather than hardcoding ids. schema/table/pk_column are
    always internal literals supplied by other command code, never
    user-controlled, so the interpolated SQL identifiers are safe.
    """
    value = connection.execute(
        text(f"SELECT {pk_column} FROM {schema}.{table} WHERE code = :code"),
        {"code": code},
    ).scalar()
    if value is None:
        raise LookupCodeNotFoundError(f"{schema}.{table} has no row with code = {code!r}")
    assert isinstance(value, uuid.UUID)
    return value


class SessionNotInCampaignError(DomainAuthorizationError):
    """Raised by `_validate_session_campaign()` when a supplied `session_id`
    does not resolve to a `campaign.sessions` row belonging exactly to the
    supplied `campaign_id` — including a nonexistent session and a session
    that belongs to a different (even same-world) campaign. `campaign_id=
    None` with a `session_id` supplied is also rejected: a session always
    belongs to exactly one campaign (`campaign.sessions.campaign_id NOT
    NULL`), so "no campaign at all" can never be the campaign a real session
    belongs to — the same rule `narrative.enforce_event_consistency()`
    (revision 057), `interaction.enforce_interaction_consistency()`
    (revision 061), and `narrative.enforce_encounter_world()` (revision 081)
    already apply at the database layer.

    Originally `dnd_ai.commands.encounters.SessionNotInCampaignError`
    (`start_encounter`/`resolve_combat_turn`/`end_encounter`); moved here
    once `dnd_ai.commands.items` needed the identical check for
    `transfer_item_possession`/`identify_item` — encounters.py re-exports
    this name for backward compatibility with existing imports/tests.

    Inherits `DomainAuthorizationError`'s fixed 404 contract deliberately:
    confirming that a session exists but belongs to a different campaign
    would itself disclose cross-campaign information to a caller who is
    only authorized for the campaign named in the request
    (docs/architecture/DATABASE_MODEL.md §19.7). The supplied campaign_id/
    session_id are included only in the constructor's `detail` argument
    (`str(self)`), never in `safe_message` — see `SafeMessageError`'s own
    contract for why that distinction matters."""


def validate_session_campaign(
    connection: Connection, *, campaign_id: uuid.UUID | None, session_id: uuid.UUID | None
) -> None:
    """Rejects a caller-supplied session_id that does not belong exactly to
    campaign_id, before anything is inserted or updated.

    campaign_id here must always be the *authoritative* campaign for the row
    about to be created/mutated, not merely an asserted one — see each
    caller's own docstring (e.g. `dnd_ai.commands.encounters.
    _start_encounter_impl` vs. `_resolve_combat_turn_impl`/
    `_end_encounter_impl`, which pass the just-locked row's actual
    campaign_id rather than their own possibly-unscoped campaign_id
    argument) for why that distinction matters for their specific case.

    Without this, a caller-supplied session_id could reference a
    campaign.sessions row belonging to a same-world but different campaign
    than the caller is authorized for (or acting on behalf of), since a
    normal foreign key only proves the session exists, never that it
    belongs to the given campaign — a durable cross-campaign session
    linkage the API's own campaign-scoped authorization
    (dnd_ai.api.access.require_campaign_capability) never catches, since
    campaign_id itself is trusted (from the URL path, already authorized,
    or from a row already locked/owned) while session_id is ordinary
    caller-supplied request data."""
    if session_id is None:
        return

    session_campaign_id = connection.execute(
        text("SELECT campaign_id FROM campaign.sessions WHERE session_id = :session"),
        {"session": session_id},
    ).scalar()

    if session_campaign_id is None or campaign_id is None or session_campaign_id != campaign_id:
        raise SessionNotInCampaignError(
            f"session {session_id} does not belong to campaign {campaign_id!r} "
            f"(session's actual campaign: {session_campaign_id!r})"
        )
