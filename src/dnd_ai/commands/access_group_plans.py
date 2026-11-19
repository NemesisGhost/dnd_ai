"""Access-group lifecycle and membership as keyed-optional pre-write plans (R01 S5-E5; plan 6.34).

`create_access_group` ... `remove_access_group_member` in `access_groups.py` stay as the direct, unguarded commands. The six
routes (`dnd_ai.api.access_groups`) use the declarations and the lock, read and write phases below, so that **every lock is
taken before `plan.finalize`**, every read a refusal depends on happens before it, and every write is a declared step after it.

## The routes, as they were (S5-E5 inventory; every status code, class, precedence, response, fingerprint and audit payload stays)

All six: capability `access.manage` (the route dependency judges it first), `Idempotency-Key` optional, audit rows with
`entity_id` and `event_id` null and `world_id` the campaign's own. A fresh keyed request ends with its receipt row; a replay
returns the stored response.

| Route | Success | Refusals, in the order the command raised them | No-op |
|---|---|---|---|
| create | 201 `{access_group_id, name}` | 422 blank / too long (trimmed name or description); campaign not active (409); duplicate name at the INSERT (409) | none |
| update | 200 `{access_group_id, name}` | group not in campaign (404); not active (409); 422 blank / too long; 422 no-op (a refusal: never stored, the key stays reusable); duplicate name at the UPDATE (409) | none |
| deactivate | 200 `{access_group_id, name}` | not in campaign (404) | already archived: 200, no write, no audit |
| reactivate | 200 `{access_group_id, name}` | not in campaign (404); campaign not active (409, the reactivation path only) | already active: 200, no write, no audit, campaign status not checked |
| add members | 201 `{id iff exactly one, ids, added_count}` | group 404, group not active 409; campaign not active 409; per member in ascending id order: not in campaign 404, not open/eligible 409, account not active 409; an already-open link at the INSERT 409 | none |
| remove member | 200 `{access_group_membership_id}` | link not in campaign, or nonexistent (404) | already removed: 200, no write, no audit |

**Bulk add is all-or-nothing.** An already-open link, an ineligible member, an inactive account or a foreign or nonexistent
membership refuses the whole batch; nothing is written and the key stays reusable. Nothing is skipped.

## Lock sequences (AO-1, CA-1)

Key to modes: S `FOR SHARE`, KS `FOR KEY SHARE`, NKU `FOR NO KEY UPDATE`, U `FOR UPDATE`. A keyed request starts with the
advisory key lock and the reservation `INSERT` (the actor's account KS; the campaign FK deferred) and ends with the receipt U.

For every transaction that locks an access-group row the order is **[keyed prefix] -> role rows -> delegation rows -> group row ->
memberships -> accounts -> campaign -> catalogue rows -> targets -> dependent rows** (correction design 3.1, AO-1; it supersedes
the earlier "group first" LA-1). A transaction holding a group row never waits for a role-row lock, so none of the cycles of the
shape found as NF-1 (revelation creation holding role rows and waiting for the group, a group holder waiting for its role rows, a
role writer bridging them) can contain a group-row wait. The claim is argued in correction design 3.2 **with its limits**: the
DEF-019 patterns (keyed authoring holds the campaign KS, then waits for a role row) and the recovery/invitation commit upgrades
are pre-existing and tracked; the order claim rests on the inventory of group lockers pinned by a structure test.

| Route | Locks |
|---|---|
| create | actor's role rows S; actor's membership S; actor's account S; **campaign KS** (CA-1); [receipt U] |
| update | actor's role rows S; **group U**; actor's membership S; actor's account S; campaign KS; [receipt U] |
| deactivate | actor's role rows S; **group U**; **group U again while active** (the "this request archives" evidence, a row already held); actor's membership S, account S; campaign KS; *only when the active evidence is non-empty:* the group's open links U, unrevoked grants U, live revelations U (each ascending); [receipt U] |
| reactivate | actor's role rows S; **group U**; **group U again while archived**; actor's membership S, account S; **campaign KS** (CA-1, always); [receipt U] |
| add | actor's role rows S; **group U** (404 and 409 refused here, before any member lock); the **membership pass**, ascending id over {actor} U members: each member NKU (one call per id), the actor S, a row that is both NKU first and then S on the held row; the **account pass**, ascending user id: the actor S, each member KS, a shared row S once; campaign KS (never U); [receipt U] |
| remove | an *unlocked discovery* of link -> group -> campaign (never updated; 404 here, without locking a foreign row); actor's role rows S, membership S, account S; campaign KS; **the link U, only while open**; [receipt U] |

CA-1: create and reactivate lock the campaign at KS, not U. No trigger of `access_groups` needs more; KS still conflicts with an
archive's `FOR UPDATE`, so the campaign-active read stays stable, and keyed authoring's reservation KS no longer waits for them.
Members are NKU, not U: a member's own FK `KEY SHARE` (for a grant the member makes) does not conflict; ending the membership,
role changes, recovery and a grant to the member do. Add stays at campaign KS: U would cycle with keyed authoring by a member
being added.

A group of another campaign matches no lock (the predicate binds the campaign), so the 404 is raised right after the group lock.

## Declared obligations (each branch chosen from held evidence, never from a handler flag)

| Route | Writes |
|---|---|
| create | `INSERT_GROUP` `Exactly(1)`, `CREATE_AUDIT` `Exactly(1)`, receipt |
| update | `UPDATE_GROUP` `Exactly(1)`, `UPDATE_AUDIT` `Exactly(1)`, receipt |
| deactivate, active | `ARCHIVE_GROUP`, `CLOSE_GROUP_LINKS`, `REVOKE_GROUP_GRANTS`, `CLOSE_GROUP_REVELATIONS` (each `EachLockedRow(complete=True)` over its lock), `DEACTIVATE_AUDIT` `PerEvidence(GROUP_ACTIVE_LOCK)`, receipt |
| deactivate, archived / reactivate, active / remove, removed | nothing but the receipt |
| reactivate, archived | `REACTIVATE_GROUP` `EachLockedRow(complete=True)`, `REACTIVATE_AUDIT` `PerEvidence(GROUP_ARCHIVED_LOCK)`, receipt |
| add | `INSERT_LINK` `PerEvidenceRow(MEMBER_LOCK, via=<the campaign_membership_id FkBinding>)` (one link per locked member), `LINK_AUDIT` `PerConfirmedRow(INSERT_LINK, "record")` (one audit row per confirmed link, naming it), receipt |
| remove, open | `REMOVE_LINK`, `REMOVE_AUDIT` `PerEvidence(LINK_OPEN_LOCK)`, receipt |

No `Between` and no optional bound for another branch.

## Timestamps

| Close | S5-E5 | Basis |
|---|---|---|
| group revelations | `GREATEST(clock_timestamp(), created_at)` | the legacy expression, preserved exactly (I-3) |
| group grants | `GREATEST(clock_timestamp(), granted_at)` | **B-5**: the legacy `now()` can be earlier than a group-grantee grant's `granted_at` (a grant that starts after the deactivation's transaction but takes the group first and commits), which violates `ck_resource_grants_revoked_after_granted` (23514) and rolled the deactivation back |
| group links, the removed link | `pg_catalog.now()` | preserved; no constraint involved |

Legacy evaluated each expression per row inside one multi-row UPDATE; here every locked row has its own declared UPDATE, so
`clock_timestamp()` is read per row at that row's statement. The clamp is identical and the instants differ only by statement
boundaries inside one transaction with every row already held.

## H-1 and D-1 (deactivation's cascade completeness)

After the three dependent locks and before `finalize`, **H-1** reads (unlocked) the group's open link, unrevoked grant and live
revelation ids by the same three predicates and compares each set with the keys the handler **received from that class's
`plan.lock`**. Any difference raises `AccessGroupCascadeIncompleteError` (a 500, a full rollback, the key reusable). The creators
of those rows (add, the two grant paths, revelation creation) all hold the group and are excluded by the group U, and the
closers of the rows lock one row last; so the sets cannot change between the locks and the check.

**Trust boundary.** H-1 is route code, not a mechanism guard. It detects an omitted or narrowed lock call while the check itself
remains. It does **not** detect the removal of both, and it does not prove the predicates. It runs only on the active branch.

**D-1 (accepted for S5-E5 only, not a waiver for future slices).** The mechanism enforces that every dependent UPDATE targets a key
of its own lock's evidence, at most once, that every row a lock that ran returned is closed exactly once, and the step order. It
does **not** enforce that a dependent lock ran (`EachLockedRow(complete=True)` treats a lock that never ran as empty). Omission is
detected by H-1 at runtime and, on the tested source, by post-state assertions with rows in every class, exact statement-sequence
pins and mutations that remove each lock call.
"""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection, bindparam, func, insert, select, text, update

from dnd_ai.domain.authorization import AuthorizationPlan, ReservationDeclarations
from dnd_ai.domain.authorization_steps import (
    EachLockedRow,
    Event,
    Exactly,
    FkBinding,
    KeyBind,
    PerConfirmedRow,
    PerEvidence,
    PerEvidenceRow,
    PreLock,
    PreWriteDeclaration,
    UniqueWait,
    WriteStep,
)
from dnd_ai.persistence.tables.audit import change_log
from dnd_ai.persistence.tables.core import lifecycle_statuses
from dnd_ai.persistence.tables.security import (
    access_group_memberships,
    access_groups,
    campaign_memberships,
    character_revelations,
    resource_grants,
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
from .access_grant_plans import _lock_actor
from .access_grants import (
    AccessGroupNotActiveError,
    AccessGroupNotInCampaignError,
    MembershipNotActiveError,
    MembershipNotInCampaignError,
)
from .access_groups import (
    ACCESS_GROUP_DESCRIPTION_MAX_LENGTH,
    ACCESS_GROUP_NAME_MAX_LENGTH,
    AccessGroupDescriptionTooLongError,
    AccessGroupMembershipNotInCampaignError,
    AccessGroupNameTooLongError,
    AccessGroupUpdateNoOpError,
    BlankAccessGroupNameError,
)
from .campaign_lifecycle_plans import (
    ACTOR_ACCOUNT_LOCK,
    ACTOR_MEMBERSHIP_LOCK,
    ACTOR_ROLES_LOCK,
)
from .membership_end_plans import GRANT_TRIGGERS, GROUP_MEMBERSHIP_TRIGGERS, REVELATION_TRIGGERS
from .membership_role_plans import (
    _AUDIT_BINDS,
    _IMMUTABLE,
    _UPDATED_AT,
    _audit_values,
    _pin,
    _scope_world,
)
from .memberships import CampaignNotActiveError

CREATE_COMMAND_NAME = "create_access_group"
UPDATE_COMMAND_NAME = "update_access_group"
DEACTIVATE_COMMAND_NAME = "deactivate_access_group"
REACTIVATE_COMMAND_NAME = "reactivate_access_group"
ADD_COMMAND_NAME = "add_access_group_member"
REMOVE_COMMAND_NAME = "remove_access_group_member"

ag = access_groups
agm = access_group_memberships
cm = campaign_memberships
rg = resource_grants
cr = character_revelations

#: `end_reason` of a revelation closed by a group's deactivation (as the legacy command wrote it).
END_REASON_GROUP_DEACTIVATED = "access_group_deactivated"
#: The audit samples of a deactivation: the first 20 ids in ascending order (B-2).
DEACTIVATE_AUDIT_ID_SAMPLE_LIMIT = 20


class AccessGroupCascadeIncompleteError(RuntimeError):
    """H-1: the group's open dependents (links, grants, revelations) differ from the keys the route's own `plan.lock` calls
    returned, so a dependent lock call was omitted or narrowed. A direct `RuntimeError`: a fixed 5xx, a full rollback, the
    key reusable. Carries no identifier."""

    def __init__(self) -> None:
        super().__init__("an access group's dependents changed or were not all locked")


class AccessGroupMembersNotLockedError(RuntimeError):
    """The add's member locks did not return exactly the requested ids although every member was found. An internal
    error (a fixed 5xx), never a client refusal."""

    def __init__(self) -> None:
        super().__init__("the requested access group members were not all locked")


# -- trigger pins of the group table ---------------------------------------------------------------------

GROUP_TRIGGERS = frozenset(
    {
        _pin(
            "tr_access_groups_enforce_immutable",
            *_IMMUTABLE,
            events=frozenset({Event.UPDATE}),
            args=("campaign_id",),
        ),
        _pin("tr_access_groups_set_updated_at", *_UPDATED_AT, events=frozenset({Event.UPDATE})),
    }
)

# -- locks ---------------------------------------------------------------------------------------------

#: The group, `FOR UPDATE`, bound `group` and `campaign`: a group of another campaign matches nothing (the 404).
GROUP_LOCK = PreLock(
    "access_group_update",
    select(ag.c.access_group_id)
    .where(ag.c.access_group_id == bindparam("group"))
    .where(ag.c.campaign_id == bindparam("campaign"))
    .with_for_update(),
)
#: The same row again, `FOR UPDATE`, **only while active** (bound `group`, `campaign`, `status` = the active status id). Already
#: held: no wait, no order change. Its evidence is the database's own answer, under the lock, to "this request archives".
GROUP_ACTIVE_LOCK = PreLock(
    "access_group_active_row",
    select(ag.c.access_group_id)
    .where(ag.c.access_group_id == bindparam("group"))
    .where(ag.c.campaign_id == bindparam("campaign"))
    .where(ag.c.lifecycle_status_id == bindparam("status"))
    .with_for_update(),
)
#: The same row again, `FOR UPDATE`, **only while archived** ("this request reactivates").
GROUP_ARCHIVED_LOCK = PreLock(
    "access_group_archived_row",
    select(ag.c.access_group_id)
    .where(ag.c.access_group_id == bindparam("group"))
    .where(ag.c.campaign_id == bindparam("campaign"))
    .where(ag.c.lifecycle_status_id == bindparam("status"))
    .with_for_update(),
)
#: The group's open links, `FOR UPDATE`, ascending (bound `group`).
GROUP_OPEN_LINKS = PreLock(
    "group_open_links",
    select(agm.c.access_group_membership_id)
    .where(agm.c.access_group_id == bindparam("group"))
    .where(agm.c.removed_at.is_(None))
    .order_by(agm.c.access_group_membership_id)
    .with_for_update(),
)
#: The group's unrevoked grants, `FOR UPDATE`, ascending (bound `group`).
GROUP_ACTIVE_GRANTS = PreLock(
    "group_active_grants",
    select(rg.c.resource_grant_id)
    .where(rg.c.grantee_access_group_id == bindparam("group"))
    .where(rg.c.revoked_at.is_(None))
    .order_by(rg.c.resource_grant_id)
    .with_for_update(),
)
#: The group's live revelations, `FOR UPDATE`, ascending (bound `group`).
GROUP_LIVE_REVELATIONS = PreLock(
    "group_live_revelations",
    select(cr.c.character_revelation_id)
    .where(cr.c.target_access_group_id == bindparam("group"))
    .where(cr.c.ended_at.is_(None))
    .order_by(cr.c.character_revelation_id)
    .with_for_update(),
)
#: One link, `FOR UPDATE`, **only while open** (bound `link`).
LINK_OPEN_LOCK = PreLock(
    "group_link_open_row",
    select(agm.c.access_group_membership_id)
    .where(agm.c.access_group_membership_id == bindparam("link"))
    .where(agm.c.removed_at.is_(None))
    .with_for_update(),
)
#: A member's campaign membership, `FOR NO KEY UPDATE` (bound `member`, `campaign`), one call per requested id. The row is
#: locked **without** a join to the status table (a locking statement joined to it that waited behind a status change is
#: re-checked against the old status row and returns no row, which would turn an end that raced the add into a 404).
MEMBER_LOCK = PreLock(
    "group_member_no_key_update",
    select(cm.c.campaign_membership_id)
    .where(cm.c.campaign_membership_id == bindparam("member"))
    .where(cm.c.campaign_id == bindparam("campaign"))
    .with_for_update(key_share=True),
)
#: A member's account, `FOR KEY SHARE` (S5-A; bound `member_user`).
MEMBER_ACCOUNT_LOCK = PreLock(
    "group_member_account_key_share",
    select(users.c.user_id)
    .where(users.c.user_id == bindparam("member_user"))
    .with_for_update(read=True, key_share=True),
)

# -- steps ---------------------------------------------------------------------------------------------

_NOW = func.pg_catalog.now
_CLOCK = func.pg_catalog.clock_timestamp

_NAME_INDEX_TEST = (
    "tests/database/test_r01_s5e5_group_routes.py::test_a_competing_group_name_is_a_unique_wait"
)
_LINK_INDEX_TEST = (
    "tests/database/test_r01_s5e5_group_routes.py::test_a_competing_open_link_is_a_unique_wait"
)
_LEAVES_INDEX_TEST = (
    "tests/database/test_r01_s5e3_end_membership.py::"
    "test_an_update_leaving_a_partial_unique_index_never_waits_for_a_competing_insert"
)
_LEAVES_GRANT_TEST = (
    "tests/database/test_r01_s5e4_access_grants.py::"
    "test_an_update_leaving_a_partial_unique_index_never_waits_for_a_competing_insert"
)
_NAME_WAIT = frozenset({UniqueWait("security.ux_access_groups_campaign_name", _NAME_INDEX_TEST)})
_LINK_WAIT = frozenset({UniqueWait("security.ux_access_group_memberships_open", _LINK_INDEX_TEST)})
_LEAVES_LINK_INDEX = frozenset(
    {UniqueWait("security.ux_access_group_memberships_open", _LEAVES_INDEX_TEST)}
)
_LEAVES_GRANT_INDEX = frozenset(
    {UniqueWait("security.ux_resource_grants_active", _LEAVES_GRANT_TEST)}
)
_LEAVES_REVELATION_INDEX = frozenset(
    {UniqueWait("security.ux_character_revelations_live", _LEAVES_INDEX_TEST)}
)


def _fk(table: Any, column: str, bind: str, lock: PreLock | None) -> FkBinding:
    return FkBinding(fk_of(table, column), (KeyBind(table.c[column], bind),), lock)


INSERT_GROUP = WriteStep(
    name="insert_access_group",
    statement=insert(ag)
    .values(
        campaign_id=bindparam("campaign"),
        name=bindparam("name"),
        description=bindparam("description"),
        lifecycle_status_id=bindparam("status"),
    )
    .returning(ag.c.access_group_id),
    cardinality=Exactly(1),
    fks=(
        _fk(ag, "campaign_id", "campaign", CAMPAIGN_KEY_SHARE_LOCK),
        _fk(ag, "lifecycle_status_id", "status", None),
    ),
    value_binds=frozenset({"name", "description"}),
    unique_waits=_NAME_WAIT,
)
UPDATE_GROUP = WriteStep(
    name="update_access_group",
    statement=update(ag)
    .where(ag.c.access_group_id == bindparam("target"))
    .values(name=bindparam("name"), description=bindparam("description"))
    .returning(ag.c.access_group_id),
    cardinality=Exactly(1),
    target=(KeyBind(ag.c.access_group_id, "target"),),
    target_lock=GROUP_LOCK,
    value_binds=frozenset({"name", "description"}),
    unique_waits=_NAME_WAIT,
    triggers=GROUP_TRIGGERS,
)
ARCHIVE_GROUP = WriteStep(
    name="archive_access_group",
    statement=update(ag)
    .where(ag.c.access_group_id == bindparam("target"))
    .values(lifecycle_status_id=bindparam("status"))
    .returning(ag.c.access_group_id),
    cardinality=EachLockedRow(complete=True),
    target=(KeyBind(ag.c.access_group_id, "target"),),
    target_lock=GROUP_ACTIVE_LOCK,
    fks=(_fk(ag, "lifecycle_status_id", "status", None),),
    triggers=GROUP_TRIGGERS,
)
REACTIVATE_GROUP = WriteStep(
    name="reactivate_access_group",
    statement=update(ag)
    .where(ag.c.access_group_id == bindparam("target"))
    .values(lifecycle_status_id=bindparam("status"))
    .returning(ag.c.access_group_id),
    cardinality=EachLockedRow(complete=True),
    target=(KeyBind(ag.c.access_group_id, "target"),),
    target_lock=GROUP_ARCHIVED_LOCK,
    fks=(_fk(ag, "lifecycle_status_id", "status", None),),
    triggers=GROUP_TRIGGERS,
)
CLOSE_GROUP_LINKS = WriteStep(
    name="close_group_links",
    statement=update(agm)
    .where(agm.c.access_group_membership_id == bindparam("target"))
    .values(removed_at=_NOW())
    .returning(agm.c.access_group_membership_id),
    cardinality=EachLockedRow(complete=True),
    target=(KeyBind(agm.c.access_group_membership_id, "target"),),
    target_lock=GROUP_OPEN_LINKS,
    unique_waits=_LEAVES_LINK_INDEX,
    triggers=GROUP_MEMBERSHIP_TRIGGERS,
)
#: B-5: the grant's own `granted_at` is the floor (the legacy `now()` was not).
REVOKE_GROUP_GRANTS = WriteStep(
    name="revoke_group_grants",
    statement=update(rg)
    .where(rg.c.resource_grant_id == bindparam("target"))
    .values(revoked_at=func.greatest(_CLOCK(), rg.c.granted_at))
    .returning(rg.c.resource_grant_id),
    cardinality=EachLockedRow(complete=True),
    target=(KeyBind(rg.c.resource_grant_id, "target"),),
    target_lock=GROUP_ACTIVE_GRANTS,
    unique_waits=_LEAVES_GRANT_INDEX,
    triggers=GRANT_TRIGGERS,
)
#: I-3: the legacy clamp `GREATEST(clock_timestamp(), created_at)`, preserved exactly.
CLOSE_GROUP_REVELATIONS = WriteStep(
    name="close_group_revelations",
    statement=update(cr)
    .where(cr.c.character_revelation_id == bindparam("target"))
    .values(
        ended_at=func.greatest(_CLOCK(), cr.c.created_at), end_reason=END_REASON_GROUP_DEACTIVATED
    )
    .returning(cr.c.character_revelation_id),
    cardinality=EachLockedRow(complete=True),
    target=(KeyBind(cr.c.character_revelation_id, "target"),),
    target_lock=GROUP_LIVE_REVELATIONS,
    unique_waits=_LEAVES_REVELATION_INDEX,
    triggers=REVELATION_TRIGGERS,
)
_LINK_MEMBER_FK = _fk(agm, "campaign_membership_id", "member", MEMBER_LOCK)
INSERT_LINK = WriteStep(
    name="insert_group_link",
    statement=insert(agm)
    .values(
        access_group_id=bindparam("group"),
        campaign_membership_id=bindparam("member"),
        added_by_membership_id=bindparam("added_by"),
    )
    .returning(agm.c.access_group_membership_id),
    cardinality=PerEvidenceRow(MEMBER_LOCK, _LINK_MEMBER_FK),
    fks=(
        _fk(agm, "access_group_id", "group", GROUP_LOCK),
        _LINK_MEMBER_FK,
        _fk(agm, "added_by_membership_id", "added_by", ACTOR_MEMBERSHIP_LOCK),
    ),
    unique_waits=_LINK_WAIT,
    triggers=GROUP_MEMBERSHIP_TRIGGERS,
)
REMOVE_LINK = WriteStep(
    name="remove_group_link",
    statement=update(agm)
    .where(agm.c.access_group_membership_id == bindparam("target"))
    .values(removed_at=_NOW())
    .returning(agm.c.access_group_membership_id),
    cardinality=EachLockedRow(complete=True),
    target=(KeyBind(agm.c.access_group_membership_id, "target"),),
    target_lock=LINK_OPEN_LOCK,
    unique_waits=_LEAVES_LINK_INDEX,
    triggers=GROUP_MEMBERSHIP_TRIGGERS,
)

CREATE_AUDIT = WriteStep(
    name="audit_group_created",
    statement=insert(change_log)
    .values(
        **_audit_values("access_groups", CREATE_COMMAND_NAME),
        changed_fields=bindparam("changed"),
    )
    .returning(change_log.c.change_log_id),
    cardinality=Exactly(1),
    fks=(CHANGE_LOG_ACTION_FK, CHANGE_LOG_ACTOR_FK),
    value_binds=_AUDIT_BINDS | {"changed"},
)
UPDATE_AUDIT = WriteStep(
    name="audit_group_updated",
    statement=insert(change_log)
    .values(
        **_audit_values("access_groups", UPDATE_COMMAND_NAME),
        previous_status=bindparam("previous_status"),
        new_status=bindparam("new_status"),
        changed_fields=bindparam("changed"),
    )
    .returning(change_log.c.change_log_id),
    cardinality=Exactly(1),
    fks=(CHANGE_LOG_ACTION_FK, CHANGE_LOG_ACTOR_FK),
    value_binds=_AUDIT_BINDS | {"previous_status", "new_status", "changed"},
)
DEACTIVATE_AUDIT = WriteStep(
    name="audit_group_deactivated",
    statement=insert(change_log)
    .values(
        **_audit_values("access_groups", DEACTIVATE_COMMAND_NAME),
        previous_status="active",
        new_status="archived",
        changed_fields=bindparam("changed"),
    )
    .returning(change_log.c.change_log_id),
    cardinality=PerEvidence(GROUP_ACTIVE_LOCK),
    fks=(CHANGE_LOG_ACTION_FK, CHANGE_LOG_ACTOR_FK),
    value_binds=_AUDIT_BINDS | {"changed"},
)
REACTIVATE_AUDIT = WriteStep(
    name="audit_group_reactivated",
    statement=insert(change_log)
    .values(
        **_audit_values("access_groups", REACTIVATE_COMMAND_NAME),
        previous_status="archived",
        new_status="active",
    )
    .returning(change_log.c.change_log_id),
    cardinality=PerEvidence(GROUP_ARCHIVED_LOCK),
    fks=(CHANGE_LOG_ACTION_FK, CHANGE_LOG_ACTOR_FK),
    value_binds=_AUDIT_BINDS,
)
LINK_AUDIT = WriteStep(
    name="audit_group_link_created",
    statement=insert(change_log)
    .values(
        **_audit_values("access_group_memberships", ADD_COMMAND_NAME),
        changed_fields=bindparam("changed"),
    )
    .returning(change_log.c.change_log_id),
    cardinality=PerConfirmedRow(INSERT_LINK, "record"),
    fks=(CHANGE_LOG_ACTION_FK, CHANGE_LOG_ACTOR_FK),
    value_binds=_AUDIT_BINDS | {"changed"},
)
REMOVE_AUDIT = WriteStep(
    name="audit_group_link_removed",
    statement=insert(change_log)
    .values(
        **_audit_values("access_group_memberships", REMOVE_COMMAND_NAME),
        changed_fields=bindparam("changed"),
    )
    .returning(change_log.c.change_log_id),
    cardinality=PerEvidence(LINK_OPEN_LOCK),
    fks=(CHANGE_LOG_ACTION_FK, CHANGE_LOG_ACTOR_FK),
    value_binds=_AUDIT_BINDS | {"changed"},
)
GROUP_RECEIPT = RECEIPT_STEP

# -- declarations ----------------------------------------------------------------------------------------

_UNLOCKED = CHANGE_LOG_UNLOCKED_FK_TARGETS | {lifecycle_statuses}


_CREATE_LOCKS = (
    ACTOR_ROLES_LOCK,
    ACTOR_MEMBERSHIP_LOCK,
    ACTOR_ACCOUNT_LOCK,
    CAMPAIGN_KEY_SHARE_LOCK,
)
_CREATE_STEPS = (INSERT_GROUP, CREATE_AUDIT)
CREATE_DECLARATIONS = ReservationDeclarations(
    reserved=PreWriteDeclaration(
        locks=(*_CREATE_LOCKS, RECEIPT_LOCK),
        steps=(*_CREATE_STEPS, GROUP_RECEIPT),
        unlocked_fk_targets=_UNLOCKED,
    ),
    unkeyed=PreWriteDeclaration(
        locks=_CREATE_LOCKS, steps=_CREATE_STEPS, unlocked_fk_targets=_UNLOCKED
    ),
)
_UPDATE_LOCKS = (
    ACTOR_ROLES_LOCK,
    GROUP_LOCK,
    ACTOR_MEMBERSHIP_LOCK,
    ACTOR_ACCOUNT_LOCK,
    CAMPAIGN_KEY_SHARE_LOCK,
)
_UPDATE_STEPS = (UPDATE_GROUP, UPDATE_AUDIT)
UPDATE_DECLARATIONS = ReservationDeclarations(
    reserved=PreWriteDeclaration(
        locks=(*_UPDATE_LOCKS, RECEIPT_LOCK),
        steps=(*_UPDATE_STEPS, GROUP_RECEIPT),
        unlocked_fk_targets=_UNLOCKED,
    ),
    unkeyed=PreWriteDeclaration(
        locks=_UPDATE_LOCKS, steps=_UPDATE_STEPS, unlocked_fk_targets=_UNLOCKED
    ),
)
_DEACTIVATE_LOCKS = (
    ACTOR_ROLES_LOCK,
    GROUP_LOCK,
    GROUP_ACTIVE_LOCK,
    ACTOR_MEMBERSHIP_LOCK,
    ACTOR_ACCOUNT_LOCK,
    CAMPAIGN_KEY_SHARE_LOCK,
    GROUP_OPEN_LINKS,
    GROUP_ACTIVE_GRANTS,
    GROUP_LIVE_REVELATIONS,
)
_DEACTIVATE_STEPS = (
    ARCHIVE_GROUP,
    CLOSE_GROUP_LINKS,
    REVOKE_GROUP_GRANTS,
    CLOSE_GROUP_REVELATIONS,
    DEACTIVATE_AUDIT,
)
DEACTIVATE_DECLARATIONS = ReservationDeclarations(
    reserved=PreWriteDeclaration(
        locks=(*_DEACTIVATE_LOCKS, RECEIPT_LOCK),
        steps=(*_DEACTIVATE_STEPS, GROUP_RECEIPT),
        unlocked_fk_targets=_UNLOCKED,
    ),
    unkeyed=PreWriteDeclaration(
        locks=_DEACTIVATE_LOCKS, steps=_DEACTIVATE_STEPS, unlocked_fk_targets=_UNLOCKED
    ),
)
_REACTIVATE_LOCKS = (
    ACTOR_ROLES_LOCK,
    GROUP_LOCK,
    GROUP_ARCHIVED_LOCK,
    ACTOR_MEMBERSHIP_LOCK,
    ACTOR_ACCOUNT_LOCK,
    CAMPAIGN_KEY_SHARE_LOCK,
)
_REACTIVATE_STEPS = (REACTIVATE_GROUP, REACTIVATE_AUDIT)
REACTIVATE_DECLARATIONS = ReservationDeclarations(
    reserved=PreWriteDeclaration(
        locks=(*_REACTIVATE_LOCKS, RECEIPT_LOCK),
        steps=(*_REACTIVATE_STEPS, GROUP_RECEIPT),
        unlocked_fk_targets=_UNLOCKED,
    ),
    unkeyed=PreWriteDeclaration(
        locks=_REACTIVATE_LOCKS, steps=_REACTIVATE_STEPS, unlocked_fk_targets=_UNLOCKED
    ),
)
_ADD_LOCKS = (
    ACTOR_ROLES_LOCK,
    GROUP_LOCK,
    MEMBER_LOCK,
    ACTOR_MEMBERSHIP_LOCK,
    ACTOR_ACCOUNT_LOCK,
    MEMBER_ACCOUNT_LOCK,
    CAMPAIGN_KEY_SHARE_LOCK,
)
_ADD_STEPS = (INSERT_LINK, LINK_AUDIT)
ADD_DECLARATIONS = ReservationDeclarations(
    reserved=PreWriteDeclaration(
        locks=(*_ADD_LOCKS, RECEIPT_LOCK),
        steps=(*_ADD_STEPS, GROUP_RECEIPT),
        unlocked_fk_targets=_UNLOCKED,
    ),
    unkeyed=PreWriteDeclaration(locks=_ADD_LOCKS, steps=_ADD_STEPS, unlocked_fk_targets=_UNLOCKED),
)
_REMOVE_LOCKS = (
    ACTOR_ROLES_LOCK,
    ACTOR_MEMBERSHIP_LOCK,
    ACTOR_ACCOUNT_LOCK,
    CAMPAIGN_KEY_SHARE_LOCK,
    LINK_OPEN_LOCK,
)
_REMOVE_STEPS = (REMOVE_LINK, REMOVE_AUDIT)
REMOVE_DECLARATIONS = ReservationDeclarations(
    reserved=PreWriteDeclaration(
        locks=(*_REMOVE_LOCKS, RECEIPT_LOCK),
        steps=(*_REMOVE_STEPS, GROUP_RECEIPT),
        unlocked_fk_targets=_UNLOCKED,
    ),
    unkeyed=PreWriteDeclaration(
        locks=_REMOVE_LOCKS, steps=_REMOVE_STEPS, unlocked_fk_targets=_UNLOCKED
    ),
)

# -- shared reads ----------------------------------------------------------------------------------------

_CAMPAIGN_STATUS = text(
    "SELECT ls.code FROM campaign.campaigns c "
    "JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = c.lifecycle_status_id "
    "WHERE c.campaign_id = :c"
)
_ACCOUNT_STATUS = text(
    "SELECT ls.code FROM security.users u "
    "JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = u.lifecycle_status_id "
    "WHERE u.user_id = :u"
)
_GROUP_ROW = text(
    "SELECT ag.campaign_id, ag.name, ag.description, ls.code AS lifecycle_status_code "
    "FROM security.access_groups ag "
    "JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = ag.lifecycle_status_id "
    "WHERE ag.access_group_id = :g"
)
_MEMBER_ROWS = text(
    "SELECT campaign_membership_id, campaign_id, ended_at, user_id, membership_status_id "
    "FROM security.campaign_memberships WHERE campaign_membership_id IN :ids"
).bindparams(bindparam("ids", expanding=True))
_MEMBER_STATUS = text(
    "SELECT code, is_active FROM security.membership_statuses WHERE membership_status_id = :status"
)
_OPEN_LINKS = text(
    "SELECT access_group_membership_id FROM security.access_group_memberships "
    "WHERE access_group_id = :g AND removed_at IS NULL"
)
_ACTIVE_GRANTS = text(
    "SELECT resource_grant_id FROM security.resource_grants "
    "WHERE grantee_access_group_id = :g AND revoked_at IS NULL"
)
_LIVE_REVELATIONS = text(
    "SELECT character_revelation_id FROM security.character_revelations "
    "WHERE target_access_group_id = :g AND ended_at IS NULL"
)
_LINK_DISCOVERY = text(
    "SELECT ag.campaign_id, agm.access_group_id, agm.campaign_membership_id "
    "FROM security.access_group_memberships agm "
    "JOIN security.access_groups ag ON ag.access_group_id = agm.access_group_id "
    "WHERE agm.access_group_membership_id = :link"
)
_LINK_REMOVED = text(
    "SELECT removed_at FROM security.access_group_memberships "
    "WHERE access_group_membership_id = :link"
)


def _normalize(name: str, description: str | None) -> tuple[str, str | None]:
    """The legacy normalization and its refusals, in the legacy order (422 each)."""
    normalized_name = name.strip()
    if not normalized_name:
        raise BlankAccessGroupNameError("access group name must not be blank")
    if len(normalized_name) > ACCESS_GROUP_NAME_MAX_LENGTH:
        raise AccessGroupNameTooLongError("access group name exceeds the maximum length")
    normalized_description = (description.strip() if description else None) or None
    if (
        normalized_description is not None
        and len(normalized_description) > ACCESS_GROUP_DESCRIPTION_MAX_LENGTH
    ):
        raise AccessGroupDescriptionTooLongError(
            "access group description exceeds the maximum length"
        )
    return normalized_name, normalized_description


def _require_campaign_active(connection: Connection, campaign_id: uuid.UUID) -> None:
    if connection.execute(_CAMPAIGN_STATUS, {"c": campaign_id}).scalar() != "active":
        raise CampaignNotActiveError(f"campaign {campaign_id} is not currently active")


def _lock_group(
    connection: Connection,
    plan: AuthorizationPlan,
    *,
    campaign_id: uuid.UUID,
    group_id: uuid.UUID,
    actor_membership_id: uuid.UUID,
) -> None:
    """AO-1: the actor's role rows S, then the group U. A group of another campaign matches nothing: the 404, raised
    right here (nothing else is worth locking for a request that will be refused)."""
    plan.lock(connection, ACTOR_ROLES_LOCK, {"membership": actor_membership_id})
    keys = plan.lock(connection, GROUP_LOCK, {"group": group_id, "campaign": campaign_id})
    if not keys:
        row = connection.execute(_GROUP_ROW, {"g": group_id}).mappings().one_or_none()
        raise AccessGroupNotInCampaignError(
            f"access group {group_id} does not belong to campaign {campaign_id} "
            f"(actual campaign: {row['campaign_id'] if row is not None else None})"
        )


def _lock_actor_after_group(
    connection: Connection,
    plan: AuthorizationPlan,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    actor_membership_id: uuid.UUID,
) -> None:
    plan.lock(
        connection,
        ACTOR_MEMBERSHIP_LOCK,
        {"membership": actor_membership_id, "campaign": campaign_id},
    )
    plan.lock(connection, ACTOR_ACCOUNT_LOCK, {"actor": actor_user_id})


def _group_name(connection: Connection, group_id: uuid.UUID) -> str:
    name = connection.execute(
        text("SELECT name FROM security.access_groups WHERE access_group_id = :g"), {"g": group_id}
    ).scalar()
    return str(name) if name is not None else ""


def _audit_binds(
    prepared: "GroupPrepared",
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


def _sample(ids: tuple[uuid.UUID, ...]) -> dict[str, Any]:
    """B-2: an exact count and the first 20 ids in ascending order."""
    sample = ids[:DEACTIVATE_AUDIT_ID_SAMPLE_LIMIT]
    return {
        "count": len(ids),
        "sample_ids": [str(item) for item in sample],
        "sample_truncated": len(ids) > len(sample),
    }


@dataclass(frozen=True)
class GroupPrepared:
    """What the lock and read phase established, all before `finalize`."""

    world_id: uuid.UUID
    action_id: uuid.UUID
    #: the response label (the group's name, normalized for create/update)
    name: str = ""
    will_write: bool = True
    status_id: uuid.UUID | None = None
    description: str | None = None
    previous_name: str | None = None
    #: add: the requested members, ascending
    member_ids: tuple[uuid.UUID, ...] = ()
    #: deactivate: the locked dependents, ascending
    link_ids: tuple[uuid.UUID, ...] = ()
    grant_ids: tuple[uuid.UUID, ...] = ()
    revelation_ids: tuple[uuid.UUID, ...] = ()
    #: remove: the link's own group and member
    group_id: uuid.UUID | None = None
    member_id: uuid.UUID | None = None


def _ascending(keys: tuple[tuple[Any, ...], ...]) -> tuple[uuid.UUID, ...]:
    return tuple(sorted((key[0] for key in keys), key=lambda value: value.int))


# =====================================================================================================
# create
# =====================================================================================================


def prepare_create_group(
    connection: Connection,
    plan: AuthorizationPlan,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    actor_membership_id: uuid.UUID,
    name: str,
    description: str | None,
    reservation_id: uuid.UUID | None,
) -> GroupPrepared:
    normalized_name, normalized_description = _normalize(name, description)
    _lock_actor(
        connection,
        plan,
        campaign_id=campaign_id,
        actor_user_id=actor_user_id,
        actor_membership_id=actor_membership_id,
    )
    plan.lock(connection, CAMPAIGN_KEY_SHARE_LOCK, {"campaign": campaign_id})
    if reservation_id is not None:
        plan.lock(connection, RECEIPT_LOCK, {"receipt": reservation_id})
    _require_campaign_active(connection, campaign_id)
    return GroupPrepared(
        world_id=_scope_world(connection, campaign_id),
        action_id=lookup_id(connection, "audit", "change_actions", "change_action_id", "created"),
        name=normalized_name,
        description=normalized_description,
        status_id=lookup_id(
            connection, "core", "lifecycle_statuses", "lifecycle_status_id", "active"
        ),
    )


def write_create_group(
    connection: Connection,
    plan: AuthorizationPlan,
    prepared: GroupPrepared,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    correlation_id: str | None,
) -> uuid.UUID:
    created = plan.execute(
        connection,
        INSERT_GROUP,
        {
            "campaign": campaign_id,
            "name": prepared.name,
            "description": prepared.description,
            "status": prepared.status_id,
        },
    )
    new_id = created.keys[0][0]
    assert isinstance(new_id, uuid.UUID)
    plan.execute(
        connection,
        CREATE_AUDIT,
        {
            **_audit_binds(
                prepared, record=new_id, actor_user_id=actor_user_id, correlation_id=correlation_id
            ),
            "changed": {"name": prepared.name, "description": prepared.description},
        },
    )
    return new_id


# =====================================================================================================
# update
# =====================================================================================================


def prepare_update_group(
    connection: Connection,
    plan: AuthorizationPlan,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    actor_membership_id: uuid.UUID,
    group_id: uuid.UUID,
    name: str,
    description: str | None,
    reservation_id: uuid.UUID | None,
) -> GroupPrepared:
    _lock_group(
        connection,
        plan,
        campaign_id=campaign_id,
        group_id=group_id,
        actor_membership_id=actor_membership_id,
    )
    _lock_actor_after_group(
        connection,
        plan,
        campaign_id=campaign_id,
        actor_user_id=actor_user_id,
        actor_membership_id=actor_membership_id,
    )
    plan.lock(connection, CAMPAIGN_KEY_SHARE_LOCK, {"campaign": campaign_id})
    if reservation_id is not None:
        plan.lock(connection, RECEIPT_LOCK, {"receipt": reservation_id})
    row = connection.execute(_GROUP_ROW, {"g": group_id}).mappings().one()
    if row["lifecycle_status_code"] != "active":
        raise AccessGroupNotActiveError(f"access group {group_id} is not currently active")
    normalized_name, normalized_description = _normalize(name, description)
    if normalized_name == row["name"] and normalized_description == row["description"]:
        raise AccessGroupUpdateNoOpError(
            "the requested name/description already match this group's current values"
        )
    return GroupPrepared(
        world_id=_scope_world(connection, campaign_id),
        action_id=lookup_id(connection, "audit", "change_actions", "change_action_id", "updated"),
        name=normalized_name,
        description=normalized_description,
        previous_name=row["name"],
    )


def write_update_group(
    connection: Connection,
    plan: AuthorizationPlan,
    prepared: GroupPrepared,
    *,
    group_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    correlation_id: str | None,
) -> None:
    plan.execute(
        connection,
        UPDATE_GROUP,
        {"target": group_id, "name": prepared.name, "description": prepared.description},
    )
    plan.execute(
        connection,
        UPDATE_AUDIT,
        {
            **_audit_binds(
                prepared,
                record=group_id,
                actor_user_id=actor_user_id,
                correlation_id=correlation_id,
            ),
            "previous_status": prepared.previous_name,
            "new_status": prepared.name,
            "changed": {"description": prepared.description},
        },
    )


# =====================================================================================================
# deactivate
# =====================================================================================================


def _check_cascade_complete(
    connection: Connection,
    group_id: uuid.UUID,
    *,
    links: tuple[uuid.UUID, ...],
    grants: tuple[uuid.UUID, ...],
    revelations: tuple[uuid.UUID, ...],
) -> None:
    """H-1 (module docstring): the group's open dependents, read without locks, equal the keys the route's own lock calls
    returned. Route code: it detects an omitted or narrowed lock call while this check remains."""
    for query, received in (
        (_OPEN_LINKS, links),
        (_ACTIVE_GRANTS, grants),
        (_LIVE_REVELATIONS, revelations),
    ):
        actual = set(connection.execute(query, {"g": group_id}).scalars().all())
        if actual != set(received):
            raise AccessGroupCascadeIncompleteError()


def prepare_deactivate_group(
    connection: Connection,
    plan: AuthorizationPlan,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    actor_membership_id: uuid.UUID,
    group_id: uuid.UUID,
    reservation_id: uuid.UUID | None,
) -> GroupPrepared:
    active_id = lookup_id(connection, "core", "lifecycle_statuses", "lifecycle_status_id", "active")
    archived_id = lookup_id(
        connection, "core", "lifecycle_statuses", "lifecycle_status_id", "archived"
    )
    _lock_group(
        connection,
        plan,
        campaign_id=campaign_id,
        group_id=group_id,
        actor_membership_id=actor_membership_id,
    )
    active_keys = plan.lock(
        connection,
        GROUP_ACTIVE_LOCK,
        {"group": group_id, "campaign": campaign_id, "status": active_id},
    )
    _lock_actor_after_group(
        connection,
        plan,
        campaign_id=campaign_id,
        actor_user_id=actor_user_id,
        actor_membership_id=actor_membership_id,
    )
    plan.lock(connection, CAMPAIGN_KEY_SHARE_LOCK, {"campaign": campaign_id})
    links: tuple[uuid.UUID, ...] = ()
    grants: tuple[uuid.UUID, ...] = ()
    revelations: tuple[uuid.UUID, ...] = ()
    if active_keys:
        links = _ascending(plan.lock(connection, GROUP_OPEN_LINKS, {"group": group_id}))
        grants = _ascending(plan.lock(connection, GROUP_ACTIVE_GRANTS, {"group": group_id}))
        revelations = _ascending(plan.lock(connection, GROUP_LIVE_REVELATIONS, {"group": group_id}))
    if reservation_id is not None:
        plan.lock(connection, RECEIPT_LOCK, {"receipt": reservation_id})
    row = connection.execute(_GROUP_ROW, {"g": group_id}).mappings().one()
    will_archive = bool(active_keys)
    if will_archive != (row["lifecycle_status_code"] == "active"):
        raise RuntimeError("the access group changed under its own lock")
    if will_archive:
        _check_cascade_complete(
            connection, group_id, links=links, grants=grants, revelations=revelations
        )
    return GroupPrepared(
        world_id=_scope_world(connection, campaign_id),
        action_id=lookup_id(connection, "audit", "change_actions", "change_action_id", "updated"),
        name=str(row["name"]),
        will_write=will_archive,
        status_id=archived_id,
        link_ids=links,
        grant_ids=grants,
        revelation_ids=revelations,
    )


def write_deactivate_group(
    connection: Connection,
    plan: AuthorizationPlan,
    prepared: GroupPrepared,
    *,
    group_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    correlation_id: str | None,
) -> None:
    """The declared archive, the dependents' closes and the audit row (attempted only by a genuine deactivation)."""
    if not prepared.will_write:
        return
    plan.execute(connection, ARCHIVE_GROUP, {"target": group_id, "status": prepared.status_id})
    for link_id in prepared.link_ids:
        plan.execute(connection, CLOSE_GROUP_LINKS, {"target": link_id})
    for grant_id in prepared.grant_ids:
        plan.execute(connection, REVOKE_GROUP_GRANTS, {"target": grant_id})
    for revelation_id in prepared.revelation_ids:
        plan.execute(connection, CLOSE_GROUP_REVELATIONS, {"target": revelation_id})
    plan.execute(
        connection,
        DEACTIVATE_AUDIT,
        {
            **_audit_binds(
                prepared,
                record=group_id,
                actor_user_id=actor_user_id,
                correlation_id=correlation_id,
            ),
            "changed": {
                "removed_access_group_memberships": _sample(prepared.link_ids),
                "revoked_resource_grants": _sample(prepared.grant_ids),
                "closed_character_revelations": _sample(prepared.revelation_ids),
            },
        },
    )


# =====================================================================================================
# reactivate
# =====================================================================================================


def prepare_reactivate_group(
    connection: Connection,
    plan: AuthorizationPlan,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    actor_membership_id: uuid.UUID,
    group_id: uuid.UUID,
    reservation_id: uuid.UUID | None,
) -> GroupPrepared:
    active_id = lookup_id(connection, "core", "lifecycle_statuses", "lifecycle_status_id", "active")
    archived_id = lookup_id(
        connection, "core", "lifecycle_statuses", "lifecycle_status_id", "archived"
    )
    _lock_group(
        connection,
        plan,
        campaign_id=campaign_id,
        group_id=group_id,
        actor_membership_id=actor_membership_id,
    )
    archived_keys = plan.lock(
        connection,
        GROUP_ARCHIVED_LOCK,
        {"group": group_id, "campaign": campaign_id, "status": archived_id},
    )
    _lock_actor_after_group(
        connection,
        plan,
        campaign_id=campaign_id,
        actor_user_id=actor_user_id,
        actor_membership_id=actor_membership_id,
    )
    plan.lock(connection, CAMPAIGN_KEY_SHARE_LOCK, {"campaign": campaign_id})
    if reservation_id is not None:
        plan.lock(connection, RECEIPT_LOCK, {"receipt": reservation_id})
    row = connection.execute(_GROUP_ROW, {"g": group_id}).mappings().one()
    will_reactivate = bool(archived_keys)
    if will_reactivate != (row["lifecycle_status_code"] != "active"):
        raise RuntimeError("the access group changed under its own lock")
    if will_reactivate:
        _require_campaign_active(connection, campaign_id)
    return GroupPrepared(
        world_id=_scope_world(connection, campaign_id),
        action_id=lookup_id(connection, "audit", "change_actions", "change_action_id", "updated"),
        name=str(row["name"]),
        will_write=will_reactivate,
        status_id=active_id,
    )


def write_reactivate_group(
    connection: Connection,
    plan: AuthorizationPlan,
    prepared: GroupPrepared,
    *,
    group_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    correlation_id: str | None,
) -> None:
    if not prepared.will_write:
        return
    plan.execute(connection, REACTIVATE_GROUP, {"target": group_id, "status": prepared.status_id})
    plan.execute(
        connection,
        REACTIVATE_AUDIT,
        _audit_binds(
            prepared, record=group_id, actor_user_id=actor_user_id, correlation_id=correlation_id
        ),
    )


# =====================================================================================================
# add members
# =====================================================================================================


def prepare_add_members(
    connection: Connection,
    plan: AuthorizationPlan,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    actor_membership_id: uuid.UUID,
    group_id: uuid.UUID,
    member_ids: tuple[uuid.UUID, ...],
    reservation_id: uuid.UUID | None,
) -> GroupPrepared:
    """`member_ids` is the request's deduplicated set, sorted by `UUID.int` (equal to PostgreSQL `uuid` order)."""
    members = tuple(sorted(set(member_ids), key=lambda value: value.int))
    _lock_group(
        connection,
        plan,
        campaign_id=campaign_id,
        group_id=group_id,
        actor_membership_id=actor_membership_id,
    )
    group = connection.execute(_GROUP_ROW, {"g": group_id}).mappings().one()
    if group["lifecycle_status_code"] != "active":
        raise AccessGroupNotActiveError(f"access group {group_id} is not currently active")
    # the membership pass: ascending id over {actor} U members; a row that is both is NKU first, then S on the held row
    for membership_id in sorted({*members, actor_membership_id}, key=lambda value: value.int):
        if membership_id in members:
            plan.lock(connection, MEMBER_LOCK, {"member": membership_id, "campaign": campaign_id})
        if membership_id == actor_membership_id:
            plan.lock(
                connection,
                ACTOR_MEMBERSHIP_LOCK,
                {"membership": actor_membership_id, "campaign": campaign_id},
            )
    rows = {
        row["campaign_membership_id"]: row
        for row in connection.execute(_MEMBER_ROWS, {"ids": list(members)}).mappings().all()
    }
    # the account pass: ascending user id; the actor S, a member KS, a shared row S once
    member_users = {row["user_id"] for row in rows.values() if row["campaign_id"] == campaign_id}
    for user_id in sorted({*member_users, actor_user_id}, key=lambda value: value.int):
        if user_id == actor_user_id:
            plan.lock(connection, ACTOR_ACCOUNT_LOCK, {"actor": actor_user_id})
        else:
            plan.lock(connection, MEMBER_ACCOUNT_LOCK, {"member_user": user_id})
    plan.lock(connection, CAMPAIGN_KEY_SHARE_LOCK, {"campaign": campaign_id})
    if reservation_id is not None:
        plan.lock(connection, RECEIPT_LOCK, {"receipt": reservation_id})
    _require_campaign_active(connection, campaign_id)
    for membership_id in members:
        row = rows.get(membership_id)
        if row is None or row["campaign_id"] != campaign_id:
            raise MembershipNotInCampaignError(
                f"membership {membership_id} does not belong to campaign {campaign_id} "
                f"(actual campaign: {row['campaign_id'] if row is not None else None})"
            )
        # the status is read after the lock, separately from it: an end that raced this add is a 409, not a 404
        status = connection.execute(_MEMBER_STATUS, {"status": row["membership_status_id"]}).one()
        if not (row["ended_at"] is None and status.code == "active" and status.is_active):
            raise MembershipNotActiveError(
                f"membership {membership_id} is not currently an eligible, open membership to "
                "add to an access group"
            )
        if connection.execute(_ACCOUNT_STATUS, {"u": row["user_id"]}).scalar() != "active":
            raise MembershipNotActiveError(
                f"membership {membership_id}'s user {row['user_id']} is not currently an "
                "active platform account"
            )
    if plan.evidence(MEMBER_LOCK) != frozenset((member,) for member in members):
        raise AccessGroupMembersNotLockedError()
    return GroupPrepared(
        world_id=_scope_world(connection, campaign_id),
        action_id=lookup_id(connection, "audit", "change_actions", "change_action_id", "created"),
        name=str(group["name"]),
        member_ids=members,
    )


def write_add_members(
    connection: Connection,
    plan: AuthorizationPlan,
    prepared: GroupPrepared,
    *,
    group_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    actor_membership_id: uuid.UUID,
    correlation_id: str | None,
) -> tuple[tuple[uuid.UUID, uuid.UUID], ...]:
    """One link INSERT per locked member, ascending, then one audit row per confirmed link in the same order. Returns
    `(campaign membership id, link id)` pairs in ascending member order."""
    added: list[tuple[uuid.UUID, uuid.UUID]] = []
    for member_id in prepared.member_ids:
        created = plan.execute(
            connection,
            INSERT_LINK,
            {"group": group_id, "member": member_id, "added_by": actor_membership_id},
        )
        link_id = created.keys[0][0]
        assert isinstance(link_id, uuid.UUID)
        added.append((member_id, link_id))
    for member_id, link_id in added:
        plan.execute(
            connection,
            LINK_AUDIT,
            {
                **_audit_binds(
                    prepared,
                    record=link_id,
                    actor_user_id=actor_user_id,
                    correlation_id=correlation_id,
                ),
                "changed": {
                    "access_group_id": str(group_id),
                    "campaign_membership_id": str(member_id),
                },
            },
        )
    return tuple(added)


# =====================================================================================================
# remove a member
# =====================================================================================================


def prepare_remove_member(
    connection: Connection,
    plan: AuthorizationPlan,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    actor_membership_id: uuid.UUID,
    link_id: uuid.UUID,
    reservation_id: uuid.UUID | None,
) -> GroupPrepared:
    # an unlocked discovery of link -> group -> campaign (never updated): the 404 before any lock of a foreign row
    found = connection.execute(_LINK_DISCOVERY, {"link": link_id}).mappings().one_or_none()
    if found is None or found["campaign_id"] != campaign_id:
        raise AccessGroupMembershipNotInCampaignError(
            f"access group membership {link_id} does not belong to campaign {campaign_id} "
            f"(actual campaign: {found['campaign_id'] if found is not None else None})"
        )
    _lock_actor(
        connection,
        plan,
        campaign_id=campaign_id,
        actor_user_id=actor_user_id,
        actor_membership_id=actor_membership_id,
    )
    plan.lock(connection, CAMPAIGN_KEY_SHARE_LOCK, {"campaign": campaign_id})
    open_keys = plan.lock(connection, LINK_OPEN_LOCK, {"link": link_id})
    if reservation_id is not None:
        plan.lock(connection, RECEIPT_LOCK, {"receipt": reservation_id})
    removed_at = connection.execute(_LINK_REMOVED, {"link": link_id}).scalar_one()
    will_remove = bool(open_keys)
    if will_remove != (removed_at is None):
        raise RuntimeError("the access group link changed under its own lock")
    return GroupPrepared(
        world_id=_scope_world(connection, campaign_id),
        action_id=lookup_id(connection, "audit", "change_actions", "change_action_id", "updated"),
        will_write=will_remove,
        group_id=found["access_group_id"],
        member_id=found["campaign_membership_id"],
    )


def write_remove_member(
    connection: Connection,
    plan: AuthorizationPlan,
    prepared: GroupPrepared,
    *,
    link_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    correlation_id: str | None,
) -> None:
    if not prepared.will_write:
        return
    plan.execute(connection, REMOVE_LINK, {"target": link_id})
    plan.execute(
        connection,
        REMOVE_AUDIT,
        {
            **_audit_binds(
                prepared, record=link_id, actor_user_id=actor_user_id, correlation_id=correlation_id
            ),
            "changed": {
                "access_group_id": str(prepared.group_id)
                if prepared.group_id is not None
                else None,
                "campaign_membership_id": (
                    str(prepared.member_id) if prepared.member_id is not None else None
                ),
            },
        },
    )


__all__ = [
    "ADD_DECLARATIONS",
    "CREATE_DECLARATIONS",
    "DEACTIVATE_DECLARATIONS",
    "GROUP_RECEIPT",
    "REACTIVATE_DECLARATIONS",
    "REMOVE_DECLARATIONS",
    "UPDATE_DECLARATIONS",
    "AccessGroupCascadeIncompleteError",
    "AccessGroupMembersNotLockedError",
    "GroupPrepared",
    "prepare_add_members",
    "prepare_create_group",
    "prepare_deactivate_group",
    "prepare_reactivate_group",
    "prepare_remove_member",
    "prepare_update_group",
    "write_add_members",
    "write_create_group",
    "write_deactivate_group",
    "write_reactivate_group",
    "write_remove_member",
    "write_update_group",
]
