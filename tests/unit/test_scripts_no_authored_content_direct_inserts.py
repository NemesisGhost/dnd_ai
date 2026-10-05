"""Guard: operator scripts must create Phase 14-owned records (worlds,
timelines, campaigns, world memberships, a world's allowed rulesets) and
Phase 15.1-authored world content (locations, organizations, religions, NPCs,
quests, knowledge claims) through the production commands, not raw SQL.

A deliberate exception carries the marker `phase14-direct-insert: allowed` (or,
for authored content, `authored-content-direct-insert: allowed`) on the same
statement or the comment line directly above it, with a stated reason. Immutable
seeds and the Phase 15.2 domains (sessions, events, timeline state, knowledge
state) are out of scope.
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
    # Phase 15 world time (checkpoint 15.2W-1).
    "core.calendars",
    "core.calendar_months",
    "core.world_times",
    # Phase 15.1 authored content.
    "world.locations",
    "world.settlements",
    "world.buildings",
    "world.organizations",
    "world.governments",
    "world.businesses",
    "world.military_units",
    "world.political_factions",
    "world.religious_organizations",
    "world.religions",
    "character.npcs",
    # Phase 15.2B-1 player-character identity.
    "character.characters",
    "character.player_characters",
    "character.character_descriptions",
    # Phase 15.2B-2 builds and starting state.
    "character.character_builds",
    "character.character_ability_scores",
    "character.character_class_levels",
    "character.character_proficiencies",
    "character.character_features",
    "character.character_spellcasting_profiles",
    "character.character_known_spells",
    "character.character_prepared_spells",
    "campaign.character_state",
    "narrative.quests",
    "narrative.quest_stages",
    "narrative.quest_objectives",
    "knowledge.knowledge_items",
)
_INSERT = re.compile(r"INSERT\s+INTO\s+(" + "|".join(re.escape(t) for t in _TABLES) + r")\b", re.I)
_MARKERS = ("phase14-direct-insert: allowed", "authored-content-direct-insert: allowed")
_MARKER = _MARKERS[0]

# Product security reference data (Phase 15 checkpoint 15.2A-1). These tables are
# seeded by migrations only; no marker can excuse a script inserting into them.
_NEVER_FROM_SCRIPTS = ("security.character_relationship_type_capabilities",)
_FORBIDDEN_INSERT = re.compile(
    r"INSERT\s+INTO\s+(" + "|".join(re.escape(t) for t in _NEVER_FROM_SCRIPTS) + r")\b", re.I
)


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
        if not any(marker in candidate for candidate in window for marker in _MARKERS):
            found.append((index + 1, match.group(1)))
    return found


def test_no_script_inserts_guarded_records_directly_without_a_marker() -> None:
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
    assert _violations('text("INSERT INTO world.locations (x) VALUES (1)")') == [
        (1, "world.locations")
    ]
    assert (
        _violations(
            "# authored-content-direct-insert: allowed (disposable)\n"
            'text("INSERT INTO knowledge.knowledge_items (x) VALUES (1)")'
        )
        == []
    )


def test_no_script_ever_inserts_security_reference_data() -> None:
    problems: dict[str, list[tuple[int, str]]] = {}
    for path in sorted(_SCRIPTS.glob("*.py")):
        hits = [
            (index + 1, match.group(1))
            for index, line in enumerate(path.read_text(encoding="utf-8").splitlines())
            if (match := _FORBIDDEN_INSERT.search(line))
        ]
        if hits:
            problems[path.name] = hits
    assert not problems, (
        "Relationship-capability defaults are production reference data seeded by "
        f"migration 114_relationship_defaults; scripts may not insert them: {problems}"
    )


def test_the_security_reference_guard_accepts_no_marker_exception() -> None:
    marked = (
        "# phase14-direct-insert: allowed\n"
        "INSERT INTO security.character_relationship_type_capabilities (a) VALUES (1)"
    )
    assert _FORBIDDEN_INSERT.search(marked) is not None
