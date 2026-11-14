"""R01 S5-A inventory: which statements lock `security.users`, and in which mode.

`FOR KEY SHARE` on a target account protects the status the command reads only because every writer of
that status takes the row `FOR UPDATE` first (a bare `UPDATE` takes `FOR NO KEY UPDATE`, which does not
conflict with `FOR KEY SHARE`). These tests pin both halves from source, with no database:

- the six access-management commands read the target account `FOR KEY SHARE OF u`, and none of them
  names `FOR UPDATE OF u`;
- the one in-app writer of `security.users.lifecycle_status_id` locks the row `FOR UPDATE` before the
  `UPDATE`;
- the only modules that lock a `security.users` row `FOR UPDATE` are the account-administration
  commands, so no access-management command regained the stronger lock.
"""

import ast
import inspect
from pathlib import Path

import pytest

from dnd_ai.commands import access_grants, access_groups, local_auth, memberships

SRC = Path(memberships.__file__).resolve().parent.parent

TARGET_ACCOUNT_COMMANDS = (
    memberships.assign_membership_role,
    memberships.add_campaign_member,
    access_grants.grant_character_relationship,
    access_grants.change_character_relationship,
    access_grants.create_resource_grant,
    access_groups.add_access_group_members,
)

# The account-administration commands, whose `FOR UPDATE` on the account row is the other half of the
# protection (they must stay as strong as they are): deactivation/reactivation and administrator
# promotion (`local_auth`), system-role changes (`system_roles`).
ACCOUNT_ADMINISTRATION_MODULES = {"local_auth.py", "system_roles.py"}


def _strings(source: str) -> list[str]:
    """The SQL statements of a module or function: string literals that start like one (a docstring
    that names a table or a lock mode is not a statement)."""
    return [
        node.value
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value.lstrip().upper().startswith(("SELECT", "UPDATE", "INSERT", "WITH"))
    ]


@pytest.mark.parametrize("command", TARGET_ACCOUNT_COMMANDS, ids=lambda c: c.__name__)
def test_a_target_account_command_reads_the_account_for_key_share(command: object) -> None:
    statements = [
        text
        for text in _strings(inspect.getsource(command))  # type: ignore[arg-type]
        if "security.users" in text and "FOR " in text
    ]
    assert len(statements) == 1, statements
    assert "FOR KEY SHARE OF u" in statements[0]
    assert "FOR UPDATE" not in statements[0]


def test_the_status_writer_locks_the_account_for_update_before_it_updates_it() -> None:
    source = inspect.getsource(local_auth._set_local_account_lifecycle_status_impl)
    lock = source.index("FOR UPDATE OF u")
    update = source.index("UPDATE security.users SET lifecycle_status_id")
    assert lock < update


def test_no_other_in_app_statement_updates_an_accounts_lifecycle_status() -> None:
    writers = sorted(
        str(path.relative_to(SRC))
        for path in SRC.rglob("*.py")
        if any(
            "UPDATE security.users" in text and "lifecycle_status_id" in text
            for text in _strings(path.read_text(encoding="utf-8"))
        )
    )
    assert writers == [str(Path("commands") / "local_auth.py")]


def test_only_account_administration_locks_an_account_row_for_update() -> None:
    holders = sorted(
        path.name
        for path in SRC.rglob("*.py")
        if any(
            "security.users" in text and "FOR UPDATE" in text
            for text in _strings(path.read_text(encoding="utf-8"))
        )
    )
    assert set(holders) <= ACCOUNT_ADMINISTRATION_MODULES, holders
    assert holders, "the account-administration locks this protection relies on are gone"
