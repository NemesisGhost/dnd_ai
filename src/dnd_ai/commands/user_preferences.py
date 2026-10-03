"""User portal preference commands (docs/UI_DESIGN.md §4.7; table
`security.user_portal_preferences`, revision 109).

Two narrowly scoped, idempotent set operations on the caller's own row:

- `set_campaign_startup_preference` — the "Always open this campaign" choice
  (`None` clears it, meaning "Resume my last visited campaign");
- `record_last_visited_campaign` — the campaign the caller most recently
  entered.

Each command writes only its own column (upsert on `user_id`), so a
last-visited write never clobbers the startup choice and vice versa.

A non-null campaign ID is stored only after re-verifying that the caller
currently has an active membership in that active campaign —
`dnd_ai.queries.bootstrap.is_campaign_bootstrap_authorized`, the same scope
the session bootstrap lists. Unknown, unauthorized, archived, and
ended-membership campaigns raise the identical `CampaignNotAvailableError`
(HTTP 404), so a caller cannot probe for campaign existence. Stored IDs never
grant access: readers re-filter them against current membership.

These are presentation-state writes, not canon, typed state, or permission
data, so they deliberately write no `audit.change_log` or security-audit
row and take no `Idempotency-Key` (`security.idempotent_requests` requires a
`campaign_id` and targets non-idempotent commands; set semantics make a
repeat a no-op). Callers compose these on the request's connection — one
transaction per request, like `change_password`.
"""

import uuid

from sqlalchemy import Connection, text

from dnd_ai.domain.errors import DomainAuthorizationError
from dnd_ai.queries.bootstrap import is_campaign_bootstrap_authorized


class CampaignNotAvailableError(DomainAuthorizationError):
    """The campaign is unknown or not currently accessible to the caller.
    One fixed, non-disclosing 404 for every such case."""


def _require_authorized(
    connection: Connection, *, user_id: uuid.UUID, campaign_id: uuid.UUID
) -> None:
    if not is_campaign_bootstrap_authorized(connection, user_id=user_id, campaign_id=campaign_id):
        raise CampaignNotAvailableError(f"campaign {campaign_id} is not available to {user_id}")


def set_campaign_startup_preference(
    connection: Connection, *, user_id: uuid.UUID, preferred_campaign_id: uuid.UUID | None
) -> None:
    """Store (or, with `None`, clear) the "Always open this campaign" choice."""
    if preferred_campaign_id is not None:
        _require_authorized(connection, user_id=user_id, campaign_id=preferred_campaign_id)
    connection.execute(
        text("""
            INSERT INTO security.user_portal_preferences (user_id, preferred_campaign_id)
            VALUES (:user_id, :campaign_id)
            ON CONFLICT (user_id) DO UPDATE
            SET preferred_campaign_id = EXCLUDED.preferred_campaign_id
        """),
        {"user_id": user_id, "campaign_id": preferred_campaign_id},
    )


def record_last_visited_campaign(
    connection: Connection, *, user_id: uuid.UUID, campaign_id: uuid.UUID
) -> None:
    """Record `campaign_id` as the caller's last-visited campaign."""
    _require_authorized(connection, user_id=user_id, campaign_id=campaign_id)
    connection.execute(
        text("""
            INSERT INTO security.user_portal_preferences (user_id, last_visited_campaign_id)
            VALUES (:user_id, :campaign_id)
            ON CONFLICT (user_id) DO UPDATE
            SET last_visited_campaign_id = EXCLUDED.last_visited_campaign_id
        """),
        {"user_id": user_id, "campaign_id": campaign_id},
    )
