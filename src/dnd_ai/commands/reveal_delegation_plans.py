"""Grant and revoke a `character.reveal` delegation as unkeyed pre-write plans (R01 S5-E6; plan 6.36).

`grant_character_reveal_delegation` and `revoke_character_reveal_delegation` in `character_reveal.py` stay as the
direct, unguarded commands (and the oracle the route tests compare against). The two routes
(`dnd_ai.api.character_reveal`) use the declarations and the lock, read and write phases below, so that **every
lock and every refusal precedes `plan.finalize`** and every write is a declared step after it. Both routes are
**unkeyed** (`R01_UNKEYED_PRE_WRITE_ROUTES`): they have never been idempotent through a reservation, an
`Idempotency-Key` header is ignored, and there is no receipt step. Repeating a grant or a revoke is idempotent by
its own rule (below), not by replay.

## Authority is two things, and `access.manage` is only the first

The route requirement (`access.manage`, evaluated by `plan.finalize`) is a coarse filter. The **operation-specific
authority** is a live built-in `campaign_owner` assignment (D3): a custom `access.manage` holder is refused 403
`campaign_owner_required` before anything is written. The grant adds **grantee eligibility**: the grantee must hold a
live built-in `gm` assignment (409 `reveal_delegation_recipient_not_gm`). Both are plain reads **after** the locks
that hold the rows they judge, repeated at a fresh database instant after the last lock wait (DEF-013), and both
precede `finalize`.

## Grant: the corrected order (S5-E2 lock-order correction C1), unchanged

One unlocked discovery read finds the caller's live owner row and the grantee's unrevoked built-in `gm` row (each
at most one: the unique indexes), ascending by id. Then, one statement per row bound to a discovered id (a row that
appears later is never picked up by a locking statement):

1. **role class**, ascending id, each row at its mode: the owner row `FOR SHARE`, the `gm` row `FOR UPDATE`;
2. the unlocked 404 (a grantee of another campaign), after the owner refusal;
3. **membership class**, ascending id: the grantee `FOR NO KEY UPDATE`, the caller `FOR KEY SHARE`; when they are
   the same membership the stronger lock is taken first and the weaker lands on the held row (no wait, no upgrade);
4. the grantee's **delegation rows** `FOR UPDATE`: the ones bound to a different `gm` row (stale) and the one bound
   to the discovered `gm` row (matching); the live unique index allows one row in all;
5. the **campaign** `FOR KEY SHARE` (the mode the insert's foreign key needs; never stronger: administrative
   recovery holds the campaign `FOR NO KEY UPDATE` while it waits for the membership it promotes).

After the last wait: the caller is judged again, the grantee's live `gm` assignment is read at a fresh instant
(409 not-GM) and must be the row locked in step 1 (409 `reveal_delegation_recipient_changed`: a `gm` row that appeared
after discovery would be a delegation target nobody holds), and the grantee's live delegations read without a lock
must equal the locked set (the same 409; the proof the empty `PerAbsence` evidence below needs).

Branches and obligations:

| Branch | Writes |
|---|---|
| a live delegation is already bound to the live `gm` row | none (`created` false, nothing audited): the matching lock returned a row, so the INSERT is forbidden (`PerAbsence`) and none is owed |
| none | the INSERT (`PerAbsence` on the matching lock) and one audit row (`AnyConfirmed` on the INSERT) |
| a live delegation bound to a lapsed or replaced `gm` row | that delegation closed (`EachLockedRow(complete=True)` over the stale lock), then the INSERT and the audit row |

Refusal precedence is the legacy command's: 403 (no live owner row, at discovery, at the lock or after the waits),
404 (grantee of another campaign), 409 not-GM, 409 recipient changed. A refused call writes nothing and no audit row.

## Revoke

The owner row `FOR SHARE` (bound to the discovered live row), the unlocked 404, the grantee's live delegation in this
campaign `FOR UPDATE`, the caller's membership `FOR KEY SHARE`, the caller judged again; no campaign lock (as before:
nothing it writes takes one). Owners may revoke whoever granted it (the grantor is provenance). A grantee with no
live delegation is a no-op: the lock returned nothing, so neither the UPDATE nor the audit row is owed or permitted.
One genuine revocation owes the UPDATE (`EachLockedRow(complete=True)`) and one audit row (`PerEvidence`).

## Cycles

No new lock class or order is introduced: every statement of the legacy commands is present in the same relative
order at the same mode, except that the legacy grant's single `FOR UPDATE` over the grantee's live delegations
is two statements over disjoint predicates (at most one row between them), run back to back. The owner row and
the `gm` row are the only role rows either route locks; the S5-E2 role routes, the transfer, the end route and
recovery reach the same rows in the same order (tests/database/test_r01_s5e6_reveal_delegation_races.py).
"""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection, bindparam, func, insert, select, text, update

from dnd_ai.domain.access import (
    find_live_builtin_gm_assignment,
    find_live_builtin_owner_assignment,
)
from dnd_ai.domain.authoring import normalize_reason
from dnd_ai.domain.authorization import AuthorizationPlan
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
    UniqueWait,
    WriteStep,
)
from dnd_ai.persistence.tables.audit import change_log
from dnd_ai.persistence.tables.security import (
    campaign_memberships,
    character_reveal_delegations,
    membership_roles,
)

from ._pre_write_steps import (
    CAMPAIGN_KEY_SHARE_LOCK,
    CHANGE_LOG_ACTION_FK,
    CHANGE_LOG_ACTOR_FK,
    CHANGE_LOG_UNLOCKED_FK_TARGETS,
    fk_of,
)
from ._shared import lookup_id
from .character_reveal import (
    _GM_KIND,
    _OWNER_KIND,
    RevealDelegationRecipientChangedError,
    RevealDelegationRecipientNotGmError,
    _discover_role_rows,
    _owner_required,
    _require_grantee_in_campaign,
)
from .membership_role_plans import DELEGATION_TRIGGERS, _audit_values, _scope_world
from .memberships import _database_clock, _recheck_caller_is_live_owner
from .reveal_delegation_lifecycle import (
    END_REASON_GM_ASSIGNMENT_LAPSED,
    END_REASON_REVOKED_BY_OWNER,
)

GRANT_COMMAND_NAME = "grant_character_reveal_delegation"
REVOKE_COMMAND_NAME = "revoke_character_reveal_delegation"

cm = campaign_memberships
mr = membership_roles
dl = character_reveal_delegations

#: "No candidate": never a valid v4 id, so a candidate-bound lock bound to it matches nothing.
_NO_CANDIDATE = uuid.UUID(int=0)

# -- locks ----------------------------------------------------------------------------------------------

#: The caller's live owner assignment, `FOR SHARE`, **bound to the row the unlocked discovery found** (bound `row`,
#: `membership`). Its liveness (role template, expiry, membership state, account) is judged by the plain reads after
#: the last wait; the lock holds the row so that a revocation, an end or a relinquishment waits for this transaction.
OWNER_ROW_LOCK = PreLock(
    "reveal_owner_row_share",
    select(mr.c.membership_role_id)
    .where(mr.c.membership_role_id == bindparam("row"))
    .where(mr.c.campaign_membership_id == bindparam("membership"))
    .where(mr.c.revoked_at.is_(None))
    .with_for_update(read=True),
)
#: The grantee's built-in `gm` row, `FOR UPDATE` (the delegation's foreign key and its lifecycle), bound to the
#: discovered row (bound `row`, `membership`).
GM_ROW_LOCK = PreLock(
    "reveal_gm_row_update",
    select(mr.c.membership_role_id)
    .where(mr.c.membership_role_id == bindparam("row"))
    .where(mr.c.campaign_membership_id == bindparam("membership"))
    .where(mr.c.revoked_at.is_(None))
    .with_for_update(),
)
#: The grantee's membership, `FOR NO KEY UPDATE` (never `FOR UPDATE`: two owners granting each other would deadlock on
#: the key share the delegation insert's foreign key takes), bound `membership`, `campaign`.
GRANTEE_MEMBERSHIP_LOCK = PreLock(
    "reveal_grantee_membership_no_key_update",
    select(cm.c.campaign_membership_id)
    .where(cm.c.campaign_membership_id == bindparam("membership"))
    .where(cm.c.campaign_id == bindparam("campaign"))
    .with_for_update(key_share=True),
)
#: The caller's membership, `FOR KEY SHARE`: the weakest mode, what the foreign keys to it need (bound `membership`,
#: `campaign`).
CALLER_MEMBERSHIP_LOCK = PreLock(
    "reveal_caller_membership_key_share",
    select(cm.c.campaign_membership_id)
    .where(cm.c.campaign_membership_id == bindparam("membership"))
    .where(cm.c.campaign_id == bindparam("campaign"))
    .with_for_update(read=True, key_share=True),
)
#: The grantee's live delegation bound to a `gm` row **other than** the one discovered (a lapsed or replaced row),
#: `FOR UPDATE` (bound `grantee`, `gm`).
STALE_DELEGATION_LOCK = PreLock(
    "reveal_stale_delegation_rows",
    select(dl.c.character_reveal_delegation_id)
    .where(dl.c.grantee_campaign_membership_id == bindparam("grantee"))
    .where(dl.c.revoked_at.is_(None))
    .where(dl.c.gm_membership_role_id != bindparam("gm"))
    .order_by(dl.c.character_reveal_delegation_id)
    .with_for_update(),
)
#: The grantee's live delegation bound to the discovered `gm` row, `FOR UPDATE` (bound `grantee`, `gm`). Its evidence
#: is what decides whether a delegation is owed (`PerAbsence`): the live unique index and the drift check
#: (`prepare_grant`) are what prove that an empty run means "none at all".
MATCHING_DELEGATION_LOCK = PreLock(
    "reveal_matching_delegation_row",
    select(dl.c.character_reveal_delegation_id)
    .where(dl.c.grantee_campaign_membership_id == bindparam("grantee"))
    .where(dl.c.revoked_at.is_(None))
    .where(dl.c.gm_membership_role_id == bindparam("gm"))
    .order_by(dl.c.character_reveal_delegation_id)
    .with_for_update(),
)
#: The grantee's live delegation of this campaign, `FOR UPDATE` (revoke; bound `grantee`, `campaign`).
REVOKE_DELEGATION_LOCK = PreLock(
    "reveal_revoke_delegation_row",
    select(dl.c.character_reveal_delegation_id)
    .where(dl.c.grantee_campaign_membership_id == bindparam("grantee"))
    .where(dl.c.campaign_id == bindparam("campaign"))
    .where(dl.c.revoked_at.is_(None))
    .order_by(dl.c.character_reveal_delegation_id)
    .with_for_update(),
)

# -- steps ----------------------------------------------------------------------------------------------

#: An UPDATE that sets `revoked_at` *leaves* the live unique index (`WHERE revoked_at IS NULL`): it inserts no index
#: entry and can never wait for a competitor's key (pinned by the named test, as in S5-E2).
_LEAVES_LIVE_DELEGATION_INDEX = frozenset(
    {
        UniqueWait(
            "security.ux_character_reveal_delegations_live",
            "tests/database/test_r01_s5e2_membership_routes.py::"
            "test_a_delegation_closure_leaving_the_live_index_never_waits_for_a_competing_insert",
        )
    }
)
_INSERT_LIVE_DELEGATION_INDEX = frozenset(
    {
        UniqueWait(
            "security.ux_character_reveal_delegations_live",
            "tests/database/test_r01_s5e6_reveal_delegation_routes.py::"
            "test_a_competing_delegation_for_the_same_grantee_is_a_unique_wait_then_a_classified_409",
        )
    }
)

CLOSE_STALE_DELEGATION = WriteStep(
    name="close_stale_delegation",
    statement=update(dl)
    .where(dl.c.character_reveal_delegation_id == bindparam("delegation"))
    .values(
        revoked_at=func.pg_catalog.clock_timestamp(), end_reason=END_REASON_GM_ASSIGNMENT_LAPSED
    )
    .returning(dl.c.character_reveal_delegation_id),
    cardinality=EachLockedRow(complete=True),
    target=(KeyBind(dl.c.character_reveal_delegation_id, "delegation"),),
    target_lock=STALE_DELEGATION_LOCK,
    unique_waits=_LEAVES_LIVE_DELEGATION_INDEX,
    triggers=DELEGATION_TRIGGERS,
)
INSERT_DELEGATION = WriteStep(
    name="insert_delegation",
    statement=insert(dl)
    .values(
        campaign_id=bindparam("campaign"),
        grantee_campaign_membership_id=bindparam("grantee"),
        gm_membership_role_id=bindparam("gm"),
        granted_by_membership_id=bindparam("actor_membership"),
        reason=bindparam("reason"),
    )
    .returning(dl.c.character_reveal_delegation_id),
    cardinality=PerAbsence(MATCHING_DELEGATION_LOCK),
    fks=(
        FkBinding(
            fk_of(dl, "campaign_id"),
            (KeyBind(dl.c.campaign_id, "campaign"),),
            CAMPAIGN_KEY_SHARE_LOCK,
        ),
        FkBinding(
            fk_of(dl, "grantee_campaign_membership_id"),
            (KeyBind(dl.c.grantee_campaign_membership_id, "grantee"),),
            GRANTEE_MEMBERSHIP_LOCK,
        ),
        FkBinding(
            fk_of(dl, "gm_membership_role_id"),
            (KeyBind(dl.c.gm_membership_role_id, "gm"),),
            GM_ROW_LOCK,
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
    name="audit_delegation_granted",
    statement=insert(change_log)
    .values(
        **_audit_values("character_reveal_delegations", GRANT_COMMAND_NAME),
        changed_fields=bindparam("changed"),
    )
    .returning(change_log.c.change_log_id),
    cardinality=AnyConfirmed((INSERT_DELEGATION,)),
    fks=(CHANGE_LOG_ACTION_FK, CHANGE_LOG_ACTOR_FK),
    value_binds=frozenset({"record", "world", "correlation", "changed"}),
)
REVOKE_DELEGATION = WriteStep(
    name="revoke_delegation",
    statement=update(dl)
    .where(dl.c.character_reveal_delegation_id == bindparam("delegation"))
    .values(
        revoked_at=func.pg_catalog.clock_timestamp(),
        revoked_by_membership_id=bindparam("actor_membership"),
        revocation_reason=bindparam("why"),
        end_reason=END_REASON_REVOKED_BY_OWNER,
    )
    .returning(dl.c.character_reveal_delegation_id),
    cardinality=EachLockedRow(complete=True),
    target=(KeyBind(dl.c.character_reveal_delegation_id, "delegation"),),
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
    name="audit_delegation_revoked",
    statement=insert(change_log)
    .values(
        **_audit_values("character_reveal_delegations", REVOKE_COMMAND_NAME),
        changed_fields=bindparam("changed"),
    )
    .returning(change_log.c.change_log_id),
    cardinality=PerEvidence(REVOKE_DELEGATION_LOCK),
    fks=(CHANGE_LOG_ACTION_FK, CHANGE_LOG_ACTOR_FK),
    value_binds=frozenset({"record", "world", "correlation", "changed"}),
)

GRANT_DECLARATION = PreWriteDeclaration(
    locks=(
        OWNER_ROW_LOCK,
        GM_ROW_LOCK,
        GRANTEE_MEMBERSHIP_LOCK,
        CALLER_MEMBERSHIP_LOCK,
        STALE_DELEGATION_LOCK,
        MATCHING_DELEGATION_LOCK,
        CAMPAIGN_KEY_SHARE_LOCK,
    ),
    steps=(CLOSE_STALE_DELEGATION, INSERT_DELEGATION, GRANT_AUDIT),
    unlocked_fk_targets=CHANGE_LOG_UNLOCKED_FK_TARGETS,
)
REVOKE_DECLARATION = PreWriteDeclaration(
    locks=(OWNER_ROW_LOCK, REVOKE_DELEGATION_LOCK, CALLER_MEMBERSHIP_LOCK),
    steps=(REVOKE_DELEGATION, REVOKE_AUDIT),
    unlocked_fk_targets=CHANGE_LOG_UNLOCKED_FK_TARGETS,
)

# -- prepare and write ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class GrantPrepared:
    """What the grant's lock and read phase established, all before `finalize`."""

    world_id: uuid.UUID
    action_id: uuid.UUID
    reason: str
    gm_assignment: uuid.UUID
    #: The delegation already bound to the live `gm` row (nothing to write), or `None`.
    existing: uuid.UUID | None
    stale: tuple[uuid.UUID, ...]


@dataclass(frozen=True)
class GrantWritten:
    grantee_campaign_membership_id: uuid.UUID
    character_reveal_delegation_id: uuid.UUID
    created: bool
    gm_membership_role_id: uuid.UUID
    replaced_stale_delegation_ids: tuple[uuid.UUID, ...]


@dataclass(frozen=True)
class RevokePrepared:
    world_id: uuid.UUID
    action_id: uuid.UUID
    reason: str
    delegation: uuid.UUID | None


@dataclass(frozen=True)
class RevokeWritten:
    grantee_campaign_membership_id: uuid.UUID
    character_reveal_delegation_id: uuid.UUID | None
    revoked: bool


def _live_delegations(connection: Connection, grantee: uuid.UUID) -> set[uuid.UUID]:
    """The grantee's live delegations, read **without** a lock (the drift check)."""
    return set(
        connection.execute(
            text(
                "SELECT character_reveal_delegation_id FROM security.character_reveal_delegations "
                "WHERE grantee_campaign_membership_id = :grantee AND revoked_at IS NULL"
            ),
            {"grantee": grantee},
        ).scalars()
    )


def prepare_grant(
    connection: Connection,
    plan: AuthorizationPlan,
    *,
    campaign_id: uuid.UUID,
    actor_membership_id: uuid.UUID,
    grantee_campaign_membership_id: uuid.UUID,
    reason: str,
) -> GrantPrepared:
    """Every lock, read and refusal of the grant, in the order of the module docstring, before `finalize`."""
    clean_reason = normalize_reason(reason, required=True)
    assert clean_reason is not None
    # 1. discovery (unlocked, ascending by id); a caller with no live owner row is refused before anything is locked
    discovered = _discover_role_rows(
        connection,
        campaign_id=campaign_id,
        caller_membership_id=actor_membership_id,
        grantee_membership_id=grantee_campaign_membership_id,
    )
    if not any(kind == _OWNER_KIND for _, kind in discovered):
        raise _owner_required(campaign_id, actor_membership_id)
    # 2. role class, one ascending pass, each statement bound to a discovered id
    locked_gm_rows: set[uuid.UUID] = set()
    for row_id, kind in discovered:
        if kind == _OWNER_KIND:
            if not plan.lock(
                connection, OWNER_ROW_LOCK, {"row": row_id, "membership": actor_membership_id}
            ):
                raise _owner_required(campaign_id, actor_membership_id)
        elif kind == _GM_KIND and plan.lock(
            connection, GM_ROW_LOCK, {"row": row_id, "membership": grantee_campaign_membership_id}
        ):
            locked_gm_rows.add(row_id)
    candidate = next((row_id for row_id, kind in discovered if kind == _GM_KIND), _NO_CANDIDATE)
    # 3. unlocked, the membership's campaign never changes: the 404 keeps its place after the owner refusal
    _require_grantee_in_campaign(
        connection,
        campaign_id=campaign_id,
        grantee_campaign_membership_id=grantee_campaign_membership_id,
    )
    # 4. membership class, one ascending pass; one membership is locked once, at the stronger mode
    grantee_lock = (GRANTEE_MEMBERSHIP_LOCK, grantee_campaign_membership_id)
    caller_lock = (CALLER_MEMBERSHIP_LOCK, actor_membership_id)
    ordered = (
        (grantee_lock, caller_lock)
        if grantee_campaign_membership_id <= actor_membership_id
        else (caller_lock, grantee_lock)
    )
    for lock, membership_id in ordered:
        plan.lock(connection, lock, {"membership": membership_id, "campaign": campaign_id})
    # 5. the grantee's delegation rows, then the campaign (`FOR KEY SHARE`, the mode the insert needs)
    binds: dict[str, Any] = {"grantee": grantee_campaign_membership_id, "gm": candidate}
    stale = tuple(key[0] for key in plan.lock(connection, STALE_DELEGATION_LOCK, binds))
    matching = tuple(key[0] for key in plan.lock(connection, MATCHING_DELEGATION_LOCK, binds))
    plan.lock(connection, CAMPAIGN_KEY_SHARE_LOCK, {"campaign": campaign_id})
    # 6. every lock wait is behind us: judge the caller and the grantee at a fresh database instant
    now = _database_clock(connection)
    _recheck_caller_is_live_owner(
        connection, campaign_id=campaign_id, actor_membership_id=actor_membership_id
    )
    gm_assignment = find_live_builtin_gm_assignment(
        connection,
        campaign_id=campaign_id,
        campaign_membership_id=grantee_campaign_membership_id,
        as_of=now,
    )
    if gm_assignment is None:
        raise RevealDelegationRecipientNotGmError(
            f"membership {grantee_campaign_membership_id} holds no live built-in gm assignment "
            f"in campaign {campaign_id}"
        )
    if gm_assignment not in locked_gm_rows or gm_assignment != candidate:
        # The live gm row was not among the rows locked in step 2 (it appeared after discovery): the delegation
        # would bind to a row nobody holds. Retryable; nothing has been written.
        raise RevealDelegationRecipientChangedError(
            f"membership {grantee_campaign_membership_id}'s live gm assignment {gm_assignment} "
            "appeared while the grant waited"
        )
    # 7. drift: the live delegations (read without a lock) are exactly the ones locked above. A delegation the two
    #    candidate-bound locks did not cover would make the empty `PerAbsence` evidence a lie (the unique index
    #    would also refuse its INSERT, a full rollback; this is the classified, retryable form)
    if _live_delegations(connection, grantee_campaign_membership_id) != {*stale, *matching} or (
        stale and matching
    ):
        raise RevealDelegationRecipientChangedError(
            f"membership {grantee_campaign_membership_id}'s live delegations changed while the grant waited"
        )
    return GrantPrepared(
        world_id=_scope_world(connection, campaign_id),
        action_id=lookup_id(connection, "audit", "change_actions", "change_action_id", "created"),
        reason=clean_reason,
        gm_assignment=gm_assignment,
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
    the grantee already holds a delegation bound to the live `gm` row."""
    if prepared.existing is not None:
        return GrantWritten(
            grantee_campaign_membership_id=grantee_campaign_membership_id,
            character_reveal_delegation_id=prepared.existing,
            created=False,
            gm_membership_role_id=prepared.gm_assignment,
            replaced_stale_delegation_ids=(),
        )
    for delegation in prepared.stale:
        plan.execute(connection, CLOSE_STALE_DELEGATION, {"delegation": delegation})
    outcome = plan.execute(
        connection,
        INSERT_DELEGATION,
        {
            "campaign": campaign_id,
            "grantee": grantee_campaign_membership_id,
            "gm": prepared.gm_assignment,
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
                "gm_membership_role_id": str(prepared.gm_assignment),
                "replaced_stale_delegation": bool(prepared.stale),
            },
        },
    )
    return GrantWritten(
        grantee_campaign_membership_id=grantee_campaign_membership_id,
        character_reveal_delegation_id=delegation_id,
        created=True,
        gm_membership_role_id=prepared.gm_assignment,
        replaced_stale_delegation_ids=prepared.stale,
    )


def prepare_revoke(
    connection: Connection,
    plan: AuthorizationPlan,
    *,
    campaign_id: uuid.UUID,
    actor_membership_id: uuid.UUID,
    grantee_campaign_membership_id: uuid.UUID,
    reason: str,
) -> RevokePrepared:
    """Every lock, read and refusal of the revoke, before `finalize`."""
    clean_reason = normalize_reason(reason, required=True)
    assert clean_reason is not None
    # the D3 gate: the caller's live owner row, discovered without a lock, then held `FOR SHARE`
    owner_row = find_live_builtin_owner_assignment(
        connection, campaign_id=campaign_id, campaign_membership_id=actor_membership_id
    )
    if owner_row is None or not plan.lock(
        connection, OWNER_ROW_LOCK, {"row": owner_row, "membership": actor_membership_id}
    ):
        raise _owner_required(campaign_id, actor_membership_id)
    _require_grantee_in_campaign(
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
    # DEF-013: the caller again, at a fresh instant, after the last lock wait
    _recheck_caller_is_live_owner(
        connection, campaign_id=campaign_id, actor_membership_id=actor_membership_id
    )
    return RevokePrepared(
        world_id=_scope_world(connection, campaign_id),
        action_id=lookup_id(connection, "audit", "change_actions", "change_action_id", "updated"),
        reason=clean_reason,
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
            character_reveal_delegation_id=None,
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
        character_reveal_delegation_id=prepared.delegation,
        revoked=True,
    )


__all__ = [
    "GRANT_DECLARATION",
    "REVOKE_DECLARATION",
    "GrantPrepared",
    "GrantWritten",
    "RevokePrepared",
    "RevokeWritten",
    "prepare_grant",
    "prepare_revoke",
    "write_grant",
    "write_revoke",
]
