"""Character public-profile drafts and releases: vocabulary, errors and the read/edit/release policy
(P03-A slice A2a, docs/PHASE14_15_P03A_IMPLEMENTATION_PLAN_2026-11-06.md section 5, decision D8).

A campaign's GMs author a public profile for a character (two text fields) in a mutable draft and
publish immutable, versioned releases of it. A release makes nothing visible by itself; an audience
sees one only through a later revelation (A3/A4), which A2a does not add.

The policy here is pure, resolved from a loaded `AccessContext`; the commands re-resolve the context
under their locks (section 5.7a "Under lock"):

- **Whole-character deny.** An `entity_id` `campaign.view` deny for the character blocks reading,
  editing and releasing for every source, an owner included (ADR 0021 section 2.9).
- **Effective character-scoped `canon.edit`.** The role `canon.edit` in the campaign, with no
  whole-character deny and no `canon.edit` deny on the character. An *allow* grant of `canon.edit`
  on the character never confers it (D8): a resource grant is not an authoring path.
- **Reading** needs effective character-scoped `canon.edit` or current `character.reveal`
  authority; reveal authority confers reading only.
- **Releasing** needs `character.reveal` authority (`resolve_reveal_authority`) and no
  whole-character deny. A `canon.edit` deny does not stop it: a different operation.
"""

import uuid

from .access import AccessContext
from .errors import DomainAuthorizationError, SafeMessageError
from .npc_authoring import NPC_TEXT_MAX_LENGTH
from .world_authority import WORLD_CANON_READ_PRIVATE, WorldAuthority

PUBLIC_PROFILE_TEXT_MAX_LENGTH = NPC_TEXT_MAX_LENGTH
PUBLIC_PROFILE_NOTE_MAX_LENGTH = 1000

FIELD_APPEARANCE = "public_appearance"
FIELD_BACKGROUND = "public_background"
PUBLIC_PROFILE_FIELDS = (FIELD_APPEARANCE, FIELD_BACKGROUND)

ORIGIN_AUTHORED = "authored"
ORIGIN_LEGACY_APPEARANCE = "legacy_appearance"
ORIGIN_LEGACY_BACKGROUND = "legacy_background"
LEGACY_ORIGINS = frozenset({ORIGIN_LEGACY_APPEARANCE, ORIGIN_LEGACY_BACKGROUND})

KIND_NPC = "npc"
KIND_PLAYER_CHARACTER = "player_character"

AUTHORITY_OWNER = "owner"
AUTHORITY_DELEGATION = "delegation"

CANON_EDIT = "canon.edit"
CAMPAIGN_VIEW = "campaign.view"


class PublicProfileNotFoundError(DomainAuthorizationError):
    """The character is not a canon character of the campaign's world, or a whole-character deny
    removes it from the caller: indistinguishable (fixed 404)."""


class PublicProfileEditDeniedError(DomainAuthorizationError):
    """The caller can still read this profile but a `canon.edit` deny on the character removes the
    right to edit it. 403 `public_profile_edit_denied`: the caller can already see the character,
    so the code discloses nothing."""

    safe_status_code = 403
    safe_error_code = "public_profile_edit_denied"
    safe_message = "You may not edit this character's public profile."


class CharacterRevealRequiredError(DomainAuthorizationError):
    """The caller does not hold `character.reveal` authority in the campaign. Reveal authority
    depends only on the campaign, so this says nothing about the character. 403
    `character_reveal_required`."""

    safe_status_code = 403
    safe_error_code = "character_reveal_required"
    safe_message = "Only a campaign owner or a delegated GM may release a public profile."


class PublicProfileFieldWithheldError(DomainAuthorizationError):
    """The request would put text into a draft field the caller may not read (copied text still
    under its source-read restriction), or would release a draft holding such a field. 403
    `public_profile_field_withheld`. The caller has already been told the field is withheld (the
    profile read shows `withheld: true`), so the code discloses nothing more."""

    safe_status_code = 403
    safe_error_code = "public_profile_field_withheld"
    safe_message = "This draft holds copied text you cannot read."


class PublicProfileDraftMissingError(SafeMessageError):
    """A release (or a save with a token) named a draft that does not exist."""

    safe_status_code = 409
    safe_error_code = "public_profile_draft_missing"
    safe_message = "This character has no public-profile draft yet."


class PublicProfileCharacterNotActiveError(SafeMessageError):
    """The character is archived (or otherwise not active): a profile cannot be saved or released."""

    safe_status_code = 409
    safe_error_code = "public_profile_character_not_active"
    safe_message = "The character is not active."


# --- policy ------------------------------------------------------------------------------------


def whole_character_denied(access: AccessContext, character_id: uuid.UUID) -> bool:
    """A `campaign.view` deny on the character's entity: the resource is removed for this caller.
    The same test `resolve_character_inventory_access` uses."""
    return not access.has_capability(CAMPAIGN_VIEW, entity_id=character_id)


def canon_edit_denied_for_character(access: AccessContext, character_id: uuid.UUID) -> bool:
    """A `canon.edit` deny on the character. Under `entity_id`, the only key a `canon.edit` grant
    can be created under; a stray `character_id` row counts too, so it fails closed.
    `has_capability("canon.edit", character_id=...)` alone is not enough: it never sees the
    `entity_id` key."""
    return any(
        access.grant_effects.get((key, character_id), {}).get(CANON_EDIT) == "deny"
        for key in ("entity_id", "character_id")
    )


def has_effective_character_canon_edit(access: AccessContext, character_id: uuid.UUID) -> bool:
    """The role `canon.edit`, with no whole-character deny and no `canon.edit` deny on the
    character. An `allow` grant on the character does not count."""
    return (
        CANON_EDIT in access.role_capabilities
        and not whole_character_denied(access, character_id)
        and not canon_edit_denied_for_character(access, character_id)
    )


def may_read_profile(
    access: AccessContext, character_id: uuid.UUID, *, has_reveal_authority: bool
) -> bool:
    """Draft and release reads: effective character-scoped `canon.edit`, or current reveal
    authority. A whole-character deny overrides both."""
    if whole_character_denied(access, character_id):
        return False
    return has_reveal_authority or has_effective_character_canon_edit(access, character_id)


# --- legacy-copy restriction (A2b, decision D7) --------------------------------------------------


def may_read_legacy_source(
    kind: str | None, *, access: AccessContext, world_authority: WorldAuthority | None
) -> bool:
    """The source-read rule: may this caller read the legacy description of a character of `kind`?

    One function, keyed by the character's kind and never by the caller's choice, equal to the gate
    of that kind's legacy authoring read today (D7-e): a `player_character` needs role `canon.edit`
    in the campaign; an `npc` needs role `canon.edit` and the world capability
    `world.canon.read_private`; any other kind has no authoring read, so nobody may. The role
    check is role-only (`has_capability("canon.edit")` with no target), so per-character denies do
    not enter the rule, as they do not enter the authoring reads; a whole-character deny still
    removes the profile entirely (D8).

    **Assumption: a character's kind is stable on every application path.** The rule uses the
    current kind at each check. No `src/` code changes `core.entities.entity_type_id` or deletes a
    `character.npcs` or `character.player_characters` row, and ADR 0021 section 1 says no code
    converts one marker into the other, but the database does not forbid it (migration 048 refuses
    a type change only while a subtype row of the old type exists). If a later slice makes kind
    mutable, the copy must first snapshot the rule into the field."""
    if CANON_EDIT not in access.role_capabilities:
        return False
    if kind == KIND_PLAYER_CHARACTER:
        return True
    if kind == KIND_NPC:
        return world_authority is not None and world_authority.has_capability(
            WORLD_CANON_READ_PRIVATE
        )
    return False


def field_is_restricted(
    *, has_text: bool, is_legacy: bool, watermark: int | None, covering_draft_version: int | None
) -> bool:
    """A draft field is restricted when it has text, a legacy origin, and no release covers it.

    A release covers a field when its `from_draft_row_version` is at or above the field's
    restriction watermark (the draft `row_version` at which the field's content last changed while
    legacy). `covering_draft_version` is the highest `from_draft_row_version` among the profile's
    releases. Because a release snapshots the draft exactly at that version, a covering release
    holds the field's current content (a later change moves the watermark past every release).
    A legacy field with no watermark is treated as restricted: it cannot be proven covered."""
    if not has_text or not is_legacy:
        return False
    if watermark is None or covering_draft_version is None:
        return True
    return covering_draft_version < watermark
