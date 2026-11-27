"""Assign, replace and revoke campaign character control as keyed-optional pre-write plans (P15-C11-S02-T01).

The three routes (`dnd_ai.api.control_assignments`) use the declarations and the lock, read and write phases below, so
that **every lock is taken before `plan.finalize`**, every read a refusal depends on happens before it, and every write
is a declared step after it. There is no direct (unguarded) command module: the plan phases are the only writers, and
the tests compare the routes with the stored rows.

## Authority

`character.assign_control` is **not** a stored capability. It is held by a live built-in `campaign_owner` or `gm`
assignment in the route's campaign (ADR 0021 OD-4), or by a live assign-control delegation bound to the holder's live
built-in `assistant_gm` assignment (OD-4a, T02: `dnd_ai.commands.assign_control_delegation_plans`). `access.manage`,
`canon.edit`, custom roles, resource grants and control assignments never confer it, and neither does anything the
campaign clock decides: the authority component of the snapshot (`with_assign_control`) names no assignment table, no
clock table and no capability table (F33). A delegated holder uses the three writers here and the read, and nothing
more: the delegation routes themselves are refused to it (no redelegation).

The route requirement is `campaign.view`. The operation authority is judged **before any target lookup**, so the
refusal (403 `character_assign_control_required`, one fixed body) is identical for an existing and a missing
character, assignment or world time. A malformed body is therefore judged *after* the authority: the handler takes the
body as a plain mapping and validates it here (422), never ahead of the 403.

## Lock sequence (ADR 0021 section 2.8 on the approved R01 class order, never inverted)

Key to modes: S `FOR SHARE`, KS `FOR KEY SHARE`, U `FOR UPDATE`. A keyed request starts with the advisory key lock, the
reservation `INSERT` (the actor's account KS; the campaign FK deferred) and ends with the receipt row U.

| Writer | Locks |
|---|---|
| assign | caller's authority row(s) S (a delegated holder: the bound `assistant_gm` row S, then the delegation row S); caller's membership S and the assignee's U (ascending id); caller's account S, the assignee's KS; **campaign U**; the relationship type row KS (by code); the character's entity row U (the anchor, taken even when no assignment exists); the character row KS; the character's live assignment rows U; the dated world-time rows KS; [receipt U] |
| replace | the same, with the old primary's membership U in the membership pass (ascending id; one lock when it is the assignee's) |
| revoke | caller's authority row(s) S; caller's membership S and the revoked row's membership U; caller's account S; **campaign U**; the character's entity row U; the assignment row U (only while unrevoked; its evidence is the "this request revokes" fact); [receipt U] |

After the last wait, at a fresh `clock_timestamp()`: the authority is judged again (403 first: an unauthorized caller
never learns the eligibility of a target), the character's live assignment set is read again and must equal the locked
set (409 otherwise), and eligibility is judged. Then `plan.finalize` (the route requirement and the authority
requirement, from one snapshot) and the declared writes.

The campaign is taken `FOR UPDATE` by every writer, so two writers for one character serialize there; the entity
anchor is what controller operations (C20) will share-lock. A competing INSERT that is not a route (a direct write)
meets the two partial unique indexes: the INSERT steps name both as **competing** `UniqueWait` entries, each with its own
race test (`tests/database/test_control_assignment_concurrency.py`), and the legacy `active_type` index as one the INSERT
never enters.

## Writes

| Writer | Writes |
|---|---|
| assign | the assignment `Exactly(1)`, one audit row `Exactly(1)`, receipt |
| replace | the old primary `Exactly(1)`, the new primary `Exactly(1)`, two audit rows `Exactly(1)` each, receipt |
| revoke | the row `EachLockedRow(complete=True)`, audit `PerEvidence`, receipt |

A revoke of an already revoked row is the only no-op: the lock returns nothing, so neither the UPDATE nor the audit
row is owed or permitted. Audit rows hold no reason text; the reason stays on the row (`notes` for an assignment,
`revocation_reason` for a revocation).
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import Connection, bindparam, func, insert, select, text, update

from dnd_ai.domain.access import (
    BUILTIN_CAMPAIGN_ASSISTANT_GM_ROLE_CODE,
    BUILTIN_CAMPAIGN_GM_ROLE_CODE,
    BUILTIN_CAMPAIGN_OWNER_ROLE_CODE,
    AuthoritySnapshot,
)
from dnd_ai.domain.authorization import AuthorizationPlan, Requirement, ReservationDeclarations
from dnd_ai.domain.authorization_requirements import judged_requirement
from dnd_ai.domain.authorization_steps import (
    EachLockedRow,
    Exactly,
    FkBinding,
    KeyBind,
    PerEvidence,
    PreLock,
    PreWriteDeclaration,
    UniqueWait,
    WriteStep,
)
from dnd_ai.domain.errors import DomainAuthorizationError, SafeMessageError
from dnd_ai.persistence.tables.audit import change_log
from dnd_ai.persistence.tables.security import (
    campaign_memberships,
    character_assign_control_delegations,
    character_relationship_types,
    membership_character_relationships,
    membership_roles,
)

from ._pre_write_steps import (
    CHANGE_LOG_ACTION_FK,
    CHANGE_LOG_ACTOR_FK,
    CHANGE_LOG_UNLOCKED_FK_TARGETS,
    RECEIPT_LOCK,
    RECEIPT_STEP,
    fk_of,
)
from ._shared import lookup_id
from .access_grant_plans import (
    _ENTITY_ROW,
    _MEMBERSHIP_ROW,
    CHARACTER_ROW_LOCK,
    TARGET_ENTITY_LOCK,
    WORLD_TIMES_KEY_SHARE_LOCK,
    _became_ineligible_while_waiting,
    _lock_scope_rows,
    _require_campaign_active,
    _status_before,
    _world_time_sort_key,
)
from .access_grants import (
    MembershipNotActiveError,
    MembershipNotInCampaignError,
    TargetNotInCampaignWorldError,
)
from .campaign_lifecycle_plans import (
    ACTOR_ACCOUNT_LOCK,
    ACTOR_MEMBERSHIP_LOCK,
    CAMPAIGN_ROW_LOCK,
)
from .membership_end_plans import RELATIONSHIP_INSERT_TRIGGERS, RELATIONSHIP_UPDATE_TRIGGERS
from .membership_role_plans import (
    _AUDIT_BINDS,
    TARGET_ACCOUNT_LOCK,
    TARGET_MEMBERSHIP_LOCK,
    _audit_values,
    _scope_world,
)
from .memberships import _database_clock

ASSIGN_COMMAND_NAME = "assign_character_control"
REPLACE_COMMAND_NAME = "replace_primary_controller"
REVOKE_COMMAND_NAME = "revoke_character_control"

PRIMARY = "primary_controller"
CO = "co_controller"

cm = campaign_memberships
mcr = membership_character_relationships
mr = membership_roles
crt = character_relationship_types
dl = character_assign_control_delegations

_TABLE_NAME = "membership_character_relationships"
_NOW = func.pg_catalog.clock_timestamp
_OWNER_KIND = "campaign_owner"
_GM_KIND = "gm"
_DELEGATION_KIND = "delegation"


# -- errors ---------------------------------------------------------------------------------------------


class AssignControlRequiredError(DomainAuthorizationError):
    """The caller holds no live built-in `campaign_owner` or `gm` assignment in this campaign. 403, one fixed body: the
    caller is an authorized campaign member and learns nothing about any target from being told so."""

    safe_status_code = 403
    safe_error_code = "character_assign_control_required"
    safe_message = "Only a campaign owner or game master may assign character control."


class ControlAssignmentRequestError(SafeMessageError):
    """The body is malformed (an unknown kind, a period that does not fit its kind, an end not after its start, a
    reason outside 1-1000 characters). 422, the same code FastAPI's own body validation answers."""

    safe_status_code = 422
    safe_error_code = "invalid_request"
    safe_message = "The request is invalid."


class PrimaryControllerExistsError(SafeMessageError):
    """A live primary controller already exists on the character (a dated one that has ended still occupies the slot).
    Use replace. 409."""

    safe_status_code = 409
    safe_error_code = "primary_controller_exists"
    safe_message = "The character already has a primary controller. Replace it instead."


class ControlAlreadyAssignedError(SafeMessageError):
    """The assignee already holds a live assignment of either role on the character. No implicit promotion. 409."""

    safe_status_code = 409
    safe_error_code = "control_already_assigned"
    safe_message = "That member already controls this character."


class NoPrimaryControllerError(SafeMessageError):
    """A replace names a character with no live primary controller. 409."""

    safe_status_code = 409
    safe_error_code = "no_primary_controller"
    safe_message = "The character has no primary controller to replace."


class ControlAssignmentsChangedError(SafeMessageError):
    """The character's live assignments changed between the locks and the re-read, in a way the request cannot repair
    under the reviewed lock order. Nothing is written; a retry judges the new state. 409."""

    safe_status_code = 409
    safe_error_code = "conflict"
    safe_message = "The character's control changed while the request was in progress. Try again."


# -- request bodies -------------------------------------------------------------------------------------

_Reason = Field(default=None, min_length=1, max_length=1000)


class _PeriodRequest(BaseModel):
    """The period of an assignment. The kind is required (OD-14: there is no default): `ongoing` carries no world time,
    `dated` a start and optionally an end."""

    model_config = ConfigDict(extra="forbid")

    campaign_membership_id: uuid.UUID
    assignment_period_kind: Literal["ongoing", "dated"]
    effective_from_world_time_id: uuid.UUID | None = None
    effective_to_world_time_id: uuid.UUID | None = None
    reason: str | None = _Reason

    @model_validator(mode="after")
    def _period_fits_its_kind(self) -> "_PeriodRequest":
        if self.assignment_period_kind == "ongoing" and (
            self.effective_from_world_time_id is not None
            or self.effective_to_world_time_id is not None
        ):
            raise ValueError("an ongoing assignment carries no world time")
        if self.assignment_period_kind == "dated" and self.effective_from_world_time_id is None:
            raise ValueError("a dated assignment needs a start")
        return self


class AssignRequest(_PeriodRequest):
    role: Literal["primary_controller", "co_controller"]


class ReplaceRequest(_PeriodRequest):
    pass


class RevokeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str | None = _Reason


def parse_request[RequestT: BaseModel](
    model: type[RequestT], raw: Mapping[str, Any] | None
) -> RequestT:
    """Validate the body **after** the authority was judged (403 before 422), so an unauthorized caller learns nothing
    about the body's shape."""
    try:
        return model.model_validate(dict(raw) if raw is not None else {})
    except ValidationError as error:
        raise ControlAssignmentRequestError(
            "the control assignment request is malformed"
        ) from error


# -- locks ----------------------------------------------------------------------------------------------

#: The caller's built-in owner or `gm` assignment, `FOR SHARE`, **bound to a row the unlocked discovery found** (bound
#: `row`, `membership`). Its liveness (template, expiry, membership state, account) is judged by the plain reads after
#: the last wait; the lock holds the row so a revocation, an end or a relinquishment waits for this transaction.
AUTHORITY_ROW_LOCK = PreLock(
    "assign_authority_row_share",
    select(mr.c.membership_role_id)
    .where(mr.c.membership_role_id == bindparam("row"))
    .where(mr.c.campaign_membership_id == bindparam("membership"))
    .where(mr.c.revoked_at.is_(None))
    .with_for_update(read=True),
)
#: A delegated holder's live delegation row, `FOR SHARE`, **bound to the row the unlocked discovery found** (bound
#: `delegation`, `membership`), taken right after the bound `assistant_gm` row (T02, plan section 3.2: role class, then
#: delegation class, before any membership). A revocation of the delegation waits for this transaction, or commits first
#: and the request is refused after its wait.
DELEGATION_ROW_LOCK = PreLock(
    "assign_delegation_row_share",
    select(dl.c.character_assign_control_delegation_id)
    .where(dl.c.character_assign_control_delegation_id == bindparam("delegation"))
    .where(dl.c.grantee_campaign_membership_id == bindparam("membership"))
    .where(dl.c.revoked_at.is_(None))
    .with_for_update(read=True),
)
#: The old primary's membership, `FOR UPDATE` (replace; bound `campaign`, `target`). The same shape as the assignee's.
OLD_PRIMARY_MEMBERSHIP_LOCK = PreLock(
    "old_primary_membership_update",
    select(cm.c.campaign_membership_id)
    .where(cm.c.campaign_id == bindparam("campaign"))
    .where(cm.c.campaign_membership_id == bindparam("old"))
    .with_for_update(),
)
#: A relationship type by code, `FOR KEY SHARE` (bound `code`): the INSERT's foreign key, taken here as evidence.
CONTROL_TYPE_LOCK = PreLock(
    "control_type_key_share",
    select(crt.c.character_relationship_type_id)
    .where(crt.c.code == bindparam("code"))
    .with_for_update(read=True, key_share=True),
)
#: The character's live assignment rows (this campaign), `FOR UPDATE`, ascending (bound `campaign`, `character`).
LIVE_ASSIGNMENTS_LOCK = PreLock(
    "character_live_assignments_update",
    select(mcr.c.membership_character_relationship_id)
    .where(mcr.c.campaign_id == bindparam("campaign"))
    .where(mcr.c.character_id == bindparam("character"))
    .where(mcr.c.is_control_assignment.is_(True))
    .where(mcr.c.revoked_at.is_(None))
    .order_by(mcr.c.membership_character_relationship_id)
    .with_for_update(),
)
#: The assignment a revoke closes, `FOR UPDATE`, only while **unrevoked** (bound `row`, `campaign`). Its evidence is the
#: database's own answer, under the lock, to "this request revokes": one key for a genuine revocation, none for the no-op.
ASSIGNMENT_ROW_LOCK = PreLock(
    "assignment_row_update",
    select(mcr.c.membership_character_relationship_id)
    .where(mcr.c.membership_character_relationship_id == bindparam("row"))
    .where(mcr.c.campaign_id == bindparam("campaign"))
    .where(mcr.c.is_control_assignment.is_(True))
    .where(mcr.c.revoked_at.is_(None))
    .with_for_update(),
)

# -- steps ----------------------------------------------------------------------------------------------

_CONCURRENCY_TESTS = "tests/database/test_control_assignment_concurrency.py::"
_COMPETING_ASSIGNMENT_WAITS = frozenset(
    {
        UniqueWait(
            "security.ux_membership_character_relationships_live_primary",
            _CONCURRENCY_TESTS + "test_a_competing_live_primary_is_a_unique_wait",
        ),
        UniqueWait(
            "security.ux_membership_character_relationships_live_assignment",
            _CONCURRENCY_TESTS + "test_a_competing_live_assignment_is_a_unique_wait",
        ),
        UniqueWait(
            "security.ux_membership_character_relationships_active_type",
            _CONCURRENCY_TESTS + "test_an_assignment_insert_never_waits_on_the_legacy_index",
        ),
    }
)
_LEAVING_TEST = (
    _CONCURRENCY_TESTS
    + "test_a_revoke_leaving_the_assignment_indexes_never_waits_for_a_competing_insert"
)
_LEAVES_ASSIGNMENT_INDEXES = frozenset(
    UniqueWait(index, _LEAVING_TEST)
    for index in (
        "security.ux_membership_character_relationships_live_primary",
        "security.ux_membership_character_relationships_live_assignment",
        "security.ux_membership_character_relationships_active_type",
    )
)


def _fk(column: str, bind: str, lock: PreLock | None) -> FkBinding:
    return FkBinding(fk_of(mcr, column), (KeyBind(mcr.c[column], bind),), lock)


_INSERT_FKS = (
    _fk("campaign_id", "campaign", CAMPAIGN_ROW_LOCK),
    _fk("campaign_membership_id", "membership", TARGET_MEMBERSHIP_LOCK),
    _fk("character_id", "character", CHARACTER_ROW_LOCK),
    _fk("character_relationship_type_id", "type", CONTROL_TYPE_LOCK),
    _fk("effective_from_world_time_id", "time_from", WORLD_TIMES_KEY_SHARE_LOCK),
    _fk("effective_to_world_time_id", "time_to", WORLD_TIMES_KEY_SHARE_LOCK),
    _fk("granted_by_membership_id", "granted_by", ACTOR_MEMBERSHIP_LOCK),
)
ASSIGN_INSERT = WriteStep(
    name="insert_control_assignment",
    statement=insert(mcr)
    .values(
        campaign_id=bindparam("campaign"),
        campaign_membership_id=bindparam("membership"),
        character_id=bindparam("character"),
        character_relationship_type_id=bindparam("type"),
        is_control_assignment=True,
        assignment_period_kind=bindparam("kind"),
        effective_from_world_time_id=bindparam("time_from"),
        effective_to_world_time_id=bindparam("time_to"),
        granted_by_membership_id=bindparam("granted_by"),
        notes=bindparam("notes"),
    )
    .returning(mcr.c.membership_character_relationship_id),
    cardinality=Exactly(1),
    fks=_INSERT_FKS,
    value_binds=frozenset({"kind", "notes"}),
    unique_waits=_COMPETING_ASSIGNMENT_WAITS,
    triggers=RELATIONSHIP_INSERT_TRIGGERS,
)
REPLACE_INSERT = WriteStep(
    name="insert_replacing_primary",
    statement=insert(mcr)
    .values(
        campaign_id=bindparam("campaign"),
        campaign_membership_id=bindparam("membership"),
        character_id=bindparam("character"),
        character_relationship_type_id=bindparam("type"),
        is_control_assignment=True,
        assignment_period_kind=bindparam("kind"),
        effective_from_world_time_id=bindparam("time_from"),
        effective_to_world_time_id=bindparam("time_to"),
        granted_by_membership_id=bindparam("granted_by"),
    )
    .returning(mcr.c.membership_character_relationship_id),
    cardinality=Exactly(1),
    fks=_INSERT_FKS,
    value_binds=frozenset({"kind"}),
    unique_waits=_COMPETING_ASSIGNMENT_WAITS,
    triggers=RELATIONSHIP_INSERT_TRIGGERS,
)


def _revoke_statement() -> Any:
    return (
        update(mcr)
        .where(mcr.c.membership_character_relationship_id == bindparam("target"))
        .values(
            revoked_at=_NOW(),
            revoked_by_membership_id=bindparam("revoked_by"),
            revocation_reason=bindparam("why"),
        )
        .returning(mcr.c.membership_character_relationship_id)
    )


REVOKE_OLD_PRIMARY = WriteStep(
    name="revoke_old_primary",
    statement=_revoke_statement(),
    cardinality=Exactly(1),
    target=(KeyBind(mcr.c.membership_character_relationship_id, "target"),),
    target_lock=LIVE_ASSIGNMENTS_LOCK,
    fks=(_fk("revoked_by_membership_id", "revoked_by", ACTOR_MEMBERSHIP_LOCK),),
    value_binds=frozenset({"why"}),
    unique_waits=_LEAVES_ASSIGNMENT_INDEXES,
    triggers=RELATIONSHIP_UPDATE_TRIGGERS,
)
REVOKE_ASSIGNMENT = WriteStep(
    name="revoke_control_assignment",
    statement=_revoke_statement(),
    cardinality=EachLockedRow(complete=True),
    target=(KeyBind(mcr.c.membership_character_relationship_id, "target"),),
    target_lock=ASSIGNMENT_ROW_LOCK,
    fks=(_fk("revoked_by_membership_id", "revoked_by", ACTOR_MEMBERSHIP_LOCK),),
    value_binds=frozenset({"why"}),
    unique_waits=_LEAVES_ASSIGNMENT_INDEXES,
    triggers=RELATIONSHIP_UPDATE_TRIGGERS,
)


ASSIGN_AUDIT = WriteStep(
    name="audit_control_assigned",
    statement=insert(change_log)
    .values(**_audit_values(_TABLE_NAME, ASSIGN_COMMAND_NAME))
    .returning(change_log.c.change_log_id),
    cardinality=Exactly(1),
    fks=(CHANGE_LOG_ACTION_FK, CHANGE_LOG_ACTOR_FK),
    value_binds=_AUDIT_BINDS,
)
REPLACE_AUDIT_REVOKED = WriteStep(
    name="audit_primary_revoked",
    statement=insert(change_log)
    .values(**_audit_values(_TABLE_NAME, REPLACE_COMMAND_NAME))
    .returning(change_log.c.change_log_id),
    cardinality=Exactly(1),
    fks=(CHANGE_LOG_ACTION_FK, CHANGE_LOG_ACTOR_FK),
    value_binds=_AUDIT_BINDS,
)
REPLACE_AUDIT_ASSIGNED = WriteStep(
    name="audit_primary_assigned",
    statement=insert(change_log)
    .values(**_audit_values(_TABLE_NAME, REPLACE_COMMAND_NAME))
    .returning(change_log.c.change_log_id),
    cardinality=Exactly(1),
    fks=(CHANGE_LOG_ACTION_FK, CHANGE_LOG_ACTOR_FK),
    value_binds=_AUDIT_BINDS,
)
REVOKE_AUDIT = WriteStep(
    name="audit_control_revoked",
    statement=insert(change_log)
    .values(**_audit_values(_TABLE_NAME, REVOKE_COMMAND_NAME))
    .returning(change_log.c.change_log_id),
    cardinality=PerEvidence(ASSIGNMENT_ROW_LOCK),
    fks=(CHANGE_LOG_ACTION_FK, CHANGE_LOG_ACTOR_FK),
    value_binds=_AUDIT_BINDS,
)
RECEIPT = RECEIPT_STEP

# -- declarations ---------------------------------------------------------------------------------------

_UNLOCKED = CHANGE_LOG_UNLOCKED_FK_TARGETS

_ASSIGN_LOCKS = (
    AUTHORITY_ROW_LOCK,
    DELEGATION_ROW_LOCK,
    ACTOR_MEMBERSHIP_LOCK,
    TARGET_MEMBERSHIP_LOCK,
    ACTOR_ACCOUNT_LOCK,
    TARGET_ACCOUNT_LOCK,
    CAMPAIGN_ROW_LOCK,
    CONTROL_TYPE_LOCK,
    TARGET_ENTITY_LOCK,
    CHARACTER_ROW_LOCK,
    LIVE_ASSIGNMENTS_LOCK,
    WORLD_TIMES_KEY_SHARE_LOCK,
)
_ASSIGN_STEPS = (ASSIGN_INSERT, ASSIGN_AUDIT)
ASSIGN_DECLARATIONS = ReservationDeclarations(
    reserved=PreWriteDeclaration(
        locks=(*_ASSIGN_LOCKS, RECEIPT_LOCK),
        steps=(*_ASSIGN_STEPS, RECEIPT),
        unlocked_fk_targets=_UNLOCKED,
    ),
    unkeyed=PreWriteDeclaration(
        locks=_ASSIGN_LOCKS, steps=_ASSIGN_STEPS, unlocked_fk_targets=_UNLOCKED
    ),
)
_REPLACE_LOCKS = (
    AUTHORITY_ROW_LOCK,
    DELEGATION_ROW_LOCK,
    ACTOR_MEMBERSHIP_LOCK,
    TARGET_MEMBERSHIP_LOCK,
    OLD_PRIMARY_MEMBERSHIP_LOCK,
    ACTOR_ACCOUNT_LOCK,
    TARGET_ACCOUNT_LOCK,
    CAMPAIGN_ROW_LOCK,
    CONTROL_TYPE_LOCK,
    TARGET_ENTITY_LOCK,
    CHARACTER_ROW_LOCK,
    LIVE_ASSIGNMENTS_LOCK,
    WORLD_TIMES_KEY_SHARE_LOCK,
)
_REPLACE_STEPS = (REVOKE_OLD_PRIMARY, REPLACE_INSERT, REPLACE_AUDIT_REVOKED, REPLACE_AUDIT_ASSIGNED)
REPLACE_DECLARATIONS = ReservationDeclarations(
    reserved=PreWriteDeclaration(
        locks=(*_REPLACE_LOCKS, RECEIPT_LOCK),
        steps=(*_REPLACE_STEPS, RECEIPT),
        unlocked_fk_targets=_UNLOCKED,
    ),
    unkeyed=PreWriteDeclaration(
        locks=_REPLACE_LOCKS, steps=_REPLACE_STEPS, unlocked_fk_targets=_UNLOCKED
    ),
)
_REVOKE_LOCKS = (
    AUTHORITY_ROW_LOCK,
    DELEGATION_ROW_LOCK,
    ACTOR_MEMBERSHIP_LOCK,
    TARGET_MEMBERSHIP_LOCK,
    ACTOR_ACCOUNT_LOCK,
    CAMPAIGN_ROW_LOCK,
    TARGET_ENTITY_LOCK,
    ASSIGNMENT_ROW_LOCK,
)
_REVOKE_STEPS = (REVOKE_ASSIGNMENT, REVOKE_AUDIT)
REVOKE_DECLARATIONS = ReservationDeclarations(
    reserved=PreWriteDeclaration(
        locks=(*_REVOKE_LOCKS, RECEIPT_LOCK),
        steps=(*_REVOKE_STEPS, RECEIPT),
        unlocked_fk_targets=_UNLOCKED,
    ),
    unkeyed=PreWriteDeclaration(
        locks=_REVOKE_LOCKS, steps=_REVOKE_STEPS, unlocked_fk_targets=_UNLOCKED
    ),
)

# -- the final authorization requirement ---------------------------------------------------------------


def assign_control_requirement(
    campaign_id: uuid.UUID, actor_membership_id: uuid.UUID
) -> Requirement:
    """The operation's own authority, judged again at `finalize`'s one `t_auth`: the caller holds a live built-in
    `campaign_owner` or `gm` assignment, or a live delegation bound to a live `assistant_gm` assignment (the
    `assign_control` source of the same snapshot). Reads **only** that source: never the caller's capabilities,
    assignments or the campaign clock (F33)."""

    def decide(snapshot: AuthoritySnapshot) -> BaseException | None:
        if snapshot.assign_control_authority in (_OWNER_KIND, _GM_KIND, _DELEGATION_KIND):
            return None
        return AssignControlRequiredError(
            f"membership {actor_membership_id} holds no live campaign_owner or gm assignment "
            f"in campaign {campaign_id} at the final authorization instant"
        )

    return judged_requirement("assign_control.authority", decide, assign_control=True)


# -- shared reads ---------------------------------------------------------------------------------------

_DISCOVER_AUTHORITY_SQL = text(f"""
    SELECT mr.membership_role_id
    FROM security.membership_roles mr
    JOIN security.roles r ON r.role_id = mr.role_id
    JOIN security.campaign_memberships cm ON cm.campaign_membership_id = mr.campaign_membership_id
    JOIN security.membership_statuses ms ON ms.membership_status_id = cm.membership_status_id
    JOIN security.users u ON u.user_id = cm.user_id
    JOIN core.lifecycle_statuses uls ON uls.lifecycle_status_id = u.lifecycle_status_id
    WHERE mr.campaign_membership_id = :caller
      AND cm.campaign_id = :campaign
      AND r.campaign_id IS NULL
      AND r.code IN ('{BUILTIN_CAMPAIGN_OWNER_ROLE_CODE}', '{BUILTIN_CAMPAIGN_GM_ROLE_CODE}')
      AND r.is_active
      AND mr.revoked_at IS NULL
      AND (mr.expires_at IS NULL OR mr.expires_at > :t)
      AND cm.ended_at IS NULL
      AND ms.code = 'active'
      AND ms.is_active
      AND uls.code = 'active'
    ORDER BY mr.membership_role_id
""")  # noqa: S608 - the interpolated names are module constants

# T02 (OD-4a): the caller's live delegation and the live built-in `assistant_gm` row it is bound to, at `:t`. The same
# predicate as the snapshot component's `ac_assistant` and `ac_delegation` CTEs, read plainly (the lock follows).
_DISCOVER_DELEGATED_SQL = text(f"""
    SELECT d.character_assign_control_delegation_id AS delegation_id,
           d.assistant_gm_membership_role_id AS role_row_id
    FROM security.character_assign_control_delegations d
    JOIN security.membership_roles mr ON mr.membership_role_id = d.assistant_gm_membership_role_id
    JOIN security.roles r ON r.role_id = mr.role_id
    JOIN security.campaign_memberships cm ON cm.campaign_membership_id = mr.campaign_membership_id
    JOIN security.membership_statuses ms ON ms.membership_status_id = cm.membership_status_id
    JOIN security.users u ON u.user_id = cm.user_id
    JOIN core.lifecycle_statuses uls ON uls.lifecycle_status_id = u.lifecycle_status_id
    WHERE d.grantee_campaign_membership_id = :caller
      AND d.campaign_id = :campaign
      AND d.revoked_at IS NULL
      AND mr.campaign_membership_id = d.grantee_campaign_membership_id
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
    ORDER BY d.character_assign_control_delegation_id
""")  # noqa: S608 - the interpolated name is a module constant

_LIVE_ASSIGNMENTS_SQL = text("""
    SELECT mcr.membership_character_relationship_id AS row_id, mcr.campaign_membership_id,
           mcr.is_primary
    FROM security.membership_character_relationships mcr
    WHERE mcr.campaign_id = :campaign AND mcr.character_id = :character
      AND mcr.is_control_assignment AND mcr.revoked_at IS NULL
    ORDER BY mcr.membership_character_relationship_id
""")

_ASSIGNMENT_FOR_REVOKE_SQL = text("""
    SELECT mcr.campaign_id, mcr.campaign_membership_id, mcr.character_id, mcr.is_control_assignment,
           mcr.revoked_at IS NOT NULL AS revoked
    FROM security.membership_character_relationships mcr
    WHERE mcr.membership_character_relationship_id = :row
""")


def _discover_authority_rows(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    caller_membership_id: uuid.UUID,
    as_of: datetime | None,
) -> list[uuid.UUID]:
    """The caller's live built-in owner and `gm` assignment rows of this campaign (at the transaction start, or at
    `as_of`), ascending by id: the order they are locked in."""
    instant = connection.execute(text("SELECT now()")).scalar_one() if as_of is None else as_of
    return list(
        connection.execute(
            _DISCOVER_AUTHORITY_SQL,
            {"caller": caller_membership_id, "campaign": campaign_id, "t": instant},
        ).scalars()
    )


def _live_assignments(
    connection: Connection, campaign_id: uuid.UUID, character_id: uuid.UUID
) -> list[Any]:
    return list(
        connection.execute(
            _LIVE_ASSIGNMENTS_SQL, {"campaign": campaign_id, "character": character_id}
        ).mappings()
    )


@dataclass(frozen=True)
class ControlPrepared:
    """What the lock and read phase established, all before `finalize`."""

    world_id: uuid.UUID
    action_id: uuid.UUID
    campaign_id: uuid.UUID
    will_write: bool = True
    membership_id: uuid.UUID | None = None
    character_id: uuid.UUID | None = None
    type_id: uuid.UUID | None = None
    kind: str | None = None
    time_from_id: uuid.UUID | None = None
    time_to_id: uuid.UUID | None = None
    notes: str | None = None
    #: replace: the revoked primary and the reason recorded on it
    old_row_id: uuid.UUID | None = None
    reason: str | None = None


@dataclass(frozen=True)
class HeldAuthority:
    """What a request locked as its authority: the role rows (owner, `gm`, or the bound `assistant_gm` row) and the
    delegation rows, `FOR SHARE`. A built-in row is authority by itself; a delegation counts only with both its own row
    and the bound role row locked. `others` are the extra role rows a caller asked to lock in the same ascending pass
    (the delegation grant's recipient row), and are never authority."""

    role_rows: frozenset[uuid.UUID]
    delegations: frozenset[uuid.UUID]
    others: frozenset[uuid.UUID] = frozenset()


@dataclass(frozen=True)
class DiscoveredAuthority:
    """The caller's candidate authority rows, found without a lock: the built-in owner and `gm` rows, and a delegated
    holder's `(delegation, bound assistant_gm row)` pairs."""

    built_in: list[uuid.UUID]
    delegated: list[tuple[uuid.UUID, uuid.UUID]]


def _discover_delegated(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    caller_membership_id: uuid.UUID,
    as_of: datetime | None,
) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """The caller's live delegation and its bound live `assistant_gm` row (`(delegation, role row)`), ascending."""
    instant = connection.execute(text("SELECT now()")).scalar_one() if as_of is None else as_of
    return [
        (row.delegation_id, row.role_row_id)
        for row in connection.execute(
            _DISCOVER_DELEGATED_SQL,
            {"caller": caller_membership_id, "campaign": campaign_id, "t": instant},
        )
    ]


def _usable(discovered: DiscoveredAuthority, held: HeldAuthority) -> bool:
    return any(row in held.role_rows for row in discovered.built_in) or any(
        role in held.role_rows and delegation in held.delegations
        for delegation, role in discovered.delegated
    )


def _discover_authority(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_membership_id: uuid.UUID,
    allow_delegation: bool,
    as_of: datetime | None,
) -> DiscoveredAuthority:
    return DiscoveredAuthority(
        built_in=_discover_authority_rows(
            connection,
            campaign_id=campaign_id,
            caller_membership_id=actor_membership_id,
            as_of=as_of,
        ),
        delegated=(
            _discover_delegated(
                connection,
                campaign_id=campaign_id,
                caller_membership_id=actor_membership_id,
                as_of=as_of,
            )
            if allow_delegation
            else []
        ),
    )


def _discover_or_refuse(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_membership_id: uuid.UUID,
    allow_delegation: bool = True,
) -> DiscoveredAuthority:
    """Discover (unlocked) the caller's authority rows; 403 before anything is locked when there are none."""
    discovered = _discover_authority(
        connection,
        campaign_id=campaign_id,
        actor_membership_id=actor_membership_id,
        allow_delegation=allow_delegation,
        as_of=None,
    )
    if not discovered.built_in and not discovered.delegated:
        raise AssignControlRequiredError(
            f"membership {actor_membership_id} holds no live owner or gm assignment in campaign {campaign_id}"
        )
    return discovered


def _lock_authority(
    connection: Connection,
    plan: AuthorizationPlan,
    *,
    actor_membership_id: uuid.UUID,
    discovered: DiscoveredAuthority,
    others: tuple[tuple[uuid.UUID, PreLock, dict[str, Any]], ...] = (),
) -> HeldAuthority:
    """Lock the caller's authority rows: the role class first (the built-in rows, a delegated holder's bound
    `assistant_gm` row and any `others`, **one ascending pass over all of them**, each at its own mode), then the
    delegation row. 403 when none of the caller's rows survives its lock."""
    wanted: dict[uuid.UUID, tuple[PreLock, dict[str, Any], bool]] = {}
    for row_id in sorted({*discovered.built_in, *(role for _, role in discovered.delegated)}):
        wanted[row_id] = (
            AUTHORITY_ROW_LOCK,
            {"row": row_id, "membership": actor_membership_id},
            True,
        )
    for row_id, lock, binds in others:
        wanted[row_id] = (lock, binds, False)
    locked_roles: set[uuid.UUID] = set()
    locked_others: set[uuid.UUID] = set()
    for row_id in sorted(wanted):
        lock, binds, is_authority = wanted[row_id]
        if plan.lock(connection, lock, binds):
            (locked_roles if is_authority else locked_others).add(row_id)
    locked_delegations: set[uuid.UUID] = set()
    for delegation, role in discovered.delegated:
        if role in locked_roles and plan.lock(
            connection,
            DELEGATION_ROW_LOCK,
            {"delegation": delegation, "membership": actor_membership_id},
        ):
            locked_delegations.add(delegation)
    held = HeldAuthority(
        frozenset(locked_roles), frozenset(locked_delegations), frozenset(locked_others)
    )
    if not _usable(discovered, held):
        raise AssignControlRequiredError(
            f"membership {actor_membership_id}'s authority rows were revoked while the request waited"
        )
    return held


def _require_authority(
    connection: Connection,
    plan: AuthorizationPlan,
    *,
    campaign_id: uuid.UUID,
    actor_membership_id: uuid.UUID,
    allow_delegation: bool = True,
) -> HeldAuthority:
    """Discover and lock the caller's authority rows (the control writers' first step)."""
    discovered = _discover_or_refuse(
        connection,
        campaign_id=campaign_id,
        actor_membership_id=actor_membership_id,
        allow_delegation=allow_delegation,
    )
    return _lock_authority(
        connection, plan, actor_membership_id=actor_membership_id, discovered=discovered
    )


def _rejudge_authority(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_membership_id: uuid.UUID,
    locked: HeldAuthority,
    allow_delegation: bool = True,
) -> None:
    """After the last lock wait, at a fresh database instant: the caller still holds a live authority row, and one that
    this request locked (a row that appeared after discovery is not held, so it cannot be relied on)."""
    live = _discover_authority(
        connection,
        campaign_id=campaign_id,
        actor_membership_id=actor_membership_id,
        allow_delegation=allow_delegation,
        as_of=_database_clock(connection),
    )
    if not _usable(live, locked):
        raise AssignControlRequiredError(
            f"membership {actor_membership_id} no longer holds a live owner, gm or delegated assignment "
            f"authority in campaign {campaign_id}"
        )


def _lock_memberships(
    connection: Connection,
    plan: AuthorizationPlan,
    *,
    campaign_id: uuid.UUID,
    actor_membership_id: uuid.UUID,
    assignee_id: uuid.UUID | None,
    old_primary_id: uuid.UUID | None = None,
) -> None:
    """The membership class, one ascending pass, each membership once at the strongest mode it needs: the caller
    `FOR SHARE`, the assignee and the old primary's membership `FOR UPDATE`. A membership that is both is locked once,
    at the stronger mode, so the weaker never lands on a held row as an upgrade."""
    wanted: dict[uuid.UUID, str] = {actor_membership_id: "actor"}
    if assignee_id is not None:
        wanted[assignee_id] = "target"
    if old_primary_id is not None and old_primary_id != assignee_id:
        wanted[old_primary_id] = "old"
    for membership_id in sorted(wanted):
        kind = wanted[membership_id]
        if kind == "actor":
            plan.lock(
                connection,
                ACTOR_MEMBERSHIP_LOCK,
                {"membership": membership_id, "campaign": campaign_id},
            )
        elif kind == "target":
            plan.lock(
                connection,
                TARGET_MEMBERSHIP_LOCK,
                {"campaign": campaign_id, "target": membership_id},
            )
        else:
            plan.lock(
                connection,
                OLD_PRIMARY_MEMBERSHIP_LOCK,
                {"campaign": campaign_id, "old": membership_id},
            )


def _check_character_and_times(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    character_id: uuid.UUID,
    time_from_id: uuid.UUID | None,
    time_to_id: uuid.UUID | None,
) -> uuid.UUID:
    """404 for a character missing, of another world or not active, and for a world time of another world; 422 for an
    end not after its start. Returns the campaign's world."""
    world_id = _scope_world(connection, campaign_id)
    character = connection.execute(_ENTITY_ROW, {"e": character_id}).mappings().one_or_none()
    if not (
        character is not None
        and character["world_id"] == world_id
        and character["lifecycle_status_code"] == "active"
    ):
        raise TargetNotInCampaignWorldError(
            f"character {character_id} does not exist in world {world_id}, or is not currently active"
        )
    if time_from_id is not None:
        from_key = _world_time_sort_key(
            connection, world_time_id=time_from_id, expected_world_id=world_id
        )
        if time_to_id is not None:
            to_key = _world_time_sort_key(
                connection, world_time_id=time_to_id, expected_world_id=world_id
            )
            if to_key <= from_key:
                raise ControlAssignmentRequestError(
                    f"assignment end (sort_key {to_key}) must be later than its start (sort_key {from_key})"
                )
    return world_id


def _check_assignee(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    assignee_id: uuid.UUID,
    status_before: Any,
) -> None:
    """404 for another campaign's membership; 409 for an ended or inactive one, an inactive campaign or account."""
    membership = connection.execute(_MEMBERSHIP_ROW, {"m": assignee_id}).mappings().one_or_none()
    if membership is None or membership["campaign_id"] != campaign_id:
        raise MembershipNotInCampaignError(
            f"membership {assignee_id} does not belong to campaign {campaign_id}"
        )
    if not (
        membership["ended_at"] is None
        and membership["status_code"] == "active"
        and membership["status_is_active"]
    ):
        _became_ineligible_while_waiting(membership, status_before, assignee_id)
        raise MembershipNotActiveError(
            f"membership {assignee_id} is not currently an eligible, open membership to assign control to"
        )
    _require_campaign_active(connection, campaign_id)
    account = connection.execute(
        text(
            "SELECT ls.code FROM security.users u "
            "JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = u.lifecycle_status_id "
            "WHERE u.user_id = :u"
        ),
        {"u": membership["user_id"]},
    ).scalar()
    if account != "active":
        raise MembershipNotActiveError(
            f"membership {assignee_id}'s account is not currently an active platform account"
        )


def _lock_character_rows(
    connection: Connection,
    plan: AuthorizationPlan,
    *,
    campaign_id: uuid.UUID,
    character_id: uuid.UUID,
    time_from_id: uuid.UUID | None,
    time_to_id: uuid.UUID | None,
    type_code: str | None,
) -> tuple[bool, set[uuid.UUID]]:
    """Catalogue row, anchor, character row, the live assignment rows and the dated world times, in the class order.
    Returns whether the character row exists (an entity that is not a character is a 404) and the locked live ids."""
    if type_code is not None:
        plan.lock(connection, CONTROL_TYPE_LOCK, {"code": type_code})
    plan.lock(connection, TARGET_ENTITY_LOCK, {"entity": character_id})
    character_row = plan.lock(connection, CHARACTER_ROW_LOCK, {"character": character_id})
    live = plan.lock(
        connection, LIVE_ASSIGNMENTS_LOCK, {"campaign": campaign_id, "character": character_id}
    )
    _lock_scope_rows(
        connection, plan, timeline_id=None, time_from_id=time_from_id, time_to_id=time_to_id
    )
    return bool(character_row), {key[0] for key in live}


def _verify_locked_set(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    character_id: uuid.UUID,
    locked: set[uuid.UUID],
) -> list[Any]:
    """The live set read again under the anchor equals the locked set; a difference is a 409."""
    rows = _live_assignments(connection, campaign_id, character_id)
    if {row["row_id"] for row in rows} != locked:
        raise ControlAssignmentsChangedError(
            f"character {character_id}'s live assignments changed while the request waited"
        )
    return rows


def _type_id(connection: Connection, code: str) -> uuid.UUID:
    value = connection.execute(
        text(
            "SELECT character_relationship_type_id FROM security.character_relationship_types "
            "WHERE code = :code AND is_active"
        ),
        {"code": code},
    ).scalar()
    if value is None:
        raise TargetNotInCampaignWorldError(f"relationship type {code!r} is not active")
    assert isinstance(value, uuid.UUID)
    return value


# -- assign ---------------------------------------------------------------------------------------------


def prepare_assign(
    connection: Connection,
    plan: AuthorizationPlan,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    actor_membership_id: uuid.UUID,
    character_id: uuid.UUID,
    raw: Mapping[str, Any] | None,
    reservation_id: uuid.UUID | None,
) -> ControlPrepared:
    locked_authority = _require_authority(
        connection, plan, campaign_id=campaign_id, actor_membership_id=actor_membership_id
    )
    request = parse_request(AssignRequest, raw)
    assignee_id = request.campaign_membership_id
    role, kind = request.role, request.assignment_period_kind
    time_from_id = request.effective_from_world_time_id
    time_to_id = request.effective_to_world_time_id
    reason = request.reason
    status_before = _status_before(connection, assignee_id)
    _lock_memberships(
        connection,
        plan,
        campaign_id=campaign_id,
        actor_membership_id=actor_membership_id,
        assignee_id=assignee_id,
    )
    plan.lock(connection, ACTOR_ACCOUNT_LOCK, {"actor": actor_user_id})
    assignee = connection.execute(_MEMBERSHIP_ROW, {"m": assignee_id}).mappings().one_or_none()
    if assignee is not None and assignee["campaign_id"] == campaign_id:
        plan.lock(connection, TARGET_ACCOUNT_LOCK, {"target_user": assignee["user_id"]})
    plan.lock(connection, CAMPAIGN_ROW_LOCK, {"campaign": campaign_id})
    character_exists, locked = _lock_character_rows(
        connection,
        plan,
        campaign_id=campaign_id,
        character_id=character_id,
        time_from_id=time_from_id,
        time_to_id=time_to_id,
        type_code=role,
    )
    if reservation_id is not None:
        plan.lock(connection, RECEIPT_LOCK, {"receipt": reservation_id})
    # every lock wait is behind us: the authority first, then the reads and refusals in the plan's order
    _rejudge_authority(
        connection,
        campaign_id=campaign_id,
        actor_membership_id=actor_membership_id,
        locked=locked_authority,
    )
    rows = _verify_locked_set(
        connection, campaign_id=campaign_id, character_id=character_id, locked=locked
    )
    world_id = _check_character_and_times(
        connection,
        campaign_id=campaign_id,
        character_id=character_id,
        time_from_id=time_from_id,
        time_to_id=time_to_id,
    )
    _check_assignee(
        connection, campaign_id=campaign_id, assignee_id=assignee_id, status_before=status_before
    )
    if role == PRIMARY and any(row["is_primary"] for row in rows):
        raise PrimaryControllerExistsError(f"character {character_id} already has a live primary")
    if any(row["campaign_membership_id"] == assignee_id for row in rows):
        raise ControlAlreadyAssignedError(
            f"membership {assignee_id} already holds a live assignment on character {character_id}"
        )
    if not character_exists:
        raise TargetNotInCampaignWorldError(f"entity {character_id} is not a character")
    plan.require(connection, assign_control_requirement(campaign_id, actor_membership_id))
    return ControlPrepared(
        world_id=world_id,
        action_id=lookup_id(connection, "audit", "change_actions", "change_action_id", "created"),
        campaign_id=campaign_id,
        membership_id=assignee_id,
        character_id=character_id,
        type_id=_type_id(connection, role),
        kind=kind,
        time_from_id=time_from_id,
        time_to_id=time_to_id,
        notes=reason,
    )


def _audit_binds(
    prepared: ControlPrepared,
    *,
    record: uuid.UUID,
    actor_user_id: uuid.UUID,
    correlation_id: str | None,
) -> dict[str, Any]:
    return {
        "action": prepared.action_id,
        "record": record,
        "world": prepared.world_id,
        "actor": actor_user_id,
        "correlation": uuid.UUID(correlation_id) if correlation_id is not None else None,
    }


def _insert_binds(prepared: ControlPrepared, actor_membership_id: uuid.UUID) -> dict[str, Any]:
    return {
        "campaign": prepared.campaign_id,
        "membership": prepared.membership_id,
        "character": prepared.character_id,
        "type": prepared.type_id,
        "kind": prepared.kind,
        "time_from": prepared.time_from_id,
        "time_to": prepared.time_to_id,
        "granted_by": actor_membership_id,
    }


def write_assign(
    connection: Connection,
    plan: AuthorizationPlan,
    prepared: ControlPrepared,
    *,
    actor_user_id: uuid.UUID,
    actor_membership_id: uuid.UUID,
    correlation_id: str | None,
) -> uuid.UUID:
    created = plan.execute(
        connection,
        ASSIGN_INSERT,
        {**_insert_binds(prepared, actor_membership_id), "notes": prepared.notes},
    )
    new_id = created.keys[0][0]
    assert isinstance(new_id, uuid.UUID)
    plan.execute(
        connection,
        ASSIGN_AUDIT,
        _audit_binds(
            prepared, record=new_id, actor_user_id=actor_user_id, correlation_id=correlation_id
        ),
    )
    return new_id


# -- replace --------------------------------------------------------------------------------------------


def prepare_replace(
    connection: Connection,
    plan: AuthorizationPlan,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    actor_membership_id: uuid.UUID,
    character_id: uuid.UUID,
    raw: Mapping[str, Any] | None,
    reservation_id: uuid.UUID | None,
) -> ControlPrepared:
    locked_authority = _require_authority(
        connection, plan, campaign_id=campaign_id, actor_membership_id=actor_membership_id
    )
    request = parse_request(ReplaceRequest, raw)
    assignee_id = request.campaign_membership_id
    kind = request.assignment_period_kind
    time_from_id = request.effective_from_world_time_id
    time_to_id = request.effective_to_world_time_id
    reason = request.reason
    status_before = _status_before(connection, assignee_id)
    discovered = next(
        (r for r in _live_assignments(connection, campaign_id, character_id) if r["is_primary"]),
        None,
    )
    old_membership = discovered["campaign_membership_id"] if discovered is not None else None
    _lock_memberships(
        connection,
        plan,
        campaign_id=campaign_id,
        actor_membership_id=actor_membership_id,
        assignee_id=assignee_id,
        old_primary_id=old_membership,
    )
    plan.lock(connection, ACTOR_ACCOUNT_LOCK, {"actor": actor_user_id})
    assignee = connection.execute(_MEMBERSHIP_ROW, {"m": assignee_id}).mappings().one_or_none()
    if assignee is not None and assignee["campaign_id"] == campaign_id:
        plan.lock(connection, TARGET_ACCOUNT_LOCK, {"target_user": assignee["user_id"]})
    plan.lock(connection, CAMPAIGN_ROW_LOCK, {"campaign": campaign_id})
    character_exists, locked = _lock_character_rows(
        connection,
        plan,
        campaign_id=campaign_id,
        character_id=character_id,
        time_from_id=time_from_id,
        time_to_id=time_to_id,
        type_code=PRIMARY,
    )
    if reservation_id is not None:
        plan.lock(connection, RECEIPT_LOCK, {"receipt": reservation_id})
    _rejudge_authority(
        connection,
        campaign_id=campaign_id,
        actor_membership_id=actor_membership_id,
        locked=locked_authority,
    )
    rows = _verify_locked_set(
        connection, campaign_id=campaign_id, character_id=character_id, locked=locked
    )
    world_id = _check_character_and_times(
        connection,
        campaign_id=campaign_id,
        character_id=character_id,
        time_from_id=time_from_id,
        time_to_id=time_to_id,
    )
    _check_assignee(
        connection, campaign_id=campaign_id, assignee_id=assignee_id, status_before=status_before
    )
    if any(row["campaign_membership_id"] == assignee_id for row in rows):
        raise ControlAlreadyAssignedError(
            f"membership {assignee_id} already holds a live assignment on character {character_id}"
        )
    primary = next((row for row in rows if row["is_primary"]), None)
    if primary is None:
        raise NoPrimaryControllerError(f"character {character_id} has no live primary controller")
    if discovered is None or primary["row_id"] != discovered["row_id"]:
        # the primary appeared or changed after discovery: its membership is not among the locked memberships
        raise ControlAssignmentsChangedError(
            f"character {character_id}'s primary controller changed while the request waited"
        )
    if not character_exists:
        raise TargetNotInCampaignWorldError(f"entity {character_id} is not a character")
    plan.require(connection, assign_control_requirement(campaign_id, actor_membership_id))
    return ControlPrepared(
        world_id=world_id,
        action_id=lookup_id(connection, "audit", "change_actions", "change_action_id", "created"),
        campaign_id=campaign_id,
        membership_id=assignee_id,
        character_id=character_id,
        type_id=_type_id(connection, PRIMARY),
        kind=kind,
        time_from_id=time_from_id,
        time_to_id=time_to_id,
        old_row_id=primary["row_id"],
        reason=reason,
    )


def write_replace(
    connection: Connection,
    plan: AuthorizationPlan,
    prepared: ControlPrepared,
    *,
    actor_user_id: uuid.UUID,
    actor_membership_id: uuid.UUID,
    correlation_id: str | None,
) -> tuple[uuid.UUID, uuid.UUID]:
    old_id = prepared.old_row_id
    assert old_id is not None
    plan.execute(
        connection,
        REVOKE_OLD_PRIMARY,
        {"target": old_id, "revoked_by": actor_membership_id, "why": prepared.reason},
    )
    created = plan.execute(connection, REPLACE_INSERT, _insert_binds(prepared, actor_membership_id))
    new_id = created.keys[0][0]
    assert isinstance(new_id, uuid.UUID)
    plan.execute(
        connection,
        REPLACE_AUDIT_REVOKED,
        _audit_binds(
            prepared, record=old_id, actor_user_id=actor_user_id, correlation_id=correlation_id
        ),
    )
    plan.execute(
        connection,
        REPLACE_AUDIT_ASSIGNED,
        _audit_binds(
            prepared, record=new_id, actor_user_id=actor_user_id, correlation_id=correlation_id
        ),
    )
    return new_id, old_id


# -- revoke ---------------------------------------------------------------------------------------------


def prepare_revoke(
    connection: Connection,
    plan: AuthorizationPlan,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    actor_membership_id: uuid.UUID,
    assignment_id: uuid.UUID,
    raw: Mapping[str, Any] | None,
    reservation_id: uuid.UUID | None,
) -> ControlPrepared:
    locked_authority = _require_authority(
        connection, plan, campaign_id=campaign_id, actor_membership_id=actor_membership_id
    )
    reason = parse_request(RevokeRequest, raw).reason
    found = (
        connection.execute(_ASSIGNMENT_FOR_REVOKE_SQL, {"row": assignment_id})
        .mappings()
        .one_or_none()
    )
    if found is None or found["campaign_id"] != campaign_id or not found["is_control_assignment"]:
        raise MembershipNotInCampaignError(
            f"control assignment {assignment_id} does not belong to campaign {campaign_id}"
        )
    owner_membership = found["campaign_membership_id"]
    character_id = found["character_id"]
    _lock_memberships(
        connection,
        plan,
        campaign_id=campaign_id,
        actor_membership_id=actor_membership_id,
        assignee_id=owner_membership,
    )
    plan.lock(connection, ACTOR_ACCOUNT_LOCK, {"actor": actor_user_id})
    plan.lock(connection, CAMPAIGN_ROW_LOCK, {"campaign": campaign_id})
    plan.lock(connection, TARGET_ENTITY_LOCK, {"entity": character_id})
    outstanding = plan.lock(
        connection, ASSIGNMENT_ROW_LOCK, {"row": assignment_id, "campaign": campaign_id}
    )
    if reservation_id is not None:
        plan.lock(connection, RECEIPT_LOCK, {"receipt": reservation_id})
    _rejudge_authority(
        connection,
        campaign_id=campaign_id,
        actor_membership_id=actor_membership_id,
        locked=locked_authority,
    )
    plan.require(connection, assign_control_requirement(campaign_id, actor_membership_id))
    return ControlPrepared(
        world_id=_scope_world(connection, campaign_id),
        action_id=lookup_id(connection, "audit", "change_actions", "change_action_id", "updated"),
        campaign_id=campaign_id,
        will_write=bool(outstanding),
        reason=reason,
    )


def write_revoke(
    connection: Connection,
    plan: AuthorizationPlan,
    prepared: ControlPrepared,
    *,
    assignment_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    actor_membership_id: uuid.UUID,
    correlation_id: str | None,
) -> bool:
    """The declared revocation and its audit row (attempted only by a genuine revoke)."""
    if not prepared.will_write:
        return False
    plan.execute(
        connection,
        REVOKE_ASSIGNMENT,
        {"target": assignment_id, "revoked_by": actor_membership_id, "why": prepared.reason},
    )
    plan.execute(
        connection,
        REVOKE_AUDIT,
        _audit_binds(
            prepared,
            record=assignment_id,
            actor_user_id=actor_user_id,
            correlation_id=correlation_id,
        ),
    )
    return True


__all__ = [
    "ASSIGN_DECLARATIONS",
    "AssignRequest",
    "ReplaceRequest",
    "RevokeRequest",
    "REPLACE_DECLARATIONS",
    "REVOKE_DECLARATIONS",
    "RECEIPT",
    "AUTHORITY_ROW_LOCK",
    "AssignControlRequiredError",
    "ControlAssignmentRequestError",
    "HeldAuthority",
    "assign_control_requirement",
    "prepare_assign",
    "prepare_replace",
    "prepare_revoke",
    "write_assign",
    "write_replace",
    "write_revoke",
]
