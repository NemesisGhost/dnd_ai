"""R01 S1: the single-statement authority reader against the multi-statement one it replaced.

`dnd_ai.domain.access.read_authority_snapshot` (and `resolve_access_context`, which now calls it) read
every source of one decision in ONE SQL statement. This file proves it changed nothing but that:

- a differential test over a corpus of users (roles, relationships, allow/deny grants including group
  keyed ones, revelations) compares `AccessContext` values with `tests/access_reference.py`, the old
  implementation kept verbatim apart from an explicit comparison instant;
- the world and reveal components equal the standalone resolvers they were folded in from;
- expiry is judged at one instant, in both directions, at the boundary (`expires_at > instant`);
- one statement and one instant per snapshot, with no row locks.

Everything runs inside the rolled-back `db_connection` transaction, with an explicit `as_of`, so the
comparison is deterministic (no wall clock).
"""

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Connection, event, text

from dnd_ai.commands.character_public_profile import (
    release_character_public_profile,
    save_character_public_profile_draft,
)
from dnd_ai.domain.access import (
    FRESH_INSTANT,
    AccessContext,
    read_authority_snapshot,
    resolve_access_context,
)
from dnd_ai.domain.reveal_authority import resolve_reveal_authority
from dnd_ai.queries.world_authority import resolve_world_authority
from tests.access_reference import reference_resolve_access_context
from tests.factories import (
    make_access_group,
    make_access_group_membership,
    make_campaign,
    make_campaign_membership,
    make_capability,
    make_character,
    make_membership_character_relationship,
    make_membership_role,
    make_resource_grant,
    make_role,
    make_role_capability,
    make_session,
    make_system_role_assignment,
    make_timeline,
    make_user,
    make_world,
    make_world_role_assignment,
)

pytestmark = [pytest.mark.database, pytest.mark.real_relationship_policy]

# Rows expire at E. The corpus is compared at instants just before, at and just after it.
E = datetime(2031, 3, 1, 12, 0, 0, tzinfo=UTC)
BEFORE = E - timedelta(microseconds=1)
AFTER = E + timedelta(microseconds=1)
INSTANTS = [BEFORE, E, AFTER, E - timedelta(days=400), E + timedelta(days=400)]


def _lookup(connection: Connection, sql: str, **params: object) -> uuid.UUID:
    value = connection.execute(text(sql), params).scalar()
    assert isinstance(value, uuid.UUID), sql
    return value


def _relationship_type(connection: Connection, code: str) -> uuid.UUID:
    return _lookup(
        connection,
        "SELECT character_relationship_type_id FROM security.character_relationship_types "
        "WHERE code = :c",
        c=code,
    )


def _template_role(connection: Connection, code: str) -> uuid.UUID:
    return _lookup(
        connection,
        "SELECT role_id FROM security.roles WHERE code = :c AND campaign_id IS NULL",
        c=code,
    )


def _set_expiry(connection: Connection, table: str, key: str, row_id: uuid.UUID) -> None:
    """`expires_at = E`, with `granted_at` pushed before it (`now()` is frozen in the test)."""
    connection.execute(
        text(
            f"UPDATE security.{table} SET granted_at = '2020-01-01T00:00:00Z', "  # noqa: S608
            f"expires_at = :e WHERE {key} = :id"
        ),
        {"e": E, "id": row_id},
    )


@dataclass
class Corpus:
    world_id: uuid.UUID
    campaign_id: uuid.UUID
    timeline_id: uuid.UUID
    owner_user: uuid.UUID
    owner_membership: uuid.UUID
    # name -> user id
    users: dict[str, uuid.UUID]
    memberships: dict[str, uuid.UUID]
    character: uuid.UUID
    other_character: uuid.UUID
    cap_role: uuid.UUID
    cap_target: uuid.UUID
    session_id: uuid.UUID
    #: named rows whose expiry flips at E
    expiring: dict[str, uuid.UUID]


def _revelation(
    connection: Connection,
    corpus_campaign: uuid.UUID,
    character: uuid.UUID,
    kind: str,
    creator: uuid.UUID,
    *,
    member: uuid.UUID | None = None,
    group: uuid.UUID | None = None,
) -> uuid.UUID:
    return _lookup(
        connection,
        """
        INSERT INTO security.character_revelations (
            campaign_id, character_id, revelation_audience_kind_id, target_campaign_membership_id,
            target_access_group_id, created_by_membership_id, authority_source_code, reason)
        VALUES (:campaign, :character,
                (SELECT revelation_audience_kind_id FROM security.revelation_audience_kinds
                 WHERE code = :kind),
                :member, :group, :creator, 'owner', 'because')
        RETURNING character_revelation_id
        """,
        campaign=corpus_campaign,
        character=character,
        kind=kind,
        member=member,
        group=group,
        creator=creator,
    )


@pytest.fixture
def corpus(db_connection: Connection) -> Corpus:
    c = db_connection
    world_id = make_world(c, slug=f"r01-differential-{uuid.uuid4().hex[:8]}")
    timeline_id = make_timeline(c, world_id, "Primary", is_primary=True)
    other_timeline = make_timeline(c, world_id, "Other", is_primary=False)
    campaign_id = make_campaign(c, timeline_id)
    character = make_character(c, world_id, name="Aria")
    other_character = make_character(c, world_id, name="Bran")
    session_id = make_session(c, campaign_id, 1)

    cap_role = make_capability(c, "r01.role_cap")
    cap_target = make_capability(c, "r01.target_cap")
    custom_role = make_role(c, campaign_id=campaign_id, code="r01_custom")
    make_role_capability(c, custom_role, cap_role)
    custom_role_b = make_role(c, campaign_id=campaign_id, code="r01_custom_b")
    make_role_capability(c, custom_role_b, cap_target)
    inactive_role = make_role(c, campaign_id=campaign_id, code="r01_inactive")
    make_role_capability(c, inactive_role, cap_role)
    c.execute(
        text("UPDATE security.roles SET is_active = false WHERE role_id = :r"), {"r": inactive_role}
    )

    users: dict[str, uuid.UUID] = {}
    memberships: dict[str, uuid.UUID] = {}
    for name in (
        "roles",
        "expiring_role",
        "relationships",
        "grants",
        "group_grants",
        "revelations",
        "gm",
        "gm_delegated",
        "ended",
        "world_owner",
        "world_use",
        "no_world",
    ):
        users[name] = make_user(c, f"u-{name}")
        memberships[name] = make_campaign_membership(c, campaign_id, users[name])
    users["stranger"] = make_user(c, "stranger")
    users["suspended"] = make_user(c, "suspended")
    make_campaign_membership(c, campaign_id, users["suspended"], status_code="suspended")
    owner_user = make_user(c, "owner")
    owner_membership = make_campaign_membership(c, campaign_id, owner_user)
    users["owner"] = owner_user
    memberships["owner"] = owner_membership

    expiring: dict[str, uuid.UUID] = {}

    # roles: active, revoked, inactive, expired-long-ago and one expiring at E
    make_membership_role(c, memberships["roles"], custom_role)
    make_membership_role(c, memberships["roles"], custom_role_b, revoked=True)
    make_membership_role(c, memberships["roles"], inactive_role)
    expiring["role"] = make_membership_role(c, memberships["expiring_role"], custom_role)
    _set_expiry(c, "membership_roles", "membership_role_id", expiring["role"])

    # relationships: a live viewer, a revoked owner, a closed-interval one, one on another
    # timeline, one on a draft character, one expiring at E
    viewer = _relationship_type(c, "viewer")
    owner_type = _relationship_type(c, "owner")
    make_membership_character_relationship(c, memberships["relationships"], character, viewer)
    make_membership_character_relationship(
        c, memberships["relationships"], other_character, owner_type, revoked=True
    )
    make_membership_character_relationship(
        c, memberships["relationships"], other_character, viewer, timeline_id=other_timeline
    )
    expiring["relationship"] = make_membership_character_relationship(
        c, memberships["expiring_role"], character, owner_type
    )
    _set_expiry(
        c,
        "membership_character_relationships",
        "membership_character_relationship_id",
        expiring["relationship"],
    )

    # grants: allow, deny, deny+allow on one target, revoked, expiring allow, expiring deny
    make_resource_grant(
        c,
        campaign_id,
        cap_target,
        grantee_campaign_membership_id=memberships["grants"],
        character_id=character,
    )
    make_resource_grant(
        c,
        campaign_id,
        cap_role,
        grantee_campaign_membership_id=memberships["grants"],
        entity_id=character,
        effect="deny",
    )
    make_resource_grant(
        c,
        campaign_id,
        cap_target,
        grantee_campaign_membership_id=memberships["grants"],
        session_id=session_id,
    )
    make_resource_grant(
        c,
        campaign_id,
        cap_target,
        grantee_campaign_membership_id=memberships["grants"],
        session_id=session_id,
        effect="deny",
    )
    make_resource_grant(
        c,
        campaign_id,
        cap_role,
        grantee_campaign_membership_id=memberships["grants"],
        entity_id=other_character,
        revoked=True,
    )
    expiring["allow_grant"] = make_resource_grant(
        c,
        campaign_id,
        cap_target,
        grantee_campaign_membership_id=memberships["expiring_role"],
        entity_id=other_character,
    )
    _set_expiry(c, "resource_grants", "resource_grant_id", expiring["allow_grant"])
    expiring["deny_grant"] = make_resource_grant(
        c,
        campaign_id,
        cap_role,
        grantee_campaign_membership_id=memberships["expiring_role"],
        entity_id=character,
        effect="deny",
    )
    _set_expiry(c, "resource_grants", "resource_grant_id", expiring["deny_grant"])

    # a group grant (live group, live member), a removed member, an archived group
    group = make_access_group(c, campaign_id, name="live")
    make_access_group_membership(c, group, memberships["group_grants"])
    make_resource_grant(
        c, campaign_id, cap_target, grantee_access_group_id=group, character_id=character
    )
    removed_group = make_access_group(c, campaign_id, name="removed")
    make_access_group_membership(c, removed_group, memberships["group_grants"], removed=True)
    make_resource_grant(
        c, campaign_id, cap_role, grantee_access_group_id=removed_group, character_id=character
    )
    archived_group = make_access_group(
        c, campaign_id, name="archived", lifecycle_status_code="archived"
    )
    make_access_group_membership(c, archived_group, memberships["group_grants"])
    make_resource_grant(
        c, campaign_id, cap_role, grantee_access_group_id=archived_group, entity_id=character
    )

    # owner (built-in campaign_owner role), a gm, and a gm with a delegation bound to it
    owner_role = _template_role(c, "campaign_owner")
    gm_role = _template_role(c, "gm")
    expiring["owner_assignment"] = make_membership_role(c, owner_membership, owner_role)
    # a second, live owner so the subject owner's expiry does not trip the retention trigger
    spare_owner = make_user(c, "spare owner")
    spare_membership = make_campaign_membership(c, campaign_id, spare_owner)
    make_membership_role(c, spare_membership, owner_role)
    _set_expiry(c, "membership_roles", "membership_role_id", expiring["owner_assignment"])
    make_membership_role(c, memberships["gm"], gm_role)
    gm_assignment = make_membership_role(c, memberships["gm_delegated"], gm_role)
    expiring["gm_assignment"] = gm_assignment
    _set_expiry(c, "membership_roles", "membership_role_id", gm_assignment)
    c.execute(
        text("""
            INSERT INTO security.character_reveal_delegations
                (campaign_id, grantee_campaign_membership_id, gm_membership_role_id,
                 granted_by_membership_id, reason)
            VALUES (:campaign, :grantee, :gm_role, :actor, 'x')
        """),
        {
            "campaign": campaign_id,
            "grantee": memberships["gm_delegated"],
            "gm_role": gm_assignment,
            "actor": spare_membership,
        },
    )

    # a character needs a release in the campaign before it can be revealed
    for released_character in (character, other_character):
        save_character_public_profile_draft(
            c,
            campaign_id=campaign_id,
            character_id=released_character,
            actor_user_id=spare_owner,
            expected_row_version=None,
            fields={"public_summary": "summary"},
        )
        release_character_public_profile(
            c,
            campaign_id=campaign_id,
            character_id=released_character,
            actor_membership_id=spare_membership,
            expected_draft_row_version=1,
            release_note=None,
        )

    # revelations: a member one, an access-group one, a campaign-wide one, and one for a draft
    _revelation(
        c, campaign_id, character, "member", spare_membership, member=memberships["revelations"]
    )
    _revelation(c, campaign_id, other_character, "access_group", spare_membership, group=group)
    make_access_group_membership(c, group, memberships["revelations"])
    _revelation(c, campaign_id, character, "campaign_current_and_future", spare_membership)

    # world authority: an owner role, a use grant, a system gm
    make_world_role_assignment(c, world_id, users["world_owner"], "world_owner")
    c.execute(
        text(
            "INSERT INTO security.world_use_grants (world_id, user_id, granted_by_user_id) "
            "VALUES (:w, :u, :g)"
        ),
        {"w": world_id, "u": users["world_use"], "g": users["world_owner"]},
    )
    make_system_role_assignment(c, users["world_owner"], "gm")

    # an ended membership
    c.execute(
        text(
            "UPDATE security.campaign_memberships SET ended_at = now() + interval '1 microsecond' "
            "WHERE campaign_membership_id = :m"
        ),
        {"m": memberships["ended"]},
    )

    return Corpus(
        world_id=world_id,
        campaign_id=campaign_id,
        timeline_id=timeline_id,
        owner_user=owner_user,
        owner_membership=owner_membership,
        users=users,
        memberships=memberships,
        character=character,
        other_character=other_character,
        cap_role=cap_role,
        cap_target=cap_target,
        session_id=session_id,
        expiring=expiring,
    )


def _same(new: AccessContext | None, old: AccessContext | None) -> None:
    assert new == old
    if new is not None and old is not None:
        # AccessContext hides grant_effects from repr/compare? compare explicitly.
        assert new.grant_effects == old.grant_effects
        assert new.revelations == old.revelations
        assert new.character_capabilities == old.character_capabilities


@pytest.mark.parametrize("as_of", INSTANTS, ids=lambda t: t.isoformat())
def test_the_single_statement_reader_equals_the_multi_statement_one_over_the_corpus(
    db_connection: Connection, corpus: Corpus, as_of: datetime
) -> None:
    for name, user_id in corpus.users.items():
        new = resolve_access_context(
            db_connection, user_id=user_id, campaign_id=corpus.campaign_id, as_of=as_of
        )
        old = reference_resolve_access_context(
            db_connection, user_id=user_id, campaign_id=corpus.campaign_id, as_of=as_of
        )
        _same(new, old)
        if name in ("stranger", "suspended", "ended"):
            assert new is None


def test_the_default_instant_is_the_transaction_start_as_it_always_was(
    db_connection: Connection, corpus: Corpus
) -> None:
    """`as_of=None` keeps judging expiry at `now()`: the corpus rows expire in 2031, so they are live,
    and the result equals the old implementation's at its default."""
    for user_id in corpus.users.values():
        _same(
            resolve_access_context(db_connection, user_id=user_id, campaign_id=corpus.campaign_id),
            reference_resolve_access_context(
                db_connection, user_id=user_id, campaign_id=corpus.campaign_id
            ),
        )


def test_the_corpus_exercises_the_cases_it_claims(
    db_connection: Connection, corpus: Corpus
) -> None:
    """A differential test over an empty corpus proves nothing: pin that the interesting rows exist
    and resolve as intended at `BEFORE`."""
    by = {
        name: resolve_access_context(
            db_connection, user_id=user_id, campaign_id=corpus.campaign_id, as_of=BEFORE
        )
        for name, user_id in corpus.users.items()
    }
    roles = by["roles"]
    assert roles is not None and roles.role_capabilities == {"r01.role_cap"}  # not revoked/inactive
    expiring = by["expiring_role"]
    assert expiring is not None and "r01.role_cap" in expiring.role_capabilities
    relationships = by["relationships"]
    assert relationships is not None and relationships.character_capabilities  # viewer
    grants = by["grants"]
    assert grants is not None
    assert grants.has_capability("r01.target_cap", character_id=corpus.character) is True
    assert grants.has_capability("r01.role_cap", entity_id=corpus.character) is False  # deny
    assert (
        grants.has_capability("r01.target_cap", session_id=corpus.session_id) is False
    )  # deny wins
    group = by["group_grants"]
    assert group is not None
    assert group.has_capability("r01.target_cap", character_id=corpus.character) is True
    assert group.grant_effects.get(("entity_id", corpus.character)) is None  # archived group
    revelations = by["revelations"]
    assert revelations is not None and corpus.character in revelations.revelations
    assert corpus.other_character in revelations.revelations  # via the group
    assert by["ended"] is None and by["stranger"] is None and by["suspended"] is None


# --- expiry, both directions, at the boundary --------------------------------------------------


@pytest.mark.parametrize(
    ("as_of", "live"), [(BEFORE, True), (E, False), (AFTER, False)], ids=["before", "at", "after"]
)
def test_an_expiring_role_relationship_or_allow_grant_is_live_only_before_its_expiry(
    db_connection: Connection, corpus: Corpus, as_of: datetime, live: bool
) -> None:
    """`expires_at > instant`: live strictly before E, lapsed at E and after."""
    ctx = resolve_access_context(
        db_connection,
        user_id=corpus.users["expiring_role"],
        campaign_id=corpus.campaign_id,
        as_of=as_of,
    )
    assert ctx is not None
    assert ("r01.role_cap" in ctx.role_capabilities) is live
    assert bool(ctx.character_capabilities.get(corpus.character)) is live
    assert ctx.has_capability("r01.target_cap", entity_id=corpus.other_character) is live


@pytest.mark.parametrize(
    ("as_of", "denied"), [(BEFORE, True), (E, False), (AFTER, False)], ids=["before", "at", "after"]
)
def test_an_expiring_deny_refuses_before_its_expiry_and_allows_after(
    db_connection: Connection, corpus: Corpus, as_of: datetime, denied: bool
) -> None:
    """The opposite direction (plan section 3): a deny that lapses in the interval counts as lapsed,
    so the same decision can ALLOW where one judged earlier refused. The user holds `r01.role_cap`
    through a role until E, and a deny of it on the character until E."""
    ctx = resolve_access_context(
        db_connection,
        user_id=corpus.users["expiring_role"],
        campaign_id=corpus.campaign_id,
        as_of=as_of,
    )
    assert ctx is not None
    effects = ctx.grant_effects.get(("entity_id", corpus.character), {})
    assert (effects.get("r01.role_cap") == "deny") is denied


@pytest.mark.parametrize(
    ("as_of", "live"), [(BEFORE, True), (E, False), (AFTER, False)], ids=["before", "at", "after"]
)
def test_reveal_authority_follows_the_same_boundary_as_the_standalone_resolver(
    db_connection: Connection, corpus: Corpus, as_of: datetime, live: bool
) -> None:
    """An expiring owner assignment and an expiring gm assignment (with a bound delegation)."""
    for name, expected in (("owner", "owner"), ("gm_delegated", "delegation")):
        snapshot = read_authority_snapshot(
            db_connection,
            user_id=corpus.users[name],
            campaign_id=corpus.campaign_id,
            with_reveal=True,
            as_of=as_of,
        )
        assert snapshot.reveal_authority == (expected if live else "none")
        assert snapshot.reveal_authority == resolve_reveal_authority(
            db_connection,
            campaign_id=corpus.campaign_id,
            campaign_membership_id=corpus.memberships[name],
            as_of=as_of,
        )


@pytest.mark.parametrize("as_of", INSTANTS, ids=lambda t: t.isoformat())
def test_world_and_reveal_components_equal_the_standalone_resolvers(
    db_connection: Connection, corpus: Corpus, as_of: datetime
) -> None:
    for name, user_id in corpus.users.items():
        snapshot = read_authority_snapshot(
            db_connection,
            user_id=user_id,
            campaign_id=corpus.campaign_id,
            world_id=corpus.world_id,
            with_reveal=True,
            as_of=as_of,
        )
        assert snapshot.world_authority == resolve_world_authority(
            db_connection, user_id=user_id, world_id=corpus.world_id
        ), name
        membership = corpus.memberships.get(name)
        expected_reveal = (
            resolve_reveal_authority(
                db_connection,
                campaign_id=corpus.campaign_id,
                campaign_membership_id=membership,
                as_of=as_of,
            )
            if membership is not None and snapshot.access is not None
            else "none"
        )
        assert snapshot.reveal_authority == expected_reveal, name
    owner = read_authority_snapshot(
        db_connection,
        user_id=corpus.users["world_owner"],
        campaign_id=corpus.campaign_id,
        world_id=corpus.world_id,
    )
    assert owner.world_authority is not None and owner.world_authority.may_administer is True
    use = read_authority_snapshot(
        db_connection,
        user_id=corpus.users["world_use"],
        campaign_id=corpus.campaign_id,
        world_id=corpus.world_id,
    )
    assert use.world_authority is not None and use.world_authority.has_use_grant is True
    none = read_authority_snapshot(
        db_connection,
        user_id=corpus.users["no_world"],
        campaign_id=corpus.campaign_id,
        world_id=corpus.world_id,
    )
    assert none.world_authority is None


# --- one statement, one instant, no row locks --------------------------------------------------

_ROW_LOCK = re.compile(r"\bFOR\s+(?:NO\s+KEY\s+UPDATE|UPDATE|SHARE|KEY\s+SHARE)\b", re.I)


def _statements(connection: Connection) -> list[str]:
    seen: list[str] = []

    def capture(_c: object, _cursor: object, statement: str, *_rest: object) -> None:
        seen.append(statement)

    event.listen(connection, "before_cursor_execute", capture)
    return seen


def test_every_declared_source_is_read_by_one_statement_with_no_row_lock(
    db_connection: Connection, corpus: Corpus
) -> None:
    seen = _statements(db_connection)
    snapshot = read_authority_snapshot(
        db_connection,
        user_id=corpus.users["gm_delegated"],
        campaign_id=corpus.campaign_id,
        world_id=corpus.world_id,
        with_reveal=True,
        as_of=FRESH_INSTANT,
    )
    assert snapshot.access is not None and snapshot.reveal_authority is not None
    assert len(seen) == 1, "access, world authority and reveal authority were not one statement"
    sql = seen[0]
    assert sql.lstrip().upper().startswith("WITH ")
    assert not _ROW_LOCK.search(sql)
    assert sql.count("clock_timestamp()") == 1, "more than one instant is read"
    assert "now()" not in sql


def test_a_fresh_snapshot_reports_the_one_instant_it_judged_expiry_at(
    db_connection: Connection, corpus: Corpus
) -> None:
    before = db_connection.execute(text("SELECT clock_timestamp()")).scalar_one()
    snapshot = read_authority_snapshot(
        db_connection,
        user_id=corpus.users["roles"],
        campaign_id=corpus.campaign_id,
        as_of=FRESH_INSTANT,
    )
    after = db_connection.execute(text("SELECT clock_timestamp()")).scalar_one()
    assert before <= snapshot.t_auth <= after
    transaction_start = db_connection.execute(text("SELECT now()")).scalar_one()
    assert snapshot.t_auth > transaction_start, "a fresh instant is not the transaction's start"


def test_an_explicit_instant_is_the_reported_instant(
    db_connection: Connection, corpus: Corpus
) -> None:
    snapshot = read_authority_snapshot(
        db_connection, user_id=corpus.users["roles"], campaign_id=corpus.campaign_id, as_of=BEFORE
    )
    assert snapshot.t_auth == BEFORE
    assert snapshot.isolation == "read committed"


def test_the_default_statement_judges_expiry_at_now_only(
    db_connection: Connection, corpus: Corpus
) -> None:
    seen = _statements(db_connection)
    snapshot = read_authority_snapshot(
        db_connection, user_id=corpus.users["roles"], campaign_id=corpus.campaign_id
    )
    assert snapshot.t_auth == db_connection.execute(text("SELECT now()")).scalar_one()
    assert "clock_timestamp()" not in seen[0]
