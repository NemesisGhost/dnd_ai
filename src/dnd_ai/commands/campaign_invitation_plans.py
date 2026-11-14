"""Campaign-invitation creation and revocation as keyed pre-write plans (R01 S5-D; plan section 6.25).

`create_campaign_invitation` and `revoke_campaign_invitation` in `campaign_invitations.py` stay as the
direct, unguarded commands (tests and any caller without a request plan). The two routes use the
declarations and the lock and write phases in this module instead, so that **every lock is taken before
`plan.finalize`** and **every write is a declared step after it**.

Neither command writes a table of `AUTHORITY_READER_TABLES`, but both are *pre-write* routes: a post-write
plan cannot produce campaign-lock evidence, and the reservation's campaign foreign key is deferred (the
J-1' opt-in, plan 6.21), so the early campaign lock the reservation used to take is replaced by the
explicit, ordered locks below.

## Lock sequences (the whole sequence; implicit foreign-key locks included)

Key to modes: KS `FOR KEY SHARE`, U `FOR UPDATE`. "reservation" is `begin_idempotent_request`.

**Create (keyed).**

1. advisory key lock (the first lock, taken by the reservation; holds nothing else)
2. reservation `INSERT`: the actor's account row, KS (the actor FK); the campaign FK is **deferred**, so no
   campaign lock is taken here
3. the inviting manager's own membership row, KS (`plan.lock`; the open membership of this campaign only)
4. the campaign row, KS (`plan.lock`; also the evidence the deferral obligation needs)
5. the reservation row, U (`plan.lock`; our own insert: the receipt's update target)
6. `plan.finalize`: authority is judged here, after every lock above
7. invitation `INSERT`: FK KS on the campaign and the membership (both already held: re-acquired), the
   `ux_campaign_invitations_token_hash` unique index (a wait only for a competing equal hash, never in
   practice: the token is 256 random bits), the actor-scope trigger (a plain read of the membership)
8. `audit.change_log` `INSERT`: FK KS on `change_actions` (seed data) and on the actor's account (held)
9. receipt `UPDATE` (the reservation row, held U)
10. COMMIT: the deferred campaign FK check re-acquires the held campaign KS; nothing else is queued

**Create (no key).** Steps 3, 4, 6, 7, 8 only; the actor's account KS comes with the audit insert (step 8).

**Revoke (keyed).**

1. advisory key lock
2. reservation `INSERT`: the actor's account row, KS; the campaign FK deferred
3. **the invitation row, U** (`plan.lock`, by invitation id *and* campaign id: an invitation of another
   campaign locks nothing and is reported as the same not-in-campaign error as an absent one)
3a. **the same row again, U, only while outstanding** (`REVOKE_OUTSTANDING_LOCK`: not revoked, not
   accepted; already held, so no wait and no order change). Its evidence is database state under the
   invitation lock: one key for a genuine revocation, none for an already-revoked invitation
4. the campaign row, KS (`plan.lock`; the deferral evidence)
5. the reservation row, U
6. validation reads (already revoked: a no-op; accepted or expired: refused), then `plan.finalize`
7. the invitation `UPDATE`, declared `EachLockedRow(complete=True)` over (3a): **required** for an
   outstanding invitation, **refused** (`TARGET_NOT_LOCKED`) for a revoked one; the actor-scope trigger again
8. `audit.change_log` `INSERT`, `Between(0, 1)`: attempted only for a genuine revocation, but the plan
   cannot *require* it (an INSERT cannot be `EachLockedRow`, and a declaration is chosen only by the
   reservation outcome). A recorded gap: plan 6.25.3
9. receipt `UPDATE`
10. COMMIT: as for create

**Revoke (no key).** Steps 3, 4, 6, 7, 8.

### Why revoke takes the invitation before the campaign (the one exception to the global order)

The approved global order (review section 5 item 5) takes the campaign before target rows. Revocation
deliberately does the opposite, because acceptance cannot be reordered: a token names no campaign, so
acceptance reaches the campaign only **through the invitation row** it locks first (`accept_campaign_
invitation`, and onboarding after its session row). Acceptance then takes the accepting user's membership
(NO KEY UPDATE) and the campaign (SHARE), and a *reopening* acceptance upgrades to the campaign `FOR UPDATE`
at COMMIT (the retention trigger). A revoker that held the campaign KS while waiting for the invitation
(the generic order, and what the immediate reservation FK did before this slice) deadlocks with that
upgrade: the acceptance waits at COMMIT for the revoker's campaign KS, the revoker waits for the
acceptance's invitation row. With the invitation first the revoker holds nothing the acceptance wants while
it waits, and a waiting acceptance holds nothing the revoker wants.

Creation has no such constraint (it locks no invitation row), so it uses the generic order: the actor's
membership, then the campaign. That order is what separates it from a keyed `end` of the inviting manager,
which holds the membership `FOR UPDATE` and then wants the campaign `FOR UPDATE`: the creator used to hold
the campaign KS (reservation FK) and then ask for the membership KS (insert FK), the reverse.

Not changed here, and not claimed: two *reopening* acceptances in one campaign still deadlock at COMMIT
(the retention trigger's upgrade of two campaign `FOR SHARE` holders; `campaign_invitations.py`, "Reopening,
at COMMIT"), and the F6 three-transaction residual.
"""

import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from sqlalchemy import Connection, bindparam, func, insert, select, text, update

from dnd_ai.domain.authorization import AuthorizationPlan, ReservationDeclarations
from dnd_ai.domain.authorization_steps import (
    Between,
    EachLockedRow,
    Event,
    Exactly,
    FkBinding,
    FunctionPin,
    KeyBind,
    Level,
    PreLock,
    PreWriteDeclaration,
    Timing,
    TriggerPin,
    UniqueWait,
    WriteStep,
)
from dnd_ai.persistence.tables.audit import change_log
from dnd_ai.persistence.tables.security import campaign_invitations, campaign_memberships

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
from .campaign_invitations import (
    InvitationNotInCampaignError,
    InvitationNotRevocableError,
    _hash_invitation_token,
)

CREATE_COMMAND_NAME = "create_campaign_invitation"
REVOKE_COMMAND_NAME = "revoke_campaign_invitation"
_TOKEN_ENTROPY_BYTES: Final = 32
DEFAULT_INVITATION_TTL: Final = timedelta(days=7)
_TOKEN_HASH_INDEX: Final = "security.ux_campaign_invitations_token_hash"

ci = campaign_invitations
cm = campaign_memberships

#: `tr_campaign_invitations_enforce_actor_scope` (migration 080): BEFORE INSERT OR UPDATE, row level. It
#: reads the inviting membership's campaign (no lock) and refuses a mismatch. Pinned by name, timing,
#: events and the md5 of the function source; a change to any of them fails the catalogue test.
_ACTOR_SCOPE_TRIGGER = TriggerPin(
    name="tr_campaign_invitations_enforce_actor_scope",
    timing=Timing.BEFORE,
    level=Level.ROW,
    events=frozenset({Event.INSERT, Event.UPDATE}),
    update_columns=None,
    when_hash=None,
    enabled="O",
    constraint_trigger=False,
    deferrable=False,
    initially_deferred=False,
    args=(),
    function=FunctionPin(
        schema="security",
        name="enforce_campaign_invitation_actor_scope",
        arg_types="",
        language="plpgsql",
        security_definer=False,
        config=None,
        volatility="v",
        source_md5="f3a3baf1e68dc04fee9c4cac8a93ccc2",
    ),
)

# -- create: locks, steps, declarations -----------------------------------------------------------------

#: The inviting manager's own open membership of this campaign, `FOR KEY SHARE` (bound `membership`,
#: `campaign`). An ended membership matches nothing: the lock phase then returns no row and `finalize`
#: refuses the request with the capability requirement's own error.
CREATE_ACTOR_MEMBERSHIP_LOCK = PreLock(
    "actor_membership_key_share",
    select(cm.c.campaign_membership_id)
    .where(cm.c.campaign_membership_id == bindparam("membership"))
    .where(cm.c.campaign_id == bindparam("campaign"))
    .where(cm.c.ended_at.is_(None))
    .with_for_update(read=True, key_share=True),
)
CREATE_CAMPAIGN_LOCK = CAMPAIGN_KEY_SHARE_LOCK
CREATE_RECEIPT_LOCK = RECEIPT_LOCK
INSERT_INVITATION = WriteStep(
    name="insert_invitation",
    statement=insert(ci)
    .values(
        campaign_id=bindparam("campaign"),
        invited_email=bindparam("email"),
        invitation_token_hash=bindparam("token_hash"),
        invited_by_membership_id=bindparam("membership"),
        expires_at=bindparam("expires_at"),
    )
    .returning(ci.c.campaign_invitation_id),
    cardinality=Exactly(1),
    fks=(
        FkBinding(
            fk_of(ci, "campaign_id"), (KeyBind(ci.c.campaign_id, "campaign"),), CREATE_CAMPAIGN_LOCK
        ),
        FkBinding(
            fk_of(ci, "invited_by_membership_id"),
            (KeyBind(ci.c.invited_by_membership_id, "membership"),),
            CREATE_ACTOR_MEMBERSHIP_LOCK,
        ),
    ),
    value_binds=frozenset({"email", "token_hash", "expires_at"}),
    unique_waits=frozenset(
        {
            UniqueWait(
                _TOKEN_HASH_INDEX,
                "tests/database/test_r01_s5d_invitation_routes.py::"
                "test_a_competing_equal_token_hash_is_a_unique_wait",
            )
        }
    ),
    triggers=frozenset({_ACTOR_SCOPE_TRIGGER}),
)
CREATE_AUDIT = WriteStep(
    name="audit_created",
    statement=insert(change_log)
    .values(
        change_action_id=bindparam("action"),
        schema_name="security",
        table_name="campaign_invitations",
        record_id=bindparam("record"),
        world_id=bindparam("world"),
        actor_user_id=bindparam("actor"),
        correlation_id=bindparam("correlation"),
        command_name="create_campaign_invitation",
    )
    .returning(change_log.c.change_log_id),
    cardinality=Exactly(1),
    fks=(CHANGE_LOG_ACTION_FK, CHANGE_LOG_ACTOR_FK),
    value_binds=frozenset({"record", "world", "correlation"}),
)
CREATE_RECEIPT = RECEIPT_STEP

CREATE_DECLARATIONS = ReservationDeclarations(
    reserved=PreWriteDeclaration(
        locks=(CREATE_ACTOR_MEMBERSHIP_LOCK, CREATE_CAMPAIGN_LOCK, CREATE_RECEIPT_LOCK),
        steps=(INSERT_INVITATION, CREATE_AUDIT, CREATE_RECEIPT),
        unlocked_fk_targets=CHANGE_LOG_UNLOCKED_FK_TARGETS,
    ),
    unkeyed=PreWriteDeclaration(
        locks=(CREATE_ACTOR_MEMBERSHIP_LOCK, CREATE_CAMPAIGN_LOCK),
        steps=(INSERT_INVITATION, CREATE_AUDIT),
        unlocked_fk_targets=CHANGE_LOG_UNLOCKED_FK_TARGETS,
    ),
)

# -- revoke: locks, steps, declarations -----------------------------------------------------------------

#: The invitation of this campaign, `FOR UPDATE` (bound `invitation`, `campaign`).
REVOKE_INVITATION_LOCK = PreLock(
    "invitation_row",
    select(ci.c.campaign_invitation_id)
    .where(ci.c.campaign_invitation_id == bindparam("invitation"))
    .where(ci.c.campaign_id == bindparam("campaign"))
    .with_for_update(),
)
#: The same row again, `FOR UPDATE`, **only while it is still outstanding** (not revoked, not accepted). It is
#: taken right after `REVOKE_INVITATION_LOCK`, so the row is already held and no wait or order changes. What
#: it returns is database state established under the invitation lock, not caller data: one key for a
#: genuine revocation (or an expired invitation, which is refused before `finalize`), none for an
#: already-revoked invitation. It is the `target_lock` of the revoke UPDATE, which is `EachLockedRow(
#: complete=True)`: the update is therefore *required* exactly when this evidence exists, and *refused*
#: (`TARGET_NOT_LOCKED`) when it does not.
REVOKE_OUTSTANDING_LOCK = PreLock(
    "invitation_outstanding_row",
    select(ci.c.campaign_invitation_id)
    .where(ci.c.campaign_invitation_id == bindparam("invitation"))
    .where(ci.c.revoked_at.is_(None))
    .where(ci.c.accepted_by_user_id.is_(None))
    .where(ci.c.accepted_at.is_(None))
    .with_for_update(),
)
REVOKE_CAMPAIGN_LOCK = CAMPAIGN_KEY_SHARE_LOCK
REVOKE_RECEIPT_LOCK = RECEIPT_LOCK
REVOKE_INVITATION = WriteStep(
    name="revoke_invitation",
    statement=update(ci)
    .where(ci.c.campaign_invitation_id == bindparam("invitation"))
    .values(revoked_at=func.pg_catalog.now())
    .returning(ci.c.campaign_invitation_id),
    cardinality=EachLockedRow(complete=True),
    target=(KeyBind(ci.c.campaign_invitation_id, "invitation"),),
    target_lock=REVOKE_OUTSTANDING_LOCK,
    triggers=frozenset({_ACTOR_SCOPE_TRIGGER}),
)
REVOKE_AUDIT = WriteStep(
    name="audit_revoked",
    statement=insert(change_log)
    .values(
        change_action_id=bindparam("action"),
        schema_name="security",
        table_name="campaign_invitations",
        record_id=bindparam("record"),
        world_id=bindparam("world"),
        actor_user_id=bindparam("actor"),
        correlation_id=bindparam("correlation"),
        command_name="revoke_campaign_invitation",
    )
    .returning(change_log.c.change_log_id),
    cardinality=Between(0, 1),
    fks=(CHANGE_LOG_ACTION_FK, CHANGE_LOG_ACTOR_FK),
    value_binds=frozenset({"record", "world", "correlation"}),
)
REVOKE_RECEIPT = RECEIPT_STEP

REVOKE_DECLARATIONS = ReservationDeclarations(
    reserved=PreWriteDeclaration(
        locks=(
            REVOKE_INVITATION_LOCK,
            REVOKE_OUTSTANDING_LOCK,
            REVOKE_CAMPAIGN_LOCK,
            REVOKE_RECEIPT_LOCK,
        ),
        steps=(REVOKE_INVITATION, REVOKE_AUDIT, REVOKE_RECEIPT),
        unlocked_fk_targets=CHANGE_LOG_UNLOCKED_FK_TARGETS,
    ),
    unkeyed=PreWriteDeclaration(
        locks=(REVOKE_INVITATION_LOCK, REVOKE_OUTSTANDING_LOCK, REVOKE_CAMPAIGN_LOCK),
        steps=(REVOKE_INVITATION, REVOKE_AUDIT),
        unlocked_fk_targets=CHANGE_LOG_UNLOCKED_FK_TARGETS,
    ),
)

# -- the lock and write phases --------------------------------------------------------------------------


@dataclass(frozen=True)
class PreparedCreate:
    token: str
    token_hash: str
    expires_at: datetime
    change_action_id: uuid.UUID


def prepare_create_invitation(
    connection: Connection,
    plan: AuthorizationPlan,
    *,
    campaign_id: uuid.UUID,
    invited_by_membership_id: uuid.UUID,
    reservation_id: uuid.UUID | None,
    ttl: timedelta = DEFAULT_INVITATION_TTL,
) -> PreparedCreate:
    """The create lock phase and its reads, all before `finalize`: the inviting membership, then the
    campaign, then (keyed) our own reservation row (module docstring, "Create"). The token is generated
    here and never stored; the expiry is the database's `now() + ttl`, as before."""
    plan.lock(
        connection,
        CREATE_ACTOR_MEMBERSHIP_LOCK,
        {"membership": invited_by_membership_id, "campaign": campaign_id},
    )
    plan.lock(connection, CREATE_CAMPAIGN_LOCK, {"campaign": campaign_id})
    if reservation_id is not None:
        plan.lock(connection, CREATE_RECEIPT_LOCK, {"receipt": reservation_id})
    token = secrets.token_urlsafe(_TOKEN_ENTROPY_BYTES)
    expires_at = connection.execute(
        text("SELECT pg_catalog.now() + :ttl"), {"ttl": ttl}
    ).scalar_one()
    return PreparedCreate(
        token=token,
        token_hash=_hash_invitation_token(token),
        expires_at=expires_at,
        change_action_id=lookup_id(
            connection, "audit", "change_actions", "change_action_id", "created"
        ),
    )


def write_create_invitation(
    connection: Connection,
    plan: AuthorizationPlan,
    prepared: PreparedCreate,
    *,
    campaign_id: uuid.UUID,
    invited_by_membership_id: uuid.UUID,
    invited_email: str | None,
) -> uuid.UUID:
    """The declared invitation insert, after `finalize`. Returns the new invitation id."""
    outcome = plan.execute(
        connection,
        INSERT_INVITATION,
        {
            "campaign": campaign_id,
            "email": invited_email,
            "token_hash": prepared.token_hash,
            "membership": invited_by_membership_id,
            "expires_at": prepared.expires_at,
        },
    )
    (invitation_id,) = outcome.keys[0]
    assert isinstance(invitation_id, uuid.UUID)
    return invitation_id


@dataclass(frozen=True)
class PreparedRevoke:
    will_revoke: bool
    change_action_id: uuid.UUID


def prepare_revoke_invitation(
    connection: Connection,
    plan: AuthorizationPlan,
    *,
    campaign_id: uuid.UUID,
    campaign_invitation_id: uuid.UUID,
    reservation_id: uuid.UUID | None,
) -> PreparedRevoke:
    """The revoke lock phase and its reads, before `finalize`: **the invitation first, then the campaign**
    (module docstring, "Why revoke takes the invitation before the campaign"), then (keyed) our own
    reservation row. The domain refusals are raised here, as before: not in the campaign (a 404), accepted
    or expired (a 409); already revoked is a no-op that attempts no write. Whether the update is required is
    decided by `REVOKE_OUTSTANDING_LOCK`'s evidence, taken under the invitation lock (see its comment)."""
    locked = plan.lock(
        connection,
        REVOKE_INVITATION_LOCK,
        {"invitation": campaign_invitation_id, "campaign": campaign_id},
    )
    outstanding = (
        plan.lock(connection, REVOKE_OUTSTANDING_LOCK, {"invitation": campaign_invitation_id})
        if locked
        else ()
    )
    plan.lock(connection, REVOKE_CAMPAIGN_LOCK, {"campaign": campaign_id})
    if reservation_id is not None:
        plan.lock(connection, REVOKE_RECEIPT_LOCK, {"receipt": reservation_id})
    if not locked:
        raise InvitationNotInCampaignError(
            f"invitation {campaign_invitation_id} does not belong to campaign {campaign_id}"
        )
    row = (
        connection.execute(
            text("""
                SELECT accepted_by_user_id, accepted_at, revoked_at, (expires_at <= now()) AS expired
                FROM security.campaign_invitations
                WHERE campaign_invitation_id = :invitation
            """),
            {"invitation": campaign_invitation_id},
        )
        .mappings()
        .one()
    )
    if row["revoked_at"] is not None:
        will_revoke = False
    elif row["accepted_by_user_id"] is not None or row["accepted_at"] is not None:
        raise InvitationNotRevocableError(
            f"invitation {campaign_invitation_id} has already been accepted"
        )
    elif row["expired"]:
        raise InvitationNotRevocableError(f"invitation {campaign_invitation_id} is expired")
    else:
        will_revoke = True
    if will_revoke != bool(outstanding):  # the lock's own evidence and the row read cannot differ
        raise RuntimeError("the invitation's state changed under its own lock")
    return PreparedRevoke(
        will_revoke=will_revoke,
        change_action_id=lookup_id(
            connection, "audit", "change_actions", "change_action_id", "updated"
        ),
    )


def write_revoke_invitation(
    connection: Connection, plan: AuthorizationPlan, *, campaign_invitation_id: uuid.UUID
) -> None:
    """The declared invitation update, after `finalize` (attempted only by a request that revokes)."""
    plan.execute(connection, REVOKE_INVITATION, {"invitation": campaign_invitation_id})
