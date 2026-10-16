"""Comparing two revision snapshots (Phase 15 checkpoint 15.3C-2).

A revision snapshot is the JSON object of an authored record (`core.entity_revisions.snapshot`).
`diff_snapshots` flattens both into `path -> value` maps and reports each path that was added,
removed or changed, in path order. Lists of objects are matched by an identifying key when every
item has one (an `id` or a `*_id` field that is unique within the list), so a reordered or
partly changed list reads as changes to the items rather than to every position; otherwise items
are matched by position. Both flattening and comparison are linear in the size of the snapshots.
Display values are cut at `VALUE_DISPLAY_LIMIT` characters and say so.
"""

from dataclasses import dataclass
from typing import Any

VALUE_DISPLAY_LIMIT = 2000

ADDED = "added"
REMOVED = "removed"
CHANGED = "changed"

_ABSENT = object()


@dataclass(frozen=True)
class Change:
    path: str
    kind: str
    before: Any
    after: Any
    truncated: bool = False


def _identity_key(items: list[Any]) -> str | None:
    """The key that identifies each object of a list, when there is one that is unique."""
    if not items or not all(isinstance(i, dict) for i in items):
        return None
    candidates = [k for k in items[0] if k == "id" or str(k).endswith("_id")]
    for key in candidates:
        values = [i.get(key) for i in items]
        if all(isinstance(v, str | int) for v in values) and len(set(values)) == len(values):
            return str(key)
    return None


def _flatten(value: Any, path: str, out: dict[str, Any]) -> None:
    if isinstance(value, dict):
        if not value:
            if path:  # an empty record has no fields to compare
                out[path] = {}
            return
        for key in sorted(value):
            _flatten(value[key], f"{path}.{key}" if path else str(key), out)
    elif isinstance(value, list):
        if not value:
            out[path] = []
            return
        key = _identity_key(value)
        for index, item in enumerate(value):
            label = f"{key}={item[key]}" if key is not None else str(index)
            _flatten(item, f"{path}[{label}]", out)
    else:
        out[path] = value


def _shown(value: Any) -> tuple[Any, bool]:
    if isinstance(value, str) and len(value) > VALUE_DISPLAY_LIMIT:
        return value[:VALUE_DISPLAY_LIMIT] + "…", True
    return value, False


def diff_snapshots(before: dict[str, Any], after: dict[str, Any]) -> list[Change]:
    old: dict[str, Any] = {}
    new: dict[str, Any] = {}
    _flatten(before, "", old)
    _flatten(after, "", new)
    changes: list[Change] = []
    for path in sorted(old.keys() | new.keys()):
        was = old.get(path, _ABSENT)
        now = new.get(path, _ABSENT)
        if was is not _ABSENT and now is not _ABSENT and was == now:
            continue
        shown_was, cut_was = (None, False) if was is _ABSENT else _shown(was)
        shown_now, cut_now = (None, False) if now is _ABSENT else _shown(now)
        kind = ADDED if was is _ABSENT else REMOVED if now is _ABSENT else CHANGED
        changes.append(
            Change(
                path=path or "(record)",
                kind=kind,
                before=shown_was,
                after=shown_now,
                truncated=cut_was or cut_now,
            )
        )
    return changes
