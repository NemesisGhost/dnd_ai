"""Campaign update, archive and reactivate as keyed pre-write plans (R01 S5-E1; plan section 6.26).

`update_campaign`, `archive_campaign` and `reactivate_campaign` in `campaigns.py` stay as the direct,
unguarded commands. The three routes (`dnd_ai.api.campaigns`) use the declarations and the lock, read and
write phases in this module instead, so that **every lock is taken before `plan.finalize`**, every read the
command's refusals depend on happens before it, and every write is a declared step after it.

All three are *pre-write* routes with an optional `Idempotency-Key`: the reservation's campaign foreign key
is deferred (J-1'), and the campaign row is locked `FOR UPDATE` (stronger than the key-share the deferral
needs, and the mode the commands took before). `archive` changes the campaign's lifecycle, which the route
requirement reads (an archived campaign is a 404 for every ordinary route), so `finalize` has to run
**before** the `UPDATE`: authority is judged against the approved pre-command state, exactly as the review
(section 6.4, "the command's own effects") requires. A post-write plan would have refused the request.

## Lock sequences (the whole sequence; implicit foreign-key locks and triggers included)

Key to modes: S `FOR SHARE`, U `FOR UPDATE`. "reservation" is `begin_idempotent_request`.

**Update, archive (keyed).**

1. advisory key lock (first lock; holds nothing else)
2. reservation `INSERT`: the actor's account row, KS (actor FK); the campaign FK is **deferred**
3. the actor's unrevoked role rows of this campaign, S (`plan.lock`, ordered by id)
4. the actor's open membership, S
5. the actor's account, S (a KS is already held by step 2; this upgrades it)
6. the campaign row, U (before: first lock of the command; now after the actor's rows, review section 5
   item 5, "campaign lifecycle commands take the actor rows before the campaign")
6a. *update only:* the same row again, U, only while the new name or description differs from the stored
   one (`CAMPAIGN_CHANGED_LOCK`; already held, no wait). Its evidence is database state under the campaign
   lock: one key for a genuine edit, none for a no-op
7. the reservation row, U
8. reads (campaign state, `access.manage` re-resolved, stale version, blocked action, world id), then
   `plan.finalize`: authority is judged here, before any write
9. campaign `UPDATE` (declared; the BEFORE triggers run: `set_updated_at`, `bump_row_version`,
   `enforce_immutable_columns`, and `enforce_campaign_ruleset_allowed`, which takes `rules.world_rulesets`
   `FOR SHARE` for the campaign's world and ruleset: a permitted residual, see below)
10. `audit.change_log` `INSERT` (FK KS on `change_actions` and the actor's account, held)
11. receipt `UPDATE` (the reservation row, held U)
12. COMMIT: the deferred campaign FK check and `tr_campaigns_retain_access_manager` re-acquire the held
    campaign U; the retention function only reads when the new status is `active`

**Reactivate (keyed)** is the same with two locks first: the world row S, then the campaign's timeline row S
(both before the actor rows, the approved global order and the order the command already used), and the
`campaign_has_access_manager` read of the blocked-action check before `finalize`. Its COMMIT-time retention
check (`assert_campaign_retains_access_manager`) takes the campaign `FOR UPDATE` (held) and reads the
membership, role and capability tables without locking.

**Unkeyed:** the same without steps 1, 2, 7 and 11.

## Declared obligations

| Route | Campaign UPDATE | Audit INSERT | Receipt |
|---|---|---|---|
| update | `EachLockedRow(complete=True)` over `CAMPAIGN_CHANGED_LOCK` | `PerEvidence(CAMPAIGN_CHANGED_LOCK)` | `Exactly(1)` on a fresh keyed request |
| archive | `Exactly(1)` | `Exactly(1)` | same |
| reactivate | `Exactly(1)` | `Exactly(1)` | same |

A genuine edit owes the update and exactly one audit row; an edit that changes nothing owes neither and may
do neither (a no-op bumps no version, writes no audit row), but a fresh keyed no-op still completes its
receipt. Archive and reactivate have no legitimate no-op: a campaign already in the target state is refused
(a 409) before `finalize`, so their writes are unconditional once the request is admitted. Replay keeps the
empty declaration and the route requirement only (R-D4).

## What the response reads

The declared step may return only the primary key, so the new `row_version` is not read back (a statement
after `finalize` must be a declared step). It is the version read under the held lock plus one:
`core.bump_row_version` is the only writer of the column and its source is pinned below, and the tests
compare the response with the stored value.

## Trigger and lock effects (what is pinned, what is residual)

All five triggers of `campaign.campaigns` are pinned by name, timing, events and function source md5. Of
their effects only `enforce_campaign_ruleset_allowed`'s `FOR SHARE` on `rules.world_rulesets` can wait: it
conflicts only with an `UPDATE`, `DELETE` or `FOR UPDATE` of that row, and the application never issues one
(the row is inserted once, at world creation). It is a **permitted residual wait**, not a re-acquisition,
and is pinned by a test that parks a competitor on it. The retention trigger re-acquires the held campaign
lock (a proven re-acquisition, tested at COMMIT).
"""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection, bindparam, insert, or_, select, text, update

from dnd_ai.domain.authoring import (
    CampaignNotAuthorizedError,
    StaleWriteError,
    normalize_description,
    normalize_name,
    normalize_reason,
)
from dnd_ai.domain.authoring_policy import CAMPAIGN_ARCHIVE, CAMPAIGN_REACTIVATE, CAMPAIGN_UPDATE
from dnd_ai.domain.authorization import AuthorizationPlan, ReservationDeclarations
from dnd_ai.domain.authorization_steps import (
    EachLockedRow,
    Event,
    Exactly,
    FkBinding,
    FunctionPin,
    KeyBind,
    Level,
    PerEvidence,
    PreLock,
    PreWriteDeclaration,
    Timing,
    TriggerPin,
    WriteStep,
)
from dnd_ai.domain.data_classification import audit_change
from dnd_ai.persistence.tables.audit import change_log
from dnd_ai.persistence.tables.campaign import campaigns, timelines
from dnd_ai.persistence.tables.core import lifecycle_statuses, worlds
from dnd_ai.persistence.tables.security import campaign_memberships, membership_roles, users

from ._pre_write_steps import (
    CHANGE_LOG_ACTION_FK,
    CHANGE_LOG_ACTOR_FK,
    CHANGE_LOG_UNLOCKED_FK_TARGETS,
    RECEIPT_LOCK,
    RECEIPT_STEP,
    fk_of,
)
from ._shared import lifecycle_code, lookup_id
from .campaigns import _require_campaign_action, _world_of_timeline, read_manageable_campaign

UPDATE_COMMAND_NAME = "update_campaign"
ARCHIVE_COMMAND_NAME = "archive_campaign"
REACTIVATE_COMMAND_NAME = "reactivate_campaign"

cm = campaign_memberships
mr = membership_roles

# -- triggers of campaign.campaigns (catalogue pins) ----------------------------------------------------


def _pin(
    name: str,
    function_schema: str,
    function_name: str,
    source_md5: str,
    *,
    timing: Timing = Timing.BEFORE,
    events: frozenset[Event] = frozenset({Event.UPDATE}),
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


CAMPAIGN_TRIGGERS = frozenset(
    {
        _pin(
            "tr_campaigns_set_updated_at",
            "core",
            "set_updated_at",
            "fa4e845cca4d0acb6dd3509d9d6c2098",
        ),
        _pin(
            "tr_campaigns_enforce_ruleset_allowed",
            "campaign",
            "enforce_campaign_ruleset_allowed",
            "eee5e515b6d790b87a9f8d25e47affa5",
            events=frozenset({Event.INSERT, Event.UPDATE}),
        ),
        _pin(
            "tr_campaigns_enforce_immutable",
            "core",
            "enforce_immutable_columns",
            "583c3783f15f299e7fc903503f694c6b",
            args=("timeline_id",),
        ),
        _pin(
            "tr_campaigns_retain_access_manager",
            "security",
            "enforce_campaigns_retain_access_manager",
            "631c0b6ac7c03ec0128f6da1f3ccc3cf",
            timing=Timing.AFTER,
            events=frozenset({Event.INSERT, Event.UPDATE}),
            constraint=True,
        ),
        _pin(
            "tr_campaigns_bump_row_version",
            "core",
            "bump_row_version",
            "c28e0a20d66b8de39865c8b610ef0031",
        ),
    }
)

# -- locks ----------------------------------------------------------------------------------------------

#: The world and the campaign's timeline, `FOR SHARE` (reactivate only), bound `world` and `timeline`.
WORLD_SHARE_LOCK = PreLock(
    "world_share",
    select(worlds.c.world_id)
    .where(worlds.c.world_id == bindparam("world"))
    .with_for_update(read=True),
)
TIMELINE_SHARE_LOCK = PreLock(
    "timeline_share",
    select(timelines.c.timeline_id)
    .where(timelines.c.timeline_id == bindparam("timeline"))
    .with_for_update(read=True),
)

#: The actor's own authority rows, `FOR SHARE`: unrevoked role rows of the membership (by id), the open
#: membership and the account. A concurrent revoke, end or deactivation (each `FOR UPDATE` on one of them)
#: serializes against the request, and these rows are locked **before** the campaign: a role revocation
#: wants the campaign `FOR UPDATE` at COMMIT (retention), so holding the campaign while waiting for a
#: revoked role row would deadlock (the reason `lock_authoring_scope` orders them this way).
ACTOR_ROLES_LOCK = PreLock(
    "actor_role_rows",
    select(mr.c.membership_role_id)
    .where(mr.c.campaign_membership_id == bindparam("membership"))
    .where(mr.c.revoked_at.is_(None))
    .order_by(mr.c.membership_role_id)
    .with_for_update(read=True),
)
ACTOR_MEMBERSHIP_LOCK = PreLock(
    "actor_membership_share",
    select(cm.c.campaign_membership_id)
    .where(cm.c.campaign_membership_id == bindparam("membership"))
    .where(cm.c.campaign_id == bindparam("campaign"))
    .where(cm.c.ended_at.is_(None))
    .with_for_update(read=True),
)
ACTOR_ACCOUNT_LOCK = PreLock(
    "actor_account_share",
    select(users.c.user_id).where(users.c.user_id == bindparam("actor")).with_for_update(read=True),
)

#: The campaign, `FOR UPDATE`, bound `campaign`. The mode the commands always took; stronger than the
#: key-share the reservation deferral needs, and the mode the reactivation retention trigger re-acquires.
CAMPAIGN_ROW_LOCK = PreLock(
    "campaign_row_update",
    select(campaigns.c.campaign_id)
    .where(campaigns.c.campaign_id == bindparam("campaign"))
    .with_for_update(),
)
#: The same row again, `FOR UPDATE`, **only if the new name or description differs** from the stored one
#: (`IS DISTINCT FROM`, so a NULL description compares correctly). Already held: no wait, no order change.
#: It is the evidence of "this edit changes something", established by the database under the lock.
CAMPAIGN_CHANGED_LOCK = PreLock(
    "campaign_changed_row",
    select(campaigns.c.campaign_id)
    .where(campaigns.c.campaign_id == bindparam("campaign"))
    .where(
        or_(
            campaigns.c.name.is_distinct_from(bindparam("new_name")),
            campaigns.c.description.is_distinct_from(bindparam("new_description")),
        )
    )
    .with_for_update(),
)
RECEIPT_ROW_LOCK = RECEIPT_LOCK

# -- steps ----------------------------------------------------------------------------------------------

UPDATE_SETTINGS = WriteStep(
    name="update_campaign",
    statement=update(campaigns)
    .where(campaigns.c.campaign_id == bindparam("campaign"))
    .values(name=bindparam("new_name"), description=bindparam("new_description"))
    .returning(campaigns.c.campaign_id),
    cardinality=EachLockedRow(complete=True),
    target=(KeyBind(campaigns.c.campaign_id, "campaign"),),
    target_lock=CAMPAIGN_CHANGED_LOCK,
    value_binds=frozenset({"new_name", "new_description"}),
    triggers=CAMPAIGN_TRIGGERS,
)
_LIFECYCLE_FK = FkBinding(
    fk_of(campaigns, "lifecycle_status_id"),
    (KeyBind(campaigns.c.lifecycle_status_id, "status"),),
    None,
)
ARCHIVE_CAMPAIGN = WriteStep(
    name="archive_campaign",
    statement=update(campaigns)
    .where(campaigns.c.campaign_id == bindparam("campaign"))
    .values(lifecycle_status_id=bindparam("status"))
    .returning(campaigns.c.campaign_id),
    cardinality=Exactly(1),
    target=(KeyBind(campaigns.c.campaign_id, "campaign"),),
    target_lock=CAMPAIGN_ROW_LOCK,
    fks=(_LIFECYCLE_FK,),
    triggers=CAMPAIGN_TRIGGERS,
)
REACTIVATE_CAMPAIGN = WriteStep(
    name="reactivate_campaign",
    statement=update(campaigns)
    .where(campaigns.c.campaign_id == bindparam("campaign"))
    .values(lifecycle_status_id=bindparam("status"))
    .returning(campaigns.c.campaign_id),
    cardinality=Exactly(1),
    target=(KeyBind(campaigns.c.campaign_id, "campaign"),),
    target_lock=CAMPAIGN_ROW_LOCK,
    fks=(_LIFECYCLE_FK,),
    triggers=CAMPAIGN_TRIGGERS,
)

UPDATE_AUDIT = WriteStep(
    name="audit_updated",
    statement=insert(change_log)
    .values(
        change_action_id=bindparam("action"),
        schema_name="campaign",
        table_name="campaigns",
        record_id=bindparam("record"),
        world_id=bindparam("world"),
        actor_user_id=bindparam("actor"),
        correlation_id=bindparam("correlation"),
        command_name="update_campaign",
        changed_fields=bindparam("changed"),
    )
    .returning(change_log.c.change_log_id),
    cardinality=PerEvidence(CAMPAIGN_CHANGED_LOCK),
    fks=(CHANGE_LOG_ACTION_FK, CHANGE_LOG_ACTOR_FK),
    value_binds=frozenset({"record", "world", "correlation", "changed"}),
)
ARCHIVE_AUDIT = WriteStep(
    name="audit_archived",
    statement=insert(change_log)
    .values(
        change_action_id=bindparam("action"),
        schema_name="campaign",
        table_name="campaigns",
        record_id=bindparam("record"),
        world_id=bindparam("world"),
        actor_user_id=bindparam("actor"),
        correlation_id=bindparam("correlation"),
        command_name="archive_campaign",
        previous_status="active",
        new_status="archived",
        reason=bindparam("reason"),
    )
    .returning(change_log.c.change_log_id),
    cardinality=Exactly(1),
    fks=(CHANGE_LOG_ACTION_FK, CHANGE_LOG_ACTOR_FK),
    value_binds=frozenset({"record", "world", "correlation", "reason"}),
)
REACTIVATE_AUDIT = WriteStep(
    name="audit_restored",
    statement=insert(change_log)
    .values(
        change_action_id=bindparam("action"),
        schema_name="campaign",
        table_name="campaigns",
        record_id=bindparam("record"),
        world_id=bindparam("world"),
        actor_user_id=bindparam("actor"),
        correlation_id=bindparam("correlation"),
        command_name="reactivate_campaign",
        previous_status="archived",
        new_status="active",
    )
    .returning(change_log.c.change_log_id),
    cardinality=Exactly(1),
    fks=(CHANGE_LOG_ACTION_FK, CHANGE_LOG_ACTOR_FK),
    value_binds=frozenset({"record", "world", "correlation"}),
)
LIFECYCLE_RECEIPT = RECEIPT_STEP

#: The change-log targets (seed data and the account) plus the lifecycle lookup: seed data nobody updates.
_UNLOCKED = CHANGE_LOG_UNLOCKED_FK_TARGETS | {lifecycle_statuses}

_ACTOR_LOCKS = (ACTOR_ROLES_LOCK, ACTOR_MEMBERSHIP_LOCK, ACTOR_ACCOUNT_LOCK)

UPDATE_DECLARATIONS = ReservationDeclarations(
    reserved=PreWriteDeclaration(
        locks=(*_ACTOR_LOCKS, CAMPAIGN_ROW_LOCK, CAMPAIGN_CHANGED_LOCK, RECEIPT_ROW_LOCK),
        steps=(UPDATE_SETTINGS, UPDATE_AUDIT, LIFECYCLE_RECEIPT),
        unlocked_fk_targets=_UNLOCKED,
    ),
    unkeyed=PreWriteDeclaration(
        locks=(*_ACTOR_LOCKS, CAMPAIGN_ROW_LOCK, CAMPAIGN_CHANGED_LOCK),
        steps=(UPDATE_SETTINGS, UPDATE_AUDIT),
        unlocked_fk_targets=_UNLOCKED,
    ),
)
ARCHIVE_DECLARATIONS = ReservationDeclarations(
    reserved=PreWriteDeclaration(
        locks=(*_ACTOR_LOCKS, CAMPAIGN_ROW_LOCK, RECEIPT_ROW_LOCK),
        steps=(ARCHIVE_CAMPAIGN, ARCHIVE_AUDIT, LIFECYCLE_RECEIPT),
        unlocked_fk_targets=_UNLOCKED,
    ),
    unkeyed=PreWriteDeclaration(
        locks=(*_ACTOR_LOCKS, CAMPAIGN_ROW_LOCK),
        steps=(ARCHIVE_CAMPAIGN, ARCHIVE_AUDIT),
        unlocked_fk_targets=_UNLOCKED,
    ),
)
REACTIVATE_DECLARATIONS = ReservationDeclarations(
    reserved=PreWriteDeclaration(
        locks=(
            WORLD_SHARE_LOCK,
            TIMELINE_SHARE_LOCK,
            *_ACTOR_LOCKS,
            CAMPAIGN_ROW_LOCK,
            RECEIPT_ROW_LOCK,
        ),
        steps=(REACTIVATE_CAMPAIGN, REACTIVATE_AUDIT, LIFECYCLE_RECEIPT),
        unlocked_fk_targets=_UNLOCKED,
    ),
    unkeyed=PreWriteDeclaration(
        locks=(WORLD_SHARE_LOCK, TIMELINE_SHARE_LOCK, *_ACTOR_LOCKS, CAMPAIGN_ROW_LOCK),
        steps=(REACTIVATE_CAMPAIGN, REACTIVATE_AUDIT),
        unlocked_fk_targets=_UNLOCKED,
    ),
)

# -- the lock, read and write phases --------------------------------------------------------------------


@dataclass(frozen=True)
class PreparedLifecycle:
    """What the lock and read phase established, all before `finalize`."""

    world_id: uuid.UUID
    row_version: int  # the version the response reports (the held version, plus one if written)
    lifecycle_status: str  # the status the response reports
    changed: bool  # whether the command writes (always true for archive and reactivate)
    change_action_id: uuid.UUID
    status_id: uuid.UUID | None  # the lifecycle status the write sets (archive, reactivate)
    changed_fields: dict[str, object] | None


def _lock_actor_and_campaign(
    connection: Connection,
    plan: AuthorizationPlan,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    actor_membership_id: uuid.UUID,
) -> None:
    plan.lock(connection, ACTOR_ROLES_LOCK, {"membership": actor_membership_id})
    plan.lock(
        connection,
        ACTOR_MEMBERSHIP_LOCK,
        {"membership": actor_membership_id, "campaign": campaign_id},
    )
    plan.lock(connection, ACTOR_ACCOUNT_LOCK, {"actor": actor_user_id})
    if not plan.lock(connection, CAMPAIGN_ROW_LOCK, {"campaign": campaign_id}):
        raise CampaignNotAuthorizedError(f"campaign {campaign_id} does not exist")


def prepare_update_campaign(
    connection: Connection,
    plan: AuthorizationPlan,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    actor_membership_id: uuid.UUID,
    expected_row_version: int,
    name: str,
    description: str | None,
    reservation_id: uuid.UUID | None,
) -> PreparedLifecycle:
    """The update lock phase and its reads. Same order of refusals as `update_campaign`: validation, then
    the locked campaign (existence, `access.manage`), the stale version, the blocked action."""
    clean_name = normalize_name(name)
    clean_description = normalize_description(description)
    _lock_actor_and_campaign(
        connection,
        plan,
        campaign_id=campaign_id,
        actor_user_id=actor_user_id,
        actor_membership_id=actor_membership_id,
    )
    evidence = plan.lock(
        connection,
        CAMPAIGN_CHANGED_LOCK,
        {"campaign": campaign_id, "new_name": clean_name, "new_description": clean_description},
    )
    if reservation_id is not None:
        plan.lock(connection, RECEIPT_ROW_LOCK, {"receipt": reservation_id})
    campaign = read_manageable_campaign(
        connection, campaign_id=campaign_id, actor_user_id=actor_user_id
    )
    world_id = _world_of_timeline(connection, campaign.timeline_id)
    if campaign.row_version != expected_row_version:
        raise StaleWriteError(f"campaign {campaign_id} is at {campaign.row_version}")
    _require_campaign_action(
        connection, action=CAMPAIGN_UPDATE, campaign_id=campaign_id, campaign=campaign
    )
    changed: dict[str, object] = {}
    if clean_name != campaign.name:
        changed["name"] = {"from": campaign.name, "to": clean_name}
    if clean_description != campaign.description:
        changed["description"] = audit_change(
            "description", campaign.description, clean_description
        )
    if bool(changed) != bool(evidence):  # the lock's own evidence and the comparison cannot differ
        raise RuntimeError("the campaign changed under its own lock")
    return PreparedLifecycle(
        world_id=world_id,
        row_version=campaign.row_version + 1 if changed else campaign.row_version,
        lifecycle_status=campaign.lifecycle_status,
        changed=bool(changed),
        change_action_id=lookup_id(
            connection, "audit", "change_actions", "change_action_id", "updated"
        ),
        status_id=None,
        changed_fields=changed or None,
    )


def prepare_archive_campaign(
    connection: Connection,
    plan: AuthorizationPlan,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    actor_membership_id: uuid.UUID,
    expected_row_version: int,
    reason: str | None,
    reservation_id: uuid.UUID | None,
) -> PreparedLifecycle:
    normalize_reason(reason)
    _lock_actor_and_campaign(
        connection,
        plan,
        campaign_id=campaign_id,
        actor_user_id=actor_user_id,
        actor_membership_id=actor_membership_id,
    )
    if reservation_id is not None:
        plan.lock(connection, RECEIPT_ROW_LOCK, {"receipt": reservation_id})
    campaign = read_manageable_campaign(
        connection, campaign_id=campaign_id, actor_user_id=actor_user_id
    )
    world_id = _world_of_timeline(connection, campaign.timeline_id)
    if campaign.row_version != expected_row_version:
        raise StaleWriteError(f"campaign {campaign_id} is at {campaign.row_version}")
    _require_campaign_action(
        connection, action=CAMPAIGN_ARCHIVE, campaign_id=campaign_id, campaign=campaign
    )
    return PreparedLifecycle(
        world_id=world_id,
        row_version=campaign.row_version + 1,
        lifecycle_status="archived",
        changed=True,
        change_action_id=lookup_id(
            connection, "audit", "change_actions", "change_action_id", "archived"
        ),
        status_id=lookup_id(
            connection, "core", "lifecycle_statuses", "lifecycle_status_id", "archived"
        ),
        changed_fields=None,
    )


def prepare_reactivate_campaign(
    connection: Connection,
    plan: AuthorizationPlan,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    actor_membership_id: uuid.UUID,
    expected_row_version: int,
    reservation_id: uuid.UUID | None,
) -> PreparedLifecycle:
    """World and timeline `FOR SHARE` first (the order the command used), then the actor's rows and the
    campaign; the access-manager pre-check (`_require_campaign_action`) runs under the campaign lock and
    before `finalize`, so the retention trigger's COMMIT-time check cannot be the first to refuse."""
    timeline_id = connection.execute(
        text("SELECT timeline_id FROM campaign.campaigns WHERE campaign_id = :c"),
        {"c": campaign_id},
    ).scalar()
    if timeline_id is None:
        raise CampaignNotAuthorizedError(f"campaign {campaign_id} does not exist")
    world_id = _world_of_timeline(connection, timeline_id)
    world_locked = plan.lock(connection, WORLD_SHARE_LOCK, {"world": world_id})
    timeline_locked = plan.lock(connection, TIMELINE_SHARE_LOCK, {"timeline": timeline_id})
    assert world_locked and timeline_locked
    world_status_id = connection.execute(
        text("SELECT lifecycle_status_id FROM core.worlds WHERE world_id = :w"), {"w": world_id}
    ).scalar()
    timeline_status_id = connection.execute(
        text("SELECT lifecycle_status_id FROM campaign.timelines WHERE timeline_id = :t"),
        {"t": timeline_id},
    ).scalar()
    assert world_status_id is not None and timeline_status_id is not None
    _lock_actor_and_campaign(
        connection,
        plan,
        campaign_id=campaign_id,
        actor_user_id=actor_user_id,
        actor_membership_id=actor_membership_id,
    )
    if reservation_id is not None:
        plan.lock(connection, RECEIPT_ROW_LOCK, {"receipt": reservation_id})
    campaign = read_manageable_campaign(
        connection, campaign_id=campaign_id, actor_user_id=actor_user_id
    )
    if campaign.row_version != expected_row_version:
        raise StaleWriteError(f"campaign {campaign_id} is at {campaign.row_version}")
    _require_campaign_action(
        connection,
        action=CAMPAIGN_REACTIVATE,
        campaign_id=campaign_id,
        campaign=campaign,
        world_status=lifecycle_code(connection, world_status_id),
        timeline_status=lifecycle_code(connection, timeline_status_id),
    )
    return PreparedLifecycle(
        world_id=world_id,
        row_version=campaign.row_version + 1,
        lifecycle_status="active",
        changed=True,
        change_action_id=lookup_id(
            connection, "audit", "change_actions", "change_action_id", "restored"
        ),
        status_id=lookup_id(
            connection, "core", "lifecycle_statuses", "lifecycle_status_id", "active"
        ),
        changed_fields=None,
    )


def _audit_params(
    prepared: PreparedLifecycle,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    correlation_id: str | None,
) -> dict[str, Any]:
    return {
        "action": prepared.change_action_id,
        "record": campaign_id,
        "world": prepared.world_id,
        "actor": actor_user_id,
        "correlation": uuid.UUID(correlation_id) if correlation_id is not None else None,
    }


def write_update_campaign(
    connection: Connection,
    plan: AuthorizationPlan,
    prepared: PreparedLifecycle,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    correlation_id: str | None,
    name: str,
    description: str | None,
) -> None:
    """The declared update and its audit row, after `finalize` (attempted only by a genuine edit)."""
    if not prepared.changed:
        return
    plan.execute(
        connection,
        UPDATE_SETTINGS,
        {
            "campaign": campaign_id,
            "new_name": normalize_name(name),
            "new_description": normalize_description(description),
        },
    )
    plan.execute(
        connection,
        UPDATE_AUDIT,
        {
            **_audit_params(
                prepared,
                campaign_id=campaign_id,
                actor_user_id=actor_user_id,
                correlation_id=correlation_id,
            ),
            "changed": prepared.changed_fields,
        },
    )


def write_archive_campaign(
    connection: Connection,
    plan: AuthorizationPlan,
    prepared: PreparedLifecycle,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    correlation_id: str | None,
    reason: str | None,
) -> None:
    plan.execute(
        connection, ARCHIVE_CAMPAIGN, {"campaign": campaign_id, "status": prepared.status_id}
    )
    plan.execute(
        connection,
        ARCHIVE_AUDIT,
        {
            **_audit_params(
                prepared,
                campaign_id=campaign_id,
                actor_user_id=actor_user_id,
                correlation_id=correlation_id,
            ),
            "reason": reason.strip() if reason and reason.strip() else None,
        },
    )


def write_reactivate_campaign(
    connection: Connection,
    plan: AuthorizationPlan,
    prepared: PreparedLifecycle,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    correlation_id: str | None,
) -> None:
    plan.execute(
        connection, REACTIVATE_CAMPAIGN, {"campaign": campaign_id, "status": prepared.status_id}
    )
    plan.execute(
        connection,
        REACTIVATE_AUDIT,
        _audit_params(
            prepared,
            campaign_id=campaign_id,
            actor_user_id=actor_user_id,
            correlation_id=correlation_id,
        ),
    )
