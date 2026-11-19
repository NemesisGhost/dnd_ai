"""R01 S5-F correction: where the final owner requirement is registered (source shape, no database).

`final_owner_requirement` is registered with `plan.require` after the last early check: for add / assign / change only
inside the branch that the database-verified built-in `campaign_owner` role selects (`is_builtin_campaign_owner_role`),
right after the fresh-clock recheck; for the transfer once, unconditionally, after the last early check and before the
plan returns. It reads the final snapshot only: no connection, no cached liveness boolean, no new lock or statement.
"""

import inspect

from dnd_ai.commands import membership_role_plans as plans


def _order(source: str, needles: list[str]) -> None:
    last = -1
    for needle in needles:
        position = source.find(needle, last + 1)
        assert position > last, f"{needle!r} missing or out of order"
        last = position


def test_add_assign_and_change_register_it_only_for_the_builtin_owner_role_after_the_recheck() -> (
    None
):
    for function in (
        plans.prepare_add_member,
        plans.prepare_assign_role,
        plans.prepare_change_role,
    ):
        source = inspect.getsource(function)
        assert source.count("final_owner_requirement(") == 1, function.__name__
        _order(
            source,
            [
                "is_builtin_campaign_owner_role(",
                "_recheck_owner(",
                "plan.require(connection, final_owner_requirement(campaign_id, actor_membership_id))",
            ],
        )
        # it is inside the owner-role branch: the line before it is the recheck
        lines = [line.strip() for line in source.splitlines()]
        index = next(i for i, line in enumerate(lines) if "final_owner_requirement(" in line)
        assert lines[index - 1].startswith("_recheck_owner("), function.__name__


def test_the_transfer_registers_it_once_in_every_branch_after_the_last_early_check() -> None:
    source = inspect.getsource(plans.prepare_transfer)
    assert source.count("final_owner_requirement(") == 1
    _order(
        source,
        [
            "_recheck_owner(",
            "require_campaign_mode_covers_role_updates(",
            "plan.require(connection, final_owner_requirement(campaign_id, actor_membership_id))",
            "return TransferPrepared(",
        ],
    )
    registration = source.index("plan.require(connection, final_owner_requirement(")
    indent = source[:registration].splitlines()[-1]
    assert indent == "    ", "registered at function level, not inside a branch"


def test_the_requirement_reads_only_the_final_snapshot() -> None:
    requirement_source = inspect.getsource(plans.final_owner_requirement)
    assert "connection" not in requirement_source and "execute(" not in requirement_source
    assert 'judged_requirement("membership_role.owner", decide, reveal=True)' in requirement_source
