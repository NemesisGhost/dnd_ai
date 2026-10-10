"""The audience-preview adapter registry is closed (checkpoint 15.2A-3)."""

import pytest

from dnd_ai.api.preview import PREVIEW_ADAPTERS, PreviewAdapter, router
from dnd_ai.domain.data_classification import DataClass

pytestmark = pytest.mark.unit


def test_the_registry_is_exactly_quests_and_knowledge() -> None:
    # Adding a previewable resource must update this pin deliberately.
    assert set(PREVIEW_ADAPTERS) == {"quests", "knowledge"}
    assert {a.resource_kind for a in PREVIEW_ADAPTERS.values()} == {"quest", "knowledge_item"}


def test_the_registry_cannot_be_mutated() -> None:
    with pytest.raises(TypeError):
        PREVIEW_ADAPTERS["sessions"] = PREVIEW_ADAPTERS["quests"]  # type: ignore[index]


@pytest.mark.parametrize("name", sorted(PREVIEW_ADAPTERS))
def test_no_adapter_may_expose_player_private_or_secret_data(name: str) -> None:
    ceiling = PREVIEW_ADAPTERS[name].ceiling
    assert DataClass.PLAYER_PRIVATE not in ceiling
    assert DataClass.SECRET not in ceiling


@pytest.mark.parametrize("forbidden", [DataClass.PLAYER_PRIVATE, DataClass.SECRET])
def test_an_adapter_declaring_private_data_is_refused_at_construction(
    forbidden: DataClass,
) -> None:
    with pytest.raises(ValueError, match="may not expose private data"):
        PreviewAdapter(
            resource_kind="notes",
            command_name="preview_notes",
            schema_name="collaboration",
            table_name="notes",
            ceiling=frozenset({DataClass.CAMPAIGN_VISIBLE, forbidden}),
        )


def test_preview_routes_are_exactly_four_get_routes() -> None:
    routes = [r for r in router.routes if "/preview/" in getattr(r, "path", "")]
    # Two detail routes (one per adapter), the Knowledge collection and the subject's
    # Knowledge perspectives: all four are named by fixed path segments.
    assert len(routes) == len(PREVIEW_ADAPTERS) + 2
    assert all(getattr(r, "methods", set()) == {"GET"} for r in routes)
    # The adapter is named by a fixed path segment, never a path parameter.
    kinds = {r.path.split("/preview/")[1].split("/")[0] for r in routes}  # type: ignore[attr-defined]
    assert kinds == set(PREVIEW_ADAPTERS)
