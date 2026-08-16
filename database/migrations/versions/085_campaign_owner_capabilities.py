"""Extend campaign_owner with campaign.view and canon.edit

Revision ID: 085_campaign_owner_capabilities
Revises: 084_hazard_interaction_types
Create Date: 2026-08-16 12:00:00.000000

Purpose:
    Fixes a High-severity authorization defect in `dnd_ai.commands.
    campaigns.create_campaign` (Phase 10 workstream 23): `POST /campaigns`
    assigns its creator exactly one role, `campaign_owner`, and migration
    080 seeded that system-template role with exactly one capability,
    `access.manage` — "the minimum the retention invariant below needs to
    be satisfiable" (080's own words), not a claim that `access.manage`
    alone was ever meant to be the *complete* functional-owner capability
    set. Every other Phase 10 command/query route gates on `campaign.view`
    or `canon.edit` (docs/architecture/DATABASE_MODEL.md §19.3), neither of
    which `access.manage` implies (`dnd_ai.domain.access.AccessContext.
    has_capability` checks exact capability codes, not a hierarchy) — so a
    campaign's own creator, immediately after creating it and holding no
    other role, could not view their own campaign's summary or perform any
    canon-mutating action the vertical slice needs (movement, interactions,
    quest advancement, ending a session), despite being its sole owner.
    `tests/scenario/test_vertical_slice_api.py` (workstream 28) masked this
    by additionally granting a hand-built, test-only "gm" role with
    `canon.edit`/`campaign.view` through direct `security.roles`/`.
    role_capabilities` factory writes after `POST /campaigns` returned —
    contradicting §25's own "must run through the application API without
    direct client database writes" acceptance criterion for exactly the
    capability set a real deployment has no way to grant at all, since no
    Phase 10 workstream ever built an endpoint for creating a role or
    attaching a capability to one.

    This migration closes that gap the same way migration 080's own
    "Deliberate scoping decisions" always intended it to be closed: "a
    later Phase 10 workstream owns the rest" of the default-capability
    matrix. It extends the *system-template* `campaign_owner` row (`code
    = 'campaign_owner' AND campaign_id IS NULL`) rather than any
    campaign-scoped copy — the same row every campaign's own owner
    membership already references via `security.membership_roles.role_id`
    (`dnd_ai.commands.campaigns.create_campaign` selects it by that exact
    `WHERE` clause) — so extending its `security.role_capabilities` here
    changes what every campaign's owner can do, past and future, with no
    per-campaign migration needed: a currently-active campaign's existing
    `campaign_owner` membership_roles row is untouched, but the role it
    points at now carries three capabilities instead of one the moment
    this migration commits.

    Scope is deliberately narrow: only `campaign.view` and `canon.edit` are
    added, not a build-out of the full role/capability matrix for `gm`,
    `assistant_gm`, `player`, `observer`, `import_reviewer`, or
    `rules_curator` — those system-template roles remain vocabulary-only,
    exactly as migration 080 left them, and `tests/scenario.
    test_vertical_slice_api.py` still bootstraps campaign-scoped roles for
    its non-owner participants (player1/player2/observer) via direct
    factory writes, the same convention every other Phase 10 test uses,
    documented there as a known, deliberate gap — not something this
    migration's own narrower defect fix should silently expand to cover.

    A caller-supplied `timeline_id` needed no additional authorization
    check as part of this fix: docs/DOMAIN_MODEL.md §2.2 ("Multiple
    campaigns may share a timeline") and §6.1 ("Timeline and campaign
    domain") document timeline reuse across campaigns as an intentional,
    load-bearing property of the persistent-world model, not an
    accidental one an authorization gap could exploit — `campaign.
    timelines` carries no owner/entitlement column, and no `security.*`
    table scopes access to a timeline itself (only to a campaign, a
    character, or another campaign-scoped resource). What *would* be a
    leak — a second campaign on the same timeline inheriting the first
    campaign's memberships, roles, resource grants, or party discoveries —
    cannot happen structurally: every one of those tables is keyed by
    `campaign_id` (or, for `knowledge.party_discoveries`, `party_id`), never
    by `timeline_id` alone, so a second `campaign.campaigns` row pointing
    at the same `timeline_id` starts with zero memberships, zero roles, and
    zero resource grants of its own — proven by `tests/scenario.
    test_vertical_slice_api.py`'s own steps 17-18 (a second campaign on the
    same timeline sees the first party's altered-but-not-hidden dungeon
    state, never its private discoveries) and by
    `tests/database/test_api_campaigns.py`'s new
    `test_a_second_campaign_on_an_already_used_timeline_succeeds_and_
    cannot_see_the_first_campaigns_access` case added alongside this
    migration.

Forward migration:
    INSERT two `security.role_capabilities` rows — (`campaign_owner`,
    `campaign.view`) and (`campaign_owner`, `canon.edit`) — for the
    system-template role, `ON CONFLICT (role_id, capability_id) DO
    NOTHING` (matching migration 080's own seeding idiom for this table).

Rollback:
    Supported. Deletes exactly the two `(role_id, capability_id)` pairs
    this revision adds, by capability code, scoped to the system-template
    `campaign_owner` row alone — never a wildcard across every role using
    either capability, and never touching the `access.manage` pairing
    migration 080 itself seeded. `security.
    enforce_role_capabilities_retain_access_manager()` (migration 080) only
    re-checks the retention invariant when the *removed* capability's code
    is `access.manage`; neither row deleted here matches that code, so
    the function itself always no-ops for these two deletes.

    That no-op still leaves a *pending* invocation, though:
    `tr_role_capabilities_retain_access_manager` (migration 080) is
    `DEFERRABLE INITIALLY DEFERRED`, so each `DELETE` above queues one
    trigger firing regardless of what the function body ultimately does
    with it, and a queued firing is not resolved until something forces
    it — normally the enclosing transaction's own `COMMIT`. A single
    `alembic downgrade base` never gives it that chance: `database/
    migrations/env.py`'s `context.begin_transaction()` wraps every
    migration's `downgrade()` invoked in that one run inside one
    continuous transaction, so this revision's two pending firings are
    still queued when migration `080_security_identity_and_access`'s own
    `downgrade()` — reached later in that same transaction — tries to
    `DROP TABLE security.role_capabilities`. PostgreSQL refuses to drop a
    table with pending trigger events against it
    (`psycopg.errors.ObjectInUse: cannot DROP TABLE "role_capabilities"
    because it has pending trigger events`), so the whole multi-revision
    downgrade fails at 080 even though this revision's own two deletes
    were individually harmless.

    `SET CONSTRAINTS security.tr_role_capabilities_retain_access_manager
    IMMEDIATE` below forces PostgreSQL to run both queued firings right
    here — where the function body no-ops immediately, exactly as it
    would have at commit — draining the pending state before control ever
    reaches a later revision's downgrade. This keeps the fix local to the
    migration whose own `DELETE`s create the pending state, so this
    revision's downgrade is self-contained and correct regardless of what
    else runs after it in a longer chain, rather than depending on
    `080_security_identity_and_access` (which has no reason to know or
    care what any later revision deleted) to compensate for it. A single-
    step `alembic downgrade 085_campaign_owner_capabilities` (no later
    revision's `downgrade()` sharing its transaction) already worked
    without this — the deferred check simply ran at that command's own
    commit — so this statement changes nothing observable about that
    case; it only matters once this revision's `downgrade()` shares a
    transaction with a later one that drops the table.

Data implications:
    Two new lookup-junction rows on an existing table. No existing row is
    altered. Every campaign whose owner already holds the `campaign_owner`
    role gains `campaign.view`/`canon.edit` in that campaign at commit —
    an intentional, immediate widening of what every existing campaign's
    owner can already do, not a data migration in the row-rewrite sense.

Locking considerations:
    Two ordinary row-level `INSERT`s against `security.role_capabilities`.
    No table rewrite, no new object.

See: database/migrations/versions/080_security_identity_and_access.py
     (role_capabilities' own seeding idiom, and the "a later Phase 10
     workstream owns the rest" scoping note this migration follows through
     on)
     docs/DOMAIN_MODEL.md §2.2, §6.1 (timeline sharing across campaigns)
     src/dnd_ai/commands/campaigns.py (this migration's own consumer)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "085_campaign_owner_capabilities"
down_revision = "084_hazard_interaction_types"
branch_labels = None
depends_on = None

_CAMPAIGN_OWNER_ROLE_CODE = "campaign_owner"
_NEW_CAPABILITY_CODES = ("campaign.view", "canon.edit")


def upgrade() -> None:
    """Apply the migration."""

    for capability_code in _NEW_CAPABILITY_CODES:
        op.execute(f"""
            INSERT INTO security.role_capabilities (role_id, capability_id)
            SELECT r.role_id, c.capability_id
            FROM security.roles r, security.capabilities c
            WHERE r.code = '{_CAMPAIGN_OWNER_ROLE_CODE}' AND r.campaign_id IS NULL
              AND c.code = '{capability_code}'
            ON CONFLICT (role_id, capability_id) DO NOTHING;
        """)


def downgrade() -> None:
    """Revert the migration."""

    for capability_code in _NEW_CAPABILITY_CODES:
        op.execute(f"""
            DELETE FROM security.role_capabilities rc
            USING security.roles r, security.capabilities c
            WHERE rc.role_id = r.role_id AND rc.capability_id = c.capability_id
              AND r.code = '{_CAMPAIGN_OWNER_ROLE_CODE}' AND r.campaign_id IS NULL
              AND c.code = '{capability_code}';
        """)

    # Drain the two deferred tr_role_capabilities_retain_access_manager
    # firings the deletes above just queued — see this module's own
    # "Rollback" docstring section for why a later revision's downgrade()
    # (080_security_identity_and_access, dropping this table) would
    # otherwise fail mid-chain with "pending trigger events" rather than
    # this revision's own deletes ever being the problem themselves.
    op.execute("SET CONSTRAINTS security.tr_role_capabilities_retain_access_manager IMMEDIATE;")
