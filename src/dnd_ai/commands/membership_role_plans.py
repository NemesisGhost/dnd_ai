"""Add member, assign role, change role and revoke role as keyed pre-write plans (R01 S5-E2; plan 6.27).

`add_campaign_member`, `assign_membership_role`, `change_membership_role` and `revoke_membership_role` in
`memberships.py` stay as the direct, unguarded commands. The four routes (`dnd_ai.api.memberships`) use the
declarations and the lock, read and write phases below, so that **every lock is taken before `plan.finalize`**,
every read the command's refusals depend on happens before it, and every write is a declared step after it.
(Ownership transfer is **not** migrated here: plan 6.27, "The gap".)

## The one deliberate reading of the global order

The review's order is world, role rows, delegation rows, memberships, accounts, campaign, catalogue rows,
targets. Its rule is "each class ascending by id; a row that is both the actor's and the target's is taken
once, at the stronger mode". Two managers revoking or assigning *each other's* rows would cycle if the actor's
rows (`FOR SHARE`) and the target's rows (`FOR UPDATE`) were taken by separate statements: A holds its own
rows and wants B's, B holds its own and wants A's. A single ordered statement per class cannot do that
either unless it covers actor and target together, and one statement has one lock mode. So **a class that
contains a target is locked by one ordered statement over actor and target rows `FOR UPDATE`**: the role rows
for change and revoke (the actor's unrevoked roles and the target role), the memberships for assign and
change (the actor's open membership and the target's). The actor's rows are therefore locked at the stronger
mode than the review's table says, and only for these commands; a class with no target keeps `FOR SHARE`.
That is a cost (an actor's concurrent authoring requests, which hold the same rows `FOR SHARE`, queue behind
the command, and the reverse), not a new cycle: every locker takes roles before memberships before accounts
before the campaign.

## Lock sequences (implicit foreign-key locks and triggers included)

Key to modes: S `FOR SHARE`, KS `FOR KEY SHARE`, U `FOR UPDATE`. A keyed request starts with the advisory key
lock, the reservation `INSERT` (the actor's account KS; the campaign FK deferred) and ends with the receipt
row U; an unkeyed one has neither.

**Add member.** actor's unrevoked role rows S, actor's open membership S, actor's account S, the target's
account KS, the campaign U (`add_campaign_member` took it first; the INSERT's campaign FK re-acquires it), the
role row U, the target's unrevoked local-login identity rows U, [receipt U], reads and refusals,
`plan.finalize`, then `INSERT campaign_memberships` (FKs: campaign, target account, `membership_statuses`;
`ux_campaign_memberships_open` is a unique wait), `INSERT membership_roles` (FKs: the **new** membership of
this transaction, the role, the actor's membership), two `audit.change_log` inserts, [receipt UPDATE].

**Assign role.** actor's unrevoked role rows S, then actor's and target's memberships U (one statement), the
actor's account S, the target's account KS, the campaign KS (it inserts; the retention trigger does not fire
on an insert), the role row U, [receipt U], reads, `finalize`, `INSERT membership_roles` (`ux_membership_roles_
active` is a unique wait), audit, [receipt].

**Change role.** actor's unrevoked role rows and the target role U (one statement), the open reveal delegation
bound to the target role U, actor's and target's memberships U, the actor's account S, the campaign U (the
deferred retention trigger fires on the update and re-acquires it), the current and new role rows U (one
statement), [receipt U], reads, the retention pre-check, `finalize`, then `UPDATE` the old assignment,
`UPDATE` the delegation (each locked row), `INSERT` the new assignment, audit, [receipt].

**Revoke role.** actor's unrevoked role rows and the target role U, the target role again U only while it is
outstanding (`REVOKE_OUTSTANDING_LOCK`; held, no wait), the delegation bound to it U (only while outstanding),
actor's membership S, actor's account S, the campaign U, [receipt U], reads, the retention pre-check (only
while outstanding), `finalize`, `UPDATE` the role, `UPDATE` the delegation, audit, [receipt].

## Declared obligations

| Route | Writes |
|---|---|
| add | membership `Exactly(1)`, role `Exactly(1)`, two audit rows `Exactly(1)` each, receipt `Exactly(1)` (keyed) |
| assign | role `Exactly(1)`, audit `Exactly(1)`, receipt |
| change | old assignment `Exactly(1)`, delegations `EachLockedRow(complete=True)`, new assignment `Exactly(1)`, audit `Exactly(1)`, receipt |
| revoke | role `EachLockedRow(complete=True)` and audit `PerEvidence` over the outstanding lock, delegations `EachLockedRow(complete=True)`, receipt |

Only revoke has a legitimate no-op (an already-revoked assignment); it owes and may do nothing but its receipt.
No `Between` is used. A duplicate assignment, a duplicate open membership or a role already held is refused
by the unique index at the declared INSERT (a 409, as before), after `finalize`, rolling everything back.

## Retention, self-affecting operations, replay

The review moves the "a manager survives" check **before** `finalize`, under the held campaign lock:
`_manager_survives` evaluates the post-write state (the revoked assignment excluded, a changed-to role
included). The refusal is the same `ValueError` (400) as before; the deferred trigger stays the backstop.
Self-revocation, self-demotion and self-assignment are judged against the **pre-command** authority: the
route requirement is evaluated at `finalize`, before any write, and nothing newly granted exists yet. The
owner-role gate (decision D3) and its DEF-013 recheck are plain reads made before `finalize`; they take no lock
of their own (the owner assignment is among the actor's locked role rows).
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Connection, and_, bindparam, func, insert, or_, select, text, update

from dnd_ai.domain.access import find_live_builtin_owner_assignment, is_builtin_campaign_owner_role
from dnd_ai.domain.authorization import AuthorizationPlan, ReservationDeclarations
from dnd_ai.domain.authorization_steps import (
    AnyConfirmed,
    EachLockedRow,
    Event,
    Exactly,
    FkBinding,
    FunctionPin,
    KeyBind,
    Level,
    PerAbsence,
    PerEvidence,
    PreLock,
    PreWriteDeclaration,
    Timing,
    TriggerPin,
    UniqueWait,
    WriteStep,
)
from dnd_ai.persistence.tables.audit import change_log
from dnd_ai.persistence.tables.security import (
    campaign_memberships,
    character_reveal_delegations,
    external_identities,
    membership_roles,
    membership_statuses,
    roles,
    users,
)

from ._pre_write_steps import (
    CAMPAIGN_KEY_SHARE_LOCK,
    CHANGE_LOG_ACTION_FK,
    CHANGE_LOG_ACTOR_FK,
    CHANGE_LOG_UNLOCKED_FK_TARGETS,
    RECEIPT_LOCK,
    RECEIPT_STEP,
    fk_of,
)
from ._shared import lookup_id
from .campaign_lifecycle_plans import (
    ACTOR_ACCOUNT_LOCK,
    ACTOR_MEMBERSHIP_LOCK,
    ACTOR_ROLES_LOCK,
    CAMPAIGN_ROW_LOCK,
)
from .memberships import (
    AccountNotEligibleError,
    CampaignNotActiveError,
    CampaignOwnerRequiredError,
    ChangeMembershipRoleNoOpError,
    MembershipNotActiveError,
    MembershipNotInCampaignError,
    MembershipRoleNotActiveError,
    OwnershipTransferRecipientAssignmentExpiresError,
    OwnershipTransferRecipientChangedError,
    RoleNotUsableByCampaignError,
)
from .reveal_delegation_lifecycle import END_REASON_GM_ROLE_CHANGED, END_REASON_GM_ROLE_REVOKED

ADD_COMMAND_NAME = "add_campaign_member"
ASSIGN_COMMAND_NAME = "assign_membership_role"
REVOKE_COMMAND_NAME = "revoke_membership_role"
CHANGE_COMMAND_NAME = "change_membership_role"

cm = campaign_memberships
mr = membership_roles
dl = character_reveal_delegations

_LOCAL_ISSUER_PLACEHOLDER = "issuer"


def _pin(
    name: str,
    function_schema: str,
    function_name: str,
    source_md5: str,
    *,
    timing: Timing = Timing.BEFORE,
    events: frozenset[Event] = frozenset({Event.INSERT, Event.UPDATE}),
    args: tuple[str, ...] = (),
    constraint: bool = False,
) -> TriggerPin:
    return TriggerPin(
        name=name,
        timing=timing,
        level=Level.ROW,
        events=events,
        update_columns=None,
        when_hash=None,
        enabled="O",
        constraint_trigger=constraint,
        deferrable=constraint,
        initially_deferred=constraint,
        args=args,
        function=FunctionPin(
            schema=function_schema,
            name=function_name,
            arg_types="",
            language="plpgsql",
            security_definer=False,
            config=None,
            volatility="v",
            source_md5=source_md5,
        ),
    )


_UPDATED_AT = ("core", "set_updated_at", "fa4e845cca4d0acb6dd3509d9d6c2098")
_IMMUTABLE = ("core", "enforce_immutable_columns", "583c3783f15f299e7fc903503f694c6b")

MEMBERSHIP_TRIGGERS = frozenset(
    {
        _pin(
            "tr_campaign_memberships_enforce_actor_scope",
            "security",
            "enforce_campaign_membership_actor_scope",
            "1ae1e80124ef638f0e542d30598560fd",
        ),
        _pin(
            "tr_campaign_memberships_enforce_immutable",
            *_IMMUTABLE,
            events=frozenset({Event.UPDATE}),
            args=("campaign_id",),
        ),
        _pin(
            "tr_campaign_memberships_retain_access_manager",
            "security",
            "enforce_campaign_memberships_retain_access_manager",
            "f861a66ca0a9b898d0f7275756b0a991",
            timing=Timing.AFTER,
            events=frozenset({Event.UPDATE, Event.DELETE}),
            constraint=True,
        ),
        _pin(
            "tr_campaign_memberships_set_updated_at", *_UPDATED_AT, events=frozenset({Event.UPDATE})
        ),
    }
)
MEMBERSHIP_ROLE_TRIGGERS = frozenset(
    {
        _pin(
            "tr_membership_roles_enforce_scope",
            "security",
            "enforce_membership_role_scope",
            "ab6f599c2ad9af31e5f9e79ffe580771",
        ),
        _pin(
            "tr_membership_roles_retain_access_manager",
            "security",
            "enforce_membership_roles_retain_access_manager",
            "485d6fec5f6e06eb2109d097cadbb112",
            timing=Timing.AFTER,
            events=frozenset({Event.UPDATE, Event.DELETE}),
            constraint=True,
        ),
    }
)
DELEGATION_TRIGGERS = frozenset(
    {
        _pin(
            "tr_character_reveal_delegations_enforce_immutable",
            *_IMMUTABLE,
            events=frozenset({Event.UPDATE}),
            args=(
                "campaign_id",
                "grantee_campaign_membership_id",
                "gm_membership_role_id",
                "granted_at",
                "reason",
            ),
        ),
        _pin(
            "tr_character_reveal_delegations_enforce_scope",
            "security",
            "enforce_character_reveal_delegation_scope",
            "963e2437fa3b33dd2d8eebe332dad05a",
        ),
        _pin(
            "tr_character_reveal_delegations_set_updated_at",
            *_UPDATED_AT,
            events=frozenset({Event.UPDATE}),
        ),
    }
)

# -- locks ----------------------------------------------------------------------------------------------

#: The actor's unrevoked role rows and the target role, **one ordered statement, `FOR UPDATE`** (module
#: docstring: why actor and target are locked together). Bound `membership` (the actor's) and `target`.
ROLE_ROWS_WITH_TARGET = PreLock(
    "role_rows_with_target",
    select(mr.c.membership_role_id)
    .where(
        or_(
            mr.c.membership_role_id == bindparam("target"),
            and_(mr.c.campaign_membership_id == bindparam("membership"), mr.c.revoked_at.is_(None)),
        )
    )
    .order_by(mr.c.membership_role_id)
    .with_for_update(),
)
#: The target role again, `FOR UPDATE`, only while it is outstanding (not revoked): already held (no wait).
#: Its evidence is database state under the lock: one key when a revocation is genuine, none for a no-op.
REVOKE_OUTSTANDING_LOCK = PreLock(
    "role_outstanding_row",
    select(mr.c.membership_role_id)
    .where(mr.c.membership_role_id == bindparam("target"))
    .where(mr.c.revoked_at.is_(None))
    .with_for_update(),
)
#: The open reveal delegation bound to one role assignment (bound `role`), `FOR UPDATE`.
DELEGATION_LOCK = PreLock(
    "role_delegation_rows",
    select(dl.c.character_reveal_delegation_id)
    .where(dl.c.gm_membership_role_id == bindparam("role"))
    .where(dl.c.revoked_at.is_(None))
    .order_by(dl.c.character_reveal_delegation_id)
    .with_for_update(),
)
#: The actor's open membership and the target membership, one ordered statement, `FOR UPDATE`. Bound
#: `campaign`, `actor`, `target`. A target of another campaign matches nothing.
MEMBERSHIPS_ACTOR_TARGET = PreLock(
    "memberships_actor_target",
    select(cm.c.campaign_membership_id)
    .where(cm.c.campaign_id == bindparam("campaign"))
    .where(
        or_(
            and_(cm.c.campaign_membership_id == bindparam("actor"), cm.c.ended_at.is_(None)),
            cm.c.campaign_membership_id == bindparam("target"),
        )
    )
    .order_by(cm.c.campaign_membership_id)
    .with_for_update(),
)
#: The target's account, `FOR KEY SHARE` (S5-A; bound `target_user`).
TARGET_ACCOUNT_LOCK = PreLock(
    "target_account_key_share",
    select(users.c.user_id)
    .where(users.c.user_id == bindparam("target_user"))
    .with_for_update(read=True, key_share=True),
)
#: One or two catalogue role rows, `FOR UPDATE`, ordered by id (bound `role_a`, `role_b`).
ROLE_CATALOGUE_LOCK = PreLock(
    "role_catalogue_rows",
    select(roles.c.role_id)
    .where(or_(roles.c.role_id == bindparam("role_a"), roles.c.role_id == bindparam("role_b")))
    .order_by(roles.c.role_id)
    .with_for_update(),
)
#: The target's unrevoked identities of one issuer, `FOR UPDATE` (bound `identity_user`, `issuer`).
IDENTITY_LOCK = PreLock(
    "local_identity_rows",
    select(external_identities.c.external_identity_id)
    .where(external_identities.c.user_id == bindparam("identity_user"))
    .where(external_identities.c.issuer == bindparam(_LOCAL_ISSUER_PLACEHOLDER))
    .where(external_identities.c.revoked_at.is_(None))
    .order_by(external_identities.c.external_identity_id)
    .with_for_update(),
)

# -- steps ----------------------------------------------------------------------------------------------

_CAMPAIGN_FK_U = FkBinding(
    fk_of(cm, "campaign_id"), (KeyBind(cm.c.campaign_id, "campaign"),), CAMPAIGN_ROW_LOCK
)
INSERT_MEMBERSHIP = WriteStep(
    name="insert_membership",
    statement=insert(cm)
    .values(
        campaign_id=bindparam("campaign"),
        user_id=bindparam("user"),
        membership_status_id=bindparam("status"),
        joined_at=func.pg_catalog.now(),
    )
    .returning(cm.c.campaign_membership_id),
    cardinality=Exactly(1),
    fks=(
        _CAMPAIGN_FK_U,
        FkBinding(fk_of(cm, "user_id"), (KeyBind(cm.c.user_id, "user"),), TARGET_ACCOUNT_LOCK),
        FkBinding(
            fk_of(cm, "membership_status_id"),
            (KeyBind(cm.c.membership_status_id, "status"),),
            None,
        ),
    ),
    unique_waits=frozenset(
        {
            UniqueWait(
                "security.ux_campaign_memberships_open",
                "tests/database/test_r01_s5e2_membership_routes.py::"
                "test_a_competing_open_membership_for_the_same_account_is_a_unique_wait",
            )
        }
    ),
    triggers=frozenset(t for t in MEMBERSHIP_TRIGGERS if Event.INSERT in t.events),
)
INSERT_ROLE_FOR_NEW_MEMBER = WriteStep(
    name="insert_initial_role",
    statement=insert(mr)
    .values(
        campaign_membership_id=bindparam("membership"),
        role_id=bindparam("role"),
        granted_by_membership_id=bindparam("granted_by"),
    )
    .returning(mr.c.membership_role_id),
    cardinality=Exactly(1),
    fks=(
        FkBinding(
            fk_of(mr, "campaign_membership_id"),
            (KeyBind(mr.c.campaign_membership_id, "membership"),),
            None,
        ),
        FkBinding(fk_of(mr, "role_id"), (KeyBind(mr.c.role_id, "role"),), ROLE_CATALOGUE_LOCK),
        FkBinding(
            fk_of(mr, "granted_by_membership_id"),
            (KeyBind(mr.c.granted_by_membership_id, "granted_by"),),
            ACTOR_MEMBERSHIP_LOCK,
        ),
    ),
    unique_waits=frozenset(
        {
            UniqueWait(
                "security.ux_membership_roles_active",
                "tests/database/test_r01_s5e2_membership_routes.py::"
                "test_a_competing_active_assignment_of_the_same_role_is_a_unique_wait",
            )
        }
    ),
    triggers=frozenset(t for t in MEMBERSHIP_ROLE_TRIGGERS if Event.INSERT in t.events),
)
#: An UPDATE that sets `revoked_at` *leaves* the partial unique indexes (`WHERE revoked_at IS NULL`): it inserts no
#: index entry, so it can never wait for a competitor's key; a competitor's INSERT of the same key waits for
#: this transaction instead. Pinned by the named tests, which show the request finishing while the competitor
#: is still queued behind it.
_LEAVES_ACTIVE_ASSIGNMENT_INDEX = frozenset(
    {
        UniqueWait(
            "security.ux_membership_roles_active",
            "tests/database/test_r01_s5e2_membership_routes.py::"
            "test_an_update_leaving_the_active_assignment_index_never_waits_for_a_competing_insert",
        )
    }
)
_LEAVES_LIVE_DELEGATION_INDEX = frozenset(
    {
        UniqueWait(
            "security.ux_character_reveal_delegations_live",
            "tests/database/test_r01_s5e2_membership_routes.py::"
            "test_a_delegation_closure_leaving_the_live_index_never_waits_for_a_competing_insert",
        )
    }
)
INSERT_ROLE_ASSIGN = WriteStep(
    name="insert_role",
    statement=insert(mr)
    .values(
        campaign_membership_id=bindparam("membership"),
        role_id=bindparam("role"),
        granted_by_membership_id=bindparam("granted_by"),
        expires_at=bindparam("expires"),
    )
    .returning(mr.c.membership_role_id),
    cardinality=Exactly(1),
    fks=(
        FkBinding(
            fk_of(mr, "campaign_membership_id"),
            (KeyBind(mr.c.campaign_membership_id, "membership"),),
            MEMBERSHIPS_ACTOR_TARGET,
        ),
        FkBinding(fk_of(mr, "role_id"), (KeyBind(mr.c.role_id, "role"),), ROLE_CATALOGUE_LOCK),
        FkBinding(
            fk_of(mr, "granted_by_membership_id"),
            (KeyBind(mr.c.granted_by_membership_id, "granted_by"),),
            MEMBERSHIPS_ACTOR_TARGET,
        ),
    ),
    value_binds=frozenset({"expires"}),
    unique_waits=INSERT_ROLE_FOR_NEW_MEMBER.unique_waits,
    triggers=INSERT_ROLE_FOR_NEW_MEMBER.triggers,
)
INSERT_ROLE_CHANGE = WriteStep(
    name="insert_new_role",
    statement=insert(mr)
    .values(
        campaign_membership_id=bindparam("membership"),
        role_id=bindparam("role"),
        granted_by_membership_id=bindparam("granted_by"),
    )
    .returning(mr.c.membership_role_id),
    cardinality=Exactly(1),
    fks=(
        FkBinding(
            fk_of(mr, "campaign_membership_id"),
            (KeyBind(mr.c.campaign_membership_id, "membership"),),
            MEMBERSHIPS_ACTOR_TARGET,
        ),
        FkBinding(fk_of(mr, "role_id"), (KeyBind(mr.c.role_id, "role"),), ROLE_CATALOGUE_LOCK),
        FkBinding(
            fk_of(mr, "granted_by_membership_id"),
            (KeyBind(mr.c.granted_by_membership_id, "granted_by"),),
            MEMBERSHIPS_ACTOR_TARGET,
        ),
    ),
    unique_waits=INSERT_ROLE_FOR_NEW_MEMBER.unique_waits,
    triggers=INSERT_ROLE_FOR_NEW_MEMBER.triggers,
)
REVOKE_ROLE = WriteStep(
    name="revoke_role",
    statement=update(mr)
    .where(mr.c.membership_role_id == bindparam("target"))
    .values(revoked_at=func.pg_catalog.now())
    .returning(mr.c.membership_role_id),
    cardinality=EachLockedRow(complete=True),
    target=(KeyBind(mr.c.membership_role_id, "target"),),
    target_lock=REVOKE_OUTSTANDING_LOCK,
    unique_waits=_LEAVES_ACTIVE_ASSIGNMENT_INDEX,
    triggers=frozenset(t for t in MEMBERSHIP_ROLE_TRIGGERS if Event.UPDATE in t.events),
)
CHANGE_REVOKE_OLD = WriteStep(
    name="revoke_old_role",
    statement=update(mr)
    .where(mr.c.membership_role_id == bindparam("target"))
    .values(revoked_at=func.pg_catalog.now())
    .returning(mr.c.membership_role_id),
    cardinality=Exactly(1),
    target=(KeyBind(mr.c.membership_role_id, "target"),),
    target_lock=ROLE_ROWS_WITH_TARGET,
    unique_waits=_LEAVES_ACTIVE_ASSIGNMENT_INDEX,
    triggers=REVOKE_ROLE.triggers,
)
CLOSE_DELEGATION_ON_REVOKE = WriteStep(
    name="close_delegation",
    statement=update(dl)
    .where(dl.c.character_reveal_delegation_id == bindparam("delegation"))
    .values(revoked_at=func.pg_catalog.clock_timestamp(), end_reason=END_REASON_GM_ROLE_REVOKED)
    .returning(dl.c.character_reveal_delegation_id),
    cardinality=EachLockedRow(complete=True),
    target=(KeyBind(dl.c.character_reveal_delegation_id, "delegation"),),
    target_lock=DELEGATION_LOCK,
    unique_waits=_LEAVES_LIVE_DELEGATION_INDEX,
    triggers=DELEGATION_TRIGGERS,
)
CLOSE_DELEGATION_ON_CHANGE = WriteStep(
    name="close_delegation_on_change",
    statement=update(dl)
    .where(dl.c.character_reveal_delegation_id == bindparam("delegation"))
    .values(revoked_at=func.pg_catalog.clock_timestamp(), end_reason=END_REASON_GM_ROLE_CHANGED)
    .returning(dl.c.character_reveal_delegation_id),
    cardinality=EachLockedRow(complete=True),
    target=(KeyBind(dl.c.character_reveal_delegation_id, "delegation"),),
    target_lock=DELEGATION_LOCK,
    unique_waits=_LEAVES_LIVE_DELEGATION_INDEX,
    triggers=DELEGATION_TRIGGERS,
)


def _audit_values(table: str, command: str) -> dict[str, Any]:
    return {
        "change_action_id": bindparam("action"),
        "schema_name": "security",
        "table_name": table,
        "record_id": bindparam("record"),
        "world_id": bindparam("world"),
        "actor_user_id": bindparam("actor"),
        "correlation_id": bindparam("correlation"),
        "command_name": command,
    }


_AUDIT_BINDS = frozenset({"record", "world", "correlation"})
ADD_AUDIT_MEMBERSHIP = WriteStep(
    name="audit_membership_created",
    statement=insert(change_log)
    .values(**_audit_values("campaign_memberships", ADD_COMMAND_NAME))
    .returning(change_log.c.change_log_id),
    cardinality=Exactly(1),
    fks=(CHANGE_LOG_ACTION_FK, CHANGE_LOG_ACTOR_FK),
    value_binds=_AUDIT_BINDS,
)
ADD_AUDIT_ROLE = WriteStep(
    name="audit_role_created",
    statement=insert(change_log)
    .values(**_audit_values("membership_roles", ADD_COMMAND_NAME))
    .returning(change_log.c.change_log_id),
    cardinality=Exactly(1),
    fks=(CHANGE_LOG_ACTION_FK, CHANGE_LOG_ACTOR_FK),
    value_binds=_AUDIT_BINDS,
)
ASSIGN_AUDIT = WriteStep(
    name="audit_assigned",
    statement=insert(change_log)
    .values(**_audit_values("membership_roles", ASSIGN_COMMAND_NAME))
    .returning(change_log.c.change_log_id),
    cardinality=Exactly(1),
    fks=(CHANGE_LOG_ACTION_FK, CHANGE_LOG_ACTOR_FK),
    value_binds=_AUDIT_BINDS,
)
REVOKE_AUDIT = WriteStep(
    name="audit_revoked",
    statement=insert(change_log)
    .values(**_audit_values("membership_roles", REVOKE_COMMAND_NAME))
    .returning(change_log.c.change_log_id),
    cardinality=PerEvidence(REVOKE_OUTSTANDING_LOCK),
    fks=(CHANGE_LOG_ACTION_FK, CHANGE_LOG_ACTOR_FK),
    value_binds=_AUDIT_BINDS,
)
CHANGE_AUDIT = WriteStep(
    name="audit_changed",
    statement=insert(change_log)
    .values(
        **_audit_values("membership_roles", CHANGE_COMMAND_NAME),
        previous_status=bindparam("previous_status"),
        new_status=bindparam("new_status"),
        changed_fields=bindparam("changed"),
    )
    .returning(change_log.c.change_log_id),
    cardinality=Exactly(1),
    fks=(CHANGE_LOG_ACTION_FK, CHANGE_LOG_ACTOR_FK),
    value_binds=_AUDIT_BINDS | {"previous_status", "new_status", "changed"},
)
MEMBERSHIP_RECEIPT = RECEIPT_STEP

_UNLOCKED = CHANGE_LOG_UNLOCKED_FK_TARGETS | {membership_statuses}
_UNLOCKED_ADD = _UNLOCKED | {cm}  # the new membership of this very transaction

ADD_DECLARATIONS = ReservationDeclarations(
    reserved=PreWriteDeclaration(
        locks=(
            ACTOR_ROLES_LOCK,
            ACTOR_MEMBERSHIP_LOCK,
            ACTOR_ACCOUNT_LOCK,
            TARGET_ACCOUNT_LOCK,
            CAMPAIGN_ROW_LOCK,
            ROLE_CATALOGUE_LOCK,
            IDENTITY_LOCK,
            RECEIPT_LOCK,
        ),
        steps=(
            INSERT_MEMBERSHIP,
            INSERT_ROLE_FOR_NEW_MEMBER,
            ADD_AUDIT_MEMBERSHIP,
            ADD_AUDIT_ROLE,
            MEMBERSHIP_RECEIPT,
        ),
        unlocked_fk_targets=_UNLOCKED_ADD,
    ),
    unkeyed=PreWriteDeclaration(
        locks=(
            ACTOR_ROLES_LOCK,
            ACTOR_MEMBERSHIP_LOCK,
            ACTOR_ACCOUNT_LOCK,
            TARGET_ACCOUNT_LOCK,
            CAMPAIGN_ROW_LOCK,
            ROLE_CATALOGUE_LOCK,
            IDENTITY_LOCK,
        ),
        steps=(INSERT_MEMBERSHIP, INSERT_ROLE_FOR_NEW_MEMBER, ADD_AUDIT_MEMBERSHIP, ADD_AUDIT_ROLE),
        unlocked_fk_targets=_UNLOCKED_ADD,
    ),
)
_ASSIGN_LOCKS = (
    ACTOR_ROLES_LOCK,
    MEMBERSHIPS_ACTOR_TARGET,
    ACTOR_ACCOUNT_LOCK,
    TARGET_ACCOUNT_LOCK,
    CAMPAIGN_KEY_SHARE_LOCK,
    ROLE_CATALOGUE_LOCK,
)
ASSIGN_DECLARATIONS = ReservationDeclarations(
    reserved=PreWriteDeclaration(
        locks=(*_ASSIGN_LOCKS, RECEIPT_LOCK),
        steps=(INSERT_ROLE_ASSIGN, ASSIGN_AUDIT, MEMBERSHIP_RECEIPT),
        unlocked_fk_targets=CHANGE_LOG_UNLOCKED_FK_TARGETS,
    ),
    unkeyed=PreWriteDeclaration(
        locks=_ASSIGN_LOCKS,
        steps=(INSERT_ROLE_ASSIGN, ASSIGN_AUDIT),
        unlocked_fk_targets=CHANGE_LOG_UNLOCKED_FK_TARGETS,
    ),
)
_CHANGE_LOCKS = (
    ROLE_ROWS_WITH_TARGET,
    DELEGATION_LOCK,
    MEMBERSHIPS_ACTOR_TARGET,
    ACTOR_ACCOUNT_LOCK,
    CAMPAIGN_ROW_LOCK,
    ROLE_CATALOGUE_LOCK,
)
_CHANGE_STEPS = (CHANGE_REVOKE_OLD, CLOSE_DELEGATION_ON_CHANGE, INSERT_ROLE_CHANGE, CHANGE_AUDIT)
CHANGE_DECLARATIONS = ReservationDeclarations(
    reserved=PreWriteDeclaration(
        locks=(*_CHANGE_LOCKS, RECEIPT_LOCK),
        steps=(*_CHANGE_STEPS, MEMBERSHIP_RECEIPT),
        unlocked_fk_targets=CHANGE_LOG_UNLOCKED_FK_TARGETS,
    ),
    unkeyed=PreWriteDeclaration(
        locks=_CHANGE_LOCKS,
        steps=_CHANGE_STEPS,
        unlocked_fk_targets=CHANGE_LOG_UNLOCKED_FK_TARGETS,
    ),
)
_REVOKE_LOCKS = (
    ROLE_ROWS_WITH_TARGET,
    REVOKE_OUTSTANDING_LOCK,
    DELEGATION_LOCK,
    ACTOR_MEMBERSHIP_LOCK,
    ACTOR_ACCOUNT_LOCK,
    CAMPAIGN_ROW_LOCK,
)
_REVOKE_STEPS = (REVOKE_ROLE, CLOSE_DELEGATION_ON_REVOKE, REVOKE_AUDIT)
REVOKE_DECLARATIONS = ReservationDeclarations(
    reserved=PreWriteDeclaration(
        locks=(*_REVOKE_LOCKS, RECEIPT_LOCK),
        steps=(*_REVOKE_STEPS, MEMBERSHIP_RECEIPT),
        unlocked_fk_targets=CHANGE_LOG_UNLOCKED_FK_TARGETS,
    ),
    unkeyed=PreWriteDeclaration(
        locks=_REVOKE_LOCKS,
        steps=_REVOKE_STEPS,
        unlocked_fk_targets=CHANGE_LOG_UNLOCKED_FK_TARGETS,
    ),
)

# -- reads ---------------------------------------------------------------------------------------------

_MANAGER_SURVIVES = text("""
    SELECT (
        EXISTS (
            SELECT 1
            FROM security.campaign_memberships cm
            JOIN security.membership_statuses ms ON ms.membership_status_id = cm.membership_status_id
            JOIN security.membership_roles mr ON mr.campaign_membership_id = cm.campaign_membership_id
            JOIN security.roles r ON r.role_id = mr.role_id
            JOIN security.role_capabilities rc ON rc.role_id = r.role_id
            JOIN security.capabilities c ON c.capability_id = rc.capability_id
            WHERE cm.campaign_id = :campaign AND cm.ended_at IS NULL
              AND ms.code = 'active' AND ms.is_active
              AND mr.revoked_at IS NULL AND mr.expires_at IS NULL
              AND mr.membership_role_id <> :revoked
              AND r.is_active AND (r.campaign_id IS NULL OR r.campaign_id = :campaign)
              AND c.code = 'access.manage' AND c.is_active
        )
        OR (
            CAST(:new_role AS uuid) IS NOT NULL AND EXISTS (
                SELECT 1
                FROM security.roles r
                JOIN security.role_capabilities rc ON rc.role_id = r.role_id
                JOIN security.capabilities c ON c.capability_id = rc.capability_id
                WHERE r.role_id = CAST(:new_role AS uuid) AND r.is_active
                  AND (r.campaign_id IS NULL OR r.campaign_id = :campaign)
                  AND c.code = 'access.manage' AND c.is_active
            )
        )
    )
""")


def _require_manager_survives(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    revoked_role_id: uuid.UUID,
    new_role_id: uuid.UUID | None,
    detail: str,
) -> None:
    """The retention pre-check, before `finalize` and under the held campaign lock: an active campaign
    must keep a non-expiring `access.manage` holder once `revoked_role_id` is closed (and `new_role_id`,
    a non-expiring assignment for the same active membership, is added). A plain `ValueError` (400) as
    before; the deferred trigger stays the backstop."""
    status = connection.execute(
        text(
            "SELECT ls.code FROM campaign.campaigns c "
            "JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = c.lifecycle_status_id "
            "WHERE c.campaign_id = :campaign"
        ),
        {"campaign": campaign_id},
    ).scalar()
    if status != "active":
        return
    survives = connection.execute(
        _MANAGER_SURVIVES,
        {"campaign": campaign_id, "revoked": revoked_role_id, "new_role": new_role_id},
    ).scalar()
    if not survives:
        raise ValueError(detail)


def _require_owner_gate(
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    actor_membership_id: uuid.UUID,
    role_id: uuid.UUID,
) -> None:
    """The D3 gate, as a plain read (the actor's owner assignment is among the actor's locked role rows)."""
    role = connection.execute(
        text("SELECT campaign_id, code FROM security.roles WHERE role_id = :role"),
        {"role": role_id},
    ).one_or_none()
    if role is not None and is_builtin_campaign_owner_role(
        role_campaign_id=role.campaign_id, role_code=role.code
    ):
        live = find_live_builtin_owner_assignment(
            connection, campaign_id=campaign_id, campaign_membership_id=actor_membership_id
        )
        if live is None:
            raise CampaignOwnerRequiredError(
                f"membership {actor_membership_id} holds no live campaign_owner assignment in "
                f"campaign {campaign_id}"
            )


def _recheck_owner(
    connection: Connection, *, campaign_id: uuid.UUID, actor_membership_id: uuid.UUID
) -> None:
    """DEF-013: judge the caller again at a fresh instant, after the last lock wait and before `finalize`."""
    clock = connection.execute(text("SELECT clock_timestamp()")).scalar()
    assert isinstance(clock, datetime)
    if (
        find_live_builtin_owner_assignment(
            connection,
            campaign_id=campaign_id,
            campaign_membership_id=actor_membership_id,
            as_of=clock,
        )
        is None
    ):
        raise CampaignOwnerRequiredError(
            f"membership {actor_membership_id} no longer holds a live campaign_owner assignment "
            f"in campaign {campaign_id}"
        )


def _usable_role(
    connection: Connection, *, role_id: uuid.UUID, campaign_id: uuid.UUID
) -> tuple[Any, ...]:
    row = connection.execute(
        text("SELECT campaign_id, code, is_active FROM security.roles WHERE role_id = :role"),
        {"role": role_id},
    ).one_or_none()
    if (
        row is None
        or (row.campaign_id is not None and row.campaign_id != campaign_id)
        or not row.is_active
    ):
        raise RoleNotUsableByCampaignError(
            f"role {role_id} is not usable by campaign {campaign_id} "
            f"(actual campaign: {row.campaign_id if row is not None else None})"
        )
    return (row.campaign_id, row.code)


@dataclass(frozen=True)
class Prepared:
    """What the lock and read phase established, all before `finalize`."""

    world_id: uuid.UUID
    action_id: uuid.UUID
    will_write: bool = True
    target_membership_id: uuid.UUID | None = None
    role_id: uuid.UUID | None = None
    status_id: uuid.UUID | None = None
    delegations: tuple[uuid.UUID, ...] = ()
    previous_role_code: str | None = None
    new_role_code: str | None = None
    membership_id: uuid.UUID | None = None


def _lock_actor_roles_and_membership(
    connection: Connection,
    plan: AuthorizationPlan,
    *,
    campaign_id: uuid.UUID,
    actor_membership_id: uuid.UUID,
) -> None:
    plan.lock(connection, ACTOR_ROLES_LOCK, {"membership": actor_membership_id})
    plan.lock(
        connection,
        ACTOR_MEMBERSHIP_LOCK,
        {"membership": actor_membership_id, "campaign": campaign_id},
    )


def _scope_world(connection: Connection, campaign_id: uuid.UUID) -> uuid.UUID:
    world = connection.execute(
        text(
            "SELECT t.world_id FROM campaign.campaigns c "
            "JOIN campaign.timelines t ON t.timeline_id = c.timeline_id WHERE c.campaign_id = :c"
        ),
        {"c": campaign_id},
    ).scalar()
    assert isinstance(world, uuid.UUID)
    return world


def prepare_add_member(
    connection: Connection,
    plan: AuthorizationPlan,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    actor_membership_id: uuid.UUID,
    user_id: uuid.UUID,
    role_id: uuid.UUID,
    local_issuer: str,
    reservation_id: uuid.UUID | None,
) -> Prepared:
    _lock_actor_roles_and_membership(
        connection, plan, campaign_id=campaign_id, actor_membership_id=actor_membership_id
    )
    plan.lock(connection, ACTOR_ACCOUNT_LOCK, {"actor": actor_user_id})
    plan.lock(connection, TARGET_ACCOUNT_LOCK, {"target_user": user_id})
    plan.lock(connection, CAMPAIGN_ROW_LOCK, {"campaign": campaign_id})
    plan.lock(connection, ROLE_CATALOGUE_LOCK, {"role_a": role_id, "role_b": role_id})
    identities = plan.lock(
        connection,
        IDENTITY_LOCK,
        {"identity_user": user_id, _LOCAL_ISSUER_PLACEHOLDER: local_issuer},
    )
    if reservation_id is not None:
        plan.lock(connection, RECEIPT_LOCK, {"receipt": reservation_id})
    # reads and refusals, in the order the command raised them
    _require_owner_gate(
        connection,
        campaign_id=campaign_id,
        actor_membership_id=actor_membership_id,
        role_id=role_id,
    )
    status = connection.execute(
        text(
            "SELECT ls.code FROM campaign.campaigns c "
            "JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = c.lifecycle_status_id "
            "WHERE c.campaign_id = :c"
        ),
        {"c": campaign_id},
    ).scalar()
    if status != "active":
        raise CampaignNotActiveError(f"campaign {campaign_id} is not currently active")
    account = connection.execute(
        text(
            "SELECT ls.code FROM security.users u "
            "JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = u.lifecycle_status_id "
            "WHERE u.user_id = :u"
        ),
        {"u": user_id},
    ).scalar()
    if account != "active":
        raise AccountNotEligibleError(
            f"user {user_id} does not exist or is not currently an active platform account"
        )
    if not identities:
        raise AccountNotEligibleError(
            f"user {user_id} has no currently unrevoked local-login identity"
        )
    role_campaign, role_code = _usable_role(connection, role_id=role_id, campaign_id=campaign_id)
    if is_builtin_campaign_owner_role(role_campaign_id=role_campaign, role_code=role_code):
        _recheck_owner(connection, campaign_id=campaign_id, actor_membership_id=actor_membership_id)
    return Prepared(
        world_id=_scope_world(connection, campaign_id),
        action_id=lookup_id(connection, "audit", "change_actions", "change_action_id", "created"),
        status_id=lookup_id(
            connection, "security", "membership_statuses", "membership_status_id", "active"
        ),
        role_id=role_id,
    )


def prepare_assign_role(
    connection: Connection,
    plan: AuthorizationPlan,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    actor_membership_id: uuid.UUID,
    target_membership_id: uuid.UUID,
    role_id: uuid.UUID,
    reservation_id: uuid.UUID | None,
) -> Prepared:
    plan.lock(connection, ACTOR_ROLES_LOCK, {"membership": actor_membership_id})
    plan.lock(
        connection,
        MEMBERSHIPS_ACTOR_TARGET,
        {"campaign": campaign_id, "actor": actor_membership_id, "target": target_membership_id},
    )
    plan.lock(connection, ACTOR_ACCOUNT_LOCK, {"actor": actor_user_id})
    membership = (
        connection.execute(
            text("""
                SELECT cm.campaign_id, cm.ended_at, cm.user_id,
                       ms.code AS status_code, ms.is_active AS status_is_active
                FROM security.campaign_memberships cm
                JOIN security.membership_statuses ms
                    ON ms.membership_status_id = cm.membership_status_id
                WHERE cm.campaign_membership_id = :m
            """),
            {"m": target_membership_id},
        )
        .mappings()
        .one_or_none()
    )
    if membership is not None and membership["campaign_id"] == campaign_id:
        plan.lock(connection, TARGET_ACCOUNT_LOCK, {"target_user": membership["user_id"]})
    plan.lock(connection, CAMPAIGN_KEY_SHARE_LOCK, {"campaign": campaign_id})
    plan.lock(connection, ROLE_CATALOGUE_LOCK, {"role_a": role_id, "role_b": role_id})
    if reservation_id is not None:
        plan.lock(connection, RECEIPT_LOCK, {"receipt": reservation_id})
    _require_owner_gate(
        connection,
        campaign_id=campaign_id,
        actor_membership_id=actor_membership_id,
        role_id=role_id,
    )
    if membership is None or membership["campaign_id"] != campaign_id:
        raise MembershipNotInCampaignError(
            f"membership {target_membership_id} does not belong to campaign {campaign_id} "
            f"(actual campaign: {membership['campaign_id'] if membership is not None else None})"
        )
    if not (
        membership["ended_at"] is None
        and membership["status_code"] == "active"
        and membership["status_is_active"]
    ):
        raise MembershipNotActiveError(
            f"membership {target_membership_id} is not currently an eligible, open "
            "membership to assign a role to"
        )
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
            f"membership {target_membership_id}'s user {membership['user_id']} is not "
            "currently an active platform account"
        )
    role_campaign, role_code = _usable_role(connection, role_id=role_id, campaign_id=campaign_id)
    if is_builtin_campaign_owner_role(role_campaign_id=role_campaign, role_code=role_code):
        _recheck_owner(connection, campaign_id=campaign_id, actor_membership_id=actor_membership_id)
    return Prepared(
        world_id=_scope_world(connection, campaign_id),
        action_id=lookup_id(connection, "audit", "change_actions", "change_action_id", "created"),
        target_membership_id=target_membership_id,
        role_id=role_id,
    )


def _target_role_row(
    connection: Connection, *, membership_role_id: uuid.UUID, campaign_id: uuid.UUID
) -> Any:
    row = (
        connection.execute(
            text("""
                SELECT cm.campaign_id, cm.campaign_membership_id, cm.ended_at,
                       ms.code AS status_code, ms.is_active AS status_is_active,
                       mr.role_id, mr.revoked_at,
                       (mr.expires_at IS NOT NULL AND mr.expires_at <= now()) AS expired,
                       r.code AS role_code, r.is_active AS role_is_active
                FROM security.membership_roles mr
                JOIN security.campaign_memberships cm
                    ON cm.campaign_membership_id = mr.campaign_membership_id
                JOIN security.membership_statuses ms
                    ON ms.membership_status_id = cm.membership_status_id
                JOIN security.roles r ON r.role_id = mr.role_id
                WHERE mr.membership_role_id = :r
            """),
            {"r": membership_role_id},
        )
        .mappings()
        .one_or_none()
    )
    if row is None or row["campaign_id"] != campaign_id:
        raise MembershipNotInCampaignError(
            f"membership role {membership_role_id} does not belong to campaign {campaign_id} "
            f"(actual campaign: {row['campaign_id'] if row is not None else None})"
        )
    return row


def prepare_revoke_role(
    connection: Connection,
    plan: AuthorizationPlan,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    actor_membership_id: uuid.UUID,
    membership_role_id: uuid.UUID,
    reservation_id: uuid.UUID | None,
) -> Prepared:
    target = plan.lock(
        connection,
        ROLE_ROWS_WITH_TARGET,
        {"membership": actor_membership_id, "target": membership_role_id},
    )
    outstanding = (
        plan.lock(connection, REVOKE_OUTSTANDING_LOCK, {"target": membership_role_id})
        if (membership_role_id,) in target
        else ()
    )
    delegations = (
        plan.lock(connection, DELEGATION_LOCK, {"role": membership_role_id}) if outstanding else ()
    )
    plan.lock(
        connection,
        ACTOR_MEMBERSHIP_LOCK,
        {"membership": actor_membership_id, "campaign": campaign_id},
    )
    plan.lock(connection, ACTOR_ACCOUNT_LOCK, {"actor": actor_user_id})
    plan.lock(connection, CAMPAIGN_ROW_LOCK, {"campaign": campaign_id})
    if reservation_id is not None:
        plan.lock(connection, RECEIPT_LOCK, {"receipt": reservation_id})
    row = _target_role_row(
        connection, membership_role_id=membership_role_id, campaign_id=campaign_id
    )
    will_revoke = row["revoked_at"] is None
    if will_revoke != bool(outstanding):  # the lock's own evidence and the row read cannot differ
        raise RuntimeError("the membership role changed under its own lock")
    if will_revoke:
        _require_manager_survives(
            connection,
            campaign_id=campaign_id,
            revoked_role_id=membership_role_id,
            new_role_id=None,
            detail=(
                f"revoking membership role {membership_role_id} would leave active campaign "
                f"{campaign_id} with no membership holding access.manage"
            ),
        )
    return Prepared(
        world_id=_scope_world(connection, campaign_id),
        action_id=lookup_id(connection, "audit", "change_actions", "change_action_id", "updated"),
        will_write=will_revoke,
        delegations=tuple(key[0] for key in delegations),
    )


def prepare_change_role(
    connection: Connection,
    plan: AuthorizationPlan,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    actor_membership_id: uuid.UUID,
    membership_role_id: uuid.UUID,
    new_role_id: uuid.UUID,
    reservation_id: uuid.UUID | None,
) -> Prepared:
    target = plan.lock(
        connection,
        ROLE_ROWS_WITH_TARGET,
        {"membership": actor_membership_id, "target": membership_role_id},
    )
    row = None
    if (membership_role_id,) in target:
        row = _target_role_row(
            connection, membership_role_id=membership_role_id, campaign_id=campaign_id
        )
    delegations = (
        plan.lock(connection, DELEGATION_LOCK, {"role": membership_role_id})
        if row is not None
        else ()
    )
    plan.lock(
        connection,
        MEMBERSHIPS_ACTOR_TARGET,
        {
            "campaign": campaign_id,
            "actor": actor_membership_id,
            "target": row["campaign_membership_id"] if row is not None else actor_membership_id,
        },
    )
    plan.lock(connection, ACTOR_ACCOUNT_LOCK, {"actor": actor_user_id})
    plan.lock(connection, CAMPAIGN_ROW_LOCK, {"campaign": campaign_id})
    plan.lock(
        connection,
        ROLE_CATALOGUE_LOCK,
        {
            "role_a": row["role_id"] if row is not None else new_role_id,
            "role_b": new_role_id,
        },
    )
    if reservation_id is not None:
        plan.lock(connection, RECEIPT_LOCK, {"receipt": reservation_id})
    _require_owner_gate(
        connection,
        campaign_id=campaign_id,
        actor_membership_id=actor_membership_id,
        role_id=new_role_id,
    )
    if row is None:
        raise MembershipNotInCampaignError(
            f"membership role {membership_role_id} does not belong to campaign {campaign_id} "
            "(actual campaign: None)"
        )
    if not (
        row["revoked_at"] is None
        and not row["expired"]
        and row["role_is_active"]
        and row["ended_at"] is None
        and row["status_code"] == "active"
        and row["status_is_active"]
    ):
        raise MembershipRoleNotActiveError(
            f"membership role {membership_role_id} is not currently an eligible, active "
            "assignment to change"
        )
    new_campaign, new_code = _usable_role(connection, role_id=new_role_id, campaign_id=campaign_id)
    if new_role_id == row["role_id"]:
        raise ChangeMembershipRoleNoOpError(
            f"role {new_role_id} is already the current role for membership role "
            f"{membership_role_id}"
        )
    if is_builtin_campaign_owner_role(role_campaign_id=new_campaign, role_code=new_code):
        _recheck_owner(connection, campaign_id=campaign_id, actor_membership_id=actor_membership_id)
    _require_manager_survives(
        connection,
        campaign_id=campaign_id,
        revoked_role_id=membership_role_id,
        new_role_id=new_role_id,
        detail=(
            f"changing membership role {membership_role_id} to role {new_role_id} would leave "
            f"active campaign {campaign_id} with no membership holding access.manage"
        ),
    )
    return Prepared(
        world_id=_scope_world(connection, campaign_id),
        action_id=lookup_id(connection, "audit", "change_actions", "change_action_id", "updated"),
        target_membership_id=row["campaign_membership_id"],
        role_id=new_role_id,
        delegations=tuple(key[0] for key in delegations),
        previous_role_code=row["role_code"],
        new_role_code=new_code,
    )


# -- the write phases -------------------------------------------------------------------------------------


def _audit(
    prepared: Prepared,
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


def write_add_member(
    connection: Connection,
    plan: AuthorizationPlan,
    prepared: Prepared,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    actor_membership_id: uuid.UUID,
    user_id: uuid.UUID,
    correlation_id: str | None,
) -> tuple[uuid.UUID, uuid.UUID]:
    """The declared inserts and audit rows, after `finalize`; returns the new membership and role ids."""
    created = plan.execute(
        connection,
        INSERT_MEMBERSHIP,
        {"campaign": campaign_id, "user": user_id, "status": prepared.status_id},
    )
    membership_id = created.keys[0][0]
    assigned = plan.execute(
        connection,
        INSERT_ROLE_FOR_NEW_MEMBER,
        {"membership": membership_id, "role": prepared.role_id, "granted_by": actor_membership_id},
    )
    role_assignment_id = assigned.keys[0][0]
    plan.execute(
        connection,
        ADD_AUDIT_MEMBERSHIP,
        _audit(
            prepared,
            record=membership_id,
            actor_user_id=actor_user_id,
            correlation_id=correlation_id,
        ),
    )
    plan.execute(
        connection,
        ADD_AUDIT_ROLE,
        _audit(
            prepared,
            record=role_assignment_id,
            actor_user_id=actor_user_id,
            correlation_id=correlation_id,
        ),
    )
    return membership_id, role_assignment_id


def write_assign_role(
    connection: Connection,
    plan: AuthorizationPlan,
    prepared: Prepared,
    *,
    actor_user_id: uuid.UUID,
    actor_membership_id: uuid.UUID,
    expires_at: datetime | None,
    correlation_id: str | None,
) -> uuid.UUID:
    outcome = plan.execute(
        connection,
        INSERT_ROLE_ASSIGN,
        {
            "membership": prepared.target_membership_id,
            "role": prepared.role_id,
            "granted_by": actor_membership_id,
            "expires": expires_at,
        },
    )
    new_id = outcome.keys[0][0]
    assert isinstance(new_id, uuid.UUID)
    plan.execute(
        connection,
        ASSIGN_AUDIT,
        _audit(prepared, record=new_id, actor_user_id=actor_user_id, correlation_id=correlation_id),
    )
    return new_id


def write_revoke_role(
    connection: Connection,
    plan: AuthorizationPlan,
    prepared: Prepared,
    *,
    membership_role_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    correlation_id: str | None,
) -> None:
    """The declared revocation, delegation closures and audit row (attempted only by a genuine revoke)."""
    if not prepared.will_write:
        return
    plan.execute(connection, REVOKE_ROLE, {"target": membership_role_id})
    for delegation in prepared.delegations:
        plan.execute(connection, CLOSE_DELEGATION_ON_REVOKE, {"delegation": delegation})
    plan.execute(
        connection,
        REVOKE_AUDIT,
        _audit(
            prepared,
            record=membership_role_id,
            actor_user_id=actor_user_id,
            correlation_id=correlation_id,
        ),
    )


def write_change_role(
    connection: Connection,
    plan: AuthorizationPlan,
    prepared: Prepared,
    *,
    membership_role_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    actor_membership_id: uuid.UUID,
    correlation_id: str | None,
) -> uuid.UUID:
    plan.execute(connection, CHANGE_REVOKE_OLD, {"target": membership_role_id})
    for delegation in prepared.delegations:
        plan.execute(connection, CLOSE_DELEGATION_ON_CHANGE, {"delegation": delegation})
    outcome = plan.execute(
        connection,
        INSERT_ROLE_CHANGE,
        {
            "membership": prepared.target_membership_id,
            "role": prepared.role_id,
            "granted_by": actor_membership_id,
        },
    )
    new_id = outcome.keys[0][0]
    assert isinstance(new_id, uuid.UUID)
    plan.execute(
        connection,
        CHANGE_AUDIT,
        {
            **_audit(
                prepared, record=new_id, actor_user_id=actor_user_id, correlation_id=correlation_id
            ),
            "previous_status": prepared.previous_role_code,
            "new_status": prepared.new_role_code,
            "changed": {"previous_membership_role_id": str(membership_role_id)},
        },
    )
    return new_id


# =====================================================================================================
# Ownership transfer (R01 S5-E2 amendment; plan 6.27.4-6.27.5; design review 2026-11-14, section 6)
# =====================================================================================================
#
# An **unkeyed** pre-write plan (`R01_UNKEYED_PRE_WRITE_ROUTES`): transfer stays non-idempotent and an
# `Idempotency-Key` header is ignored. `memberships.transfer_campaign_ownership` stays as the direct command.
#
# Lock sequence (every lock before `plan.finalize`; modes as T5 of the design):
#
#   1. unlocked reads of lock-stable facts: the owner template id, the recipient membership's campaign;
#   2. role class: the actor's unrevoked role rows NO KEY UPDATE (one ordered statement), the recipient's
#      EXPIRED owner row NO KEY UPDATE, then (strictly after) the recipient's LIVE owner row KEY SHARE, then,
#      only when relinquishing, the actor's owner row NO KEY UPDATE (already held, no wait);
#   3. delegations bound to each of those role keys, FOR UPDATE (always empty: trigger 141 binds them to `gm`);
#   4. the actor's open membership and the recipient's, FOR UPDATE, one ordered statement. **Absence and
#      positive evidence become stable here**, not at the role-class SELECTs;
#   5. the actor's account FOR SHARE, the recipient's account FOR KEY SHARE (S5-A);
#   6. the campaign FOR UPDATE; 7. the owner template FOR UPDATE.
#
# Why the modes: NO KEY UPDATE does not conflict with the other side's KEY SHARE, so two owners transferring to
# each other do not wait in the role class and serialize at the memberships; FOR UPDATE would deadlock them. A
# separate FOR SHARE on the actor's own row followed by NO KEY UPDATE would be an upgrade that deadlocks two
# identical requests. KEY SHARE on the recipient's live row blocks every FOR UPDATE revoker (S5-E2 revoke and
# change, the legacy revoke, end) and is compatible with the legacy reveal-delegation grant's FOR SHARE.
#
# Declared writes: S1 close the recipient's expired owner row(s) (`EachLockedRow(complete)` over the expired
# lock); S4 close delegations of S1/S3's roles (`EachLockedRow(complete)`; always empty); S2 insert the owner
# assignment (`PerAbsence(live lock)`: owed exactly when no live owner row exists); S3 relinquish the actor's
# own owner row (`EachLockedRow(complete)` over the actor-owner lock, which only a relinquishing request runs);
# S5 one audit row (`AnyConfirmed((S2, S3))`). S1 must precede S2 (the partial unique index), so it is
# declared first; S4 is declared before S2 as well, so that every closure precedes the INSERT.

OWNER_TRANSFER_COMMAND_NAME = "transfer_campaign_ownership"

#: The actor's unrevoked role rows, one ordered statement, FOR NO KEY UPDATE (bound `membership`).
TRANSFER_ACTOR_ROLE_ROWS = PreLock(
    "transfer_actor_role_rows",
    select(mr.c.membership_role_id)
    .where(mr.c.campaign_membership_id == bindparam("membership"))
    .where(mr.c.revoked_at.is_(None))
    .order_by(mr.c.membership_role_id)
    .with_for_update(key_share=True),
)
#: The recipient's unrevoked owner rows already expired at this statement's clock, FOR NO KEY UPDATE (bound
#: `membership`, `role`). Run **before** `RECIPIENT_LIVE_OWNER`: a row expiring between the two is in neither
#: set, and the later drift check refuses it (fail closed).
RECIPIENT_EXPIRED_OWNER = PreLock(
    "recipient_expired_owner",
    select(mr.c.membership_role_id)
    .where(mr.c.campaign_membership_id == bindparam("membership"))
    .where(mr.c.role_id == bindparam("role"))
    .where(mr.c.revoked_at.is_(None))
    .where(mr.c.expires_at.is_not(None))
    .where(mr.c.expires_at <= func.pg_catalog.clock_timestamp())
    .order_by(mr.c.membership_role_id)
    .with_for_update(key_share=True),
)
#: The recipient's unrevoked, not-yet-expired owner row, FOR KEY SHARE (bound `membership`, `role`). Its
#: evidence is a *positive* observation; the protection of absence comes from the membership lock.
RECIPIENT_LIVE_OWNER = PreLock(
    "recipient_live_owner",
    select(mr.c.membership_role_id)
    .where(mr.c.campaign_membership_id == bindparam("membership"))
    .where(mr.c.role_id == bindparam("role"))
    .where(mr.c.revoked_at.is_(None))
    .where(or_(mr.c.expires_at.is_(None), mr.c.expires_at > func.pg_catalog.clock_timestamp()))
    .order_by(mr.c.membership_role_id)
    .with_for_update(read=True, key_share=True),
)
#: The actor's unrevoked owner row, FOR NO KEY UPDATE; run only by a relinquishing request (already held by
#: `TRANSFER_ACTOR_ROLE_ROWS`, so no wait). Bound `membership`, `role`.
ACTOR_OWNER_ROW = PreLock(
    "transfer_actor_owner_row",
    select(mr.c.membership_role_id)
    .where(mr.c.campaign_membership_id == bindparam("membership"))
    .where(mr.c.role_id == bindparam("role"))
    .where(mr.c.revoked_at.is_(None))
    .order_by(mr.c.membership_role_id)
    .with_for_update(key_share=True),
)

_TRANSFER_UNIQUE_WAITS = frozenset(
    {
        UniqueWait(
            "security.ux_membership_roles_active",
            "tests/database/test_r01_s5e2_transfer_route.py::"
            "test_a_competing_owner_assignment_of_the_recipient_is_a_unique_wait_or_a_classified_409",
        )
    }
)
_TRANSFER_LEAVES_ACTIVE_ASSIGNMENT_INDEX = frozenset(
    {
        UniqueWait(
            "security.ux_membership_roles_active",
            "tests/database/test_r01_s5e2_transfer_route.py::"
            "test_an_update_leaving_the_active_assignment_index_never_waits_for_a_competing_insert",
        )
    }
)
CLOSE_EXPIRED_OWNER = WriteStep(
    name="close_expired_owner",
    statement=update(mr)
    .where(mr.c.membership_role_id == bindparam("target"))
    .values(revoked_at=func.pg_catalog.now())
    .returning(mr.c.membership_role_id),
    cardinality=EachLockedRow(complete=True),
    target=(KeyBind(mr.c.membership_role_id, "target"),),
    target_lock=RECIPIENT_EXPIRED_OWNER,
    unique_waits=_TRANSFER_LEAVES_ACTIVE_ASSIGNMENT_INDEX,
    triggers=REVOKE_ROLE.triggers,
)
INSERT_OWNER_ROLE = WriteStep(
    name="insert_owner_role",
    statement=insert(mr)
    .values(
        campaign_membership_id=bindparam("membership"),
        role_id=bindparam("role"),
        granted_by_membership_id=bindparam("granted_by"),
    )
    .returning(mr.c.membership_role_id),
    cardinality=PerAbsence(RECIPIENT_LIVE_OWNER),
    fks=(
        FkBinding(
            fk_of(mr, "campaign_membership_id"),
            (KeyBind(mr.c.campaign_membership_id, "membership"),),
            MEMBERSHIPS_ACTOR_TARGET,
        ),
        FkBinding(fk_of(mr, "role_id"), (KeyBind(mr.c.role_id, "role"),), ROLE_CATALOGUE_LOCK),
        FkBinding(
            fk_of(mr, "granted_by_membership_id"),
            (KeyBind(mr.c.granted_by_membership_id, "granted_by"),),
            MEMBERSHIPS_ACTOR_TARGET,
        ),
    ),
    unique_waits=_TRANSFER_UNIQUE_WAITS,
    triggers=INSERT_ROLE_FOR_NEW_MEMBER.triggers,
)
RELINQUISH_OWNER = WriteStep(
    name="relinquish_owner",
    statement=update(mr)
    .where(mr.c.membership_role_id == bindparam("target"))
    .values(revoked_at=func.pg_catalog.now())
    .returning(mr.c.membership_role_id),
    cardinality=EachLockedRow(complete=True),
    target=(KeyBind(mr.c.membership_role_id, "target"),),
    target_lock=ACTOR_OWNER_ROW,
    unique_waits=_TRANSFER_LEAVES_ACTIVE_ASSIGNMENT_INDEX,
    triggers=REVOKE_ROLE.triggers,
)
TRANSFER_AUDIT = WriteStep(
    name="audit_transferred",
    statement=insert(change_log)
    .values(
        **_audit_values("membership_roles", OWNER_TRANSFER_COMMAND_NAME),
        changed_fields=bindparam("changed"),
    )
    .returning(change_log.c.change_log_id),
    cardinality=AnyConfirmed((INSERT_OWNER_ROLE, RELINQUISH_OWNER)),
    fks=(CHANGE_LOG_ACTION_FK, CHANGE_LOG_ACTOR_FK),
    value_binds=_AUDIT_BINDS | {"changed"},
)
TRANSFER_LOCKS = (
    TRANSFER_ACTOR_ROLE_ROWS,
    RECIPIENT_EXPIRED_OWNER,
    RECIPIENT_LIVE_OWNER,
    ACTOR_OWNER_ROW,
    DELEGATION_LOCK,
    MEMBERSHIPS_ACTOR_TARGET,
    ACTOR_ACCOUNT_LOCK,
    TARGET_ACCOUNT_LOCK,
    CAMPAIGN_ROW_LOCK,
    ROLE_CATALOGUE_LOCK,
)
TRANSFER_STEPS = (
    CLOSE_EXPIRED_OWNER,
    CLOSE_DELEGATION_ON_REVOKE,
    INSERT_OWNER_ROLE,
    RELINQUISH_OWNER,
    TRANSFER_AUDIT,
)
TRANSFER_DECLARATION = PreWriteDeclaration(
    locks=TRANSFER_LOCKS,
    steps=TRANSFER_STEPS,
    unlocked_fk_targets=CHANGE_LOG_UNLOCKED_FK_TARGETS,
)


@dataclass(frozen=True)
class TransferPrepared:
    """What the transfer's lock and read phase established, all before `finalize`."""

    world_id: uuid.UUID
    action_id: uuid.UUID
    owner_role_id: uuid.UUID
    relinquishing: bool
    expired: tuple[uuid.UUID, ...]
    own: tuple[uuid.UUID, ...]
    delegations: tuple[uuid.UUID, ...]
    inserting: bool
    recipient_membership_id: uuid.UUID


@dataclass(frozen=True)
class TransferWritten:
    target_campaign_membership_id: uuid.UUID
    assigned_membership_role_id: uuid.UUID | None
    revoked_membership_role_ids: tuple[uuid.UUID, ...]
    replaced_expired_membership_role_ids: tuple[uuid.UUID, ...]


def _database_clock(connection: Connection) -> datetime:
    value = connection.execute(text("SELECT clock_timestamp()")).scalar()
    assert isinstance(value, datetime)
    return value


def _unrevoked_owner_rows(
    connection: Connection,
    *,
    membership_id: uuid.UUID,
    owner_role_id: uuid.UUID,
    checked_at: datetime,
) -> dict[uuid.UUID, bool]:
    """The membership's unrevoked owner rows, each with whether it is expired at `checked_at`."""
    rows = connection.execute(
        text("""
            SELECT membership_role_id,
                   (expires_at IS NOT NULL AND expires_at <= :checked_at) AS is_expired
            FROM security.membership_roles
            WHERE campaign_membership_id = :m AND role_id = :r AND revoked_at IS NULL
        """),
        {"m": membership_id, "r": owner_role_id, "checked_at": checked_at},
    ).all()
    return {row.membership_role_id: bool(row.is_expired) for row in rows}


def _recipient_changed(recipient: uuid.UUID, detail: str) -> OwnershipTransferRecipientChangedError:
    return OwnershipTransferRecipientChangedError(f"membership {recipient}: {detail}")


def prepare_transfer(  # noqa: C901, PLR0912, PLR0915 - one linear lock and refusal sequence
    connection: Connection,
    plan: AuthorizationPlan,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    actor_membership_id: uuid.UUID,
    target_membership_id: uuid.UUID,
    relinquish_own_ownership: bool,
) -> TransferPrepared:
    """Every lock, read and refusal of the transfer, in the design's order (section 6), before `finalize`."""
    relinquishing = relinquish_own_ownership and actor_membership_id != target_membership_id
    # 1. unlocked reads of lock-stable facts
    owner_role_id = connection.execute(
        text(
            "SELECT role_id FROM security.roles WHERE code = 'campaign_owner' AND campaign_id IS NULL"
        )
    ).scalar()
    assert isinstance(owner_role_id, uuid.UUID)
    recipient_campaign = connection.execute(
        text(
            "SELECT campaign_id FROM security.campaign_memberships WHERE campaign_membership_id = :m"
        ),
        {"m": target_membership_id},
    ).scalar()
    in_campaign = recipient_campaign == campaign_id
    # 2. role class
    plan.lock(connection, TRANSFER_ACTOR_ROLE_ROWS, {"membership": actor_membership_id})
    expired: tuple[tuple[Any, ...], ...] = ()
    live: tuple[tuple[Any, ...], ...] = ()
    if in_campaign:
        recipient_binds = {"membership": target_membership_id, "role": owner_role_id}
        expired = plan.lock(connection, RECIPIENT_EXPIRED_OWNER, recipient_binds)
        live = plan.lock(connection, RECIPIENT_LIVE_OWNER, recipient_binds)
    own: tuple[tuple[Any, ...], ...] = ()
    if relinquishing:
        own = plan.lock(
            connection,
            ACTOR_OWNER_ROW,
            {"membership": actor_membership_id, "role": owner_role_id},
        )
    # 3. delegations bound to the role rows this request will close
    delegations: list[uuid.UUID] = []
    for key in (*expired, *own):
        for found in plan.lock(connection, DELEGATION_LOCK, {"role": key[0]}):
            delegations.append(found[0])
    # 4. memberships: absence and positive evidence are stable from here
    plan.lock(
        connection,
        MEMBERSHIPS_ACTOR_TARGET,
        {"campaign": campaign_id, "actor": actor_membership_id, "target": target_membership_id},
    )
    # 5. accounts
    plan.lock(connection, ACTOR_ACCOUNT_LOCK, {"actor": actor_user_id})
    membership = (
        connection.execute(
            text("""
                SELECT cm.campaign_id, cm.ended_at, cm.user_id,
                       ms.code AS status_code, ms.is_active AS status_is_active
                FROM security.campaign_memberships cm
                JOIN security.membership_statuses ms
                    ON ms.membership_status_id = cm.membership_status_id
                WHERE cm.campaign_membership_id = :m
            """),
            {"m": target_membership_id},
        )
        .mappings()
        .one_or_none()
    )
    if membership is not None and membership["campaign_id"] == campaign_id:
        plan.lock(connection, TARGET_ACCOUNT_LOCK, {"target_user": membership["user_id"]})
    # 6. campaign, 7. catalogue
    plan.lock(connection, CAMPAIGN_ROW_LOCK, {"campaign": campaign_id})
    plan.lock(connection, ROLE_CATALOGUE_LOCK, {"role_a": owner_role_id, "role_b": owner_role_id})
    # 8. reads and refusals (no lock, no wait), in the legacy order
    #   1. the gate, at the transaction's start (D3): first, so a non-owner learns nothing
    if (
        find_live_builtin_owner_assignment(
            connection, campaign_id=campaign_id, campaign_membership_id=actor_membership_id
        )
        is None
    ):
        raise CampaignOwnerRequiredError(
            f"membership {actor_membership_id} holds no live campaign_owner assignment in "
            f"campaign {campaign_id}"
        )
    checked_at = _database_clock(connection)
    expired_keys = {key[0] for key in expired}
    live_keys = {key[0] for key in live}
    #   2. drift and liveness (safety-critical, not only classification: a concurrent relinquishing transfer
    #      by the recipient could otherwise leave the campaign without a built-in owner)
    if in_campaign:
        now_rows = _unrevoked_owner_rows(
            connection,
            membership_id=target_membership_id,
            owner_role_id=owner_role_id,
            checked_at=checked_at,
        )
        if (
            expired_keys & live_keys
            or set(now_rows) != expired_keys | live_keys
            or any(now_rows[key] for key in live_keys)
        ):
            raise _recipient_changed(
                target_membership_id, "the owner assignment changed while the transfer waited"
            )
    #   3. DEF-013: the caller again, at a fresh instant, after the last lock wait
    _recheck_owner(connection, campaign_id=campaign_id, actor_membership_id=actor_membership_id)
    #   4. the legacy retention assert on closing the recipient's expired row, before any replacement (F-9)
    for expired_key in sorted(expired_keys):
        _require_manager_survives(
            connection,
            campaign_id=campaign_id,
            revoked_role_id=expired_key,
            new_role_id=None,
            detail=(
                f"revoking membership role {expired_key} would leave active campaign "
                f"{campaign_id} with no membership holding access.manage"
            ),
        )
    #   5. the shared live-owner definition at the fresh instant
    already = find_live_builtin_owner_assignment(
        connection,
        campaign_id=campaign_id,
        campaign_membership_id=target_membership_id,
        as_of=checked_at,
    )
    #   6. approved policy (b): a handoff needs a non-expiring recipient assignment
    if relinquishing and already is not None:
        finite = connection.execute(
            text(
                "SELECT expires_at IS NOT NULL FROM security.membership_roles "
                "WHERE membership_role_id = :r"
            ),
            {"r": already},
        ).scalar_one()
        if finite:
            raise OwnershipTransferRecipientAssignmentExpiresError(
                f"membership {target_membership_id}'s live owner assignment {already} has an expiry"
            )
    #   7. the assignment branch's eligibility refusals, in `assign_membership_role`'s order
    if already is None:
        if membership is None or membership["campaign_id"] != campaign_id:
            raise MembershipNotInCampaignError(
                f"membership {target_membership_id} does not belong to campaign {campaign_id} "
                f"(actual campaign: {membership['campaign_id'] if membership is not None else None})"
            )
        if not (
            membership["ended_at"] is None
            and membership["status_code"] == "active"
            and membership["status_is_active"]
        ):
            raise MembershipNotActiveError(
                f"membership {target_membership_id} is not currently an eligible, open "
                "membership to assign a role to"
            )
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
                f"membership {target_membership_id}'s user {membership['user_id']} is not "
                "currently an active platform account"
            )
        _usable_role(connection, role_id=owner_role_id, campaign_id=campaign_id)
        _recheck_owner(connection, campaign_id=campaign_id, actor_membership_id=actor_membership_id)
        if live_keys:
            raise _recipient_changed(
                target_membership_id, "an owner assignment appeared while the transfer waited"
            )
    elif live_keys != {already}:
        raise _recipient_changed(
            target_membership_id, "the owner assignment changed while the transfer waited"
        )
    #   8. relinquishing: the caller again, then the retention assert for the caller's own row
    own_keys = sorted(key[0] for key in own)
    if relinquishing:
        _recheck_owner(connection, campaign_id=campaign_id, actor_membership_id=actor_membership_id)
        for own_key in own_keys:
            _require_manager_survives(
                connection,
                campaign_id=campaign_id,
                revoked_role_id=own_key,
                new_role_id=owner_role_id if already is None else None,
                detail=(
                    f"revoking membership role {own_key} would leave active campaign "
                    f"{campaign_id} with no membership holding access.manage"
                ),
            )
    #   9. the world and the audit action
    return TransferPrepared(
        world_id=_scope_world(connection, campaign_id),
        action_id=lookup_id(connection, "audit", "change_actions", "change_action_id", "updated"),
        owner_role_id=owner_role_id,
        relinquishing=relinquishing,
        expired=tuple(sorted(expired_keys)),
        own=tuple(own_keys),
        delegations=tuple(delegations),
        inserting=already is None,
        recipient_membership_id=target_membership_id,
    )


def write_transfer(
    connection: Connection,
    plan: AuthorizationPlan,
    prepared: TransferPrepared,
    *,
    actor_user_id: uuid.UUID,
    actor_membership_id: uuid.UUID,
    correlation_id: str | None,
) -> TransferWritten:
    """The declared writes, after `finalize`: close, close delegations, insert, relinquish, one audit row."""
    for expired_key in prepared.expired:
        plan.execute(connection, CLOSE_EXPIRED_OWNER, {"target": expired_key})
    for delegation in prepared.delegations:
        plan.execute(connection, CLOSE_DELEGATION_ON_REVOKE, {"delegation": delegation})
    assigned: uuid.UUID | None = None
    if prepared.inserting:
        outcome = plan.execute(
            connection,
            INSERT_OWNER_ROLE,
            {
                "membership": prepared.recipient_membership_id,
                "role": prepared.owner_role_id,
                "granted_by": actor_membership_id,
            },
        )
        assigned = outcome.keys[0][0]
        assert isinstance(assigned, uuid.UUID)
    revoked: list[uuid.UUID] = []
    if prepared.relinquishing:
        for own_key in prepared.own:
            plan.execute(connection, RELINQUISH_OWNER, {"target": own_key})
            revoked.append(own_key)
    if assigned is not None or revoked:
        plan.execute(
            connection,
            TRANSFER_AUDIT,
            {
                **_audit(
                    prepared_as_audit(prepared),
                    record=assigned or revoked[0],
                    actor_user_id=actor_user_id,
                    correlation_id=correlation_id,
                ),
                "changed": {
                    "assigned": assigned is not None,
                    "relinquished": bool(revoked),
                    "replaced_expired_assignment": bool(prepared.expired),
                },
            },
        )
    return TransferWritten(
        target_campaign_membership_id=prepared.recipient_membership_id,
        assigned_membership_role_id=assigned,
        revoked_membership_role_ids=tuple(revoked),
        replaced_expired_membership_role_ids=prepared.expired,
    )


def prepared_as_audit(prepared: TransferPrepared) -> Prepared:
    """The transfer's world and action in the shape `_audit` reads."""
    return Prepared(world_id=prepared.world_id, action_id=prepared.action_id)
