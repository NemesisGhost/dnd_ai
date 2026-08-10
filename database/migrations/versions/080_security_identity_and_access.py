"""Security, identity, and authorization: external identities, service
accounts, campaign membership and invitations, campaign-scoped roles and
capabilities, human-to-character relationships, access groups, and typed
resource grants.

Revision ID: 080_security_identity_and_access
Revises: 079_integration_domain
Create Date: 2026-08-10 09:00:00.000000

Purpose:
    Phase 10 ("Core API and playable vertical slice", docs/PLAN.md §24)
    starts with the database schema everything else in the phase depends
    on: the application-security model in
    docs/architecture/DATABASE_MODEL.md §19. This revision delivers that
    schema only — no FastAPI app, no command/query layer, no OIDC
    integration, no Terraform. Those are later Phase 10 workstreams. It
    does, however, fully enforce every cross-row invariant DATABASE_MODEL.md
    §19/§22 states for this schema at the database level — the command
    layer's job is to call these tables correctly, not to compensate for
    gaps left here.

    Reconciles rather than collides with the placeholder security tables
    revision 003 deliberately created small ("Intentionally unseeded: the
    role vocabulary is not yet specified... inventing it here would
    preempt that decision"). security.users is ALTERed to the §19.1
    target shape (drop username/is_active, add lifecycle_status_id/
    last_login_at) rather than recreated, because it is already
    FK-referenced (ON DELETE SET NULL, pure attribution) by
    core.entities.created_by_user_id, core.entity_names/entity_tags.
    tagged_by_user_id, audit.change_actions.actor_user_id, and
    character.characters.player_user_id — all reference user_id, none
    reference username/is_active, so those references are unaffected.
    The old global security.roles/security.user_roles pair is dropped
    outright and replaced by the new campaign-scoped security.roles plus
    security.membership_roles — confirmed by full-repo grep that nothing
    outside revision 003 and the persistence reflection module references
    either table, so there is no dangling foreign key. No user-facing
    data exists yet (pre-launch project), so a destructive ALTER is safe;
    the "Data implications" note below is explicit about this not being a
    generally safe pattern.

    Scope is deliberately narrower than every target column
    DATABASE_MODEL.md §19.6 lists for security.resource_grants — the
    phase's own boundary note restricts this migration to "only the
    typed targets required by the playable vertical slice and portal
    queries": character_id, entity_id, knowledge_item_id, quest_id,
    session_id, event_id. source_document_id (Phase 12 rules corpus),
    ai_proposed_change_id (no core.proposed_changes table exists yet),
    and import_job_id (Phase 14) are added by the migration that
    introduces their target table, per §19.6's own "later resource types
    extend the same constrained pattern as needed" note.

Forward migration:
    - Lookups (§11 shape, seeded via apply_seed()):
      security.membership_statuses, security.character_relationship_types,
      security.capabilities
    - ALTER security.users to the §19.1 shape
    - DROP the old security.roles / security.user_roles pair
    - security.external_identities, security.service_accounts
    - security.campaign_memberships, security.campaign_invitations, each
      with a same-campaign actor-scope guard for their own
      *_by_membership_id column
    - security.roles (new campaign-scoped shape, seeded with the 7 system
      role codes as vocabulary), security.role_capabilities (seeded with
      exactly one pairing — campaign_owner/access.manage, the minimum the
      retention invariant below needs to be satisfiable; the rest of the
      matrix is still deferred, see deliberate scoping decisions)
    - security.membership_roles, with
      security.enforce_membership_role_scope() (same-campaign role
      usability plus same-campaign granted_by_membership_id)
    - security.membership_character_relationships, with
      security.enforce_membership_character_relationship_scope() (same-
      world/-campaign agreement plus same-campaign granted_by_membership_id;
      also derives effective_period, mirroring campaign.
      sync_party_membership_period() from revision 009)
    - security.character_relationship_type_capabilities
    - security.access_groups, security.access_group_memberships, with
      security.enforce_access_group_membership_scope() (same-campaign
      group membership plus same-campaign added_by_membership_id)
    - security.resource_grants, with security.enforce_resource_grant_scope()
      (same-world/-campaign/-timeline agreement plus same-campaign
      granted_by_membership_id)
    - Reverse-mutation guards: core.enforce_immutable_columns() (revision
      030) attached to security.campaign_memberships.campaign_id,
      security.access_groups.campaign_id, campaign.sessions.campaign_id,
      and narrative.events.campaign_id/timeline_id. security.roles.
      campaign_id gets its own dedicated, NULL-inclusive guard instead
      (security.enforce_roles_campaign_immutable()) — a system template
      (campaign_id NULL) must never be promotable to campaign-scoped, so
      the generic function's NULL -> value allowance does not apply here
    - Campaign owner/access-manager retention invariant (DATABASE_MODEL.md
      §22 rule 19): security.campaign_has_access_manager() (requiring a
      non-expiring qualifying grant with an active role, capability, and
      membership status — see deliberate scoping decisions for why),
      security.assert_campaign_retains_access_manager(), and seven
      DEFERRABLE INITIALLY DEFERRED constraint triggers on security.
      campaign_memberships, security.membership_roles, security.
      role_capabilities, security.capabilities, security.
      membership_statuses, security.roles, and campaign.campaigns (checked
      on INSERT as well as UPDATE) — see that section's own docstring for
      the full design

Rollback:
    Supported, with one honest caveat: reverting security.users to its
    old shape cannot reconstruct real usernames (none exist to preserve
    in the target environment), so the downgrade synthesizes a
    placeholder username per row rather than silently failing on the
    NOT NULL/UNIQUE constraints the old shape required.

Data implications:
    security.users.lifecycle_status_id is added NOT NULL with no
    application-level DEFAULT. That only works because this environment
    is pre-launch and the table is guaranteed empty — it is not a
    generally safe pattern for a column addition against a populated
    table (that needs an expand/contract pair per conventions §25.5).

Locking considerations:
    The ALTER TABLE security.users statements take a brief ACCESS
    EXCLUSIVE lock on an empty table; negligible. Adding a trigger (the
    reverse-mutation guards on campaign.sessions/narrative.events, and the
    retention constraint trigger on campaign.campaigns) does not rewrite
    those tables. Every other statement creates a new, empty object.

Deliberate scoping decisions:
    - security.capabilities is one shared, dot-namespaced vocabulary
      reused by both security.role_capabilities and
      security.character_relationship_type_capabilities, rather than two
      separate lookups — DATABASE_MODEL.md §19.3 and §19.4 name
      `character.control`/`control` and `access.manage`/`manage_access`
      informally; this migration resolves each pair to one capability
      code (`character.control`, `access.manage`) rather than treating
      them as four.
    - security.capabilities uses a namespaced code format
      (`^[a-z][a-z0-9_]*(\\.[a-z][a-z0-9_]*)*$`), a first deviation from
      every other lookup's plain `^[a-z][a-z0-9_]*$` — capability codes
      are namespaced by design (`campaign.view`, `character.control`).
    - security.roles seeds the 7 system-role codes §19.3 names
      (campaign_owner, gm, assistant_gm, player, observer,
      import_reviewer, rules_curator) as vocabulary, and security.
      role_capabilities seeds exactly the one campaign_owner/access.manage
      pairing the retention invariant structurally requires to exist — not
      the full default-capability matrix every other role should
      eventually carry. That fuller mapping has no command layer yet to
      validate it against, and inventing all of it now would repeat
      exactly the mistake revision 003 avoided by leaving the old
      security.roles unseeded. A later Phase 10 workstream owns the rest.
    - security.external_identities' "unique (issuer, subject)" (§19.1) is
      implemented as a *partial* unique index, `WHERE revoked_at IS
      NULL`, not an unconditional one — so a revoked identity link can be
      re-established later (e.g. the same IdP re-issuing the same
      subject) without a manual delete of the old row.
    - security.resource_grants' active-grant uniqueness uses one `NULLS
      NOT DISTINCT` unique index across the grantee/target/scope/
      capability/effect columns, rather than the ~12 partial indexes a
      one-per-combination approach would need (PostgreSQL 18 is the
      project's pinned version everywhere, so the syntax is available;
      first use of it in this codebase).
    - security.resource_grants.timeline_id scopes to "any timeline in the
      grant's world" (checked by the guard trigger), not "must equal the
      grant's campaign's single timeline" — the stricter reading would
      make the column redundant with campaign_id, since one campaign has
      exactly one timeline in the current schema; the looser reading is
      what lets a grant reference a sibling branch's timeline instead.
    - security.service_accounts has no consumer yet: security.
      resource_grants' grantee is limited to campaign_membership/
      access_group for the vertical slice (§19.6, this migration's own
      scope note), so a created service account cannot yet be the target
      of a resource grant. Per §19.1, service accounts get capabilities
      "through explicit service-account grants or narrowly scoped
      application configuration" — the former extends resource_grants'
      grantee columns in a later migration when a concrete caller exists.
    - The campaign owner/access-manager retention invariant (DATABASE_MODEL.md
      §22 rule 19) is fully enforced at the database level, with no
      accepted exception for how a campaign came to be active — see
      section 18's own docstring for the complete design (stable
      capability semantics; the INSERT-and-UPDATE trigger on campaign.
      campaigns so a campaign can never be active, even momentarily,
      without a qualifying owner already existing in the same transaction;
      the non-expiring-grant requirement so the guarantee cannot lapse
      merely because time passes with no write; DEFERRABLE INITIALLY
      DEFERRED constraint triggers so a normal revoke-old/grant-new
      transfer is checked once against final state; and a row lock making
      concurrent removal attempts serialize correctly).
      security.resource_grants cannot currently express a campaign-wide
      grant or deny (every row requires exactly one specific target from
      the six kinds Phase 10 needs — none of them is "the campaign as a
      whole"), so there is no resource-grant-shaped path that can revoke
      this capability today; if a future migration adds a campaign-wide
      resource_grant target, extend security.campaign_has_access_manager()
      to account for it.
    - Three explicit decisions about lookup-row activation state, made
      rather than left as an accidental silence: (1) security.capabilities.
      is_active and security.membership_statuses.is_active are both now
      required by security.campaign_has_access_manager() — an inactive
      access.manage capability, or an inactive 'active' membership-status
      row, does not authorize, matching how security.roles.is_active
      already worked before this correction pass. Deactivating either
      specific row is guarded the same way removing access.manage from a
      role already was (security.enforce_capabilities_retain_access_manager(),
      security.enforce_membership_statuses_retain_access_manager()). (2) The
      three lookup *codes* these comparisons depend on by name — core.
      lifecycle_statuses.code = 'active', security.membership_statuses.
      code = 'active', security.capabilities.code = 'access.manage' — are
      protected from renaming by section 17's
      core.enforce_protected_lookup_codes(), since none of the triggers in
      this section fire on an UPDATE to a lookup table's own code column,
      and a rename would otherwise silently break every hardcoded
      comparison here with nothing to observe it. (3) core.
      lifecycle_statuses.is_active (the campaign's own status row) is
      deliberately *not* added to this invariant, unlike the two lookups
      above — that table is shared across the entire schema (worlds,
      entities, timelines, users, sessions, roles, and more, none of it
      owned by this revision), every row in it is seeded is_active = true
      today with nothing elsewhere in the codebase gating on it, and its
      documented meaning (§11.1-adjacent convention: whether a lookup value
      is currently offered for *new* assignment) is a different question
      from whether a campaign already pointing at the 'active' row should
      retroactively stop counting as active. Extending is_active semantics
      to a table this revision does not own, on a dimension nothing else
      in the codebase currently uses, would be scope creep past what
      DATABASE_MODEL.md §22 rule 19 requires; revisit only if a real
      consumer for core.lifecycle_statuses.is_active is ever built.

See: docs/PLAN.md §24, Phase 10 (Core API and playable vertical slice)
     docs/architecture/DATABASE_MODEL.md §19 (security, identity, and
     access), §22 rule 19 (campaign owner/access-manager retention)
     docs/DATABASE_CONVENTIONS.md §8.3 (partial unique indexes), §9.5
     (same-world consistency), §11 (lookup tables), §12.5 (ADR 0010
     interval contract), §20 (constraints), §20.3 (deferred constraints),
     §25.4 (seed data), §31 (documentation)
     database/migrations/versions/030_parent_scope_immutability.py,
     033_rules_identity_immutability.py, 075_phase7_reparent_guards.py
     (the reverse-mutation-guard precedent this revision reuses)
"""

from alembic import op

from dnd_ai.persistence.seeds import apply_seed

# revision identifiers, used by Alembic.
revision = "080_security_identity_and_access"
down_revision = "079_integration_domain"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the migration."""

    # ==========================================================================
    # 1. Lookups
    # ==========================================================================
    for schema, table, pk, comment in (
        (
            "security",
            "membership_statuses",
            "membership_status_id",
            "Lifecycle of a security.campaign_memberships row: invited, active, "
            "suspended, revoked, departed (docs/architecture/DATABASE_MODEL.md "
            "§19.2).",
        ),
        (
            "security",
            "character_relationship_types",
            "character_relationship_type_id",
            "Semantic relationship between a campaign membership and a "
            "character — owner, primary_controller, co_controller, viewer, "
            "portrayer, former_controller, observer_approved_viewer "
            "(docs/architecture/DATABASE_MODEL.md §19.4).",
        ),
        (
            "security",
            "capabilities",
            "capability_id",
            "A stable, dot-namespaced operation code — campaign.view, "
            "canon.edit, character.control, and similar — assigned to roles "
            "(security.role_capabilities) and character-relationship types "
            "(security.character_relationship_type_capabilities). One shared "
            "vocabulary for both (docs/architecture/DATABASE_MODEL.md §19.3, "
            "§19.4).",
        ),
    ):
        op.execute(f"""
            CREATE TABLE {schema}.{table} (
                {pk}          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                code          TEXT NOT NULL,
                display_name  TEXT NOT NULL,
                description   TEXT,
                sort_order    core.nonnegative_integer NOT NULL DEFAULT 0,
                is_active     BOOLEAN NOT NULL DEFAULT true,
                created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
                CONSTRAINT ux_{table}_code UNIQUE (code),
                CONSTRAINT ck_{table}_code_length CHECK (char_length(code) <= 100)
            );
        """)
        op.execute(f"COMMENT ON TABLE {schema}.{table} IS '{comment}';")
        op.execute(f"""
            COMMENT ON COLUMN {schema}.{table}.code IS
            'Stable machine-readable identifier. Application logic may reference '
            'codes, but foreign keys use IDs (conventions §11.1).';
        """)
        op.execute(f"""
            CREATE TRIGGER tr_{table}_set_updated_at
            BEFORE UPDATE ON {schema}.{table}
            FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
        """)

    # capabilities codes are namespaced (campaign.view, character.control),
    # unlike every other lookup's plain ^[a-z][a-z0-9_]*$ — see this
    # revision's "Deliberate scoping decisions".
    op.execute(r"""
        ALTER TABLE security.capabilities
        ADD CONSTRAINT ck_capabilities_code_format
        CHECK (code ~ '^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$');
    """)
    op.execute(r"""
        ALTER TABLE security.membership_statuses
        ADD CONSTRAINT ck_membership_statuses_code_format
        CHECK (code ~ '^[a-z][a-z0-9_]*$');
    """)
    op.execute(r"""
        ALTER TABLE security.character_relationship_types
        ADD CONSTRAINT ck_character_relationship_types_code_format
        CHECK (code ~ '^[a-z][a-z0-9_]*$');
    """)

    # ==========================================================================
    # 2. Reshape security.users to the §19.1 target shape
    # ==========================================================================
    # No data exists yet worth preserving (pre-launch) — a single destructive
    # ALTER rather than an expand/contract pair. Dropping username/is_active
    # also drops their column-scoped constraints (ux_users_username,
    # ck_users_username_length) automatically; nothing else references them.
    op.execute("ALTER TABLE security.users DROP COLUMN username;")
    op.execute("ALTER TABLE security.users DROP COLUMN is_active;")
    op.execute("""
        ALTER TABLE security.users
        ADD COLUMN lifecycle_status_id UUID
            REFERENCES core.lifecycle_statuses(lifecycle_status_id) ON DELETE RESTRICT;
    """)
    op.execute(
        "UPDATE security.users SET lifecycle_status_id = ("
        "SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'active'"
        ") WHERE lifecycle_status_id IS NULL;"
    )
    op.execute("ALTER TABLE security.users ALTER COLUMN lifecycle_status_id SET NOT NULL;")
    op.execute("ALTER TABLE security.users ADD COLUMN last_login_at TIMESTAMPTZ;")
    op.execute("CREATE INDEX ix_users_lifecycle_status_id ON security.users (lifecycle_status_id);")
    op.execute("""
        COMMENT ON TABLE security.users IS
        'Application identity independent of any login provider. Authentication is '
        'delegated to external identity providers via security.external_identities — '
        'this table is identity for attribution and authorization only '
        '(docs/architecture/DATABASE_MODEL.md §19.1).';
    """)
    op.execute("""
        COMMENT ON COLUMN security.users.lifecycle_status_id IS
        'Whether this identity is currently usable by the platform — replaces the '
        'old is_active boolean (conventions §11: lookup tables over booleans).';
    """)
    op.execute("""
        COMMENT ON COLUMN security.users.last_login_at IS
        'Updated by the application on successful authentication; NULL for a user '
        'who has never logged in.';
    """)

    # ==========================================================================
    # 3. Drop the old global security.roles / security.user_roles
    # ==========================================================================
    # Confirmed by full-repo grep: nothing outside revision 003 and the
    # persistence reflection module references either table.
    op.execute("DROP TABLE IF EXISTS security.user_roles;")
    op.execute("DROP TABLE IF EXISTS security.roles;")

    # ==========================================================================
    # 4. security.external_identities
    # ==========================================================================
    op.execute("""
        CREATE TABLE security.external_identities (
            external_identity_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id                   UUID NOT NULL
                                    REFERENCES security.users(user_id) ON DELETE CASCADE,
            issuer                      TEXT NOT NULL,
            subject                       TEXT NOT NULL,
            email_at_last_login             TEXT,
            claims_snapshot                    JSONB,
            linked_at                             TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_authenticated_at                    TIMESTAMPTZ,
            revoked_at                                  TIMESTAMPTZ,
            CONSTRAINT ck_external_identities_issuer_length
                CHECK (char_length(issuer) BETWEEN 1 AND 255),
            CONSTRAINT ck_external_identities_subject_length
                CHECK (char_length(subject) BETWEEN 1 AND 255)
        );
    """)
    op.execute("""
        COMMENT ON TABLE security.external_identities IS
        'Maps one security.users row to one or more OIDC identities '
        '(issuer, subject) — never raw tokens (docs/architecture/'
        'DATABASE_MODEL.md §19.1). Email is informational, not the identity key, '
        'since it may change or be reused by the provider.';
    """)
    op.execute("""
        COMMENT ON COLUMN security.external_identities.claims_snapshot IS
        'A minimal allow-listed set of claims kept for diagnostics — never raw '
        'tokens.';
    """)
    op.execute(
        "CREATE INDEX ix_external_identities_user_id ON security.external_identities (user_id);"
    )
    op.execute("""
        CREATE UNIQUE INDEX ux_external_identities_issuer_subject
        ON security.external_identities (issuer, subject)
        WHERE revoked_at IS NULL;
    """)

    # ==========================================================================
    # 5. security.service_accounts
    # ==========================================================================
    op.execute("""
        CREATE TABLE security.service_accounts (
            service_account_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            code                    TEXT NOT NULL,
            display_name              TEXT NOT NULL,
            description                  TEXT,
            is_active                      BOOLEAN NOT NULL DEFAULT true,
            created_at                        TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at                           TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ux_service_accounts_code UNIQUE (code),
            CONSTRAINT ck_service_accounts_code_format CHECK (code ~ '^[a-z][a-z0-9_]*$')
        );
    """)
    op.execute("""
        COMMENT ON TABLE security.service_accounts IS
        'A non-human application principal. Never gains campaign access merely by '
        'existing — capabilities are assigned through explicit service-account '
        'grants or narrowly scoped application configuration, and all actions '
        'identify the service principal in audit records '
        '(docs/architecture/DATABASE_MODEL.md §19.1).';
    """)
    op.execute("""
        CREATE TRIGGER tr_service_accounts_set_updated_at
        BEFORE UPDATE ON security.service_accounts
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)

    # ==========================================================================
    # 6. security.campaign_memberships
    # ==========================================================================
    op.execute("""
        CREATE TABLE security.campaign_memberships (
            campaign_membership_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            campaign_id                 UUID NOT NULL
                                    REFERENCES campaign.campaigns(campaign_id) ON DELETE CASCADE,
            user_id                       UUID NOT NULL
                                    REFERENCES security.users(user_id) ON DELETE RESTRICT,
            membership_status_id           UUID NOT NULL
                                    REFERENCES security.membership_statuses(membership_status_id)
                                    ON DELETE RESTRICT,
            joined_at                         TIMESTAMPTZ,
            ended_at                            TIMESTAMPTZ,
            ended_by_membership_id                 UUID
                                    REFERENCES security.campaign_memberships(campaign_membership_id)
                                    ON DELETE SET NULL,
            created_at                                TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at                                   TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_campaign_memberships_ended_after_joined CHECK (
                ended_at IS NULL OR joined_at IS NULL OR ended_at > joined_at
            )
        );
    """)
    op.execute("""
        COMMENT ON TABLE security.campaign_memberships IS
        'The many-to-many association between users and campaigns and the root '
        'of human authorization within a campaign (docs/architecture/'
        'DATABASE_MODEL.md §19.2). user_id is ON DELETE RESTRICT, not CASCADE — '
        'membership history must survive a user delete. Revoked/departed rows '
        'are closed (ended_at set), never deleted.';
    """)
    op.execute("""
        CREATE TRIGGER tr_campaign_memberships_set_updated_at
        BEFORE UPDATE ON security.campaign_memberships
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute(
        "CREATE INDEX ix_campaign_memberships_campaign_id "
        "ON security.campaign_memberships (campaign_id);"
    )
    op.execute(
        "CREATE INDEX ix_campaign_memberships_user_id ON security.campaign_memberships (user_id);"
    )
    op.execute(
        "CREATE INDEX ix_campaign_memberships_membership_status_id "
        "ON security.campaign_memberships (membership_status_id);"
    )
    op.execute(
        "CREATE INDEX ix_campaign_memberships_ended_by_membership_id "
        "ON security.campaign_memberships (ended_by_membership_id) "
        "WHERE ended_by_membership_id IS NOT NULL;"
    )
    op.execute("""
        CREATE UNIQUE INDEX ux_campaign_memberships_open
        ON security.campaign_memberships (campaign_id, user_id)
        WHERE ended_at IS NULL;
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION security.enforce_campaign_membership_actor_scope()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_actor_campaign  UUID;
        BEGIN
            IF NEW.ended_by_membership_id IS NOT NULL THEN
                SELECT campaign_id INTO v_actor_campaign
                FROM security.campaign_memberships
                WHERE campaign_membership_id = NEW.ended_by_membership_id;

                IF v_actor_campaign IS DISTINCT FROM NEW.campaign_id THEN
                    RAISE EXCEPTION
                        'Membership % belongs to campaign %, but ended_by_membership_id % '
                        'belongs to campaign %',
                        NEW.campaign_membership_id, NEW.campaign_id,
                        NEW.ended_by_membership_id, v_actor_campaign
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION security.enforce_campaign_membership_actor_scope() IS
        'Guard for security.campaign_memberships: ended_by_membership_id, when set, must '
        'belong to the same campaign as the membership it closed (conventions §9.5). '
        'campaign_id is immutable (see the reverse-mutation guards below), so this check '
        'can never be invalidated by a later reparenting of either row.';
    """)
    op.execute("""
        CREATE TRIGGER tr_campaign_memberships_enforce_actor_scope
        BEFORE INSERT OR UPDATE ON security.campaign_memberships
        FOR EACH ROW EXECUTE FUNCTION security.enforce_campaign_membership_actor_scope();
    """)

    # ==========================================================================
    # 7. security.campaign_invitations
    # ==========================================================================
    op.execute("""
        CREATE TABLE security.campaign_invitations (
            campaign_invitation_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            campaign_id                 UUID NOT NULL
                                    REFERENCES campaign.campaigns(campaign_id) ON DELETE CASCADE,
            invited_email                  TEXT,
            invitation_token_hash             TEXT NOT NULL,
            invited_by_membership_id             UUID NOT NULL
                                    REFERENCES security.campaign_memberships(campaign_membership_id)
                                    ON DELETE RESTRICT,
            expires_at                              TIMESTAMPTZ NOT NULL,
            accepted_by_user_id                        UUID
                                    REFERENCES security.users(user_id) ON DELETE SET NULL,
            accepted_at                                   TIMESTAMPTZ,
            revoked_at                                       TIMESTAMPTZ,
            created_at                                          TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ux_campaign_invitations_token_hash UNIQUE (invitation_token_hash),
            CONSTRAINT ck_campaign_invitations_token_hash_length
                CHECK (char_length(invitation_token_hash) BETWEEN 20 AND 255),
            CONSTRAINT ck_campaign_invitations_accepted_pair CHECK (
                (accepted_at IS NULL) = (accepted_by_user_id IS NULL)
            )
        );
    """)
    op.execute("""
        COMMENT ON TABLE security.campaign_invitations IS
        'Tracks an invitation without pre-creating a durable membership for an '
        'unknown recipient (docs/architecture/DATABASE_MODEL.md §19.2). Only the '
        'token hash is retained. Acceptance creates or activates a '
        'security.campaign_memberships row through an application command and is '
        'idempotent.';
    """)
    op.execute(
        "CREATE INDEX ix_campaign_invitations_campaign_id "
        "ON security.campaign_invitations (campaign_id);"
    )
    op.execute(
        "CREATE INDEX ix_campaign_invitations_invited_by_membership_id "
        "ON security.campaign_invitations (invited_by_membership_id);"
    )
    op.execute(
        "CREATE INDEX ix_campaign_invitations_accepted_by_user_id "
        "ON security.campaign_invitations (accepted_by_user_id) "
        "WHERE accepted_by_user_id IS NOT NULL;"
    )

    op.execute("""
        CREATE OR REPLACE FUNCTION security.enforce_campaign_invitation_actor_scope()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_actor_campaign  UUID;
        BEGIN
            SELECT campaign_id INTO v_actor_campaign
            FROM security.campaign_memberships
            WHERE campaign_membership_id = NEW.invited_by_membership_id;

            IF v_actor_campaign IS DISTINCT FROM NEW.campaign_id THEN
                RAISE EXCEPTION
                    'Invitation % targets campaign %, but invited_by_membership_id % '
                    'belongs to campaign %',
                    NEW.campaign_invitation_id, NEW.campaign_id,
                    NEW.invited_by_membership_id, v_actor_campaign
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION security.enforce_campaign_invitation_actor_scope() IS
        'Guard for security.campaign_invitations: invited_by_membership_id must belong to '
        'the same campaign the invitation is for (conventions §9.5). campaign_id is '
        'immutable on both tables (see the reverse-mutation guards below), so this check '
        'can never be invalidated by a later reparenting of either row.';
    """)
    op.execute("""
        CREATE TRIGGER tr_campaign_invitations_enforce_actor_scope
        BEFORE INSERT OR UPDATE ON security.campaign_invitations
        FOR EACH ROW EXECUTE FUNCTION security.enforce_campaign_invitation_actor_scope();
    """)

    # ==========================================================================
    # 8. security.roles (new campaign-scoped shape)
    # ==========================================================================
    op.execute("""
        CREATE TABLE security.roles (
            role_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            campaign_id      UUID
                            REFERENCES campaign.campaigns(campaign_id) ON DELETE CASCADE,
            code               TEXT NOT NULL,
            display_name          TEXT NOT NULL,
            description              TEXT,
            sort_order                  core.nonnegative_integer NOT NULL DEFAULT 0,
            is_active                      BOOLEAN NOT NULL DEFAULT true,
            created_at                        TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at                           TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_roles_code_format CHECK (code ~ '^[a-z][a-z0-9_]*$'),
            CONSTRAINT uq_roles_campaign_code UNIQUE (campaign_id, code)
        );
    """)
    op.execute("""
        COMMENT ON TABLE security.roles IS
        'A configurable campaign role — campaign owner, GM, assistant GM, player, '
        'observer, import reviewer, rules curator (docs/architecture/'
        'DATABASE_MODEL.md §19.3). campaign_id NULL means a system template usable '
        'by any campaign; non-NULL scopes the role to one campaign. '
        'uq_roles_campaign_code does not by itself stop two system templates '
        'sharing a code (NULL <> NULL) — see ux_roles_system_code below.';
    """)
    op.execute("""
        CREATE UNIQUE INDEX ux_roles_system_code
        ON security.roles (code) WHERE campaign_id IS NULL;
    """)
    op.execute(
        "CREATE INDEX ix_roles_campaign_id ON security.roles (campaign_id) "
        "WHERE campaign_id IS NOT NULL;"
    )
    op.execute("""
        CREATE TRIGGER tr_roles_set_updated_at
        BEFORE UPDATE ON security.roles
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)

    # ==========================================================================
    # 9. security.role_capabilities
    # ==========================================================================
    op.execute("""
        CREATE TABLE security.role_capabilities (
            role_id        UUID NOT NULL
                          REFERENCES security.roles(role_id) ON DELETE CASCADE,
            capability_id     UUID NOT NULL
                          REFERENCES security.capabilities(capability_id) ON DELETE RESTRICT,
            created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (role_id, capability_id)
        );
    """)
    op.execute("""
        COMMENT ON TABLE security.role_capabilities IS
        'Many-to-many default capabilities for a role (docs/architecture/'
        'DATABASE_MODEL.md §19.3). ON DELETE RESTRICT against capabilities so a '
        'capability in active use cannot vanish out from under its holders.';
    """)
    op.execute(
        "CREATE INDEX ix_role_capabilities_capability_id "
        "ON security.role_capabilities (capability_id);"
    )

    # ==========================================================================
    # 10. security.membership_roles
    # ==========================================================================
    op.execute("""
        CREATE TABLE security.membership_roles (
            membership_role_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            campaign_membership_id        UUID NOT NULL
                                    REFERENCES security.campaign_memberships(campaign_membership_id)
                                    ON DELETE CASCADE,
            role_id                          UUID NOT NULL
                                    REFERENCES security.roles(role_id) ON DELETE RESTRICT,
            granted_by_membership_id            UUID
                                    REFERENCES security.campaign_memberships(campaign_membership_id)
                                    ON DELETE SET NULL,
            granted_at                             TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at                                TIMESTAMPTZ,
            revoked_at                                   TIMESTAMPTZ,
            CONSTRAINT ck_membership_roles_expires_after_granted
                CHECK (expires_at IS NULL OR expires_at > granted_at),
            CONSTRAINT ck_membership_roles_revoked_after_granted
                CHECK (revoked_at IS NULL OR revoked_at >= granted_at)
        );
    """)
    op.execute("""
        COMMENT ON TABLE security.membership_roles IS
        'Many-to-many role assignment from a campaign membership to a role '
        '(docs/architecture/DATABASE_MODEL.md §19.3). A membership may hold '
        'multiple roles concurrently. Revocation closes the row (revoked_at set) '
        'rather than deleting it.';
    """)
    op.execute(
        "CREATE INDEX ix_membership_roles_campaign_membership_id "
        "ON security.membership_roles (campaign_membership_id);"
    )
    op.execute("CREATE INDEX ix_membership_roles_role_id ON security.membership_roles (role_id);")
    op.execute(
        "CREATE INDEX ix_membership_roles_granted_by_membership_id "
        "ON security.membership_roles (granted_by_membership_id) "
        "WHERE granted_by_membership_id IS NOT NULL;"
    )
    op.execute("""
        CREATE UNIQUE INDEX ux_membership_roles_active
        ON security.membership_roles (campaign_membership_id, role_id)
        WHERE revoked_at IS NULL;
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION security.enforce_membership_role_scope()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_membership_campaign  UUID;
            v_role_campaign        UUID;
            v_actor_campaign       UUID;
        BEGIN
            SELECT campaign_id INTO v_membership_campaign
            FROM security.campaign_memberships
            WHERE campaign_membership_id = NEW.campaign_membership_id;

            SELECT campaign_id INTO v_role_campaign
            FROM security.roles WHERE role_id = NEW.role_id;

            -- A role is usable by a membership when it's a system template
            -- (campaign_id IS NULL) or belongs to that membership's own campaign.
            IF v_role_campaign IS NOT NULL AND v_role_campaign IS DISTINCT FROM v_membership_campaign THEN
                RAISE EXCEPTION
                    'Membership % belongs to campaign %, but role % is scoped to campaign %',
                    NEW.campaign_membership_id, v_membership_campaign, NEW.role_id, v_role_campaign
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF NEW.granted_by_membership_id IS NOT NULL THEN
                SELECT campaign_id INTO v_actor_campaign
                FROM security.campaign_memberships
                WHERE campaign_membership_id = NEW.granted_by_membership_id;

                IF v_actor_campaign IS DISTINCT FROM v_membership_campaign THEN
                    RAISE EXCEPTION
                        'Membership % belongs to campaign %, but granted_by_membership_id % '
                        'belongs to campaign %',
                        NEW.campaign_membership_id, v_membership_campaign,
                        NEW.granted_by_membership_id, v_actor_campaign
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION security.enforce_membership_role_scope() IS
        'Guard for security.membership_roles: a membership may receive only a '
        'role usable by its own campaign — a system template or a role scoped '
        'to that same campaign — and granted_by_membership_id, when set, must '
        'belong to that same campaign too (conventions §9.5). campaign_memberships.'
        'campaign_id and security.roles.campaign_id are both immutable (see the '
        'reverse-mutation guards below), so neither check can be invalidated by a '
        'later reparenting.';
    """)
    op.execute("""
        CREATE TRIGGER tr_membership_roles_enforce_scope
        BEFORE INSERT OR UPDATE ON security.membership_roles
        FOR EACH ROW EXECUTE FUNCTION security.enforce_membership_role_scope();
    """)

    # ==========================================================================
    # 11. security.membership_character_relationships
    # ==========================================================================
    op.execute("""
        CREATE TABLE security.membership_character_relationships (
            membership_character_relationship_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            campaign_membership_id                    UUID NOT NULL
                                    REFERENCES security.campaign_memberships(campaign_membership_id)
                                    ON DELETE CASCADE,
            character_id                                 UUID NOT NULL
                                    REFERENCES character.characters(character_id) ON DELETE CASCADE,
            character_relationship_type_id                  UUID NOT NULL
                                    REFERENCES security.character_relationship_types(
                                        character_relationship_type_id
                                    ) ON DELETE RESTRICT,
            timeline_id                                        UUID
                                    REFERENCES campaign.timelines(timeline_id) ON DELETE CASCADE,
            effective_from_world_time_id                          UUID
                                    REFERENCES core.world_times(world_time_id) ON DELETE RESTRICT,
            effective_to_world_time_id                               UUID
                                    REFERENCES core.world_times(world_time_id) ON DELETE RESTRICT,
            effective_period                                            INT8RANGE,
            granted_by_membership_id                                       UUID
                                    REFERENCES security.campaign_memberships(campaign_membership_id)
                                    ON DELETE SET NULL,
            granted_at                                                        TIMESTAMPTZ NOT NULL
                                    DEFAULT now(),
            expires_at                                                           TIMESTAMPTZ,
            revoked_at                                                              TIMESTAMPTZ,
            notes                                                                     TEXT,
            CONSTRAINT ck_membership_character_relationships_expires_after_granted
                CHECK (expires_at IS NULL OR expires_at > granted_at),
            CONSTRAINT ck_membership_character_relationships_revoked_after_granted
                CHECK (revoked_at IS NULL OR revoked_at >= granted_at)
        );
    """)
    op.execute("""
        COMMENT ON TABLE security.membership_character_relationships IS
        'Many-to-many, typed relationship between an active campaign membership '
        'and a character (docs/architecture/DATABASE_MODEL.md §19.4). The '
        'membership''s campaign, the character''s world, and an optional timeline '
        'must agree — enforced by '
        'security.enforce_membership_character_relationship_scope(), which also '
        'derives effective_period from the world-time endpoints, mirroring '
        'campaign.sync_party_membership_period() (revision 009). A transfer of '
        'ownership or control closes the prior relationship (revoked_at) and '
        'creates a new row rather than overwriting history.';
    """)
    op.execute("""
        COMMENT ON COLUMN security.membership_character_relationships.effective_period IS
        'Derived, never client-authoritative: an INT8RANGE over '
        'effective_from_world_time_id/effective_to_world_time_id''s sort_key values, '
        'maintained by security.enforce_membership_character_relationship_scope().';
    """)
    op.execute(
        "CREATE INDEX ix_membership_character_relationships_campaign_membership_id "
        "ON security.membership_character_relationships (campaign_membership_id);"
    )
    op.execute(
        "CREATE INDEX ix_membership_character_relationships_character_id "
        "ON security.membership_character_relationships (character_id);"
    )
    op.execute(
        "CREATE INDEX ix_membership_character_relationships_relationship_type_id "
        "ON security.membership_character_relationships (character_relationship_type_id);"
    )
    op.execute(
        "CREATE INDEX ix_membership_character_relationships_timeline_id "
        "ON security.membership_character_relationships (timeline_id) "
        "WHERE timeline_id IS NOT NULL;"
    )
    op.execute(
        # Name shortened to "from"/"to" (dropping "effective_") — the full
        # "..._effective_from_world_time_id" name exceeds PostgreSQL's
        # 63-character identifier limit.
        "CREATE INDEX ix_membership_character_relationships_from_world_time_id "
        "ON security.membership_character_relationships (effective_from_world_time_id) "
        "WHERE effective_from_world_time_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_membership_character_relationships_to_world_time_id "
        "ON security.membership_character_relationships (effective_to_world_time_id) "
        "WHERE effective_to_world_time_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_membership_character_relationships_granted_by_membership_id "
        "ON security.membership_character_relationships (granted_by_membership_id) "
        "WHERE granted_by_membership_id IS NOT NULL;"
    )
    op.execute("""
        CREATE UNIQUE INDEX ux_membership_character_relationships_active_type
        ON security.membership_character_relationships (
            campaign_membership_id, character_id, character_relationship_type_id
        )
        WHERE revoked_at IS NULL;
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION security.enforce_membership_character_relationship_scope()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_campaign_id       UUID;
            v_campaign_world    UUID;
            v_character_world   UUID;
            v_timeline_world    UUID;
            v_from_world        UUID;
            v_from_sort_key     BIGINT;
            v_to_world          UUID;
            v_to_sort_key       BIGINT;
            v_actor_campaign    UUID;
        BEGIN
            SELECT cm.campaign_id, t.world_id INTO v_campaign_id, v_campaign_world
            FROM security.campaign_memberships cm
            JOIN campaign.campaigns c ON c.campaign_id = cm.campaign_id
            JOIN campaign.timelines t ON t.timeline_id = c.timeline_id
            WHERE cm.campaign_membership_id = NEW.campaign_membership_id;

            SELECT world_id INTO v_character_world
            FROM core.entities WHERE entity_id = NEW.character_id;

            IF v_character_world IS DISTINCT FROM v_campaign_world THEN
                RAISE EXCEPTION
                    'Membership % belongs to world %, but character % belongs to world %',
                    NEW.campaign_membership_id, v_campaign_world, NEW.character_id, v_character_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF NEW.timeline_id IS NOT NULL THEN
                SELECT world_id INTO v_timeline_world
                FROM campaign.timelines WHERE timeline_id = NEW.timeline_id;

                IF v_timeline_world IS DISTINCT FROM v_campaign_world THEN
                    RAISE EXCEPTION
                        'Membership % belongs to world %, but timeline % belongs to world %',
                        NEW.campaign_membership_id, v_campaign_world, NEW.timeline_id, v_timeline_world
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            IF NEW.granted_by_membership_id IS NOT NULL THEN
                SELECT campaign_id INTO v_actor_campaign
                FROM security.campaign_memberships
                WHERE campaign_membership_id = NEW.granted_by_membership_id;

                IF v_actor_campaign IS DISTINCT FROM v_campaign_id THEN
                    RAISE EXCEPTION
                        'Relationship for membership % (campaign %) has granted_by_membership_id % '
                        'belonging to campaign %',
                        NEW.campaign_membership_id, v_campaign_id,
                        NEW.granted_by_membership_id, v_actor_campaign
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            IF NEW.effective_from_world_time_id IS NULL THEN
                NEW.effective_period := NULL;
                RETURN NEW;
            END IF;

            SELECT world_id, sort_key INTO v_from_world, v_from_sort_key
            FROM core.world_times WHERE world_time_id = NEW.effective_from_world_time_id;

            IF v_from_world IS DISTINCT FROM v_campaign_world THEN
                RAISE EXCEPTION
                    'Start world time % belongs to world %, but relationship belongs to world %',
                    NEW.effective_from_world_time_id, v_from_world, v_campaign_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF NEW.effective_to_world_time_id IS NULL THEN
                NEW.effective_period := int8range(v_from_sort_key, NULL, '[)');
                RETURN NEW;
            END IF;

            SELECT world_id, sort_key INTO v_to_world, v_to_sort_key
            FROM core.world_times WHERE world_time_id = NEW.effective_to_world_time_id;

            IF v_to_world IS DISTINCT FROM v_campaign_world THEN
                RAISE EXCEPTION
                    'End world time % belongs to world %, but relationship belongs to world %',
                    NEW.effective_to_world_time_id, v_to_world, v_campaign_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF v_to_sort_key <= v_from_sort_key THEN
                RAISE EXCEPTION
                    'Relationship end (sort_key %) must be later than its start (sort_key %)',
                    v_to_sort_key, v_from_sort_key
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            NEW.effective_period := int8range(v_from_sort_key, v_to_sort_key, '[)');
            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION security.enforce_membership_character_relationship_scope() IS
        'Same-world guard for security.membership_character_relationships, same-campaign '
        'guard for granted_by_membership_id, plus derivation of effective_period from its '
        'world-time endpoints when supplied (conventions §9.5, ADR 0010 interval '
        'contract). Unlike campaign.party_memberships, both endpoints are optional here '
        '— the guard clears effective_period to NULL rather than raising when no start '
        'endpoint is supplied.';
    """)
    op.execute("""
        CREATE TRIGGER tr_membership_character_relationships_enforce_scope
        BEFORE INSERT OR UPDATE ON security.membership_character_relationships
        FOR EACH ROW EXECUTE FUNCTION security.enforce_membership_character_relationship_scope();
    """)

    # ==========================================================================
    # 12. security.character_relationship_type_capabilities
    # ==========================================================================
    op.execute("""
        CREATE TABLE security.character_relationship_type_capabilities (
            character_relationship_type_id   UUID NOT NULL
                REFERENCES security.character_relationship_types(character_relationship_type_id)
                ON DELETE CASCADE,
            capability_id                       UUID NOT NULL
                REFERENCES security.capabilities(capability_id) ON DELETE RESTRICT,
            created_at                             TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (character_relationship_type_id, capability_id)
        );
    """)
    op.execute("""
        COMMENT ON TABLE security.character_relationship_type_capabilities IS
        'Default capabilities a character-relationship type grants — discover, '
        'view_summary, view_full, view_private, view_character_knowledge, '
        'edit_narrative, edit_mechanical_state, interact, control, manage_access '
        '(docs/architecture/DATABASE_MODEL.md §19.4). A direct '
        'security.resource_grants row may extend or restrict a specific '
        'membership beyond these defaults.';
    """)
    op.execute(
        "CREATE INDEX ix_character_relationship_type_capabilities_capability_id "
        "ON security.character_relationship_type_capabilities (capability_id);"
    )

    # ==========================================================================
    # 13. security.access_groups
    # ==========================================================================
    op.execute("""
        CREATE TABLE security.access_groups (
            access_group_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            campaign_id          UUID NOT NULL
                                REFERENCES campaign.campaigns(campaign_id) ON DELETE CASCADE,
            name                    TEXT NOT NULL,
            description                TEXT,
            created_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at                       TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ux_access_groups_campaign_name UNIQUE (campaign_id, name),
            CONSTRAINT ck_access_groups_name_length CHECK (char_length(name) BETWEEN 1 AND 200)
        );
    """)
    op.execute("""
        COMMENT ON TABLE security.access_groups IS
        'A campaign-scoped named set of memberships — livestream observers, '
        'former players, a GM-curated lore audience (docs/architecture/'
        'DATABASE_MODEL.md §19.5). Does not represent an in-world party; adding a '
        'membership to a group never touches campaign.party_memberships or '
        'in-world knowledge.';
    """)
    op.execute("""
        CREATE TRIGGER tr_access_groups_set_updated_at
        BEFORE UPDATE ON security.access_groups
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute("CREATE INDEX ix_access_groups_campaign_id ON security.access_groups (campaign_id);")

    # ==========================================================================
    # 14. security.access_group_memberships
    # ==========================================================================
    op.execute("""
        CREATE TABLE security.access_group_memberships (
            access_group_membership_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            access_group_id                 UUID NOT NULL
                                    REFERENCES security.access_groups(access_group_id)
                                    ON DELETE CASCADE,
            campaign_membership_id             UUID NOT NULL
                                    REFERENCES security.campaign_memberships(campaign_membership_id)
                                    ON DELETE CASCADE,
            added_by_membership_id                 UUID
                                    REFERENCES security.campaign_memberships(campaign_membership_id)
                                    ON DELETE SET NULL,
            added_at                                  TIMESTAMPTZ NOT NULL DEFAULT now(),
            removed_at                                   TIMESTAMPTZ
        );
    """)
    op.execute("""
        COMMENT ON TABLE security.access_group_memberships IS
        'Many-to-many association between campaign memberships and access groups '
        '(docs/architecture/DATABASE_MODEL.md §19.5). Removal closes the row '
        '(removed_at set) rather than deleting it.';
    """)
    op.execute(
        "CREATE INDEX ix_access_group_memberships_access_group_id "
        "ON security.access_group_memberships (access_group_id);"
    )
    op.execute(
        "CREATE INDEX ix_access_group_memberships_campaign_membership_id "
        "ON security.access_group_memberships (campaign_membership_id);"
    )
    op.execute(
        "CREATE INDEX ix_access_group_memberships_added_by_membership_id "
        "ON security.access_group_memberships (added_by_membership_id) "
        "WHERE added_by_membership_id IS NOT NULL;"
    )
    op.execute("""
        CREATE UNIQUE INDEX ux_access_group_memberships_open
        ON security.access_group_memberships (access_group_id, campaign_membership_id)
        WHERE removed_at IS NULL;
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION security.enforce_access_group_membership_scope()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_group_campaign       UUID;
            v_membership_campaign  UUID;
            v_actor_campaign       UUID;
        BEGIN
            SELECT campaign_id INTO v_group_campaign
            FROM security.access_groups WHERE access_group_id = NEW.access_group_id;

            SELECT campaign_id INTO v_membership_campaign
            FROM security.campaign_memberships
            WHERE campaign_membership_id = NEW.campaign_membership_id;

            IF v_group_campaign IS DISTINCT FROM v_membership_campaign THEN
                RAISE EXCEPTION
                    'Access group % belongs to campaign %, but membership % belongs to campaign %',
                    NEW.access_group_id, v_group_campaign, NEW.campaign_membership_id,
                    v_membership_campaign
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF NEW.added_by_membership_id IS NOT NULL THEN
                SELECT campaign_id INTO v_actor_campaign
                FROM security.campaign_memberships
                WHERE campaign_membership_id = NEW.added_by_membership_id;

                IF v_actor_campaign IS DISTINCT FROM v_membership_campaign THEN
                    RAISE EXCEPTION
                        'Access group membership for campaign % has added_by_membership_id % '
                        'belonging to campaign %',
                        v_membership_campaign, NEW.added_by_membership_id, v_actor_campaign
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION security.enforce_access_group_membership_scope() IS
        'Guard for security.access_group_memberships: a membership may only join an '
        'access group belonging to its own campaign, and added_by_membership_id, when '
        'set, must belong to that same campaign too (conventions §9.5).';
    """)
    op.execute("""
        CREATE TRIGGER tr_access_group_memberships_enforce_scope
        BEFORE INSERT OR UPDATE ON security.access_group_memberships
        FOR EACH ROW EXECUTE FUNCTION security.enforce_access_group_membership_scope();
    """)

    # ==========================================================================
    # 15. security.resource_grants
    # ==========================================================================
    op.execute("""
        CREATE TABLE security.resource_grants (
            resource_grant_id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            campaign_id                         UUID NOT NULL
                                    REFERENCES campaign.campaigns(campaign_id) ON DELETE CASCADE,
            timeline_id                            UUID
                                    REFERENCES campaign.timelines(timeline_id) ON DELETE CASCADE,
            grantee_campaign_membership_id            UUID
                                    REFERENCES security.campaign_memberships(campaign_membership_id)
                                    ON DELETE CASCADE,
            grantee_access_group_id                      UUID
                                    REFERENCES security.access_groups(access_group_id)
                                    ON DELETE CASCADE,
            capability_id                                   UUID NOT NULL
                                    REFERENCES security.capabilities(capability_id) ON DELETE RESTRICT,
            effect                                             TEXT NOT NULL DEFAULT 'allow',
            character_id                                          UUID
                                    REFERENCES character.characters(character_id) ON DELETE CASCADE,
            entity_id                                                UUID
                                    REFERENCES core.entities(entity_id) ON DELETE CASCADE,
            knowledge_item_id                                           UUID
                                    REFERENCES knowledge.knowledge_items(knowledge_item_id)
                                    ON DELETE CASCADE,
            quest_id                                                       UUID
                                    REFERENCES narrative.quests(quest_id) ON DELETE CASCADE,
            session_id                                                        UUID
                                    REFERENCES campaign.sessions(session_id) ON DELETE CASCADE,
            event_id                                                             UUID
                                    REFERENCES narrative.events(event_id) ON DELETE CASCADE,
            granted_by_membership_id                                                UUID
                                    REFERENCES security.campaign_memberships(campaign_membership_id)
                                    ON DELETE SET NULL,
            grant_source                                                               TEXT NOT NULL
                                    DEFAULT 'manual',
            reason                                                                        TEXT,
            granted_at                                                                      TIMESTAMPTZ
                                    NOT NULL DEFAULT now(),
            expires_at                                                                         TIMESTAMPTZ,
            revoked_at                                                                            TIMESTAMPTZ,
            CONSTRAINT ck_resource_grants_exactly_one_grantee CHECK (
                num_nonnulls(grantee_campaign_membership_id, grantee_access_group_id) = 1
            ),
            CONSTRAINT ck_resource_grants_exactly_one_target CHECK (
                num_nonnulls(
                    character_id, entity_id, knowledge_item_id, quest_id, session_id, event_id
                ) = 1
            ),
            CONSTRAINT ck_resource_grants_effect CHECK (effect IN ('allow', 'deny')),
            CONSTRAINT ck_resource_grants_expires_after_granted
                CHECK (expires_at IS NULL OR expires_at > granted_at),
            CONSTRAINT ck_resource_grants_revoked_after_granted
                CHECK (revoked_at IS NULL OR revoked_at >= granted_at)
        );
    """)
    op.execute("""
        COMMENT ON TABLE security.resource_grants IS
        'Explicit many-to-many access to a protected record, without an '
        'unenforced (resource_type, resource_id) polymorphic reference '
        '(docs/architecture/DATABASE_MODEL.md §19.6). Exactly one grantee column '
        'and exactly one typed target column are non-null. Scoped to the six '
        'target kinds the Phase 10 vertical slice needs (character, entity, '
        'knowledge item, quest, session, event) — source_document_id, '
        'ai_proposed_change_id, and import_job_id are added by the migration '
        'that introduces their target table (§19.6''s own extension rule). '
        'Revocation closes a row (revoked_at set) rather than deleting it.';
    """)
    op.execute("""
        COMMENT ON COLUMN security.resource_grants.effect IS
        'allow or deny. An explicit deny overrides an allow at the same or broader '
        'inherited path. A deny here is always scoped to one specific resource target '
        '(never the whole campaign — no campaign-wide target exists), so it can never '
        'by itself remove the campaign-wide access.manage capability the campaign '
        'owner/access-manager retention invariant protects (§19.6, §22 rule 19) — that '
        'invariant is database-enforced separately, by security.'
        'assert_campaign_retains_access_manager() against role-derived capabilities.';
    """)
    op.execute(
        "CREATE INDEX ix_resource_grants_campaign_id ON security.resource_grants (campaign_id);"
    )
    op.execute(
        "CREATE INDEX ix_resource_grants_timeline_id ON security.resource_grants (timeline_id) "
        "WHERE timeline_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_resource_grants_grantee_campaign_membership_id "
        "ON security.resource_grants (grantee_campaign_membership_id) "
        "WHERE grantee_campaign_membership_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_resource_grants_grantee_access_group_id "
        "ON security.resource_grants (grantee_access_group_id) "
        "WHERE grantee_access_group_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_resource_grants_capability_id ON security.resource_grants (capability_id);"
    )
    for column in (
        "character_id",
        "entity_id",
        "knowledge_item_id",
        "quest_id",
        "session_id",
        "event_id",
        "granted_by_membership_id",
    ):
        op.execute(
            f"CREATE INDEX ix_resource_grants_{column} ON security.resource_grants ({column}) "
            f"WHERE {column} IS NOT NULL;"
        )
    op.execute("""
        CREATE UNIQUE INDEX ux_resource_grants_active
        ON security.resource_grants (
            grantee_campaign_membership_id, grantee_access_group_id,
            character_id, entity_id, knowledge_item_id, quest_id, session_id, event_id,
            timeline_id, capability_id, effect
        ) NULLS NOT DISTINCT
        WHERE revoked_at IS NULL;
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION security.enforce_resource_grant_scope()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_grant_world        UUID;
            v_grantee_campaign   UUID;
            v_target_world       UUID;
            v_target_campaign    UUID;
            v_target_timeline    UUID;
            v_timeline_world     UUID;
            v_actor_campaign     UUID;
        BEGIN
            SELECT t.world_id INTO v_grant_world
            FROM campaign.campaigns c
            JOIN campaign.timelines t ON t.timeline_id = c.timeline_id
            WHERE c.campaign_id = NEW.campaign_id;

            IF NEW.grantee_campaign_membership_id IS NOT NULL THEN
                SELECT campaign_id INTO v_grantee_campaign
                FROM security.campaign_memberships
                WHERE campaign_membership_id = NEW.grantee_campaign_membership_id;

                IF v_grantee_campaign IS DISTINCT FROM NEW.campaign_id THEN
                    RAISE EXCEPTION
                        'Grant % targets campaign %, but grantee membership % belongs to campaign %',
                        NEW.resource_grant_id, NEW.campaign_id,
                        NEW.grantee_campaign_membership_id, v_grantee_campaign
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            ELSIF NEW.grantee_access_group_id IS NOT NULL THEN
                SELECT campaign_id INTO v_grantee_campaign
                FROM security.access_groups WHERE access_group_id = NEW.grantee_access_group_id;

                IF v_grantee_campaign IS DISTINCT FROM NEW.campaign_id THEN
                    RAISE EXCEPTION
                        'Grant % targets campaign %, but grantee access group % belongs to campaign %',
                        NEW.resource_grant_id, NEW.campaign_id, NEW.grantee_access_group_id,
                        v_grantee_campaign
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            IF NEW.character_id IS NOT NULL THEN
                SELECT world_id INTO v_target_world FROM core.entities WHERE entity_id = NEW.character_id;
            ELSIF NEW.entity_id IS NOT NULL THEN
                SELECT world_id INTO v_target_world FROM core.entities WHERE entity_id = NEW.entity_id;
            ELSIF NEW.knowledge_item_id IS NOT NULL THEN
                SELECT world_id INTO v_target_world
                FROM core.entities WHERE entity_id = NEW.knowledge_item_id;
            ELSIF NEW.quest_id IS NOT NULL THEN
                SELECT world_id INTO v_target_world FROM core.entities WHERE entity_id = NEW.quest_id;
            ELSIF NEW.session_id IS NOT NULL THEN
                SELECT t.world_id, s.campaign_id INTO v_target_world, v_target_campaign
                FROM campaign.sessions s
                JOIN campaign.campaigns c ON c.campaign_id = s.campaign_id
                JOIN campaign.timelines t ON t.timeline_id = c.timeline_id
                WHERE s.session_id = NEW.session_id;
            ELSIF NEW.event_id IS NOT NULL THEN
                SELECT t.world_id, e.campaign_id, e.timeline_id
                INTO v_target_world, v_target_campaign, v_target_timeline
                FROM narrative.events e
                JOIN campaign.timelines t ON t.timeline_id = e.timeline_id
                WHERE e.event_id = NEW.event_id;
            END IF;

            IF v_target_world IS DISTINCT FROM v_grant_world THEN
                RAISE EXCEPTION
                    'Grant % belongs to world %, but its target belongs to world %',
                    NEW.resource_grant_id, v_grant_world, v_target_world
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF v_target_campaign IS NOT NULL AND v_target_campaign IS DISTINCT FROM NEW.campaign_id THEN
                RAISE EXCEPTION
                    'Grant % targets campaign %, but its target belongs to campaign %',
                    NEW.resource_grant_id, NEW.campaign_id, v_target_campaign
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            IF NEW.timeline_id IS NOT NULL THEN
                SELECT world_id INTO v_timeline_world
                FROM campaign.timelines WHERE timeline_id = NEW.timeline_id;

                IF v_timeline_world IS DISTINCT FROM v_grant_world THEN
                    RAISE EXCEPTION
                        'Grant % declares timeline % (world %), but the grant itself belongs to world %',
                        NEW.resource_grant_id, NEW.timeline_id, v_timeline_world, v_grant_world
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;

                IF v_target_timeline IS NOT NULL AND v_target_timeline IS DISTINCT FROM NEW.timeline_id THEN
                    RAISE EXCEPTION
                        'Grant % declares timeline %, but its target belongs to timeline %',
                        NEW.resource_grant_id, NEW.timeline_id, v_target_timeline
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            IF NEW.granted_by_membership_id IS NOT NULL THEN
                SELECT campaign_id INTO v_actor_campaign
                FROM security.campaign_memberships
                WHERE campaign_membership_id = NEW.granted_by_membership_id;

                IF v_actor_campaign IS DISTINCT FROM NEW.campaign_id THEN
                    RAISE EXCEPTION
                        'Grant % belongs to campaign %, but granted_by_membership_id % '
                        'belongs to campaign %',
                        NEW.resource_grant_id, NEW.campaign_id,
                        NEW.granted_by_membership_id, v_actor_campaign
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION security.enforce_resource_grant_scope() IS
        'Same-world/-campaign/-timeline guard for security.resource_grants: '
        'whichever grantee column is set must belong to the grant''s own '
        'campaign, whichever target column is set must belong to the '
        'grant''s world and, where the target itself carries a campaign_id or '
        'timeline_id (sessions, events), agree with the grant''s own '
        'campaign_id/timeline_id too, and granted_by_membership_id, when set, '
        'must belong to the grant''s own campaign too (conventions §9.5).';
    """)
    op.execute("""
        CREATE TRIGGER tr_resource_grants_enforce_scope
        BEFORE INSERT OR UPDATE ON security.resource_grants
        FOR EACH ROW EXECUTE FUNCTION security.enforce_resource_grant_scope();
    """)

    # ==========================================================================
    # 16. Reverse-mutation guards — immutable parent-scope identity columns
    # ==========================================================================
    # Every scope-agreement trigger above (10, 11, 14, 15, and the two
    # actor-scope guards in 6/7) validates only the *child* row, at its own
    # INSERT/UPDATE — exactly the class of gap revisions 030, 033, and 075
    # already closed once each for other domains. None of them re-run when a
    # *parent* row's own scope identity changes out from under already-valid
    # dependents: security.campaign_memberships.campaign_id (parent to
    # security.membership_roles, .membership_character_relationships,
    # .access_group_memberships, .resource_grants, and the actor-scope checks
    # on all six *_by_membership_id columns), security.roles.campaign_id
    # (parent to .membership_roles), security.access_groups.campaign_id
    # (parent to .access_group_memberships, .resource_grants), and — because
    # security.resource_grants' session_id/event_id targets resolve their
    # scope by joining out to campaign.sessions/narrative.events —
    # campaign.sessions.campaign_id and narrative.events.campaign_id/
    # timeline_id. campaign.campaigns.timeline_id, campaign.timelines.
    # world_id, and core.entities.world_id are already immutable (revision
    # 030), which already closes the reparenting path for every
    # resource_grants target column rooted in core.entities (character_id,
    # entity_id, knowledge_item_id, quest_id) and for the campaign/timeline
    # scope columns every guard above ultimately derives from.
    #
    # None of the columns protected here represent a legitimate "move" — a
    # membership's owning campaign, an access group's owning campaign, a
    # session's owning campaign, and an event's owning campaign/timeline are
    # all identity, matching revisions 030/033/075's own stated preference
    # for immutability over a transactional revalidate-and-rebuild path.
    # Reuses core.enforce_immutable_columns() (revision 030, extended by
    # revision 033 to allow a NULL -> value transition) rather than building
    # bespoke reverse-guard triggers per table.
    #
    # security.roles.campaign_id is handled separately, immediately below,
    # by a dedicated guard rather than this shared function — a system
    # template (campaign_id NULL, usable by every campaign) must never be
    # promotable to campaign-scoped after creation, so the generic
    # "immutable once set" NULL -> value allowance core.
    # enforce_immutable_columns() gives every other nullable identity column
    # it protects (rules.features, revision 033) is deliberately *not*
    # applied here — NULL is a real, permanent value for this column, not a
    # not-yet-set placeholder.
    for schema, table, trigger_name, columns in (
        (
            "security",
            "campaign_memberships",
            "tr_campaign_memberships_enforce_immutable",
            ["campaign_id"],
        ),
        ("security", "access_groups", "tr_access_groups_enforce_immutable", ["campaign_id"]),
        ("campaign", "sessions", "tr_sessions_enforce_immutable", ["campaign_id"]),
        (
            "narrative",
            "events",
            "tr_events_enforce_immutable",
            ["campaign_id", "timeline_id"],
        ),
    ):
        args = ", ".join(f"'{c}'" for c in columns)
        op.execute(f"""
            CREATE TRIGGER {trigger_name}
            BEFORE UPDATE ON {schema}.{table}
            FOR EACH ROW EXECUTE FUNCTION core.enforce_immutable_columns({args});
        """)

    # security.roles.campaign_id: a dedicated, NULL-inclusive guard. Unlike
    # every other reverse-mutation guard above, NULL is not "not yet set" —
    # it is the permanent value identifying a system-template role usable by
    # every campaign, and a value is the permanent value identifying a
    # campaign-scoped one. `IS DISTINCT FROM` treats NULL/NULL as unchanged
    # and any other transition (NULL -> value, value -> NULL, or value ->
    # a different value) as a rejected mutation — so a system template can
    # never be promoted to campaign-scoped, or vice versa, after creation.
    op.execute("""
        CREATE OR REPLACE FUNCTION security.enforce_roles_campaign_immutable()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.campaign_id IS DISTINCT FROM OLD.campaign_id THEN
                RAISE EXCEPTION
                    'security.roles.campaign_id is immutable, including NULL, and cannot '
                    'be changed once a role is created — role %',
                    OLD.role_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION security.enforce_roles_campaign_immutable() IS
        'NULL-inclusive immutability guard for security.roles.campaign_id — unlike core.'
        'enforce_immutable_columns(), a NULL -> value transition is rejected here too, '
        'since NULL (system template) is a permanent value for this column, not a '
        'not-yet-set placeholder (conventions §9.5).';
    """)
    op.execute("""
        CREATE TRIGGER tr_roles_enforce_campaign_immutable
        BEFORE UPDATE ON security.roles
        FOR EACH ROW EXECUTE FUNCTION security.enforce_roles_campaign_immutable();
    """)

    # ==========================================================================
    # 17. Protect the seeded lookup codes section 18's invariant relies upon
    # ==========================================================================
    # Section 18 (and, indirectly, security.users.lifecycle_status_id above)
    # hardcodes three lookup *codes* as semantic identifiers:
    # core.lifecycle_statuses.code = 'active' (a campaign's own status),
    # security.membership_statuses.code = 'active' (a membership's own
    # status), and security.capabilities.code = 'access.manage' (the
    # capability the retention invariant looks for). Every guard trigger
    # section 18 adds protects the *rows and relationships* that establish
    # an access manager, but none of them would fire if someone instead
    # renamed the code a hardcoded string comparison depends on directly —
    # core.lifecycle_statuses is a plain lookup table like any other, with
    # no trigger anywhere (before this section) stopping `UPDATE core.
    # lifecycle_statuses SET code = 'renamed' WHERE code = 'active'`. That
    # rename would silently make every `code = 'active'` comparison in
    # section 18 stop matching campaign rows that a moment ago were
    # unambiguously active, with no retention trigger ever firing, because
    # none of them are triggered by an UPDATE to a lookup table's own code
    # column. This closes that gap directly: renaming the specific seeded
    # rows these comparisons depend on is rejected outright, while every
    # other column on the same rows (display_name, description, sort_order,
    # is_active, and — since this is the only column guarded — any other
    # row's code) remains freely editable.
    #
    # The existing ux_<table>_code UNIQUE constraint on every lookup table
    # already prevents a *second* row from being renamed to collide with a
    # still-existing 'active'/'access.manage' row, so protecting only the
    # original seeded row (not every row in these tables) is sufficient:
    # freeing up the code by renaming the seeded row away is exactly what
    # this section blocks, and without that first step there is no way to
    # reassign the code elsewhere.
    op.execute("""
        CREATE OR REPLACE FUNCTION core.enforce_protected_lookup_codes()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.code IS DISTINCT FROM OLD.code AND OLD.code = ANY(TG_ARGV) THEN
                RAISE EXCEPTION
                    '%.%''s code % is a protected semantic identifier relied upon by '
                    'name and cannot be renamed',
                    TG_TABLE_SCHEMA, TG_TABLE_NAME, OLD.code
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;

            RETURN NEW;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION core.enforce_protected_lookup_codes() IS
        'Generic guard rejecting UPDATEs that rename a lookup row whose code (matched '
        'against the trigger''s own arguments) is relied upon as a semantic identifier '
        'by hardcoded string comparisons elsewhere, rather than only by foreign-key ID '
        '(conventions §11.1 names IDs as the normal reference; this is the documented '
        'exception). Every other column on the same row remains freely editable. Attach '
        'with the protected code(s) as trigger arguments, the same shape as core.'
        'enforce_immutable_columns(''<column>'').';
    """)
    for schema, table, trigger_name, codes in (
        ("core", "lifecycle_statuses", "tr_lifecycle_statuses_enforce_protected_codes", ["active"]),
        (
            "security",
            "membership_statuses",
            "tr_membership_statuses_enforce_protected_codes",
            ["active"],
        ),
        (
            "security",
            "capabilities",
            "tr_capabilities_enforce_protected_codes",
            ["access.manage"],
        ),
    ):
        args = ", ".join(f"'{c}'" for c in codes)
        op.execute(f"""
            CREATE TRIGGER {trigger_name}
            BEFORE UPDATE ON {schema}.{table}
            FOR EACH ROW EXECUTE FUNCTION core.enforce_protected_lookup_codes({args});
        """)

    # ==========================================================================
    # 18. Campaign owner/access-manager retention invariant
    # ==========================================================================
    # DATABASE_MODEL.md §22 rule 19: "Every active campaign retains at least
    # one membership authorized to manage campaign ownership and access."
    # "Authorized to manage" is resolved through the same stable capability
    # vocabulary §19.7's effective-access algorithm uses generally — the
    # access.manage capability code, never a role's code or display name —
    # so this invariant stays correct even if a campaign renames or
    # reconfigures which role carries that capability. Campaign-wide
    # capabilities (access.manage, campaign.view, canon.edit, ...) are
    # granted only through security.role_capabilities in the current schema
    # — security.resource_grants always targets one of six specific
    # resources (character/entity/knowledge item/quest/session/event), never
    # the campaign as a whole, so there is no "campaign-wide resource grant"
    # path that could remove this capability; if a future migration adds one,
    # extend security.campaign_has_access_manager() accordingly.
    #
    # A membership counts as an effective owner/access-manager only while
    # its own status is the *active row* of security.membership_statuses —
    # both code = 'active' ("suspended is an open but non-authorizing
    # status", §19.2) and that row's own is_active, decided explicitly: an
    # inactive lookup row does not authorize, even one whose code still
    # reads 'active', the same rule already applied to security.roles.
    # is_active here. Its membership_roles grant must be neither revoked
    # nor *expiring* (expires_at IS NOT NULL), via a role that is itself
    # active and either a system template or scoped to the campaign being
    # checked, granting a capability that is both code = 'access.manage'
    # and — the same explicit decision, applied the same way —
    # security.capabilities.is_active. core.lifecycle_statuses.is_active
    # (the campaign's own status row) is deliberately *not* part of this
    # decision — see deliberate scoping decisions for why that one nullable
    # dimension is treated differently from the two above.
    #
    # expires_at IS NOT NULL is excluded outright, not compared against
    # now(), and this is deliberate, not an oversight: a trigger only runs
    # in response to a write, and PostgreSQL has no mechanism to fire one
    # merely because a stored timestamp has since passed — nothing here
    # claims otherwise. A grant that "currently" satisfies `expires_at >
    # now()` at write time can silently lapse into the past with no write
    # ever happening afterward, which would make the invariant false with no
    # trigger able to observe it. The only way to keep the guarantee
    # database-backed rather than aspirational is to require a *permanent*
    # (non-expiring) qualifying grant at all times — an expiring
    # access-manager grant never counts toward satisfying the invariant, on
    # top of an active campaign or a temporary co-owner, never as its sole
    # support. This is enforced by construction (the WHERE clause below),
    # not by a comparison that could go stale.
    #
    # Enforcement covers every mutation-shaped path that can *remove* the
    # last such (non-expiring, qualifying) membership: campaign_memberships
    # status/closure changes or deletion; membership_roles revocation,
    # giving a previously non-expiring grant an expiry (the mutation, not
    # the later passage of that expiry, is what is checked — see above),
    # reassignment, or deletion; role_capabilities removing access.manage
    # from a role; security.roles is_active turned false or deletion
    # (campaign_id reparenting is separately impossible — see section 16's
    # dedicated, NULL-inclusive guard); security.capabilities and security.
    # membership_statuses is_active turned false on the specific rows this
    # invariant depends on (access.manage / active respectively — see
    # immediately below); renaming the *code* of any of those same rows,
    # or core.lifecycle_statuses' own 'active' row (section 17 — a rename
    # would silently break every hardcoded `code = '...'` comparison in
    # this section with no other trigger here able to observe it, since
    # none of them fire on an UPDATE to a lookup table's own code column);
    # and campaign.campaigns rows that are active, whether inserted active
    # directly or later transitioned into 'active' — both are checked
    # identically, so a campaign can never reach or remain in the active
    # state without a qualifying owner, not even momentarily outside the
    # same transaction that establishes one.
    #
    # Every check is expressed as a DEFERRABLE INITIALLY DEFERRED constraint
    # trigger (conventions §20.3's own named use case: "transactions that
    # must temporarily pass through an incomplete state"), so the normal
    # ownership-transfer pattern — revoke the old owner's role, grant the new
    # owner the role, both in one transaction — is checked once against the
    # final state at commit (or at an explicit `SET CONSTRAINTS ALL
    # IMMEDIATE`) rather than being rejected on the momentarily-owner-less
    # intermediate state an immediate trigger would see. This also covers
    # campaign creation: INSERTing a campaign row already active and
    # INSERTing its owning membership/role are two statements in the same
    # transaction, checked together at commit — there is no requirement
    # that the campaign be created non-active first, though creating it
    # non-active, assigning ownership, and only then transitioning it to
    # active in the same transaction works identically and may read more
    # naturally as a command-layer flow. security.
    # assert_campaign_retains_access_manager() takes a `SELECT ... FOR
    # UPDATE` lock on the campaign row before evaluating the check, so two
    # concurrent transactions each removing a *different* owning membership
    # of the same campaign cannot both independently observe "someone else
    # still has it" and both commit — the second to reach the check blocks
    # on the first's lock and then re-evaluates live, post-commit state.
    op.execute("""
        CREATE OR REPLACE FUNCTION security.campaign_has_access_manager(p_campaign_id UUID)
        RETURNS boolean
        LANGUAGE sql
        STABLE
        AS $$
            SELECT EXISTS (
                SELECT 1
                FROM security.campaign_memberships cm
                JOIN security.membership_statuses ms
                    ON ms.membership_status_id = cm.membership_status_id
                JOIN security.membership_roles mr
                    ON mr.campaign_membership_id = cm.campaign_membership_id
                JOIN security.roles r ON r.role_id = mr.role_id
                JOIN security.role_capabilities rc ON rc.role_id = r.role_id
                JOIN security.capabilities c ON c.capability_id = rc.capability_id
                WHERE cm.campaign_id = p_campaign_id
                  AND cm.ended_at IS NULL
                  AND ms.code = 'active'
                  AND ms.is_active
                  AND mr.revoked_at IS NULL
                  AND mr.expires_at IS NULL
                  AND r.is_active
                  AND (r.campaign_id IS NULL OR r.campaign_id = p_campaign_id)
                  AND c.code = 'access.manage'
                  AND c.is_active
            );
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION security.campaign_has_access_manager(UUID) IS
        'Whether campaign_id currently has at least one active membership holding a '
        'non-revoked, non-expiring (expires_at IS NULL), role-derived access.manage '
        'capability (DATABASE_MODEL.md §22 rule 19). expires_at IS NULL is required, not '
        'merely expires_at > now() — a trigger cannot fire on the passage of time alone, '
        'so only a permanent grant can be trusted to keep this true between writes; a '
        'temporary co-owner is welcome alongside one but can never be the sole support. '
        'ms.is_active and c.is_active are both required explicitly, not silently ignored '
        '— an inactive membership_statuses/capabilities lookup row does not authorize, '
        'the same rule already applied to r.is_active (security.roles) here. Pure read — '
        'callers needing the enforcement side (locking plus RAISE) use security.'
        'assert_campaign_retains_access_manager().';
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION security.assert_campaign_retains_access_manager(p_campaign_id UUID)
        RETURNS void
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_status TEXT;
        BEGIN
            IF p_campaign_id IS NULL THEN
                RETURN;
            END IF;

            -- Serializes concurrent removals of different owning memberships of
            -- the same campaign against each other (see this section's docstring).
            PERFORM 1 FROM campaign.campaigns WHERE campaign_id = p_campaign_id FOR UPDATE;

            SELECT ls.code INTO v_status
            FROM campaign.campaigns c
            JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = c.lifecycle_status_id
            WHERE c.campaign_id = p_campaign_id;

            IF v_status IS DISTINCT FROM 'active' THEN
                RETURN;
            END IF;

            IF NOT security.campaign_has_access_manager(p_campaign_id) THEN
                RAISE EXCEPTION
                    'Campaign % would be left with no membership authorized to manage its '
                    'ownership and access (capability access.manage) — every active campaign '
                    'must retain at least one (DATABASE_MODEL.md §22 rule 19)',
                    p_campaign_id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION security.assert_campaign_retains_access_manager(UUID) IS
        'Locks campaign.campaigns for p_campaign_id (FOR UPDATE, concurrency-safety — see '
        'this section''s docstring), then raises unless it is not active or security.'
        'campaign_has_access_manager() is true. Called only from DEFERRABLE INITIALLY '
        'DEFERRED constraint triggers, so it evaluates the fully-committed-within-the-'
        'transaction final state, not a momentarily incomplete one.';
    """)

    # security.campaign_memberships: status/closure changes, deletion, or
    # (defense in depth; campaign_id is immutable per section 16)
    # reparenting to a different campaign.
    op.execute("""
        CREATE OR REPLACE FUNCTION security.enforce_campaign_memberships_retain_access_manager()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP IN ('UPDATE', 'DELETE') THEN
                PERFORM security.assert_campaign_retains_access_manager(OLD.campaign_id);
            END IF;

            IF TG_OP = 'UPDATE' AND NEW.campaign_id IS DISTINCT FROM OLD.campaign_id THEN
                PERFORM security.assert_campaign_retains_access_manager(NEW.campaign_id);
            END IF;

            RETURN NULL;
        END;
        $$;
    """)
    op.execute("""
        CREATE CONSTRAINT TRIGGER tr_campaign_memberships_retain_access_manager
        AFTER UPDATE OR DELETE ON security.campaign_memberships
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION security.enforce_campaign_memberships_retain_access_manager();
    """)

    # security.membership_roles: revocation, expiration-relevant mutation,
    # reassignment, or deletion.
    op.execute("""
        CREATE OR REPLACE FUNCTION security.enforce_membership_roles_retain_access_manager()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_old_campaign  UUID;
            v_new_campaign  UUID;
        BEGIN
            IF TG_OP IN ('UPDATE', 'DELETE') THEN
                SELECT campaign_id INTO v_old_campaign
                FROM security.campaign_memberships
                WHERE campaign_membership_id = OLD.campaign_membership_id;

                PERFORM security.assert_campaign_retains_access_manager(v_old_campaign);
            END IF;

            IF TG_OP = 'UPDATE' THEN
                SELECT campaign_id INTO v_new_campaign
                FROM security.campaign_memberships
                WHERE campaign_membership_id = NEW.campaign_membership_id;

                IF v_new_campaign IS DISTINCT FROM v_old_campaign THEN
                    PERFORM security.assert_campaign_retains_access_manager(v_new_campaign);
                END IF;
            END IF;

            RETURN NULL;
        END;
        $$;
    """)
    op.execute("""
        CREATE CONSTRAINT TRIGGER tr_membership_roles_retain_access_manager
        AFTER UPDATE OR DELETE ON security.membership_roles
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION security.enforce_membership_roles_retain_access_manager();
    """)

    # security.role_capabilities: removing access.manage from a role — for a
    # system-template role (campaign_id IS NULL), every campaign currently
    # relying on it must be checked, not just one.
    op.execute("""
        CREATE OR REPLACE FUNCTION security.enforce_role_capabilities_retain_access_manager()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_capability_code  TEXT;
            v_role_campaign    UUID;
            v_campaign_id      UUID;
        BEGIN
            SELECT code INTO v_capability_code
            FROM security.capabilities WHERE capability_id = OLD.capability_id;

            IF v_capability_code IS DISTINCT FROM 'access.manage' THEN
                RETURN NULL;
            END IF;

            SELECT campaign_id INTO v_role_campaign
            FROM security.roles WHERE role_id = OLD.role_id;

            IF v_role_campaign IS NOT NULL THEN
                PERFORM security.assert_campaign_retains_access_manager(v_role_campaign);
            ELSE
                FOR v_campaign_id IN
                    SELECT DISTINCT cm.campaign_id
                    FROM security.campaign_memberships cm
                    JOIN security.membership_roles mr
                        ON mr.campaign_membership_id = cm.campaign_membership_id
                    WHERE mr.role_id = OLD.role_id
                      AND cm.ended_at IS NULL
                      AND mr.revoked_at IS NULL
                LOOP
                    PERFORM security.assert_campaign_retains_access_manager(v_campaign_id);
                END LOOP;
            END IF;

            RETURN NULL;
        END;
        $$;
    """)
    op.execute("""
        CREATE CONSTRAINT TRIGGER tr_role_capabilities_retain_access_manager
        AFTER UPDATE OR DELETE ON security.role_capabilities
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION security.enforce_role_capabilities_retain_access_manager();
    """)

    # security.capabilities: deactivating (is_active -> false) the
    # access.manage row itself — decided explicitly, not silently ignored:
    # an inactive capability does not authorize (campaign_has_access_manager()
    # requires c.is_active), so deactivation must be checked the same way
    # removing access.manage from a role is checked immediately above. The
    # code itself can never change (section 17), so OLD.code is a stable
    # identity check here; every campaign relying on access.manage through
    # *any* role (there can be more than one, and access.manage can only
    # ever belong to the single row with that code, so this is a search
    # across every role that currently carries it, not per-role like the
    # role_capabilities trigger above) must be re-checked.
    op.execute("""
        CREATE OR REPLACE FUNCTION security.enforce_capabilities_retain_access_manager()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_campaign_id  UUID;
        BEGIN
            IF NEW.is_active IS NOT DISTINCT FROM OLD.is_active OR NEW.is_active THEN
                RETURN NULL;
            END IF;

            IF OLD.code IS DISTINCT FROM 'access.manage' THEN
                RETURN NULL;
            END IF;

            FOR v_campaign_id IN
                SELECT DISTINCT cm.campaign_id
                FROM security.campaign_memberships cm
                JOIN security.membership_roles mr
                    ON mr.campaign_membership_id = cm.campaign_membership_id
                JOIN security.role_capabilities rc ON rc.role_id = mr.role_id
                WHERE rc.capability_id = OLD.capability_id
                  AND cm.ended_at IS NULL
                  AND mr.revoked_at IS NULL
            LOOP
                PERFORM security.assert_campaign_retains_access_manager(v_campaign_id);
            END LOOP;

            RETURN NULL;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION security.enforce_capabilities_retain_access_manager() IS
        'Guard for security.capabilities: deactivating the access.manage row (is_active '
        '-> false) is checked exactly like removing it from a role, since an inactive '
        'capability does not authorize (security.campaign_has_access_manager()).';
    """)
    op.execute("""
        CREATE CONSTRAINT TRIGGER tr_capabilities_retain_access_manager
        AFTER UPDATE ON security.capabilities
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION security.enforce_capabilities_retain_access_manager();
    """)

    # security.membership_statuses: deactivating (is_active -> false) the
    # 'active' row itself — the same reasoning and same explicit decision as
    # capabilities immediately above, applied to the other lookup
    # campaign_has_access_manager() now checks is_active on
    # (ms.is_active). Every campaign with a membership currently on this
    # exact status row must be re-checked; membership_status_id is not
    # itself reparentable per membership (it can change per row, but that
    # is covered by the campaign_memberships trigger already, not here —
    # this trigger only concerns the *lookup row* being deactivated).
    op.execute("""
        CREATE OR REPLACE FUNCTION security.enforce_membership_statuses_retain_access_manager()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_campaign_id  UUID;
        BEGIN
            IF NEW.is_active IS NOT DISTINCT FROM OLD.is_active OR NEW.is_active THEN
                RETURN NULL;
            END IF;

            IF OLD.code IS DISTINCT FROM 'active' THEN
                RETURN NULL;
            END IF;

            FOR v_campaign_id IN
                SELECT DISTINCT cm.campaign_id
                FROM security.campaign_memberships cm
                WHERE cm.membership_status_id = OLD.membership_status_id
                  AND cm.ended_at IS NULL
            LOOP
                PERFORM security.assert_campaign_retains_access_manager(v_campaign_id);
            END LOOP;

            RETURN NULL;
        END;
        $$;
    """)
    op.execute("""
        COMMENT ON FUNCTION security.enforce_membership_statuses_retain_access_manager() IS
        'Guard for security.membership_statuses: deactivating the ''active'' row '
        '(is_active -> false) is checked, since an inactive status row does not '
        'authorize a membership that references it (security.'
        'campaign_has_access_manager()) even though its code is still ''active''.';
    """)
    op.execute("""
        CREATE CONSTRAINT TRIGGER tr_membership_statuses_retain_access_manager
        AFTER UPDATE ON security.membership_statuses
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION security.enforce_membership_statuses_retain_access_manager();
    """)

    # security.roles: is_active turned false, campaign_id reparented (defense
    # in depth — already structurally impossible per section 16), or
    # deletion (already blocked by membership_roles' ON DELETE RESTRICT
    # whenever the role is actually in use, so this is a no-op in practice).
    op.execute("""
        CREATE OR REPLACE FUNCTION security.enforce_roles_retain_access_manager()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_campaign_id  UUID;
        BEGIN
            IF TG_OP = 'UPDATE'
               AND NEW.campaign_id IS NOT DISTINCT FROM OLD.campaign_id
               AND NEW.is_active IS NOT DISTINCT FROM OLD.is_active THEN
                RETURN NULL;
            END IF;

            IF OLD.campaign_id IS NOT NULL THEN
                PERFORM security.assert_campaign_retains_access_manager(OLD.campaign_id);
            ELSE
                FOR v_campaign_id IN
                    SELECT DISTINCT cm.campaign_id
                    FROM security.campaign_memberships cm
                    JOIN security.membership_roles mr
                        ON mr.campaign_membership_id = cm.campaign_membership_id
                    WHERE mr.role_id = OLD.role_id
                      AND cm.ended_at IS NULL
                      AND mr.revoked_at IS NULL
                LOOP
                    PERFORM security.assert_campaign_retains_access_manager(v_campaign_id);
                END LOOP;
            END IF;

            IF TG_OP = 'UPDATE'
               AND NEW.campaign_id IS DISTINCT FROM OLD.campaign_id
               AND NEW.campaign_id IS NOT NULL THEN
                PERFORM security.assert_campaign_retains_access_manager(NEW.campaign_id);
            END IF;

            RETURN NULL;
        END;
        $$;
    """)
    op.execute("""
        CREATE CONSTRAINT TRIGGER tr_roles_retain_access_manager
        AFTER UPDATE OR DELETE ON security.roles
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION security.enforce_roles_retain_access_manager();
    """)

    # campaign.campaigns: an INSERT whose row is active (directly, not via a
    # later transition) requires an owner to already exist by commit — or,
    # since this is deferred, to be added later in the *same* transaction —
    # exactly like a later transition into 'active' does. Neither case is
    # optional: a campaign created active with zero qualifying memberships
    # is exactly as ownerless as one that later loses its last one, and
    # DATABASE_MODEL.md §22 rule 19 does not carve out an exception for how
    # the campaign came to be active. assert_campaign_retains_access_manager()
    # re-reads live status itself, so the unconditional PERFORM on INSERT is
    # correct even when a later statement in the same transaction changes
    # the campaign away from active before commit. Leaving 'active' on
    # UPDATE relaxes the invariant and needs no check.
    op.execute("""
        CREATE OR REPLACE FUNCTION security.enforce_campaigns_retain_access_manager()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            v_new_status  TEXT;
        BEGIN
            IF TG_OP = 'INSERT' THEN
                PERFORM security.assert_campaign_retains_access_manager(NEW.campaign_id);
                RETURN NULL;
            END IF;

            IF NEW.lifecycle_status_id IS NOT DISTINCT FROM OLD.lifecycle_status_id THEN
                RETURN NULL;
            END IF;

            SELECT code INTO v_new_status
            FROM core.lifecycle_statuses WHERE lifecycle_status_id = NEW.lifecycle_status_id;

            IF v_new_status = 'active' THEN
                PERFORM security.assert_campaign_retains_access_manager(NEW.campaign_id);
            END IF;

            RETURN NULL;
        END;
        $$;
    """)
    op.execute("""
        CREATE CONSTRAINT TRIGGER tr_campaigns_retain_access_manager
        AFTER INSERT OR UPDATE ON campaign.campaigns
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION security.enforce_campaigns_retain_access_manager();
    """)

    # ==========================================================================
    # 19. Seed the lookups
    # ==========================================================================
    apply_seed(op, "security", "membership_statuses")
    apply_seed(op, "security", "character_relationship_types")
    apply_seed(op, "security", "capabilities")

    # security.roles has no plain UNIQUE(code) constraint to serve as an
    # apply_seed() ON CONFLICT (code) arbiter — system-template uniqueness is
    # the partial index ux_roles_system_code (WHERE campaign_id IS NULL), so
    # the conflict target's predicate must be given explicitly. Seeded
    # directly rather than through database/seeds/ for that reason. Vocabulary
    # only (§19.3) — no default security.role_capabilities matrix beyond the
    # one pairing section 17's invariant structurally requires to exist (see
    # immediately below); the rest of that matrix is still deferred, see this
    # revision's "Deliberate scoping decisions".
    op.execute("""
        INSERT INTO security.roles (campaign_id, code, display_name, sort_order)
        VALUES
            (NULL, 'campaign_owner', 'Campaign Owner', 10),
            (NULL, 'gm', 'GM', 20),
            (NULL, 'assistant_gm', 'Assistant GM', 30),
            (NULL, 'player', 'Player', 40),
            (NULL, 'observer', 'Observer', 50),
            (NULL, 'import_reviewer', 'Import Reviewer', 60),
            (NULL, 'rules_curator', 'Rules Curator', 70)
        ON CONFLICT (code) WHERE campaign_id IS NULL DO NOTHING;
    """)

    # The one role_capabilities pairing section 17's retention invariant
    # needs to be satisfiable at all: without it, campaign_has_access_manager()
    # would return false for every campaign, and every covered mutation on an
    # active campaign would unconditionally fail. campaign_owner is the
    # system-template role every campaign can use for this by construction.
    op.execute("""
        INSERT INTO security.role_capabilities (role_id, capability_id)
        SELECT r.role_id, c.capability_id
        FROM security.roles r, security.capabilities c
        WHERE r.code = 'campaign_owner' AND r.campaign_id IS NULL
          AND c.code = 'access.manage'
        ON CONFLICT (role_id, capability_id) DO NOTHING;
    """)


def downgrade() -> None:
    """Revert the migration."""

    # Reverse-mutation-invariant, retention, and protected-code triggers on
    # pre-existing tables this revision does not own (campaign.campaigns,
    # campaign.sessions, narrative.events, core.lifecycle_statuses) — must
    # be dropped explicitly here; the DROP TABLE statements below only
    # remove triggers on tables this revision itself created.
    op.execute("DROP TRIGGER IF EXISTS tr_campaigns_retain_access_manager ON campaign.campaigns;")
    op.execute("DROP TRIGGER IF EXISTS tr_events_enforce_immutable ON narrative.events;")
    op.execute("DROP TRIGGER IF EXISTS tr_sessions_enforce_immutable ON campaign.sessions;")
    op.execute(
        "DROP TRIGGER IF EXISTS tr_lifecycle_statuses_enforce_protected_codes "
        "ON core.lifecycle_statuses;"
    )

    op.execute("DROP TABLE IF EXISTS security.resource_grants;")
    op.execute("DROP FUNCTION IF EXISTS security.enforce_resource_grant_scope();")

    op.execute("DROP TABLE IF EXISTS security.access_group_memberships;")
    op.execute("DROP FUNCTION IF EXISTS security.enforce_access_group_membership_scope();")

    op.execute("DROP TABLE IF EXISTS security.access_groups;")

    op.execute("DROP TABLE IF EXISTS security.character_relationship_type_capabilities;")

    op.execute("DROP TABLE IF EXISTS security.membership_character_relationships;")
    op.execute(
        "DROP FUNCTION IF EXISTS security.enforce_membership_character_relationship_scope();"
    )

    op.execute("DROP TABLE IF EXISTS security.membership_roles;")
    op.execute("DROP FUNCTION IF EXISTS security.enforce_membership_role_scope();")

    op.execute("DROP TABLE IF EXISTS security.role_capabilities;")
    op.execute("DROP TABLE IF EXISTS security.roles;")

    op.execute("DROP TABLE IF EXISTS security.campaign_invitations;")
    op.execute("DROP TABLE IF EXISTS security.campaign_memberships;")

    op.execute("DROP TABLE IF EXISTS security.service_accounts;")
    op.execute("DROP TABLE IF EXISTS security.external_identities;")

    # Reshape security.users back to its revision-003 shape. Real usernames
    # cannot be reconstructed (none exist in the target environment) — a
    # placeholder is synthesized per row so the NOT NULL/UNIQUE constraints
    # below can be restored structurally.
    op.execute("DROP INDEX IF EXISTS security.ix_users_lifecycle_status_id;")
    op.execute("ALTER TABLE security.users DROP COLUMN lifecycle_status_id;")
    op.execute("ALTER TABLE security.users DROP COLUMN last_login_at;")
    op.execute("ALTER TABLE security.users ADD COLUMN username TEXT;")
    op.execute("UPDATE security.users SET username = 'user_' || user_id WHERE username IS NULL;")
    op.execute("ALTER TABLE security.users ALTER COLUMN username SET NOT NULL;")
    op.execute("""
        ALTER TABLE security.users
        ADD CONSTRAINT ux_users_username UNIQUE (username);
    """)
    op.execute("""
        ALTER TABLE security.users
        ADD CONSTRAINT ck_users_username_length CHECK (char_length(username) BETWEEN 1 AND 100);
    """)
    op.execute("ALTER TABLE security.users ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT true;")
    op.execute("""
        COMMENT ON TABLE security.users IS
        'A person who can author or approve world content. Authentication itself '
        'is handled outside the database; this is identity for attribution and '
        'authorization.';
    """)

    # Recreate the old security.roles / security.user_roles pair verbatim
    # (revision 003's shape) so the downgrade chain lands where 003 left it.
    op.execute("""
        CREATE TABLE security.roles (
            role_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            code          TEXT NOT NULL,
            display_name  TEXT NOT NULL,
            description   TEXT,
            sort_order    core.nonnegative_integer NOT NULL DEFAULT 0,
            is_active     BOOLEAN NOT NULL DEFAULT true,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ux_roles_code UNIQUE (code),
            CONSTRAINT ck_roles_code_format CHECK (code ~ '^[a-z][a-z0-9_]*$')
        );
    """)
    op.execute("""
        COMMENT ON TABLE security.roles IS
        'Platform-level role a user can hold. Intentionally unseeded: the role '
        'vocabulary is not yet specified in the domain docs, and inventing it '
        'here would preempt that decision.';
    """)
    op.execute("""
        CREATE TRIGGER tr_roles_set_updated_at
        BEFORE UPDATE ON security.roles
        FOR EACH ROW EXECUTE FUNCTION core.set_updated_at();
    """)
    op.execute("""
        CREATE TABLE security.user_roles (
            user_id             UUID NOT NULL
                                REFERENCES security.users(user_id) ON DELETE CASCADE,
            role_id             UUID NOT NULL
                                REFERENCES security.roles(role_id) ON DELETE RESTRICT,
            granted_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            granted_by_user_id  UUID REFERENCES security.users(user_id) ON DELETE SET NULL,
            PRIMARY KEY (user_id, role_id)
        );
    """)
    op.execute("""
        COMMENT ON TABLE security.user_roles IS
        'Role assignment. ON DELETE RESTRICT against roles so a role in use '
        'cannot be removed out from under its holders.';
    """)
    op.execute("CREATE INDEX ix_user_roles_role_id ON security.user_roles (role_id);")
    op.execute(
        "CREATE INDEX ix_user_roles_granted_by_user_id ON security.user_roles (granted_by_user_id);"
    )

    op.execute("DROP TABLE IF EXISTS security.capabilities;")
    op.execute("DROP TABLE IF EXISTS security.character_relationship_types;")
    op.execute("DROP TABLE IF EXISTS security.membership_statuses;")

    # Functions are not owned by any table and survive DROP TABLE, so drop
    # them explicitly now that every trigger that referenced them (on tables
    # this revision created) is already gone with its table, and the three
    # pre-existing-table triggers were already dropped at the top of this
    # function.
    op.execute("DROP FUNCTION IF EXISTS security.enforce_campaigns_retain_access_manager();")
    op.execute("DROP FUNCTION IF EXISTS security.enforce_roles_retain_access_manager();")
    op.execute(
        "DROP FUNCTION IF EXISTS security.enforce_role_capabilities_retain_access_manager();"
    )
    op.execute("DROP FUNCTION IF EXISTS security.enforce_membership_roles_retain_access_manager();")
    op.execute(
        "DROP FUNCTION IF EXISTS security.enforce_campaign_memberships_retain_access_manager();"
    )
    op.execute("DROP FUNCTION IF EXISTS security.assert_campaign_retains_access_manager(UUID);")
    op.execute("DROP FUNCTION IF EXISTS security.campaign_has_access_manager(UUID);")
    op.execute("DROP FUNCTION IF EXISTS security.enforce_campaign_invitation_actor_scope();")
    op.execute("DROP FUNCTION IF EXISTS security.enforce_campaign_membership_actor_scope();")
    op.execute("DROP FUNCTION IF EXISTS security.enforce_roles_campaign_immutable();")
    op.execute("DROP FUNCTION IF EXISTS security.enforce_capabilities_retain_access_manager();")
    op.execute(
        "DROP FUNCTION IF EXISTS security.enforce_membership_statuses_retain_access_manager();"
    )
    op.execute("DROP FUNCTION IF EXISTS core.enforce_protected_lookup_codes();")
