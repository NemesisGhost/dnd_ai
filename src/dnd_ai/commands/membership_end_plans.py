"""End campaign membership as a keyed-optional pre-write plan (R01 S5-E3; plan 6.30).

`end_campaign_membership` in `memberships.py` stays as the direct, unguarded command. The route
(`dnd_ai.api.memberships.end_campaign_membership_endpoint`) uses the declarations and the lock, read and write
phases below, so that **every lock is taken before `plan.finalize`**, every read a refusal depends on happens
before it, and every write is a declared step after it.

## The command, as it was (S5-E3 inventory)

`POST /campaigns/{campaign_id}/memberships/{campaign_membership_id}/end`, capability `access.manage`, no request
body, `Idempotency-Key` optional, `200` and `{"campaign_membership_id": ...}`.

1. **Authorization and refusals, in order.** The route dependency judges `access.manage` first (403/401 before
   anything below). The command then answers 404 `not_found` for a membership that does not exist or belongs to
   another campaign, a no-op (200, no write, no audit row) for an already-ended membership, and a plain `ValueError`
   (400) when ending the membership would leave an **active** campaign with no non-expiring `access.manage`
   holder. Self-removal has no special case: the actor is judged on the authority held **before** the command and
   may end their own membership, subject to the same retention rule.
2. **Cascade** (one transaction, only when the membership was open; every row is closed, never deleted, so a
   membership reopened by an invitation starts with none of them): the member's unrevoked `membership_roles`
   (`revoked_at`), their live `character_reveal_delegations` as grantee (`revoked_at`, `end_reason =
   membership_ended`; delegations the member *granted* stay), their `membership_character_relationships`
   (`revoked_at`), their `resource_grants` as grantee (`revoked_at`), their `access_group_memberships`
   (`removed_at`), the live `character_revelations` that target them (`ended_at`, `end_reason =
   target_membership_ended`) and their unremoved `character_revelation_members` snapshot rows (`removed_at`,
   `removal_reason = membership_ended`); then the membership itself (`ended_at`, `ended_by_membership_id`, the
   `revoked` status).
3. **Audit.** One `audit.change_log` row (`updated`, `previous_status active`, `new_status revoked`, the closed ids in
   `changed_fields`) for an actual removal, none for the no-op.
4. **Deferred backstops.** `tr_campaign_memberships_retain_access_manager` (AFTER UPDATE, deferred) and
   `tr_membership_roles_retain_access_manager` (AFTER UPDATE, deferred) both run `assert_campaign_retains_access_
   manager` at COMMIT, which takes the campaign `FOR UPDATE` and re-checks `campaign_has_access_manager`.

## Lock sequence (the approved ascending class order, each row once at the mode it needs, no upgrades)

Key to modes: S `FOR SHARE`, KS `FOR KEY SHARE`, U `FOR UPDATE`. A keyed request starts with the advisory key
lock and the reservation `INSERT` (actor account KS; the campaign FK deferred) and ends with the receipt row U.

1. **Role class**, one ascending pass over the actor's unrevoked role rows and the target's: the actor's rows S, the
   target's rows U, a row that is both (self-end) U once. The target's rows are *discovered* by an unlocked read and
   locked one at a time (bound to that id), the actor's rows are locked in the id ranges between them (the transfer's
   technique, plan 6.28). A row of both is never locked twice and never upgraded; two managers ending each other take
   the same rows in the same order (whoever gets the lowest first proceeds; the other waits holding nothing).
2. **Delegation class**: the target's live delegations as grantee, U, ascending id.
3. **Membership class** (C4, `lock_memberships`): the actor's open membership S and the target membership U, ascending
   id, the target first when they are the same row; then the target again, U, only while it is **open** (its
   evidence is the "this removal writes" fact, `END_OPEN_MEMBERSHIP`; already held, no wait).
4. **Accounts**: the actor's account S. (The target's account is not locked: nothing here writes a row that
   references it.)
5. **Campaign**: `FOR UPDATE` when the membership is open (every write fires a deferred retention trigger whose
   COMMIT-time campaign `FOR UPDATE` would otherwise be an upgrade), `FOR KEY SHARE` when it is not (the no-op
   writes nothing; a keyed one needs the reservation's deferred campaign FK evidence). The mode rests on **held
   evidence**, never on a prediction, and `require_campaign_mode_covers_writes` re-asserts it before `finalize`.
6. **Target class** (all U, each ascending by id, under the membership and campaign locks): the member's
   relationships, resource grants, access-group memberships, live revelations that target them, snapshot rows.
7. **Receipt** row U (keyed).

## Why the lock set is complete

- *Existing dependent rows cannot change incompatibly.* Every row the cascade writes is locked `FOR UPDATE` before
  `finalize`, in the order above; a concurrent closer of the same row (revoke role, revoke grant, remove from group,
  revoke delegation or revelation) waits for it or is waited for, and the locking statements re-evaluate their
  predicate after a wait, so a row closed meanwhile is simply not returned and not written.
- *Supported concurrent creators cannot add rows the cascade misses.* Every creator of a row of these seven tables
  references the member's membership (a foreign key, or an explicit lock of it), and the target membership is held
  `FOR UPDATE`, which conflicts with the `FOR KEY SHARE` of every such foreign key. For the **target class** (step
  6) the rows are discovered by predicate **after** the membership lock, so they are complete. The **role and
  delegation classes** come *before* the membership in the approved order, so their rows were locked before the
  membership was held: a creator that committed while the request waited for the membership added a row the early
  pass did not see. After the membership lock the request therefore reads the member's unrevoked roles and live
  delegations again and locks every row it had not locked **`FOR UPDATE NOWAIT`** (`END_LATE_ROLE_ROW`,
  `END_LATE_DELEGATION`). A `NOWAIT` lock can never wait, so it can never be an edge of a cycle even though it takes a
  role row after the membership; when another transaction holds the row (a request that holds it and wants the campaign
  would otherwise be a cycle) the request is refused with the retryable 409 `membership_end_state_changed` and nothing
  is written. A last read compares the member's live roles and delegations with every locked row; a difference would be
  a creator that slipped past the membership lock (unreachable) and is an internal error.
- *Empty evidence is not a lock that never ran.* The write obligations are `EachLockedRow(complete=True)` over the
  evidence of each lock; the membership update and the audit row are derived from the evidence of
  `END_OPEN_MEMBERSHIP` (`EachLockedRow` and `PerEvidence`), so "no rows" is a successful, executed lock; a lock that
  was never run on an open membership fails closed (the audit row is then not permitted and the plan cannot
  complete). No `Between` and no optional bound is used for the already-ended branch: it owes and may write only
  its receipt.
- *Actor/target overlap.* Self-end locks the shared rows once, at U, in the one ascending pass, and the actor's S
  lock on the membership lands on the row already held; no row is upgraded and no pair of managers can wait on each
  other's rows in opposite order.
- *No new cycle.* The order of the baseline command was: role rows, membership, the relationship, grant and group
  updates (implicit row locks), delegations, the actor `FOR KEY SHARE`, the campaign, revelations. The pre-write order
  differs only where the plan requires it (delegations before the membership, the actor's rows `FOR SHARE`, the campaign
  before the relationship, grant and group rows). The writers of those rows that are still unmigrated take the row only
  (revoke relationship, revoke grant, remove from group) or the membership first (grant relationship, create grant);
  none holds a row and then wants the campaign, so the earlier campaign lock closes no cycle with them. The one cycle
  that exists, the unmigrated `change` of a relationship (relationship row, then membership), is **identical at the
  baseline** and is characterized, not fixed (`tests/database/test_r01_s5e3_end_races.py`, S5-E4/E5).

## Declared obligations

| Branch | Writes |
|---|---|
| open | each locked role, delegation, relationship, grant, group membership, revelation and snapshot row once (`EachLockedRow(complete=True)`), the membership update once, one audit row (`PerEvidence`), the receipt (keyed) |
| already ended | the receipt only (keyed); nothing (unkeyed) |

## Retention, self-end, replay

The "a manager survives" check runs **before** `finalize`, under the held campaign lock, against the post-write
state (the member excluded); the refusal is the same `ValueError` (400) as before and the deferred triggers stay
the backstop. Self-end is judged against the pre-command authority. A replay carries the empty declaration and
takes no lock.
"""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection, bindparam, func, insert, select, text, update
from sqlalchemy.exc import DBAPIError

from dnd_ai.domain.authorization import AuthorizationPlan, ReservationDeclarations
from dnd_ai.domain.authorization_steps import (
    EachLockedRow,
    Event,
    FkBinding,
    KeyBind,
    PerEvidence,
    PreLock,
    PreWriteDeclaration,
    UniqueWait,
    WriteStep,
)
from dnd_ai.persistence.tables.audit import change_log
from dnd_ai.persistence.tables.security import (
    access_group_memberships,
    campaign_memberships,
    character_reveal_delegations,
    character_revelation_members,
    character_revelations,
    membership_character_relationships,
    membership_roles,
    membership_statuses,
    resource_grants,
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
    CAMPAIGN_ROW_LOCK,
)
from .membership_role_plans import (
    _AUDIT_BINDS,
    _LAST_ID,
    _LEAVES_ACTIVE_ASSIGNMENT_INDEX,
    _LEAVES_LIVE_DELEGATION_INDEX,
    _NO_CANDIDATE,
    _UPDATED_AT,
    DELEGATION_TRIGGERS,
    MEMBERSHIP_ROLE_TRIGGERS,
    MEMBERSHIP_TRIGGERS,
    TARGET_MEMBERSHIP_LOCK,
    _audit_values,
    _pin,
    _scope_world,
    lock_memberships,
)
from .memberships import (
    MembershipEndedStateChangedError,
    MembershipNotInCampaignError,
)
from .reveal_delegation_lifecycle import END_REASON_MEMBERSHIP_ENDED

END_COMMAND_NAME = "end_campaign_membership"
END_REASON_REVELATION_TARGET_ENDED = "target_membership_ended"
REMOVAL_REASON_MEMBERSHIP_ENDED = "membership_ended"

cm = campaign_memberships
mr = membership_roles
dl = character_reveal_delegations
mcr = membership_character_relationships
rg = resource_grants
agm = access_group_memberships
cr = character_revelations
crm = character_revelation_members

# -- locks ----------------------------------------------------------------------------------------------

#: The actor's unrevoked role rows strictly between two ids, one ordered statement, `FOR SHARE` (bound
#: `membership`, `after`, `before`). Run in the gaps between the target's rows (and once for the whole range when
#: the target has none), so the role class is one ascending pass in which the actor's rows are S and the target's U.
END_ACTOR_ROLE_RANGE = PreLock(
    "end_actor_role_range",
    select(mr.c.membership_role_id)
    .where(mr.c.campaign_membership_id == bindparam("membership"))
    .where(mr.c.revoked_at.is_(None))
    .where(mr.c.membership_role_id > bindparam("after"))
    .where(mr.c.membership_role_id < bindparam("before"))
    .order_by(mr.c.membership_role_id)
    .with_for_update(read=True),
)
#: One of the target's unrevoked role rows, `FOR UPDATE`, **candidate-bound** (bound `membership`, `row`): the row
#: the unlocked discovery read found. It can lock nothing else, so a row created later is never picked up out of
#: order; the drift check refuses it.
END_TARGET_ROLE_ROW = PreLock(
    "end_target_role_row",
    select(mr.c.membership_role_id)
    .where(mr.c.campaign_membership_id == bindparam("membership"))
    .where(mr.c.revoked_at.is_(None))
    .where(mr.c.membership_role_id == bindparam("row"))
    .with_for_update(),
)
#: A role row of the target that **appeared after the early role pass** (a creator committed while the request waited for
#: the membership), `FOR UPDATE NOWAIT`, candidate-bound (bound `membership`, `row`). It is taken only after the
#: membership is held, so it reverses the class order; it can never wait, so it can never be a deadlock edge: a row some
#: other transaction already holds raises `lock_not_available` and the request is refused with the retryable 409.
END_LATE_ROLE_ROW = PreLock(
    "end_late_role_row",
    select(mr.c.membership_role_id)
    .where(mr.c.campaign_membership_id == bindparam("membership"))
    .where(mr.c.revoked_at.is_(None))
    .where(mr.c.membership_role_id == bindparam("row"))
    .with_for_update(nowait=True),
)
#: The target's live delegations as grantee, `FOR UPDATE`, ascending id (bound `grantee`). At most one can be live
#: (`ux_character_reveal_delegations_live`).
END_TARGET_DELEGATIONS = PreLock(
    "end_target_delegations",
    select(dl.c.character_reveal_delegation_id)
    .where(dl.c.grantee_campaign_membership_id == bindparam("grantee"))
    .where(dl.c.revoked_at.is_(None))
    .order_by(dl.c.character_reveal_delegation_id)
    .with_for_update(),
)
#: The late counterpart of `END_TARGET_DELEGATIONS` (bound `grantee`, `row`): `NOWAIT`, candidate-bound.
END_LATE_DELEGATION = PreLock(
    "end_late_delegation",
    select(dl.c.character_reveal_delegation_id)
    .where(dl.c.grantee_campaign_membership_id == bindparam("grantee"))
    .where(dl.c.revoked_at.is_(None))
    .where(dl.c.character_reveal_delegation_id == bindparam("row"))
    .with_for_update(nowait=True),
)
#: The target membership again, `FOR UPDATE`, only while it is **open** (bound `campaign`, `target`): already held
#: by `TARGET_MEMBERSHIP_LOCK` (no wait). Its evidence is the database's own answer, under the lock, to "this
#: request ends a membership": one key for a genuine removal, none for the no-op.
END_OPEN_MEMBERSHIP = PreLock(
    "end_open_membership",
    select(cm.c.campaign_membership_id)
    .where(cm.c.campaign_id == bindparam("campaign"))
    .where(cm.c.campaign_membership_id == bindparam("target"))
    .where(cm.c.ended_at.is_(None))
    .with_for_update(),
)
END_RELATIONSHIPS = PreLock(
    "end_relationships",
    select(mcr.c.membership_character_relationship_id)
    .where(mcr.c.campaign_membership_id == bindparam("membership"))
    .where(mcr.c.revoked_at.is_(None))
    .order_by(mcr.c.membership_character_relationship_id)
    .with_for_update(),
)
END_GRANTS = PreLock(
    "end_resource_grants",
    select(rg.c.resource_grant_id)
    .where(rg.c.grantee_campaign_membership_id == bindparam("membership"))
    .where(rg.c.revoked_at.is_(None))
    .order_by(rg.c.resource_grant_id)
    .with_for_update(),
)
END_GROUP_MEMBERSHIPS = PreLock(
    "end_group_memberships",
    select(agm.c.access_group_membership_id)
    .where(agm.c.campaign_membership_id == bindparam("membership"))
    .where(agm.c.removed_at.is_(None))
    .order_by(agm.c.access_group_membership_id)
    .with_for_update(),
)
END_REVELATIONS = PreLock(
    "end_revelations",
    select(cr.c.character_revelation_id)
    .where(cr.c.target_campaign_membership_id == bindparam("membership"))
    .where(cr.c.ended_at.is_(None))
    .order_by(cr.c.character_revelation_id)
    .with_for_update(),
)
END_REVELATION_MEMBERS = PreLock(
    "end_revelation_members",
    select(crm.c.character_revelation_member_id)
    .where(crm.c.campaign_membership_id == bindparam("membership"))
    .where(crm.c.removed_at.is_(None))
    .order_by(crm.c.character_revelation_member_id)
    .with_for_update(),
)

# -- trigger pins of the target tables -------------------------------------------------------------------

_IMMUTABLE_FN = ("core", "enforce_immutable_columns", "583c3783f15f299e7fc903503f694c6b")
RELATIONSHIP_TRIGGERS = frozenset(
    {
        _pin(
            "tr_membership_character_relationships_enforce_scope",
            "security",
            "enforce_membership_character_relationship_scope",
            "55e6250b7716c86dd78d80414645bdd0",
        )
    }
)
GRANT_TRIGGERS = frozenset(
    {
        _pin(
            "tr_resource_grants_enforce_scope",
            "security",
            "enforce_resource_grant_scope",
            "af83cde09c796ed8b06d1834243da865",
        ),
        _pin(
            "tr_resource_grants_reject_reveal",
            "security",
            "reject_character_reveal_capability_row",
            "9334dcfb854da2b93743ae815823e661",
        ),
        _pin(
            "tr_resource_grants_reject_view_public_profile",
            "security",
            "reject_view_public_profile_capability_row",
            "a385af3db8ebf52afa9c149229c3544e",
        ),
    }
)
GROUP_MEMBERSHIP_TRIGGERS = frozenset(
    {
        _pin(
            "tr_access_group_memberships_enforce_scope",
            "security",
            "enforce_access_group_membership_scope",
            "ccb4400359f288ec4f5482a3f1f0600c",
        )
    }
)
REVELATION_TRIGGERS = frozenset(
    {
        _pin(
            "tr_character_revelations_closed_once",
            "security",
            "enforce_character_revelation_closed_once",
            "cfe44771b20b8233eb909ac1ac3d4f01",
            events=frozenset({Event.UPDATE}),
        ),
        _pin(
            "tr_character_revelations_enforce_immutable",
            *_IMMUTABLE_FN,
            events=frozenset({Event.UPDATE}),
            args=(
                "campaign_id",
                "character_id",
                "revelation_audience_kind_id",
                "target_campaign_membership_id",
                "target_access_group_id",
                "created_by_membership_id",
                "authority_source_code",
                "character_reveal_delegation_id",
                "reason",
                "created_at",
            ),
        ),
        _pin(
            "tr_character_revelations_enforce_shape_and_scope",
            "security",
            "enforce_character_revelation_shape_and_scope",
            "6bb386237a385102e6dcc5b77ef1361a",
        ),
        _pin(
            "tr_character_revelations_set_updated_at",
            *_UPDATED_AT,
            events=frozenset({Event.UPDATE}),
        ),
    }
)
REVELATION_MEMBER_TRIGGERS = frozenset(
    {
        _pin(
            "tr_character_revelation_members_rules",
            "security",
            "enforce_character_revelation_member_rules",
            "93969e5ade75cd42cd2c11cd38c9a017",
        )
    }
)

# -- steps ----------------------------------------------------------------------------------------------

_LEAVES_INDEX_TEST = (
    "tests/database/test_r01_s5e3_end_membership.py::"
    "test_an_update_leaving_a_partial_unique_index_never_waits_for_a_competing_insert"
)


def _leaves_index(index: str) -> frozenset[UniqueWait]:
    """An UPDATE that sets the closing column *leaves* a partial unique index (`WHERE <closing column> IS NULL`): it
    inserts no index entry, so it can never wait for a competitor's key, and a competitor's INSERT of the same key
    waits for this transaction instead. Pinned by the named test for every index below."""
    return frozenset({UniqueWait(index, _LEAVES_INDEX_TEST)})


_NOW = func.pg_catalog.clock_timestamp
END_REVOKE_ROLE = WriteStep(
    name="end_revoke_role",
    statement=update(mr)
    .where(mr.c.membership_role_id == bindparam("target"))
    .values(revoked_at=_NOW())
    .returning(mr.c.membership_role_id),
    cardinality=EachLockedRow(complete=True),
    target=(KeyBind(mr.c.membership_role_id, "target"),),
    target_lock=END_TARGET_ROLE_ROW,
    unique_waits=_LEAVES_ACTIVE_ASSIGNMENT_INDEX,
    triggers=frozenset(t for t in MEMBERSHIP_ROLE_TRIGGERS if Event.UPDATE in t.events),
)
END_REVOKE_LATE_ROLE = WriteStep(
    name="end_revoke_late_role",
    statement=update(mr)
    .where(mr.c.membership_role_id == bindparam("target"))
    .values(revoked_at=_NOW())
    .returning(mr.c.membership_role_id),
    cardinality=EachLockedRow(complete=True),
    target=(KeyBind(mr.c.membership_role_id, "target"),),
    target_lock=END_LATE_ROLE_ROW,
    unique_waits=_LEAVES_ACTIVE_ASSIGNMENT_INDEX,
    triggers=frozenset(t for t in MEMBERSHIP_ROLE_TRIGGERS if Event.UPDATE in t.events),
)
END_CLOSE_DELEGATION = WriteStep(
    name="end_close_delegation",
    statement=update(dl)
    .where(dl.c.character_reveal_delegation_id == bindparam("target"))
    .values(revoked_at=_NOW(), end_reason=END_REASON_MEMBERSHIP_ENDED)
    .returning(dl.c.character_reveal_delegation_id),
    cardinality=EachLockedRow(complete=True),
    target=(KeyBind(dl.c.character_reveal_delegation_id, "target"),),
    target_lock=END_TARGET_DELEGATIONS,
    unique_waits=_LEAVES_LIVE_DELEGATION_INDEX,
    triggers=DELEGATION_TRIGGERS,
)
END_CLOSE_LATE_DELEGATION = WriteStep(
    name="end_close_late_delegation",
    statement=update(dl)
    .where(dl.c.character_reveal_delegation_id == bindparam("target"))
    .values(revoked_at=_NOW(), end_reason=END_REASON_MEMBERSHIP_ENDED)
    .returning(dl.c.character_reveal_delegation_id),
    cardinality=EachLockedRow(complete=True),
    target=(KeyBind(dl.c.character_reveal_delegation_id, "target"),),
    target_lock=END_LATE_DELEGATION,
    unique_waits=_LEAVES_LIVE_DELEGATION_INDEX,
    triggers=DELEGATION_TRIGGERS,
)
END_REVOKE_RELATIONSHIP = WriteStep(
    name="end_revoke_relationship",
    statement=update(mcr)
    .where(mcr.c.membership_character_relationship_id == bindparam("target"))
    .values(revoked_at=_NOW())
    .returning(mcr.c.membership_character_relationship_id),
    cardinality=EachLockedRow(complete=True),
    target=(KeyBind(mcr.c.membership_character_relationship_id, "target"),),
    target_lock=END_RELATIONSHIPS,
    unique_waits=_leaves_index("security.ux_membership_character_relationships_active_type"),
    triggers=RELATIONSHIP_TRIGGERS,
)
END_REVOKE_GRANT = WriteStep(
    name="end_revoke_grant",
    statement=update(rg)
    .where(rg.c.resource_grant_id == bindparam("target"))
    .values(revoked_at=_NOW())
    .returning(rg.c.resource_grant_id),
    cardinality=EachLockedRow(complete=True),
    target=(KeyBind(rg.c.resource_grant_id, "target"),),
    target_lock=END_GRANTS,
    unique_waits=_leaves_index("security.ux_resource_grants_active"),
    triggers=GRANT_TRIGGERS,
)
END_REMOVE_GROUP_MEMBERSHIP = WriteStep(
    name="end_remove_group_membership",
    statement=update(agm)
    .where(agm.c.access_group_membership_id == bindparam("target"))
    .values(removed_at=_NOW())
    .returning(agm.c.access_group_membership_id),
    cardinality=EachLockedRow(complete=True),
    target=(KeyBind(agm.c.access_group_membership_id, "target"),),
    target_lock=END_GROUP_MEMBERSHIPS,
    unique_waits=_leaves_index("security.ux_access_group_memberships_open"),
    triggers=GROUP_MEMBERSHIP_TRIGGERS,
)
END_CLOSE_REVELATION = WriteStep(
    name="end_close_revelation",
    statement=update(cr)
    .where(cr.c.character_revelation_id == bindparam("target"))
    .values(ended_at=_NOW(), end_reason=END_REASON_REVELATION_TARGET_ENDED)
    .returning(cr.c.character_revelation_id),
    cardinality=EachLockedRow(complete=True),
    target=(KeyBind(cr.c.character_revelation_id, "target"),),
    target_lock=END_REVELATIONS,
    unique_waits=_leaves_index("security.ux_character_revelations_live"),
    triggers=REVELATION_TRIGGERS,
)
END_REMOVE_REVELATION_MEMBER = WriteStep(
    name="end_remove_revelation_member",
    statement=update(crm)
    .where(crm.c.character_revelation_member_id == bindparam("target"))
    .values(removed_at=_NOW(), removal_reason=REMOVAL_REASON_MEMBERSHIP_ENDED)
    .returning(crm.c.character_revelation_member_id),
    cardinality=EachLockedRow(complete=True),
    target=(KeyBind(crm.c.character_revelation_member_id, "target"),),
    target_lock=END_REVELATION_MEMBERS,
    triggers=REVELATION_MEMBER_TRIGGERS,
)
END_MEMBERSHIP = WriteStep(
    name="end_membership",
    statement=update(cm)
    .where(cm.c.campaign_membership_id == bindparam("target"))
    .values(
        ended_at=_NOW(),
        ended_by_membership_id=bindparam("actor"),
        membership_status_id=bindparam("status"),
    )
    .returning(cm.c.campaign_membership_id),
    cardinality=EachLockedRow(complete=True),
    target=(KeyBind(cm.c.campaign_membership_id, "target"),),
    target_lock=END_OPEN_MEMBERSHIP,
    unique_waits=_leaves_index("security.ux_campaign_memberships_open"),
    fks=(
        FkBinding(
            fk_of(cm, "ended_by_membership_id"),
            (KeyBind(cm.c.ended_by_membership_id, "actor"),),
            ACTOR_MEMBERSHIP_LOCK,
        ),
        FkBinding(
            fk_of(cm, "membership_status_id"),
            (KeyBind(cm.c.membership_status_id, "status"),),
            None,
        ),
    ),
    triggers=frozenset(t for t in MEMBERSHIP_TRIGGERS if Event.UPDATE in t.events),
)
END_AUDIT = WriteStep(
    name="audit_membership_ended",
    statement=insert(change_log)
    .values(
        **_audit_values("campaign_memberships", END_COMMAND_NAME),
        previous_status="active",
        new_status="revoked",
        changed_fields=bindparam("changed"),
    )
    .returning(change_log.c.change_log_id),
    cardinality=PerEvidence(END_OPEN_MEMBERSHIP),
    fks=(CHANGE_LOG_ACTION_FK, CHANGE_LOG_ACTOR_FK),
    value_binds=_AUDIT_BINDS | {"changed"},
)
END_RECEIPT = RECEIPT_STEP

_END_LOCKS = (
    END_ACTOR_ROLE_RANGE,
    END_TARGET_ROLE_ROW,
    END_TARGET_DELEGATIONS,
    ACTOR_MEMBERSHIP_LOCK,
    TARGET_MEMBERSHIP_LOCK,
    END_OPEN_MEMBERSHIP,
    END_LATE_ROLE_ROW,
    END_LATE_DELEGATION,
    ACTOR_ACCOUNT_LOCK,
    CAMPAIGN_ROW_LOCK,
    CAMPAIGN_KEY_SHARE_LOCK,
    END_RELATIONSHIPS,
    END_GRANTS,
    END_GROUP_MEMBERSHIPS,
    END_REVELATIONS,
    END_REVELATION_MEMBERS,
)
_END_STEPS = (
    END_REVOKE_ROLE,
    END_REVOKE_LATE_ROLE,
    END_CLOSE_DELEGATION,
    END_CLOSE_LATE_DELEGATION,
    END_REVOKE_RELATIONSHIP,
    END_REVOKE_GRANT,
    END_REMOVE_GROUP_MEMBERSHIP,
    END_CLOSE_REVELATION,
    END_REMOVE_REVELATION_MEMBER,
    END_MEMBERSHIP,
    END_AUDIT,
)
_UNLOCKED = CHANGE_LOG_UNLOCKED_FK_TARGETS | {membership_statuses}
END_DECLARATIONS = ReservationDeclarations(
    reserved=PreWriteDeclaration(
        locks=(*_END_LOCKS, RECEIPT_LOCK),
        steps=(*_END_STEPS, END_RECEIPT),
        unlocked_fk_targets=_UNLOCKED,
    ),
    unkeyed=PreWriteDeclaration(
        locks=_END_LOCKS,
        steps=_END_STEPS,
        unlocked_fk_targets=_UNLOCKED,
    ),
)

# -- reads ---------------------------------------------------------------------------------------------

#: `security.campaign_has_access_manager`, with the membership being ended excluded: the post-write state.
_MANAGER_SURVIVES_END = text("""
    SELECT EXISTS (
        SELECT 1
        FROM security.campaign_memberships cm
        JOIN security.membership_statuses ms ON ms.membership_status_id = cm.membership_status_id
        JOIN security.membership_roles mr ON mr.campaign_membership_id = cm.campaign_membership_id
        JOIN security.roles r ON r.role_id = mr.role_id
        JOIN security.role_capabilities rc ON rc.role_id = r.role_id
        JOIN security.capabilities c ON c.capability_id = rc.capability_id
        WHERE cm.campaign_id = :campaign AND cm.ended_at IS NULL
          AND cm.campaign_membership_id <> :ended
          AND ms.code = 'active' AND ms.is_active
          AND mr.revoked_at IS NULL AND mr.expires_at IS NULL
          AND r.is_active AND (r.campaign_id IS NULL OR r.campaign_id = :campaign)
          AND c.code = 'access.manage' AND c.is_active
    )
""")


def _require_manager_survives_end(
    connection: Connection, *, campaign_id: uuid.UUID, ended_membership_id: uuid.UUID
) -> None:
    """The retention pre-check, before `finalize` and under the held campaign lock: an active campaign must keep a
    non-expiring `access.manage` holder once `ended_membership_id` is closed. A plain `ValueError` (400) as before;
    the deferred triggers stay the backstop."""
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
    if not connection.execute(
        _MANAGER_SURVIVES_END, {"campaign": campaign_id, "ended": ended_membership_id}
    ).scalar():
        raise ValueError(
            f"ending membership {ended_membership_id} would leave active campaign "
            f"{campaign_id} with no membership holding access.manage"
        )


def require_campaign_mode_covers_writes(*, will_write: bool, campaign_for_update: bool) -> None:
    """Internal invariant (unreachable in production): every write of an open removal fires a deferred retention
    trigger whose COMMIT-time campaign `FOR UPDATE` would be an upgrade of a weaker mode taken here."""
    if will_write and not campaign_for_update:
        raise RuntimeError("the membership end writes but did not take the campaign FOR UPDATE")


@dataclass(frozen=True)
class EndPrepared:
    """What the lock and read phase established, all before `finalize`."""

    world_id: uuid.UUID
    action_id: uuid.UUID
    status_id: uuid.UUID
    will_write: bool
    role_ids: tuple[uuid.UUID, ...] = ()
    late_role_ids: tuple[uuid.UUID, ...] = ()
    delegation_ids: tuple[uuid.UUID, ...] = ()
    late_delegation_ids: tuple[uuid.UUID, ...] = ()
    relationship_ids: tuple[uuid.UUID, ...] = ()
    grant_ids: tuple[uuid.UUID, ...] = ()
    group_membership_ids: tuple[uuid.UUID, ...] = ()
    revelation_ids: tuple[uuid.UUID, ...] = ()
    revelation_member_ids: tuple[uuid.UUID, ...] = ()


def _ids(keys: Any) -> tuple[uuid.UUID, ...]:
    return tuple(sorted(key[0] for key in keys))


_LIVE_ROLES = (
    "SELECT membership_role_id FROM security.membership_roles "
    "WHERE campaign_membership_id = :m AND revoked_at IS NULL"
)
_LIVE_DELEGATIONS = (
    "SELECT character_reveal_delegation_id FROM security.character_reveal_delegations "
    "WHERE grantee_campaign_membership_id = :m AND revoked_at IS NULL"
)
_LOCK_NOT_AVAILABLE = "55P03"


def _live_ids(connection: Connection, sql: str, membership_id: uuid.UUID) -> tuple[uuid.UUID, ...]:
    return tuple(sorted(connection.execute(text(sql), {"m": membership_id}).scalars()))


def prepare_end_membership(  # noqa: PLR0915 - one linear lock and refusal sequence
    connection: Connection,
    plan: AuthorizationPlan,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    actor_membership_id: uuid.UUID,
    target_membership_id: uuid.UUID,
    reservation_id: uuid.UUID | None,
) -> EndPrepared:
    """Every lock, read and refusal of the removal, in the design's order, before `finalize`."""
    self_end = actor_membership_id == target_membership_id
    # 1. an unlocked read: the target's campaign (never changes, `enforce_immutable`) and whether it looks open. The
    #    second is a hint only: it decides whether the early role and delegation passes are worth taking (an ended
    #    membership has nothing to close), and the membership lock below decides for real. A membership that was
    #    reopened in the window has its rows found by the late pass; one that ended in the window finds its rows
    #    already revoked when the early statements re-evaluate their predicates.
    target = (
        connection.execute(
            text(
                "SELECT campaign_id, ended_at IS NULL AS open "
                "FROM security.campaign_memberships WHERE campaign_membership_id = :m"
            ),
            {"m": target_membership_id},
        )
        .mappings()
        .one_or_none()
    )
    in_campaign = target is not None and target["campaign_id"] == campaign_id
    looks_open = in_campaign and bool(target["open"]) if target is not None else False
    # 2. role class, one ascending pass: the target's rows (discovered unlocked, locked one by one at U) with the
    #    actor's rows (S) in the id ranges between them. A self-end has only the target's rows (the same rows).
    target_roles: list[uuid.UUID] = []
    if looks_open:
        target_roles = list(
            connection.execute(
                text(
                    "SELECT membership_role_id FROM security.membership_roles "
                    "WHERE campaign_membership_id = :m AND revoked_at IS NULL "
                    "ORDER BY membership_role_id"
                ),
                {"m": target_membership_id},
            ).scalars()
        )

    def actor_range(after: uuid.UUID, before: uuid.UUID) -> None:
        if not self_end:
            plan.lock(
                connection,
                END_ACTOR_ROLE_RANGE,
                {"membership": actor_membership_id, "after": after, "before": before},
            )

    locked_roles: set[uuid.UUID] = set()
    previous = _NO_CANDIDATE
    for role_id in target_roles:
        actor_range(previous, role_id)
        for key in plan.lock(
            connection, END_TARGET_ROLE_ROW, {"membership": target_membership_id, "row": role_id}
        ):
            locked_roles.add(key[0])
        previous = role_id
    actor_range(previous, _LAST_ID)
    # 3. delegation class
    delegations: tuple[tuple[Any, ...], ...] = ()
    if looks_open:
        delegations = plan.lock(
            connection, END_TARGET_DELEGATIONS, {"grantee": target_membership_id}
        )
    # 4. membership class (C4), then the open evidence
    lock_memberships(
        connection,
        plan,
        campaign_id=campaign_id,
        actor_membership_id=actor_membership_id,
        target_membership_id=target_membership_id,
    )
    open_evidence = plan.lock(
        connection,
        END_OPEN_MEMBERSHIP,
        {"campaign": campaign_id, "target": target_membership_id},
    )
    # the refusal that needs only the membership lock: unknown or foreign membership (404, as before)
    row = (
        connection.execute(
            text(
                "SELECT campaign_id, ended_at FROM security.campaign_memberships "
                "WHERE campaign_membership_id = :m"
            ),
            {"m": target_membership_id},
        )
        .mappings()
        .one_or_none()
    )
    if row is None or row["campaign_id"] != campaign_id:
        raise MembershipNotInCampaignError(
            f"membership {target_membership_id} does not belong to campaign {campaign_id} "
            f"(actual campaign: {row['campaign_id'] if row is not None else None})"
        )
    will_write = bool(open_evidence)
    if will_write != (
        row["ended_at"] is None
    ):  # the lock's own evidence and the row read cannot differ
        raise RuntimeError("the membership changed under its own lock")
    # 4b. the roles and delegations were locked before the membership: read them again now that it is held (no creator
    #     can add one any more). A row that appeared while the request waited is locked here, `NOWAIT`: it can never
    #     wait, so it can never be an edge of a cycle; if another transaction holds it the request is refused with the
    #     retryable 409 and nothing is written.
    late_roles: set[uuid.UUID] = set()
    late_delegations: set[uuid.UUID] = set()
    if will_write:
        known_delegations = {key[0] for key in delegations}
        try:
            for row_id in _live_ids(connection, _LIVE_ROLES, target_membership_id):
                if row_id not in locked_roles:
                    for key in plan.lock(
                        connection,
                        END_LATE_ROLE_ROW,
                        {"membership": target_membership_id, "row": row_id},
                    ):
                        late_roles.add(key[0])
            for row_id in _live_ids(connection, _LIVE_DELEGATIONS, target_membership_id):
                if row_id not in known_delegations:
                    for key in plan.lock(
                        connection,
                        END_LATE_DELEGATION,
                        {"grantee": target_membership_id, "row": row_id},
                    ):
                        late_delegations.add(key[0])
        except DBAPIError as exc:
            if getattr(exc.orig, "sqlstate", None) != _LOCK_NOT_AVAILABLE:
                raise
            raise MembershipEndedStateChangedError(
                f"membership {target_membership_id}: a role or delegation created while the removal "
                "waited is held by another request"
            ) from exc
    # 5. accounts, then the campaign: FOR UPDATE for a removal (the deferred retention triggers re-acquire it at
    #    COMMIT), FOR KEY SHARE for the no-op (nothing is written; the keyed deferral still needs evidence)
    plan.lock(connection, ACTOR_ACCOUNT_LOCK, {"actor": actor_user_id})
    if will_write:
        plan.lock(connection, CAMPAIGN_ROW_LOCK, {"campaign": campaign_id})
    else:
        plan.lock(connection, CAMPAIGN_KEY_SHARE_LOCK, {"campaign": campaign_id})
    # 6. target class: rows complete by predicate, because the membership lock excludes every creator
    relationships: tuple[tuple[Any, ...], ...] = ()
    grants: tuple[tuple[Any, ...], ...] = ()
    groups: tuple[tuple[Any, ...], ...] = ()
    revelations: tuple[tuple[Any, ...], ...] = ()
    snapshot_rows: tuple[tuple[Any, ...], ...] = ()
    if will_write:
        binds = {"membership": target_membership_id}
        relationships = plan.lock(connection, END_RELATIONSHIPS, binds)
        grants = plan.lock(connection, END_GRANTS, binds)
        groups = plan.lock(connection, END_GROUP_MEMBERSHIPS, binds)
        revelations = plan.lock(connection, END_REVELATIONS, binds)
        snapshot_rows = plan.lock(connection, END_REVELATION_MEMBERS, binds)
    # 7. the receipt
    if reservation_id is not None:
        plan.lock(connection, RECEIPT_LOCK, {"receipt": reservation_id})
    # 8. reads and refusals (no lock, no wait)
    #   completeness: every live role and delegation of the member is now locked (an unlocked one would be a creator
    #   that slipped past the membership lock: unreachable, and refused rather than written around)
    live_roles = _live_ids(connection, _LIVE_ROLES, target_membership_id)
    live_delegations = _live_ids(connection, _LIVE_DELEGATIONS, target_membership_id)
    if will_write and (
        live_roles != tuple(sorted(locked_roles | late_roles))
        or live_delegations != tuple(sorted({key[0] for key in delegations} | late_delegations))
    ):
        raise RuntimeError("a role or delegation of the member is not among the locked rows")
    # (an ended membership is the no-op whatever it still holds: the baseline never touched it either)
    if will_write:
        _require_manager_survives_end(
            connection, campaign_id=campaign_id, ended_membership_id=target_membership_id
        )
    require_campaign_mode_covers_writes(will_write=will_write, campaign_for_update=will_write)
    return EndPrepared(
        world_id=_scope_world(connection, campaign_id),
        action_id=lookup_id(connection, "audit", "change_actions", "change_action_id", "updated"),
        status_id=lookup_id(
            connection, "security", "membership_statuses", "membership_status_id", "revoked"
        ),
        will_write=will_write,
        role_ids=tuple(sorted(locked_roles)),
        late_role_ids=tuple(sorted(late_roles)),
        delegation_ids=_ids(delegations),
        late_delegation_ids=tuple(sorted(late_delegations)),
        relationship_ids=_ids(relationships),
        grant_ids=_ids(grants),
        group_membership_ids=_ids(groups),
        revelation_ids=_ids(revelations),
        revelation_member_ids=_ids(snapshot_rows),
    )


def changed_fields(prepared: EndPrepared) -> dict[str, list[str]]:
    """The audit row's `changed_fields`: the ids closed by this removal (the keys the locks returned)."""
    return {
        "revoked_membership_role_ids": [
            str(i) for i in sorted((*prepared.role_ids, *prepared.late_role_ids))
        ],
        "revoked_membership_character_relationship_ids": [
            str(i) for i in prepared.relationship_ids
        ],
        "revoked_resource_grant_ids": [str(i) for i in prepared.grant_ids],
        "removed_access_group_membership_ids": [str(i) for i in prepared.group_membership_ids],
        "closed_character_revelation_ids": [str(i) for i in prepared.revelation_ids],
        "removed_character_revelation_member_ids": [str(i) for i in prepared.revelation_member_ids],
    }


def write_end_membership(
    connection: Connection,
    plan: AuthorizationPlan,
    prepared: EndPrepared,
    *,
    campaign_membership_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    actor_membership_id: uuid.UUID,
    correlation_id: str | None,
) -> None:
    """The declared closures, the membership update and the audit row (attempted only by a genuine removal)."""
    if not prepared.will_write:
        return
    for step, ids in (
        (END_REVOKE_ROLE, prepared.role_ids),
        (END_REVOKE_LATE_ROLE, prepared.late_role_ids),
        (END_CLOSE_DELEGATION, prepared.delegation_ids),
        (END_CLOSE_LATE_DELEGATION, prepared.late_delegation_ids),
        (END_REVOKE_RELATIONSHIP, prepared.relationship_ids),
        (END_REVOKE_GRANT, prepared.grant_ids),
        (END_REMOVE_GROUP_MEMBERSHIP, prepared.group_membership_ids),
        (END_CLOSE_REVELATION, prepared.revelation_ids),
        (END_REMOVE_REVELATION_MEMBER, prepared.revelation_member_ids),
    ):
        for key in ids:
            plan.execute(connection, step, {"target": key})
    plan.execute(
        connection,
        END_MEMBERSHIP,
        {
            "target": campaign_membership_id,
            "actor": actor_membership_id,
            "status": prepared.status_id,
        },
    )
    plan.execute(
        connection,
        END_AUDIT,
        {
            "action": prepared.action_id,
            "record": campaign_membership_id,
            "world": prepared.world_id,
            "actor": actor_user_id,
            "correlation": uuid.UUID(correlation_id) if correlation_id is not None else None,
            "changed": changed_fields(prepared),
        },
    )
