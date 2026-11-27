"""P15-C11-S02 correction S02-R2 (unit): the delegation grant's recipient requirement and its snapshot source.

The requirement is judged over the final snapshot only (`finalize`'s one statement); the source it declares reads no
table the authority statement did not already read, and is the `subject_gm` predicate with only the role code and the
bind name changed. Database behaviour (expiry and account deactivation between the eligibility read and the final
statement) is in `tests/database/test_assign_control_delegation_recipient_final.py`.
"""

import re
import uuid
from datetime import UTC, datetime

import pytest

from dnd_ai.commands import assign_control_delegation_plans as delegation_plans
from dnd_ai.commands.assign_control_delegations import (
    AssignControlRecipientChangedError,
    AssignControlRecipientNotAssistantGmError,
)
from dnd_ai.domain import access
from dnd_ai.domain.access import AUTHORITY_READER_TABLES, AuthoritySnapshot, _authority_snapshot_sql

pytestmark = pytest.mark.unit

TABLES = re.compile(r"(?:FROM|JOIN)\s+([a-z_]+\.[a-z_]+)")


def _snapshot(subject: uuid.UUID | None, held: uuid.UUID | None) -> AuthoritySnapshot:
    return AuthoritySnapshot(
        t_auth=datetime.now(UTC),
        isolation="read committed",
        access=None,
        subject_assistant_membership_id=subject,
        subject_assistant_gm_assignment=held,
    )


def test_the_recipient_requirement_declares_the_grantee_and_nothing_else() -> None:
    campaign, grantee, row = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    requirement = delegation_plans.recipient_requirement(campaign, grantee, row)
    assert requirement.assistant_gm_subject == grantee
    assert requirement.gm_subject is None and not requirement.reveal
    assert not requirement.assign_control and not requirement.account
    assert requirement.world_id is None and requirement.perspective is None


def test_the_recipient_requirement_holds_only_for_the_locked_live_row() -> None:
    campaign, grantee, row = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    def judged(snapshot: AuthoritySnapshot) -> tuple[bool, type[BaseException] | None]:
        requirement = delegation_plans.recipient_requirement(campaign, grantee, row)
        held = requirement.predicate(snapshot)
        return held, (None if held else type(requirement.refusal()))

    assert judged(_snapshot(grantee, row)) == (True, None)
    assert judged(_snapshot(grantee, None)) == (False, AssignControlRecipientNotAssistantGmError)
    assert judged(_snapshot(grantee, uuid.uuid4())) == (False, AssignControlRecipientChangedError)
    # a snapshot that did not declare this grantee is a programming error, never a pass
    assert judged(_snapshot(uuid.uuid4(), row)) == (False, RuntimeError)
    assert judged(_snapshot(None, None)) == (False, RuntimeError)


def test_the_subject_assistant_source_reads_no_new_table_and_is_the_gm_predicate() -> None:
    sql = _authority_snapshot_sql(
        instant="fresh",
        with_world=True,
        with_reveal=True,
        with_assign_control=True,
        with_subject_assistant_gm=True,
    )
    assert set(TABLES.findall(sql)) == AUTHORITY_READER_TABLES
    assert "subject_assistant_gm AS" in sql
    gm = access._SUBJECT_GM_CTES.replace("subject_gm AS", "subject_assistant_gm AS")
    gm = gm.replace(":subject_membership_id", ":subject_assistant_membership_id")
    gm = gm.replace(
        f"r.code = '{access.BUILTIN_CAMPAIGN_GM_ROLE_CODE}'",
        f"r.code = '{access.BUILTIN_CAMPAIGN_ASSISTANT_GM_ROLE_CODE}'",
    )
    assert " ".join(gm.split()) == " ".join(access._SUBJECT_ASSISTANT_GM_CTES.split())


def test_finalize_declares_the_subject_only_when_a_requirement_does() -> None:
    plain = _authority_snapshot_sql(instant="fresh", with_world=False, with_reveal=False)
    assert "subject_assistant_gm" not in plain
