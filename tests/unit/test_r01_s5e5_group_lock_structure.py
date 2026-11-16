"""R01 S5-E5 correction (AO-1, SA-1; finding NF-1): the structure of the group-row lock order (correction design T-9).

The invariant: **a transaction that holds a group row never waits for a role-row or delegation-row lock.** Every group locker
therefore takes its actor's role rows first, and the group row before memberships, accounts and the campaign. Two pins:

1. the group-grantee branch of `prepare_create_grant` (and its declaration) takes the actor's role rows before the group row;
2. the set of modules that contain a statement locking `security.access_groups` is exactly the inventoried one, so a new group
   locker is a deliberate, reviewed addition (it must follow the order above and be added here).
"""

import inspect
import re
from pathlib import Path

import pytest

from dnd_ai.commands import access_grant_plans as plans

pytestmark = pytest.mark.unit

SRC = Path(plans.__file__).resolve().parents[1]
#: Modules with a statement that locks an `access_groups` row, as of the S5-E5 correction. `access_group_plans.py` (S5-E5's routes)
#: joins this set with that slice and must keep the order.
GROUP_LOCKERS = {
    "commands/access_grant_plans.py",  # the S5-E4 group-grantee grant (corrected: role rows, then the group)
    "commands/access_grants.py",  # the legacy `create_resource_grant` command (no route)
    "commands/access_groups.py",  # the six legacy group commands (routes migrate in S5-E5)
    "commands/character_revelations.py",  # revelation creation: authority role rows, then the group `FOR KEY SHARE`
}
_SQL_LOCK = re.compile(
    r"(?:FROM|JOIN)\s+security\.access_groups\b[^;]{0,600}?FOR\s+(?:KEY\s+SHARE|NO\s+KEY\s+UPDATE|UPDATE|SHARE)",
    re.DOTALL,
)
_CORE_LOCK = re.compile(r"select\(access_groups\.c.{0,500}?with_for_update", re.DOTALL)


def test_the_group_grantee_branch_takes_the_actor_role_rows_before_the_group_row() -> None:
    source = inspect.getsource(plans.prepare_create_grant)
    assert source.index("ACTOR_ROLES_LOCK") < source.index("GROUP_GRANTEE_LOCK")
    # the group row precedes the membership class, the accounts and the campaign
    for later in (
        "lock_memberships(",
        "ACTOR_MEMBERSHIP_LOCK",
        "ACTOR_ACCOUNT_LOCK",
        "CAMPAIGN_ROW_LOCK",
    ):
        assert source.index("GROUP_GRANTEE_LOCK") < source.index(later), later


def test_the_declared_lock_order_of_the_create_grant_has_the_role_rows_before_the_group_row() -> (
    None
):
    for declaration in (
        plans.CREATE_GRANT_DECLARATIONS.reserved,
        plans.CREATE_GRANT_DECLARATIONS.unkeyed,
    ):
        assert declaration is not None
        locks = list(declaration.locks)
        assert locks.index(plans.ACTOR_ROLES_LOCK) < locks.index(plans.GROUP_GRANTEE_LOCK)
        assert locks.index(plans.GROUP_GRANTEE_LOCK) < locks.index(plans.ACTOR_MEMBERSHIP_LOCK)
        assert locks.index(plans.GROUP_GRANTEE_LOCK) < locks.index(plans.CAMPAIGN_ROW_LOCK)


def test_no_group_lock_is_called_before_the_actor_role_lock_in_any_plan_module() -> None:
    """Every function of a plan module that locks a group row calls the actor-role lock first (the sources are read in text order)."""
    for module in (plans,):
        for name, function in inspect.getmembers(module, inspect.isfunction):
            if function.__module__ != module.__name__:
                continue
            source = inspect.getsource(function)
            if "GROUP_GRANTEE_LOCK" in source and "plan.lock(" in source:
                assert "ACTOR_ROLES_LOCK" in source, name
                assert source.index("ACTOR_ROLES_LOCK") < source.index("GROUP_GRANTEE_LOCK"), name


def test_the_modules_that_lock_an_access_group_row_are_exactly_the_inventoried_ones() -> None:
    found = {
        path.relative_to(SRC).as_posix()
        for path in SRC.rglob("*.py")
        if _SQL_LOCK.search(path.read_text(encoding="utf-8"))
        or _CORE_LOCK.search(path.read_text(encoding="utf-8"))
    }
    assert found == GROUP_LOCKERS, found ^ GROUP_LOCKERS
