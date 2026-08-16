"""Character tables — character schema.

Part of the src/dnd_ai/persistence/tables package. See
src/dnd_ai/persistence/tables/__init__.py for the metadata-authority note
this module inherits: this is compared against the live database by
`alembic check`, so declared tables/columns/comments must match migrations
exactly.
"""

from sqlalchemy import (
    Boolean,
    Column,
    ForeignKey,
    Index,
    PrimaryKeyConstraint,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP, UUID

from ._shared import (
    NONNEGATIVE_INTEGER,
    PERCENTAGE_0_100,
    _timestamps,
    _uuid_pk,
    metadata,
)

# ---------------------------------------------------------------------------
# character — characters, npcs, player_characters (revision 017)
# ---------------------------------------------------------------------------

characters = Table(
    "characters",
    metadata,
    Column(
        "character_id",
        UUID(),
        ForeignKey("core.entities.entity_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "species_id",
        UUID(),
        ForeignKey("rules.species.species_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("size_category", Text(), nullable=False),
    *_timestamps(),
    # Added by revision 042, once world.locations existed to point at.
    Column(
        "origin_location_id",
        UUID(),
        ForeignKey("world.locations.location_id", ondelete="SET NULL"),
        comment=(
            "Where this character is from. References world.locations "
            "existed (docs/architecture/DATABASE_MODEL.md §7.1). Must belong to the "
            "character's own world, enforced by trigger."
        ),
    ),
    schema="character",
    comment=(
        "Identity-level mechanical data shared by every character: species and size. "
        "NPCs and player characters both extend this row rather than duplicating it "
        "(docs/DOMAIN_MODEL.md §7.1). origin_location_id references "
        "world.locations exists."
    ),
)

Index("ix_characters_species_id", characters.c.species_id)
Index(
    "ix_characters_origin_location_id",
    characters.c.origin_location_id,
    postgresql_where=characters.c.origin_location_id.isnot(None),
)

npcs = Table(
    "npcs",
    metadata,
    Column(
        "npc_id",
        UUID(),
        ForeignKey("character.characters.character_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    *_timestamps(),
    schema="character",
    comment=(
        "Marks a character as an NPC. Portrayal, goals, routines, and other simulation "
        "apparatus belongs in the AI domain rather than this mechanical table "
        "agents that consume them."
    ),
)

player_characters = Table(
    "player_characters",
    metadata,
    Column(
        "player_character_id",
        UUID(),
        ForeignKey("character.characters.character_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "player_user_id",
        UUID(),
        ForeignKey("security.users.user_id", ondelete="SET NULL"),
    ),
    *_timestamps(),
    schema="character",
    comment=(
        "Marks a character as player-controlled. player_user_id is basic ownership "
        "identity; timeline- or session-scoped control handoffs "
        "are represented by security.membership_character_relationships."
    ),
)

Index(
    "ix_player_characters_player_user_id",
    player_characters.c.player_user_id,
    postgresql_where=player_characters.c.player_user_id.isnot(None),
)

# ---------------------------------------------------------------------------
# character — shared data: descriptions, languages, senses, movements
# (revision 019)
# ---------------------------------------------------------------------------

character_descriptions = Table(
    "character_descriptions",
    metadata,
    Column(
        "character_id",
        UUID(),
        ForeignKey("character.characters.character_id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("background", Text()),
    Column("appearance", Text()),
    Column("notes", Text()),
    *_timestamps(),
    schema="character",
    comment=(
        "Free-text background, appearance, and notes that do not drive mechanics "
        "Optional: a character need not have one."
    ),
)

character_languages = Table(
    "character_languages",
    metadata,
    Column(
        "character_id",
        UUID(),
        ForeignKey("character.characters.character_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "language_id",
        UUID(),
        ForeignKey("rules.languages.language_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    PrimaryKeyConstraint("character_id", "language_id"),
    schema="character",
    comment=(
        "Languages a character knows. Pure association — a character may know "
        "languages from more than one ruleset's content, as long as every ruleset "
        "family in play is one the character's world allows (rules.world_rulesets); "
        "enforced by trigger (revision 037), same as species/build/condition/resource."
    ),
)

Index("ix_character_languages_language_id", character_languages.c.language_id)

character_senses = Table(
    "character_senses",
    metadata,
    Column(
        "character_id",
        UUID(),
        ForeignKey("character.characters.character_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("sense_type", Text(), nullable=False),
    Column("range_feet", NONNEGATIVE_INTEGER, nullable=False),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    PrimaryKeyConstraint("character_id", "sense_type"),
    schema="character",
    comment="A special sense a character has (darkvision, blindsight, ...) and its range.",
)

character_movements = Table(
    "character_movements",
    metadata,
    Column(
        "character_id",
        UUID(),
        ForeignKey("character.characters.character_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("movement_type", Text(), nullable=False),
    Column("speed_feet", NONNEGATIVE_INTEGER, nullable=False),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    PrimaryKeyConstraint("character_id", "movement_type"),
    schema="character",
    comment="A movement mode a character has (walk, fly, swim, ...) and its speed.",
)

# ---------------------------------------------------------------------------
# character — builds (revision 020)
# ---------------------------------------------------------------------------

character_builds = Table(
    "character_builds",
    metadata,
    _uuid_pk("character_build_id"),
    Column(
        "character_id",
        UUID(),
        ForeignKey("character.characters.character_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "ruleset_version_id",
        UUID(),
        ForeignKey("rules.ruleset_versions.ruleset_version_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("label", Text()),
    # is_current removed by revision 028: active-build selection moved to
    # timeline state (campaign.character_state.character_build_id), since a
    # single global "current" flag cannot represent a character built
    # differently on two timelines after a branch.
    *_timestamps(),
    schema="character",
    comment=(
        "A versioned mechanical snapshot of a character, pinned to one ruleset version. "
        "Ability scores, class levels, proficiencies, features, and spellcasting all "
        "belong to a build, not directly to the character, so re-leveling or rebuilding "
        "does not erase the prior build's history. Which build is active on a given "
        "timeline is timeline state (campaign.character_state.character_build_id), not a "
        "property of the build itself — a character may use different builds on "
        "different timelines after a branch."
    ),
)

Index("ix_character_builds_character_id", character_builds.c.character_id)
Index("ix_character_builds_ruleset_version_id", character_builds.c.ruleset_version_id)

character_ability_scores = Table(
    "character_ability_scores",
    metadata,
    Column(
        "character_build_id",
        UUID(),
        ForeignKey("character.character_builds.character_build_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "ability_id",
        UUID(),
        ForeignKey("rules.abilities.ability_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("score", NONNEGATIVE_INTEGER, nullable=False),
    *_timestamps(),
    PrimaryKeyConstraint("character_build_id", "ability_id"),
    schema="character",
    comment=(
        "The raw score (e.g. 16) a build has in one ability. Modifiers are derived, not stored."
    ),
)

Index("ix_character_ability_scores_ability_id", character_ability_scores.c.ability_id)

character_class_levels = Table(
    "character_class_levels",
    metadata,
    Column(
        "character_build_id",
        UUID(),
        ForeignKey("character.character_builds.character_build_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "class_id",
        UUID(),
        ForeignKey("rules.classes.class_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column(
        "subclass_id",
        UUID(),
        ForeignKey("rules.subclasses.subclass_id", ondelete="RESTRICT"),
    ),
    Column("level", NONNEGATIVE_INTEGER, nullable=False),
    *_timestamps(),
    PrimaryKeyConstraint("character_build_id", "class_id"),
    schema="character",
    comment="A build's level in one class. Multiple rows per build support multiclassing.",
)

Index("ix_character_class_levels_class_id", character_class_levels.c.class_id)
Index(
    "ix_character_class_levels_subclass_id",
    character_class_levels.c.subclass_id,
    postgresql_where=character_class_levels.c.subclass_id.isnot(None),
)

character_proficiencies = Table(
    "character_proficiencies",
    metadata,
    _uuid_pk("character_proficiency_id"),
    Column(
        "character_build_id",
        UUID(),
        ForeignKey("character.character_builds.character_build_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "proficiency_type_id",
        UUID(),
        ForeignKey("rules.proficiency_types.proficiency_type_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("skill_id", UUID(), ForeignKey("rules.skills.skill_id", ondelete="CASCADE")),
    Column(
        "saving_throw_ability_id",
        UUID(),
        ForeignKey("rules.abilities.ability_id", ondelete="CASCADE"),
    ),
    Column("target_label", Text()),
    Column("is_expertise", Boolean(), nullable=False, server_default=text("false")),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    schema="character",
    comment=(
        "A build's proficiency in a skill, a saving-throw ability, or a free-text "
        "target (a weapon, armor category, or tool). Exactly one of skill_id, "
        "saving_throw_ability_id, and target_label is set."
    ),
)

Index("ix_character_proficiencies_build_id", character_proficiencies.c.character_build_id)
Index("ix_character_proficiencies_type_id", character_proficiencies.c.proficiency_type_id)
Index(
    "ix_character_proficiencies_skill_id",
    character_proficiencies.c.skill_id,
    postgresql_where=character_proficiencies.c.skill_id.isnot(None),
)
Index(
    "ix_character_proficiencies_saving_throw_ability_id",
    character_proficiencies.c.saving_throw_ability_id,
    postgresql_where=character_proficiencies.c.saving_throw_ability_id.isnot(None),
)
# Duplicate-prevention indexes added by revision 029 — a build cannot be
# granted the same semantic proficiency twice.
Index(
    "ux_character_proficiencies_build_skill",
    character_proficiencies.c.character_build_id,
    character_proficiencies.c.skill_id,
    unique=True,
    postgresql_where=character_proficiencies.c.skill_id.isnot(None),
)
Index(
    "ux_character_proficiencies_build_saving_throw",
    character_proficiencies.c.character_build_id,
    character_proficiencies.c.saving_throw_ability_id,
    unique=True,
    postgresql_where=character_proficiencies.c.saving_throw_ability_id.isnot(None),
)
Index(
    "ux_character_proficiencies_build_target_label",
    character_proficiencies.c.character_build_id,
    character_proficiencies.c.target_label,
    unique=True,
    postgresql_where=character_proficiencies.c.target_label.isnot(None),
)

character_features = Table(
    "character_features",
    metadata,
    Column(
        "character_build_id",
        UUID(),
        ForeignKey("character.character_builds.character_build_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "feature_id",
        UUID(),
        ForeignKey("rules.features.feature_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    PrimaryKeyConstraint("character_build_id", "feature_id"),
    schema="character",
    comment="A feature a build has been granted, from its class, subclass, or species.",
)

Index("ix_character_features_feature_id", character_features.c.feature_id)

character_spellcasting_profiles = Table(
    "character_spellcasting_profiles",
    metadata,
    _uuid_pk("character_spellcasting_profile_id"),
    Column(
        "character_build_id",
        UUID(),
        ForeignKey("character.character_builds.character_build_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("class_id", UUID(), ForeignKey("rules.classes.class_id", ondelete="CASCADE")),
    Column(
        "spellcasting_ability_id",
        UUID(),
        ForeignKey("rules.abilities.ability_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    UniqueConstraint("character_build_id", "class_id", name="ux_spellcasting_profiles_build_class"),
    schema="character",
    comment=(
        "A source of spellcasting for a build (Wizard casting, Warlock Pact Magic, "
        "...) and the ability it keys off. class_id is NULL for species- or "
        "feat-granted casting with no owning class."
    ),
)

Index("ix_spellcasting_profiles_build_id", character_spellcasting_profiles.c.character_build_id)
Index(
    "ix_spellcasting_profiles_class_id",
    character_spellcasting_profiles.c.class_id,
    postgresql_where=character_spellcasting_profiles.c.class_id.isnot(None),
)
Index(
    "ix_spellcasting_profiles_ability_id",
    character_spellcasting_profiles.c.spellcasting_ability_id,
)

character_known_spells = Table(
    "character_known_spells",
    metadata,
    Column(
        "character_spellcasting_profile_id",
        UUID(),
        ForeignKey(
            "character.character_spellcasting_profiles.character_spellcasting_profile_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    ),
    Column(
        "spell_id",
        UUID(),
        ForeignKey("rules.spells.spell_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    PrimaryKeyConstraint("character_spellcasting_profile_id", "spell_id"),
    schema="character",
    comment="Spells a spellcasting profile knows, independent of whether they are prepared.",
)

Index("ix_character_known_spells_spell_id", character_known_spells.c.spell_id)

character_prepared_spells = Table(
    "character_prepared_spells",
    metadata,
    Column(
        "character_spellcasting_profile_id",
        UUID(),
        ForeignKey(
            "character.character_spellcasting_profiles.character_spellcasting_profile_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    ),
    Column(
        "spell_id",
        UUID(),
        ForeignKey("rules.spells.spell_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    PrimaryKeyConstraint("character_spellcasting_profile_id", "spell_id"),
    schema="character",
    comment=(
        "Spells currently prepared for a spellcasting profile. Not constrained to be "
        "a subset of known spells: whether that subset relationship applies at all "
        "varies by class."
    ),
)

Index("ix_character_prepared_spells_spell_id", character_prepared_spells.c.spell_id)

# ---------------------------------------------------------------------------
# character — religious affiliations (revision 076)
# ---------------------------------------------------------------------------

character_religious_affiliations = Table(
    "character_religious_affiliations",
    metadata,
    _uuid_pk("character_religious_affiliation_id"),
    Column(
        "character_id",
        UUID(),
        ForeignKey("character.characters.character_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "religion_id",
        UUID(),
        ForeignKey("world.religions.religion_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("devotion", PERCENTAGE_0_100),
    Column("belief_status", Text(), nullable=False, server_default=text("'believer'::text")),
    Column("practice", Text()),
    Column("interpretation", Text()),
    Column("conflicts", Text()),
    Column("public_display", Boolean(), nullable=False, server_default=text("true")),
    *_timestamps(),
    UniqueConstraint(
        "character_id",
        "religion_id",
        name="ux_character_religious_affiliations_character_religion",
    ),
    schema="character",
    comment=(
        "A character's personal relationship with a religion — devotion, "
        "belief status, practice, interpretation, conflicts, public display "
        "(docs/DOMAIN_MODEL.md §10.7). Kept separate from organizational rank "
        "(world.organization_memberships) and employment "
        "(world.employment_relationships) — clergy office and organizational "
        "rank remain organization memberships, not this table."
    ),
)

Index(
    "ix_character_religious_affiliations_character_id",
    character_religious_affiliations.c.character_id,
)
Index(
    "ix_character_religious_affiliations_religion_id",
    character_religious_affiliations.c.religion_id,
)
