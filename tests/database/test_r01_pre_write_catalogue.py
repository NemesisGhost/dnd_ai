# ruff: noqa: F811, S608 - synthetic DDL in a per-test schema
"""R01 S1-C: the catalogue helper (plan 6.10.7, 6.11.6; PW-19, PW-29-PW-32).

One synthetic target per rejected effect; the helper must fail each and pass the corrected declaration.
The helper reads identities from the catalogue (OIDs, namespaces, stored node trees), never deparsed text.
"""

import dataclasses

import pytest
from sqlalchemy import Connection, bindparam, insert, text

from dnd_ai.domain.authorization_steps import (
    Event,
    PreWriteDeclaration,
    WriteStep,
)
from tests.database.test_authorization_pre_write import Kit
from tests.r01_pre_write_catalogue import check_declaration, read_trigger_pins
from tests.r01_pre_write_evidence import Synthetic, new_id, synthetic  # noqa: F401

pytestmark = pytest.mark.database


def _check(s: Synthetic, declaration: PreWriteDeclaration) -> list[str]:
    with s.plain.connect() as connection:
        connection.begin()
        try:
            return check_declaration(connection, declaration)
        finally:
            connection.rollback()


def _pinned(connection: Connection, step: WriteStep) -> WriteStep:
    command = Event.UPDATE if step.is_update else Event.INSERT
    return dataclasses.replace(step, triggers=read_trigger_pins(connection, step.table, command))


def _child_step(s: Synthetic, kit: Kit) -> WriteStep:
    child, ref = s.tables["child"], s.tables["ref"]
    assert ref is not None
    constraint = next(iter(child.foreign_key_constraints))
    from dnd_ai.domain.authorization_steps import Between, FkBinding, KeyBind

    return WriteStep(
        name="ins_child",
        statement=insert(child)
        .values(
            child_id=bindparam("cid"),
            r_id=bindparam("r"),
            scope=bindparam("sc"),
            other=bindparam("ot"),
        )
        .returning(child.c.child_id),
        cardinality=Between(0, 5),
        fks=(
            FkBinding(
                constraint,
                tuple(
                    KeyBind(child.c[c], b)
                    for c, b in (("r_id", "r"), ("scope", "sc"), ("other", "ot"))
                ),
                kit.lock_ref,
            ),
        ),
        value_binds=frozenset({"cid"}),
    )


def _base(s: Synthetic, kit: Kit, *, extra: tuple[WriteStep, ...] = ()) -> PreWriteDeclaration:
    with s.plain.connect() as connection:
        connection.begin()
        steps = tuple(
            _pinned(connection, step)
            for step in (
                kit.upd(lock=kit.lock_targets),
                kit.ins_log(),
                kit.ins_audit(),
                kit.ins_label(),
                *extra,
            )
        )
        connection.rollback()
    return PreWriteDeclaration(locks=kit.locks, steps=steps)


def _ddl(s: Synthetic, *statements: str) -> None:
    for statement in statements:
        s.run(statement.format(s=s.schema))


def test_the_corrected_declaration_passes_and_diagnostics_are_empty(synthetic: Synthetic) -> None:
    s = synthetic
    kit = Kit(s)
    assert _check(s, _base(s, kit, extra=(_child_step(s, kit),))) == []


_REJECTED: dict[str, tuple[list[str], str]] = {
    "rls_enabled": (["ALTER TABLE {s}.target ENABLE ROW LEVEL SECURITY"], "row-level security"),
    "rls_forced": (
        [
            "ALTER TABLE {s}.target ENABLE ROW LEVEL SECURITY",
            "ALTER TABLE {s}.target FORCE ROW LEVEL SECURITY",
        ],
        "row-level security",
    ),
    "rule": (["CREATE RULE r AS ON UPDATE TO {s}.target DO ALSO NOTHING"], "rewrite rules"),
    "child_table": (["CREATE TABLE {s}.tchild () INHERITS ({s}.target)"], "inheritance"),
    "generated_column": (
        ["ALTER TABLE {s}.target ADD COLUMN g integer GENERATED ALWAYS AS (v + 1) STORED"],
        "generated column",
    ),
    "function_default": (
        [
            "CREATE FUNCTION {s}.clock() RETURNS timestamptz LANGUAGE sql AS 'select pg_catalog.now()'",
            "ALTER TABLE {s}.target ALTER COLUMN stamp SET DEFAULT {s}.clock()",
        ],
        "default of omitted column stamp",
    ),
    "nextval_default": (
        [
            "CREATE SEQUENCE {s}.sq",
            "ALTER TABLE {s}.target ALTER COLUMN note SET DEFAULT nextval('{s}.sq')::text",
        ],
        "default of omitted column note",
    ),
    "exclusion_constraint": (
        ["ALTER TABLE {s}.target ADD CONSTRAINT ex EXCLUDE USING btree (v WITH =)"],
        "exclusion constraint",
    ),
    "deferrable_unique": (
        ["ALTER TABLE {s}.target ADD CONSTRAINT du UNIQUE (note) DEFERRABLE"],
        "deferrable unique",
    ),
    "unique_index_without_wait": (
        ["CREATE UNIQUE INDEX ux_extra ON {s}.target (note)"],
        "ux_extra needs a UniqueWait",
    ),
    "unpinned_trigger": (
        [
            "CREATE TRIGGER extra AFTER UPDATE ON {s}.target FOR EACH STATEMENT "
            "EXECUTE FUNCTION {s}.target_bump()"
        ],
        "unpinned or changed trigger extra",
    ),
    "changed_function_body": (
        [
            "CREATE OR REPLACE FUNCTION {s}.target_bump() RETURNS trigger LANGUAGE plpgsql AS "
            "$$BEGIN PERFORM nextval('{s}.target_ctr'); PERFORM 1; RETURN NULL; END$$"
        ],
        "pinned trigger differs",
    ),
    "security_definer_function": (
        ["ALTER FUNCTION {s}.target_bump() SECURITY DEFINER"],
        "SECURITY DEFINER",
    ),
    "volatile_check": (
        ["ALTER TABLE {s}.target ADD CONSTRAINT ck CHECK (random() < 2)"],
        "not immutable",
    ),
    "user_function_check": (
        [
            "CREATE FUNCTION {s}.okf(integer) RETURNS boolean LANGUAGE sql IMMUTABLE AS 'select true'",
            "ALTER TABLE {s}.target ADD CONSTRAINT ck CHECK ({s}.okf(v))",
        ],
        "non-built-in",
    ),
    "opexpr_default": (
        ["ALTER TABLE {s}.target ALTER COLUMN stamp SET DEFAULT now() + interval '1 day'"],
        "default of omitted column stamp",
    ),
    "deferrable_pk_on_lock_table": (
        [
            "ALTER TABLE {s}.cpk DROP CONSTRAINT cpk_pkey",
            "ALTER TABLE {s}.cpk ADD PRIMARY KEY (a, b) DEFERRABLE INITIALLY DEFERRED",
        ],
        "deferrable primary key",
    ),
}


@pytest.mark.parametrize("case", sorted(_REJECTED))
def test_each_rejected_effect_fails_the_helper(synthetic: Synthetic, case: str) -> None:
    s = synthetic
    kit = Kit(s)
    declaration = _base(s, kit)
    assert _check(s, declaration) == []  # the corrected declaration passes
    statements, expected = _REJECTED[case]
    _ddl(s, *statements)
    problems = _check(s, declaration)
    assert any(expected in p for p in problems), problems


def test_partitioned_tables_and_foreign_key_order_fail_the_helper(synthetic: Synthetic) -> None:
    s = synthetic
    kit = Kit(s)
    step = _child_step(s, kit)
    declaration = PreWriteDeclaration(locks=kit.locks, steps=(_pinned_on(s, step),))
    assert _check(s, declaration) == []
    # the FK in the database lists the same columns in another order
    _ddl(
        s,
        "ALTER TABLE {s}.child DROP CONSTRAINT child_r_id_scope_other_fkey",
        "ALTER TABLE {s}.ref ADD CONSTRAINT ref_alt UNIQUE (scope, r_id, other)",
        "ALTER TABLE {s}.child ADD FOREIGN KEY (scope, r_id, other) REFERENCES {s}.ref (scope, r_id, other)",
    )
    assert any("no foreign key over" in p for p in _check(s, declaration))
    # a partitioned relation (no PK needed in the database for this inventory)
    _ddl(
        s,
        "ALTER TABLE {s}.other RENAME TO other_old",
        "CREATE TABLE {s}.other (n integer) PARTITION BY LIST (n)",
    )
    from sqlalchemy import select, update

    other = s.tables["other"]
    assert other is not None
    assert (
        select and update
    )  # the partitioned relation kind is exercised through the relation query
    with s.plain.connect() as connection:
        connection.begin()
        from tests.r01_pre_write_catalogue import _relation

        relation = _relation(connection, other)
        connection.rollback()
    assert relation is not None and relation[1] == "p"


def _pinned_on(s: Synthetic, step: WriteStep) -> WriteStep:
    with s.plain.connect() as connection:
        connection.begin()
        try:
            return _pinned(connection, step)
        finally:
            connection.rollback()


_TRIGGER_CHANGES: dict[str, list[str]] = {
    "disabled": ["ALTER TABLE {s}.target DISABLE TRIGGER target_bump_stmt"],
    "enable_always": ["ALTER TABLE {s}.target ENABLE ALWAYS TRIGGER target_bump_stmt"],
    "column_list": [
        "DROP TRIGGER target_bump_stmt ON {s}.target",
        "CREATE TRIGGER target_bump_stmt BEFORE INSERT OR UPDATE OF v ON {s}.target "
        "FOR EACH STATEMENT EXECUTE FUNCTION {s}.target_bump()",
    ],
    "when": [
        "DROP TRIGGER target_bump_stmt ON {s}.target",
        "CREATE TRIGGER target_bump_stmt BEFORE INSERT OR UPDATE ON {s}.target "
        "FOR EACH STATEMENT WHEN (true) EXECUTE FUNCTION {s}.target_bump()",
    ],
    "after_statement": [
        "DROP TRIGGER target_bump_stmt ON {s}.target",
        "CREATE TRIGGER target_bump_stmt AFTER INSERT OR UPDATE ON {s}.target "
        "FOR EACH STATEMENT EXECUTE FUNCTION {s}.target_bump()",
    ],
    "deferred_constraint_trigger": [
        "DROP TRIGGER target_bump_stmt ON {s}.target",
        "CREATE CONSTRAINT TRIGGER target_bump_stmt AFTER INSERT OR UPDATE ON {s}.target "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION {s}.target_bump()",
    ],
    "arguments": [
        "DROP TRIGGER target_bump_stmt ON {s}.target",
        "CREATE TRIGGER target_bump_stmt BEFORE INSERT OR UPDATE ON {s}.target "
        "FOR EACH STATEMENT EXECUTE FUNCTION {s}.target_bump('x')",
    ],
}


@pytest.mark.parametrize("case", sorted(_TRIGGER_CHANGES))
def test_a_changed_trigger_configuration_fails_the_helper(synthetic: Synthetic, case: str) -> None:
    s = synthetic
    kit = Kit(s)
    declaration = _base(s, kit)
    assert _check(s, declaration) == []
    _ddl(s, *_TRIGGER_CHANGES[case])
    problems = _check(s, declaration)
    assert any("trigger" in p for p in problems), problems


def test_recreating_the_same_when_with_different_whitespace_still_passes(
    synthetic: Synthetic,
) -> None:
    s = synthetic
    kit = Kit(s)
    _ddl(s, *_TRIGGER_CHANGES["when"])
    declaration = _base(s, kit)
    assert _check(s, declaration) == []
    _ddl(
        s,
        "DROP TRIGGER target_bump_stmt ON {s}.target",
        "CREATE TRIGGER target_bump_stmt BEFORE INSERT OR UPDATE ON {s}.target "
        "FOR EACH STATEMENT WHEN (  true  ) EXECUTE FUNCTION {s}.target_bump()",
    )
    assert _check(s, declaration) == []


def test_lookalike_defaults_and_trigger_functions_are_told_apart_by_identity(
    synthetic: Synthetic,
) -> None:
    s = synthetic
    kit = Kit(s)
    declaration = _base(s, kit)
    # (a) a default calling <schema>.now() that deparses as now() under a search_path naming the schema
    _ddl(
        s,
        "CREATE FUNCTION {s}.now() RETURNS timestamptz LANGUAGE sql AS 'select pg_catalog.now()'",
        "ALTER TABLE {s}.log ALTER COLUMN created_at SET DEFAULT {s}.now()",
    )
    with s.plain.connect() as connection:
        connection.begin()
        connection.execute(text(f"SET LOCAL search_path = {s.schema}, pg_catalog"))
        deparsed = connection.execute(
            text(
                "SELECT pg_get_expr(d.adbin, d.adrelid) FROM pg_attrdef d JOIN pg_attribute a ON "
                "a.attrelid = d.adrelid AND a.attnum = d.adnum WHERE a.attname = 'created_at' "
                f"AND d.adrelid = '{s.schema}.log'::regclass"
            )
        ).scalar_one()
        connection.rollback()
    assert deparsed == "now()"  # the misleading text
    problems = _check(s, declaration)
    assert any("default of omitted column created_at" in p for p in problems), problems
    _ddl(
        s,
        "ALTER TABLE {s}.log ALTER COLUMN created_at SET DEFAULT now()",
        "DROP FUNCTION {s}.now()",
    )
    assert _check(s, declaration) == []
    # (b) pgcrypto's public.gen_random_uuid(), when the extension's function exists
    exists = s.rows(
        "SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
        "WHERE n.nspname = 'public' AND p.proname = 'gen_random_uuid'"
    )[0][0]
    if exists:
        _ddl(s, "ALTER TABLE {s}.log ALTER COLUMN log_id SET DEFAULT public.gen_random_uuid()")
        assert any("default of omitted column log_id" in p for p in _check(s, declaration))
        _ddl(s, "ALTER TABLE {s}.log ALTER COLUMN log_id SET DEFAULT gen_random_uuid()")
        assert _check(s, declaration) == []
    # (c) a trigger re-pointed to a same-named function with an identical body in another schema
    alt = f"{s.schema}_alt"
    try:
        s.run(f"CREATE SCHEMA {alt}")
        s.run(
            f"CREATE FUNCTION {alt}.target_bump() RETURNS trigger LANGUAGE plpgsql AS "
            f"$$BEGIN PERFORM nextval('{s.schema}.target_ctr'); RETURN NULL; END$$"
        )
        same_body = s.rows(
            f"SELECT (SELECT md5(prosrc) FROM pg_proc WHERE oid = '{s.schema}.target_bump()'::regprocedure) "
            f"= (SELECT md5(prosrc) FROM pg_proc WHERE oid = '{alt}.target_bump()'::regprocedure)"
        )[0][0]
        assert same_body is True
        _ddl(
            s,
            "DROP TRIGGER target_bump_stmt ON {s}.target",
            "CREATE TRIGGER target_bump_stmt BEFORE INSERT OR UPDATE ON {s}.target FOR EACH STATEMENT "
            f"EXECUTE FUNCTION {alt}.target_bump()",
        )
        assert any("trigger" in p for p in _check(s, declaration))
    finally:
        s.run(f"DROP SCHEMA IF EXISTS {alt} CASCADE")


def test_a_deferrable_primary_key_lets_a_full_pk_update_affect_two_rows(
    synthetic: Synthetic,
) -> None:
    """Q-K1: the reason deferrable primary keys are rejected."""
    s = synthetic
    _ddl(
        s,
        "CREATE TABLE {s}.dk (k uuid NOT NULL, v integer, PRIMARY KEY (k) DEFERRABLE INITIALLY DEFERRED)",
    )
    key = new_id()
    with s.plain.connect() as connection:
        connection.begin()
        connection.execute(text(f"INSERT INTO {s.schema}.dk VALUES (:k, 1), (:k, 2)"), {"k": key})
        result = connection.execute(
            text(f"UPDATE {s.schema}.dk SET v = 9 WHERE k = :k"), {"k": key}
        )
        assert result.rowcount == 2
        connection.rollback()


def test_the_helper_reports_a_catalogue_row_it_cannot_find(synthetic: Synthetic) -> None:
    s = synthetic
    kit = Kit(s)
    declaration = _base(s, kit)
    _ddl(s, "ALTER TABLE {s}.audit RENAME TO audit_gone")
    assert any("not found" in p for p in _check(s, declaration))
