"""Constraint and guard-trigger tests for revision 080 — security, identity,
and authorization: external identities, service accounts, campaign
membership and invitations, campaign-scoped roles and capabilities,
human-to-character relationships, access groups, and typed resource grants.

Every nontrivial constraint gets a positive and a negative test per
docs/DATABASE_CONVENTIONS.md §32.1. All tests run inside the fixture's
transaction and roll back. See tests/database/test_core_lookups_and_security.py
for the surviving revision-003 security.users tests.
"""

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError, InternalError, ProgrammingError

from tests.factories import (
    lookup_id,
    make_access_group,
    make_access_group_membership,
    make_campaign,
    make_campaign_invitation,
    make_campaign_membership,
    make_capability,
    make_character,
    make_character_relationship_type,
    make_event,
    make_knowledge_item,
    make_membership_character_relationship,
    make_membership_role,
    make_quest,
    make_relationship_type_capability,
    make_resource_grant,
    make_role,
    make_role_capability,
    make_service_account,
    make_session,
    make_timeline,
    make_user,
    make_world,
    make_world_time,
)

pytestmark = pytest.mark.database

# Trigger-raised errors surface as InternalError, constraint violations as
# IntegrityError; a few arrive as ProgrammingError depending on driver state.
CONSTRAINT_ERRORS = (IntegrityError, InternalError, ProgrammingError)


class Fixture:
    """One campaign, on its own world, with a GM and a player membership,
    a character, and one of each security.resource_grants target kind."""

    def __init__(self, connection: Connection) -> None:
        self.world_id = make_world(connection, slug="security-world")
        self.other_world_id = make_world(connection, slug="security-other-world")
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        self.other_world_timeline_id = make_timeline(
            connection, self.other_world_id, is_primary=True
        )
        self.campaign_id = make_campaign(connection, self.timeline_id)
        self.character_id = make_character(connection, self.world_id, name="PC")
        self.other_world_character_id = make_character(
            connection, self.other_world_id, name="Other World PC"
        )

        self.gm_user_id = make_user(connection, "GM")
        self.player_user_id = make_user(connection, "Player")
        self.gm_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.gm_user_id
        )
        self.player_membership_id = make_campaign_membership(
            connection, self.campaign_id, self.player_user_id
        )

        self.role_id = make_role(connection, campaign_id=self.campaign_id)
        self.capability_id = make_capability(connection)
        self.relationship_type_id = make_character_relationship_type(connection)
        self.access_group_id = make_access_group(connection, self.campaign_id)

        self.knowledge_item_id = make_knowledge_item(connection, self.world_id)
        self.quest_id = make_quest(connection, self.world_id)
        self.session_id = make_session(connection, self.campaign_id, 1)
        self.t0 = make_world_time(connection, self.world_id, 100)
        self.t1 = make_world_time(connection, self.world_id, 200)
        self.other_world_t0 = make_world_time(connection, self.other_world_id, 100)
        self.event_id = make_event(
            connection, self.world_id, self.timeline_id, self.t0, campaign_id=self.campaign_id
        )


@pytest.fixture
def f(db_connection: Connection) -> Fixture:
    return Fixture(db_connection)


# ---------------------------------------------------------------------------
# security.users (revision 080 shape)
# ---------------------------------------------------------------------------


def test_users_rejects_null_lifecycle_status_via_factory_status_id(
    db_connection: Connection,
) -> None:
    with pytest.raises(CONSTRAINT_ERRORS):
        db_connection.execute(
            text(
                "INSERT INTO security.users (display_name, lifecycle_status_id) VALUES ('X', NULL)"
            )
        )


# ---------------------------------------------------------------------------
# security.external_identities
# ---------------------------------------------------------------------------


def test_external_identities_creates_and_cascades_on_user_delete(db_connection: Connection) -> None:
    # A user with no campaign_memberships row — that FK is ON DELETE RESTRICT
    # and would otherwise block the delete this test exercises.
    user_id = make_user(db_connection, "Cascade Test User")
    db_connection.execute(
        text("""
            INSERT INTO security.external_identities (user_id, issuer, subject)
            VALUES (:u, 'https://idp.example', 'sub-1')
        """),
        {"u": user_id},
    )
    db_connection.execute(text("DELETE FROM security.users WHERE user_id = :u"), {"u": user_id})
    remaining = db_connection.execute(
        text("SELECT count(*) FROM security.external_identities WHERE user_id = :u"),
        {"u": user_id},
    ).scalar()
    assert remaining == 0


def test_external_identities_rejects_duplicate_active_issuer_subject(
    db_connection: Connection, f: Fixture
) -> None:
    db_connection.execute(
        text("""
            INSERT INTO security.external_identities (user_id, issuer, subject)
            VALUES (:u, 'https://idp.example', 'dupe-subject')
        """),
        {"u": f.gm_user_id},
    )
    with pytest.raises(CONSTRAINT_ERRORS):
        db_connection.execute(
            text("""
                INSERT INTO security.external_identities (user_id, issuer, subject)
                VALUES (:u, 'https://idp.example', 'dupe-subject')
            """),
            {"u": f.player_user_id},
        )


def test_external_identities_allows_relink_after_revocation(
    db_connection: Connection, f: Fixture
) -> None:
    """A revoked (issuer, subject) can be re-established — the active
    uniqueness index is partial (WHERE revoked_at IS NULL)."""
    db_connection.execute(
        text("""
            INSERT INTO security.external_identities (user_id, issuer, subject, revoked_at)
            VALUES (:u, 'https://idp.example', 'relink-subject', now())
        """),
        {"u": f.gm_user_id},
    )
    db_connection.execute(
        text("""
            INSERT INTO security.external_identities (user_id, issuer, subject)
            VALUES (:u, 'https://idp.example', 'relink-subject')
        """),
        {"u": f.gm_user_id},
    )


# ---------------------------------------------------------------------------
# security.service_accounts
# ---------------------------------------------------------------------------


def test_service_accounts_rejects_duplicate_code(db_connection: Connection) -> None:
    make_service_account(db_connection, code="svc_dupe")
    with pytest.raises(CONSTRAINT_ERRORS):
        make_service_account(db_connection, code="svc_dupe")


def test_service_accounts_rejects_malformed_code(db_connection: Connection) -> None:
    with pytest.raises(CONSTRAINT_ERRORS):
        make_service_account(db_connection, code="Not-Valid")


# ---------------------------------------------------------------------------
# security.campaign_memberships
# ---------------------------------------------------------------------------


def test_campaign_memberships_rejects_second_open_membership(
    db_connection: Connection, f: Fixture
) -> None:
    with pytest.raises(CONSTRAINT_ERRORS):
        make_campaign_membership(db_connection, f.campaign_id, f.gm_user_id)


def test_campaign_memberships_allows_second_closed_membership(
    db_connection: Connection, f: Fixture
) -> None:
    # now() is transaction-start time in PostgreSQL, so a plain `now()` here
    # would equal joined_at's `now()` from the fixture's own insert within
    # this same transaction and fail ck_campaign_memberships_ended_after_joined
    # (strictly >, not >=) — advance explicitly instead.
    db_connection.execute(
        text(
            "UPDATE security.campaign_memberships SET ended_at = now() + interval '1 second' "
            "WHERE campaign_membership_id = :m"
        ),
        {"m": f.gm_membership_id},
    )
    make_campaign_membership(db_connection, f.campaign_id, f.gm_user_id)


def test_campaign_memberships_rejects_ended_before_joined(
    db_connection: Connection, f: Fixture
) -> None:
    with pytest.raises(CONSTRAINT_ERRORS):
        db_connection.execute(
            text("""
                INSERT INTO security.campaign_memberships
                    (campaign_id, user_id, membership_status_id, joined_at, ended_at)
                VALUES (
                    :c, :u,
                    (SELECT membership_status_id FROM security.membership_statuses
                     WHERE code = 'active'),
                    now(), now() - interval '1 day'
                )
            """),
            {"c": f.campaign_id, "u": make_user(db_connection, "Backdated")},
        )


# ---------------------------------------------------------------------------
# security.campaign_invitations
# ---------------------------------------------------------------------------


def test_campaign_invitations_rejects_duplicate_token_hash(
    db_connection: Connection, f: Fixture
) -> None:
    make_campaign_invitation(
        db_connection, f.campaign_id, f.gm_membership_id, token_hash="token-hash-duplicate-test"
    )
    with pytest.raises(CONSTRAINT_ERRORS):
        make_campaign_invitation(
            db_connection,
            f.campaign_id,
            f.gm_membership_id,
            token_hash="token-hash-duplicate-test",
        )


def test_campaign_invitations_rejects_accepted_at_without_accepted_by(
    db_connection: Connection, f: Fixture
) -> None:
    with pytest.raises(CONSTRAINT_ERRORS):
        db_connection.execute(
            text("""
                INSERT INTO security.campaign_invitations
                    (campaign_id, invitation_token_hash, invited_by_membership_id, expires_at,
                     accepted_at)
                VALUES (:c, 'tok-half-accepted-000000', :m, now() + interval '7 days', now())
            """),
            {"c": f.campaign_id, "m": f.gm_membership_id},
        )


# ---------------------------------------------------------------------------
# security.roles
# ---------------------------------------------------------------------------


def test_roles_allows_system_template_and_campaign_scoped(
    db_connection: Connection, f: Fixture
) -> None:
    make_role(db_connection, campaign_id=None, code="template_role")
    make_role(db_connection, campaign_id=f.campaign_id, code="template_role")


def test_roles_rejects_duplicate_system_template_code(db_connection: Connection) -> None:
    make_role(db_connection, campaign_id=None, code="dupe_template")
    with pytest.raises(CONSTRAINT_ERRORS):
        make_role(db_connection, campaign_id=None, code="dupe_template")


def test_roles_rejects_duplicate_code_within_same_campaign(
    db_connection: Connection, f: Fixture
) -> None:
    make_role(db_connection, campaign_id=f.campaign_id, code="dupe_in_campaign")
    with pytest.raises(CONSTRAINT_ERRORS):
        make_role(db_connection, campaign_id=f.campaign_id, code="dupe_in_campaign")


def test_roles_allows_same_code_in_two_different_campaigns(
    db_connection: Connection, f: Fixture
) -> None:
    other_campaign_id = make_campaign(db_connection, f.timeline_id, "Other Campaign")
    make_role(db_connection, campaign_id=f.campaign_id, code="shared_code")
    make_role(db_connection, campaign_id=other_campaign_id, code="shared_code")


def test_roles_seeded_system_templates_present(db_connection: Connection) -> None:
    for code in (
        "campaign_owner",
        "gm",
        "assistant_gm",
        "player",
        "observer",
        "import_reviewer",
        "rules_curator",
    ):
        lookup_id(db_connection, "security", "roles", "role_id", code)


# ---------------------------------------------------------------------------
# security.role_capabilities
# ---------------------------------------------------------------------------


def test_role_capabilities_restricts_deleting_capability_in_use(
    db_connection: Connection, f: Fixture
) -> None:
    make_role_capability(db_connection, f.role_id, f.capability_id)
    with pytest.raises(CONSTRAINT_ERRORS):
        db_connection.execute(
            text("DELETE FROM security.capabilities WHERE capability_id = :c"),
            {"c": f.capability_id},
        )


# ---------------------------------------------------------------------------
# security.membership_roles
# ---------------------------------------------------------------------------


def test_membership_roles_creates_for_matching_campaign(
    db_connection: Connection, f: Fixture
) -> None:
    make_membership_role(db_connection, f.gm_membership_id, f.role_id)


def test_membership_roles_rejects_role_from_different_campaign(
    db_connection: Connection, f: Fixture
) -> None:
    other_campaign_id = make_campaign(db_connection, f.timeline_id, "Other Campaign")
    other_role_id = make_role(db_connection, campaign_id=other_campaign_id)
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_membership_role(db_connection, f.gm_membership_id, other_role_id)
    assert "belongs to campaign" in str(exc.value)


def test_membership_roles_allows_system_template_role(
    db_connection: Connection, f: Fixture
) -> None:
    template_role_id = make_role(db_connection, campaign_id=None, code="usable_anywhere")
    make_membership_role(db_connection, f.gm_membership_id, template_role_id)


def test_membership_roles_rejects_duplicate_active_assignment(
    db_connection: Connection, f: Fixture
) -> None:
    make_membership_role(db_connection, f.gm_membership_id, f.role_id)
    with pytest.raises(CONSTRAINT_ERRORS):
        make_membership_role(db_connection, f.gm_membership_id, f.role_id)


def test_membership_roles_allows_regrant_after_revocation(
    db_connection: Connection, f: Fixture
) -> None:
    make_membership_role(db_connection, f.gm_membership_id, f.role_id, revoked=True)
    make_membership_role(db_connection, f.gm_membership_id, f.role_id)


# ---------------------------------------------------------------------------
# security.membership_character_relationships
# ---------------------------------------------------------------------------


def test_membership_character_relationships_creates_same_world(
    db_connection: Connection, f: Fixture
) -> None:
    make_membership_character_relationship(
        db_connection, f.player_membership_id, f.character_id, f.relationship_type_id
    )


def test_membership_character_relationships_rejects_character_from_different_world(
    db_connection: Connection, f: Fixture
) -> None:
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_membership_character_relationship(
            db_connection,
            f.player_membership_id,
            f.other_world_character_id,
            f.relationship_type_id,
        )
    assert "belongs to world" in str(exc.value)


def test_membership_character_relationships_rejects_timeline_from_different_world(
    db_connection: Connection, f: Fixture
) -> None:
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_membership_character_relationship(
            db_connection,
            f.player_membership_id,
            f.character_id,
            f.relationship_type_id,
            timeline_id=f.other_world_timeline_id,
        )
    assert "belongs to world" in str(exc.value)


def test_membership_character_relationships_rejects_duplicate_active_same_type(
    db_connection: Connection, f: Fixture
) -> None:
    make_membership_character_relationship(
        db_connection, f.player_membership_id, f.character_id, f.relationship_type_id
    )
    with pytest.raises(CONSTRAINT_ERRORS):
        make_membership_character_relationship(
            db_connection, f.player_membership_id, f.character_id, f.relationship_type_id
        )


def test_membership_character_relationships_allows_duplicate_after_revocation(
    db_connection: Connection, f: Fixture
) -> None:
    make_membership_character_relationship(
        db_connection,
        f.player_membership_id,
        f.character_id,
        f.relationship_type_id,
        revoked=True,
    )
    make_membership_character_relationship(
        db_connection, f.player_membership_id, f.character_id, f.relationship_type_id
    )


def test_membership_character_relationships_derives_effective_period(
    db_connection: Connection, f: Fixture
) -> None:
    relationship_id = make_membership_character_relationship(
        db_connection,
        f.player_membership_id,
        f.character_id,
        f.relationship_type_id,
        effective_from_world_time_id=f.t0,
        effective_to_world_time_id=f.t1,
    )
    period = db_connection.execute(
        text(
            "SELECT effective_period::text FROM security.membership_character_relationships "
            "WHERE membership_character_relationship_id = :r"
        ),
        {"r": relationship_id},
    ).scalar()
    assert period == "[100,200)"


def test_membership_character_relationships_effective_period_null_without_endpoints(
    db_connection: Connection, f: Fixture
) -> None:
    relationship_id = make_membership_character_relationship(
        db_connection, f.player_membership_id, f.character_id, f.relationship_type_id
    )
    period = db_connection.execute(
        text(
            "SELECT effective_period FROM security.membership_character_relationships "
            "WHERE membership_character_relationship_id = :r"
        ),
        {"r": relationship_id},
    ).scalar()
    assert period is None


def test_membership_character_relationships_rejects_end_before_start(
    db_connection: Connection, f: Fixture
) -> None:
    with pytest.raises(CONSTRAINT_ERRORS):
        make_membership_character_relationship(
            db_connection,
            f.player_membership_id,
            f.character_id,
            f.relationship_type_id,
            effective_from_world_time_id=f.t1,
            effective_to_world_time_id=f.t0,
        )


# ---------------------------------------------------------------------------
# security.character_relationship_type_capabilities
# ---------------------------------------------------------------------------


def test_relationship_type_capabilities_restricts_deleting_capability_in_use(
    db_connection: Connection, f: Fixture
) -> None:
    make_relationship_type_capability(db_connection, f.relationship_type_id, f.capability_id)
    with pytest.raises(CONSTRAINT_ERRORS):
        db_connection.execute(
            text("DELETE FROM security.capabilities WHERE capability_id = :c"),
            {"c": f.capability_id},
        )


# ---------------------------------------------------------------------------
# security.access_groups / security.access_group_memberships
# ---------------------------------------------------------------------------


def test_access_groups_rejects_duplicate_name_in_same_campaign(
    db_connection: Connection, f: Fixture
) -> None:
    # f.access_group_id was already created with the default name "Test Group".
    with pytest.raises(CONSTRAINT_ERRORS):
        make_access_group(db_connection, f.campaign_id, name="Test Group")


def test_access_group_memberships_creates_for_matching_campaign(
    db_connection: Connection, f: Fixture
) -> None:
    make_access_group_membership(db_connection, f.access_group_id, f.player_membership_id)


def test_access_group_memberships_rejects_membership_from_different_campaign(
    db_connection: Connection, f: Fixture
) -> None:
    other_campaign_id = make_campaign(db_connection, f.timeline_id, "Other Campaign")
    other_user_id = make_user(db_connection, "Other Campaign User")
    other_membership_id = make_campaign_membership(db_connection, other_campaign_id, other_user_id)
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_access_group_membership(db_connection, f.access_group_id, other_membership_id)
    assert "belongs to campaign" in str(exc.value)


def test_access_group_memberships_rejects_duplicate_open_row(
    db_connection: Connection, f: Fixture
) -> None:
    make_access_group_membership(db_connection, f.access_group_id, f.player_membership_id)
    with pytest.raises(CONSTRAINT_ERRORS):
        make_access_group_membership(db_connection, f.access_group_id, f.player_membership_id)


def test_access_group_memberships_allows_rejoin_after_removal(
    db_connection: Connection, f: Fixture
) -> None:
    make_access_group_membership(
        db_connection, f.access_group_id, f.player_membership_id, removed=True
    )
    make_access_group_membership(db_connection, f.access_group_id, f.player_membership_id)


# ---------------------------------------------------------------------------
# security.resource_grants
# ---------------------------------------------------------------------------


def test_resource_grants_creates_for_each_target_kind(
    db_connection: Connection, f: Fixture
) -> None:
    targets = {
        "character_id": f.character_id,
        "entity_id": f.knowledge_item_id,  # any core.entities row works for the generic target
        "knowledge_item_id": f.knowledge_item_id,
        "quest_id": f.quest_id,
        "session_id": f.session_id,
        "event_id": f.event_id,
    }
    for kwarg, target_id in targets.items():
        make_resource_grant(
            db_connection,
            f.campaign_id,
            f.capability_id,
            grantee_campaign_membership_id=f.player_membership_id,
            **{kwarg: target_id},
        )


def test_resource_grants_creates_for_access_group_grantee(
    db_connection: Connection, f: Fixture
) -> None:
    make_resource_grant(
        db_connection,
        f.campaign_id,
        f.capability_id,
        grantee_access_group_id=f.access_group_id,
        character_id=f.character_id,
    )


def test_resource_grants_rejects_zero_grantees(db_connection: Connection, f: Fixture) -> None:
    with pytest.raises(CONSTRAINT_ERRORS):
        make_resource_grant(
            db_connection, f.campaign_id, f.capability_id, character_id=f.character_id
        )


def test_resource_grants_rejects_two_grantees(db_connection: Connection, f: Fixture) -> None:
    with pytest.raises(CONSTRAINT_ERRORS):
        make_resource_grant(
            db_connection,
            f.campaign_id,
            f.capability_id,
            grantee_campaign_membership_id=f.player_membership_id,
            grantee_access_group_id=f.access_group_id,
            character_id=f.character_id,
        )


def test_resource_grants_rejects_zero_targets(db_connection: Connection, f: Fixture) -> None:
    with pytest.raises(CONSTRAINT_ERRORS):
        make_resource_grant(
            db_connection,
            f.campaign_id,
            f.capability_id,
            grantee_campaign_membership_id=f.player_membership_id,
        )


def test_resource_grants_rejects_two_targets(db_connection: Connection, f: Fixture) -> None:
    with pytest.raises(CONSTRAINT_ERRORS):
        make_resource_grant(
            db_connection,
            f.campaign_id,
            f.capability_id,
            grantee_campaign_membership_id=f.player_membership_id,
            character_id=f.character_id,
            quest_id=f.quest_id,
        )


def test_resource_grants_rejects_invalid_effect(db_connection: Connection, f: Fixture) -> None:
    with pytest.raises(CONSTRAINT_ERRORS):
        make_resource_grant(
            db_connection,
            f.campaign_id,
            f.capability_id,
            grantee_campaign_membership_id=f.player_membership_id,
            character_id=f.character_id,
            effect="maybe",
        )


def test_resource_grants_rejects_grantee_membership_from_different_campaign(
    db_connection: Connection, f: Fixture
) -> None:
    other_campaign_id = make_campaign(db_connection, f.timeline_id, "Other Campaign")
    other_user_id = make_user(db_connection, "Other Campaign User")
    other_membership_id = make_campaign_membership(db_connection, other_campaign_id, other_user_id)
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_resource_grant(
            db_connection,
            f.campaign_id,
            f.capability_id,
            grantee_campaign_membership_id=other_membership_id,
            character_id=f.character_id,
        )
    assert "belongs to campaign" in str(exc.value)


def test_resource_grants_rejects_target_from_different_world(
    db_connection: Connection, f: Fixture
) -> None:
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_resource_grant(
            db_connection,
            f.campaign_id,
            f.capability_id,
            grantee_campaign_membership_id=f.player_membership_id,
            character_id=f.other_world_character_id,
        )
    assert "belongs to world" in str(exc.value)


def test_resource_grants_rejects_session_from_different_campaign(
    db_connection: Connection, f: Fixture
) -> None:
    other_campaign_id = make_campaign(db_connection, f.timeline_id, "Other Campaign")
    other_session_id = make_session(db_connection, other_campaign_id, 1)
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_resource_grant(
            db_connection,
            f.campaign_id,
            f.capability_id,
            grantee_campaign_membership_id=f.player_membership_id,
            session_id=other_session_id,
        )
    assert "belongs to campaign" in str(exc.value)


def test_resource_grants_rejects_timeline_from_different_world(
    db_connection: Connection, f: Fixture
) -> None:
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_resource_grant(
            db_connection,
            f.campaign_id,
            f.capability_id,
            grantee_campaign_membership_id=f.player_membership_id,
            character_id=f.character_id,
            timeline_id=f.other_world_timeline_id,
        )
    assert "belongs to world" in str(exc.value)


def test_resource_grants_rejects_duplicate_active_grant(
    db_connection: Connection, f: Fixture
) -> None:
    make_resource_grant(
        db_connection,
        f.campaign_id,
        f.capability_id,
        grantee_campaign_membership_id=f.player_membership_id,
        character_id=f.character_id,
    )
    with pytest.raises(CONSTRAINT_ERRORS):
        make_resource_grant(
            db_connection,
            f.campaign_id,
            f.capability_id,
            grantee_campaign_membership_id=f.player_membership_id,
            character_id=f.character_id,
        )


def test_resource_grants_allows_duplicate_after_revocation(
    db_connection: Connection, f: Fixture
) -> None:
    make_resource_grant(
        db_connection,
        f.campaign_id,
        f.capability_id,
        grantee_campaign_membership_id=f.player_membership_id,
        character_id=f.character_id,
        revoked=True,
    )
    make_resource_grant(
        db_connection,
        f.campaign_id,
        f.capability_id,
        grantee_campaign_membership_id=f.player_membership_id,
        character_id=f.character_id,
    )


def test_resource_grants_allows_allow_and_deny_to_coexist(
    db_connection: Connection, f: Fixture
) -> None:
    make_resource_grant(
        db_connection,
        f.campaign_id,
        f.capability_id,
        grantee_campaign_membership_id=f.player_membership_id,
        character_id=f.character_id,
        effect="allow",
    )
    make_resource_grant(
        db_connection,
        f.campaign_id,
        f.capability_id,
        grantee_campaign_membership_id=f.player_membership_id,
        character_id=f.character_id,
        effect="deny",
    )


# ---------------------------------------------------------------------------
# Lookups: security.membership_statuses, .character_relationship_types,
# .capabilities
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "table",
    ["security.membership_statuses", "security.character_relationship_types"],
)
def test_plain_lookup_rejects_malformed_code(db_connection: Connection, table: str) -> None:
    with pytest.raises(CONSTRAINT_ERRORS):
        db_connection.execute(
            text(f"INSERT INTO {table} (code, display_name) VALUES ('Not Valid', 'X')")
        )


def test_capabilities_accepts_namespaced_code(db_connection: Connection) -> None:
    make_capability(db_connection, code="namespace.sub_code")


@pytest.mark.parametrize("bad_code", ["Uppercase.thing", ".leading_dot", "trailing_dot.", "a..b"])
def test_capabilities_rejects_malformed_namespaced_code(
    db_connection: Connection, bad_code: str
) -> None:
    with pytest.raises(CONSTRAINT_ERRORS):
        make_capability(db_connection, code=bad_code)


def test_membership_statuses_seeded_codes_present(db_connection: Connection) -> None:
    for code in ("invited", "active", "suspended", "revoked", "departed"):
        lookup_id(db_connection, "security", "membership_statuses", "membership_status_id", code)


def test_character_relationship_types_seeded_codes_present(db_connection: Connection) -> None:
    for code in (
        "owner",
        "primary_controller",
        "co_controller",
        "viewer",
        "portrayer",
        "former_controller",
        "observer_approved_viewer",
    ):
        lookup_id(
            db_connection,
            "security",
            "character_relationship_types",
            "character_relationship_type_id",
            code,
        )


def test_capabilities_seeded_codes_present(db_connection: Connection) -> None:
    for code in ("campaign.view", "canon.edit", "character.control", "access.manage"):
        lookup_id(db_connection, "security", "capabilities", "capability_id", code)


# ---------------------------------------------------------------------------
# updated_at trigger coverage for the timestamped tables this revision adds
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "table",
    [
        "security.membership_statuses",
        "security.character_relationship_types",
        "security.capabilities",
        "security.service_accounts",
        "security.campaign_memberships",
        "security.roles",
        "security.access_groups",
    ],
)
def test_updated_at_trigger_fires(db_connection: Connection, table: str, f: Fixture) -> None:
    if table in (
        "security.membership_statuses",
        "security.character_relationship_types",
        "security.capabilities",
    ):
        pk_column = {
            "security.membership_statuses": "membership_status_id",
            "security.character_relationship_types": "character_relationship_type_id",
            "security.capabilities": "capability_id",
        }[table]
        row_id = db_connection.execute(
            text(
                f"INSERT INTO {table} (code, display_name) VALUES ('trig_code', 'T') "
                f"RETURNING {pk_column}"
            )
        ).scalar()
        where = f"{pk_column} = '{row_id}'"
    elif table == "security.service_accounts":
        row_id = make_service_account(db_connection, code="trig_service")
        where = f"service_account_id = '{row_id}'"
    elif table == "security.campaign_memberships":
        where = f"campaign_membership_id = '{f.gm_membership_id}'"
    elif table == "security.roles":
        row_id = make_role(db_connection, code="trig_role")
        where = f"role_id = '{row_id}'"
    else:
        row_id = make_access_group(db_connection, f.campaign_id, name="Trigger Group")
        where = f"access_group_id = '{row_id}'"

    db_connection.execute(
        text(f"UPDATE {table} SET updated_at = TIMESTAMPTZ '2000-01-01' WHERE {where}")
    )
    after = db_connection.execute(text(f"SELECT updated_at FROM {table} WHERE {where}")).scalar()
    txn_now = db_connection.execute(text("SELECT now()")).scalar()
    assert after == txn_now, f"core.set_updated_at() did not fire on {table}"
