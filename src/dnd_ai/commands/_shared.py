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


class PartyNotInCampaignError(DomainAuthorizationError):
    """Raised by `validate_campaign_party()` when a supplied `party_id` does
    not resolve to a `campaign.campaign_parties` row belonging exactly to
    the supplied `campaign_id` — including a nonexistent party and a party
    associated only with a different (even same-world) campaign.
    `campaign_id=None` with a `party_id` supplied is also rejected: "no
    campaign at all" can never be the campaign a real party is associated
    with, mirroring `SessionNotInCampaignError`'s identical rule for
    `session_id`.

    Originally `dnd_ai.commands.quests.PartyNotInCampaignError` — that
    module's own docstring reasoned it should stay local "unlike
    SessionNotInCampaignError/validate_session_campaign, which moved [here]
    once a *second* command needed the identical session/campaign check...
    no other command needs this check yet." `dnd_ai.queries.dungeon` is that
    second caller: a party-scoped query filters hidden dungeon content by
    the party's own `knowledge.party_discoveries` rows, and
    `knowledge.party_discoveries` is scoped by `timeline_id` alone — a
    caller-supplied `party_id` belonging to a *different* campaign on the
    same timeline would otherwise leak that other party's discoveries, the
    same class of gap this check already closed for quest-objective
    advancement. `dnd_ai.commands.quests` re-exports both names unchanged
    for backward compatibility with existing imports.

    Inherits `DomainAuthorizationError`'s fixed 404 contract deliberately:
    confirming that a party exists but belongs to a different campaign
    would itself disclose cross-campaign information to a caller only
    authorized for the campaign named in the request
    (docs/architecture/DATABASE_MODEL.md §19.7). The supplied campaign_id/
    party_id are included only in the constructor's `detail` argument
    (`str(self)`), never in `safe_message`."""


def validate_campaign_party(
    connection: Connection, *, campaign_id: uuid.UUID | None, party_id: uuid.UUID | None
) -> None:
    """Rejects a caller-supplied party_id that is not actually associated
    with campaign_id, before anything is inserted, updated, or read.
    Mirrors `validate_session_campaign`'s shape exactly — see
    `PartyNotInCampaignError`'s docstring for why
    `campaign.campaign_parties`' world-agreement trigger alone isn't
    sufficient here.

    `campaign_id = NULL`/`party_id = NULL` comparisons in the query below
    never match (SQL NULL semantics), so a `campaign_id=None` caller with a
    `party_id` supplied is rejected the same way a mismatched campaign
    would be — no separate `is None` branch is needed."""
    if party_id is None:
        return

    exists = connection.execute(
        text(
            "SELECT 1 FROM campaign.campaign_parties "
            "WHERE campaign_id = :campaign AND party_id = :party"
        ),
        {"campaign": campaign_id, "party": party_id},
    ).scalar()

    if exists is None:
        raise PartyNotInCampaignError(
            f"party {party_id} is not associated with campaign {campaign_id!r}"
        )
