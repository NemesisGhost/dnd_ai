"""Correction pass on revision 080 (security, identity, and access):

1. The campaign owner/access-manager retention invariant (DATABASE_MODEL.md
   §22 rule 19) — security.campaign_has_access_manager(),
   security.assert_campaign_retains_access_manager(), and the five
   DEFERRABLE INITIALLY DEFERRED constraint triggers that enforce it.
   campaign.campaigns is checked on INSERT as well as UPDATE, so a campaign
   row created active directly (not only one later transitioned into
   'active') is covered — section "1. Owner/access-manager retention
   invariant" below.
1b. The invariant only counts a *non-expiring* (expires_at IS NULL)
    qualifying grant — a trigger cannot fire on the later passage of a
    stored timestamp, so an expiring grant can never be trusted as the
    sole support for an invariant that must hold between writes. Temporary
    co-owners remain fully supported alongside a permanent one — section
    "1b. The wall-clock expiration hole" below.
2. Reverse-mutation guards — security.campaign_memberships.campaign_id,
   security.access_groups.campaign_id, campaign.sessions.campaign_id, and
   narrative.events.campaign_id/timeline_id are immutable once set
   (core.enforce_immutable_columns(), the same pattern revisions 030/033/075
   established). security.roles.campaign_id uses a separate, NULL-inclusive
   dedicated guard instead (security.enforce_roles_campaign_immutable()) —
   NULL (system template) is a permanent value for that column, not a
   not-yet-set placeholder, so the generic function's NULL -> value
   allowance does not apply to it. Together these close the "parent row
   reparented out from under an already-valid child" gap for security.
   membership_roles, .membership_character_relationships,
   .access_group_memberships, and .resource_grants.
3. Same-campaign actor-scope guards on every *_by_membership_id column:
   campaign_memberships.ended_by_membership_id, campaign_invitations.
   invited_by_membership_id, membership_roles.granted_by_membership_id,
   membership_character_relationships.granted_by_membership_id,
   access_group_memberships.added_by_membership_id, resource_grants.
   granted_by_membership_id.

Deferred constraint triggers only fire at COMMIT (or an explicit
`SET CONSTRAINTS ALL IMMEDIATE`) — the shared db_connection fixture wraps
every test in a transaction that always rolls back and never commits, so
every retention-invariant test below calls `SET CONSTRAINTS ALL IMMEDIATE`
after the mutating statement to force evaluation without needing to
actually commit. See tests/database/test_security_identity_and_access.py
for baseline CRUD/constraint coverage of every table this file assumes
already exists and works.
"""

import uuid

import pytest
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import IntegrityError, InternalError, ProgrammingError

from tests.factories import (
    lookup_id,
    make_access_group,
    make_access_group_membership,
    make_campaign,
    make_campaign_invitation,
    make_campaign_membership,
    make_character,
    make_character_relationship_type,
    make_event,
    make_knowledge_item,
    make_membership_character_relationship,
    make_membership_role,
    make_resource_grant,
    make_role,
    make_role_capability,
    make_session,
    make_timeline,
    make_user,
    make_world,
    make_world_time,
    status_id,
)

pytestmark = pytest.mark.database

CONSTRAINT_ERRORS = (IntegrityError, InternalError, ProgrammingError)


def _immediate(connection: Connection) -> None:
    """Force any deferred constraint triggers queued so far to evaluate now,
    inside the still-open (and, under db_connection, still rollback-able)
    transaction — without this, revision 080's retention triggers never
    fire under the standard rolled-back-transaction test fixture."""
    connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


def _campaign_owner_role_id(connection: Connection) -> uuid.UUID:
    return lookup_id(connection, "security", "roles", "role_id", "campaign_owner")


def _make_owner(
    connection: Connection, campaign_id: uuid.UUID, name: str
) -> tuple[uuid.UUID, uuid.UUID]:
    """A campaign membership holding the seeded campaign_owner role (which
    revision 080 seeds with the access.manage capability). Returns
    (campaign_membership_id, membership_role_id)."""
    user_id = make_user(connection, name)
    membership_id = make_campaign_membership(connection, campaign_id, user_id)
    role_assignment_id = make_membership_role(
        connection, membership_id, _campaign_owner_role_id(connection)
    )
    return membership_id, role_assignment_id


def _set_campaign_lifecycle(connection: Connection, campaign_id: uuid.UUID, code: str) -> None:
    connection.execute(
        text("UPDATE campaign.campaigns SET lifecycle_status_id = :s WHERE campaign_id = :c"),
        {"s": status_id(connection, "lifecycle_statuses", code), "c": campaign_id},
    )


class Fixture:
    def __init__(self, connection: Connection, slug: str) -> None:
        self.world_id = make_world(connection, slug=slug)
        self.timeline_id = make_timeline(connection, self.world_id, is_primary=True)
        self.campaign_id = make_campaign(connection, self.timeline_id)


@pytest.fixture
def f(db_connection: Connection) -> Fixture:
    return Fixture(db_connection, "access-control-invariants-world")


# ---------------------------------------------------------------------------
# 1. Owner/access-manager retention invariant
# ---------------------------------------------------------------------------


def test_normal_ownership_transfer_succeeds(db_connection: Connection, f: Fixture) -> None:
    """Revoking the old owner's role and granting the new owner the role, in
    one transaction, must not be rejected on the momentarily-owner-less
    intermediate state — the whole point of DEFERRABLE INITIALLY DEFERRED."""
    _old_membership, old_role_assignment = _make_owner(db_connection, f.campaign_id, "Old Owner")
    new_membership, _new_role_assignment = _make_owner(db_connection, f.campaign_id, "New Owner")

    # Revoke the second owner too, leaving only the "old" owner, so the
    # subsequent revoke of "old" would (if checked immediately) leave zero.
    db_connection.execute(
        text(
            "UPDATE security.membership_roles SET revoked_at = now() WHERE campaign_membership_id = :m"
        ),
        {"m": new_membership},
    )
    make_membership_role(db_connection, new_membership, _campaign_owner_role_id(db_connection))
    db_connection.execute(
        text(
            "UPDATE security.membership_roles SET revoked_at = now() WHERE membership_role_id = :r"
        ),
        {"r": old_role_assignment},
    )
    # Final state: new_membership has an active campaign_owner grant, old does not.
    _immediate(db_connection)


def test_revoking_the_only_owning_role_is_rejected(db_connection: Connection, f: Fixture) -> None:
    _membership, role_assignment = _make_owner(db_connection, f.campaign_id, "Sole Owner")

    db_connection.execute(
        text(
            "UPDATE security.membership_roles SET revoked_at = now() WHERE membership_role_id = :r"
        ),
        {"r": role_assignment},
    )
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        _immediate(db_connection)
    assert "would be left with no membership" in str(exc.value)


def test_closing_the_only_owning_membership_is_rejected(
    db_connection: Connection, f: Fixture
) -> None:
    membership_id, _role_assignment = _make_owner(db_connection, f.campaign_id, "Sole Owner")

    # now() is transaction-start time, equal to joined_at set moments ago in
    # this same transaction — advance explicitly past it, the same fix
    # test_security_identity_and_access.py's campaign_memberships tests use.
    db_connection.execute(
        text(
            "UPDATE security.campaign_memberships SET ended_at = now() + interval '1 second' "
            "WHERE campaign_membership_id = :m"
        ),
        {"m": membership_id},
    )
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        _immediate(db_connection)
    assert "would be left with no membership" in str(exc.value)


def test_suspending_the_only_owning_membership_is_rejected(
    db_connection: Connection, f: Fixture
) -> None:
    """Suspended is an open (ended_at IS NULL) but non-authorizing status
    (DATABASE_MODEL.md §19.2) — it must not count as a retained owner."""
    membership_id, _role_assignment = _make_owner(db_connection, f.campaign_id, "Sole Owner")

    db_connection.execute(
        text(
            "UPDATE security.campaign_memberships SET membership_status_id = :s "
            "WHERE campaign_membership_id = :m"
        ),
        {
            "s": lookup_id(
                db_connection,
                "security",
                "membership_statuses",
                "membership_status_id",
                "suspended",
            ),
            "m": membership_id,
        },
    )
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        _immediate(db_connection)
    assert "would be left with no membership" in str(exc.value)


# An expiring sole grant is rejected regardless of whether the expiry is
# already past or still ahead — see test_giving_the_sole_access_manager_a_
# finite_expiry_is_rejected in the "wall-clock expiration hole" section
# below, which is the direct test of that (expires_at IS NOT NULL disqualifies
# outright; campaign_has_access_manager() never compares it against now()).


def test_reassigning_the_only_owning_role_away_is_rejected(
    db_connection: Connection, f: Fixture
) -> None:
    membership_id, role_assignment = _make_owner(db_connection, f.campaign_id, "Sole Owner")
    player_role_id = make_role(
        db_connection, campaign_id=f.campaign_id, code="reassign_target_role"
    )

    db_connection.execute(
        text("UPDATE security.membership_roles SET role_id = :r WHERE membership_role_id = :a"),
        {"r": player_role_id, "a": role_assignment},
    )
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        _immediate(db_connection)
    assert "would be left with no membership" in str(exc.value)


def test_deleting_the_only_owning_role_assignment_is_rejected(
    db_connection: Connection, f: Fixture
) -> None:
    _membership, role_assignment = _make_owner(db_connection, f.campaign_id, "Sole Owner")

    db_connection.execute(
        text("DELETE FROM security.membership_roles WHERE membership_role_id = :r"),
        {"r": role_assignment},
    )
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        _immediate(db_connection)
    assert "would be left with no membership" in str(exc.value)


def test_removing_access_manage_from_the_only_supporting_role_is_rejected(
    db_connection: Connection, f: Fixture
) -> None:
    """A campaign-scoped role (not the shared campaign_owner system template,
    so this test cannot affect any other campaign) with access.manage,
    granted to the sole membership; deleting the role_capabilities row that
    grants it must be rejected."""
    role_id = make_role(db_connection, campaign_id=f.campaign_id, code="custom_owner_role")
    access_manage_id = lookup_id(
        db_connection, "security", "capabilities", "capability_id", "access.manage"
    )
    make_role_capability(db_connection, role_id, access_manage_id)

    user_id = make_user(db_connection, "Custom Owner")
    membership_id = make_campaign_membership(db_connection, f.campaign_id, user_id)
    make_membership_role(db_connection, membership_id, role_id)

    db_connection.execute(
        text("DELETE FROM security.role_capabilities WHERE role_id = :r AND capability_id = :c"),
        {"r": role_id, "c": access_manage_id},
    )
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        _immediate(db_connection)
    assert "would be left with no membership" in str(exc.value)


def test_deactivating_the_only_supporting_role_is_rejected(
    db_connection: Connection, f: Fixture
) -> None:
    role_id = make_role(db_connection, campaign_id=f.campaign_id, code="deactivate_target_role")
    access_manage_id = lookup_id(
        db_connection, "security", "capabilities", "capability_id", "access.manage"
    )
    make_role_capability(db_connection, role_id, access_manage_id)

    user_id = make_user(db_connection, "Deactivated Role Owner")
    membership_id = make_campaign_membership(db_connection, f.campaign_id, user_id)
    make_membership_role(db_connection, membership_id, role_id)

    db_connection.execute(
        text("UPDATE security.roles SET is_active = false WHERE role_id = :r"), {"r": role_id}
    )
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        _immediate(db_connection)
    assert "would be left with no membership" in str(exc.value)


def test_activating_a_campaign_with_no_owner_is_rejected(
    db_connection: Connection, f: Fixture
) -> None:
    _set_campaign_lifecycle(db_connection, f.campaign_id, "pending")

    db_connection.execute(
        text(
            "UPDATE campaign.campaigns SET lifecycle_status_id = "
            "(SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'active') "
            "WHERE campaign_id = :c"
        ),
        {"c": f.campaign_id},
    )
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        _immediate(db_connection)
    assert "would be left with no membership" in str(exc.value)


def test_activating_a_campaign_with_an_owner_already_present_succeeds(
    db_connection: Connection, f: Fixture
) -> None:
    _set_campaign_lifecycle(db_connection, f.campaign_id, "pending")
    _make_owner(db_connection, f.campaign_id, "Pre-Activation Owner")

    db_connection.execute(
        text(
            "UPDATE campaign.campaigns SET lifecycle_status_id = "
            "(SELECT lifecycle_status_id FROM core.lifecycle_statuses WHERE code = 'active') "
            "WHERE campaign_id = :c"
        ),
        {"c": f.campaign_id},
    )
    _immediate(db_connection)


def test_direct_active_campaign_insert_without_owner_is_rejected(
    db_connection: Connection, f: Fixture
) -> None:
    """The invariant must not be checkable only via a later UPDATE into
    'active' — a campaign row INSERTed already active with zero qualifying
    memberships is exactly as ownerless. f.campaign_id was INSERTed active
    by the Fixture itself and nothing has given it an owner yet."""
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        _immediate(db_connection)
    assert "would be left with no membership" in str(exc.value)


def test_direct_active_campaign_insert_with_owner_in_same_transaction_succeeds(
    db_connection: Connection, f: Fixture
) -> None:
    """The supported creation flow this closes the gap for: INSERT the
    campaign already active, then INSERT its owning membership/role in the
    same transaction — both checked together, once, at commit (or here, at
    the explicit SET CONSTRAINTS ALL IMMEDIATE)."""
    _make_owner(db_connection, f.campaign_id, "Same-Transaction Owner")
    _immediate(db_connection)


def test_removing_the_only_owner_of_a_non_active_campaign_is_not_rejected(
    db_connection: Connection, f: Fixture
) -> None:
    """The invariant only binds active campaigns."""
    _set_campaign_lifecycle(db_connection, f.campaign_id, "pending")
    _membership, role_assignment = _make_owner(db_connection, f.campaign_id, "Draft Campaign Owner")

    db_connection.execute(
        text(
            "UPDATE security.membership_roles SET revoked_at = now() WHERE membership_role_id = :r"
        ),
        {"r": role_assignment},
    )
    _immediate(db_connection)


def test_second_owner_can_be_removed_leaving_one(db_connection: Connection, f: Fixture) -> None:
    """Sanity check that the invariant is "at least one", not "exactly one
    forever" — removing a second, non-sole owner is fine."""
    _make_owner(db_connection, f.campaign_id, "Owner A")
    _membership_b, role_assignment_b = _make_owner(db_connection, f.campaign_id, "Owner B")

    db_connection.execute(
        text(
            "UPDATE security.membership_roles SET revoked_at = now() WHERE membership_role_id = :r"
        ),
        {"r": role_assignment_b},
    )
    _immediate(db_connection)


def test_concurrent_removal_of_both_owners_cannot_both_commit(postgres_engine: Engine) -> None:
    """Two simultaneous transactions each revoking a *different* owning
    membership's role. The row lock security.
    assert_campaign_retains_access_manager() takes on campaign.campaigns
    serializes them: the second to reach the check blocks on the first
    (observable via lock_timeout, the same idiom test_party_memberships.py
    uses), and once unblocked it re-evaluates live, post-commit state and
    correctly rejects the resulting zero-owner outcome.

    Takes the session engine rather than the db_connection fixture — needs
    real concurrent transactions and committed setup data, and db_connection
    wraps everything in one transaction it always rolls back (and deferred
    constraint triggers never fire on rollback at all).
    """
    engine = postgres_engine
    slug = f"access-control-concurrency-{uuid.uuid4().hex[:8]}"
    try:
        with engine.begin() as setup:
            world_id = make_world(setup, slug=slug)
            timeline_id = make_timeline(setup, world_id, is_primary=True)
            campaign_id = make_campaign(setup, timeline_id)
            _membership_a, role_assignment_a = _make_owner(setup, campaign_id, f"{slug}-owner-a")
            _membership_b, role_assignment_b = _make_owner(setup, campaign_id, f"{slug}-owner-b")

        with engine.connect() as first, engine.connect() as second:
            first.begin()
            second.begin()

            first.execute(
                text(
                    "UPDATE security.membership_roles SET revoked_at = now() WHERE membership_role_id = :r"
                ),
                {"r": role_assignment_a},
            )
            first.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))  # owner B still active — passes

            second.execute(text("SET LOCAL lock_timeout = '2s'"))
            second.execute(
                text(
                    "UPDATE security.membership_roles SET revoked_at = now() WHERE membership_role_id = :r"
                ),
                {"r": role_assignment_b},
            )
            with pytest.raises(Exception) as exc:
                second.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))

            message = str(exc.value)
            assert (
                "lock_timeout" in message
                or "canceling statement" in message
                or "could not obtain lock" in message
            ), f"expected a lock-contention error, got: {message}"

            second.rollback()
            first.commit()

            with engine.begin() as third:
                third.execute(
                    text(
                        "UPDATE security.membership_roles SET revoked_at = now() "
                        "WHERE membership_role_id = :r"
                    ),
                    {"r": role_assignment_b},
                )
                with pytest.raises(IntegrityError) as exc2:
                    third.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
                assert "would be left with no membership" in str(exc2.value)
    finally:
        with engine.begin() as cleanup:
            params = {"s": slug}
            cleanup.execute(
                text("""
                    DELETE FROM security.membership_roles
                    WHERE campaign_membership_id IN (
                        SELECT campaign_membership_id FROM security.campaign_memberships
                        WHERE campaign_id IN (
                            SELECT campaign_id FROM campaign.campaigns
                            WHERE timeline_id IN (
                                SELECT timeline_id FROM campaign.timelines
                                WHERE world_id IN (SELECT world_id FROM core.worlds WHERE slug = :s)
                            )
                        )
                    )
                """),
                params,
            )
            cleanup.execute(
                text("""
                    DELETE FROM security.campaign_memberships
                    WHERE campaign_id IN (
                        SELECT campaign_id FROM campaign.campaigns
                        WHERE timeline_id IN (
                            SELECT timeline_id FROM campaign.timelines
                            WHERE world_id IN (SELECT world_id FROM core.worlds WHERE slug = :s)
                        )
                    )
                """),
                params,
            )
            cleanup.execute(
                text("""
                    DELETE FROM campaign.campaigns
                    WHERE timeline_id IN (
                        SELECT timeline_id FROM campaign.timelines
                        WHERE world_id IN (SELECT world_id FROM core.worlds WHERE slug = :s)
                    )
                """),
                params,
            )
            cleanup.execute(
                text("""
                    DELETE FROM campaign.timelines
                    WHERE world_id IN (SELECT world_id FROM core.worlds WHERE slug = :s)
                """),
                params,
            )
            cleanup.execute(text("DELETE FROM core.worlds WHERE slug = :s"), params)
            cleanup.execute(
                text("DELETE FROM security.users WHERE display_name IN (:a, :b)"),
                {"a": f"{slug}-owner-a", "b": f"{slug}-owner-b"},
            )


# ---------------------------------------------------------------------------
# 1b. The wall-clock expiration hole: only a non-expiring grant counts
# ---------------------------------------------------------------------------


def test_giving_the_sole_access_manager_a_finite_expiry_is_rejected(
    db_connection: Connection, f: Fixture
) -> None:
    """Even though the grant is still technically valid at check time (the
    expiry is an hour in the future), it must not count — a trigger cannot
    fire on the later passage of that hour, so only a permanent grant can be
    trusted to keep the invariant true between writes."""
    _membership, role_assignment = _make_owner(db_connection, f.campaign_id, "Sole Owner")

    db_connection.execute(
        text(
            "UPDATE security.membership_roles SET expires_at = now() + interval '1 hour' "
            "WHERE membership_role_id = :r"
        ),
        {"r": role_assignment},
    )
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        _immediate(db_connection)
    assert "would be left with no membership" in str(exc.value)


def test_expiring_additional_manager_allowed_alongside_a_non_expiring_owner(
    db_connection: Connection, f: Fixture
) -> None:
    """Temporary co-owners remain fully supported — the invariant only
    requires that at least one qualifying grant be permanent."""
    _make_owner(db_connection, f.campaign_id, "Permanent Owner")
    _membership_b, role_assignment_b = _make_owner(
        db_connection, f.campaign_id, "Temporary Co-Owner"
    )

    db_connection.execute(
        text(
            "UPDATE security.membership_roles SET expires_at = now() + interval '1 hour' "
            "WHERE membership_role_id = :r"
        ),
        {"r": role_assignment_b},
    )
    _immediate(db_connection)


def test_ownership_transfer_leaves_a_non_expiring_manager(
    db_connection: Connection, f: Fixture
) -> None:
    _old_membership, old_role_assignment = _make_owner(db_connection, f.campaign_id, "Old Owner")
    new_membership, _new_role_assignment = _make_owner(db_connection, f.campaign_id, "New Owner")

    db_connection.execute(
        text(
            "UPDATE security.membership_roles SET revoked_at = now() WHERE membership_role_id = :r"
        ),
        {"r": old_role_assignment},
    )
    _immediate(db_connection)

    expires_at = db_connection.execute(
        text(
            "SELECT expires_at FROM security.membership_roles "
            "WHERE campaign_membership_id = :m AND revoked_at IS NULL"
        ),
        {"m": new_membership},
    ).scalar()
    assert expires_at is None


def test_ownership_transfer_to_an_expiring_only_new_owner_is_rejected(
    db_connection: Connection, f: Fixture
) -> None:
    """The mirror image of the previous test: a transfer that leaves only an
    expiring grant behind must be rejected, not merely "any grant"."""
    _old_membership, old_role_assignment = _make_owner(db_connection, f.campaign_id, "Old Owner")
    new_user_id = make_user(db_connection, "Expiring New Owner")
    new_membership_id = make_campaign_membership(db_connection, f.campaign_id, new_user_id)
    new_role_assignment = make_membership_role(
        db_connection, new_membership_id, _campaign_owner_role_id(db_connection)
    )
    db_connection.execute(
        text(
            "UPDATE security.membership_roles SET expires_at = now() + interval '1 hour' "
            "WHERE membership_role_id = :r"
        ),
        {"r": new_role_assignment},
    )

    db_connection.execute(
        text(
            "UPDATE security.membership_roles SET revoked_at = now() WHERE membership_role_id = :r"
        ),
        {"r": old_role_assignment},
    )
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        _immediate(db_connection)
    assert "would be left with no membership" in str(exc.value)


# ---------------------------------------------------------------------------
# 1c. Protected lookup codes and lookup-row activation state
# ---------------------------------------------------------------------------


def test_renaming_the_active_lifecycle_status_code_is_rejected(db_connection: Connection) -> None:
    """core.lifecycle_statuses is shared, pre-existing infrastructure (revision
    003) — no other trigger in this schema fires on a rename of its own code
    column, so the invariant's `code = 'active'` comparison would silently
    stop matching every campaign without this guard."""
    with pytest.raises(CONSTRAINT_ERRORS) as exc, db_connection.begin_nested():
        db_connection.execute(
            text("UPDATE core.lifecycle_statuses SET code = 'renamed' WHERE code = 'active'")
        )
    assert "protected semantic identifier" in str(exc.value)


def test_lifecycle_status_active_row_descriptive_fields_still_updatable(
    db_connection: Connection,
) -> None:
    db_connection.execute(
        text(
            "UPDATE core.lifecycle_statuses SET display_name = 'Currently Active' "
            "WHERE code = 'active'"
        )
    )


def test_renaming_the_active_membership_status_code_is_rejected(db_connection: Connection) -> None:
    with pytest.raises(CONSTRAINT_ERRORS) as exc, db_connection.begin_nested():
        db_connection.execute(
            text("UPDATE security.membership_statuses SET code = 'renamed' WHERE code = 'active'")
        )
    assert "protected semantic identifier" in str(exc.value)


def test_membership_status_active_row_descriptive_fields_still_updatable(
    db_connection: Connection,
) -> None:
    db_connection.execute(
        text(
            "UPDATE security.membership_statuses SET description = 'Updated description' "
            "WHERE code = 'active'"
        )
    )


def test_renaming_the_access_manage_capability_code_is_rejected(db_connection: Connection) -> None:
    with pytest.raises(CONSTRAINT_ERRORS) as exc, db_connection.begin_nested():
        db_connection.execute(
            text("UPDATE security.capabilities SET code = 'renamed' WHERE code = 'access.manage'")
        )
    assert "protected semantic identifier" in str(exc.value)


def test_access_manage_capability_descriptive_fields_still_updatable(
    db_connection: Connection,
) -> None:
    db_connection.execute(
        text("UPDATE security.capabilities SET sort_order = 999 WHERE code = 'access.manage'")
    )


def test_other_lookup_rows_remain_freely_renamable(db_connection: Connection) -> None:
    """The guard is scoped to the specific seeded rows revision 080 relies
    on by code, not every row in these tables — an unrelated code (here, a
    fresh custom role's is unaffected, but that's covered by other tests;
    this proves a *different* pre-existing lookup row, e.g. a non-'active'
    membership status, is untouched by the new trigger)."""
    db_connection.execute(
        text(
            "UPDATE security.membership_statuses SET code = 'renamed_suspended' WHERE code = 'suspended'"
        )
    )
    db_connection.execute(
        text(
            "UPDATE security.membership_statuses SET code = 'suspended' WHERE code = 'renamed_suspended'"
        )
    )


def test_deactivating_the_sole_supporting_access_manage_capability_is_rejected(
    db_connection: Connection, f: Fixture
) -> None:
    """An inactive capability does not authorize — decided explicitly, not
    silently ignored — so deactivating it while a campaign depends on it
    solely must be rejected the same way removing it from a role is."""
    _make_owner(db_connection, f.campaign_id, "Sole Owner")

    db_connection.execute(
        text("UPDATE security.capabilities SET is_active = false WHERE code = 'access.manage'")
    )
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        _immediate(db_connection)
    assert "would be left with no membership" in str(exc.value)


def test_deactivating_access_manage_capability_with_no_dependents_succeeds(
    db_connection: Connection, f: Fixture
) -> None:
    """No campaign currently depends on access.manage. f.campaign_id is set
    non-active first — it was INSERTed active by the Fixture with no owner,
    which queues its own deferred check unconditionally (section 18); that
    check re-reads live status when it fires and only requires an owner
    while still active, so this is not a contradiction, just a reminder
    that a still-active, ownerless fixture campaign would itself fail this
    assertion for reasons unrelated to what this test verifies."""
    _set_campaign_lifecycle(db_connection, f.campaign_id, "pending")

    db_connection.execute(
        text("UPDATE security.capabilities SET is_active = false WHERE code = 'access.manage'")
    )
    _immediate(db_connection)


def test_deactivating_the_sole_supporting_membership_status_is_rejected(
    db_connection: Connection, f: Fixture
) -> None:
    """An inactive membership_statuses row does not authorize, even though
    its code still reads 'active' — deactivating it while a campaign
    depends on it solely must be rejected."""
    _make_owner(db_connection, f.campaign_id, "Sole Owner")

    db_connection.execute(
        text("UPDATE security.membership_statuses SET is_active = false WHERE code = 'active'")
    )
    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        _immediate(db_connection)
    assert "would be left with no membership" in str(exc.value)


def test_deactivating_active_membership_status_with_no_dependents_succeeds(
    db_connection: Connection, f: Fixture
) -> None:
    """f.campaign_id is set non-active first — see the analogous capability
    test immediately above for why."""
    _set_campaign_lifecycle(db_connection, f.campaign_id, "pending")

    db_connection.execute(
        text("UPDATE security.membership_statuses SET is_active = false WHERE code = 'active'")
    )
    _immediate(db_connection)


# ---------------------------------------------------------------------------
# 2. Reverse-mutation guards — immutable parent-scope identity columns
# ---------------------------------------------------------------------------


def test_campaign_memberships_campaign_cannot_be_reparented_once_a_role_references_it(
    db_connection: Connection, f: Fixture
) -> None:
    membership_id, _role_assignment = _make_owner(db_connection, f.campaign_id, "Reparent Target")
    other_timeline = make_timeline(db_connection, f.world_id)
    other_campaign = make_campaign(db_connection, other_timeline, "Other Campaign")

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "UPDATE security.campaign_memberships SET campaign_id = :c "
                "WHERE campaign_membership_id = :m"
            ),
            {"c": other_campaign, "m": membership_id},
        )
    assert "immutable" in str(exc.value)


def test_campaign_memberships_joined_at_can_still_be_updated(
    db_connection: Connection, f: Fixture
) -> None:
    membership_id, _role_assignment = _make_owner(
        db_connection, f.campaign_id, "Legit Update Target"
    )
    db_connection.execute(
        text(
            "UPDATE security.campaign_memberships SET joined_at = now() WHERE campaign_membership_id = :m"
        ),
        {"m": membership_id},
    )


def test_roles_campaign_cannot_be_reparented_once_a_membership_role_references_it(
    db_connection: Connection, f: Fixture
) -> None:
    role_id = make_role(db_connection, campaign_id=f.campaign_id, code="reparent_role")
    user_id = make_user(db_connection, "Role Reparent User")
    membership_id = make_campaign_membership(db_connection, f.campaign_id, user_id)
    make_membership_role(db_connection, membership_id, role_id)

    other_timeline = make_timeline(db_connection, f.world_id)
    other_campaign = make_campaign(db_connection, other_timeline, "Other Campaign")

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("UPDATE security.roles SET campaign_id = :c WHERE role_id = :r"),
            {"c": other_campaign, "r": role_id},
        )
    assert "immutable" in str(exc.value)


def test_roles_display_name_can_still_be_updated(db_connection: Connection, f: Fixture) -> None:
    role_id = make_role(db_connection, campaign_id=f.campaign_id, code="renamable_role")
    db_connection.execute(
        text("UPDATE security.roles SET display_name = 'Renamed Role' WHERE role_id = :r"),
        {"r": role_id},
    )


def test_system_role_campaign_id_cannot_be_promoted_to_campaign_scoped(
    db_connection: Connection, f: Fixture
) -> None:
    """campaign_owner (campaign_id NULL) is a system template usable by
    every campaign — used here by two different ones. The generic "immutable
    once set" guard (core.enforce_immutable_columns()) allows a NULL -> value
    transition elsewhere in this schema, but security.roles.campaign_id uses
    its own dedicated, NULL-inclusive guard instead: NULL is a permanent
    value for this column (system template), not a not-yet-set placeholder,
    so promoting it to campaign-scoped must be rejected — and both existing,
    unrelated assignments of the role must remain untouched and valid."""
    other_timeline = make_timeline(db_connection, f.world_id)
    other_campaign = make_campaign(db_connection, other_timeline, "Second Campaign")

    _membership_a, role_assignment_a = _make_owner(db_connection, f.campaign_id, "Owner A")
    _membership_b, role_assignment_b = _make_owner(db_connection, other_campaign, "Owner B")

    # A SAVEPOINT (begin_nested): the failed UPDATE aborts the current
    # transaction in PostgreSQL, which would poison every later statement on
    # this connection — including the verification queries below — unless
    # the failure is scoped to a sub-transaction that rolls back on its own.
    with pytest.raises(CONSTRAINT_ERRORS) as exc, db_connection.begin_nested():
        db_connection.execute(
            text("UPDATE security.roles SET campaign_id = :c WHERE role_id = :r"),
            {"c": f.campaign_id, "r": _campaign_owner_role_id(db_connection)},
        )
    assert "immutable" in str(exc.value)

    for role_assignment in (role_assignment_a, role_assignment_b):
        row = db_connection.execute(
            text(
                "SELECT revoked_at, role_id FROM security.membership_roles "
                "WHERE membership_role_id = :r"
            ),
            {"r": role_assignment},
        ).one()
        assert row.revoked_at is None
        assert row.role_id == _campaign_owner_role_id(db_connection)


def test_access_groups_campaign_cannot_be_reparented_once_a_membership_references_it(
    db_connection: Connection, f: Fixture
) -> None:
    access_group_id = make_access_group(db_connection, f.campaign_id)
    user_id = make_user(db_connection, "Access Group Reparent User")
    membership_id = make_campaign_membership(db_connection, f.campaign_id, user_id)
    make_access_group_membership(db_connection, access_group_id, membership_id)

    other_timeline = make_timeline(db_connection, f.world_id)
    other_campaign = make_campaign(db_connection, other_timeline, "Other Campaign")

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("UPDATE security.access_groups SET campaign_id = :c WHERE access_group_id = :g"),
            {"c": other_campaign, "g": access_group_id},
        )
    assert "immutable" in str(exc.value)


def test_access_groups_description_can_still_be_updated(
    db_connection: Connection, f: Fixture
) -> None:
    access_group_id = make_access_group(db_connection, f.campaign_id)
    db_connection.execute(
        text(
            "UPDATE security.access_groups SET description = 'Updated' WHERE access_group_id = :g"
        ),
        {"g": access_group_id},
    )


def test_sessions_campaign_cannot_be_reparented_once_a_resource_grant_references_it(
    db_connection: Connection, f: Fixture
) -> None:
    session_id = make_session(db_connection, f.campaign_id, 1)
    membership_id, _role_assignment = _make_owner(
        db_connection, f.campaign_id, "Session Reparent Grantee"
    )
    access_manage_id = lookup_id(
        db_connection, "security", "capabilities", "capability_id", "access.manage"
    )
    make_resource_grant(
        db_connection,
        f.campaign_id,
        access_manage_id,
        grantee_campaign_membership_id=membership_id,
        session_id=session_id,
    )

    other_timeline = make_timeline(db_connection, f.world_id)
    other_campaign = make_campaign(db_connection, other_timeline, "Other Campaign")

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text("UPDATE campaign.sessions SET campaign_id = :c WHERE session_id = :s"),
            {"c": other_campaign, "s": session_id},
        )
    assert "immutable" in str(exc.value)


def test_sessions_title_can_still_be_updated(db_connection: Connection, f: Fixture) -> None:
    session_id = make_session(db_connection, f.campaign_id, 1)
    db_connection.execute(
        text("UPDATE campaign.sessions SET title = 'Renamed Session' WHERE session_id = :s"),
        {"s": session_id},
    )


def test_events_campaign_and_timeline_cannot_be_reparented_once_a_resource_grant_references_it(
    db_connection: Connection, f: Fixture
) -> None:
    world_time_id = make_world_time(db_connection, f.world_id, 100)
    event_id = make_event(
        db_connection,
        f.world_id,
        f.timeline_id,
        world_time_id,
        campaign_id=f.campaign_id,
        event_status_code="draft",
    )
    membership_id, _role_assignment = _make_owner(
        db_connection, f.campaign_id, "Event Reparent Grantee"
    )
    access_manage_id = lookup_id(
        db_connection, "security", "capabilities", "capability_id", "access.manage"
    )
    make_resource_grant(
        db_connection,
        f.campaign_id,
        access_manage_id,
        grantee_campaign_membership_id=membership_id,
        event_id=event_id,
    )

    # A campaign has exactly one timeline (campaign.campaigns.timeline_id is
    # itself immutable, revision 030), so changing only one of campaign_id/
    # timeline_id on an event always trips the pre-existing narrative.
    # enforce_event_consistency() cross-check first (event campaign's
    # timeline disagreeing with event.timeline_id) — that trigger fires
    # before this revision's tr_events_enforce_immutable alphabetically
    # (tr_events_enforce_consistency < tr_events_enforce_immutable) in any
    # case. Moving both together to a mutually consistent new pair passes
    # that pre-existing check and isolates this revision's own guard as the
    # one that rejects it.
    other_timeline = make_timeline(db_connection, f.world_id)
    other_campaign = make_campaign(db_connection, other_timeline, "Other Campaign")

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "UPDATE narrative.events SET campaign_id = :c, timeline_id = :t WHERE event_id = :e"
            ),
            {"c": other_campaign, "t": other_timeline, "e": event_id},
        )
    assert "immutable" in str(exc.value)


def test_events_details_can_still_be_updated(db_connection: Connection, f: Fixture) -> None:
    world_time_id = make_world_time(db_connection, f.world_id, 100)
    event_id = make_event(
        db_connection,
        f.world_id,
        f.timeline_id,
        world_time_id,
        campaign_id=f.campaign_id,
        event_status_code="draft",
    )
    db_connection.execute(
        text("UPDATE narrative.events SET details = 'Updated details' WHERE event_id = :e"),
        {"e": event_id},
    )


# ---------------------------------------------------------------------------
# 3. Same-campaign actor-scope guards
# ---------------------------------------------------------------------------


def test_campaign_membership_ended_by_rejects_actor_from_another_campaign(
    db_connection: Connection, f: Fixture
) -> None:
    membership_id, _role_assignment = _make_owner(db_connection, f.campaign_id, "Target Membership")
    other_timeline = make_timeline(db_connection, f.world_id)
    other_campaign = make_campaign(db_connection, other_timeline, "Other Campaign")
    foreign_user_id = make_user(db_connection, "Foreign Actor")
    foreign_membership_id = make_campaign_membership(db_connection, other_campaign, foreign_user_id)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "UPDATE security.campaign_memberships SET ended_at = now(), ended_by_membership_id = :a "
                "WHERE campaign_membership_id = :m"
            ),
            {"a": foreign_membership_id, "m": membership_id},
        )
    assert "belongs to campaign" in str(exc.value)


def test_campaign_membership_ended_by_accepts_actor_from_same_campaign(
    db_connection: Connection, f: Fixture
) -> None:
    membership_id, _role_assignment = _make_owner(db_connection, f.campaign_id, "Target Membership")
    actor_membership_id, _ = _make_owner(db_connection, f.campaign_id, "Same-Campaign Actor")

    db_connection.execute(
        text(
            "UPDATE security.campaign_memberships "
            "SET ended_at = now() + interval '1 second', ended_by_membership_id = :a "
            "WHERE campaign_membership_id = :m"
        ),
        {"a": actor_membership_id, "m": membership_id},
    )


def test_campaign_invitation_invited_by_rejects_actor_from_another_campaign(
    db_connection: Connection, f: Fixture
) -> None:
    other_timeline = make_timeline(db_connection, f.world_id)
    other_campaign = make_campaign(db_connection, other_timeline, "Other Campaign")
    foreign_user_id = make_user(db_connection, "Foreign Inviter")
    foreign_membership_id = make_campaign_membership(db_connection, other_campaign, foreign_user_id)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_campaign_invitation(db_connection, f.campaign_id, foreign_membership_id)
    assert "belongs to campaign" in str(exc.value)


def test_membership_role_granted_by_rejects_actor_from_another_campaign(
    db_connection: Connection, f: Fixture
) -> None:
    user_id = make_user(db_connection, "Grant Target")
    membership_id = make_campaign_membership(db_connection, f.campaign_id, user_id)
    other_timeline = make_timeline(db_connection, f.world_id)
    other_campaign = make_campaign(db_connection, other_timeline, "Other Campaign")
    foreign_user_id = make_user(db_connection, "Foreign Granter")
    foreign_membership_id = make_campaign_membership(db_connection, other_campaign, foreign_user_id)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_membership_role(
            db_connection,
            membership_id,
            _campaign_owner_role_id(db_connection),
            granted_by_membership_id=foreign_membership_id,
        )
    assert "belongs to campaign" in str(exc.value)


def test_membership_role_granted_by_rejects_actor_via_update_too(
    db_connection: Connection, f: Fixture
) -> None:
    membership_id, role_assignment = _make_owner(
        db_connection, f.campaign_id, "Update Grant Target"
    )
    other_timeline = make_timeline(db_connection, f.world_id)
    other_campaign = make_campaign(db_connection, other_timeline, "Other Campaign")
    foreign_user_id = make_user(db_connection, "Foreign Granter Via Update")
    foreign_membership_id = make_campaign_membership(db_connection, other_campaign, foreign_user_id)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "UPDATE security.membership_roles SET granted_by_membership_id = :a "
                "WHERE membership_role_id = :r"
            ),
            {"a": foreign_membership_id, "r": role_assignment},
        )
    assert "belongs to campaign" in str(exc.value)


def test_membership_character_relationship_granted_by_rejects_actor_from_another_campaign(
    db_connection: Connection, f: Fixture
) -> None:
    membership_id, _ = _make_owner(db_connection, f.campaign_id, "Relationship Target")
    character_id = make_character(db_connection, f.world_id)
    relationship_type_id = make_character_relationship_type(db_connection)
    other_timeline = make_timeline(db_connection, f.world_id)
    other_campaign = make_campaign(db_connection, other_timeline, "Other Campaign")
    foreign_user_id = make_user(db_connection, "Foreign Relationship Granter")
    foreign_membership_id = make_campaign_membership(db_connection, other_campaign, foreign_user_id)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_membership_character_relationship(
            db_connection,
            membership_id,
            character_id,
            relationship_type_id,
            granted_by_membership_id=foreign_membership_id,
        )
    assert "belonging to campaign" in str(exc.value)


def test_access_group_membership_added_by_rejects_actor_from_another_campaign(
    db_connection: Connection, f: Fixture
) -> None:
    access_group_id = make_access_group(db_connection, f.campaign_id)
    user_id = make_user(db_connection, "Group Target")
    membership_id = make_campaign_membership(db_connection, f.campaign_id, user_id)
    other_timeline = make_timeline(db_connection, f.world_id)
    other_campaign = make_campaign(db_connection, other_timeline, "Other Campaign")
    foreign_user_id = make_user(db_connection, "Foreign Adder")
    foreign_membership_id = make_campaign_membership(db_connection, other_campaign, foreign_user_id)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        db_connection.execute(
            text(
                "INSERT INTO security.access_group_memberships "
                "(access_group_id, campaign_membership_id, added_by_membership_id) "
                "VALUES (:g, :m, :a)"
            ),
            {"g": access_group_id, "m": membership_id, "a": foreign_membership_id},
        )
    assert "belonging to campaign" in str(exc.value)


def test_resource_grant_granted_by_rejects_actor_from_another_campaign(
    db_connection: Connection, f: Fixture
) -> None:
    membership_id, _ = _make_owner(db_connection, f.campaign_id, "Grant Target Membership")
    knowledge_item_id = make_knowledge_item(db_connection, f.world_id)
    access_manage_id = lookup_id(
        db_connection, "security", "capabilities", "capability_id", "access.manage"
    )
    other_timeline = make_timeline(db_connection, f.world_id)
    other_campaign = make_campaign(db_connection, other_timeline, "Other Campaign")
    foreign_user_id = make_user(db_connection, "Foreign Grant Actor")
    foreign_membership_id = make_campaign_membership(db_connection, other_campaign, foreign_user_id)

    with pytest.raises(CONSTRAINT_ERRORS) as exc:
        make_resource_grant(
            db_connection,
            f.campaign_id,
            access_manage_id,
            grantee_campaign_membership_id=membership_id,
            knowledge_item_id=knowledge_item_id,
            granted_by_membership_id=foreign_membership_id,
        )
    assert "belongs to campaign" in str(exc.value)
