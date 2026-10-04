"""Guard: operator scripts must create Phase 14-owned records (worlds,
timelines, campaigns, world memberships, a world's allowed rulesets) through
the production commands, not raw SQL.

A deliberate exception carries the marker `phase14-direct-insert: allowed` on
the same statement (or the comment line directly above it) with a stated
reason. Immutable seeds and Phase 15+ domains (entities, quests, sessions, …)
are out of scope, so only the five Phase 14 tables are checked.
"""

import re
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
_TABLES = (
    "core.worlds",
    "campaign.timelines",
    "campaign.campaigns",
    "security.world_memberships",
    "rules.world_rulesets",
)
_INSERT = re.compile(r"INSERT\s+INTO\s+(" + "|".join(re.escape(t) for t in _TABLES) + r")\b", re.I)
_MARKER = "phase14-direct-insert: allowed"


def _violations(source: str) -> list[tuple[int, str]]:
    lines = source.splitlines()
    found: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        match = _INSERT.search(line)
        if match is None:
            continue
        # The marker may sit on this line or on either of the two lines above
        # (a SQL comment inside the statement, or a Python comment before it).
        window = lines[max(0, index - 2) : index + 1]
        if not any(_MARKER in candidate for candidate in window):
            found.append((index + 1, match.group(1)))
    return found


def test_no_script_inserts_phase14_records_directly_without_a_marker() -> None:
    problems = {
        path.name: _violations(path.read_text(encoding="utf-8"))
        for path in sorted(_SCRIPTS.glob("*.py"))
    }
    problems = {name: found for name, found in problems.items() if found}
    assert not problems, (
        "Create worlds/timelines/campaigns/memberships through dnd_ai.commands "
        f"(or mark a justified exception with '{_MARKER}'): {problems}"
    )


def test_the_guard_detects_an_unmarked_insert_and_accepts_a_marked_one() -> None:
    assert _violations('text("INSERT INTO core.worlds (name) VALUES (:n)")') == [(1, "core.worlds")]
    assert (
        _violations(
            f'# {_MARKER} (disposable)\ntext("INSERT INTO campaign.timelines (x) VALUES (1)")'
        )
        == []
    )
    assert _violations('text("INSERT INTO core.entities (x) VALUES (1)")') == []
