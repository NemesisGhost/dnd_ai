"""Shared test-data builders.

Lives here rather than in a test module so test modules never import from each
other — that coupling makes it unclear who owns a helper and breaks as soon as
the importing module is collected first.

These issue raw inserts. docs/DATABASE_CONVENTIONS.md §32.3 asks for test data
built through the same commands production uses, and those commands do not
exist yet — the application layer arrives in a later phase. Everything using
these builders is also specifically testing database enforcement, which is the
exception §32.3 allows. Replace these with command calls once the command layer
lands, rather than growing them into a parallel write path.
"""

import json
import uuid

from sqlalchemy import Connection, text


def status_id(connection: Connection, table: str, code: str) -> uuid.UUID:
    """Look up a seeded status by code. Asserts rather than returning None."""
    pk = "canon_status_id" if table == "canon_statuses" else "lifecycle_status_id"
    value = connection.execute(
        text(f"SELECT {pk} FROM core.{table} WHERE code = :c"), {"c": code}
    ).scalar()
    assert isinstance(value, uuid.UUID), f"seeded {table} row {code!r} missing"
    return value


def lookup_id(connection: Connection, schema: str, table: str, pk: str, code: str) -> uuid.UUID:
    value = connection.execute(
        text(f"SELECT {pk} FROM {schema}.{table} WHERE code = :c"), {"c": code}
    ).scalar()
    assert isinstance(value, uuid.UUID), f"seeded {schema}.{table} row {code!r} missing"
    return value


def make_world(connection: Connection, slug: str = "test-world") -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO core.worlds (name, slug, lifecycle_status_id)
            VALUES ('Test World', :slug, :status)
            RETURNING world_id
        """),
        {"slug": slug, "status": status_id(connection, "lifecycle_statuses", "active")},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_entity_type(
    connection: Connection,
    code: str,
    *,
    parent_id: uuid.UUID | None = None,
    subtype_table: str | None = None,
    subtype_pk_column: str | None = None,
) -> uuid.UUID:
    """subtype_pk_column is required whenever subtype_table is set (revision
    048's ck_entity_types_subtype_pk_column_paired) — the primary-key column
    name of subtype_table, e.g. "npc_id" for "character.npcs". Left unset
    when a caller is deliberately testing an invalid/unqualified
    subtype_table and expects the INSERT to fail regardless."""
    value = connection.execute(
        text("""
            INSERT INTO core.entity_types
                (code, display_name, parent_entity_type_id, required_subtype_table,
                 required_subtype_pk_column)
            VALUES (:code, :code, :parent, :subtype, :pk_column)
            RETURNING entity_type_id
        """),
        {
            "code": code,
            "parent": parent_id,
            "subtype": subtype_table,
            "pk_column": subtype_pk_column,
        },
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_entity(
    connection: Connection,
    world_id: uuid.UUID,
    entity_type_id: uuid.UUID,
    name: str = "Test Entity",
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO core.entities
                (world_id, entity_type_id, canonical_name, canon_status_id, lifecycle_status_id)
            VALUES (:world, :etype, :name, :canon, :lifecycle)
            RETURNING entity_id
        """),
        {
            "world": world_id,
            "etype": entity_type_id,
            "name": name,
            "canon": status_id(connection, "canon_statuses", "draft"),
            "lifecycle": status_id(connection, "lifecycle_statuses", "active"),
        },
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_user(
    connection: Connection, display_name: str = "Tester", *, status_code: str = "active"
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO security.users (display_name, lifecycle_status_id)
            VALUES (:name, :status)
            RETURNING user_id
        """),
        {"name": display_name, "status": status_id(connection, "lifecycle_statuses", status_code)},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_external_identity(
    connection: Connection,
    user_id: uuid.UUID,
    *,
    issuer: str = "https://test-idp.example",
    subject: str | None = None,
    revoked: bool = False,
) -> uuid.UUID:
    if subject is None:
        subject = f"subject-{uuid.uuid4().hex[:8]}"
    value = connection.execute(
        text("""
            INSERT INTO security.external_identities (user_id, issuer, subject, revoked_at)
            VALUES (:user, :issuer, :subject, CASE WHEN :revoked THEN now() ELSE NULL END)
            RETURNING external_identity_id
        """),
        {"user": user_id, "issuer": issuer, "subject": subject, "revoked": revoked},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_service_account(connection: Connection, code: str | None = None) -> uuid.UUID:
    if code is None:
        code = f"service_{uuid.uuid4().hex[:8]}"
    value = connection.execute(
        text("""
            INSERT INTO security.service_accounts (code, display_name)
            VALUES (:code, :code)
            RETURNING service_account_id
        """),
        {"code": code},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_campaign_membership(
    connection: Connection,
    campaign_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    status_code: str = "active",
    ended: bool = False,
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO security.campaign_memberships
                (campaign_id, user_id, membership_status_id, joined_at, ended_at)
            VALUES (
                :campaign, :user,
                (SELECT membership_status_id FROM security.membership_statuses WHERE code = :status),
                now(),
                -- +1 microsecond: now() is frozen for the whole test transaction, so a bare
                -- now() here would tie joined_at exactly and trip
                -- ck_campaign_memberships_ended_after_joined's strict ">".
                CASE WHEN :ended THEN now() + interval '1 microsecond' ELSE NULL END
            )
            RETURNING campaign_membership_id
        """),
        {"campaign": campaign_id, "user": user_id, "status": status_code, "ended": ended},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_campaign_invitation(
    connection: Connection,
    campaign_id: uuid.UUID,
    invited_by_membership_id: uuid.UUID,
    *,
    token_hash: str | None = None,
) -> uuid.UUID:
    if token_hash is None:
        token_hash = uuid.uuid4().hex
    value = connection.execute(
        text("""
            INSERT INTO security.campaign_invitations
                (campaign_id, invitation_token_hash, invited_by_membership_id, expires_at)
            VALUES (:campaign, :token, :invited_by, now() + interval '7 days')
            RETURNING campaign_invitation_id
        """),
        {"campaign": campaign_id, "token": token_hash, "invited_by": invited_by_membership_id},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_role(
    connection: Connection,
    *,
    campaign_id: uuid.UUID | None = None,
    code: str | None = None,
) -> uuid.UUID:
    if code is None:
        code = f"role_{uuid.uuid4().hex[:8]}"
    value = connection.execute(
        text("""
            INSERT INTO security.roles (campaign_id, code, display_name)
            VALUES (:campaign, :code, :code)
            RETURNING role_id
        """),
        {"campaign": campaign_id, "code": code},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_capability(connection: Connection, code: str | None = None) -> uuid.UUID:
    if code is None:
        code = f"test.capability_{uuid.uuid4().hex[:8]}"
    value = connection.execute(
        text("""
            INSERT INTO security.capabilities (code, display_name)
            VALUES (:code, :code)
            RETURNING capability_id
        """),
        {"code": code},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_role_capability(
    connection: Connection, role_id: uuid.UUID, capability_id: uuid.UUID
) -> None:
    connection.execute(
        text("INSERT INTO security.role_capabilities (role_id, capability_id) VALUES (:r, :c)"),
        {"r": role_id, "c": capability_id},
    )


def make_membership_role(
    connection: Connection,
    campaign_membership_id: uuid.UUID,
    role_id: uuid.UUID,
    *,
    granted_by_membership_id: uuid.UUID | None = None,
    revoked: bool = False,
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO security.membership_roles
                (campaign_membership_id, role_id, granted_by_membership_id, revoked_at)
            VALUES (:membership, :role, :granted_by, CASE WHEN :revoked THEN now() ELSE NULL END)
            RETURNING membership_role_id
        """),
        {
            "membership": campaign_membership_id,
            "role": role_id,
            "granted_by": granted_by_membership_id,
            "revoked": revoked,
        },
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_character_relationship_type(connection: Connection, code: str | None = None) -> uuid.UUID:
    if code is None:
        code = f"relationship_type_{uuid.uuid4().hex[:8]}"
    value = connection.execute(
        text("""
            INSERT INTO security.character_relationship_types (code, display_name)
            VALUES (:code, :code)
            RETURNING character_relationship_type_id
        """),
        {"code": code},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_membership_character_relationship(
    connection: Connection,
    campaign_membership_id: uuid.UUID,
    character_id: uuid.UUID,
    character_relationship_type_id: uuid.UUID,
    *,
    timeline_id: uuid.UUID | None = None,
    effective_from_world_time_id: uuid.UUID | None = None,
    effective_to_world_time_id: uuid.UUID | None = None,
    granted_by_membership_id: uuid.UUID | None = None,
    revoked: bool = False,
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO security.membership_character_relationships
                (campaign_membership_id, character_id, character_relationship_type_id,
                 timeline_id, effective_from_world_time_id, effective_to_world_time_id,
                 granted_by_membership_id, revoked_at)
            VALUES (
                :membership, :character, :rtype, :timeline, :from_time, :to_time, :granted_by,
                CASE WHEN :revoked THEN now() ELSE NULL END
            )
            RETURNING membership_character_relationship_id
        """),
        {
            "membership": campaign_membership_id,
            "character": character_id,
            "rtype": character_relationship_type_id,
            "timeline": timeline_id,
            "from_time": effective_from_world_time_id,
            "to_time": effective_to_world_time_id,
            "granted_by": granted_by_membership_id,
            "revoked": revoked,
        },
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_relationship_type_capability(
    connection: Connection, character_relationship_type_id: uuid.UUID, capability_id: uuid.UUID
) -> None:
    connection.execute(
        text(
            "INSERT INTO security.character_relationship_type_capabilities "
            "(character_relationship_type_id, capability_id) VALUES (:rt, :c)"
        ),
        {"rt": character_relationship_type_id, "c": capability_id},
    )


def make_access_group(
    connection: Connection, campaign_id: uuid.UUID, *, name: str = "Test Group"
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO security.access_groups (campaign_id, name)
            VALUES (:campaign, :name)
            RETURNING access_group_id
        """),
        {"campaign": campaign_id, "name": name},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_access_group_membership(
    connection: Connection,
    access_group_id: uuid.UUID,
    campaign_membership_id: uuid.UUID,
    *,
    removed: bool = False,
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO security.access_group_memberships
                (access_group_id, campaign_membership_id, removed_at)
            VALUES (:group, :membership, CASE WHEN :removed THEN now() ELSE NULL END)
            RETURNING access_group_membership_id
        """),
        {"group": access_group_id, "membership": campaign_membership_id, "removed": removed},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_resource_grant(
    connection: Connection,
    campaign_id: uuid.UUID,
    capability_id: uuid.UUID,
    *,
    timeline_id: uuid.UUID | None = None,
    grantee_campaign_membership_id: uuid.UUID | None = None,
    grantee_access_group_id: uuid.UUID | None = None,
    character_id: uuid.UUID | None = None,
    entity_id: uuid.UUID | None = None,
    knowledge_item_id: uuid.UUID | None = None,
    quest_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    event_id: uuid.UUID | None = None,
    effect: str = "allow",
    grant_source: str = "test",
    granted_by_membership_id: uuid.UUID | None = None,
    revoked: bool = False,
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO security.resource_grants
                (campaign_id, timeline_id, grantee_campaign_membership_id, grantee_access_group_id,
                 capability_id, effect, character_id, entity_id, knowledge_item_id, quest_id,
                 session_id, event_id, granted_by_membership_id, grant_source, revoked_at)
            VALUES (
                :campaign, :timeline, :grantee_membership, :grantee_group,
                :capability, :effect, :character, :entity, :knowledge_item, :quest,
                :session, :event, :granted_by, :grant_source,
                CASE WHEN :revoked THEN now() ELSE NULL END
            )
            RETURNING resource_grant_id
        """),
        {
            "campaign": campaign_id,
            "timeline": timeline_id,
            "grantee_membership": grantee_campaign_membership_id,
            "grantee_group": grantee_access_group_id,
            "capability": capability_id,
            "effect": effect,
            "character": character_id,
            "entity": entity_id,
            "knowledge_item": knowledge_item_id,
            "quest": quest_id,
            "session": session_id,
            "event": event_id,
            "granted_by": granted_by_membership_id,
            "grant_source": grant_source,
            "revoked": revoked,
        },
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_world_time(connection: Connection, world_id: uuid.UUID, sort_key: int) -> uuid.UUID:
    """A minimal point in a world's fictional chronology.

    sort_key is the only field that matters to interval logic, so callers pass
    it explicitly and everything else takes a default. year is supplied because
    ck_world_times_year_or_label requires a year or a label.
    """
    value = connection.execute(
        text("""
            INSERT INTO core.world_times
                (world_id, world_time_precision_id, year, sort_key)
            VALUES (
                :world,
                (SELECT world_time_precision_id FROM core.world_time_precisions
                 WHERE code = 'exact'),
                :year,
                :sort_key
            )
            RETURNING world_time_id
        """),
        {"world": world_id, "year": 1000 + sort_key, "sort_key": sort_key},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_timeline(
    connection: Connection,
    world_id: uuid.UUID,
    name: str = "Primary",
    *,
    is_primary: bool = False,
    parent_timeline_id: uuid.UUID | None = None,
    branch_world_time_id: uuid.UUID | None = None,
    branch_event_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """branch_event_id is omitted from the INSERT column list entirely when
    not given, rather than always sent as NULL — tests/database/
    test_phase5_populated_upgrade.py deliberately calls this against a
    database pinned at revision 042, before campaign.timelines.
    branch_event_id existed (revision 058); every other caller passing no
    branch_event_id must keep working unchanged there."""
    params = {
        "world": world_id,
        "name": name,
        "primary": is_primary,
        "parent": parent_timeline_id,
        "branch": branch_world_time_id,
        "status": status_id(connection, "lifecycle_statuses", "active"),
    }
    if branch_event_id is not None:
        query = """
            INSERT INTO campaign.timelines
                (world_id, name, is_primary, parent_timeline_id, branch_world_time_id,
                 branch_event_id, lifecycle_status_id)
            VALUES (:world, :name, :primary, :parent, :branch, :branch_event, :status)
            RETURNING timeline_id
        """
        params["branch_event"] = branch_event_id
    else:
        query = """
            INSERT INTO campaign.timelines
                (world_id, name, is_primary, parent_timeline_id, branch_world_time_id,
                 lifecycle_status_id)
            VALUES (:world, :name, :primary, :parent, :branch, :status)
            RETURNING timeline_id
        """
    value = connection.execute(text(query), params).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def set_timeline_branch_event(
    connection: Connection, timeline_id: uuid.UUID, branch_event_id: uuid.UUID | None
) -> None:
    """Set/clear branch_event_id on an already-created timeline — for tests
    that need to exercise campaign.enforce_timeline_branch()'s UPDATE path,
    not just the INSERT path make_timeline covers."""
    connection.execute(
        text("UPDATE campaign.timelines SET branch_event_id = :e WHERE timeline_id = :t"),
        {"e": branch_event_id, "t": timeline_id},
    )


def make_party(connection: Connection, world_id: uuid.UUID, name: str = "The Company") -> uuid.UUID:
    value = connection.execute(
        text("INSERT INTO campaign.parties (world_id, name) VALUES (:w, :n) RETURNING party_id"),
        {"w": world_id, "n": name},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_campaign_party(
    connection: Connection, campaign_id: uuid.UUID, party_id: uuid.UUID
) -> None:
    """Associates a party with a campaign via campaign.campaign_parties
    (revision 010) — a pure composite-PK join table, so there is no
    surrogate id to return."""
    connection.execute(
        text("INSERT INTO campaign.campaign_parties (campaign_id, party_id) VALUES (:c, :p)"),
        {"c": campaign_id, "p": party_id},
    )


def make_party_membership(
    connection: Connection,
    timeline_id: uuid.UUID,
    party_id: uuid.UUID,
    member_entity_id: uuid.UUID,
    effective_from_world_time_id: uuid.UUID,
    *,
    effective_to_world_time_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """A `campaign.party_memberships` row (migration 009) — the timeline-
    scoped, temporal record of a character belonging to a party. Leaving
    `effective_to_world_time_id` unset (the default) produces an
    open-ended membership, this table's own documented "the single
    representation of 'still a member'" — the exact contract
    `dnd_ai.api.access.resolve_party_perspective` relies on to authorize a
    party perspective."""
    value = connection.execute(
        text("""
            INSERT INTO campaign.party_memberships
                (timeline_id, party_id, member_entity_id, effective_from_world_time_id,
                 effective_to_world_time_id)
            VALUES (:timeline, :party, :member, :from_time, :to_time)
            RETURNING party_membership_id
        """),
        {
            "timeline": timeline_id,
            "party": party_id,
            "member": member_entity_id,
            "from_time": effective_from_world_time_id,
            "to_time": effective_to_world_time_id,
        },
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_ruleset_version(connection: Connection, code: str | None = None) -> uuid.UUID:
    """A bare ruleset + ruleset_version, with no world association.

    For content tests (species, classes, ...) that need a version to hang
    off but don't need a campaign or world_rulesets entry. Use
    make_ruleset_for_world instead when a campaign needs to reference the
    ruleset.
    """
    if code is None:
        code = f"ruleset_{uuid.uuid4().hex[:8]}"
    ruleset_id = connection.execute(
        text(
            "INSERT INTO rules.rulesets (code, display_name) VALUES (:c, :c) RETURNING ruleset_id"
        ),
        {"c": code},
    ).scalar()
    value = connection.execute(
        text("""
            INSERT INTO rules.ruleset_versions (ruleset_id, version_label)
            VALUES (:r, 'v1')
            RETURNING ruleset_version_id
        """),
        {"r": ruleset_id},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_bare_ruleset(connection: Connection, code: str) -> uuid.UUID:
    """A ruleset row with no version at all — for tests that manage the
    ruleset_versions insert themselves (e.g. moving a version between two
    rulesets to prove ruleset_id is immutable)."""
    value = connection.execute(
        text(
            "INSERT INTO rules.rulesets (code, display_name) VALUES (:c, :c) RETURNING ruleset_id"
        ),
        {"c": code},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def current_ruleset_version_id(connection: Connection, ruleset_id: uuid.UUID) -> uuid.UUID:
    value = connection.execute(
        text(
            "SELECT ruleset_version_id FROM rules.ruleset_versions "
            "WHERE ruleset_id = :r AND is_current"
        ),
        {"r": ruleset_id},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_species(
    connection: Connection, ruleset_version_id: uuid.UUID, code: str = "human"
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO rules.species (ruleset_version_id, code, display_name)
            VALUES (:v, :c, :c)
            RETURNING species_id
        """),
        {"v": ruleset_version_id, "c": code},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_ability(
    connection: Connection, ruleset_version_id: uuid.UUID, code: str = "strength"
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO rules.abilities (ruleset_version_id, code, display_name)
            VALUES (:v, :c, :c)
            RETURNING ability_id
        """),
        {"v": ruleset_version_id, "c": code},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_skill(
    connection: Connection,
    ruleset_version_id: uuid.UUID,
    ability_id: uuid.UUID,
    code: str = "stealth",
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO rules.skills (ruleset_version_id, ability_id, code, display_name)
            VALUES (:v, :a, :c, :c)
            RETURNING skill_id
        """),
        {"v": ruleset_version_id, "a": ability_id, "c": code},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_character(
    connection: Connection,
    world_id: uuid.UUID,
    *,
    species_id: uuid.UUID | None = None,
    name: str = "Test Character",
    size_category: str = "medium",
    entity_type_code: str = "character",
) -> uuid.UUID:
    """A core.entities row plus its character.characters row. Returns the
    shared UUID (the character_id, same as the entity_id).

    species_id is auto-provisioned (a ruleset version associated with
    world_id, so the species passes character.enforce_character_species_
    ruleset_allowed() — revision 029) when omitted. entity_type_code defaults
    to the bare 'character' type; pass 'npc' or 'player_character' when the
    caller also needs to insert the corresponding character.npcs /
    character.player_characters row — core.enforce_entity_subtype() rejects
    that subtype row otherwise, since a bare 'character'-typed entity does
    not require one.
    """
    if species_id is None:
        species_id = make_species(connection, make_ruleset_version_for_world(connection, world_id))

    character_type_id = lookup_id(
        connection, "core", "entity_types", "entity_type_id", entity_type_code
    )
    character_id = make_entity(connection, world_id, character_type_id, name=name)
    connection.execute(
        text("""
            INSERT INTO character.characters (character_id, species_id, size_category)
            VALUES (:c, :s, :size)
        """),
        {"c": character_id, "s": species_id, "size": size_category},
    )
    return character_id


def make_ruleset_for_world(
    connection: Connection,
    world_id: uuid.UUID,
    code: str | None = None,
    *,
    is_default: bool | None = None,
) -> uuid.UUID:
    """A ruleset + current ruleset_version + world_rulesets association, ready
    for a campaign in this world to reference.

    code defaults to a random slug since rules.rulesets.code is unique across
    the whole database, not per world. is_default controls
    core.worlds.default_ruleset_id — the sole source of truth for a world's
    default ruleset since revision 027 removed rules.world_rulesets.is_default
    — and defaults to True only if the world has no default yet.
    """
    if code is None:
        code = f"ruleset_{uuid.uuid4().hex[:8]}"

    ruleset_id = connection.execute(
        text(
            "INSERT INTO rules.rulesets (code, display_name) VALUES (:c, :c) RETURNING ruleset_id"
        ),
        {"c": code},
    ).scalar()
    assert isinstance(ruleset_id, uuid.UUID)
    connection.execute(
        text("""
            INSERT INTO rules.ruleset_versions (ruleset_id, version_label, is_current)
            VALUES (:r, 'v1', true)
        """),
        {"r": ruleset_id},
    )
    connection.execute(
        text("INSERT INTO rules.world_rulesets (world_id, ruleset_id) VALUES (:w, :r)"),
        {"w": world_id, "r": ruleset_id},
    )

    if is_default is None:
        existing_default = connection.execute(
            text("SELECT default_ruleset_id FROM core.worlds WHERE world_id = :w"),
            {"w": world_id},
        ).scalar()
        is_default = existing_default is None

    if is_default:
        connection.execute(
            text("UPDATE core.worlds SET default_ruleset_id = :r WHERE world_id = :w"),
            {"r": ruleset_id, "w": world_id},
        )

    return ruleset_id


def make_ruleset_version_for_world(
    connection: Connection, world_id: uuid.UUID, code: str | None = None
) -> uuid.UUID:
    """A ruleset version associated with world_id via rules.world_rulesets,
    ready to hang content (species, conditions, resource_definitions, a
    character build, ...) off for a character or timeline in this world.

    Since revision 029, species/build/condition/resource references are
    checked against rules.world_rulesets for the owning world — a bare
    make_ruleset_version() has no such association and will be rejected.
    Does not touch core.worlds.default_ruleset_id (is_default=False).
    """
    ruleset_id = make_ruleset_for_world(connection, world_id, code, is_default=False)
    value = connection.execute(
        text(
            "SELECT ruleset_version_id FROM rules.ruleset_versions "
            "WHERE ruleset_id = :r AND is_current"
        ),
        {"r": ruleset_id},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_campaign(
    connection: Connection,
    timeline_id: uuid.UUID,
    name: str = "The Campaign",
    *,
    ruleset_version_id: uuid.UUID | None = None,
    lifecycle_status_code: str = "active",
) -> uuid.UUID:
    """A campaign on the given timeline.

    ruleset_version_id is auto-provisioned when omitted: looks up the
    timeline's world, reuses a ruleset already allowed there if one exists
    (pinning to its current version), otherwise creates one via
    make_ruleset_for_world. Callers testing ruleset-specific behavior should
    pass one explicitly.

    lifecycle_status_code defaults to "active" (matching every caller's
    prior expectation). Since revision 080, an active campaign must retain
    a qualifying access-manager membership at commit — pass "pending" (or
    similar) for a caller that doesn't set one up and doesn't care about
    campaign lifecycle, or a real one for a caller that wants to exercise
    the create-then-activate flow itself.
    """
    if ruleset_version_id is None:
        world_id = connection.execute(
            text("SELECT world_id FROM campaign.timelines WHERE timeline_id = :t"),
            {"t": timeline_id},
        ).scalar()
        existing_ruleset_id = connection.execute(
            text("SELECT ruleset_id FROM rules.world_rulesets WHERE world_id = :w LIMIT 1"),
            {"w": world_id},
        ).scalar()
        if existing_ruleset_id is None:
            existing_ruleset_id = make_ruleset_for_world(connection, world_id)
        ruleset_version_id = connection.execute(
            text(
                "SELECT ruleset_version_id FROM rules.ruleset_versions "
                "WHERE ruleset_id = :r AND is_current"
            ),
            {"r": existing_ruleset_id},
        ).scalar()

    value = connection.execute(
        text("""
            INSERT INTO campaign.campaigns
                (timeline_id, name, lifecycle_status_id, ruleset_version_id)
            VALUES (:tl, :n, :status, :ruleset_version)
            RETURNING campaign_id
        """),
        {
            "tl": timeline_id,
            "n": name,
            "status": status_id(connection, "lifecycle_statuses", lifecycle_status_code),
            "ruleset_version": ruleset_version_id,
        },
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_session(
    connection: Connection,
    campaign_id: uuid.UUID,
    session_number: int,
    *,
    start_world_time_id: uuid.UUID | None = None,
    end_world_time_id: uuid.UUID | None = None,
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO campaign.sessions
                (campaign_id, session_number, lifecycle_status_id,
                 start_world_time_id, end_world_time_id)
            VALUES (:c, :n, :status, :start, :end)
            RETURNING session_id
        """),
        {
            "c": campaign_id,
            "n": session_number,
            "status": status_id(connection, "lifecycle_statuses", "active"),
            "start": start_world_time_id,
            "end": end_world_time_id,
        },
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_location(
    connection: Connection,
    world_id: uuid.UUID,
    *,
    parent_location_id: uuid.UUID | None = None,
    entity_type_code: str = "location",
    name: str = "Test Location",
) -> uuid.UUID:
    """A core.entities row plus its world.locations row. Returns the shared
    UUID (the location_id, same as the entity_id).

    entity_type_code defaults to the bare 'location' type; pass 'settlement',
    'building', 'dungeon', or 'dungeon_area' when the caller also needs to
    insert the corresponding subtype row — core.enforce_entity_subtype()
    rejects that subtype row otherwise.
    """
    location_type_id = lookup_id(
        connection, "core", "entity_types", "entity_type_id", entity_type_code
    )
    location_id = make_entity(connection, world_id, location_type_id, name=name)
    connection.execute(
        text("""
            INSERT INTO world.locations (location_id, parent_location_id)
            VALUES (:l, :p)
        """),
        {"l": location_id, "p": parent_location_id},
    )
    return location_id


def make_dungeon(
    connection: Connection,
    world_id: uuid.UUID,
    *,
    parent_location_id: uuid.UUID | None = None,
    name: str = "Test Dungeon",
) -> uuid.UUID:
    """A location plus its world.dungeons row. Returns the shared UUID."""
    dungeon_id = make_location(
        connection,
        world_id,
        parent_location_id=parent_location_id,
        entity_type_code="dungeon",
        name=name,
    )
    connection.execute(
        text("INSERT INTO world.dungeons (dungeon_id) VALUES (:d)"), {"d": dungeon_id}
    )
    return dungeon_id


def make_dungeon_area(
    connection: Connection,
    dungeon_id: uuid.UUID,
    *,
    name: str = "Test Area",
) -> uuid.UUID:
    """A dungeon area belonging to the given dungeon. Returns the shared UUID.

    world_id is derived from the dungeon's own entity row.
    """
    world_id = connection.execute(
        text("SELECT world_id FROM core.entities WHERE entity_id = :d"), {"d": dungeon_id}
    ).scalar()
    assert isinstance(world_id, uuid.UUID)
    area_id = make_location(
        connection,
        world_id,
        parent_location_id=dungeon_id,
        entity_type_code="dungeon_area",
        name=name,
    )
    connection.execute(
        text("INSERT INTO world.dungeon_areas (dungeon_area_id) VALUES (:a)"), {"a": area_id}
    )
    return area_id


def make_area_connection(
    connection: Connection,
    from_dungeon_area_id: uuid.UUID,
    to_dungeon_area_id: uuid.UUID,
    *,
    connection_type_code: str = "door",
    is_hidden: bool = False,
    is_one_way: bool = False,
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO world.area_connections
                (from_dungeon_area_id, to_dungeon_area_id, connection_type_id, is_hidden,
                 is_one_way)
            VALUES (:f, :t, :ct, :hidden, :one_way)
            RETURNING area_connection_id
        """),
        {
            "f": from_dungeon_area_id,
            "t": to_dungeon_area_id,
            "ct": lookup_id(
                connection,
                "world",
                "connection_types",
                "connection_type_id",
                connection_type_code,
            ),
            "hidden": is_hidden,
            "one_way": is_one_way,
        },
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_area_feature(
    connection: Connection, dungeon_area_id: uuid.UUID, *, is_hidden: bool = False
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO world.area_features (dungeon_area_id, feature_type, is_hidden)
            VALUES (:a, 'statue', :hidden)
            RETURNING area_feature_id
        """),
        {"a": dungeon_area_id, "hidden": is_hidden},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_area_hazard(
    connection: Connection, dungeon_area_id: uuid.UUID, *, is_hidden: bool = False
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO world.area_hazards (dungeon_area_id, hazard_type, is_hidden)
            VALUES (:a, 'trap', :hidden)
            RETURNING area_hazard_id
        """),
        {"a": dungeon_area_id, "hidden": is_hidden},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_area_interactable(
    connection: Connection, dungeon_area_id: uuid.UUID, *, is_hidden: bool = False
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO world.area_interactables (dungeon_area_id, interactable_type, is_hidden)
            VALUES (:a, 'lever', :hidden)
            RETURNING area_interactable_id
        """),
        {"a": dungeon_area_id, "hidden": is_hidden},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_knowledge_item(
    connection: Connection,
    world_id: uuid.UUID,
    *,
    knowledge_type_code: str = "secret",
    truth_status_code: str = "true",
    statement: str = "There is a secret door here.",
    subject_area_connection_id: uuid.UUID | None = None,
    subject_area_feature_id: uuid.UUID | None = None,
    subject_area_hazard_id: uuid.UUID | None = None,
    subject_area_interactable_id: uuid.UUID | None = None,
    subject_entity_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """A core.entities row plus its knowledge.knowledge_items row. Returns
    the shared UUID (the knowledge_item_id, same as the entity_id)."""
    knowledge_item_type_id = lookup_id(
        connection, "core", "entity_types", "entity_type_id", "knowledge_item"
    )
    knowledge_item_id = make_entity(connection, world_id, knowledge_item_type_id, name=statement)
    connection.execute(
        text("""
            INSERT INTO knowledge.knowledge_items
                (knowledge_item_id, knowledge_type_id, truth_status_id, canonical_statement,
                 subject_entity_id, subject_area_connection_id, subject_area_feature_id,
                 subject_area_hazard_id, subject_area_interactable_id)
            VALUES (
                :id,
                (SELECT knowledge_type_id FROM knowledge.knowledge_types WHERE code = :kt),
                (SELECT truth_status_id FROM knowledge.truth_statuses WHERE code = :ts),
                :statement, :subject_entity, :subject_connection, :subject_feature,
                :subject_hazard, :subject_interactable
            )
        """),
        {
            "id": knowledge_item_id,
            "kt": knowledge_type_code,
            "ts": truth_status_code,
            "statement": statement,
            "subject_entity": subject_entity_id,
            "subject_connection": subject_area_connection_id,
            "subject_feature": subject_area_feature_id,
            "subject_hazard": subject_area_hazard_id,
            "subject_interactable": subject_area_interactable_id,
        },
    )
    return knowledge_item_id


def make_event(
    connection: Connection,
    world_id: uuid.UUID,
    timeline_id: uuid.UUID,
    world_time_id: uuid.UUID,
    *,
    campaign_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    event_type_code: str = "other",
    event_status_code: str = "recorded",
    details: str | None = None,
    name: str = "Test Event",
) -> uuid.UUID:
    """A core.entities row plus its narrative.events row. Returns the shared
    UUID (the event_id, same as the entity_id).

    world_time_id has no default — callers exercising branch/effective-history
    behavior need explicit control over ordering (sort_key), so guessing one
    here would hide bugs rather than catch them.
    """
    event_entity_type_id = lookup_id(connection, "core", "entity_types", "entity_type_id", "event")
    event_id = make_entity(connection, world_id, event_entity_type_id, name=name)
    connection.execute(
        text("""
            INSERT INTO narrative.events
                (event_id, timeline_id, campaign_id, session_id, event_type_id,
                 event_status_id, world_time_id, details)
            VALUES (
                :id, :timeline, :campaign, :session,
                (SELECT event_type_id FROM narrative.event_types WHERE code = :etc),
                (SELECT event_status_id FROM narrative.event_statuses WHERE code = :esc),
                :world_time, :details
            )
        """),
        {
            "id": event_id,
            "timeline": timeline_id,
            "campaign": campaign_id,
            "session": session_id,
            "etc": event_type_code,
            "esc": event_status_code,
            "world_time": world_time_id,
            "details": details,
        },
    )
    return event_id


def make_interaction(
    connection: Connection,
    timeline_id: uuid.UUID,
    world_time_id: uuid.UUID,
    *,
    campaign_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    interaction_type_code: str = "other",
    status: str = "initiated",
    resulting_event_id: uuid.UUID | None = None,
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO interaction.interactions
                (timeline_id, campaign_id, session_id, interaction_type_id, world_time_id,
                 status, resulting_event_id)
            VALUES (
                :timeline, :campaign, :session,
                (SELECT interaction_type_id FROM interaction.interaction_types WHERE code = :itc),
                :world_time, :status, :resulting_event
            )
            RETURNING interaction_id
        """),
        {
            "timeline": timeline_id,
            "campaign": campaign_id,
            "session": session_id,
            "itc": interaction_type_code,
            "world_time": world_time_id,
            "status": status,
            "resulting_event": resulting_event_id,
        },
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_action(
    connection: Connection,
    interaction_id: uuid.UUID,
    actor_entity_id: uuid.UUID,
    *,
    sequence_number: int = 0,
    description: str | None = None,
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO interaction.actions
                (interaction_id, actor_entity_id, sequence_number, description)
            VALUES (:interaction, :actor, :seq, :description)
            RETURNING action_id
        """),
        {
            "interaction": interaction_id,
            "actor": actor_entity_id,
            "seq": sequence_number,
            "description": description,
        },
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_target(
    connection: Connection,
    action_id: uuid.UUID,
    *,
    target_entity_id: uuid.UUID | None = None,
    target_area_connection_id: uuid.UUID | None = None,
    target_area_feature_id: uuid.UUID | None = None,
    target_area_hazard_id: uuid.UUID | None = None,
    target_area_interactable_id: uuid.UUID | None = None,
    target_component: str | None = None,
    target_description: str | None = None,
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO interaction.targets
                (action_id, target_entity_id, target_area_connection_id, target_area_feature_id,
                 target_area_hazard_id, target_area_interactable_id, target_component,
                 target_description)
            VALUES (:action, :entity, :connection, :feature, :hazard, :interactable, :component,
                    :description)
            RETURNING target_id
        """),
        {
            "action": action_id,
            "entity": target_entity_id,
            "connection": target_area_connection_id,
            "feature": target_area_feature_id,
            "hazard": target_area_hazard_id,
            "interactable": target_area_interactable_id,
            "component": target_component,
            "description": target_description,
        },
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_check_request(
    connection: Connection,
    action_id: uuid.UUID,
    actor_entity_id: uuid.UUID,
    *,
    check_kind: str = "ability_check",
    ability_id: uuid.UUID | None = None,
    skill_id: uuid.UUID | None = None,
    difficulty: int = 10,
    advantage_state: str = "normal",
    stakes: str | None = None,
    target_id: uuid.UUID | None = None,
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO interaction.check_requests
                (action_id, actor_entity_id, check_kind, ability_id, skill_id, difficulty,
                 advantage_state, stakes, target_id)
            VALUES (:action, :actor, :kind, :ability, :skill, :difficulty, :advantage, :stakes,
                    :target)
            RETURNING check_request_id
        """),
        {
            "action": action_id,
            "actor": actor_entity_id,
            "kind": check_kind,
            "ability": ability_id,
            "skill": skill_id,
            "difficulty": difficulty,
            "advantage": advantage_state,
            "stakes": stakes,
            "target": target_id,
        },
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_check_result(
    connection: Connection,
    check_request_id: uuid.UUID,
    *,
    roll: int | None = None,
    total_modifier: int | None = None,
    total: int | None = None,
    degree_of_success: str = "success",
    is_visible_to_players: bool = True,
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO interaction.check_results
                (check_request_id, roll, total_modifier, total, degree_of_success,
                 is_visible_to_players)
            VALUES (:request, :roll, :total_modifier, :total, :degree, :visible)
            RETURNING check_result_id
        """),
        {
            "request": check_request_id,
            "roll": roll,
            "total_modifier": total_modifier,
            "total": total,
            "degree": degree_of_success,
            "visible": is_visible_to_players,
        },
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_consequence(
    connection: Connection,
    interaction_id: uuid.UUID,
    *,
    consequence_type: str = "observation",
    status: str = "proposed",
    resulting_event_id: uuid.UUID | None = None,
    resulting_party_discovery_id: uuid.UUID | None = None,
    resulting_quest_objective_state_id: uuid.UUID | None = None,
    resulting_relationship_state_id: uuid.UUID | None = None,
    description: str | None = None,
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO interaction.consequences
                (interaction_id, consequence_type, status, resulting_event_id,
                 resulting_party_discovery_id, resulting_quest_objective_state_id,
                 resulting_relationship_state_id, description)
            VALUES (:interaction, :type, :status, :event, :discovery, :objective_state,
                    :relationship_state, :description)
            RETURNING consequence_id
        """),
        {
            "interaction": interaction_id,
            "type": consequence_type,
            "status": status,
            "event": resulting_event_id,
            "discovery": resulting_party_discovery_id,
            "objective_state": resulting_quest_objective_state_id,
            "relationship_state": resulting_relationship_state_id,
            "description": description,
        },
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_event_effect(
    connection: Connection,
    event_id: uuid.UUID,
    *,
    target_entity_id: uuid.UUID | None = None,
    target_quest_objective_id: uuid.UUID | None = None,
    target_relationship_id: uuid.UUID | None = None,
    target_component: str = "status",
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO narrative.event_effects
                (event_id, target_entity_id, target_quest_objective_id, target_relationship_id,
                 target_component)
            VALUES (:event, :entity, :objective, :relationship, :component)
            RETURNING event_effect_id
        """),
        {
            "event": event_id,
            "entity": target_entity_id,
            "objective": target_quest_objective_id,
            "relationship": target_relationship_id,
            "component": target_component,
        },
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_world_entity(connection: Connection, slug: str) -> uuid.UUID:
    """A world plus a throwaway entity type plus one entity, for tests that need
    an entity but do not care about its world or type."""
    world = make_world(connection, slug=slug)
    entity_type = make_entity_type(connection, f"{slug.replace('-', '_')}_type")
    return make_entity(connection, world, entity_type)


def make_story_arc(
    connection: Connection,
    world_id: uuid.UUID,
    *,
    name: str = "Test Story Arc",
    status: str = "active",
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO narrative.story_arcs (world_id, name, status)
            VALUES (:world, :name, :status)
            RETURNING story_arc_id
        """),
        {"world": world_id, "name": name, "status": status},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_quest(
    connection: Connection,
    world_id: uuid.UUID,
    *,
    story_arc_id: uuid.UUID | None = None,
    name: str = "Test Quest",
) -> uuid.UUID:
    """A core.entities row plus its narrative.quests row. Returns the shared
    UUID (the quest_id, same as the entity_id)."""
    quest_type_id = lookup_id(connection, "core", "entity_types", "entity_type_id", "quest")
    quest_id = make_entity(connection, world_id, quest_type_id, name=name)
    connection.execute(
        text("""
            INSERT INTO narrative.quests (quest_id, story_arc_id)
            VALUES (:id, :arc)
        """),
        {"id": quest_id, "arc": story_arc_id},
    )
    return quest_id


def make_quest_stage(
    connection: Connection,
    quest_id: uuid.UUID,
    *,
    name: str = "Test Stage",
    sequence_number: int = 0,
    stage_type: str = "sequential",
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO narrative.quest_stages (quest_id, name, sequence_number, stage_type)
            VALUES (:quest, :name, :seq, :type)
            RETURNING quest_stage_id
        """),
        {"quest": quest_id, "name": name, "seq": sequence_number, "type": stage_type},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_quest_objective(
    connection: Connection,
    quest_stage_id: uuid.UUID,
    *,
    objective_type_code: str = "other",
    name: str = "Test Objective",
    requirement_level: str = "required",
    completion_mode: str = "automatic",
    completion_rule: dict[str, object] | None = None,
    visibility_policy: str = "visible",
    target_entity_id: uuid.UUID | None = None,
    target_area_connection_id: uuid.UUID | None = None,
    target_area_feature_id: uuid.UUID | None = None,
    target_area_hazard_id: uuid.UUID | None = None,
    target_area_interactable_id: uuid.UUID | None = None,
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO narrative.quest_objectives
                (quest_stage_id, objective_type_id, name, requirement_level, completion_mode,
                 completion_rule, visibility_policy, target_entity_id, target_area_connection_id,
                 target_area_feature_id, target_area_hazard_id, target_area_interactable_id)
            VALUES (
                :stage,
                (SELECT objective_type_id FROM narrative.objective_types WHERE code = :otc),
                :name, :requirement, :completion, :completion_rule, :visibility,
                :entity, :connection, :feature, :hazard, :interactable
            )
            RETURNING quest_objective_id
        """),
        {
            "stage": quest_stage_id,
            "otc": objective_type_code,
            "name": name,
            "requirement": requirement_level,
            "completion": completion_mode,
            "completion_rule": json.dumps(completion_rule) if completion_rule is not None else None,
            "visibility": visibility_policy,
            "entity": target_entity_id,
            "connection": target_area_connection_id,
            "feature": target_area_feature_id,
            "hazard": target_area_hazard_id,
            "interactable": target_area_interactable_id,
        },
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_objective_dependency(
    connection: Connection,
    objective_id: uuid.UUID,
    depends_on_objective_id: uuid.UUID,
    *,
    dependency_type: str = "prerequisite",
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO narrative.objective_dependencies
                (objective_id, depends_on_objective_id, dependency_type)
            VALUES (:objective, :depends_on, :type)
            RETURNING objective_dependency_id
        """),
        {"objective": objective_id, "depends_on": depends_on_objective_id, "type": dependency_type},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_quest_participant(
    connection: Connection,
    quest_id: uuid.UUID,
    participant_entity_id: uuid.UUID,
    *,
    participant_role: str = "involved",
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO narrative.quest_participants
                (quest_id, participant_entity_id, participant_role)
            VALUES (:quest, :participant, :role)
            RETURNING quest_participant_id
        """),
        {"quest": quest_id, "participant": participant_entity_id, "role": participant_role},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_quest_outcome(
    connection: Connection,
    quest_id: uuid.UUID,
    *,
    code: str = "success",
    name: str = "Success",
    outcome_category: str = "success",
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO narrative.quest_outcomes (quest_id, code, name, outcome_category)
            VALUES (:quest, :code, :name, :category)
            RETURNING quest_outcome_id
        """),
        {"quest": quest_id, "code": code, "name": name, "category": outcome_category},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_quest_state(
    connection: Connection,
    timeline_id: uuid.UUID,
    quest_id: uuid.UUID,
    *,
    party_id: uuid.UUID | None = None,
    status_code: str = "active",
    last_event_id: uuid.UUID | None = None,
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO campaign.quest_state
                (timeline_id, quest_id, party_id, quest_status_id, last_event_id)
            VALUES (
                :timeline, :quest, :party,
                (SELECT quest_status_id FROM campaign.quest_statuses WHERE code = :status),
                :event
            )
            RETURNING quest_state_id
        """),
        {
            "timeline": timeline_id,
            "quest": quest_id,
            "party": party_id,
            "status": status_code,
            "event": last_event_id,
        },
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_objective_state(
    connection: Connection,
    timeline_id: uuid.UUID,
    quest_objective_id: uuid.UUID,
    *,
    party_id: uuid.UUID | None = None,
    status_code: str = "active",
    last_event_id: uuid.UUID | None = None,
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO campaign.objective_state
                (timeline_id, quest_objective_id, party_id, objective_status_id, last_event_id)
            VALUES (
                :timeline, :objective, :party,
                (SELECT objective_status_id FROM campaign.objective_statuses WHERE code = :status),
                :event
            )
            RETURNING objective_state_id
        """),
        {
            "timeline": timeline_id,
            "objective": quest_objective_id,
            "party": party_id,
            "status": status_code,
            "event": last_event_id,
        },
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_knowledge_version(
    connection: Connection,
    knowledge_item_id: uuid.UUID,
    *,
    version_statement: str = "A distorted retelling.",
    distortion_type: str = "embellishment",
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO knowledge.knowledge_versions
                (knowledge_item_id, version_statement, distortion_type)
            VALUES (:item, :statement, :distortion)
            RETURNING knowledge_version_id
        """),
        {"item": knowledge_item_id, "statement": version_statement, "distortion": distortion_type},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_party_knowledge(
    connection: Connection,
    timeline_id: uuid.UUID,
    party_id: uuid.UUID,
    knowledge_item_id: uuid.UUID,
    *,
    knowledge_version_id: uuid.UUID | None = None,
    awareness_level: str = "aware",
    confidence: int | None = None,
    interpretation: str | None = None,
    willing_to_share: bool = True,
    last_event_id: uuid.UUID | None = None,
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO campaign.party_knowledge
                (timeline_id, party_id, knowledge_item_id, knowledge_version_id, awareness_level,
                 confidence, interpretation, willing_to_share, last_event_id)
            VALUES (:timeline, :party, :item, :version, :awareness, :confidence, :interpretation,
                    :share, :event)
            RETURNING party_knowledge_id
        """),
        {
            "timeline": timeline_id,
            "party": party_id,
            "item": knowledge_item_id,
            "version": knowledge_version_id,
            "awareness": awareness_level,
            "confidence": confidence,
            "interpretation": interpretation,
            "share": willing_to_share,
            "event": last_event_id,
        },
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_party_discovery(
    connection: Connection,
    timeline_id: uuid.UUID,
    knowledge_item_id: uuid.UUID,
    *,
    party_id: uuid.UUID | None = None,
    knower_entity_id: uuid.UUID | None = None,
    discovered_via_interaction_id: uuid.UUID | None = None,
    discovered_via_event_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """A `knowledge.party_discoveries` row — the discovery record used to
    reveal a hidden dungeon feature/hazard/interactable/connection to
    `dnd_ai.queries.dungeon.get_dungeon_area_view` (docs/architecture/
    DATABASE_MODEL.md §9.3, §15). Exactly one of party_id/knower_entity_id
    must be supplied, mirroring the table's own check constraint; at most
    one of discovered_via_interaction_id/discovered_via_event_id may be
    supplied (revision 063), and both may be omitted (an ambient/unrecorded
    discovery)."""
    value = connection.execute(
        text("""
            INSERT INTO knowledge.party_discoveries
                (timeline_id, knowledge_item_id, party_id, knower_entity_id,
                 discovered_via_interaction_id, discovered_via_event_id)
            VALUES (:timeline, :item, :party, :knower, :via_interaction, :via_event)
            RETURNING party_discovery_id
        """),
        {
            "timeline": timeline_id,
            "item": knowledge_item_id,
            "party": party_id,
            "knower": knower_entity_id,
            "via_interaction": discovered_via_interaction_id,
            "via_event": discovered_via_event_id,
        },
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_relationship(
    connection: Connection,
    world_id: uuid.UUID,
    *,
    relationship_type_code: str = "alliance",
    description: str | None = None,
    started_world_time_id: uuid.UUID | None = None,
    ended_world_time_id: uuid.UUID | None = None,
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO world.relationships
                (world_id, relationship_type_id, description, started_world_time_id,
                 ended_world_time_id)
            VALUES (
                :world,
                (SELECT relationship_type_id FROM world.relationship_types WHERE code = :rtc),
                :description, :started, :ended
            )
            RETURNING relationship_id
        """),
        {
            "world": world_id,
            "rtc": relationship_type_code,
            "description": description,
            "started": started_world_time_id,
            "ended": ended_world_time_id,
        },
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_relationship_participant(
    connection: Connection,
    relationship_id: uuid.UUID,
    entity_id: uuid.UUID,
    *,
    role_code: str = "subject",
    notes: str | None = None,
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO world.relationship_participants
                (relationship_id, entity_id, participant_role_id, notes)
            VALUES (
                :relationship, :entity,
                (SELECT relationship_participant_role_id FROM world.relationship_participant_roles
                 WHERE code = :rc),
                :notes
            )
            RETURNING relationship_participant_id
        """),
        {"relationship": relationship_id, "entity": entity_id, "rc": role_code, "notes": notes},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_relationship_perspective(
    connection: Connection,
    relationship_id: uuid.UUID,
    perspective_holder_entity_id: uuid.UUID,
    *,
    affinity: int | None = None,
    trust: int | None = None,
    respect: int | None = None,
    fear: int | None = None,
    obligation: int | None = None,
    emotional_tone: str | None = None,
    private_interpretation: str | None = None,
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO world.relationship_perspectives
                (relationship_id, perspective_holder_entity_id, affinity, trust, respect, fear,
                 obligation, emotional_tone, private_interpretation)
            VALUES (:relationship, :holder, :affinity, :trust, :respect, :fear, :obligation, :tone,
                    :interpretation)
            RETURNING relationship_perspective_id
        """),
        {
            "relationship": relationship_id,
            "holder": perspective_holder_entity_id,
            "affinity": affinity,
            "trust": trust,
            "respect": respect,
            "fear": fear,
            "obligation": obligation,
            "tone": emotional_tone,
            "interpretation": private_interpretation,
        },
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


_ORGANIZATION_CTI_ENTITY_TYPES = frozenset(
    {"business", "government", "religious_organization", "military_unit", "political_faction"}
)


def make_organization(
    connection: Connection,
    world_id: uuid.UUID,
    *,
    organization_type_code: str = "guild",
    name: str = "Test Organization",
    parent_organization_id: uuid.UUID | None = None,
    headquarters_location_id: uuid.UUID | None = None,
    founded_world_time_id: uuid.UUID | None = None,
    dissolved_world_time_id: uuid.UUID | None = None,
    public_description: str | None = None,
    internal_description: str | None = None,
) -> uuid.UUID:
    """A core.entities row plus its world.organizations row. Returns the
    shared UUID (the organization_id, same as the entity_id).

    organization_type_code sets world.organizations.organization_type_id (the
    descriptive lookup) always. When it names one of the five subtypes with
    its own CTI leaf table (business/government/religious_organization/
    military_unit/political_faction), core.entities.entity_type_id is set to
    that same code too, so a caller can immediately follow up with
    make_business()/make_government()/etc. without core.enforce_entity_
    subtype() rejecting it — the same two-tier scheme
    docs/architecture/DATABASE_MODEL.md §10.3 describes. Any other code
    (guild, criminal_organization, secret_society, other) gets the bare
    'organization' entity type, since none of those has a CTI leaf table.
    """
    entity_type_code = (
        organization_type_code
        if organization_type_code in _ORGANIZATION_CTI_ENTITY_TYPES
        else "organization"
    )
    entity_type_id = lookup_id(
        connection, "core", "entity_types", "entity_type_id", entity_type_code
    )
    organization_id = make_entity(connection, world_id, entity_type_id, name=name)
    connection.execute(
        text("""
            INSERT INTO world.organizations
                (organization_id, organization_type_id, parent_organization_id,
                 founded_world_time_id, dissolved_world_time_id, headquarters_location_id,
                 public_description, internal_description)
            VALUES (
                :id,
                (SELECT organization_type_id FROM world.organization_types WHERE code = :otc),
                :parent, :founded, :dissolved, :hq, :public_desc, :internal_desc
            )
        """),
        {
            "id": organization_id,
            "otc": organization_type_code,
            "parent": parent_organization_id,
            "founded": founded_world_time_id,
            "dissolved": dissolved_world_time_id,
            "hq": headquarters_location_id,
            "public_desc": public_description,
            "internal_desc": internal_description,
        },
    )
    return organization_id


def make_business(
    connection: Connection,
    organization_id: uuid.UUID,
    *,
    business_type: str | None = None,
    operating_status: str = "operating",
    reputation: int | None = None,
) -> uuid.UUID:
    connection.execute(
        text("""
            INSERT INTO world.businesses (business_id, business_type, operating_status, reputation)
            VALUES (:id, :type, :status, :reputation)
        """),
        {
            "id": organization_id,
            "type": business_type,
            "status": operating_status,
            "reputation": reputation,
        },
    )
    return organization_id


def make_government(
    connection: Connection, organization_id: uuid.UUID, *, government_form: str | None = None
) -> uuid.UUID:
    connection.execute(
        text("INSERT INTO world.governments (government_id, government_form) VALUES (:id, :form)"),
        {"id": organization_id, "form": government_form},
    )
    return organization_id


def make_military_unit(
    connection: Connection, organization_id: uuid.UUID, *, unit_type: str | None = None
) -> uuid.UUID:
    connection.execute(
        text("INSERT INTO world.military_units (military_unit_id, unit_type) VALUES (:id, :type)"),
        {"id": organization_id, "type": unit_type},
    )
    return organization_id


def make_political_faction(
    connection: Connection, organization_id: uuid.UUID, *, ideology: str | None = None
) -> uuid.UUID:
    connection.execute(
        text(
            "INSERT INTO world.political_factions (political_faction_id, ideology) "
            "VALUES (:id, :ideology)"
        ),
        {"id": organization_id, "ideology": ideology},
    )
    return organization_id


def make_religion(
    connection: Connection,
    world_id: uuid.UUID,
    *,
    name: str = "Test Religion",
    pantheon_structure: str | None = None,
) -> uuid.UUID:
    """A core.entities row plus its world.religions row. Returns the shared
    UUID (the religion_id, same as the entity_id)."""
    entity_type_id = lookup_id(connection, "core", "entity_types", "entity_type_id", "religion")
    religion_id = make_entity(connection, world_id, entity_type_id, name=name)
    connection.execute(
        text(
            "INSERT INTO world.religions (religion_id, pantheon_structure) VALUES (:id, :structure)"
        ),
        {"id": religion_id, "structure": pantheon_structure},
    )
    return religion_id


def make_religious_organization(
    connection: Connection, organization_id: uuid.UUID, religion_id: uuid.UUID
) -> uuid.UUID:
    connection.execute(
        text(
            "INSERT INTO world.religious_organizations (religious_organization_id, religion_id) "
            "VALUES (:id, :religion)"
        ),
        {"id": organization_id, "religion": religion_id},
    )
    return organization_id


def make_character_religious_affiliation(
    connection: Connection,
    character_id: uuid.UUID,
    religion_id: uuid.UUID,
    *,
    devotion: int | None = None,
    belief_status: str = "believer",
    practice: str | None = None,
    interpretation: str | None = None,
    conflicts: str | None = None,
    public_display: bool = True,
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO character.character_religious_affiliations
                (character_id, religion_id, devotion, belief_status, practice, interpretation,
                 conflicts, public_display)
            VALUES (:character, :religion, :devotion, :belief, :practice, :interpretation,
                    :conflicts, :public)
            RETURNING character_religious_affiliation_id
        """),
        {
            "character": character_id,
            "religion": religion_id,
            "devotion": devotion,
            "belief": belief_status,
            "practice": practice,
            "interpretation": interpretation,
            "conflicts": conflicts,
            "public": public_display,
        },
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_organization_membership(
    connection: Connection,
    relationship_id: uuid.UUID,
    organization_id: uuid.UUID,
    member_entity_id: uuid.UUID,
    effective_from_world_time_id: uuid.UUID,
    *,
    effective_to_world_time_id: uuid.UUID | None = None,
    role: str | None = None,
    rank: str | None = None,
    is_public: bool = True,
) -> uuid.UUID:
    connection.execute(
        text("""
            INSERT INTO world.organization_memberships
                (relationship_id, organization_id, member_entity_id, role, rank, is_public,
                 effective_from_world_time_id, effective_to_world_time_id)
            VALUES (:relationship, :organization, :member, :role, :rank, :public, :from_time, :to_time)
        """),
        {
            "relationship": relationship_id,
            "organization": organization_id,
            "member": member_entity_id,
            "role": role,
            "rank": rank,
            "public": is_public,
            "from_time": effective_from_world_time_id,
            "to_time": effective_to_world_time_id,
        },
    )
    return relationship_id


def make_employment_relationship(
    connection: Connection,
    relationship_id: uuid.UUID,
    employer_entity_id: uuid.UUID,
    employee_entity_id: uuid.UUID,
    *,
    job_title: str | None = None,
    effective_from_world_time_id: uuid.UUID | None = None,
    effective_to_world_time_id: uuid.UUID | None = None,
) -> uuid.UUID:
    connection.execute(
        text("""
            INSERT INTO world.employment_relationships
                (relationship_id, employer_entity_id, employee_entity_id, job_title,
                 effective_from_world_time_id, effective_to_world_time_id)
            VALUES (:relationship, :employer, :employee, :title, :from_time, :to_time)
        """),
        {
            "relationship": relationship_id,
            "employer": employer_entity_id,
            "employee": employee_entity_id,
            "title": job_title,
            "from_time": effective_from_world_time_id,
            "to_time": effective_to_world_time_id,
        },
    )
    return relationship_id


def make_ownership_relationship(
    connection: Connection,
    relationship_id: uuid.UUID,
    owner_entity_id: uuid.UUID,
    owned_entity_id: uuid.UUID,
    *,
    ownership_share: int | None = None,
    is_public: bool = True,
) -> uuid.UUID:
    connection.execute(
        text("""
            INSERT INTO world.ownership_relationships
                (relationship_id, owner_entity_id, owned_entity_id, ownership_share, is_public)
            VALUES (:relationship, :owner, :owned, :share, :public)
        """),
        {
            "relationship": relationship_id,
            "owner": owner_entity_id,
            "owned": owned_entity_id,
            "share": ownership_share,
            "public": is_public,
        },
    )
    return relationship_id


def make_family_relationship(
    connection: Connection, relationship_id: uuid.UUID, *, family_unit_name: str | None = None
) -> uuid.UUID:
    connection.execute(
        text(
            "INSERT INTO world.family_relationships (relationship_id, family_unit_name) "
            "VALUES (:id, :name)"
        ),
        {"id": relationship_id, "name": family_unit_name},
    )
    return relationship_id


def make_political_relationship(
    connection: Connection,
    relationship_id: uuid.UUID,
    *,
    is_active: bool = True,
    treaty_terms: str | None = None,
) -> uuid.UUID:
    connection.execute(
        text("""
            INSERT INTO world.political_relationships (relationship_id, is_active, treaty_terms)
            VALUES (:id, :active, :terms)
        """),
        {"id": relationship_id, "active": is_active, "terms": treaty_terms},
    )
    return relationship_id


def make_organization_state(
    connection: Connection,
    timeline_id: uuid.UUID,
    organization_id: uuid.UUID,
    *,
    status_code: str = "active",
    last_event_id: uuid.UUID | None = None,
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO campaign.organization_state
                (timeline_id, organization_id, organization_status_id, last_event_id)
            VALUES (
                :timeline, :organization,
                (SELECT organization_status_id FROM campaign.organization_statuses
                 WHERE code = :status),
                :event
            )
            RETURNING organization_state_id
        """),
        {
            "timeline": timeline_id,
            "organization": organization_id,
            "status": status_code,
            "event": last_event_id,
        },
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_relationship_state(
    connection: Connection,
    timeline_id: uuid.UUID,
    relationship_id: uuid.UUID,
    *,
    perspective_holder_entity_id: uuid.UUID | None = None,
    status_code: str = "active",
    affinity: int | None = None,
    trust: int | None = None,
    respect: int | None = None,
    fear: int | None = None,
    obligation: int | None = None,
    emotional_tone: str | None = None,
    private_interpretation: str | None = None,
    last_event_id: uuid.UUID | None = None,
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO campaign.relationship_state
                (timeline_id, relationship_id, perspective_holder_entity_id, relationship_status_id,
                 affinity, trust, respect, fear, obligation, emotional_tone, private_interpretation,
                 last_event_id)
            VALUES (
                :timeline, :relationship, :holder,
                (SELECT relationship_status_id FROM campaign.relationship_statuses WHERE code = :status),
                :affinity, :trust, :respect, :fear, :obligation, :tone, :interpretation, :event
            )
            RETURNING relationship_state_id
        """),
        {
            "timeline": timeline_id,
            "relationship": relationship_id,
            "holder": perspective_holder_entity_id,
            "status": status_code,
            "affinity": affinity,
            "trust": trust,
            "respect": respect,
            "fear": fear,
            "obligation": obligation,
            "tone": emotional_tone,
            "interpretation": private_interpretation,
            "event": last_event_id,
        },
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_item_category(connection: Connection, code: str = "wondrous_item") -> uuid.UUID:
    value = connection.execute(
        text("SELECT item_category_id FROM rules.item_categories WHERE code = :c"), {"c": code}
    ).scalar()
    assert isinstance(value, uuid.UUID), f"seeded rules.item_categories row {code!r} missing"
    return value


def make_item_definition(
    connection: Connection,
    ruleset_version_id: uuid.UUID,
    *,
    item_category_code: str = "wondrous_item",
    code: str | None = None,
    display_name: str = "Test Item",
    rarity: str = "common",
    requires_attunement: bool = False,
    weight: float | None = None,
    base_cost_gp: float | None = None,
    properties: dict[str, object] | None = None,
) -> uuid.UUID:
    if code is None:
        code = f"item_{uuid.uuid4().hex[:8]}"
    value = connection.execute(
        text("""
            INSERT INTO rules.item_definitions
                (ruleset_version_id, item_category_id, code, display_name, rarity,
                 requires_attunement, weight, base_cost_gp, properties_jsonb)
            VALUES (:version, :category, :code, :name, :rarity, :attunement, :weight, :cost,
                    :properties)
            RETURNING item_definition_id
        """),
        {
            "version": ruleset_version_id,
            "category": make_item_category(connection, item_category_code),
            "code": code,
            "name": display_name,
            "rarity": rarity,
            "attunement": requires_attunement,
            "weight": weight,
            "cost": base_cost_gp,
            "properties": json.dumps(properties) if properties is not None else None,
        },
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_item_instance(
    connection: Connection,
    world_id: uuid.UUID,
    item_definition_id: uuid.UUID,
    *,
    name: str = "Test Item Instance",
    origin_notes: str | None = None,
) -> uuid.UUID:
    """A core.entities row plus its world.item_instances row. Returns the
    shared UUID (the item_instance_id, same as the entity_id)."""
    entity_type_id = lookup_id(
        connection, "core", "entity_types", "entity_type_id", "item_instance"
    )
    item_instance_id = make_entity(connection, world_id, entity_type_id, name=name)
    connection.execute(
        text("""
            INSERT INTO world.item_instances (item_instance_id, item_definition_id, origin_notes)
            VALUES (:id, :definition, :notes)
        """),
        {"id": item_instance_id, "definition": item_definition_id, "notes": origin_notes},
    )
    return item_instance_id


def make_item_container(
    connection: Connection,
    item_instance_id: uuid.UUID,
    *,
    capacity_weight: float | None = None,
    capacity_items: int | None = None,
) -> uuid.UUID:
    connection.execute(
        text("""
            INSERT INTO world.item_containers (container_id, capacity_weight, capacity_items)
            VALUES (:id, :weight, :items)
        """),
        {"id": item_instance_id, "weight": capacity_weight, "items": capacity_items},
    )
    return item_instance_id


def make_item_state(
    connection: Connection,
    timeline_id: uuid.UUID,
    item_instance_id: uuid.UUID,
    *,
    quantity: int = 1,
    condition_percentage: int | None = None,
    charges_current: int | None = None,
    charges_maximum: int | None = None,
    is_equipped: bool = False,
    is_destroyed: bool = False,
    last_event_id: uuid.UUID | None = None,
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO campaign.item_state
                (timeline_id, item_instance_id, quantity, condition_percentage,
                 charges_current, charges_maximum, is_equipped, is_destroyed, last_event_id)
            VALUES (:timeline, :item, :quantity, :condition, :charges_cur, :charges_max,
                    :equipped, :destroyed, :event)
            RETURNING item_state_id
        """),
        {
            "timeline": timeline_id,
            "item": item_instance_id,
            "quantity": quantity,
            "condition": condition_percentage,
            "charges_cur": charges_current,
            "charges_max": charges_maximum,
            "equipped": is_equipped,
            "destroyed": is_destroyed,
            "event": last_event_id,
        },
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_item_ownership(
    connection: Connection,
    timeline_id: uuid.UUID,
    item_instance_id: uuid.UUID,
    *,
    owner_entity_id: uuid.UUID | None = None,
    acquired_world_time_id: uuid.UUID | None = None,
    last_event_id: uuid.UUID | None = None,
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO campaign.item_ownership
                (timeline_id, item_instance_id, owner_entity_id, acquired_world_time_id,
                 last_event_id)
            VALUES (:timeline, :item, :owner, :acquired, :event)
            RETURNING item_ownership_id
        """),
        {
            "timeline": timeline_id,
            "item": item_instance_id,
            "owner": owner_entity_id,
            "acquired": acquired_world_time_id,
            "event": last_event_id,
        },
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_inventory_entry(
    connection: Connection,
    timeline_id: uuid.UUID,
    item_instance_id: uuid.UUID,
    *,
    holder_entity_id: uuid.UUID | None = None,
    container_id: uuid.UUID | None = None,
    location_id: uuid.UUID | None = None,
    last_event_id: uuid.UUID | None = None,
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO campaign.inventory_entries
                (timeline_id, item_instance_id, holder_entity_id, container_id, location_id,
                 last_event_id)
            VALUES (:timeline, :item, :holder, :container, :location, :event)
            RETURNING inventory_entry_id
        """),
        {
            "timeline": timeline_id,
            "item": item_instance_id,
            "holder": holder_entity_id,
            "container": container_id,
            "location": location_id,
            "event": last_event_id,
        },
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_item_attunement(
    connection: Connection,
    timeline_id: uuid.UUID,
    item_instance_id: uuid.UUID,
    character_id: uuid.UUID,
    *,
    attuned_world_time_id: uuid.UUID | None = None,
    broken_world_time_id: uuid.UUID | None = None,
    last_event_id: uuid.UUID | None = None,
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO campaign.item_attunements
                (timeline_id, item_instance_id, character_id, attuned_world_time_id,
                 broken_world_time_id, last_event_id)
            VALUES (:timeline, :item, :character, :attuned, :broken, :event)
            RETURNING item_attunement_id
        """),
        {
            "timeline": timeline_id,
            "item": item_instance_id,
            "character": character_id,
            "attuned": attuned_world_time_id,
            "broken": broken_world_time_id,
            "event": last_event_id,
        },
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_item_identification(
    connection: Connection,
    timeline_id: uuid.UUID,
    item_instance_id: uuid.UUID,
    knower_entity_id: uuid.UUID,
    *,
    identification_level: str = "unidentified",
    known_properties: dict[str, object] | None = None,
    identified_at_world_time_id: uuid.UUID | None = None,
    last_event_id: uuid.UUID | None = None,
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO knowledge.item_identification
                (timeline_id, item_instance_id, knower_entity_id, identification_level,
                 known_properties_jsonb, identified_at_world_time_id, last_event_id)
            VALUES (:timeline, :item, :knower, :level, :properties, :identified_at, :event)
            RETURNING item_identification_id
        """),
        {
            "timeline": timeline_id,
            "item": item_instance_id,
            "knower": knower_entity_id,
            "level": identification_level,
            "properties": json.dumps(known_properties) if known_properties is not None else None,
            "identified_at": identified_at_world_time_id,
            "event": last_event_id,
        },
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_encounter(
    connection: Connection,
    timeline_id: uuid.UUID,
    world_time_id: uuid.UUID,
    *,
    campaign_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    location_id: uuid.UUID | None = None,
    status: str = "pending",
    current_round: int = 0,
    summary: str | None = None,
    resulting_event_id: uuid.UUID | None = None,
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO narrative.encounters
                (timeline_id, campaign_id, session_id, location_id, world_time_id, status,
                 current_round, summary, resulting_event_id)
            VALUES (:timeline, :campaign, :session, :location, :world_time, :status, :round,
                    :summary, :event)
            RETURNING encounter_id
        """),
        {
            "timeline": timeline_id,
            "campaign": campaign_id,
            "session": session_id,
            "location": location_id,
            "world_time": world_time_id,
            "status": status,
            "round": current_round,
            "summary": summary,
            "event": resulting_event_id,
        },
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_encounter_participant(
    connection: Connection,
    encounter_id: uuid.UUID,
    participant_entity_id: uuid.UUID,
    *,
    side: str = "party",
    initiative: int | None = None,
    outcome: str | None = None,
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO narrative.encounter_participants
                (encounter_id, participant_entity_id, side, initiative, outcome)
            VALUES (:encounter, :participant, :side, :initiative, :outcome)
            RETURNING encounter_participant_id
        """),
        {
            "encounter": encounter_id,
            "participant": participant_entity_id,
            "side": side,
            "initiative": initiative,
            "outcome": outcome,
        },
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_encounter_round(
    connection: Connection, encounter_id: uuid.UUID, round_number: int
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO narrative.encounter_rounds (encounter_id, round_number)
            VALUES (:encounter, :round)
            RETURNING encounter_round_id
        """),
        {"encounter": encounter_id, "round": round_number},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_combat_action(
    connection: Connection,
    action_id: uuid.UUID,
    *,
    target_id: uuid.UUID | None = None,
    action_kind: str = "attack",
    item_instance_id: uuid.UUID | None = None,
    spell_id: uuid.UUID | None = None,
    hit: bool | None = None,
    damage_amount: int | None = None,
    damage_type_id: uuid.UUID | None = None,
    resulting_condition_id: uuid.UUID | None = None,
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO interaction.combat_actions
                (action_id, target_id, action_kind, item_instance_id, spell_id, hit,
                 damage_amount, damage_type_id, resulting_condition_id)
            VALUES (:action, :target, :kind, :item, :spell, :hit, :damage, :damage_type,
                    :condition)
            RETURNING combat_action_id
        """),
        {
            "action": action_id,
            "target": target_id,
            "kind": action_kind,
            "item": item_instance_id,
            "spell": spell_id,
            "hit": hit,
            "damage": damage_amount,
            "damage_type": damage_type_id,
            "condition": resulting_condition_id,
        },
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_encounter_turn(
    connection: Connection,
    encounter_round_id: uuid.UUID,
    participant_id: uuid.UUID,
    turn_order: int,
    *,
    combat_action_id: uuid.UUID | None = None,
    notes: str | None = None,
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO narrative.encounter_turns
                (encounter_round_id, participant_id, turn_order, combat_action_id, notes)
            VALUES (:round, :participant, :order, :combat_action, :notes)
            RETURNING encounter_turn_id
        """),
        {
            "round": encounter_round_id,
            "participant": participant_id,
            "order": turn_order,
            "combat_action": combat_action_id,
            "notes": notes,
        },
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_character_state(
    connection: Connection,
    timeline_id: uuid.UUID,
    character_id: uuid.UUID,
    *,
    current_hit_points: int = 10,
    maximum_hit_points: int = 10,
) -> None:
    connection.execute(
        text("""
            INSERT INTO campaign.character_state
                (timeline_id, character_id, current_hit_points, maximum_hit_points)
            VALUES (:timeline, :character, :current, :maximum)
        """),
        {
            "timeline": timeline_id,
            "character": character_id,
            "current": current_hit_points,
            "maximum": maximum_hit_points,
        },
    )


def make_condition(
    connection: Connection, ruleset_version_id: uuid.UUID, code: str = "poisoned"
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO rules.conditions (ruleset_version_id, code, display_name)
            VALUES (:v, :c, :c)
            RETURNING condition_id
        """),
        {"v": ruleset_version_id, "c": code},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_resource_definition(
    connection: Connection, ruleset_version_id: uuid.UUID, code: str = "ki_points"
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO rules.resource_definitions (ruleset_version_id, code, display_name)
            VALUES (:v, :c, :c)
            RETURNING resource_definition_id
        """),
        {"v": ruleset_version_id, "c": code},
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_character_condition(
    connection: Connection,
    timeline_id: uuid.UUID,
    character_id: uuid.UUID,
    condition_id: uuid.UUID,
    *,
    source_description: str | None = None,
) -> None:
    connection.execute(
        text("""
            INSERT INTO campaign.character_conditions
                (timeline_id, character_id, condition_id, source_description)
            VALUES (:timeline, :character, :condition, :source)
        """),
        {
            "timeline": timeline_id,
            "character": character_id,
            "condition": condition_id,
            "source": source_description,
        },
    )


def make_character_resource(
    connection: Connection,
    timeline_id: uuid.UUID,
    character_id: uuid.UUID,
    resource_definition_id: uuid.UUID,
    *,
    current_amount: int = 1,
    maximum_amount: int = 1,
) -> None:
    connection.execute(
        text("""
            INSERT INTO campaign.character_resources
                (timeline_id, character_id, resource_definition_id, current_amount, maximum_amount)
            VALUES (:timeline, :character, :resource, :current, :maximum)
        """),
        {
            "timeline": timeline_id,
            "character": character_id,
            "resource": resource_definition_id,
            "current": current_amount,
            "maximum": maximum_amount,
        },
    )


def make_character_location_history(
    connection: Connection,
    timeline_id: uuid.UUID,
    character_id: uuid.UUID,
    location_id: uuid.UUID,
    arrived_at_world_time_id: uuid.UUID,
    *,
    departed_at_world_time_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """A `campaign.character_location_history` row. Leaving
    `departed_at_world_time_id` unset (the default) produces the character's
    current location — at most one such open row per `(timeline,
    character)`, enforced by a partial unique index (revision 042/043)."""
    value = connection.execute(
        text("""
            INSERT INTO campaign.character_location_history
                (timeline_id, character_id, location_id, arrived_at_world_time_id,
                 departed_at_world_time_id)
            VALUES (:timeline, :character, :location, :arrived, :departed)
            RETURNING character_location_history_id
        """),
        {
            "timeline": timeline_id,
            "character": character_id,
            "location": location_id,
            "arrived": arrived_at_world_time_id,
            "departed": departed_at_world_time_id,
        },
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_external_system(
    connection: Connection,
    world_id: uuid.UUID,
    *,
    system_type: str = "foundry",
    display_name: str = "Test Foundry World",
    external_reference: str | None = None,
    is_active: bool = True,
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO integration.external_systems
                (world_id, system_type, display_name, external_reference, is_active)
            VALUES (:world, :type, :name, :reference, :active)
            RETURNING external_system_id
        """),
        {
            "world": world_id,
            "type": system_type,
            "name": display_name,
            "reference": external_reference,
            "active": is_active,
        },
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_external_identifier(
    connection: Connection,
    external_system_id: uuid.UUID,
    entity_id: uuid.UUID,
    *,
    external_kind: str = "actor",
    external_id: str = "test-external-id",
    last_synced_at: str | None = None,
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO integration.external_identifiers
                (external_system_id, entity_id, external_kind, external_id, last_synced_at)
            VALUES (:system, :entity, :kind, :external, :synced)
            RETURNING external_identifier_id
        """),
        {
            "system": external_system_id,
            "entity": entity_id,
            "kind": external_kind,
            "external": external_id,
            "synced": last_synced_at,
        },
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_sync_job(
    connection: Connection,
    external_system_id: uuid.UUID,
    *,
    direction: str = "inbound",
    job_type: str = "combat_turn",
    target_entity_id: uuid.UUID | None = None,
    target_encounter_id: uuid.UUID | None = None,
    status: str = "pending",
    payload: dict[str, object] | None = None,
    error_message: str | None = None,
    resulting_event_id: uuid.UUID | None = None,
    resulting_encounter_turn_id: uuid.UUID | None = None,
    external_operation_id: str | None = None,
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO integration.sync_jobs
                (external_system_id, direction, job_type, target_entity_id, target_encounter_id,
                 status, payload_jsonb, error_message, resulting_event_id,
                 resulting_encounter_turn_id, external_operation_id)
            VALUES (:system, :direction, :job_type, :entity, :encounter, :status, :payload,
                    :error, :event, :turn, :operation)
            RETURNING sync_job_id
        """),
        {
            "system": external_system_id,
            "direction": direction,
            "job_type": job_type,
            "entity": target_entity_id,
            "encounter": target_encounter_id,
            "status": status,
            "payload": json.dumps(payload) if payload is not None else None,
            "error": error_message,
            "event": resulting_event_id,
            "turn": resulting_encounter_turn_id,
            "operation": external_operation_id,
        },
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_sync_state(
    connection: Connection,
    external_system_id: uuid.UUID,
    *,
    target_entity_id: uuid.UUID | None = None,
    target_encounter_id: uuid.UUID | None = None,
    last_sync_job_id: uuid.UUID | None = None,
    sync_status: str = "unsynced",
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO integration.sync_state
                (external_system_id, target_entity_id, target_encounter_id, last_sync_job_id,
                 sync_status)
            VALUES (:system, :entity, :encounter, :job, :status)
            RETURNING sync_state_id
        """),
        {
            "system": external_system_id,
            "entity": target_entity_id,
            "encounter": target_encounter_id,
            "job": last_sync_job_id,
            "status": sync_status,
        },
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value


def make_delivery_attempt(
    connection: Connection,
    sync_job_id: uuid.UUID,
    *,
    attempt_number: int = 1,
    succeeded: bool = True,
    response_summary: str | None = None,
) -> uuid.UUID:
    value = connection.execute(
        text("""
            INSERT INTO integration.delivery_attempts
                (sync_job_id, attempt_number, succeeded, response_summary)
            VALUES (:job, :number, :succeeded, :summary)
            RETURNING delivery_attempt_id
        """),
        {
            "job": sync_job_id,
            "number": attempt_number,
            "succeeded": succeeded,
            "summary": response_summary,
        },
    ).scalar()
    assert isinstance(value, uuid.UUID)
    return value
