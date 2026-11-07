"""The restriction predicate and the source-read rule (P03-A A2b-1, plan sections 9.1-9.2, I3, I4).

Pure functions over synthetic histories: a tiny model of the draft applies the same watermark rule
the database trigger enforces (a content change of a legacy field sets its watermark to the new
`row_version`; clearing ends the lineage; other fields are left alone), releases record the draft
version they snapshot, and the predicate is read against them.
"""

import uuid
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from dnd_ai.domain.access import AccessContext
from dnd_ai.domain.public_profiles import field_is_restricted, may_read_legacy_source
from dnd_ai.domain.world_authority import WORLD_CANON_READ_PRIVATE


@dataclass
class Field:
    text: str | None = None
    legacy: bool = False
    watermark: int | None = None


@dataclass
class Draft:
    row_version: int = 1
    fields: dict[str, Field] = field(default_factory=lambda: {"a": Field(), "b": Field()})
    releases: list[int] = field(default_factory=list)  # from_draft_row_version of each release

    def _bump(self) -> int:
        self.row_version += 1
        return self.row_version

    def copy(self, name: str, text: str) -> None:
        version = self._bump()
        self.fields[name] = Field(text=text, legacy=True, watermark=version)

    def edit(self, name: str, text: str) -> None:
        version = self._bump()
        current = self.fields[name]
        # Editing legacy text keeps the origin and advances the watermark (I2); other fields are
        # left alone (I3).
        self.fields[name] = Field(
            text=text, legacy=current.legacy, watermark=version if current.legacy else None
        )

    def clear(self, name: str) -> None:
        self._bump()
        self.fields[name] = Field()  # I6: the lineage ends

    def release(self) -> None:
        self.releases.append(self.row_version)

    def restricted(self, name: str) -> bool:
        f = self.fields[name]
        covering = max(self.releases) if self.releases else None
        return field_is_restricted(
            has_text=f.text is not None,
            is_legacy=f.legacy,
            watermark=f.watermark,
            covering_draft_version=covering,
        )


def test_a_copied_field_is_restricted_until_a_release_covers_it() -> None:
    draft = Draft()
    draft.copy("b", "full source")
    assert draft.restricted("b")
    draft.release()
    assert not draft.restricted("b")


def test_every_later_change_restricts_it_again_until_released() -> None:
    draft = Draft()
    draft.copy("b", "full")
    draft.edit("b", "excerpt")
    draft.release()
    assert not draft.restricted("b")
    for change in ("excerpt plus more", "full", "excerpt"):  # append, restore, back to the excerpt
        draft.edit("b", change)
        assert draft.restricted("b"), change
        draft.release()
        assert not draft.restricted("b"), change


def test_editing_another_field_never_restricts_a_released_one_i3() -> None:
    draft = Draft()
    draft.copy("b", "full")
    draft.release()
    draft.edit("a", "authored change")
    draft.edit("a", "another")
    assert not draft.restricted("b")
    draft.edit("b", "changed")
    assert draft.restricted("b") and not draft.restricted("a")


def test_a_release_covers_exactly_the_text_it_snapshotted_i4() -> None:
    draft = Draft()
    draft.copy("b", "one")
    draft.release()  # snapshots "one" at version 2
    released_version = draft.releases[-1]
    draft.edit("b", "two")  # version 3: the watermark moves past every release
    assert draft.fields["b"].watermark is not None
    assert draft.fields["b"].watermark > released_version
    assert draft.restricted("b")


def test_clearing_ends_the_lineage_and_a_recopy_starts_a_new_one() -> None:
    draft = Draft()
    draft.copy("b", "one")
    draft.release()
    draft.clear("b")
    assert not draft.restricted("b")
    draft.copy("b", "one")  # the same text again is still new restricted content
    assert draft.restricted("b")


def test_an_authored_field_and_an_empty_field_are_never_restricted() -> None:
    assert not field_is_restricted(
        has_text=True, is_legacy=False, watermark=None, covering_draft_version=None
    )
    assert not field_is_restricted(
        has_text=False, is_legacy=True, watermark=3, covering_draft_version=None
    )
    # A legacy field with no watermark cannot be proven covered.
    assert field_is_restricted(
        has_text=True, is_legacy=True, watermark=None, covering_draft_version=9
    )


def _access(*capabilities: str) -> AccessContext:
    return AccessContext(
        user_id=uuid.uuid4(),
        campaign_id=uuid.uuid4(),
        campaign_membership_id=uuid.uuid4(),
        timeline_id=uuid.uuid4(),
        role_capabilities=frozenset(capabilities),
        character_capabilities={},
        grant_effects={},
    )


def _world(*capabilities: str) -> object:
    return SimpleNamespace(has_capability=lambda code: code in capabilities)


@pytest.mark.parametrize(
    ("kind", "role", "world", "expected"),
    [
        ("player_character", ("canon.edit",), (), True),
        ("player_character", (), (), False),
        ("npc", ("canon.edit",), (WORLD_CANON_READ_PRIVATE,), True),
        ("npc", ("canon.edit",), (), False),
        ("npc", (), (WORLD_CANON_READ_PRIVATE,), False),
        ("character", ("canon.edit",), (WORLD_CANON_READ_PRIVATE,), False),
        (None, ("canon.edit",), (WORLD_CANON_READ_PRIVATE,), False),
    ],
)
def test_the_source_read_rule_follows_the_kind(
    kind: str | None, role: tuple[str, ...], world: tuple[str, ...], expected: bool
) -> None:
    authority = _world(*world) if world else None
    assert (
        may_read_legacy_source(kind, access=_access(*role), world_authority=authority)  # type: ignore[arg-type]
        is expected
    )
