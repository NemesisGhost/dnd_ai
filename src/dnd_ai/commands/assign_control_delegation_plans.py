"""Delegate and revoke `character.assign_control` as unkeyed pre-write plans (P15-C11-S02-T02, ADR 0021 OD-4a).

The two routes (`dnd_ai.api.assign_control_delegations`) use the declarations and the lock, read and write phases
below, so that **every lock and every refusal precedes `plan.finalize`** and every write is a declared step after it.
Both routes are **unkeyed** (`R01_UNKEYED_PRE_WRITE_ROUTES`): an `Idempotency-Key` header is ignored and there is no
receipt step. Repeating a grant or a revoke is idempotent by its own rule (below), not by replay.

## Authority

The grantor and the revoker hold a live built-in `campaign_owner` or `gm` assignment in this campaign. A delegated
holder is refused 403 (**no redelegation**), and so are `access.manage`, `canon.edit`, a custom role, a control
assignment and an assistant GM without a delegation. The route requirement is `campaign.view`; the operation authority
is judged before any target lookup (the same fixed 403 `character_assign_control_required` as the control writers), the
body is validated after it (403 before 422), and it is judged again at a fresh database instant after the last lock wait
and by `plan.finalize` (the snapshot's `assign_control` source: `campaign_owner` or `gm`, never `delegation`).

The recipient is an open, active member of this campaign who holds a live built-in `assistant_gm` assignment (409
`assign_control_recipient_not_assistant_gm` otherwise; a membership of another campaign is a 404). The assignment is
read at a fresh instant under the locks that hold it (the row `FOR UPDATE`, the membership `FOR NO KEY UPDATE`).

## Grant: lock sequence (plan section 3.2; ADR 0021 section 2.8 delegation row, on the approved class order)

One unlocked discovery finds the caller's live owner or `gm` rows and the grantee's unrevoked built-in `assistant_gm`
rows of this campaign, ascending by id. Then, one statement per row bound to a discovered id:

1. **role class**, ascending id, each row at its mode: the caller's row `FOR SHARE`, the grantee's `assistant_gm` row `FOR
   UPDATE`;
2. the unlocked 404 (a grantee of another campaign), after the authority refusal;
3. **delegation class**: the grantee's live delegations `FOR UPDATE` (the ones bound to a different `assistant_gm` row,
   stale, and the one bound to the discovered row, matching; the live unique index allows one row between them);
4. **membership class**, ascending id: the grantee `FOR NO KEY UPDATE`, the caller `FOR KEY SHARE` (one membership is
   locked once, at the stronger mode);
5. the **campaign** `FOR UPDATE` (ADR step 2: it serializes with the control writers).

After the last wait: the caller is judged again, the grantee's live `assistant_gm` assignment is read at a fresh instant
(409 not-assistant) and must be the row locked in step 1 (409 `assign_control_recipient_changed`), and the live
delegations read without a lock must equal the locked set (the same 409; the proof the empty `PerAbsence` evidence needs).

| Branch | Writes |
|---|---|
| a live delegation is already bound to the live `assistant_gm` row | none (`granted` false, nothing audited): the matching lock returned a row, so the INSERT is forbidden (`PerAbsence`) |
| none | the INSERT (`PerAbsence` on the matching lock) and one audit row (`AnyConfirmed` on the INSERT) |
| a live delegation bound to a lapsed or replaced `assistant_gm` row | that delegation closed (`EachLockedRow(complete=True)` over the stale lock, `end_reason = assistant_gm_assignment_lapsed`), then the INSERT and the audit row |

## Revoke

The caller's role row `FOR SHARE`, the unlocked 404, the grantee's live delegation of this campaign `FOR UPDATE`, the
caller's membership `FOR KEY SHARE`, the campaign `FOR UPDATE`, then the caller judged again. A grantee with no live
delegation is a no-op: the lock returned nothing, so neither the UPDATE nor the audit row is owed or permitted. One
genuine revocation owes the UPDATE (`EachLockedRow(complete=True)`) and one audit row (`PerEvidence`). Revoking
never touches an assignment the holder made (T86): the assignments stay live and in effect.

## Cycles

The control writers take a delegated holder's `assistant_gm` row `FOR SHARE`, then the delegation row `FOR SHARE`, before
any membership (`control_assignment_plans`); a revocation therefore waits for an in-flight assign, or commits first and
the assign is refused after its wait. The role class, then the delegation class, then memberships, then the campaign is
the same relative order every other writer of these rows reaches them in (`tests/database/
test_assign_control_delegation_concurrency.py`).
"""

import uuid
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, bindparam, func, insert, select, text, update

from dnd_ai.domain.access import BUILTIN_CAMPAIGN_ASSISTANT_GM_ROLE_CODE, AuthoritySnapshot
from dnd_ai.domain.authorization import AuthorizationPlan, Requirement
from dnd_ai.domain.authorization_requirements import judged_requirement
from dnd_ai.domain.authorization_steps import (
    AnyConfirmed,
    EachLockedRow,
    Event,
    FkBinding,
    KeyBind,
    PerAbsence,
    PerEvidence,
    PreLock,
    PreWriteDeclaration,
    TriggerPin,
    UniqueWait,
    WriteStep,
)
from dnd_ai.persistence.tables.audit import change_log
from dnd_ai.persistence.tables.security import (
    campaign_memberships,
    character_assign_control_delegations,
    membership_roles,
)

from ._pre_write_steps import (
    CHANGE_LOG_ACTION_FK,
    CHANGE_LOG_ACTOR_FK,
    CHANGE_LOG_UNLOCKED_FK_TARGETS,
    fk_of,
)
from ._shared import lookup_id
from .assign_control_delegations import (
    END_REASON_ASSISTANT_GM_LAPSED,
    END_REASON_REVOKED,
    GRANT_COMMAND_NAME,
    REVOKE_COMMAND_NAME,
    AssignControlRecipientChangedError,
    AssignControlRecipientNotAssistantGmError,
    require_grantee_in_campaign,
)
from .campaign_lifecycle_plans import CAMPAIGN_ROW_LOCK
from .control_assignment_plans import (
    AUTHORITY_ROW_LOCK,
    AssignControlRequiredError,
    HeldAuthority,
    _discover_or_refuse,
    _lock_authority,
    _rejudge_authority,
    _require_authority,
    parse_request,
)
from .membership_role_plans import _IMMUTABLE, _UPDATED_AT, _audit_values, _pin, _scope_world
from .memberships import _database_clock

cm = campaign_memberships
mr = membership_roles
dl = character_assign_control_delegations

_OWNER_KIND = "campaign_owner"
_GM_KIND = "gm"

#: "No candidate": never a valid v4 id, so a candidate-bound lock bound to it matches nothing.
_NO_CANDIDATE = uuid.UUID(int=0)

# -- request bodies -------------------------------------------------------------------------------------

_Reason = Field(min_length=1, max_length=1000)


class GrantRequest(BaseModel):
    """The reason is required and stripped: a blank one is as missing as none (422, after the authority)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    grantee_campaign_membership_id: uuid.UUID
    reason: str = _Reason


class RevokeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    reason: str = _Reason


# -- triggers -------------------------------------------------------------------------------------------

#: The delegation table's three triggers (revision 151), pinned by name, timing, events and function source hash.
DELEGATION_TRIGGERS: frozenset[TriggerPin] = frozenset(
    {
        _pin(
            "tr_character_assign_control_delegations_enforce_immutable",
            *_IMMUTABLE,
            events=frozenset({Event.UPDATE}),
            args=(
                "campaign_id",
                "grantee_campaign_membership_id",
                "assistant_gm_membership_role_id",
                "granted_at",
                "reason",
            ),
        ),
        _pin(
            "tr_character_assign_control_delegations_enforce_scope",
            "security",
            "enforce_character_assign_control_delegation_scope",
            "2fdb1f929c8586ea5556182890512f76",
        ),
        _pin(
            "tr_character_assign_control_delegations_set_updated_at",
            *_UPDATED_AT,
            events=frozenset({Event.UPDATE}),
        ),
    }
)

# -- locks ----------------------------------------------------------------------------------------------

#: The grantee's built-in `assistant_gm` row, `FOR UPDATE` (the delegation's foreign key and its lifecycle), bound to the
#: discovered row (bound `row`, `membership`).
ASSISTANT_ROW_LOCK = PreLock(
    "assistant_gm_row_update",
    select(mr.c.membership_role_id)
    .where(mr.c.membership_role_id == bindparam("row"))
    .where(mr.c.campaign_membership_id == bindparam("membership"))
    .where(mr.c.revoked_at.is_(None))
    .with_for_update(),
)
#: The grantee's membership, `FOR NO KEY UPDATE` (never `FOR UPDATE`: two grantors delegating to each other would
#: deadlock on the key share the delegation insert's foreign key takes), bound `membership`, `campaign`.
GRANTEE_MEMBERSHIP_LOCK = PreLock(
    "delegation_grantee_membership_no_key_update",
    select(cm.c.campaign_membership_id)
    .where(cm.c.campaign_membership_id == bindparam("membership"))
    .where(cm.c.campaign_id == bindparam("campaign"))
    .with_for_update(key_share=True),
)
#: The caller's membership, `FOR KEY SHARE`: the weakest mode, what the foreign keys to it need (bound `membership`,
#: `campaign`).
CALLER_MEMBERSHIP_LOCK = PreLock(
    "delegation_caller_membership_key_share",
    select(cm.c.campaign_membership_id)
    .where(cm.c.campaign_membership_id == bindparam("membership"))
    .where(cm.c.campaign_id == bindparam("campaign"))
    .with_for_update(read=True, key_share=True),
)
#: The grantee's live delegation bound to an `assistant_gm` row **other than** the one discovered (a lapsed or replaced
#: row), `FOR UPDATE` (bound `grantee`, `role`).
STALE_DELEGATION_LOCK = PreLock(
    "stale_assign_delegation_rows",
    select(dl.c.character_assign_control_delegation_id)
    .where(dl.c.grantee_campaign_membership_id == bindparam("grantee"))
    .where(dl.c.revoked_at.is_(None))
    .where(dl.c.assistant_gm_membership_role_id != bindparam("role"))
    .order_by(dl.c.character_assign_control_delegation_id)
    .with_for_update(),
)
#: The grantee's live delegation bound to the discovered `assistant_gm` row, `FOR UPDATE` (bound `grantee`, `role`). Its
#: evidence decides whether a delegation is owed (`PerAbsence`): the live unique index and the drift check
#: (`prepare_grant`) are what prove that an empty run means "none at all".
MATCHING_DELEGATION_LOCK = PreLock(
    "matching_assign_delegation_row",
    select(dl.c.character_assign_control_delegation_id)
    .where(dl.c.grantee_campaign_membership_id == bindparam("grantee"))
    .where(dl.c.revoked_at.is_(None))
    .where(dl.c.assistant_gm_membership_role_id == bindparam("role"))
    .order_by(dl.c.character_assign_control_delegation_id)
    .with_for_update(),
)
#: The grantee's live delegation of this campaign, `FOR UPDATE` (revoke; bound `grantee`, `campaign`).
REVOKE_DELEGATION_LOCK = PreLock(
    "revoke_assign_delegation_row",
    select(dl.c.character_assign_control_delegation_id)
    .where(dl.c.grantee_campaign_membership_id == bindparam("grantee"))
    .where(dl.c.campaign_id == bindparam("campaign"))
    .where(dl.c.revoked_at.is_(None))
    .order_by(dl.c.character_assign_control_delegation_id)
    .with_for_update(),
)

# -- steps ----------------------------------------------------------------------------------------------

_CONCURRENCY_TESTS = "tests/database/test_assign_control_delegation_concurrency.py::"
_LIVE_INDEX = "security.ux_character_assign_control_delegations_live"
#: An UPDATE that sets `revoked_at` *leaves* the live unique index (`WHERE revoked_at IS NULL`): it inserts no index
#: entry and can never wait for a competitor's key (pinned by the named test).
_LEAVES_LIVE_DELEGATION_INDEX = frozenset(
    {
        UniqueWait(
            _LIVE_INDEX,
            _CONCURRENCY_TESTS
            + "test_a_delegation_closure_leaving_the_live_index_never_waits_for_a_competing_insert",
        )
    }
)
_INSERT_LIVE_DELEGATION_INDEX = frozenset(
    {
        UniqueWait(
            _LIVE_INDEX,
            _CONCURRENCY_TESTS
            + "test_a_competing_delegation_for_the_same_grantee_is_a_unique_wait",
        )
    }
)

CLOSE_STALE_DELEGATION = WriteStep(
    name="close_stale_assign_delegation",
    statement=update(dl)
    .where(dl.c.character_assign_control_delegation_id == bindparam("delegation"))
    .values(revoked_at=func.pg_catalog.clock_timestamp(), end_reason=END_REASON_ASSISTANT_GM_LAPSED)
    .returning(dl.c.character_assign_control_delegation_id),
    cardinality=EachLockedRow(complete=True),
    target=(KeyBind(dl.c.character_assign_control_delegation_id, "delegation"),),
    target_lock=STALE_DELEGATION_LOCK,
    unique_waits=_LEAVES_LIVE_DELEGATION_INDEX,
    triggers=DELEGATION_TRIGGERS,
)
INSERT_DELEGATION = WriteStep(
    name="insert_assign_delegation",
    statement=insert(dl)
    .values(
        campaign_id=bindparam("campaign"),
        grantee_campaign_membership_id=bindparam("grantee"),
        assistant_gm_membership_role_id=bindparam("role"),
        granted_by_membership_id=bindparam("actor_membership"),
        reason=bindparam("reason"),
    )
    .returning(dl.c.character_assign_control_delegation_id),
    cardinality=PerAbsence(MATCHING_DELEGATION_LOCK),
    fks=(
        FkBinding(
            fk_of(dl, "campaign_id"),
            (KeyBind(dl.c.campaign_id, "campaign"),),
            CAMPAIGN_ROW_LOCK,
        ),
        FkBinding(
            fk_of(dl, "grantee_campaign_membership_id"),
            (KeyBind(dl.c.grantee_campaign_membership_id, "grantee"),),
            GRANTEE_MEMBERSHIP_LOCK,
        ),
        FkBinding(
            fk_of(dl, "assistant_gm_membership_role_id"),
            (KeyBind(dl.c.assistant_gm_membership_role_id, "role"),),
            ASSISTANT_ROW_LOCK,
        ),
        FkBinding(
            fk_of(dl, "granted_by_membership_id"),
            (KeyBind(dl.c.granted_by_membership_id, "actor_membership"),),
            CALLER_MEMBERSHIP_LOCK,
        ),
    ),
    value_binds=frozenset({"reason"}),
    unique_waits=_INSERT_LIVE_DELEGATION_INDEX,
    triggers=frozenset(t for t in DELEGATION_TRIGGERS if Event.INSERT in t.events),
)
GRANT_AUDIT = WriteStep(
    name="audit_assign_delegation_granted",
    statement=insert(change_log)
    .values(
        **_audit_values("character_assign_control_delegations", GRANT_COMMAND_NAME),
        changed_fields=bindparam("changed"),
    )
    .returning(change_log.c.change_log_id),
    cardinality=AnyConfirmed((INSERT_DELEGATION,)),
    fks=(CHANGE_LOG_ACTION_FK, CHANGE_LOG_ACTOR_FK),
    value_binds=frozenset({"record", "world", "correlation", "changed"}),
)
REVOKE_DELEGATION = WriteStep(
    name="revoke_assign_delegation",
    statement=update(dl)
    .where(dl.c.character_assign_control_delegation_id == bindparam("delegation"))
    .values(
        revoked_at=func.pg_catalog.clock_timestamp(),
        revoked_by_membership_id=bindparam("actor_membership"),
        revocation_reason=bindparam("why"),
        end_reason=END_REASON_REVOKED,
    )
    .returning(dl.c.character_assign_control_delegation_id),
    cardinality=EachLockedRow(complete=True),
    target=(KeyBind(dl.c.character_assign_control_delegation_id, "delegation"),),
    target_lock=REVOKE_DELEGATION_LOCK,
    fks=(
        FkBinding(
            fk_of(dl, "revoked_by_membership_id"),
            (KeyBind(dl.c.revoked_by_membership_id, "actor_membership"),),
            CALLER_MEMBERSHIP_LOCK,
        ),
    ),
    value_binds=frozenset({"why"}),
    unique_waits=_LEAVES_LIVE_DELEGATION_INDEX,
    triggers=DELEGATION_TRIGGERS,
)
REVOKE_AUDIT = WriteStep(
    name="audit_assign_delegation_revoked",
    statement=insert(change_log)
    .values(
        **_audit_values("character_assign_control_delegations", REVOKE_COMMAND_NAME),
        changed_fields=bindparam("changed"),
    )
    .returning(change_log.c.change_log_id),
    cardinality=PerEvidence(REVOKE_DELEGATION_LOCK),
    fks=(CHANGE_LOG_ACTION_FK, CHANGE_LOG_ACTOR_FK),
    value_binds=frozenset({"record", "world", "correlation", "changed"}),
)

GRANT_DECLARATION = PreWriteDeclaration(
    locks=(
        AUTHORITY_ROW_LOCK,
        ASSISTANT_ROW_LOCK,
        STALE_DELEGATION_LOCK,
        MATCHING_DELEGATION_LOCK,
        GRANTEE_MEMBERSHIP_LOCK,
        CALLER_MEMBERSHIP_LOCK,
        CAMPAIGN_ROW_LOCK,
    ),
    steps=(CLOSE_STALE_DELEGATION, INSERT_DELEGATION, GRANT_AUDIT),
    unlocked_fk_targets=CHANGE_LOG_UNLOCKED_FK_TARGETS,
)
REVOKE_DECLARATION = PreWriteDeclaration(
    locks=(
        AUTHORITY_ROW_LOCK,
        REVOKE_DELEGATION_LOCK,
        CALLER_MEMBERSHIP_LOCK,
        CAMPAIGN_ROW_LOCK,
    ),
    steps=(REVOKE_DELEGATION, REVOKE_AUDIT),
    unlocked_fk_targets=CHANGE_LOG_UNLOCKED_FK_TARGETS,
)

# -- the final authorization requirement ----------------------------------------------------------------


def grantor_requirement(campaign_id: uuid.UUID, actor_membership_id: uuid.UUID) -> Requirement:
    """The operation's own authority, judged again at `finalize`'s one `t_auth`: the caller holds a live built-in
    `campaign_owner` or `gm` assignment (the `assign_control` source of the same snapshot). The `delegation` source is
    **not** enough: a delegated holder cannot delegate (no redelegation). Reads only that source (F33)."""

    def decide(snapshot: AuthoritySnapshot) -> BaseException | None:
        if snapshot.assign_control_authority in (_OWNER_KIND, _GM_KIND):
            return None
        return AssignControlRequiredError(
            f"membership {actor_membership_id} holds no live campaign_owner or gm assignment "
            f"in campaign {campaign_id} at the final authorization instant"
        )

    return judged_requirement("assign_control_delegation.grantor", decide, assign_control=True)


def recipient_requirement(
    campaign_id: uuid.UUID, grantee: uuid.UUID, assistant_row: uuid.UUID
) -> Requirement:
    """The grant's recipient at the same final instant (correction S02-R2): the grantee's live built-in `assistant_gm`
    assignment (the template; the assignment unrevoked, unexpired at `t_auth`, its role active; the membership of this
    campaign, open and active; its account active) exists (409 not-assistant otherwise) and is the very row the grant
    locked and will bind the delegation to (`recipient_changed` otherwise). The row lock stops a concurrent update or
    revoke of that row and the membership lock a concurrent membership change; neither stops expiry and neither covers
    the account, which this check does. It reads the database at `finalize`, never the pre-finalization read."""

    def decide(snapshot: AuthoritySnapshot) -> BaseException | None:
        if snapshot.subject_assistant_membership_id != grantee:
            return RuntimeError(
                "the final snapshot does not carry the grantee's assistant_gm assignment"
            )
        held = snapshot.subject_assistant_gm_assignment
        if held is None:
            return AssignControlRecipientNotAssistantGmError(
                f"membership {grantee} holds no live built-in assistant_gm assignment in campaign {campaign_id} "
                "at the final authorization instant"
            )
        if held != assistant_row:
            return AssignControlRecipientChangedError(
                f"membership {grantee}'s live assistant_gm assignment {held} is not the locked {assistant_row}"
            )
        return None

    return judged_requirement(
        "assign_control_delegation.recipient_assistant_gm", decide, assistant_gm_subject=grantee
    )


# -- reads ----------------------------------------------------------------------------------------------

_LIVE_ASSISTANT_SQL = text(f"""
    SELECT mr.membership_role_id
    FROM security.membership_roles mr
    JOIN security.roles r ON r.role_id = mr.role_id
    JOIN security.campaign_memberships cm ON cm.campaign_membership_id = mr.campaign_membership_id
    JOIN security.membership_statuses ms ON ms.membership_status_id = cm.membership_status_id
    JOIN security.users u ON u.user_id = cm.user_id
    JOIN core.lifecycle_statuses uls ON uls.lifecycle_status_id = u.lifecycle_status_id
    WHERE mr.campaign_membership_id = :grantee
      AND cm.campaign_id = :campaign
      AND r.campaign_id IS NULL
      AND r.code = '{BUILTIN_CAMPAIGN_ASSISTANT_GM_ROLE_CODE}'
      AND r.is_active
      AND mr.revoked_at IS NULL
      AND (mr.expires_at IS NULL OR mr.expires_at > :t)
      AND cm.ended_at IS NULL
      AND ms.code = 'active'
      AND ms.is_active
      AND uls.code = 'active'
    ORDER BY mr.membership_role_id
    LIMIT 1
""")  # noqa: S608 - the interpolated name is a module constant

_UNREVOKED_ASSISTANT_ROWS_SQL = text(f"""
    SELECT mr.membership_role_id
    FROM security.membership_roles mr
    JOIN security.roles r ON r.role_id = mr.role_id
    JOIN security.campaign_memberships cm ON cm.campaign_membership_id = mr.campaign_membership_id
    WHERE mr.campaign_membership_id = :grantee
      AND cm.campaign_id = :campaign
      AND r.campaign_id IS NULL
      AND r.code = '{BUILTIN_CAMPAIGN_ASSISTANT_GM_ROLE_CODE}'
      AND mr.revoked_at IS NULL
    ORDER BY mr.membership_role_id
""")  # noqa: S608 - the interpolated name is a module constant


def _live_delegations(connection: Connection, grantee: uuid.UUID) -> set[uuid.UUID]:
    """The grantee's live delegations, read **without** a lock (the drift check)."""
    return set(
        connection.execute(
            text(
                "SELECT character_assign_control_delegation_id "
                "FROM security.character_assign_control_delegations "
                "WHERE grantee_campaign_membership_id = :grantee AND revoked_at IS NULL"
            ),
            {"grantee": grantee},
        ).scalars()
    )


# -- prepare and write ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class GrantPrepared:
    """What the grant's lock and read phase established, all before `finalize`."""

    world_id: uuid.UUID
    action_id: uuid.UUID
    reason: str
    grantee: uuid.UUID
    assistant_row: uuid.UUID
    #: The delegation already bound to the live `assistant_gm` row (nothing to write), or `None`.
    existing: uuid.UUID | None
    stale: tuple[uuid.UUID, ...]


@dataclass(frozen=True)
class GrantWritten:
    grantee_campaign_membership_id: uuid.UUID
    character_assign_control_delegation_id: uuid.UUID
    created: bool


@dataclass(frozen=True)
class RevokePrepared:
    world_id: uuid.UUID
    action_id: uuid.UUID
    reason: str
    delegation: uuid.UUID | None


@dataclass(frozen=True)
class RevokeWritten:
    grantee_campaign_membership_id: uuid.UUID
    character_assign_control_delegation_id: uuid.UUID | None
    revoked: bool


def prepare_grant(
    connection: Connection,
    plan: AuthorizationPlan,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    actor_membership_id: uuid.UUID,
    raw: Any,
) -> GrantPrepared:
    """Every lock, read and refusal of the grant, in the order of the module docstring, before `finalize`."""
    del actor_user_id  # the account is not a row this grant writes against
    # 1. the caller's rows (unlocked): 403 before the body is looked at
    discovered = _discover_or_refuse(
        connection,
        campaign_id=campaign_id,
        actor_membership_id=actor_membership_id,
        allow_delegation=False,
    )
    request = parse_request(GrantRequest, raw)
    grantee = request.grantee_campaign_membership_id
    # 2. the grantee's unrevoked built-in assistant_gm rows (unlocked), then the role class in ONE ascending pass over
    #    the caller's rows (`FOR SHARE`) and the grantee's (`FOR UPDATE`)
    assistant_rows = list(
        connection.execute(
            _UNREVOKED_ASSISTANT_ROWS_SQL, {"grantee": grantee, "campaign": campaign_id}
        ).scalars()
    )
    held = _lock_authority(
        connection,
        plan,
        actor_membership_id=actor_membership_id,
        discovered=discovered,
        others=tuple(
            (row_id, ASSISTANT_ROW_LOCK, {"row": row_id, "membership": grantee})
            for row_id in assistant_rows
        ),
    )
    locked_assistant = set(held.others)
    candidate = assistant_rows[0] if assistant_rows else _NO_CANDIDATE
    # 3. unlocked, the membership's campaign never changes: the 404 keeps its place after the authority refusal
    require_grantee_in_campaign(
        connection, campaign_id=campaign_id, grantee_campaign_membership_id=grantee
    )
    # 4. delegation class: the grantee's live delegations, stale and matching
    binds: dict[str, Any] = {"grantee": grantee, "role": candidate}
    stale = tuple(key[0] for key in plan.lock(connection, STALE_DELEGATION_LOCK, binds))
    matching = tuple(key[0] for key in plan.lock(connection, MATCHING_DELEGATION_LOCK, binds))
    # 5. membership class, one ascending pass; one membership is locked once, at the stronger mode
    grantee_lock = (GRANTEE_MEMBERSHIP_LOCK, grantee)
    caller_lock = (CALLER_MEMBERSHIP_LOCK, actor_membership_id)
    ordered = (
        (grantee_lock, caller_lock)
        if grantee <= actor_membership_id
        else (caller_lock, grantee_lock)
    )
    for lock, membership_id in ordered:
        plan.lock(connection, lock, {"membership": membership_id, "campaign": campaign_id})
    # 6. the campaign
    plan.lock(connection, CAMPAIGN_ROW_LOCK, {"campaign": campaign_id})
    # 7. every lock wait is behind us: judge the caller and the grantee at a fresh database instant
    _rejudge_authority(
        connection,
        campaign_id=campaign_id,
        actor_membership_id=actor_membership_id,
        locked=held,
        allow_delegation=False,
    )
    live_assistant = connection.execute(
        _LIVE_ASSISTANT_SQL,
        {"grantee": grantee, "campaign": campaign_id, "t": _database_clock(connection)},
    ).scalar()
    if live_assistant is None:
        raise AssignControlRecipientNotAssistantGmError(
            f"membership {grantee} holds no live built-in assistant_gm assignment in campaign {campaign_id}"
        )
    if live_assistant not in locked_assistant or live_assistant != candidate:
        # The live assistant_gm row was not among the rows locked in step 2 (it appeared after discovery): the
        # delegation would bind to a row nobody holds. Retryable; nothing has been written.
        raise AssignControlRecipientChangedError(
            f"membership {grantee}'s live assistant_gm assignment {live_assistant} appeared while the grant waited"
        )
    # 8. drift: the live delegations (read without a lock) are exactly the ones locked above. A delegation the two
    #    candidate-bound locks did not cover would make the empty `PerAbsence` evidence a lie
    if _live_delegations(connection, grantee) != {*stale, *matching} or (stale and matching):
        raise AssignControlRecipientChangedError(
            f"membership {grantee}'s live delegations changed while the grant waited"
        )
    # 9. the final requirements, registered after every early check (so refusal precedence is unchanged: the grantor's
    #    403 before the recipient's 409) and judged by `finalize` at its own instant, read from the database again. The
    #    recipient is part of that one statement (S02-R2): step 7's read is the early check, not the final word
    plan.require(connection, grantor_requirement(campaign_id, actor_membership_id))
    plan.require(connection, recipient_requirement(campaign_id, grantee, live_assistant))
    return GrantPrepared(
        world_id=_scope_world(connection, campaign_id),
        action_id=lookup_id(connection, "audit", "change_actions", "change_action_id", "created"),
        reason=request.reason,
        grantee=grantee,
        assistant_row=live_assistant,
        existing=matching[0] if matching else None,
        stale=stale,
    )


def write_grant(
    connection: Connection,
    plan: AuthorizationPlan,
    prepared: GrantPrepared,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    actor_membership_id: uuid.UUID,
    grantee_campaign_membership_id: uuid.UUID,
    correlation_id: str | None,
) -> GrantWritten:
    """The declared writes, after `finalize`: close the stale delegation, insert, one audit row. Nothing at all when
    the grantee already holds a delegation bound to the live `assistant_gm` row."""
    if prepared.existing is not None:
        return GrantWritten(
            grantee_campaign_membership_id=grantee_campaign_membership_id,
            character_assign_control_delegation_id=prepared.existing,
            created=False,
        )
    for delegation in prepared.stale:
        plan.execute(connection, CLOSE_STALE_DELEGATION, {"delegation": delegation})
    outcome = plan.execute(
        connection,
        INSERT_DELEGATION,
        {
            "campaign": campaign_id,
            "grantee": grantee_campaign_membership_id,
            "role": prepared.assistant_row,
            "actor_membership": actor_membership_id,
            "reason": prepared.reason,
        },
    )
    delegation_id = outcome.keys[0][0]
    assert isinstance(delegation_id, uuid.UUID)
    plan.execute(
        connection,
        GRANT_AUDIT,
        {
            "action": prepared.action_id,
            "record": delegation_id,
            "world": prepared.world_id,
            "actor": actor_user_id,
            "correlation": uuid.UUID(correlation_id) if correlation_id is not None else None,
            "changed": {
                "grantee_campaign_membership_id": str(grantee_campaign_membership_id),
                "assistant_gm_membership_role_id": str(prepared.assistant_row),
                "replaced_stale_delegation": bool(prepared.stale),
            },
        },
    )
    return GrantWritten(
        grantee_campaign_membership_id=grantee_campaign_membership_id,
        character_assign_control_delegation_id=delegation_id,
        created=True,
    )


def prepare_revoke(
    connection: Connection,
    plan: AuthorizationPlan,
    *,
    campaign_id: uuid.UUID,
    actor_membership_id: uuid.UUID,
    grantee_campaign_membership_id: uuid.UUID,
    raw: Any,
) -> RevokePrepared:
    """Every lock, read and refusal of the revoke, before `finalize`."""
    held = _require_authority(
        connection,
        plan,
        campaign_id=campaign_id,
        actor_membership_id=actor_membership_id,
        allow_delegation=False,
    )
    reason = parse_request(RevokeRequest, raw).reason
    require_grantee_in_campaign(
        connection,
        campaign_id=campaign_id,
        grantee_campaign_membership_id=grantee_campaign_membership_id,
    )
    delegations = plan.lock(
        connection,
        REVOKE_DELEGATION_LOCK,
        {"grantee": grantee_campaign_membership_id, "campaign": campaign_id},
    )
    plan.lock(
        connection,
        CALLER_MEMBERSHIP_LOCK,
        {"membership": actor_membership_id, "campaign": campaign_id},
    )
    plan.lock(connection, CAMPAIGN_ROW_LOCK, {"campaign": campaign_id})
    # the caller again, at a fresh instant, after the last lock wait
    _rejudge_authority(
        connection,
        campaign_id=campaign_id,
        actor_membership_id=actor_membership_id,
        locked=held,
        allow_delegation=False,
    )
    plan.require(connection, grantor_requirement(campaign_id, actor_membership_id))
    return RevokePrepared(
        world_id=_scope_world(connection, campaign_id),
        action_id=lookup_id(connection, "audit", "change_actions", "change_action_id", "updated"),
        reason=reason,
        delegation=delegations[0][0] if delegations else None,
    )


def write_revoke(
    connection: Connection,
    plan: AuthorizationPlan,
    prepared: RevokePrepared,
    *,
    actor_user_id: uuid.UUID,
    actor_membership_id: uuid.UUID,
    grantee_campaign_membership_id: uuid.UUID,
    correlation_id: str | None,
) -> RevokeWritten:
    """The declared revocation and its audit row; nothing when the grantee held no live delegation."""
    if prepared.delegation is None:
        return RevokeWritten(
            grantee_campaign_membership_id=grantee_campaign_membership_id,
            character_assign_control_delegation_id=None,
            revoked=False,
        )
    plan.execute(
        connection,
        REVOKE_DELEGATION,
        {
            "delegation": prepared.delegation,
            "actor_membership": actor_membership_id,
            "why": prepared.reason,
        },
    )
    plan.execute(
        connection,
        REVOKE_AUDIT,
        {
            "action": prepared.action_id,
            "record": prepared.delegation,
            "world": prepared.world_id,
            "actor": actor_user_id,
            "correlation": uuid.UUID(correlation_id) if correlation_id is not None else None,
            "changed": {
                "grantee_campaign_membership_id": str(grantee_campaign_membership_id),
                "revoked": True,
            },
        },
    )
    return RevokeWritten(
        grantee_campaign_membership_id=grantee_campaign_membership_id,
        character_assign_control_delegation_id=prepared.delegation,
        revoked=True,
    )


__all__ = [
    "GRANT_DECLARATION",
    "REVOKE_DECLARATION",
    "GrantPrepared",
    "GrantWritten",
    "HeldAuthority",
    "RevokePrepared",
    "RevokeWritten",
    "grantor_requirement",
    "prepare_grant",
    "prepare_revoke",
    "write_grant",
    "write_revoke",
]
