"""Bootstrap database: extensions, schemas, roles

Revision ID: 001_bootstrap
Revises: 
Create Date: 2026-07-31 00:00:00.000000

Purpose:
    Bootstrap the database with essential infrastructure required before any domain
    tables can be created: PostgreSQL extensions, the thirteen bounded schemas, public
    schema protection, and five database roles.

Forward migration:
    - Enable pgcrypto and pg_trgm extensions (vector deferred until embeddings)
    - Create thirteen bounded schemas per docs/PLAN.md §3
    - Revoke public schema CREATE privilege per docs/DATABASE_CONVENTIONS.md §3.1
    - Create five database roles per docs/DATABASE_CONVENTIONS.md §27.1:
      * migration_owner — owns schema objects; DDL only
      * app_read_write — application runtime; DML only
      * app_read_only — reporting and read models
      * integration_worker — scoped for Foundry/Discord/import services
      * admin_maintenance — break-glass human access
    - Grant rds_iam to non-migration roles for IAM database authentication
    - Set up schema ownership and default privileges

Rollback:
    Supported in development. Drops roles, schemas, and extensions.
    DO NOT run downgrade against a database with data — schema CASCADE will destroy it.

Data implications:
    None. This is the first revision; the database is empty.

Locking considerations:
    None. No tables exist yet.

See: docs/PLAN.md §29.5 (Database bootstrap requirements)
     docs/DATABASE_CONVENTIONS.md §27.1 (Database roles)
     docs/DEVELOPMENT.md §5 (Phase 1 walkthrough)
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '001_bootstrap'
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
        ('core', 'Worlds, entities, names, sources, statuses, tags, calendars, world time'),
        ('security', 'Users, roles, permissions, access-control policies'),
        ('rules', 'Rulesets and reusable mechanical definitions'),
        ('character', 'Shared character mechanics plus NPC and PC extensions'),
        ('world', 'Locations, organizations, items, relationships, economies, religions'),
        ('campaign', 'Timelines, campaigns, parties, sessions, effective mutable state'),
        ('narrative', 'Events, quests, objectives, encounters, story arcs'),
        ('knowledge', 'Facts, rumors, beliefs, discoveries, expertise, information transfer'),
        ('interaction', 'Player, GM, Foundry, Discord, and AI actions and resolutions'),
        ('ai', 'Agents, context assembly, prompt fragments, embeddings, proposals'),
        ('audit', 'Change history, approvals, validation errors, agent activity'),
        ('import', 'Staging and review for future campaign-data imports'),
        ('integration', 'External-system identifiers, sync state, webhook or polling metadata'),
    ]
    
    for schema_name, comment in schemas:
        op.execute(f"CREATE SCHEMA IF NOT EXISTS {schema_name};")
        op.execute(
            f"COMMENT ON SCHEMA {schema_name} IS '{comment}';"
        )
    
    # ==========================================================================
    # 3. Public schema protection
    # ==========================================================================
    # Prevent accidental table creation in public
    # Alembic's version table already lives in core per alembic.ini
    
    op.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC;")
    
    # ==========================================================================
    # 4. Database roles
    # ==========================================================================
    # Five roles per docs/DATABASE_CONVENTIONS.md §27.1
    # Each created WITH LOGIN and granted rds_iam for IAM database authentication
    # (except migration_owner — the migration runner authenticates as the master user)
    #
    # Role hierarchy:
    #   migration_owner: Owns all schema objects; DDL only
    #   app_read_write: Application runtime; DML on owned schemas
    #   app_read_only: SELECT only
    #   integration_worker: Scoped to integration schema plus minimal others
    #   admin_maintenance: Break-glass, all privileges
    
    # migration_owner: Owns schema objects, DDL only
    # (no rds_iam — the migration runner uses the AWS-managed master credential)
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'migration_owner') THEN
                CREATE ROLE migration_owner WITH LOGIN;
            END IF;
        END
        $$;
    """)
    
    # app_read_write: Application runtime
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'app_read_write') THEN
                CREATE ROLE app_read_write WITH LOGIN;
            END IF;
        END
        $$;
    """)
    op.execute("GRANT rds_iam TO app_read_write;")
    
    # app_read_only: Reporting and read models
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'app_read_only') THEN
                CREATE ROLE app_read_only WITH LOGIN;
            END IF;
        END
        $$;
    """)
    op.execute("GRANT rds_iam TO app_read_only;")
    
    # integration_worker: Foundry/Discord/import-facing services
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'integration_worker') THEN
                CREATE ROLE integration_worker WITH LOGIN;
            END IF;
        END
        $$;
    """)
    op.execute("GRANT rds_iam TO integration_worker;")
    
    # admin_maintenance: Break-glass human access
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'admin_maintenance') THEN
                CREATE ROLE admin_maintenance WITH LOGIN;
            END IF;
        END
        $$;
    """)
    op.execute("GRANT rds_iam TO admin_maintenance;")
    
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


def downgrade() -> None:
    """Revert the bootstrap migration."""
    
    # WARNING: Only safe on empty development databases
    # Running this on a database with data will CASCADE destroy everything
    
    # Drop schemas (CASCADE removes all contained objects)
    schemas = [
        'core', 'security', 'rules', 'character', 'world', 'campaign',
        'narrative', 'knowledge', 'interaction', 'ai', 'audit', 'import', 'integration'
    ]
    for schema_name in schemas:
        op.execute(f"DROP SCHEMA IF EXISTS {schema_name} CASCADE;")
    
    # Restore public schema CREATE privilege
    op.execute("GRANT CREATE ON SCHEMA public TO PUBLIC;")
    
    # Drop roles
    # Cannot drop if objects are owned or privileges exist
    # In practice, downgrade immediately after upgrade is safe
    # Downgrade after domain migrations requires manual REASSIGN OWNED / DROP OWNED first
    roles = ['integration_worker', 'app_read_only', 'app_read_write', 'admin_maintenance', 'migration_owner']
    for role in roles:
        op.execute(f"DROP ROLE IF EXISTS {role};")
    
    # Drop extensions
    op.execute("DROP EXTENSION IF EXISTS pg_trgm;")
    op.execute("DROP EXTENSION IF EXISTS pgcrypto;")
