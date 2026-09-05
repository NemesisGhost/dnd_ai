"""Explicit, ruleset-selected derived-value calculations for a character
sheet (docs/PLAN.md §6.3, "Derived calculations").

Framework-free and pure: every function here is plain arithmetic over
already-resolved inputs, with no database access and no knowledge of
authorization, HTTP, or the shape of any particular endpoint's response.
Callers (currently only `dnd_ai.queries.character_sheet`) decide *when* a
value can be computed at all (e.g. a skill's governing ability score is
missing from the build, or the build has no class levels yet) — this
module never invents a plausible-looking number to fill a gap; that
decision is the caller's, made explicit by simply not calling the relevant
function.

`supports_ruleset()` is the single gate a caller must check before calling
anything else here. Only `dnd5e` is implemented today — the D&D 5e ability
modifier, proficiency bonus, and derived-bonus formulas are the same across
the 2014 and 2024 revisions this codebase's own seed data spans (revision
034's "edition-neutral ruleset family" split: the edition lives on
`rules.ruleset_versions.version_label`, not the ruleset family code), so
gating on `ruleset_code` alone (rather than also requiring a specific
`version_label`) is deliberate, not an oversight. A homebrew or future
non-5e ruleset must return `False` here rather than silently having D&D
formulas applied to it — see this module's own docstring reasoning
mirrored in `dnd_ai.queries.character_sheet`'s docstring for how an
unsupported ruleset's sheet response looks (raw values only, every derived
field `None`).

This is deliberately not a plugin framework or a general rules engine: one
closed vocabulary (`_SUPPORTED_RULESET_CODES`) and one set of formulas,
matching the one ruleset this platform seeds today. Add a new ruleset's
formulas here only when that ruleset actually exists and needs them.
"""

from collections.abc import Iterable

_SUPPORTED_RULESET_CODES = frozenset({"dnd5e"})


def supports_ruleset(ruleset_code: str) -> bool:
    """Whether this module's calculations apply to `ruleset_code`. Callers
    must check this before calling any other function here — the D&D 5e
    formulas below must never be silently applied to an unrecognized or
    homebrew ruleset."""
    return ruleset_code in _SUPPORTED_RULESET_CODES


def ability_modifier(score: int) -> int:
    """`floor((score - 10) / 2)` — Python's integer floor division (`//`)
    already floors toward negative infinity for negative results, which is
    exactly this formula's intent (e.g. score 7 -> -2, not -1)."""
    return (score - 10) // 2


def total_level(class_levels: Iterable[int]) -> int:
    """Sum of every class level a build holds — 0 for a build with no
    class levels recorded yet."""
    return sum(class_levels)


def proficiency_bonus(total_char_level: int) -> int:
    """`2 + floor((level - 1) / 4)`, valid for `total_char_level >= 1`.
    Callers must not call this for a build with no class levels at all
    (`total_level(...) == 0`) — there is no level to derive a bonus from,
    and this function does not guess one."""
    if total_char_level < 1:
        raise ValueError(
            f"proficiency_bonus requires total_char_level >= 1, got {total_char_level}"
        )
    return 2 + (total_char_level - 1) // 4


def skill_bonus(
    ability_score_modifier: int,
    proficiency_bonus_value: int,
    *,
    is_proficient: bool,
    is_expertise: bool,
) -> int:
    """A skill check bonus: the governing ability modifier, plus the
    proficiency bonus once if proficient, or twice if the build also has
    expertise in this skill (expertise is never treated as ordinary
    proficiency — the caller's `is_expertise` and `is_proficient` are
    independent booleans, and this function applies the correct
    multiplier for each combination)."""
    multiplier = 2 if is_expertise else (1 if is_proficient else 0)
    return ability_score_modifier + multiplier * proficiency_bonus_value


def passive_score(computed_skill_bonus: int) -> int:
    """10 + the skill's own computed bonus (proficiency/expertise already
    applied by the caller via `skill_bonus`)."""
    return 10 + computed_skill_bonus


def saving_throw_bonus(
    ability_score_modifier: int, proficiency_bonus_value: int, *, is_proficient: bool
) -> int:
    """A saving throw bonus: the ability modifier, plus the proficiency
    bonus once if proficient in this saving throw."""
    return ability_score_modifier + (proficiency_bonus_value if is_proficient else 0)


def spell_attack_bonus(ability_score_modifier: int, proficiency_bonus_value: int) -> int:
    return ability_score_modifier + proficiency_bonus_value


def spell_save_dc(ability_score_modifier: int, proficiency_bonus_value: int) -> int:
    return 8 + ability_score_modifier + proficiency_bonus_value
