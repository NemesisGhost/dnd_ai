"""Unit coverage for the pure, no-database helper functions in
`dnd_ai.queries.audit_history` — specifically the defensive placeholder
fallback branches (`_resolve_actor`, `_resolve_target`, `_change_summary`)
that, per that module's own docstring, are provably unreachable through
any real, FK-respecting database write path in this codebase (the
`ck_change_log_actor_present` CHECK constraint blocks deleting the sole
actor of an existing `audit.change_log` row outright; every target column
this module reads is similarly `ON DELETE RESTRICT` or cascades the whole
row out of the result set). A `tests/database` fixture cannot reach these
branches at all — this is the only place they are exercised."""

from dnd_ai.queries.audit_history import (
    AUDIT_CATEGORIES,
    _change_summary,
    _resolve_actor,
    _resolve_target,
    _validate_category,
)


def test_validate_category_accepts_every_public_category() -> None:
    for category in AUDIT_CATEGORIES:
        # Must not raise, and must return a non-empty command set.
        assert len(_validate_category(category)) > 0


def test_validate_category_none_returns_every_command() -> None:
    everything = _validate_category(None)
    for category in AUDIT_CATEGORIES:
        assert set(_validate_category(category)) <= set(everything)


def test_validate_category_rejects_an_unknown_value() -> None:
    try:
        _validate_category("not_a_real_category")
    except ValueError as exc:
        assert "not_a_real_category" in str(exc)
    else:
        raise AssertionError("expected ValueError for an unrecognized category")


def test_resolve_actor_prefers_a_resolved_user_display_name() -> None:
    label, actor_type = _resolve_actor(
        {"actor_user_id": "u1", "actor_display_name": "GM Alex", "actor_service": None}
    )
    assert (label, actor_type) == ("GM Alex", "user")


def test_resolve_actor_falls_back_to_placeholder_when_the_user_join_fails() -> None:
    # Defensive only — see module docstring: this shape (actor_user_id set
    # but no resolvable display name) cannot occur through any real write
    # path in this schema, since ck_change_log_actor_present blocks
    # deleting the sole actor of an existing row.
    label, actor_type = _resolve_actor(
        {"actor_user_id": "u1", "actor_display_name": None, "actor_service": None}
    )
    assert (label, actor_type) == ("Removed account", "user")


def test_resolve_actor_uses_actor_service_when_no_user_is_set() -> None:
    label, actor_type = _resolve_actor(
        {"actor_user_id": None, "actor_display_name": None, "actor_service": "importer-bot"}
    )
    assert (label, actor_type) == ("importer-bot", "service")


def test_resolve_actor_unknown_when_neither_is_set() -> None:
    # Defensive only — ck_change_log_actor_present forbids this shape from
    # ever being written or surviving in the first place.
    label, actor_type = _resolve_actor(
        {"actor_user_id": None, "actor_display_name": None, "actor_service": None}
    )
    assert (label, actor_type) == ("Unknown actor", "unknown")


def test_resolve_target_membership_command_uses_target_user() -> None:
    label, target_type = _resolve_target(
        {"target_user_id": "u1", "target_user_display_name": "Player Sam"},
        command_name="add_campaign_member",
    )
    assert (label, target_type) == ("Player Sam", "account")


def test_resolve_target_membership_command_placeholder_when_join_fails() -> None:
    label, target_type = _resolve_target(
        {"target_user_id": "u1", "target_user_display_name": None},
        command_name="add_campaign_member",
    )
    assert (label, target_type) == ("Removed account", "account")


def test_resolve_target_relationship_command_uses_target_character() -> None:
    label, target_type = _resolve_target(
        {"target_character_id": "c1", "target_character_name": "Elenwe"},
        command_name="grant_character_relationship",
    )
    assert (label, target_type) == ("Elenwe", "character")


def test_resolve_target_grant_command_prefers_account_grantee() -> None:
    label, target_type = _resolve_target(
        {
            "grantee_user_display_name": "Player Sam",
            "grantee_group_name": None,
            "grantee_membership_id": "m1",
            "grantee_access_group_id": None,
        },
        command_name="create_resource_grant",
    )
    assert (label, target_type) == ("Player Sam", "account")


def test_resolve_target_grant_command_falls_back_to_access_group() -> None:
    label, target_type = _resolve_target(
        {
            "grantee_user_display_name": None,
            "grantee_group_name": "Livestream Observers",
            "grantee_membership_id": None,
            "grantee_access_group_id": "g1",
        },
        command_name="create_resource_grant",
    )
    assert (label, target_type) == ("Livestream Observers", "access_group")


def test_resolve_target_grant_command_placeholder_when_both_grantees_missing() -> None:
    # Defensive only — security.resource_grants requires exactly one
    # grantee column non-null; this shape cannot occur in a real row.
    label, target_type = _resolve_target(
        {
            "grantee_user_display_name": None,
            "grantee_group_name": None,
            "grantee_membership_id": "m1",
            "grantee_access_group_id": None,
        },
        command_name="create_resource_grant",
    )
    assert (label, target_type) == ("Removed account", "account")

    label, target_type = _resolve_target(
        {
            "grantee_user_display_name": None,
            "grantee_group_name": None,
            "grantee_membership_id": None,
            "grantee_access_group_id": "g1",
        },
        command_name="create_resource_grant",
    )
    assert (label, target_type) == ("Removed access group", "access_group")


def test_resolve_target_invitation_and_campaign_commands_have_no_discrete_target() -> None:
    assert _resolve_target({}, command_name="create_campaign_invitation") == (None, None)
    assert _resolve_target({}, command_name="accept_campaign_invitation") == (None, None)
    assert _resolve_target({}, command_name="create_campaign") == (None, None)


def test_change_summary_role_change_uses_resolved_display_names() -> None:
    summary = _change_summary(
        {
            "previous_status": "player",
            "previous_role_display_name": "Player",
            "role_display_name": "Observer",
        },
        command_name="change_membership_role",
    )
    assert summary == "Player → Observer"


def test_change_summary_role_change_falls_back_to_raw_code_when_join_fails() -> None:
    summary = _change_summary(
        {
            "previous_status": "player",
            "previous_role_display_name": None,
            "role_display_name": None,
        },
        command_name="change_membership_role",
    )
    assert summary == "player → Removed role"


def test_change_summary_grant_commands_include_capability_and_grantee() -> None:
    summary = _change_summary(
        {
            "capability_display_name": "View Full Character",
            "grantee_user_display_name": "Player Sam",
            "grantee_group_name": None,
        },
        command_name="create_resource_grant",
    )
    assert summary == "View Full Character — Player Sam"


def test_change_summary_membership_commands_have_no_summary() -> None:
    assert _change_summary({}, command_name="add_campaign_member") is None
    assert _change_summary({}, command_name="end_campaign_membership") is None
