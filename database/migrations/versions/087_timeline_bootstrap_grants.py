"""Add security.timeline_bootstrap_grants

Revision ID: 087_timeline_bootstrap_grants
Revises: 086_system_role_capabilities
Create Date: 2026-08-17 09:00:00.000000

Purpose:
    Fixes a second Critical privilege-escalation defect in `dnd_ai.
    commands.campaigns.create_campaign`, discovered immediately after
    workstream 30 closed the first one (docs/PLAN.md's own workstream 32
    entry has the full narrative). Workstream 30's `_authorize_timeline_
    reuse()` correctly gated *reuse* of a timeline an existing campaign
    already uses (requiring `access.manage` there), but treated "no
    campaign currently references this timeline" as sufficient
    authorization on its own for the *first* campaign. That is not an
    entitlement — worlds, timelines, dungeon content, characters, lore,
    and knowledge can all be authored before their first campaign exists
    (the vertical-slice scenario's own step ordering depends on exactly
    this), so any authenticated user who merely obtained such a
    `timeline_id` — by guessing, by log exposure, by a shared link, or any
    other route — could claim it, become `campaign_owner` (`campaign.
    view`/`canon.edit`/`access.manage`, migration 085), and read or mutate
    the entire pre-authored world.

    This migration adds the missing positive, server-verifiable
    entitlement: a single-use, directly-targeted grant issued by trusted
    world-authoring/import infrastructure (today: `tests/factories.py`,
    the same trust boundary every other pre-campaign content helper in
    this codebase already has; later: import tooling) to one specific
    `(timeline_id, granted_to_user_id)` pair. `dnd_ai.commands.campaigns.
    grant_timeline_bootstrap()` is the one function that writes this
    table — never exposed over HTTP, the same "no authoring endpoint
    exists yet" scope boundary every other piece of pre-campaign content
    in this codebase already has (docs/PLAN.md §25's own "Keep the
    endpoint surface limited to what that scenario needs").

    Deliberately *not* a bearer token (unlike `security.
    campaign_invitations`, its closest sibling): `granted_to_user_id`
    binds the grant to a specific, already-known `security.users` row
    directly, rather than a secret string an unknown recipient redeems.
    world-authoring infrastructure always knows which user it is
    bootstrapping a timeline for (there is no "invite an unknown email"
    case here, unlike a campaign invitation) — binding by user id removes
    an entire class of leakage (a copied/logged/shared token) that a
    secret-string design would otherwise need to defend, directly
    satisfying "do not use UUID secrecy... as authorization."

Forward migration:
    `security.timeline_bootstrap_grants`:
      - `timeline_bootstrap_grant_id UUID PK`
      - `timeline_id UUID NOT NULL REFERENCES campaign.timelines(timeline_id)
        ON DELETE CASCADE` — the entitled timeline
      - `granted_to_user_id UUID NOT NULL REFERENCES security.users(user_id)
        ON DELETE CASCADE` — the one user this grant authorizes; never a
        token, see above
      - `granted_by_user_id UUID REFERENCES security.users(user_id)
        ON DELETE SET NULL` — nullable provenance: the human who issued
        this grant, or NULL for a system/import-job-issued one (no human
        actor to attribute it to, the same "administrative source"
        concept CLAUDE.md rule 6 already accepts for event-less state
        changes)
      - `expires_at TIMESTAMPTZ NOT NULL` — mirrors `security.
        campaign_invitations.expires_at`'s identical shape
      - `revoked_at TIMESTAMPTZ` — checked by the authorization query;
        no dedicated revoke command exists yet, the identical scope gap
        `security.campaign_invitations.revoked_at` already has (that
        table's own `revoked_at` is checked by `accept_campaign_invitation`
        but has no command that sets it either) — trusted infrastructure
        may set it directly today, exactly as it does to grant one
      - `consumed_at TIMESTAMPTZ` / `consumed_by_campaign_id UUID
        REFERENCES campaign.campaigns(campaign_id) ON DELETE RESTRICT` —
        set together, atomically, by `create_campaign` itself once the
        campaign the grant authorized has actually been created (never by
        a separate "redeem" step, unlike `accept_campaign_invitation`'s
        two-phase create-then-accept shape — there is exactly one thing a
        timeline bootstrap grant is ever redeemed for). `ON DELETE
        RESTRICT`, not `SET NULL`: `ck_timeline_bootstrap_grants_
        consumed_pairing` (below) requires `consumed_at` and `consumed_
        by_campaign_id` to be `NULL` or non-`NULL` *together* — a `SET
        NULL` cascade from a deleted `campaign.campaigns` row would null
        out `consumed_by_campaign_id` alone, leaving `consumed_at` still
        set and violating that very constraint the moment the cascade
        ran. No command in this codebase deletes a `campaign.campaigns`
        row at all (CLAUDE.md rule 9's archive-don't-delete discipline,
        and `docs/architecture/DATABASE_MODEL.md`'s campaign lifecycle,
        both treat a campaign as permanent once created), so `RESTRICT`
        costs nothing in practice — it only turns a schema-level
        contradiction that would otherwise silently corrupt this table's
        own invariant into an explicit, loud failure if that assumption
        is ever violated.
      - `ck_timeline_bootstrap_grants_consumed_pairing`: `consumed_at` and
        `consumed_by_campaign_id` are NULL or non-NULL together
      - `ux_timeline_bootstrap_grants_active`: a partial unique index on
        `(timeline_id, granted_to_user_id)` `WHERE consumed_at IS NULL AND
        revoked_at IS NULL`, preventing duplicate live grants for the same
        pair — mirroring `ux_campaign_memberships_open`'s identical
        "only one open row" idiom; also the supporting index for the
        `timeline_id` foreign key (conventions §19.1's "a leading-column
        match counts")
      - `ix_timeline_bootstrap_grants_consumed_by_campaign_id`: partial,
        `WHERE consumed_by_campaign_id IS NOT NULL` — the `consumed_by_
        campaign_id` foreign key's own supporting index
      - `ix_timeline_bootstrap_grants_granted_to_user_id`: the
        `granted_to_user_id` foreign key's own supporting index — needed
        despite that column also appearing in `ux_timeline_bootstrap_
        grants_active` above, since it is that index's *second* column,
        not its leading one
      - `ix_timeline_bootstrap_grants_granted_by_user_id`: partial,
        `WHERE granted_by_user_id IS NOT NULL` — the `granted_by_user_id`
        foreign key's own supporting index

Rollback:
    Supported. Drops the table (and its constraints/index with it).

Data implications:
    A new, empty table. No existing row is altered.

Locking considerations:
    Creates one new table; no lock on any existing table.

See: database/migrations/versions/080_security_identity_and_access.py
     (security.campaign_invitations — the closest sibling design, and the
     "revoked_at checked but no revoke command yet" precedent this
     revision follows)
     database/migrations/versions/085_campaign_owner_capabilities.py,
     086_system_role_capabilities.py (the two migrations whose functional
     capability grants first made this defect exploitable — see
     085/086's own docstrings)
     src/dnd_ai/commands/campaigns.py (this table's only writer/reader)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "087_timeline_bootstrap_grants"
down_revision = "086_system_role_capabilities"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    op.execute("""
        CREATE TABLE security.timeline_bootstrap_grants (
            timeline_bootstrap_grant_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            timeline_id                  UUID NOT NULL
                                          REFERENCES campaign.timelines(timeline_id)
                                          ON DELETE CASCADE,
            granted_to_user_id           UUID NOT NULL
                                          REFERENCES security.users(user_id) ON DELETE CASCADE,
            granted_by_user_id           UUID
                                          REFERENCES security.users(user_id) ON DELETE SET NULL,
            expires_at                   TIMESTAMPTZ NOT NULL,
            revoked_at                   TIMESTAMPTZ,
            consumed_at                  TIMESTAMPTZ,
            consumed_by_campaign_id      UUID
                                          REFERENCES campaign.campaigns(campaign_id)
                                          ON DELETE RESTRICT,
            created_at                   TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_timeline_bootstrap_grants_consumed_pairing
                CHECK ((consumed_at IS NULL) = (consumed_by_campaign_id IS NULL))
        );
    """)
    op.execute("""
        COMMENT ON TABLE security.timeline_bootstrap_grants IS
        'A single-use entitlement, issued by trusted world-authoring/import '
        'infrastructure (never over HTTP), authorizing one specific user to '
        'create the first campaign.campaigns row on one specific timeline. '
        'Consumed atomically by dnd_ai.commands.campaigns.create_campaign() '
        'in the same transaction that creates the campaign it authorizes — '
        'see that module''s own docstring for the full policy.';
    """)
    op.execute("""
        CREATE UNIQUE INDEX ux_timeline_bootstrap_grants_active
        ON security.timeline_bootstrap_grants (timeline_id, granted_to_user_id)
        WHERE consumed_at IS NULL AND revoked_at IS NULL;
    """)
    op.execute(
        "CREATE INDEX ix_timeline_bootstrap_grants_consumed_by_campaign_id "
        "ON security.timeline_bootstrap_grants (consumed_by_campaign_id) "
        "WHERE consumed_by_campaign_id IS NOT NULL;"
    )
    # conventions §19.1: every FK needs a supporting index — a leading-
    # column match counts, so ux_timeline_bootstrap_grants_active above
    # already covers timeline_id (its own leading column), but not
    # granted_to_user_id (its second column) or granted_by_user_id (no
    # index touches it at all).
    op.execute(
        "CREATE INDEX ix_timeline_bootstrap_grants_granted_to_user_id "
        "ON security.timeline_bootstrap_grants (granted_to_user_id);"
    )
    op.execute(
        "CREATE INDEX ix_timeline_bootstrap_grants_granted_by_user_id "
        "ON security.timeline_bootstrap_grants (granted_by_user_id) "
        "WHERE granted_by_user_id IS NOT NULL;"
    )


def downgrade() -> None:
    """Revert the migration."""

    op.execute("DROP TABLE IF EXISTS security.timeline_bootstrap_grants;")
