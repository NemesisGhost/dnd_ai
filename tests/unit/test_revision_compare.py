"""Snapshot comparison policy (checkpoint 15.3C-2): no database."""

from dnd_ai.domain.revision_compare import (
    ADDED,
    CHANGED,
    REMOVED,
    VALUE_DISPLAY_LIMIT,
    diff_snapshots,
)


def paths(changes):  # type: ignore[no-untyped-def]
    return [(c.path, c.kind) for c in changes]


def test_equal_snapshots_have_no_changes() -> None:
    snapshot = {"name": "A", "tags": ["x"], "nested": {"a": 1}}
    assert diff_snapshots(snapshot, dict(snapshot)) == []


def test_added_removed_and_changed_fields_are_reported_in_path_order() -> None:
    changes = diff_snapshots(
        {"name": "Old", "summary": "s", "gone": 1},
        {"name": "New", "summary": "s", "fresh": True},
    )
    assert paths(changes) == [("fresh", ADDED), ("gone", REMOVED), ("name", CHANGED)]
    name = changes[2]
    assert (name.before, name.after) == ("Old", "New")
    assert changes[0].before is None and changes[0].after is True


def test_nested_objects_report_the_inner_path() -> None:
    changes = diff_snapshots({"a": {"b": {"c": 1}}}, {"a": {"b": {"c": 2}}})
    assert paths(changes) == [("a.b.c", CHANGED)]


def test_null_is_a_value_not_an_absence() -> None:
    changes = diff_snapshots({"a": None}, {"a": "x"})
    assert paths(changes) == [("a", CHANGED)]
    assert diff_snapshots({"a": None}, {"a": None}) == []
    assert paths(diff_snapshots({}, {"a": None})) == [("a", ADDED)]


def test_lists_of_objects_are_matched_by_their_id_so_reordering_is_not_a_change() -> None:
    before = {"stages": [{"stage_id": "s1", "name": "One"}, {"stage_id": "s2", "name": "Two"}]}
    after = {"stages": [{"stage_id": "s2", "name": "Two"}, {"stage_id": "s1", "name": "Uno"}]}
    assert paths(diff_snapshots(before, after)) == [("stages[stage_id=s1].name", CHANGED)]


def test_an_item_added_to_or_removed_from_a_list_of_objects() -> None:
    before = {"items": [{"id": "a", "v": 1}]}
    after = {"items": [{"id": "a", "v": 1}, {"id": "b", "v": 2}]}
    assert paths(diff_snapshots(before, after)) == [
        ("items[id=b].id", ADDED),
        ("items[id=b].v", ADDED),
    ]
    assert paths(diff_snapshots(after, before)) == [
        ("items[id=b].id", REMOVED),
        ("items[id=b].v", REMOVED),
    ]


def test_lists_without_a_unique_identity_are_matched_by_position() -> None:
    changes = diff_snapshots({"tags": ["a", "b"]}, {"tags": ["a", "c", "d"]})
    assert paths(changes) == [("tags[1]", CHANGED), ("tags[2]", ADDED)]
    duplicate_ids = {"x": [{"id": "1", "v": 1}, {"id": "1", "v": 2}]}
    assert paths(
        diff_snapshots(duplicate_ids, {"x": [{"id": "1", "v": 1}, {"id": "1", "v": 3}]})
    ) == [("x[1].v", CHANGED)]


def test_empty_containers_are_values() -> None:
    assert paths(diff_snapshots({"a": []}, {"a": [1]})) == [("a", REMOVED), ("a[0]", ADDED)]
    assert diff_snapshots({"a": {}}, {"a": {}}) == []


def test_long_values_are_cut_and_flagged() -> None:
    long = "x" * (VALUE_DISPLAY_LIMIT + 50)
    (change,) = diff_snapshots({"notes": "short"}, {"notes": long})
    assert change.truncated is True and len(change.after) == VALUE_DISPLAY_LIMIT + 1
    assert change.after.endswith("…") and change.before == "short"


def test_large_snapshots_compare_quickly() -> None:
    big = {f"field_{i}": {"value": i, "tags": [str(j) for j in range(20)]} for i in range(2000)}
    other = {k: dict(v) for k, v in big.items()}
    other["field_1999"] = {"value": -1, "tags": ["z"]}
    changes = diff_snapshots(big, other)
    assert changes and all(c.path.startswith("field_1999") for c in changes)
