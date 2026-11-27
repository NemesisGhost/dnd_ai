"""P15-C11-S02-T01: the shape of the control-assignment routes' R01 registration, and F33.

Structural pins (no database): the three keyed routes are registered with declarations that take their locks in
the approved class order (plan section 3.1, ADR 0021 section 2.8 mapped onto the R01 class order), declare every
write with the stated cardinality, and never pass a controller scope to a canonical command. F33 pins the
capability separation of S01 section 3.2 item 3a: assignment authority is read from the built-in role rows only,
never from assignment-derived or clock-derived capabilities.
"""

import inspect
import re
import uuid
from datetime import UTC, datetime

import pytest

from dnd_ai.api.r01_pre_write_routes import R01_KEYED_PRE_WRITE_ROUTES
from dnd_ai.commands import control_assignment_plans as plans
from dnd_ai.domain import access as access_module
from dnd_ai.domain.access import (
    CONTROL_ASSIGNMENT_CAPABILITIES,
    AccessContext,
    AuthoritySnapshot,
    ControlAssignmentSource,
)
from dnd_ai.domain.authorization_steps import EachLockedRow, Exactly, PerEvidence

ASSIGN = ("POST", "/campaigns/{campaign_id}/characters/{character_id}/control-assignments")
REPLACE = (
    "POST",
    "/campaigns/{campaign_id}/characters/{character_id}/control-assignments/replace-primary",
)
REVOKE = ("POST", "/campaigns/{campaign_id}/control-assignments/{control_assignment_id}/revoke")

# the approved class order, lowest first (access_grant_plans module docstring; S5-E2 C1-C4, S5-E4 AO-1)
_CLASS_RANK = {
    "authority_row": 1,  # role rows (the caller's built-in owner or gm row)
    "membership": 3,
    "account": 4,
    "campaign": 5,
    "catalogue": 6,
    "target": 7,
    "dependent": 8,
    "leaf_target": 9,
}


def _names(declaration: object) -> list[str]:
    return [lock.name for lock in declaration.locks]  # type: ignore[attr-defined]


def test_the_three_keyed_routes_are_registered_with_reserved_and_unkeyed_declarations() -> None:
    for key, declarations in (
        (ASSIGN, plans.ASSIGN_DECLARATIONS),
        (REPLACE, plans.REPLACE_DECLARATIONS),
        (REVOKE, plans.REVOKE_DECLARATIONS),
    ):
        assert R01_KEYED_PRE_WRITE_ROUTES[key] is declarations
        assert declarations.reserved is not None and declarations.unkeyed is not None
        # the keyed declaration is the unkeyed one plus the receipt lock and step, at the end
        assert _names(declarations.reserved)[:-1] == _names(declarations.unkeyed)
        assert declarations.reserved.steps[:-1] == declarations.unkeyed.steps


@pytest.mark.parametrize(
    ("declarations", "expected"),
    [
        (
            plans.ASSIGN_DECLARATIONS,
            [
                "assign_authority_row_share",
                "actor_membership_share",
                "target_membership_update",
                "actor_account_share",
                "target_account_key_share",
                "campaign_row_update",
                "control_type_key_share",
                "target_entity_update",
                "character_row_key_share",
                "character_live_assignments_update",
                "world_time_rows_key_share",
            ],
        ),
        (
            plans.REPLACE_DECLARATIONS,
            [
                "assign_authority_row_share",
                "actor_membership_share",
                "target_membership_update",
                "old_primary_membership_update",
                "actor_account_share",
                "target_account_key_share",
                "campaign_row_update",
                "control_type_key_share",
                "target_entity_update",
                "character_row_key_share",
                "character_live_assignments_update",
                "world_time_rows_key_share",
            ],
        ),
        (
            plans.REVOKE_DECLARATIONS,
            [
                "assign_authority_row_share",
                "actor_membership_share",
                "target_membership_update",
                "actor_account_share",
                "campaign_row_update",
                "target_entity_update",
                "assignment_row_update",
            ],
        ),
    ],
    ids=["assign", "replace", "revoke"],
)
def test_each_declaration_names_its_locks_in_the_section_3_sequence(
    declarations: object, expected: list[str]
) -> None:
    """The plan's lock sequence: authority row, memberships, accounts, campaign, catalogue, the character anchor,
    its live assignment rows, world times. Pinned by name and order."""
    assert _names(declarations.unkeyed) == expected  # type: ignore[attr-defined]


def test_the_lock_sequence_never_inverts_the_class_order() -> None:
    def rank(name: str) -> int:
        if name.startswith("assign_authority"):
            return _CLASS_RANK["authority_row"]
        if "membership" in name:
            return _CLASS_RANK["membership"]
        if "account" in name:
            return _CLASS_RANK["account"]
        if name.startswith("campaign"):
            return _CLASS_RANK["campaign"]
        if name.startswith("control_type"):
            return _CLASS_RANK["catalogue"]
        if name in {"target_entity_update", "character_row_key_share"}:
            return _CLASS_RANK["target"]
        if name == "world_time_rows_key_share":
            return _CLASS_RANK[
                "leaf_target"
            ]  # plan section 3.1 step 9, after the character's dependent rows
        return _CLASS_RANK["dependent"]

    for declarations in (
        plans.ASSIGN_DECLARATIONS,
        plans.REPLACE_DECLARATIONS,
        plans.REVOKE_DECLARATIONS,
    ):
        ranks = [rank(name) for name in _names(declarations.unkeyed)]
        assert ranks == sorted(ranks), _names(declarations.unkeyed)


def test_the_writes_are_declared_with_their_cardinalities() -> None:
    assign = {s.name: s for s in plans.ASSIGN_DECLARATIONS.unkeyed.steps}
    assert isinstance(assign["insert_control_assignment"].cardinality, Exactly)
    assert isinstance(assign["audit_control_assigned"].cardinality, Exactly)
    replace = {s.name: s for s in plans.REPLACE_DECLARATIONS.unkeyed.steps}
    assert isinstance(replace["revoke_old_primary"].cardinality, Exactly)
    assert isinstance(replace["insert_replacing_primary"].cardinality, Exactly)
    assert isinstance(replace["audit_primary_revoked"].cardinality, Exactly)
    assert isinstance(replace["audit_primary_assigned"].cardinality, Exactly)
    revoke = {s.name: s for s in plans.REVOKE_DECLARATIONS.unkeyed.steps}
    assert isinstance(revoke["revoke_control_assignment"].cardinality, EachLockedRow)
    assert revoke["revoke_control_assignment"].cardinality.complete is True
    assert isinstance(revoke["audit_control_revoked"].cardinality, PerEvidence)


def test_the_assignment_inserts_name_both_assignment_indexes_as_competing_waits() -> None:
    """S01 contract 5: S02's INSERT really enters `live_primary` (primary only) and `live_assignment`; each is a
    competing wait with its own race test, and the legacy `active_type` index is one it never enters."""
    for step in (
        plans.ASSIGN_DECLARATIONS.unkeyed.steps[0],
        plans.REPLACE_DECLARATIONS.unkeyed.steps[1],
    ):
        waits = {w.index: w.competitor_test for w in step.unique_waits}
        primary = waits["security.ux_membership_character_relationships_live_primary"]
        assignment = waits["security.ux_membership_character_relationships_live_assignment"]
        assert primary.endswith("test_a_competing_live_primary_is_a_unique_wait")
        assert assignment.endswith("test_a_competing_live_assignment_is_a_unique_wait")
        legacy = waits["security.ux_membership_character_relationships_active_type"]
        assert legacy.endswith("test_an_assignment_insert_never_waits_on_the_legacy_index")


def test_no_route_passes_a_controller_scope_to_a_canonical_command() -> None:
    """C20 owns controller operations; nothing here takes `lock_controller_operation_scope` or a scope argument."""
    from dnd_ai.api import control_assignments as api

    for module in (plans, api):
        source = inspect.getsource(module)
        assert not re.search(r"controller_operation|controller_scope|lock_controller", source)


# --- F33 --------------------------------------------------------------------------------------------------------


def _rich_access() -> AccessContext:
    """Everything an assignment can confer, and a clock, with no owner, gm or delegation source."""
    character = uuid.uuid4()
    return AccessContext(
        user_id=uuid.uuid4(),
        campaign_id=uuid.uuid4(),
        campaign_membership_id=uuid.uuid4(),
        timeline_id=uuid.uuid4(),
        role_capabilities=frozenset({"campaign.view", "canon.edit", "access.manage"}),
        character_capabilities={
            character: frozenset().union(*CONTROL_ASSIGNMENT_CAPABILITIES.values())
        },
        grant_effects={},
        campaign_lifecycle_status="active",
        revelations={},
        control_assignments={
            character: ControlAssignmentSource(uuid.uuid4(), "primary_controller", "ongoing")
        },
        control_clock_key=1_000,
    )


def _snapshot(authority: str, row: uuid.UUID | None = None) -> AuthoritySnapshot:
    return AuthoritySnapshot(
        t_auth=datetime.now(UTC),
        isolation="read committed",
        access=_rich_access(),
        assign_control_authority=authority,  # type: ignore[arg-type]
        assign_control_row=row,
    )


def test_f33_assignment_derived_and_clock_derived_capabilities_never_confer_assign_authority() -> (
    None
):
    campaign, membership = uuid.uuid4(), uuid.uuid4()
    requirement = plans.assign_control_requirement(campaign, membership)
    assert requirement.assign_control is True
    # a context holding every matrix code, live assignments and a clock, with authority source none: refused
    assert requirement.predicate(_snapshot("none")) is False
    assert isinstance(requirement.refusal(), plans.AssignControlRequiredError)
    for source in ("campaign_owner", "gm"):
        assert plans.assign_control_requirement(campaign, membership).predicate(
            _snapshot(source, uuid.uuid4())
        )


def test_f33_the_authority_sql_names_no_clock_table_and_no_assignment_output() -> None:
    sql = access_module._ASSIGN_CONTROL_CTES + access_module._ASSIGN_CONTROL_COLUMNS
    for forbidden in (
        "timeline_clocks",
        "world_times",
        "campaign_clock",
        "asgn",
        "control_assignment",
        "is_control_assignment",
        "membership_character_relationships",
        "character_capabilities",
        "role_capabilities",
        "resource_grants",
    ):
        assert forbidden not in sql, forbidden


def test_f33_the_requirement_reads_only_the_authority_fields_of_the_snapshot() -> None:
    source = inspect.getsource(plans.assign_control_requirement)
    assert "snapshot.access" not in source
    assert "control_assignments" not in source and "control_clock_key" not in source
    assert "character_capabilities" not in source and "has_capability" not in source
