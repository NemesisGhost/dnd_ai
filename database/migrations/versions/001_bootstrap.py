"""Bootstrap database: extensions, schemas, roles

Revision ID: 001_bootstrap
Revises:
Create Date: 2026-07-31 00:00:00.000000

Purpose:
    Bootstrap the database with essential infrastructure required before any domain
    tables can be created: PostgreSQL extensions, the thirteen bounded schemas, public
    schema protection, and the six database roles.

Forward migration:
    - Enable pgcrypto and pg_trgm extensions (vector deferred until embeddings)
    - Create thirteen bounded schemas per docs/PLAN.md §3
    - Revoke public schema CREATE privilege per docs/DATABASE_CONVENTIONS.md §3.1
    - Create six database roles per docs/DATABASE_CONVENTIONS.md §27.1, split
      into one owning role and five login roles:
      * migration_owner   — NOLOGIN. Owns every schema object. Never authenticates.
      * migration_runner  — LOGIN. Runs migrations as a member of migration_owner.
      * app_read_write    — LOGIN. Application runtime; DML only
      * app_read_only     — LOGIN. Reporting and read models
      * integration_worker — LOGIN. Scoped for Foundry/Discord/import services
      * admin_maintenance — LOGIN. Break-glass human access
    - Grant rds_iam to the five LOGIN roles only, where rds_iam exists (RDS
      only — skipped on local/CI PostgreSQL). migration_owner is deliberately
      excluded; see the role-model note in section 4 below.
    - Set up schema ownership and default privileges

Rollback:
    Supported in development. Drops roles, schemas, and extensions, except the
    `core` schema itself, which is left in place (empty of domain objects) because
    it holds Alembic's own version table (version_table_schema = "core").
    DO NOT run downgrade against a database with data — schema CASCADE will destroy it.

    Roles are cluster-wide and are kept, not dropped, when another database on
    the same instance still references them — see the note in downgrade().

Data implications:
    None. This is the first revision; the database is empty.

Locking considerations:
    None. No tables exist yet.

See: docs/PLAN.md §29.5 (Database bootstrap requirements)
     docs/DATABASE_CONVENTIONS.md §27.1 (Database roles)
     docs/DEVELOPMENT.md §5 (Phase 1 walkthrough)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "001_bootstrap"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply the bootstrap migration."""

    # ==========================================================================
    # 1. Extensions
    # ==========================================================================
    # pgcrypto: UUID generation (gen_random_uuid)
    # pg_trgm: Trigram similarity for text search
    # vector: Deferred until embedding subsystem per docs/PLAN.md §4.1

    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")

    # ==========================================================================
    # 2. Schemas
    # ==========================================================================
    # All thirteen bounded schemas from docs/PLAN.md §3
    # No domain tables go in public per docs/DATABASE_CONVENTIONS.md §3.1

    schemas = [
        ("core", "Worlds, entities, names, sources, statuses, tags, calendars, world time"),
        ("security", "Users, roles, permissions, access-control policies"),
        ("rules", "Rulesets and reusable mechanical definitions"),
        ("character", "Shared character mechanics plus NPC and PC extensions"),
        ("world", "Locations, organizations, items, relationships, economies, religions"),
        ("campaign", "Timelines, campaigns, parties, sessions, effective mutable state"),
        ("narrative", "Events, quests, objectives, encounters, story arcs"),
        ("knowledge", "Facts, rumors, beliefs, discoveries, expertise, information transfer"),
        ("interaction", "Player, GM, Foundry, Discord, and AI actions and resolutions"),
        ("ai", "Agents, context assembly, prompt fragments, embeddings, proposals"),
        ("audit", "Change history, approvals, validation errors, agent activity"),
        ("import", "Staging and review for future campaign-data imports"),
        ("integration", "External-system identifiers, sync state, webhook or polling metadata"),
    ]

    for schema_name, comment in schemas:
        op.execute(f"CREATE SCHEMA IF NOT EXISTS {schema_name};")
        op.execute(f"COMMENT ON SCHEMA {schema_name} IS '{comment}';")

    # ==========================================================================
    # 3. Public schema protection
    # ==========================================================================
    # Prevent accidental table creation in public
    # Alembic's version table already lives in core per alembic.ini

    op.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC;")

    # ==========================================================================
    # 4. Database roles
    # ==========================================================================
    # Six roles per docs/DATABASE_CONVENTIONS.md §27.1, split into one role that
    # OWNS objects and five roles that LOG IN. See ADR 0009 for the full
    # rationale; the short version, because it is easy to "simplify" back into
    # a bug:
    #
    #   On RDS, granting `rds_iam` to a role forces IAM authentication for that
    #   role and permanently disables password auth for it. Role membership is
    #   transitive, so if migration_owner held rds_iam, then granting
    #   migration_owner to the RDS master user (which the ownership transfer in
    #   section 5 below requires) would silently lock the master user out of
    #   password authentication — every subsequent connection failing with
    #   "PAM authentication failed". That is not hypothetical: it happened on a
    #   real instance and is what motivated this split.
    #
    #   Keeping migration_owner NOLOGIN and rds_iam-free makes it a pure
    #   ownership anchor that can be granted to anyone safely, because there is
    #   no authentication behavior to inherit.
    #
    # Role model:
    #   migration_owner    NOLOGIN. Owns every schema object. Never authenticates.
    #   migration_runner   LOGIN. Member of migration_owner; runs migrations.
    #   app_read_write     LOGIN. Application runtime; DML on owned schemas
    #   app_read_only      LOGIN. SELECT only
    #   integration_worker LOGIN. Scoped to integration schema plus minimal others
    #   admin_maintenance  LOGIN. Break-glass, all privileges

    # The owning role: no LOGIN, and deliberately never granted rds_iam.
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'migration_owner') THEN
                CREATE ROLE migration_owner WITH NOLOGIN;
            END IF;
        END
        $$;
    """)

    # The login roles. rds_iam only exists on RDS; locally and in CI (plain
    # postgres:15) the role is absent, so the grant is conditional rather than
    # failing the bootstrap on non-RDS PostgreSQL.
    for role_name in (
        "migration_runner",
        "app_read_write",
        "app_read_only",
        "integration_worker",
        "admin_maintenance",
    ):
        op.execute(f"""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '{role_name}') THEN
                    CREATE ROLE {role_name} WITH LOGIN;
                END IF;
            END
            $$;
        """)
        op.execute(f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'rds_iam') THEN
                    GRANT rds_iam TO {role_name};
                END IF;
            END
            $$;
        """)

    # migration_runner executes migrations but must not own what it creates —
    # objects are owned by migration_owner so that a compromised or rotated
    # runner identity never owns canon (§27.2). env.py issues SET ROLE
    # migration_owner after connecting to make that happen.
    op.execute("GRANT migration_owner TO migration_runner;")

    # The connecting role (the RDS master user, or `postgres` locally) also
    # needs membership before it can transfer schema ownership to
    # migration_owner or set default privileges "FOR ROLE migration_owner"
    # below — neither statement is permitted otherwise, even for the RDS master
    # user, which is rds_superuser rather than a true superuser and gets no
    # implicit membership in roles it creates. Verified against a real RDS
    # instance: without this, section 5 fails with
    # "must be member of role migration_owner".
    #
    # This grant is only safe because migration_owner carries no rds_iam.
    op.execute("GRANT migration_owner TO CURRENT_USER;")

    # Later revisions run as migration_owner (see section 7), so it — not the
    # connecting role — is what needs privileges for anything they create. That
    # includes extensions: revision 009 installs btree_gist for the party
    # membership exclusion constraint, and without this it fails with
    # "permission denied to create extension btree_gist" even when the
    # connecting user is the RDS master.
    #
    # CREATE on the database is sufficient rather than superuser because
    # btree_gist, pgcrypto, and pg_trgm are all *trusted* extensions on
    # PostgreSQL 13+ (verified as trusted on the dev instance, 15.18). A
    # non-superuser may install a trusted extension with only this privilege,
    # which is why the roles never need rds_superuser.
    # The database name is not known statically — ephemeral test databases are
    # named dnd_ai_test_<random> — so it is resolved at run time.
    op.execute("""
        DO $$
        BEGIN
            EXECUTE format(
                'GRANT CREATE ON DATABASE %I TO migration_owner', current_database()
            );
        END
        $$;
    """)

    # ==========================================================================
    # 5. Schema ownership and default privileges
    # ==========================================================================
    # migration_owner owns all schema objects
    # Future tables/sequences/functions created by migration_owner automatically
    # grant appropriate privileges to application roles

    for schema_name, _ in schemas:
        # Transfer schema ownership to migration_owner
        op.execute(f"ALTER SCHEMA {schema_name} OWNER TO migration_owner;")

        # Default privileges: future tables by migration_owner
        op.execute(f"""
            ALTER DEFAULT PRIVILEGES FOR ROLE migration_owner IN SCHEMA {schema_name}
            GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_read_write;
        """)

        op.execute(f"""
            ALTER DEFAULT PRIVILEGES FOR ROLE migration_owner IN SCHEMA {schema_name}
            GRANT SELECT ON TABLES TO app_read_only;
        """)

        # Default privileges: future sequences by migration_owner
        op.execute(f"""
            ALTER DEFAULT PRIVILEGES FOR ROLE migration_owner IN SCHEMA {schema_name}
            GRANT USAGE, SELECT ON SEQUENCES TO app_read_write;
        """)

        op.execute(f"""
            ALTER DEFAULT PRIVILEGES FOR ROLE migration_owner IN SCHEMA {schema_name}
            GRANT SELECT ON SEQUENCES TO app_read_only;
        """)

    # Integration worker: scoped to integration schema plus minimal read access
    op.execute("""
        ALTER DEFAULT PRIVILEGES FOR ROLE migration_owner IN SCHEMA integration
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO integration_worker;
    """)

    # admin_maintenance: all privileges on all schemas
    for schema_name, _ in schemas:
        op.execute(f"GRANT ALL PRIVILEGES ON SCHEMA {schema_name} TO admin_maintenance;")
        op.execute(f"""
            ALTER DEFAULT PRIVILEGES FOR ROLE migration_owner IN SCHEMA {schema_name}
            GRANT ALL PRIVILEGES ON TABLES TO admin_maintenance;
        """)
        op.execute(f"""
            ALTER DEFAULT PRIVILEGES FOR ROLE migration_owner IN SCHEMA {schema_name}
            GRANT ALL PRIVILEGES ON SEQUENCES TO admin_maintenance;
        """)

    # ==========================================================================
    # 6. Let migration_owner write Alembic's own bookkeeping table
    # ==========================================================================
    # Alembic creates core.alembic_version itself, before any revision's
    # upgrade() runs, using whatever role was active at connection time — so on
    # a database this bootstrap revision is creating from scratch, that table
    # is owned by the connecting user (dnd_admin on RDS), not migration_owner.
    # Once section 7 below switches the session to migration_owner for the
    # rest of the run, Alembic's own post-migration write to that table would
    # otherwise fail with "permission denied for table alembic_version" —
    # verified against a real RDS instance. Table-level grants survive
    # ownership transfers elsewhere in this file, so this only needs stating
    # once, here, regardless of how many revisions run after it.
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON core.alembic_version TO migration_owner;")

    # ==========================================================================
    # 7. Become migration_owner for the rest of this run
    # ==========================================================================
    # PostgreSQL assigns ownership from the CURRENT role, not from inherited
    # membership — so without this, every object created by later revisions in
    # this same `alembic upgrade` would be owned by whoever connected, and the
    # ALTER DEFAULT PRIVILEGES entries above (which are keyed to
    # migration_owner) would never fire.
    #
    # env.py issues the same SET ROLE on connect for runs where this revision
    # has already been applied; this one covers the remainder of a run that
    # starts from an empty database. downgrade() resets it.
    op.execute("SET ROLE migration_owner;")


def downgrade() -> None:
    """Revert the bootstrap migration."""

    # WARNING: Only safe on empty development databases
    # Running this on a database with data will CASCADE destroy everything

    # Stop being migration_owner (set either by upgrade() above or by env.py on
    # connect) — a role cannot be dropped while it is the current role, and the
    # cleanup below has to run as the connecting user.
    op.execute("RESET ROLE;")

    # Drop schemas (CASCADE removes all contained objects).
    # `core` is deliberately excluded: version_table_schema = "core" (alembic.ini),
    # so core.alembic_version lives inside it. Alembic writes to that table
    # immediately after this function returns to record the downgrade — dropping
    # the schema here would drop the table out from under that write. By this
    # point 002's downgrade has already removed the domains it added to core,
    # so core is left holding only Alembic's own bookkeeping table.
    schemas = [
        "security",
        "rules",
        "character",
        "world",
        "campaign",
        "narrative",
        "knowledge",
        "interaction",
        "ai",
        "audit",
        "import",
        "integration",
    ]
    for schema_name in schemas:
        op.execute(f"DROP SCHEMA IF EXISTS {schema_name} CASCADE;")

    # Restore public schema CREATE privilege
    op.execute("GRANT CREATE ON SCHEMA public TO PUBLIC;")

    # `core` survives (see above), so migration_owner still owns it and
    # admin_maintenance still holds grants on it. PostgreSQL refuses to drop a
    # role that owns objects or is the grantee of surviving privileges, so both
    # have to be unwound before the DROP ROLE calls below.
    op.execute("ALTER SCHEMA core OWNER TO CURRENT_USER;")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'admin_maintenance') THEN
                REVOKE ALL PRIVILEGES ON SCHEMA core FROM admin_maintenance;
            END IF;
        END
        $$;
    """)

    # Clear migration_owner's remaining privilege and default-privilege entries.
    # REASSIGN first so anything it still owns changes hands rather than being
    # dropped; DROP OWNED then removes only the grants. Both require membership
    # in migration_owner, which upgrade() granted to CURRENT_USER.
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'migration_owner') THEN
                EXECUTE format('REASSIGN OWNED BY migration_owner TO %I', CURRENT_USER);
                DROP OWNED BY migration_owner;
            END IF;
        END
        $$;
    """)

    # Drop roles. migration_runner is dropped before migration_owner because it
    # is a member of it.
    #
    # These roles are CLUSTER-WIDE, unlike everything else this revision
    # creates — every database on the instance shares one set of roles, while
    # schemas, tables, and grants are per-database. So on a shared instance
    # another database may still own objects or hold grants referencing them,
    # and PostgreSQL refuses:
    #
    #   role "integration_worker" cannot be dropped because some objects
    #   depend on it
    #   DETAIL:  1 object in database dnd_ai
    #
    # That dependency lives in a *different* database, so the REASSIGN OWNED
    # and DROP OWNED above cannot clear it — both only ever affect the current
    # database, and there is no cross-database equivalent. This is exactly the
    # situation the ephemeral per-run test databases in docs/PLAN.md §29.9
    # create: CI downgrades its throwaway database to base while dev's main
    # database is still at head.
    #
    # Keeping the role in that case is the correct outcome — it is still in
    # use. On a single-database instance the drop succeeds and the downgrade
    # remains a true inverse.
    roles = [
        "integration_worker",
        "app_read_only",
        "app_read_write",
        "admin_maintenance",
        "migration_runner",
        "migration_owner",
    ]
    for role in roles:
        op.execute(f"""
            DO $$
            BEGIN
                DROP ROLE IF EXISTS {role};
            EXCEPTION
                WHEN dependent_objects_still_exist THEN
                    RAISE NOTICE
                        'Kept cluster-wide role % — still referenced from another database.',
                        '{role}';
            END
            $$;
        """)

    # Drop extensions
    op.execute("DROP EXTENSION IF EXISTS pg_trgm;")
    op.execute("DROP EXTENSION IF EXISTS pgcrypto;")
