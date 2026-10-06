"""Add entity source links and the authorable source types

Revision ID: 134_entity_source_links
Revises: 133_item_runtime_events
Create Date: 2026-10-07 09:00:00.000000

Purpose:
    Phase 15 checkpoint 15.3C-1 (decision D-26). Every authored entity cites the one source it
    was created from (`core.entities.source_id`, a `gm_entry`). A GM also needs to attach further
    sources to it later (a published rulebook page, a homebrew document, session notes) and to
    detach one that no longer applies, keeping the history of both. This revision adds
    `core.entity_source_links` for that, and the three source types a GM can author beside
    `gm_entry`: `published_reference`, `homebrew_document` and `session_notes`.

    A link is never edited except to detach it once (`detached_at` and `detached_by_user_id`
    set together); a detached source can be attached again as a new link. At most one active link
    per entity and source. A source must belong to the entity's world (a source with no world,
    such as a shared rulebook, is also accepted by the database; the authoring commands attach
    world-owned sources only).

Forward migration:
    - `core.entity_source_links`, its indexes, the world guard, and the detach-only update guard
    - three `core.source_types` rows (explicit INSERT; `database/seeds/core.source_types.yaml`
      is revision 003's frozen input and is not edited)

Rollback:
    Supported: drops the table and deletes the three source types by code. The delete fails
    (foreign key) once any source uses one, which is the safe outcome; downgrade is intended for
    development databases.

Data implications:
    A new empty table and three lookup rows.

Locking considerations:
    A new table and a small lookup insert; nothing existing is rewritten.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "134_entity_source_links"
down_revision = "133_item_runtime_events"
branch_labels = None
depends_on = None

_SOURCE_TYPES = [
    ("published_reference", "Published Reference", "A page or section of a published book.", 110),
    ("homebrew_document", "Homebrew Document", "A homebrew rules or setting document.", 120),
    ("session_notes", "Session Notes", "Notes taken at or after a play session.", 130),
]


def upgrade() -> None:
    for code, name, description, order in _SOURCE_TYPES:
        op.execute(f"""
            INSERT INTO core.source_types (code, display_name, description, sort_order, is_active)
            VALUES ('{code}', '{name}', '{description}', {order}, true)
            ON CONFLICT (code) DO NOTHING;
        """)
    op.execute("""
        CREATE TABLE core.entity_source_links (
            entity_source_link_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            entity_id              UUID NOT NULL
                                   REFERENCES core.entities(entity_id) ON DELETE CASCADE,
            source_id              UUID NOT NULL
                                   REFERENCES core.sources(source_id) ON DELETE RESTRICT,
            attached_by_user_id    UUID REFERENCES security.users(user_id) ON DELETE SET NULL,
            attached_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
            detached_by_user_id    UUID REFERENCES security.users(user_id) ON DELETE SET NULL,
            detached_at            TIMESTAMPTZ,
            CONSTRAINT ck_entity_source_links_detached_after_attached CHECK (
                detached_at IS NULL OR detached_at >= attached_at
            )
        );
    """)
    op.execute("""
        COMMENT ON TABLE core.entity_source_links IS
        'A source attached to an entity after its creation (the creation source stays on '
        'core.entities.source_id). A link is detached by setting detached_at once and is never '
        'otherwise changed or deleted, so the history of what was cited and when is kept. '
        'Never part of a player read.';
    """)
    op.execute("""
        COMMENT ON COLUMN core.entity_source_links.detached_at IS
        'When the source was detached; NULL while it is attached.';
    """)
    op.execute(
        "CREATE UNIQUE INDEX ux_entity_source_links_active "
        "ON core.entity_source_links (entity_id, source_id) WHERE detached_at IS NULL;"
    )
    op.execute(
        "CREATE INDEX ix_entity_source_links_source_id ON core.entity_source_links (source_id);"
    )
    op.execute(
        "CREATE INDEX ix_entity_source_links_attached_by_user_id "
        "ON core.entity_source_links (attached_by_user_id) WHERE attached_by_user_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX ix_entity_source_links_detached_by_user_id "
        "ON core.entity_source_links (detached_by_user_id) WHERE detached_by_user_id IS NOT NULL;"
    )
    op.execute("""
        CREATE FUNCTION core.enforce_entity_source_link()
        RETURNS trigger LANGUAGE plpgsql AS $fn$
        DECLARE
            v_entity_world UUID;
            v_source_world UUID;
        BEGIN
            IF TG_OP = 'INSERT' THEN
                SELECT world_id INTO v_entity_world
                FROM core.entities WHERE entity_id = NEW.entity_id;
                SELECT world_id INTO v_source_world
                FROM core.sources WHERE source_id = NEW.source_id;
                IF v_source_world IS NOT NULL AND v_source_world IS DISTINCT FROM v_entity_world THEN
                    RAISE EXCEPTION 'Source % belongs to another world than entity %',
                        NEW.source_id, NEW.entity_id
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
                IF NEW.detached_at IS NOT NULL THEN
                    RAISE EXCEPTION 'A source link starts attached'
                        USING ERRCODE = 'integrity_constraint_violation';
                END IF;
                RETURN NEW;
            END IF;
            -- UPDATE: only the one-time detach.
            IF OLD.detached_at IS NOT NULL
               OR NEW.entity_id IS DISTINCT FROM OLD.entity_id
               OR NEW.source_id IS DISTINCT FROM OLD.source_id
               OR NEW.attached_at IS DISTINCT FROM OLD.attached_at
               OR NEW.attached_by_user_id IS DISTINCT FROM OLD.attached_by_user_id
               OR NEW.detached_at IS NULL THEN
                RAISE EXCEPTION 'A source link can only be detached, once'
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END;
        $fn$;
    """)
    op.execute("""
        CREATE TRIGGER tr_entity_source_links_guard
        BEFORE INSERT OR UPDATE ON core.entity_source_links
        FOR EACH ROW EXECUTE FUNCTION core.enforce_entity_source_link();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS tr_entity_source_links_guard ON core.entity_source_links;")
    op.execute("DROP FUNCTION IF EXISTS core.enforce_entity_source_link();")
    op.execute("DROP TABLE IF EXISTS core.entity_source_links;")
    codes = ", ".join(f"'{code}'" for code, _, _, _ in _SOURCE_TYPES)
    op.execute(f"DELETE FROM core.source_types WHERE code IN ({codes});")
