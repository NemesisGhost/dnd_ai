"""Resource grants and character relationships as keyed-optional pre-write plans (R01 S5-E4; plan 6.31).

`grant_character_relationship`, `change_character_relationship`, `revoke_character_relationship`,
`create_resource_grant` and `revoke_resource_grant` in `access_grants.py` stay as the direct, unguarded commands.
The five routes (`dnd_ai.api.access_grants`) use the declarations and the lock, read and write phases below, so that
**every lock is taken before `plan.finalize`**, every read a refusal depends on happens before it, and every write is
a declared step after it.

## The commands, as they were (S5-E4 inventory)

All five: capability `access.manage` (the route dependency judges it first), `Idempotency-Key` optional, the
campaign's `access.manage` actor recorded as `granted_by_membership_id`, one `audit.change_log` row per *actual*
change (`entity_id` and `event_id` null, `world_id` the campaign's own).

| Route | Success | Refusals, in the order the command raised them | No-op |
|---|---|---|---|
| `POST /memberships/{id}/character-relationships` | 201 `{membership_character_relationship_id}` | membership not in campaign (404); membership ended, status not active or inactive (409); campaign not active (409); account not active (409); character missing, other world or not active (404); timeline of another world (404); `to` without `from` (400); world time of another world (404); `to` not after `from` (400); type missing or inactive (404); the INSERT's foreign keys and `ux_membership_character_relationships_active_type` (400, 409) | none |
| `POST /character-relationships/{id}/change` | 201 `{new id}` | relationship not in campaign (404); campaign not active (409); relationship not an eligible active assignment (409: revoked, expired, a closed period, membership ended or not active, account or character no longer eligible); new type missing or inactive (404); same type (422) | none |
| `POST /character-relationships/{id}/revoke` | 200 `{id}` | relationship not in campaign (404) | already revoked: 200, no write, no audit row |
| `POST /resource-grants` | 201 `{resource_grant_id}` | grantee membership (404, 409) or group (404, 409) as above; campaign not active (409); account not active (409); target missing, other world/campaign or not active (404; an own-column kind passed through `entity_id` is refused too); capability missing, inactive or not grantable for the kind (404); the INSERT's `CHECK`s and foreign keys (400) and `ux_resource_grants_active` (409) | none |
| `POST /resource-grants/{id}/revoke` | 200 `{id}` | grant not in campaign (404) | already revoked: 200, no write, no audit row |

Changes this module makes, all unreachable by a request that was valid and uncontended before:

- A request whose shape the **database `CHECK`** would have refused (no grantee or two, no target or several) and a
  referenced child row that does not exist (an entity that is not a character, quest, knowledge item or event) are
  refused **before `finalize`** with the same 400 `validation_failed` the constraint produced after the INSERT
  (`GrantRowRefusedError`); the constraint stays the backstop. Pre-write steps cannot be given a foreign key whose
  lock never ran, so the INSERT is not attempted for them.
- The change's eligibility "not expired" is judged at a fresh `clock_timestamp()` after the last lock wait (DEF-013
  style) rather than at the transaction start: a relationship that expired while the request waited is refused
  (409), where it was changed before.

## Lock sequences (the approved ascending class order, each row once at the mode it needs, no upgrades)

Key to modes: S `FOR SHARE`, KS `FOR KEY SHARE`, U `FOR UPDATE`. A keyed request starts with the advisory key lock and
the reservation `INSERT` (the actor's account KS; the campaign FK deferred) and ends with the receipt row U.

World -> role rows -> delegation rows -> memberships -> accounts -> campaign -> catalogue rows -> targets.

| Route | Locks |
|---|---|
| grant relationship | actor's unrevoked role rows S; actor's open membership S and the target membership U (C4, ascending id, the target first when they are the same row); actor's account S, the target's account KS (S5-A); **campaign U** (the command took it U; it excludes in-flight authors' stability inputs); the relationship type row U (by code); the character's entity row U and its `character.characters` row KS; the timeline row KS and the world-time rows KS, only when supplied (each the INSERT's foreign key, taken here instead of implicitly); [receipt U] |
| change relationship | the same actor rows, then the **owning membership** U; accounts; **campaign U**; the new type row U; the character's entity U and `characters` KS; the old relationship row U (candidate-bound); the timeline and world-time rows KS the new row carries forward; [receipt U] |
| revoke relationship | actor's role rows S, open membership S, account S; **campaign KS**; the relationship row U, only while it is unrevoked (candidate-bound; its evidence is the "this request revokes" fact); [receipt U] |
| create grant, **membership grantee** | the grantee's role pass is the actor's alone (S); actor's membership S and the grantee's U (C4); actor's account S, the grantee's account KS; **campaign U**; the capability row U (by code); the target (entity U and the kind's child row KS, or the session row U); [receipt U] |
| create grant, **group grantee** | actor's role rows S, **then the group row U** (R01 S5-E4 correction SA-1, order AO-1), then actor's open membership S, actor's account S; **campaign U**; capability U; the target; [receipt U] |
| revoke grant | actor's role rows S, open membership S, account S; **campaign KS**; the grant row U, only while it is unrevoked (campaign- and id-bound); [receipt U] |

### Why the group grantee's row comes right after the actor's role rows (AO-1; correction SA-1, finding NF-1)

For every transaction that locks an access-group row the order is: [keyed prefix] -> **role rows -> delegation rows -> group row** ->
memberships -> accounts -> campaign -> catalogue rows -> targets -> dependent rows. This route's group-grantee branch locks the
actor's role rows `FOR SHARE` and only then the group row `FOR UPDATE`.

The first S5-E4 version locked the group **before** the actor's role rows (a "group first" exception to the class order). That
order closes a three-party cycle with revelation creation and a role writer: revelation creation holds its caller's role rows
`FOR SHARE` and waits for the group `FOR KEY SHARE`; this route holds the group and waits for its actor's role rows `FOR SHARE`;
a role revoke by the revelation's caller holds the actor's role row `FOR UPDATE` and waits for the caller's rows. Reproduced
through the application (a 40P01 with a different victim per run) and absent at the S5-E4 parent. With the role rows first, a
transaction that holds a group row never waits for a role row, so no cycle of that shape can contain a group-row wait.

What stays: the group row still comes **before** the actor's membership, the memberships, the accounts and the campaign. A
grant that locked the actor's membership `FOR SHARE` before the group would deadlock with a concurrent add that names the actor
as a member (`FOR NO KEY UPDATE` on that membership while holding the group), and the campaign before the group is still the
rejected class order. Both are pinned as deadlocks by tests. A membership grantee has no group lock and is unchanged.

## Why the lock sets are complete

- *The target membership.* U: it conflicts with the `FOR KEY SHARE` of every creator's foreign key (relationships,
  grants) and every `FOR UPDATE` of an end; the eligibility read that follows therefore cannot be undone before
  COMMIT. The grantee/owner's account is KS (S5-A): the real status writer's `FOR UPDATE` still conflicts.
- *The dependent rows of the target membership (`END_RELATIONSHIPS`, `END_GRANTS`).* An end locks them after the
  membership; this route holds the membership first (the same class order), so the two serialize at the membership.
  The closers (revoke relationship, revoke grant) lock only the row, last, and are leaves.
- *Every foreign key the INSERT checks has a held lock before `finalize`.* The membership, the actor's membership,
  the campaign, the capability or type, the group, the entity, the child row, the session, the timeline and the
  world times are each locked above, so no INSERT FK check can first-acquire a row (the plan refuses a foreign key
  whose lock evidence is missing).
- *Absence is not assumed.* The "this revokes" and "this audits" obligations of the two revokes are derived from the
  successfully executed outstanding lock (`EachLockedRow(complete=True)`, `PerEvidence`); a lock that never ran is not
  empty evidence.

## Declared obligations

| Route | Writes |
|---|---|
| grant relationship | the relationship `Exactly(1)`, one audit row `Exactly(1)`, receipt `Exactly(1)` (keyed) |
| change relationship | the old row `Exactly(1)`, the new row `Exactly(1)`, one audit row `Exactly(1)`, receipt |
| revoke relationship | the row `EachLockedRow(complete=True)`, audit `PerEvidence` over the outstanding lock, receipt |
| create grant | the grant `Exactly(1)`, one audit row `Exactly(1)`, receipt |
| revoke grant | the row `EachLockedRow(complete=True)`, audit `PerEvidence`, receipt |

Only the two revokes have a legitimate no-op; each owes and may do nothing but its receipt. No `Between`, no optional
bound for another branch. A duplicate relationship, duplicate grant, bad effect value or unknown reference that gets
through every pre-check is refused by the constraint at the declared INSERT (409/400, as before), after `finalize`,
rolling everything back.
"""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection, bindparam, func, insert, or_, select, text, update

from dnd_ai.domain.access import RESOURCE_GRANT_CAPABILITY_CATALOG
from dnd_ai.domain.authorization import AuthorizationPlan, ReservationDeclarations
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
from dnd_ai.domain.errors import SafeMessageError
from dnd_ai.persistence.tables.audit import change_log
from dnd_ai.persistence.tables.campaign import sessions, timelines
from dnd_ai.persistence.tables.characters import characters
from dnd_ai.persistence.tables.core import entities, world_times
from dnd_ai.persistence.tables.knowledge import knowledge_items
from dnd_ai.persistence.tables.narrative import events, quests
from dnd_ai.persistence.tables.security import (
    access_groups,
    campaign_memberships,
    capabilities,
    character_relationship_types,
    membership_character_relationships,
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
from ._shared import lookup_id, validate_session_campaign
from .access_grants import (
    AccessGroupNotActiveError,
    AccessGroupNotInCampaignError,
    CampaignNotActiveError,
    ChangeCharacterRelationshipNoOpError,
    CharacterRelationshipNotActiveError,
    InvalidRelationshipPeriodError,
    MembershipNotActiveError,
    MembershipNotInCampaignError,
    RelationshipTypeNotActiveError,
    ResourceGrantCapabilityNotGrantableError,
    ResourceGrantNotInCampaignError,
    TargetNotInCampaignWorldError,
)
from .campaign_lifecycle_plans import (
    ACTOR_ACCOUNT_LOCK,
    ACTOR_MEMBERSHIP_LOCK,
    ACTOR_ROLES_LOCK,
    CAMPAIGN_ROW_LOCK,
)
from .membership_end_plans import GRANT_TRIGGERS, RELATIONSHIP_TRIGGERS
from .membership_role_plans import (
    _AUDIT_BINDS,
    TARGET_ACCOUNT_LOCK,
    TARGET_MEMBERSHIP_LOCK,
    _audit_values,
    _scope_world,
    lock_memberships,
)

GRANT_RELATIONSHIP_COMMAND_NAME = "grant_character_relationship"
CHANGE_RELATIONSHIP_COMMAND_NAME = "change_character_relationship"
REVOKE_RELATIONSHIP_COMMAND_NAME = "revoke_character_relationship"
CREATE_GRANT_COMMAND_NAME = "create_resource_grant"
REVOKE_GRANT_COMMAND_NAME = "revoke_resource_grant"

cm = campaign_memberships
mcr = membership_character_relationships
rg = resource_grants

# The six target columns of `security.resource_grants`, in the command's order, with the lock-and-table of each.
RESOURCE_GRANT_TARGET_FIELDS = (
    "character_id",
    "entity_id",
    "knowledge_item_id",
    "quest_id",
    "session_id",
    "event_id",
)

# core.entity_types.code values with a dedicated target column (see `access_grants`)
_OWN_COLUMN_ENTITY_TYPE_CODES = frozenset(
    {"character", "npc", "player_character", "event", "quest", "knowledge_item"}
)
_CHARACTER_ENTITY_TYPE_CODES = frozenset({"character", "npc", "player_character"})


class GrantRowRefusedError(SafeMessageError):
    """The request names a row shape or a referenced row the INSERT's own constraint would have refused (the exactly-one
    grantee and target `CHECK`s, a foreign key to a child row that does not exist). Raised **before `finalize`**
    because a declared INSERT cannot be given a foreign key whose lock never returned the row. The same 400 and
    public message the constraint's SQLSTATE `23514`/`23503` produced (`dnd_ai.api.errors.handle_integrity_error`)."""

    safe_status_code = 400
    safe_error_code = "validation_failed"
    safe_message = "The request could not be processed."


# -- locks ----------------------------------------------------------------------------------------------

#: The group grantee, `FOR UPDATE`, taken **right after the actor's role rows** (module docstring, AO-1 and NF-1).
#: Bound `group`, `campaign`; a group of another campaign matches nothing.
GROUP_GRANTEE_LOCK = PreLock(
    "grantee_group_update",
    select(access_groups.c.access_group_id)
    .where(access_groups.c.access_group_id == bindparam("group"))
    .where(access_groups.c.campaign_id == bindparam("campaign"))
    .with_for_update(),
)
#: A relationship type by code, `FOR UPDATE` (the grant; bound `code`), and by id (the change; bound `type`).
RELATIONSHIP_TYPE_BY_CODE_LOCK = PreLock(
    "relationship_type_by_code",
    select(character_relationship_types.c.character_relationship_type_id)
    .where(character_relationship_types.c.code == bindparam("code"))
    .with_for_update(),
)
RELATIONSHIP_TYPE_BY_ID_LOCK = PreLock(
    "relationship_type_by_id",
    select(character_relationship_types.c.character_relationship_type_id)
    .where(character_relationship_types.c.character_relationship_type_id == bindparam("type"))
    .with_for_update(),
)
#: A capability by code, `FOR UPDATE` (bound `code`).
CAPABILITY_LOCK = PreLock(
    "capability_by_code",
    select(capabilities.c.capability_id)
    .where(capabilities.c.code == bindparam("code"))
    .with_for_update(),
)
#: The entity row of a target, `FOR UPDATE` (bound `entity`): the command's own target lock (an archive takes it too).
TARGET_ENTITY_LOCK = PreLock(
    "target_entity_update",
    select(entities.c.entity_id)
    .where(entities.c.entity_id == bindparam("entity"))
    .with_for_update(),
)
#: The class-table row a foreign key references, `FOR KEY SHARE` (the key share the INSERT would take implicitly,
#: taken here so it is evidence before `finalize`). Each bound to its own key.
CHARACTER_ROW_LOCK = PreLock(
    "character_row_key_share",
    select(characters.c.character_id)
    .where(characters.c.character_id == bindparam("character"))
    .with_for_update(read=True, key_share=True),
)
KNOWLEDGE_ITEM_ROW_LOCK = PreLock(
    "knowledge_item_row_key_share",
    select(knowledge_items.c.knowledge_item_id)
    .where(knowledge_items.c.knowledge_item_id == bindparam("knowledge_item"))
    .with_for_update(read=True, key_share=True),
)
QUEST_ROW_LOCK = PreLock(
    "quest_row_key_share",
    select(quests.c.quest_id)
    .where(quests.c.quest_id == bindparam("quest"))
    .with_for_update(read=True, key_share=True),
)
EVENT_ROW_LOCK = PreLock(
    "event_row_key_share",
    select(events.c.event_id)
    .where(events.c.event_id == bindparam("event"))
    .with_for_update(read=True, key_share=True),
)
#: A session target, `FOR UPDATE` (bound `session`): the command's own target lock.
SESSION_LOCK = PreLock(
    "target_session_update",
    select(sessions.c.session_id)
    .where(sessions.c.session_id == bindparam("session"))
    .with_for_update(),
)
TIMELINE_KEY_SHARE_LOCK = PreLock(
    "timeline_key_share",
    select(timelines.c.timeline_id)
    .where(timelines.c.timeline_id == bindparam("timeline"))
    .with_for_update(read=True, key_share=True),
)
#: One or two world-time rows, `FOR KEY SHARE`, ordered by id (bound `time_a`, `time_b`; the same id twice for one).
WORLD_TIMES_KEY_SHARE_LOCK = PreLock(
    "world_time_rows_key_share",
    select(world_times.c.world_time_id)
    .where(
        or_(
            world_times.c.world_time_id == bindparam("time_a"),
            world_times.c.world_time_id == bindparam("time_b"),
        )
    )
    .order_by(world_times.c.world_time_id)
    .with_for_update(read=True, key_share=True),
)
#: The relationship the change closes, `FOR UPDATE`, candidate-bound (bound `row`, `membership`): the owning
#: membership is part of the predicate, so a row that is not the discovered owner's matches nothing.
RELATIONSHIP_ROW_LOCK = PreLock(
    "relationship_row_update",
    select(mcr.c.membership_character_relationship_id)
    .where(mcr.c.membership_character_relationship_id == bindparam("row"))
    .where(mcr.c.campaign_membership_id == bindparam("membership"))
    .with_for_update(),
)
#: The relationship the revoke closes, `FOR UPDATE`, only while **unrevoked** (bound `row`, `membership`). Its evidence is
#: the database's own answer, under the lock, to "this request revokes": one key for a genuine revocation, none for the
#: no-op.
RELATIONSHIP_OUTSTANDING_LOCK = PreLock(
    "relationship_outstanding_row",
    select(mcr.c.membership_character_relationship_id)
    .where(mcr.c.membership_character_relationship_id == bindparam("row"))
    .where(mcr.c.campaign_membership_id == bindparam("membership"))
    .where(mcr.c.revoked_at.is_(None))
    .with_for_update(),
)
#: The grant the revoke closes, `FOR UPDATE`, only while **unrevoked** (bound `grant`, `campaign`).
GRANT_OUTSTANDING_LOCK = PreLock(
    "grant_outstanding_row",
    select(rg.c.resource_grant_id)
    .where(rg.c.resource_grant_id == bindparam("grant"))
    .where(rg.c.campaign_id == bindparam("campaign"))
    .where(rg.c.revoked_at.is_(None))
    .with_for_update(),
)

# -- steps ----------------------------------------------------------------------------------------------

_LEAVES_INDEX_TEST = (
    "tests/database/test_r01_s5e4_access_grants.py::"
    "test_an_update_leaving_a_partial_unique_index_never_waits_for_a_competing_insert"
)
_LEAVES_RELATIONSHIP_INDEX = frozenset(
    {UniqueWait("security.ux_membership_character_relationships_active_type", _LEAVES_INDEX_TEST)}
)
_LEAVES_GRANT_INDEX = frozenset(
    {UniqueWait("security.ux_resource_grants_active", _LEAVES_INDEX_TEST)}
)
_NOW = func.pg_catalog.now


def _fk(table: Any, column: str, bind: str, lock: PreLock | None) -> FkBinding:
    return FkBinding(fk_of(table, column), (KeyBind(table.c[column], bind),), lock)


_COMPETING_RELATIONSHIP_WAIT = frozenset(
    {
        UniqueWait(
            "security.ux_membership_character_relationships_active_type",
            "tests/database/test_r01_s5e4_access_grants.py::"
            "test_a_competing_active_relationship_of_the_same_type_is_a_unique_wait",
        )
    }
)
GRANT_RELATIONSHIP_INSERT = WriteStep(
    name="insert_relationship",
    statement=insert(mcr)
    .values(
        campaign_membership_id=bindparam("membership"),
        character_id=bindparam("character"),
        character_relationship_type_id=bindparam("type"),
        timeline_id=bindparam("timeline"),
        effective_from_world_time_id=bindparam("time_from"),
        effective_to_world_time_id=bindparam("time_to"),
        granted_by_membership_id=bindparam("granted_by"),
    )
    .returning(mcr.c.membership_character_relationship_id),
    cardinality=Exactly(1),
    fks=(
        _fk(mcr, "campaign_membership_id", "membership", TARGET_MEMBERSHIP_LOCK),
        _fk(mcr, "character_id", "character", CHARACTER_ROW_LOCK),
        _fk(mcr, "character_relationship_type_id", "type", RELATIONSHIP_TYPE_BY_CODE_LOCK),
        _fk(mcr, "timeline_id", "timeline", TIMELINE_KEY_SHARE_LOCK),
        _fk(mcr, "effective_from_world_time_id", "time_from", WORLD_TIMES_KEY_SHARE_LOCK),
        _fk(mcr, "effective_to_world_time_id", "time_to", WORLD_TIMES_KEY_SHARE_LOCK),
        _fk(mcr, "granted_by_membership_id", "granted_by", ACTOR_MEMBERSHIP_LOCK),
    ),
    unique_waits=_COMPETING_RELATIONSHIP_WAIT,
    triggers=RELATIONSHIP_TRIGGERS,
)
CHANGE_RELATIONSHIP_INSERT = WriteStep(
    name="insert_changed_relationship",
    statement=insert(mcr)
    .values(
        campaign_membership_id=bindparam("membership"),
        character_id=bindparam("character"),
        character_relationship_type_id=bindparam("type"),
        timeline_id=bindparam("timeline"),
        effective_from_world_time_id=bindparam("time_from"),
        effective_to_world_time_id=bindparam("time_to"),
        granted_by_membership_id=bindparam("granted_by"),
    )
    .returning(mcr.c.membership_character_relationship_id),
    cardinality=Exactly(1),
    fks=(
        _fk(mcr, "campaign_membership_id", "membership", TARGET_MEMBERSHIP_LOCK),
        _fk(mcr, "character_id", "character", CHARACTER_ROW_LOCK),
        _fk(mcr, "character_relationship_type_id", "type", RELATIONSHIP_TYPE_BY_ID_LOCK),
        _fk(mcr, "timeline_id", "timeline", TIMELINE_KEY_SHARE_LOCK),
        _fk(mcr, "effective_from_world_time_id", "time_from", WORLD_TIMES_KEY_SHARE_LOCK),
        _fk(mcr, "effective_to_world_time_id", "time_to", WORLD_TIMES_KEY_SHARE_LOCK),
        _fk(mcr, "granted_by_membership_id", "granted_by", ACTOR_MEMBERSHIP_LOCK),
    ),
    unique_waits=_COMPETING_RELATIONSHIP_WAIT,
    triggers=RELATIONSHIP_TRIGGERS,
)
CHANGE_RELATIONSHIP_REVOKE_OLD = WriteStep(
    name="revoke_old_relationship",
    statement=update(mcr)
    .where(mcr.c.membership_character_relationship_id == bindparam("target"))
    .values(revoked_at=_NOW())
    .returning(mcr.c.membership_character_relationship_id),
    cardinality=Exactly(1),
    target=(KeyBind(mcr.c.membership_character_relationship_id, "target"),),
    target_lock=RELATIONSHIP_ROW_LOCK,
    unique_waits=_LEAVES_RELATIONSHIP_INDEX,
    triggers=RELATIONSHIP_TRIGGERS,
)
REVOKE_RELATIONSHIP = WriteStep(
    name="revoke_relationship",
    statement=update(mcr)
    .where(mcr.c.membership_character_relationship_id == bindparam("target"))
    .values(revoked_at=_NOW())
    .returning(mcr.c.membership_character_relationship_id),
    cardinality=EachLockedRow(complete=True),
    target=(KeyBind(mcr.c.membership_character_relationship_id, "target"),),
    target_lock=RELATIONSHIP_OUTSTANDING_LOCK,
    unique_waits=_LEAVES_RELATIONSHIP_INDEX,
    triggers=RELATIONSHIP_TRIGGERS,
)
CREATE_GRANT_INSERT = WriteStep(
    name="insert_resource_grant",
    statement=insert(rg)
    .values(
        campaign_id=bindparam("campaign"),
        grantee_campaign_membership_id=bindparam("grantee_membership"),
        grantee_access_group_id=bindparam("grantee_group"),
        capability_id=bindparam("capability"),
        effect=bindparam("effect"),
        character_id=bindparam("character"),
        entity_id=bindparam("entity"),
        knowledge_item_id=bindparam("knowledge_item"),
        quest_id=bindparam("quest"),
        session_id=bindparam("session"),
        event_id=bindparam("event"),
        granted_by_membership_id=bindparam("granted_by"),
        reason=bindparam("reason"),
    )
    .returning(rg.c.resource_grant_id),
    cardinality=Exactly(1),
    fks=(
        _fk(rg, "campaign_id", "campaign", CAMPAIGN_ROW_LOCK),
        _fk(rg, "grantee_campaign_membership_id", "grantee_membership", TARGET_MEMBERSHIP_LOCK),
        _fk(rg, "grantee_access_group_id", "grantee_group", GROUP_GRANTEE_LOCK),
        _fk(rg, "capability_id", "capability", CAPABILITY_LOCK),
        _fk(rg, "character_id", "character", CHARACTER_ROW_LOCK),
        _fk(rg, "entity_id", "entity", TARGET_ENTITY_LOCK),
        _fk(rg, "knowledge_item_id", "knowledge_item", KNOWLEDGE_ITEM_ROW_LOCK),
        _fk(rg, "quest_id", "quest", QUEST_ROW_LOCK),
        _fk(rg, "session_id", "session", SESSION_LOCK),
        _fk(rg, "event_id", "event", EVENT_ROW_LOCK),
        _fk(rg, "granted_by_membership_id", "granted_by", ACTOR_MEMBERSHIP_LOCK),
    ),
    value_binds=frozenset({"effect", "reason"}),
    unique_waits=frozenset(
        {
            UniqueWait(
                "security.ux_resource_grants_active",
                "tests/database/test_r01_s5e4_access_grants.py::"
                "test_a_competing_active_grant_of_the_same_key_is_a_unique_wait",
            )
        }
    ),
    triggers=GRANT_TRIGGERS,
)
REVOKE_GRANT = WriteStep(
    name="revoke_resource_grant",
    statement=update(rg)
    .where(rg.c.resource_grant_id == bindparam("target"))
    .values(revoked_at=_NOW())
    .returning(rg.c.resource_grant_id),
    cardinality=EachLockedRow(complete=True),
    target=(KeyBind(rg.c.resource_grant_id, "target"),),
    target_lock=GRANT_OUTSTANDING_LOCK,
    unique_waits=_LEAVES_GRANT_INDEX,
    triggers=GRANT_TRIGGERS,
)


GRANT_RELATIONSHIP_AUDIT = WriteStep(
    name="audit_relationship_created",
    statement=insert(change_log)
    .values(
        **_audit_values("membership_character_relationships", GRANT_RELATIONSHIP_COMMAND_NAME),
    )
    .returning(change_log.c.change_log_id),
    cardinality=Exactly(1),
    fks=(CHANGE_LOG_ACTION_FK, CHANGE_LOG_ACTOR_FK),
    value_binds=_AUDIT_BINDS,
)
CHANGE_RELATIONSHIP_AUDIT = WriteStep(
    name="audit_relationship_changed",
    statement=insert(change_log)
    .values(
        **_audit_values("membership_character_relationships", CHANGE_RELATIONSHIP_COMMAND_NAME),
        previous_status=bindparam("previous_status"),
        new_status=bindparam("new_status"),
        changed_fields=bindparam("changed"),
    )
    .returning(change_log.c.change_log_id),
    cardinality=Exactly(1),
    fks=(CHANGE_LOG_ACTION_FK, CHANGE_LOG_ACTOR_FK),
    value_binds=_AUDIT_BINDS | {"previous_status", "new_status", "changed"},
)
REVOKE_RELATIONSHIP_AUDIT = WriteStep(
    name="audit_relationship_revoked",
    statement=insert(change_log)
    .values(
        **_audit_values("membership_character_relationships", REVOKE_RELATIONSHIP_COMMAND_NAME),
    )
    .returning(change_log.c.change_log_id),
    cardinality=PerEvidence(RELATIONSHIP_OUTSTANDING_LOCK),
    fks=(CHANGE_LOG_ACTION_FK, CHANGE_LOG_ACTOR_FK),
    value_binds=_AUDIT_BINDS,
)
CREATE_GRANT_AUDIT = WriteStep(
    name="audit_grant_created",
    statement=insert(change_log)
    .values(
        **_audit_values("resource_grants", CREATE_GRANT_COMMAND_NAME),
        changed_fields=bindparam("changed"),
    )
    .returning(change_log.c.change_log_id),
    cardinality=Exactly(1),
    fks=(CHANGE_LOG_ACTION_FK, CHANGE_LOG_ACTOR_FK),
    value_binds=_AUDIT_BINDS | {"changed"},
)
REVOKE_GRANT_AUDIT = WriteStep(
    name="audit_grant_revoked",
    statement=insert(change_log)
    .values(
        **_audit_values("resource_grants", REVOKE_GRANT_COMMAND_NAME),
        changed_fields=bindparam("changed"),
    )
    .returning(change_log.c.change_log_id),
    cardinality=PerEvidence(GRANT_OUTSTANDING_LOCK),
    fks=(CHANGE_LOG_ACTION_FK, CHANGE_LOG_ACTOR_FK),
    value_binds=_AUDIT_BINDS | {"changed"},
)
GRANT_RECEIPT = RECEIPT_STEP

# -- declarations ----------------------------------------------------------------------------------------

_UNLOCKED = CHANGE_LOG_UNLOCKED_FK_TARGETS

_GRANT_RELATIONSHIP_LOCKS = (
    ACTOR_ROLES_LOCK,
    ACTOR_MEMBERSHIP_LOCK,
    TARGET_MEMBERSHIP_LOCK,
    ACTOR_ACCOUNT_LOCK,
    TARGET_ACCOUNT_LOCK,
    CAMPAIGN_ROW_LOCK,
    RELATIONSHIP_TYPE_BY_CODE_LOCK,
    TARGET_ENTITY_LOCK,
    CHARACTER_ROW_LOCK,
    TIMELINE_KEY_SHARE_LOCK,
    WORLD_TIMES_KEY_SHARE_LOCK,
)
_GRANT_RELATIONSHIP_STEPS = (GRANT_RELATIONSHIP_INSERT, GRANT_RELATIONSHIP_AUDIT)
GRANT_RELATIONSHIP_DECLARATIONS = ReservationDeclarations(
    reserved=PreWriteDeclaration(
        locks=(*_GRANT_RELATIONSHIP_LOCKS, RECEIPT_LOCK),
        steps=(*_GRANT_RELATIONSHIP_STEPS, GRANT_RECEIPT),
        unlocked_fk_targets=_UNLOCKED,
    ),
    unkeyed=PreWriteDeclaration(
        locks=_GRANT_RELATIONSHIP_LOCKS,
        steps=_GRANT_RELATIONSHIP_STEPS,
        unlocked_fk_targets=_UNLOCKED,
    ),
)
_CHANGE_RELATIONSHIP_LOCKS = (
    ACTOR_ROLES_LOCK,
    ACTOR_MEMBERSHIP_LOCK,
    TARGET_MEMBERSHIP_LOCK,
    ACTOR_ACCOUNT_LOCK,
    TARGET_ACCOUNT_LOCK,
    CAMPAIGN_ROW_LOCK,
    RELATIONSHIP_TYPE_BY_ID_LOCK,
    TARGET_ENTITY_LOCK,
    CHARACTER_ROW_LOCK,
    RELATIONSHIP_ROW_LOCK,
    TIMELINE_KEY_SHARE_LOCK,
    WORLD_TIMES_KEY_SHARE_LOCK,
)
_CHANGE_RELATIONSHIP_STEPS = (
    CHANGE_RELATIONSHIP_REVOKE_OLD,
    CHANGE_RELATIONSHIP_INSERT,
    CHANGE_RELATIONSHIP_AUDIT,
)
CHANGE_RELATIONSHIP_DECLARATIONS = ReservationDeclarations(
    reserved=PreWriteDeclaration(
        locks=(*_CHANGE_RELATIONSHIP_LOCKS, RECEIPT_LOCK),
        steps=(*_CHANGE_RELATIONSHIP_STEPS, GRANT_RECEIPT),
        unlocked_fk_targets=_UNLOCKED,
    ),
    unkeyed=PreWriteDeclaration(
        locks=_CHANGE_RELATIONSHIP_LOCKS,
        steps=_CHANGE_RELATIONSHIP_STEPS,
        unlocked_fk_targets=_UNLOCKED,
    ),
)
_REVOKE_RELATIONSHIP_LOCKS = (
    ACTOR_ROLES_LOCK,
    ACTOR_MEMBERSHIP_LOCK,
    ACTOR_ACCOUNT_LOCK,
    CAMPAIGN_KEY_SHARE_LOCK,
    RELATIONSHIP_OUTSTANDING_LOCK,
)
_REVOKE_RELATIONSHIP_STEPS = (REVOKE_RELATIONSHIP, REVOKE_RELATIONSHIP_AUDIT)
REVOKE_RELATIONSHIP_DECLARATIONS = ReservationDeclarations(
    reserved=PreWriteDeclaration(
        locks=(*_REVOKE_RELATIONSHIP_LOCKS, RECEIPT_LOCK),
        steps=(*_REVOKE_RELATIONSHIP_STEPS, GRANT_RECEIPT),
        unlocked_fk_targets=_UNLOCKED,
    ),
    unkeyed=PreWriteDeclaration(
        locks=_REVOKE_RELATIONSHIP_LOCKS,
        steps=_REVOKE_RELATIONSHIP_STEPS,
        unlocked_fk_targets=_UNLOCKED,
    ),
)
_CREATE_GRANT_LOCKS = (
    ACTOR_ROLES_LOCK,
    GROUP_GRANTEE_LOCK,
    ACTOR_MEMBERSHIP_LOCK,
    TARGET_MEMBERSHIP_LOCK,
    ACTOR_ACCOUNT_LOCK,
    TARGET_ACCOUNT_LOCK,
    CAMPAIGN_ROW_LOCK,
    CAPABILITY_LOCK,
    TARGET_ENTITY_LOCK,
    CHARACTER_ROW_LOCK,
    KNOWLEDGE_ITEM_ROW_LOCK,
    QUEST_ROW_LOCK,
    EVENT_ROW_LOCK,
    SESSION_LOCK,
)
_CREATE_GRANT_STEPS = (CREATE_GRANT_INSERT, CREATE_GRANT_AUDIT)
CREATE_GRANT_DECLARATIONS = ReservationDeclarations(
    reserved=PreWriteDeclaration(
        locks=(*_CREATE_GRANT_LOCKS, RECEIPT_LOCK),
        steps=(*_CREATE_GRANT_STEPS, GRANT_RECEIPT),
        unlocked_fk_targets=_UNLOCKED,
    ),
    unkeyed=PreWriteDeclaration(
        locks=_CREATE_GRANT_LOCKS, steps=_CREATE_GRANT_STEPS, unlocked_fk_targets=_UNLOCKED
    ),
)
_REVOKE_GRANT_LOCKS = (
    ACTOR_ROLES_LOCK,
    ACTOR_MEMBERSHIP_LOCK,
    ACTOR_ACCOUNT_LOCK,
    CAMPAIGN_KEY_SHARE_LOCK,
    GRANT_OUTSTANDING_LOCK,
)
_REVOKE_GRANT_STEPS = (REVOKE_GRANT, REVOKE_GRANT_AUDIT)
REVOKE_GRANT_DECLARATIONS = ReservationDeclarations(
    reserved=PreWriteDeclaration(
        locks=(*_REVOKE_GRANT_LOCKS, RECEIPT_LOCK),
        steps=(*_REVOKE_GRANT_STEPS, GRANT_RECEIPT),
        unlocked_fk_targets=_UNLOCKED,
    ),
    unkeyed=PreWriteDeclaration(
        locks=_REVOKE_GRANT_LOCKS, steps=_REVOKE_GRANT_STEPS, unlocked_fk_targets=_UNLOCKED
    ),
)

# -- shared reads ----------------------------------------------------------------------------------------

_MEMBERSHIP_ROW = text("""
    SELECT cm.campaign_id, cm.ended_at, cm.user_id, cm.membership_status_id,
           ms.code AS status_code, ms.is_active AS status_is_active
    FROM security.campaign_memberships cm
    JOIN security.membership_statuses ms ON ms.membership_status_id = cm.membership_status_id
    WHERE cm.campaign_membership_id = :m
""")
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
_ENTITY_ROW = text("""
    SELECT e.world_id, ls.code AS lifecycle_status_code, et.code AS entity_type_code
    FROM core.entities e
    JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = e.lifecycle_status_id
    JOIN core.entity_types et ON et.entity_type_id = e.entity_type_id
    WHERE e.entity_id = :e
""")


def _status_before(connection: Connection, membership_id: uuid.UUID | None) -> Any:
    """BA-404: one unlocked snapshot of the target's status id before any lock. It is trusted for nothing but the
    classification of a membership that turns ineligible *while this request waited*."""
    if membership_id is None:
        return None
    return connection.execute(
        text(
            "SELECT membership_status_id FROM security.campaign_memberships "
            "WHERE campaign_membership_id = :m"
        ),
        {"m": membership_id},
    ).scalar()


def _became_ineligible_while_waiting(
    membership: Any, status_before: Any, membership_id: uuid.UUID | None
) -> None:
    """The baseline commands locked the membership with a joined `FOR UPDATE OF cm` statement whose join was re-checked after
    a wait, so a membership that ended while the request waited was *not found* (404 `not_found`); one that was already
    ineligible still answered 409. Same classification here (the S5-E2 assign's BA-404)."""
    if membership["membership_status_id"] != status_before:
        raise MembershipNotInCampaignError(
            f"membership {membership_id} ended while the request waited"
        )


def _require_campaign_active(connection: Connection, campaign_id: uuid.UUID) -> None:
    if connection.execute(_CAMPAIGN_STATUS, {"c": campaign_id}).scalar() != "active":
        raise CampaignNotActiveError(f"campaign {campaign_id} is not currently active")


def _lock_actor(
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


def _audit_binds(
    prepared: "AccessPrepared",
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


@dataclass(frozen=True)
class AccessPrepared:
    """What the lock and read phase established, all before `finalize`."""

    world_id: uuid.UUID
    action_id: uuid.UUID
    will_write: bool = True
    #: grant relationship / change: the relationship's bind values
    membership_id: uuid.UUID | None = None
    character_id: uuid.UUID | None = None
    type_id: uuid.UUID | None = None
    timeline_id: uuid.UUID | None = None
    time_from_id: uuid.UUID | None = None
    time_to_id: uuid.UUID | None = None
    previous_type_code: str | None = None
    new_type_code: str | None = None
    #: create grant
    capability_id: uuid.UUID | None = None
    #: revoke grant: the audit payload read from the locked row
    changed: dict[str, Any] | None = None


# =====================================================================================================
# Grant character relationship
# =====================================================================================================


def _world_time_sort_key(
    connection: Connection, *, world_time_id: uuid.UUID, expected_world_id: uuid.UUID
) -> int:
    row = (
        connection.execute(
            text("SELECT world_id, sort_key FROM core.world_times WHERE world_time_id = :wt"),
            {"wt": world_time_id},
        )
        .mappings()
        .one_or_none()
    )
    if row is None or row["world_id"] != expected_world_id:
        raise TargetNotInCampaignWorldError(
            f"world time {world_time_id} does not exist in world {expected_world_id} "
            f"(actual world: {row['world_id'] if row is not None else None})"
        )
    sort_key = row["sort_key"]
    assert isinstance(sort_key, int)
    return sort_key


def _lock_scope_rows(
    connection: Connection,
    plan: AuthorizationPlan,
    *,
    timeline_id: uuid.UUID | None,
    time_from_id: uuid.UUID | None,
    time_to_id: uuid.UUID | None,
) -> None:
    """The timeline and world-time rows a relationship's foreign keys will check, `FOR KEY SHARE`, taken as lock
    evidence (the INSERT would take the same key share implicitly)."""
    if timeline_id is not None:
        plan.lock(connection, TIMELINE_KEY_SHARE_LOCK, {"timeline": timeline_id})
    times = [t for t in (time_from_id, time_to_id) if t is not None]
    if times:
        plan.lock(
            connection,
            WORLD_TIMES_KEY_SHARE_LOCK,
            {"time_a": times[0], "time_b": times[-1]},
        )


def prepare_grant_relationship(  # noqa: PLR0915 - one linear lock and refusal sequence
    connection: Connection,
    plan: AuthorizationPlan,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    actor_membership_id: uuid.UUID,
    target_membership_id: uuid.UUID,
    character_id: uuid.UUID,
    relationship_type_code: str,
    timeline_id: uuid.UUID | None,
    time_from_id: uuid.UUID | None,
    time_to_id: uuid.UUID | None,
    reservation_id: uuid.UUID | None,
) -> AccessPrepared:
    status_before = _status_before(connection, target_membership_id)
    plan.lock(connection, ACTOR_ROLES_LOCK, {"membership": actor_membership_id})
    lock_memberships(
        connection,
        plan,
        campaign_id=campaign_id,
        actor_membership_id=actor_membership_id,
        target_membership_id=target_membership_id,
    )
    plan.lock(connection, ACTOR_ACCOUNT_LOCK, {"actor": actor_user_id})
    membership = (
        connection.execute(_MEMBERSHIP_ROW, {"m": target_membership_id}).mappings().one_or_none()
    )
    in_campaign = membership is not None and membership["campaign_id"] == campaign_id
    if in_campaign and membership is not None:
        plan.lock(connection, TARGET_ACCOUNT_LOCK, {"target_user": membership["user_id"]})
    plan.lock(connection, CAMPAIGN_ROW_LOCK, {"campaign": campaign_id})
    type_keys = plan.lock(
        connection, RELATIONSHIP_TYPE_BY_CODE_LOCK, {"code": relationship_type_code}
    )
    plan.lock(connection, TARGET_ENTITY_LOCK, {"entity": character_id})
    character_row_keys = plan.lock(connection, CHARACTER_ROW_LOCK, {"character": character_id})
    _lock_scope_rows(
        connection, plan, timeline_id=timeline_id, time_from_id=time_from_id, time_to_id=time_to_id
    )
    if reservation_id is not None:
        plan.lock(connection, RECEIPT_LOCK, {"receipt": reservation_id})
    # reads and refusals, in the order the command raised them
    if not in_campaign:
        raise MembershipNotInCampaignError(
            f"membership {target_membership_id} does not belong to campaign {campaign_id} "
            f"(actual campaign: {membership['campaign_id'] if membership is not None else None})"
        )
    assert membership is not None
    if not (
        membership["ended_at"] is None
        and membership["status_code"] == "active"
        and membership["status_is_active"]
    ):
        _became_ineligible_while_waiting(membership, status_before, target_membership_id)
        raise MembershipNotActiveError(
            f"membership {target_membership_id} is not currently an eligible, open "
            "membership to grant a character relationship to"
        )
    _require_campaign_active(connection, campaign_id)
    if connection.execute(_ACCOUNT_STATUS, {"u": membership["user_id"]}).scalar() != "active":
        raise MembershipNotActiveError(
            f"membership {target_membership_id}'s user {membership['user_id']} is not "
            "currently an active platform account"
        )
    expected_world_id = _scope_world(connection, campaign_id)
    character = connection.execute(_ENTITY_ROW, {"e": character_id}).mappings().one_or_none()
    if not (
        character is not None
        and character["world_id"] == expected_world_id
        and character["lifecycle_status_code"] == "active"
    ):
        raise TargetNotInCampaignWorldError(
            f"character {character_id} does not exist in world {expected_world_id}, or is not "
            "currently active "
            f"(actual world: {character['world_id'] if character is not None else None})"
        )
    if timeline_id is not None:
        timeline_world = connection.execute(
            text("SELECT world_id FROM campaign.timelines WHERE timeline_id = :t"),
            {"t": timeline_id},
        ).scalar()
        if timeline_world is None or timeline_world != expected_world_id:
            raise TargetNotInCampaignWorldError(
                f"timeline {timeline_id} does not exist in world {expected_world_id} "
                f"(actual world: {timeline_world})"
            )
    if time_to_id is not None and time_from_id is None:
        raise InvalidRelationshipPeriodError(
            "effective_to_world_time_id requires effective_from_world_time_id"
        )
    if time_from_id is not None:
        from_key = _world_time_sort_key(
            connection, world_time_id=time_from_id, expected_world_id=expected_world_id
        )
        if time_to_id is not None:
            to_key = _world_time_sort_key(
                connection, world_time_id=time_to_id, expected_world_id=expected_world_id
            )
            if to_key <= from_key:
                raise InvalidRelationshipPeriodError(
                    f"relationship end (sort_key {to_key}) must be later than its start "
                    f"(sort_key {from_key})"
                )
    type_row = connection.execute(
        text(
            "SELECT character_relationship_type_id, is_active "
            "FROM security.character_relationship_types WHERE code = :code"
        ),
        {"code": relationship_type_code},
    ).one_or_none()
    if type_row is None or not type_row.is_active or not type_keys:
        raise RelationshipTypeNotActiveError(
            f"relationship type code {relationship_type_code!r} does not exist or is not currently active"
        )
    if not character_row_keys:
        # an entity that is not a character: the INSERT's foreign key would have refused it (400)
        raise GrantRowRefusedError(f"entity {character_id} is not a character")
    return AccessPrepared(
        world_id=expected_world_id,
        action_id=lookup_id(connection, "audit", "change_actions", "change_action_id", "created"),
        membership_id=target_membership_id,
        character_id=character_id,
        type_id=type_row.character_relationship_type_id,
        timeline_id=timeline_id,
        time_from_id=time_from_id,
        time_to_id=time_to_id,
    )


def write_grant_relationship(
    connection: Connection,
    plan: AuthorizationPlan,
    prepared: AccessPrepared,
    *,
    actor_user_id: uuid.UUID,
    actor_membership_id: uuid.UUID,
    correlation_id: str | None,
) -> uuid.UUID:
    created = plan.execute(
        connection,
        GRANT_RELATIONSHIP_INSERT,
        {
            "membership": prepared.membership_id,
            "character": prepared.character_id,
            "type": prepared.type_id,
            "timeline": prepared.timeline_id,
            "time_from": prepared.time_from_id,
            "time_to": prepared.time_to_id,
            "granted_by": actor_membership_id,
        },
    )
    new_id = created.keys[0][0]
    assert isinstance(new_id, uuid.UUID)
    plan.execute(
        connection,
        GRANT_RELATIONSHIP_AUDIT,
        _audit_binds(
            prepared, record=new_id, actor_user_id=actor_user_id, correlation_id=correlation_id
        ),
    )
    return new_id


# =====================================================================================================
# Change character relationship
# =====================================================================================================

_RELATIONSHIP_FOR_CHANGE = text("""
    SELECT cm.campaign_id, cm.ended_at, cm.user_id, cm.membership_status_id,
           ms.code AS membership_status_code, ms.is_active AS membership_status_is_active,
           mcr.campaign_membership_id, mcr.character_id, mcr.character_relationship_type_id,
           mcr.timeline_id, mcr.effective_from_world_time_id, mcr.effective_to_world_time_id,
           mcr.revoked_at,
           (mcr.expires_at IS NOT NULL AND mcr.expires_at <= clock_timestamp()) AS relationship_is_expired,
           rt.code AS relationship_type_code
    FROM security.membership_character_relationships mcr
    JOIN security.campaign_memberships cm ON cm.campaign_membership_id = mcr.campaign_membership_id
    JOIN security.membership_statuses ms ON ms.membership_status_id = cm.membership_status_id
    JOIN security.character_relationship_types rt
        ON rt.character_relationship_type_id = mcr.character_relationship_type_id
    WHERE mcr.membership_character_relationship_id = :r
""")


def prepare_change_relationship(  # noqa: PLR0915 - one linear lock and refusal sequence
    connection: Connection,
    plan: AuthorizationPlan,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    actor_membership_id: uuid.UUID,
    relationship_id: uuid.UUID,
    new_type_id: uuid.UUID,
    reservation_id: uuid.UUID | None,
) -> AccessPrepared:
    # an unlocked discovery read: the relationship's owning membership and its carried-forward values. They are
    # re-read under the locks and compared (no application path changes them).
    found = (
        connection.execute(_RELATIONSHIP_FOR_CHANGE, {"r": relationship_id})
        .mappings()
        .one_or_none()
    )
    in_campaign = found is not None and found["campaign_id"] == campaign_id
    owner = (
        found["campaign_membership_id"]
        if in_campaign and found is not None
        else actor_membership_id
    )
    plan.lock(connection, ACTOR_ROLES_LOCK, {"membership": actor_membership_id})
    lock_memberships(
        connection,
        plan,
        campaign_id=campaign_id,
        actor_membership_id=actor_membership_id,
        target_membership_id=owner,
    )
    plan.lock(connection, ACTOR_ACCOUNT_LOCK, {"actor": actor_user_id})
    if in_campaign and found is not None:
        plan.lock(connection, TARGET_ACCOUNT_LOCK, {"target_user": found["user_id"]})
    plan.lock(connection, CAMPAIGN_ROW_LOCK, {"campaign": campaign_id})
    plan.lock(connection, RELATIONSHIP_TYPE_BY_ID_LOCK, {"type": new_type_id})
    character_row_keys: tuple[tuple[Any, ...], ...] = ()
    row_keys: tuple[tuple[Any, ...], ...] = ()
    if in_campaign and found is not None:
        plan.lock(connection, TARGET_ENTITY_LOCK, {"entity": found["character_id"]})
        character_row_keys = plan.lock(
            connection, CHARACTER_ROW_LOCK, {"character": found["character_id"]}
        )
        row_keys = plan.lock(
            connection, RELATIONSHIP_ROW_LOCK, {"row": relationship_id, "membership": owner}
        )
        _lock_scope_rows(
            connection,
            plan,
            timeline_id=found["timeline_id"],
            time_from_id=found["effective_from_world_time_id"],
            time_to_id=found["effective_to_world_time_id"],
        )
    if reservation_id is not None:
        plan.lock(connection, RECEIPT_LOCK, {"receipt": reservation_id})
    # reads and refusals, in the order the command raised them
    row = (
        connection.execute(_RELATIONSHIP_FOR_CHANGE, {"r": relationship_id})
        .mappings()
        .one_or_none()
    )
    if row is None or row["campaign_id"] != campaign_id:
        raise MembershipNotInCampaignError(
            f"membership character relationship {relationship_id} does not belong to campaign "
            f"{campaign_id} (actual campaign: {row['campaign_id'] if row is not None else None})"
        )
    if (
        found is None
        or not row_keys
        or (
            row["campaign_membership_id"],
            row["character_id"],
            row["timeline_id"],
            row["effective_from_world_time_id"],
            row["effective_to_world_time_id"],
        )
        != (
            found["campaign_membership_id"],
            found["character_id"],
            found["timeline_id"],
            found["effective_from_world_time_id"],
            found["effective_to_world_time_id"],
        )
    ):
        raise RuntimeError("the relationship changed under its own lock")
    if row["membership_status_id"] != found["membership_status_id"]:
        # BA-404: the owning membership changed status while this request waited (a concurrent end): the baseline's
        # joined `FOR UPDATE OF mcr, cm` statement re-checked its join and found no row, so it answered "not in campaign"
        raise MembershipNotInCampaignError(
            f"membership character relationship {relationship_id}: its membership changed while the change waited"
        )
    _require_campaign_active(connection, campaign_id)
    expected_world_id = _scope_world(connection, campaign_id)
    account_active = connection.execute(_ACCOUNT_STATUS, {"u": row["user_id"]}).scalar() == "active"
    character = connection.execute(_ENTITY_ROW, {"e": row["character_id"]}).mappings().one_or_none()
    character_is_eligible = (
        character is not None
        and character["world_id"] == expected_world_id
        and character["lifecycle_status_code"] == "active"
    )
    if not (
        row["revoked_at"] is None
        and not row["relationship_is_expired"]
        and row["effective_to_world_time_id"] is None
        and row["ended_at"] is None
        and row["membership_status_code"] == "active"
        and row["membership_status_is_active"]
        and account_active
        and character_is_eligible
    ):
        raise CharacterRelationshipNotActiveError(
            f"membership character relationship {relationship_id} is not currently an eligible, "
            "active assignment to change"
        )
    new_type = connection.execute(
        text(
            "SELECT code, is_active FROM security.character_relationship_types "
            "WHERE character_relationship_type_id = :t"
        ),
        {"t": new_type_id},
    ).one_or_none()
    if new_type is None or not new_type.is_active:
        raise RelationshipTypeNotActiveError(
            f"relationship type {new_type_id} does not exist or is not currently active"
        )
    if new_type_id == row["character_relationship_type_id"]:
        raise ChangeCharacterRelationshipNoOpError(
            f"relationship type {new_type_id} is already the current type for membership "
            f"character relationship {relationship_id}"
        )
    if not character_row_keys:
        raise GrantRowRefusedError(f"entity {row['character_id']} is not a character")
    return AccessPrepared(
        world_id=expected_world_id,
        action_id=lookup_id(connection, "audit", "change_actions", "change_action_id", "updated"),
        membership_id=row["campaign_membership_id"],
        character_id=row["character_id"],
        type_id=new_type_id,
        timeline_id=row["timeline_id"],
        time_from_id=row["effective_from_world_time_id"],
        time_to_id=row["effective_to_world_time_id"],
        previous_type_code=row["relationship_type_code"],
        new_type_code=new_type.code,
    )


def write_change_relationship(
    connection: Connection,
    plan: AuthorizationPlan,
    prepared: AccessPrepared,
    *,
    relationship_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    actor_membership_id: uuid.UUID,
    correlation_id: str | None,
) -> uuid.UUID:
    plan.execute(connection, CHANGE_RELATIONSHIP_REVOKE_OLD, {"target": relationship_id})
    created = plan.execute(
        connection,
        CHANGE_RELATIONSHIP_INSERT,
        {
            "membership": prepared.membership_id,
            "character": prepared.character_id,
            "type": prepared.type_id,
            "timeline": prepared.timeline_id,
            "time_from": prepared.time_from_id,
            "time_to": prepared.time_to_id,
            "granted_by": actor_membership_id,
        },
    )
    new_id = created.keys[0][0]
    assert isinstance(new_id, uuid.UUID)
    plan.execute(
        connection,
        CHANGE_RELATIONSHIP_AUDIT,
        {
            **_audit_binds(
                prepared, record=new_id, actor_user_id=actor_user_id, correlation_id=correlation_id
            ),
            "previous_status": prepared.previous_type_code,
            "new_status": prepared.new_type_code,
            "changed": {"previous_membership_character_relationship_id": str(relationship_id)},
        },
    )
    return new_id


# =====================================================================================================
# Revoke character relationship
# =====================================================================================================


def prepare_revoke_relationship(
    connection: Connection,
    plan: AuthorizationPlan,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    actor_membership_id: uuid.UUID,
    relationship_id: uuid.UUID,
    reservation_id: uuid.UUID | None,
) -> AccessPrepared:
    found = (
        connection.execute(
            text(
                "SELECT cm.campaign_id, mcr.campaign_membership_id "
                "FROM security.membership_character_relationships mcr "
                "JOIN security.campaign_memberships cm "
                "ON cm.campaign_membership_id = mcr.campaign_membership_id "
                "WHERE mcr.membership_character_relationship_id = :r"
            ),
            {"r": relationship_id},
        )
        .mappings()
        .one_or_none()
    )
    in_campaign = found is not None and found["campaign_id"] == campaign_id
    _lock_actor(
        connection,
        plan,
        campaign_id=campaign_id,
        actor_user_id=actor_user_id,
        actor_membership_id=actor_membership_id,
    )
    plan.lock(connection, CAMPAIGN_KEY_SHARE_LOCK, {"campaign": campaign_id})
    outstanding: tuple[tuple[Any, ...], ...] = ()
    if in_campaign and found is not None:
        outstanding = plan.lock(
            connection,
            RELATIONSHIP_OUTSTANDING_LOCK,
            {"row": relationship_id, "membership": found["campaign_membership_id"]},
        )
    if reservation_id is not None:
        plan.lock(connection, RECEIPT_LOCK, {"receipt": reservation_id})
    if not in_campaign:
        raise MembershipNotInCampaignError(
            f"membership character relationship {relationship_id} does not belong to campaign "
            f"{campaign_id} (actual campaign: {found['campaign_id'] if found is not None else None})"
        )
    return AccessPrepared(
        world_id=_scope_world(connection, campaign_id),
        action_id=lookup_id(connection, "audit", "change_actions", "change_action_id", "updated"),
        will_write=bool(outstanding),
    )


def write_revoke_relationship(
    connection: Connection,
    plan: AuthorizationPlan,
    prepared: AccessPrepared,
    *,
    relationship_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    correlation_id: str | None,
) -> None:
    """The declared revocation and audit row (attempted only by a genuine revoke)."""
    if not prepared.will_write:
        return
    plan.execute(connection, REVOKE_RELATIONSHIP, {"target": relationship_id})
    plan.execute(
        connection,
        REVOKE_RELATIONSHIP_AUDIT,
        _audit_binds(
            prepared,
            record=relationship_id,
            actor_user_id=actor_user_id,
            correlation_id=correlation_id,
        ),
    )


# =====================================================================================================
# Create resource grant
# =====================================================================================================


def _supplied_target_field(**targets: uuid.UUID | None) -> str | None:
    supplied = [name for name in RESOURCE_GRANT_TARGET_FIELDS if targets[name] is not None]
    return supplied[0] if len(supplied) == 1 else None


def prepare_create_grant(  # noqa: C901, PLR0912, PLR0915 - one linear lock and refusal sequence
    connection: Connection,
    plan: AuthorizationPlan,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    actor_membership_id: uuid.UUID,
    grantee_membership_id: uuid.UUID | None,
    grantee_group_id: uuid.UUID | None,
    capability_code: str,
    effect: str,
    character_id: uuid.UUID | None,
    entity_id: uuid.UUID | None,
    knowledge_item_id: uuid.UUID | None,
    quest_id: uuid.UUID | None,
    session_id: uuid.UUID | None,
    event_id: uuid.UUID | None,
    reservation_id: uuid.UUID | None,
) -> AccessPrepared:
    targets = {
        "character_id": character_id,
        "entity_id": entity_id,
        "knowledge_item_id": knowledge_item_id,
        "quest_id": quest_id,
        "session_id": session_id,
        "event_id": event_id,
    }
    target_field = _supplied_target_field(**targets)
    entity_rooted = character_id or entity_id or knowledge_item_id or quest_id or event_id
    status_before = _status_before(connection, grantee_membership_id)
    # 1. actor role rows, then the group grantee (AO-1: a transaction holding a group row never waits for a role row; a membership
    #    grantee wins when both are supplied, as before)
    plan.lock(connection, ACTOR_ROLES_LOCK, {"membership": actor_membership_id})
    group_keys: tuple[tuple[Any, ...], ...] = ()
    if grantee_membership_id is None and grantee_group_id is not None:
        group_keys = plan.lock(
            connection, GROUP_GRANTEE_LOCK, {"group": grantee_group_id, "campaign": campaign_id}
        )
    # 2. the membership class (C4), then accounts
    if grantee_membership_id is not None:
        lock_memberships(
            connection,
            plan,
            campaign_id=campaign_id,
            actor_membership_id=actor_membership_id,
            target_membership_id=grantee_membership_id,
        )
    else:
        plan.lock(
            connection,
            ACTOR_MEMBERSHIP_LOCK,
            {"membership": actor_membership_id, "campaign": campaign_id},
        )
    plan.lock(connection, ACTOR_ACCOUNT_LOCK, {"actor": actor_user_id})
    membership = (
        connection.execute(_MEMBERSHIP_ROW, {"m": grantee_membership_id}).mappings().one_or_none()
        if grantee_membership_id is not None
        else None
    )
    membership_in_campaign = membership is not None and membership["campaign_id"] == campaign_id
    if membership_in_campaign and membership is not None:
        plan.lock(connection, TARGET_ACCOUNT_LOCK, {"target_user": membership["user_id"]})
    # 3. campaign, catalogue, target
    plan.lock(connection, CAMPAIGN_ROW_LOCK, {"campaign": campaign_id})
    capability_keys: tuple[tuple[Any, ...], ...] = ()
    if target_field is not None:
        capability_keys = plan.lock(connection, CAPABILITY_LOCK, {"code": capability_code})
    child_keys: tuple[tuple[Any, ...], ...] = ()
    child_lock_ran = False
    if entity_rooted is not None:
        plan.lock(connection, TARGET_ENTITY_LOCK, {"entity": entity_rooted})
        if character_id is not None:
            child_keys = plan.lock(connection, CHARACTER_ROW_LOCK, {"character": character_id})
            child_lock_ran = True
        elif knowledge_item_id is not None:
            child_keys = plan.lock(
                connection, KNOWLEDGE_ITEM_ROW_LOCK, {"knowledge_item": knowledge_item_id}
            )
            child_lock_ran = True
        elif quest_id is not None:
            child_keys = plan.lock(connection, QUEST_ROW_LOCK, {"quest": quest_id})
            child_lock_ran = True
        elif event_id is not None:
            child_keys = plan.lock(connection, EVENT_ROW_LOCK, {"event": event_id})
            child_lock_ran = True
    session_keys: tuple[tuple[Any, ...], ...] = ()
    if session_id is not None:
        session_keys = plan.lock(connection, SESSION_LOCK, {"session": session_id})
    if reservation_id is not None:
        plan.lock(connection, RECEIPT_LOCK, {"receipt": reservation_id})
    # 4. reads and refusals, in the order the command raised them
    if grantee_membership_id is not None:
        if not membership_in_campaign:
            raise MembershipNotInCampaignError(
                f"membership {grantee_membership_id} does not belong to campaign {campaign_id} "
                f"(actual campaign: {membership['campaign_id'] if membership is not None else None})"
            )
        assert membership is not None
        if not (
            membership["ended_at"] is None
            and membership["status_code"] == "active"
            and membership["status_is_active"]
        ):
            _became_ineligible_while_waiting(membership, status_before, grantee_membership_id)
            raise MembershipNotActiveError(
                f"membership {grantee_membership_id} is not currently an eligible, open "
                "membership to grant a resource grant to"
            )
    elif grantee_group_id is not None:
        group = (
            connection.execute(
                text(
                    "SELECT ag.campaign_id, ls.code AS lifecycle_status_code "
                    "FROM security.access_groups ag "
                    "JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = ag.lifecycle_status_id "
                    "WHERE ag.access_group_id = :g"
                ),
                {"g": grantee_group_id},
            )
            .mappings()
            .one_or_none()
        )
        if group is None or group["campaign_id"] != campaign_id or not group_keys:
            raise AccessGroupNotInCampaignError(
                f"access group {grantee_group_id} does not belong to campaign {campaign_id} "
                f"(actual campaign: {group['campaign_id'] if group is not None else None})"
            )
        if group["lifecycle_status_code"] != "active":
            raise AccessGroupNotActiveError(
                f"access group {grantee_group_id} is not currently active"
            )
    _require_campaign_active(connection, campaign_id)
    if (
        membership is not None
        and membership_in_campaign
        and connection.execute(_ACCOUNT_STATUS, {"u": membership["user_id"]}).scalar() != "active"
    ):
        raise MembershipNotActiveError(
            f"membership {grantee_membership_id}'s user {membership['user_id']} is not "
            "currently an active platform account"
        )
    expected_world_id = _scope_world(connection, campaign_id)
    _validate_grant_target(
        connection,
        campaign_id=campaign_id,
        expected_world_id=expected_world_id,
        entity_id=entity_id,
        entity_rooted=entity_rooted,
        event_id=event_id,
        session_id=session_id,
        effect=effect,
        session_locked=bool(session_keys),
    )
    if target_field is not None:
        allowed = RESOURCE_GRANT_CAPABILITY_CATALOG.get(target_field, frozenset())
        active = connection.execute(
            text("SELECT is_active FROM security.capabilities WHERE code = :c"),
            {"c": capability_code},
        ).scalar()
        if not capability_keys or not active or capability_code not in allowed:
            raise ResourceGrantCapabilityNotGrantableError(
                f"capability code {capability_code!r} does not exist, is not currently active, or is "
                f"not a valid capability for a {target_field!r} resource-grant target"
            )
        capability_id = capability_keys[0][0]
    else:
        # a malformed target shape: the plain lookup, then the constraint's refusal below, as before
        capability_id = lookup_id(
            connection, "security", "capabilities", "capability_id", capability_code
        )
    grantee_count = (grantee_membership_id is not None) + (grantee_group_id is not None)
    if grantee_count != 1 or target_field is None:
        raise GrantRowRefusedError(
            "a resource grant names exactly one grantee and exactly one target"
        )
    if entity_rooted is not None and entity_id is None and child_lock_ran and not child_keys:
        raise GrantRowRefusedError(f"target {entity_rooted} is not a row of the named kind")
    return AccessPrepared(
        world_id=expected_world_id,
        action_id=lookup_id(connection, "audit", "change_actions", "change_action_id", "created"),
        capability_id=capability_id,
    )


def _validate_grant_target(  # noqa: C901, PLR0913
    connection: Connection,
    *,
    campaign_id: uuid.UUID,
    expected_world_id: uuid.UUID,
    entity_id: uuid.UUID | None,
    entity_rooted: uuid.UUID | None,
    event_id: uuid.UUID | None,
    session_id: uuid.UUID | None,
    effect: str,
    session_locked: bool,
) -> None:
    """`access_grants._validate_resource_grant_target`, as plain reads under the locks already held."""
    if entity_rooted is not None:
        target = connection.execute(_ENTITY_ROW, {"e": entity_rooted}).mappings().one_or_none()
        if not (
            target is not None
            and target["world_id"] == expected_world_id
            and target["lifecycle_status_code"] == "active"
        ):
            raise TargetNotInCampaignWorldError(
                f"resource grant target {entity_rooted} does not exist in world "
                f"{expected_world_id}, or is not currently active "
                f"(actual world: {target['world_id'] if target is not None else None})"
            )
        entity_type_code = target["entity_type_code"]
        if (
            entity_id is not None
            and entity_type_code in _OWN_COLUMN_ENTITY_TYPE_CODES
            and not (entity_type_code in _CHARACTER_ENTITY_TYPE_CODES and effect == "deny")
        ):
            raise TargetNotInCampaignWorldError(
                f"entity {entity_id} is a {entity_type_code!r} entity, which has its "
                "own resource-grant target column and must not be granted through entity_id"
            )
    if event_id is not None:
        event_campaign_id = connection.execute(
            text("SELECT campaign_id FROM narrative.events WHERE event_id = :e"), {"e": event_id}
        ).scalar()
        if event_campaign_id is not None and event_campaign_id != campaign_id:
            raise TargetNotInCampaignWorldError(
                f"event {event_id} belongs to campaign {event_campaign_id}, not {campaign_id}"
            )
    if session_id is not None:
        validate_session_campaign(connection, campaign_id=campaign_id, session_id=session_id)
        status = connection.execute(
            text(
                "SELECT ls.code FROM campaign.sessions s "
                "JOIN core.lifecycle_statuses ls ON ls.lifecycle_status_id = s.lifecycle_status_id "
                "WHERE s.session_id = :s"
            ),
            {"s": session_id},
        ).scalar()
        if status != "active" or not session_locked:
            raise TargetNotInCampaignWorldError(f"session {session_id} is not currently active")


def write_create_grant(
    connection: Connection,
    plan: AuthorizationPlan,
    prepared: AccessPrepared,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    actor_membership_id: uuid.UUID,
    grantee_membership_id: uuid.UUID | None,
    grantee_group_id: uuid.UUID | None,
    effect: str,
    character_id: uuid.UUID | None,
    entity_id: uuid.UUID | None,
    knowledge_item_id: uuid.UUID | None,
    quest_id: uuid.UUID | None,
    session_id: uuid.UUID | None,
    event_id: uuid.UUID | None,
    reason: str | None,
    changed: dict[str, Any],
    correlation_id: str | None,
) -> uuid.UUID:
    created = plan.execute(
        connection,
        CREATE_GRANT_INSERT,
        {
            "campaign": campaign_id,
            "grantee_membership": grantee_membership_id,
            "grantee_group": grantee_group_id,
            "capability": prepared.capability_id,
            "effect": effect,
            "character": character_id,
            "entity": entity_id,
            "knowledge_item": knowledge_item_id,
            "quest": quest_id,
            "session": session_id,
            "event": event_id,
            "granted_by": actor_membership_id,
            "reason": reason,
        },
    )
    new_id = created.keys[0][0]
    assert isinstance(new_id, uuid.UUID)
    plan.execute(
        connection,
        CREATE_GRANT_AUDIT,
        {
            **_audit_binds(
                prepared, record=new_id, actor_user_id=actor_user_id, correlation_id=correlation_id
            ),
            "changed": changed,
        },
    )
    return new_id


# =====================================================================================================
# Revoke resource grant
# =====================================================================================================

_GRANT_FOR_REVOKE = text(f"""
    SELECT rg.campaign_id, rg.revoked_at, rg.grantee_campaign_membership_id,
           rg.grantee_access_group_id, rg.effect, cap.code AS capability_code,
           {", ".join(f"rg.{column}" for column in RESOURCE_GRANT_TARGET_FIELDS)}
    FROM security.resource_grants rg
    JOIN security.capabilities cap ON cap.capability_id = rg.capability_id
    WHERE rg.resource_grant_id = :g
""")


def prepare_revoke_grant(
    connection: Connection,
    plan: AuthorizationPlan,
    *,
    campaign_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    actor_membership_id: uuid.UUID,
    resource_grant_id: uuid.UUID,
    reservation_id: uuid.UUID | None,
) -> AccessPrepared:
    _lock_actor(
        connection,
        plan,
        campaign_id=campaign_id,
        actor_user_id=actor_user_id,
        actor_membership_id=actor_membership_id,
    )
    plan.lock(connection, CAMPAIGN_KEY_SHARE_LOCK, {"campaign": campaign_id})
    outstanding = plan.lock(
        connection,
        GRANT_OUTSTANDING_LOCK,
        {"grant": resource_grant_id, "campaign": campaign_id},
    )
    if reservation_id is not None:
        plan.lock(connection, RECEIPT_LOCK, {"receipt": reservation_id})
    row = connection.execute(_GRANT_FOR_REVOKE, {"g": resource_grant_id}).mappings().one_or_none()
    if row is None or row["campaign_id"] != campaign_id:
        raise ResourceGrantNotInCampaignError(
            f"resource grant {resource_grant_id} does not belong to campaign {campaign_id} "
            f"(actual campaign: {row['campaign_id'] if row is not None else None})"
        )
    will_write = row["revoked_at"] is None
    if will_write != bool(outstanding):  # the lock's own evidence and the row read cannot differ
        raise RuntimeError("the resource grant changed under its own lock")
    changed: dict[str, Any] | None = None
    if will_write:
        field = _supplied_target_field(**{name: row[name] for name in RESOURCE_GRANT_TARGET_FIELDS})
        changed = {
            "grantee_campaign_membership_id": (
                str(row["grantee_campaign_membership_id"])
                if row["grantee_campaign_membership_id"] is not None
                else None
            ),
            "grantee_access_group_id": (
                str(row["grantee_access_group_id"])
                if row["grantee_access_group_id"] is not None
                else None
            ),
            "target_kind": field,
            "target_id": str(row[field]) if field is not None else None,
            "capability_code": row["capability_code"],
            "effect": row["effect"],
        }
    return AccessPrepared(
        world_id=_scope_world(connection, campaign_id),
        action_id=lookup_id(connection, "audit", "change_actions", "change_action_id", "updated"),
        will_write=will_write,
        changed=changed,
    )


def write_revoke_grant(
    connection: Connection,
    plan: AuthorizationPlan,
    prepared: AccessPrepared,
    *,
    resource_grant_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    correlation_id: str | None,
) -> None:
    """The declared revocation and audit row (attempted only by a genuine revoke)."""
    if not prepared.will_write:
        return
    plan.execute(connection, REVOKE_GRANT, {"target": resource_grant_id})
    plan.execute(
        connection,
        REVOKE_GRANT_AUDIT,
        {
            **_audit_binds(
                prepared,
                record=resource_grant_id,
                actor_user_id=actor_user_id,
                correlation_id=correlation_id,
            ),
            "changed": prepared.changed,
        },
    )


__all__ = [
    "CHANGE_RELATIONSHIP_DECLARATIONS",
    "CREATE_GRANT_DECLARATIONS",
    "GRANT_RECEIPT",
    "GRANT_RELATIONSHIP_DECLARATIONS",
    "REVOKE_GRANT_DECLARATIONS",
    "REVOKE_RELATIONSHIP_DECLARATIONS",
    "AccessPrepared",
    "GrantRowRefusedError",
    "prepare_change_relationship",
    "prepare_create_grant",
    "prepare_grant_relationship",
    "prepare_revoke_grant",
    "prepare_revoke_relationship",
    "write_change_relationship",
    "write_create_grant",
    "write_grant_relationship",
    "write_revoke_grant",
    "write_revoke_relationship",
]
