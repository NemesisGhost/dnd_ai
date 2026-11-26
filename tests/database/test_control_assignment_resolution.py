"""P15-C11-S01-T02: control assignments resolve through a clock-aware, closed matrix (E1-E24).

ADR 0021 sections 2.4-2.6 and 2.9. An assignment is a marked row of `security.membership_character_relationships`.
It confers only `CONTROL_ASSIGNMENT_CAPABILITIES`, only while in effect (ongoing, or dated with a campaign clock
inside the half-open period), only in its own campaign, and never through the legacy relationship matrix. Every
legacy row keeps its legacy meaning (E11, E14, E20, E21).

The core cases resolve through the real `resolve_access_context` on a rolled-back transaction. The reader cases
(effective access, access overview, legacy change and revoke, the party roster, archive, membership end, audit
history, bootstrap) use the same fixtures as the existing tests of those readers.
"""

import re
import uuid

import pytest
from sqlalchemy import Connection, event, text

from dnd_ai.api.world_explorer import (
    _grant_denied_entity_ids,
    resolve_world_character_visibility,
)
from dnd_ai.commands.access_grants import (
    MembershipNotInCampaignError,
    change_character_relationship,
    revoke_character_relationship,
)
from dnd_ai.commands.memberships import end_campaign_membership
from dnd_ai.domain.access import (
    BUILTIN_RELATIONSHIP_CAPABILITIES,
    CONTROL_ASSIGNMENT_CAPABILITIES,
    read_authority_snapshot,
    resolve_access_context,
)
from dnd_ai.queries.access_overview import get_campaign_access_overview
from dnd_ai.queries.audit_history import _RELATIONSHIP_TABLE_COMMANDS
from dnd_ai.queries.bootstrap import get_session_bootstrap
from dnd_ai.queries.content_preconditions import archive_blocked_reason
from dnd_ai.queries.effective_access import resolve_member_effective_access
from tests.authoring_support import AuthoringHarness, harness_fixture_factory
from tests.content_support import ContentSetup, add_member
from tests.database.test_api_party_roster import Cast
from tests.factories import (
    make_campaign,
    make_campaign_membership,
    make_character,
    make_control_assignment,
    make_membership_character_relationship,
    make_membership_role,
    make_relationship_type_capability,
    make_resource_grant,
    make_timeline,
    make_timeline_clock,
    make_user,
    make_world,
    make_world_time,
    relationship_type_id,
    status_id,
    system_role_id,
)

pytestmark = [pytest.mark.database, pytest.mark.real_relationship_policy]

MATRIX = CONTROL_ASSIGNMENT_CAPABILITIES["primary_controller"]
_LEGACY_PRIMARY = BUILTIN_RELATIONSHIP_CAPABILITIES["primary_controller"]


class Scene:
    """A world, its primary timeline, a campaign, one player membership with no role, and one character."""

    def __init__(self, connection: Connection) -> None:
        self.connection = connection
        self.world_id = make_world(connection, slug=f"c11-{uuid.uuid4().hex[:8]}")
        self.timeline_id = make_timeline(connection, self.world_id, "Primary", is_primary=True)
        self.campaign_id = make_campaign(connection, self.timeline_id)
        self.user_id = make_user(connection, "Controller")
        self.membership_id = make_campaign_membership(connection, self.campaign_id, self.user_id)
        self.character_id = make_character(connection, self.world_id, name="Hero")
        self._keys = iter(range(1000, 100000, 10))

    def time(self, key: int) -> uuid.UUID:
        return make_world_time(self.connection, self.world_id, key)

    def clock(self, key: int, timeline_id: uuid.UUID | None = None) -> None:
        make_timeline_clock(self.connection, timeline_id or self.timeline_id, self.time(key))

    def assign(
        self,
        role: str = "primary_controller",
        kind: str = "ongoing",
        *,
        frm: int | None = None,
        to: int | None = None,
        character_id: uuid.UUID | None = None,
        membership_id: uuid.UUID | None = None,
        **kw: object,
    ) -> uuid.UUID:
        return make_control_assignment(
            self.connection,
            membership_id or self.membership_id,
            character_id or self.character_id,
            role,
            kind,
            from_time=self.time(frm) if frm is not None else None,
            to_time=self.time(to) if to is not None else None,
            **kw,  # type: ignore[arg-type]
        )

    def legacy(self, role: str = "primary_controller", **kw: object) -> uuid.UUID:
        return make_membership_character_relationship(
            self.connection,
            self.membership_id,
            self.character_id,
            relationship_type_id(self.connection, role),
            **kw,  # type: ignore[arg-type]
        )

    def access(self, campaign_id: uuid.UUID | None = None, user_id: uuid.UUID | None = None):  # type: ignore[no-untyped-def]
        return resolve_access_context(
            self.connection,
            user_id=user_id or self.user_id,
            campaign_id=campaign_id or self.campaign_id,
        )

    def caps(self, character_id: uuid.UUID | None = None) -> frozenset[str]:
        access = self.access()
        assert access is not None
        return access.character_capabilities.get(character_id or self.character_id, frozenset())


@pytest.fixture
def sc(db_connection: Connection) -> Scene:
    return Scene(db_connection)


# --- resolution -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("role", ["primary_controller", "co_controller"])
def test_an_in_effect_assignment_confers_exactly_the_matrix_set(sc: Scene, role: str) -> None:
    """E1 and E2: the two roles confer the identical set (OD-2), and nothing else."""
    sc.assign(role, "ongoing")
    access = sc.access()
    assert access is not None
    assert access.character_capabilities[sc.character_id] == MATRIX
    assert "character.control" in MATRIX
    assert not {"character.view_private", "character.view_knowledge"} & MATRIX
    assert access.role_capabilities == frozenset()
    assert not access.has_capability("canon.edit") and not access.has_capability("campaign.view")


def test_an_ongoing_assignment_with_no_clock_confers_the_matrix_set(sc: Scene) -> None:
    """E3 (OD-14: ongoing never needs a clock)."""
    assert sc.caps() == frozenset()
    sc.assign("primary_controller", "ongoing")
    assert sc.caps() == MATRIX


def test_a_dated_assignment_with_no_clock_confers_nothing(sc: Scene) -> None:
    """E4: undetermined is not in effect."""
    sc.assign("co_controller", "dated", frm=100)
    assert sc.caps() == frozenset()
    snapshot = read_authority_snapshot(
        sc.connection, user_id=sc.user_id, campaign_id=sc.campaign_id
    )
    assert snapshot.access is not None
    assert snapshot.access.control_clock_key is None
    assert snapshot.access.control_assignments == {}


@pytest.mark.parametrize(
    ("clock", "in_effect"),
    [(150, True), (100, True), (200, False), (250, False), (50, False)],
    ids=["inside", "equal-to-from", "equal-to-to", "after-to", "before-from-upcoming"],
)
def test_a_dated_assignment_is_in_effect_over_a_half_open_period(
    sc: Scene, clock: int, in_effect: bool
) -> None:
    """E5: the start is included and the end excluded."""
    sc.assign("primary_controller", "dated", frm=100, to=200)
    sc.clock(clock)
    assert sc.caps() == (MATRIX if in_effect else frozenset())


def test_an_open_ended_dated_assignment_runs_from_its_start(sc: Scene) -> None:
    sc.assign("co_controller", "dated", frm=100)
    sc.clock(10_000)
    assert sc.caps() == MATRIX


def test_a_branch_without_its_own_clock_uses_the_parent_clock_bounded_at_the_branch_point(
    sc: Scene,
) -> None:
    """E6: the parent's clock is 500, the branch point is 300. The branch's effective clock is 300, never the parent's
    later time."""
    sc.clock(500)
    branch = make_timeline(
        sc.connection,
        sc.world_id,
        "Branch",
        parent_timeline_id=sc.timeline_id,
        branch_world_time_id=sc.time(300),
    )
    campaign = make_campaign(sc.connection, branch)
    membership = make_campaign_membership(sc.connection, campaign, sc.user_id)
    make_control_assignment(
        sc.connection, membership, sc.character_id, "primary_controller", "dated",
        from_time=sc.time(200), to_time=sc.time(400),
    )  # fmt: skip
    other = make_character(sc.connection, sc.world_id, name="Later")
    make_control_assignment(
        sc.connection, membership, other, "co_controller", "dated", from_time=sc.time(400)
    )
    access = sc.access(campaign_id=campaign)
    assert access is not None
    assert access.control_clock_key == 300
    assert access.character_capabilities == {sc.character_id: MATRIX}


def test_an_assignment_in_one_campaign_confers_nothing_in_another_on_the_same_timeline(
    sc: Scene,
) -> None:
    """E7."""
    sc.assign("primary_controller", "ongoing")
    other = make_campaign(sc.connection, sc.timeline_id)
    make_campaign_membership(sc.connection, other, sc.user_id)
    access = sc.access(campaign_id=other)
    assert access is not None and access.character_capabilities == {}
    assert access.control_assignments == {}


@pytest.mark.parametrize(
    "case",
    ["revoked", "archived-character", "draft-character", "inactive-type", "ended-membership"],
)
def test_a_revoked_inactive_or_ended_assignment_confers_nothing(sc: Scene, case: str) -> None:
    """E8."""
    sc.assign("primary_controller", "ongoing", revoked=(case == "revoked"))
    assert sc.caps() == (frozenset() if case == "revoked" else MATRIX)
    if case == "archived-character":
        sc.connection.execute(
            text("UPDATE core.entities SET lifecycle_status_id = :s WHERE entity_id = :e"),
            {"s": status_id(sc.connection, "lifecycle_statuses", "archived"), "e": sc.character_id},
        )
    elif case == "draft-character":
        sc.connection.execute(
            text("UPDATE core.entities SET canon_status_id = :s WHERE entity_id = :e"),
            {"s": status_id(sc.connection, "canon_statuses", "draft"), "e": sc.character_id},
        )
    elif case == "inactive-type":
        sc.connection.execute(
            text(
                "UPDATE security.character_relationship_types SET is_active = false "
                "WHERE code = 'primary_controller'"
            )
        )
    elif case == "ended-membership":
        sc.connection.execute(
            text(
                "UPDATE security.campaign_memberships SET ended_at = now() + interval '1 second' "
                "WHERE campaign_membership_id = :m"
            ),
            {"m": sc.membership_id},
        )
        assert sc.access() is None
        return
    if case != "revoked":
        assert sc.caps() == frozenset()


def test_a_whole_character_deny_suppresses_an_assigned_character(sc: Scene) -> None:
    """E9 (ADR 0021 section 2.9): denies win over the assignment's capabilities and discovery."""
    sc.assign("primary_controller", "ongoing")
    sc.connection.execute(
        text("""
            INSERT INTO security.resource_grants
                (campaign_id, grantee_campaign_membership_id, capability_id, effect, character_id,
                 grant_source)
            SELECT :c, :m, cap.capability_id, 'deny', :ch, 'test'
            FROM security.capabilities cap WHERE cap.code = 'character.discover'
        """),
        {"c": sc.campaign_id, "m": sc.membership_id, "ch": sc.character_id},
    )
    view = sc.connection.execute(
        text("SELECT capability_id FROM security.capabilities WHERE code = 'campaign.view'")
    ).scalar_one()
    make_resource_grant(
        sc.connection,
        sc.campaign_id,
        view,
        grantee_campaign_membership_id=sc.membership_id,
        entity_id=sc.character_id,
        effect="deny",
    )
    access = sc.access()
    assert access is not None
    assert not access.has_capability("character.discover", character_id=sc.character_id)
    assert access.has_capability("character.view_summary", character_id=sc.character_id)
    assert sc.character_id in access.resource_grant_targets("campaign.view", "entity_id")[0]
    # the whole-character `campaign.view` deny reaches discovery through the denied-entity set, which overrides
    # `force_visible` in SQL (`cv_denied`)
    assert sc.character_id in _grant_denied_entity_ids(access)


def test_a_legacy_row_and_an_assignment_each_keep_their_own_set(sc: Scene) -> None:
    """E10."""
    sc.legacy("primary_controller")
    assert sc.caps() == _LEGACY_PRIMARY
    assignment = sc.assign("co_controller", "ongoing")
    assert sc.caps() == _LEGACY_PRIMARY | MATRIX
    access = sc.access()
    assert access is not None
    assert access.has_capability("character.view_private", character_id=sc.character_id)
    assert access.has_capability("character.control", character_id=sc.character_id)
    sc.connection.execute(
        text(
            "UPDATE security.membership_character_relationships SET revoked_at = now() "
            "WHERE membership_character_relationship_id = :a"
        ),
        {"a": assignment},
    )
    assert sc.caps() == _LEGACY_PRIMARY


def test_legacy_rows_are_unchanged(sc: Scene) -> None:
    """E11 (guard): R2 (a legacy primary confers its six and not `character.control`) and R3 (a legacy row dated
    after every clock, on a campaign with no clock, still confers its capabilities: the open-end rule)."""
    sc.legacy("primary_controller", effective_from_world_time_id=sc.time(9_999_999))
    caps = sc.caps()
    assert caps == _LEGACY_PRIMARY
    assert "character.control" not in caps and "character.view_private" in caps


def test_the_assigned_character_is_discoverable(sc: Scene) -> None:
    """E12: through a dated assignment with an end, which the legacy reading never honours, so only the assignment
    resolution can make the character discoverable."""
    sc.assign("co_controller", "dated", frm=100, to=200)
    sc.clock(150)
    access = sc.access()
    assert access is not None
    assert sc.character_id in resolve_world_character_visibility(access).force_visible
    other = make_character(sc.connection, sc.world_id, name="Unassigned")
    assert other not in resolve_world_character_visibility(access).force_visible


def test_the_context_exposes_the_sources_and_the_one_clock_and_the_statement_count_stays_one(
    sc: Scene,
) -> None:
    """E13."""
    ongoing = sc.assign("primary_controller", "ongoing")
    sc.clock(150)
    other = make_character(sc.connection, sc.world_id, name="Dated")
    dated = sc.assign("co_controller", "dated", frm=100, to=200, character_id=other)
    statements: list[str] = []

    def count(conn, cursor, statement, parameters, context, executemany):  # type: ignore[no-untyped-def]  # noqa: ANN001, ARG001
        statements.append(statement)

    event.listen(sc.connection, "before_cursor_execute", count)
    try:
        snapshot = read_authority_snapshot(
            sc.connection, user_id=sc.user_id, campaign_id=sc.campaign_id
        )
    finally:
        event.remove(sc.connection, "before_cursor_execute", count)
    assert len(statements) == 1
    assert not re.search(r"FOR (UPDATE|SHARE|NO KEY UPDATE|KEY SHARE)", statements[0])
    access = snapshot.access
    assert access is not None
    assert access.control_clock_key == 150
    assert {
        c: (s.assignment_id, s.role, s.kind) for c, s in access.control_assignments.items()
    } == {
        sc.character_id: (ongoing, "primary_controller", "ongoing"),
        other: (dated, "co_controller", "dated"),
    }


# --- the legacy path does not read assignment rows --------------------------------------------------------------


def test_bootstrap_offers_no_perspective_from_an_assignment(sc: Scene) -> None:
    """E22: perspectives need `character.view_knowledge`, which no assignment confers."""
    make_membership_role(sc.connection, sc.membership_id, system_role_id(sc.connection, "player"))
    sc.assign("primary_controller", "ongoing")
    campaign = get_session_bootstrap(sc.connection, user_id=sc.user_id).campaigns[0]
    assert campaign.character_perspectives == ()


def test_a_stray_type_capability_mapping_confers_nothing_on_an_assignment(sc: Scene) -> None:
    """E23: the matrix is code-only; `character_relationship_type_capabilities` is never read for assignments."""
    stray = sc.connection.execute(
        text("SELECT capability_id FROM security.capabilities WHERE code = 'canon.edit'")
    ).scalar_one()
    make_relationship_type_capability(
        sc.connection, relationship_type_id(sc.connection, "primary_controller"), stray
    )
    sc.assign("primary_controller", "ongoing")
    access = sc.access()
    assert access is not None
    assert access.character_capabilities[sc.character_id] == MATRIX
    assert not access.has_capability("canon.edit", character_id=sc.character_id)


def test_a_legacy_revoke_of_an_assignment_id_leaves_it_live_and_in_effect(sc: Scene) -> None:
    """E24 (with E17): the refused legacy revoke and the assignment's own resolution agree."""
    assignment = sc.assign("primary_controller", "ongoing")
    with pytest.raises(MembershipNotInCampaignError):
        sc.connection.execute(text("SAVEPOINT s"))
        revoke_character_relationship(
            sc.connection,
            membership_character_relationship_id=assignment,
            campaign_id=sc.campaign_id,
        )
    sc.connection.execute(text("ROLLBACK TO SAVEPOINT s"))
    assert (
        sc.connection.execute(
            text(
                "SELECT revoked_at IS NULL FROM security.membership_character_relationships "
                "WHERE membership_character_relationship_id = :a"
            ),
            {"a": assignment},
        ).scalar()
        is True
    )
    assert sc.caps() == MATRIX


# --- the readers of the table -----------------------------------------------------------------------------------


@pytest.fixture
def harness(db_connection: Connection):  # type: ignore[no-untyped-def]
    yield from harness_fixture_factory()(db_connection)


@pytest.fixture
def s(harness: AuthoringHarness, db_connection: Connection) -> ContentSetup:
    return ContentSetup(harness, db_connection)


def _membership(s: ContentSetup, actor: str = "player") -> uuid.UUID:
    value = s.connection.execute(
        text(
            "SELECT campaign_membership_id FROM security.campaign_memberships "
            "WHERE campaign_id = :c AND user_id = :u AND ended_at IS NULL"
        ),
        {"c": s.cid, "u": getattr(s, actor).user_id},
    ).scalar_one()
    assert isinstance(value, uuid.UUID)
    return value


def _timeline(s: ContentSetup) -> uuid.UUID:
    value = s.connection.execute(
        text("SELECT timeline_id FROM campaign.campaigns WHERE campaign_id = :c"), {"c": s.cid}
    ).scalar_one()
    assert isinstance(value, uuid.UUID)
    return value


def _character(s: ContentSetup, name: str = "Hero") -> uuid.UUID:
    return make_character(s.connection, s.world_id, name=name)


def test_effective_access_lists_an_in_effect_assignment_as_its_own_source(s: ContentSetup) -> None:
    """E15."""
    hero = _character(s)
    member = _membership(s)
    make_control_assignment(s.connection, member, hero, "primary_controller", "ongoing")
    undetermined = _character(s, "Undetermined")
    make_control_assignment(
        s.connection,
        member,
        undetermined,
        "co_controller",
        "dated",
        from_time=make_world_time(s.connection, s.world_id, 50),
    )
    view = resolve_member_effective_access(
        s.connection,
        campaign_id=uuid.UUID(s.cid),
        campaign_membership_id=member,
        timeline_id=_timeline(s),
    )
    assert view is not None
    sources = [
        (c.code, src.kind, src.label, src.target_display_name)
        for c in view.capabilities
        for src in c.sources
        if src.target_display_name in ("Hero", "Undetermined")
    ]
    assert (
        "character.control",
        "control_assignment",
        "Primary controller (ongoing)",
        "Hero",
    ) in sources
    assert not any(kind == "character_relationship" for _, kind, _, _ in sources)
    assert not any(name == "Undetermined" for *_, name in sources)
    codes = {c.code for c in view.capabilities}
    assert not {"character.view_private", "character.view_knowledge"} & codes


def test_the_access_overview_omits_assignments_and_keeps_legacy_rows(s: ContentSetup) -> None:
    """E16."""
    member = _membership(s)
    legacy, assigned = _character(s, "Legacy"), _character(s, "Assigned")
    make_membership_character_relationship(
        s.connection, member, legacy, relationship_type_id(s.connection, "owner")
    )
    make_control_assignment(s.connection, member, assigned, "primary_controller", "ongoing")
    overview = get_campaign_access_overview(
        s.connection, campaign_id=uuid.UUID(s.cid), timeline_id=_timeline(s)
    )
    row = next(m for m in overview if m.campaign_membership_id == member)
    assert [r.character_display_name for r in row.character_relationships] == ["Legacy"]


def _audit_rows(s: ContentSetup, record: uuid.UUID) -> int:
    return int(
        s.connection.execute(
            text("SELECT count(*) FROM audit.change_log WHERE record_id = :r"), {"r": record}
        ).scalar_one()
    )


def test_legacy_revoke_and_change_refuse_an_assignment_id_without_writing(s: ContentSetup) -> None:
    """E17, through the command and through each route: the non-disclosing refusal of a row of another campaign."""
    member = _membership(s)
    hero = _character(s)
    assignment = make_control_assignment(
        s.connection, member, hero, "primary_controller", "ongoing"
    )
    world_id = s.world_id
    co = relationship_type_id(s.connection, "co_controller")
    for call in (
        lambda: revoke_character_relationship(
            s.connection,
            membership_character_relationship_id=assignment,
            campaign_id=uuid.UUID(s.cid),
        ),
        lambda: change_character_relationship(
            s.connection,
            membership_character_relationship_id=assignment,
            campaign_id=uuid.UUID(s.cid),
            expected_world_id=world_id,
            new_relationship_type_id=co,
            granted_by_membership_id=_membership(s, "gm"),
        ),
    ):
        s.connection.execute(text("SAVEPOINT cmd"))
        with pytest.raises(MembershipNotInCampaignError):
            call()
        s.connection.execute(text("ROLLBACK TO SAVEPOINT cmd"))
    for path, body in (("revoke", {}), ("change", {"new_relationship_type_id": str(co)})):
        response = s.gm.post_raw(
            f"/campaigns/{s.cid}/character-relationships/{assignment}/{path}",
            body,
            key=s.gm.fresh_key(),
        )
        assert response.status_code == 404, (path, response.text)
    row = s.connection.execute(
        text(
            "SELECT revoked_at, character_relationship_type_id FROM "
            "security.membership_character_relationships "
            "WHERE membership_character_relationship_id = :a"
        ),
        {"a": assignment},
    ).one()
    assert row.revoked_at is None and row.character_relationship_type_id == relationship_type_id(
        s.connection, "primary_controller"
    )
    assert _audit_rows(s, assignment) == 0
    assert (
        s.connection.execute(
            text(
                "SELECT count(*) FROM security.membership_character_relationships "
                "WHERE campaign_membership_id = :m AND character_id = :c"
            ),
            {"m": member, "c": hero},
        ).scalar()
        == 1
    )


def test_the_party_roster_admits_an_in_effect_assignment_and_still_the_legacy_branch(
    s: ContentSetup,
) -> None:
    """E18."""
    cast = Cast(s)
    member = _membership(s)
    assert cast.names() == []
    assignment = make_control_assignment(
        s.connection, member, uuid.UUID(cast.alpha), "co_controller", "ongoing"
    )
    assert sorted(cast.names()) == ["Alpha", "Bravo"]
    s.connection.execute(
        text(
            "UPDATE security.membership_character_relationships SET revoked_at = now() "
            "WHERE membership_character_relationship_id = :a"
        ),
        {"a": assignment},
    )
    assert cast.names() == []
    # an upcoming dated assignment is not in effect: it does not qualify
    make_control_assignment(
        s.connection,
        member,
        uuid.UUID(cast.alpha),
        "primary_controller",
        "dated",
        from_time=make_world_time(s.connection, s.world_id, 900_000_000),
    )
    assert cast.names() == []
    # the legacy branch still qualifies
    make_membership_character_relationship(
        s.connection, member, uuid.UUID(cast.bravo), relationship_type_id(s.connection, "owner")
    )
    assert sorted(cast.names()) == ["Alpha", "Bravo"]


def test_a_denied_character_does_not_qualify_the_roster_through_an_assignment(
    s: ContentSetup,
) -> None:
    cast = Cast(s)
    member = _membership(s)
    make_control_assignment(
        s.connection, member, uuid.UUID(cast.alpha), "primary_controller", "ongoing"
    )
    assert sorted(cast.names()) == ["Alpha", "Bravo"]
    view = s.connection.execute(
        text("SELECT capability_id FROM security.capabilities WHERE code = 'campaign.view'")
    ).scalar_one()
    make_resource_grant(
        s.connection,
        uuid.UUID(s.cid),
        view,
        grantee_campaign_membership_id=member,
        entity_id=uuid.UUID(cast.alpha),
        effect="deny",
    )
    assert cast.names() == []


@pytest.mark.parametrize("period", ["dated-with-end", "dated-open", "ongoing"])
def test_an_unrevoked_assignment_blocks_archiving_until_it_is_revoked(
    s: ContentSetup, period: str
) -> None:
    """E19 (R-8): any unrevoked assignment blocks archive, whatever its period."""
    member = _membership(s)
    hero = _character(s)
    frm = make_world_time(s.connection, s.world_id, 10)
    to = make_world_time(s.connection, s.world_id, 20)
    assignment = make_control_assignment(
        s.connection,
        member,
        hero,
        "primary_controller",
        "ongoing" if period == "ongoing" else "dated",
        from_time=None if period == "ongoing" else frm,
        to_time=to if period == "dated-with-end" else None,
    )
    assert archive_blocked_reason(s.connection, entity_id=hero, entity_type_code="npc") is not None
    s.connection.execute(
        text(
            "UPDATE security.membership_character_relationships SET revoked_at = now() "
            "WHERE membership_character_relationship_id = :a"
        ),
        {"a": assignment},
    )
    assert archive_blocked_reason(s.connection, entity_id=hero, entity_type_code="npc") is None


def test_membership_end_revokes_assignments_and_frees_the_primary_slot(s: ContentSetup) -> None:
    """E20: the revocation is a guard (it already happens); the new primary after it needs T01's index."""
    member, gm = _membership(s), _membership(s, "gm")
    hero = _character(s)
    first = make_control_assignment(s.connection, member, hero, "primary_controller", "ongoing")
    end_campaign_membership(
        s.connection,
        campaign_membership_id=member,
        campaign_id=uuid.UUID(s.cid),
        ended_by_membership_id=gm,
    )
    assert (
        s.connection.execute(
            text(
                "SELECT revoked_at IS NOT NULL FROM security.membership_character_relationships "
                "WHERE membership_character_relationship_id = :a"
            ),
            {"a": first},
        ).scalar()
        is True
    )
    add_member(s.connection, s.cid, s.stranger.user_id, "player")
    other = _membership(s, "stranger")
    make_control_assignment(s.connection, other, hero, "primary_controller", "ongoing")


def test_assignment_audit_never_shows_under_character_relationships(s: ContentSetup) -> None:
    """E21 (guard): the history selects by the legacy relationship command names only, and an assignment id left
    unrecorded by the legacy commands has no row of its own."""
    assert set(_RELATIONSHIP_TABLE_COMMANDS) == {
        "grant_character_relationship",
        "change_character_relationship",
        "revoke_character_relationship",
    }
    assignment = make_control_assignment(
        s.connection, _membership(s), _character(s), "primary_controller", "ongoing"
    )
    assert _audit_rows(s, assignment) == 0
