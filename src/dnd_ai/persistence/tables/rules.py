"""Rules tables — rules schema.

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
    _provenance_columns,
    _timestamps,
    _uuid_pk,
    metadata,
)

# ---------------------------------------------------------------------------
# rules — rulesets and ruleset versions (revision 013)
# ---------------------------------------------------------------------------

rulesets = Table(
    "rulesets",
    metadata,
    _uuid_pk("ruleset_id"),
    Column("code", Text(), nullable=False),
    Column("display_name", Text(), nullable=False),
    Column("description", Text()),
    Column(
        "source_id",
        UUID(),
        ForeignKey("core.sources.source_id", ondelete="SET NULL"),
    ),
    # canon_status_id added by revision 025 — rules.rulesets had source_id
    # from the start but was missing this, contradicting its own comment
    # below (which was already true about source_id and became true about
    # canon status once this column existed).
    Column(
        "canon_status_id",
        UUID(),
        ForeignKey("core.canon_statuses.canon_status_id", ondelete="RESTRICT"),
        nullable=False,
        # PostgreSQL rejects a bare subquery in a column DEFAULT — matches the
        # STABLE SQL function every other rule-content table's canon_status_id
        # default calls (revision 025's rules.default_canon_status_id()).
        server_default=text("rules.default_canon_status_id()"),
        comment=(
            "How authoritative this ruleset is. Homebrew rulesets typically start at "
            "draft/proposed rather than canon (docs/architecture/DATABASE_MODEL.md §8)."
        ),
    ),
    *_timestamps(),
    UniqueConstraint("code", name="ux_rulesets_code"),
    schema="rules",
    comment=(
        'A named, edition-neutral rule-system family (e.g. "D&D 5e") — a specific edition '
        "or revision is recorded on rules.ruleset_versions.version_label and description, "
        "not here. Homebrew rulesets are ordinary rows here with their own source and "
        "canon status (docs/PLAN.md §6.2) — not a separate structure."
    ),
)

ruleset_versions = Table(
    "ruleset_versions",
    metadata,
    _uuid_pk("ruleset_version_id"),
    Column(
        "ruleset_id",
        UUID(),
        ForeignKey("rules.rulesets.ruleset_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("version_label", Text(), nullable=False),
    Column("description", Text()),
    Column(
        "is_current",
        Boolean(),
        nullable=False,
        server_default=text("false"),
        comment=(
            "The version to use when none is pinned explicitly. At most one per ruleset, "
            "enforced by a partial unique index rather than a CHECK, since the rule spans "
            "rows."
        ),
    ),
    *_provenance_columns(),
    *_timestamps(),
    UniqueConstraint("ruleset_id", "version_label", name="ux_ruleset_versions_ruleset_label"),
    schema="rules",
    comment=(
        "A version within a ruleset. Rule-content tables reference a version rather than "
        "a bare ruleset, since two versions of the same ruleset may define the same-named "
        "thing differently."
    ),
)

Index(
    "ix_rulesets_source_id",
    rulesets.c.source_id,
    postgresql_where=rulesets.c.source_id.isnot(None),
)
Index("ix_rulesets_canon_status_id", rulesets.c.canon_status_id)
Index("ix_ruleset_versions_ruleset_id", ruleset_versions.c.ruleset_id)
Index(
    "ix_ruleset_versions_source_id",
    ruleset_versions.c.source_id,
    postgresql_where=ruleset_versions.c.source_id.isnot(None),
)
Index("ix_ruleset_versions_canon_status_id", ruleset_versions.c.canon_status_id)
Index(
    "ux_ruleset_versions_one_current_per_ruleset",
    ruleset_versions.c.ruleset_id,
    unique=True,
    postgresql_where=ruleset_versions.c.is_current,
)

# ---------------------------------------------------------------------------
# rules — ruleset-scoped lookup content (revision 014)
# ---------------------------------------------------------------------------


def _ruleset_lookup_table(name: str, pk: str, comment: str) -> Table:
    """A ruleset-version-scoped lookup, per revision 014's shared shape."""
    return Table(
        name,
        metadata,
        _uuid_pk(pk),
        Column(
            "ruleset_version_id",
            UUID(),
            ForeignKey("rules.ruleset_versions.ruleset_version_id", ondelete="CASCADE"),
            nullable=False,
        ),
        Column("code", Text(), nullable=False),
        Column("display_name", Text(), nullable=False),
        Column("description", Text()),
        *_provenance_columns(),
        *_timestamps(),
        UniqueConstraint("ruleset_version_id", "code", name=f"ux_{name}_ruleset_version_code"),
        schema="rules",
        comment=comment,
    )


abilities = _ruleset_lookup_table(
    "abilities",
    "ability_id",
    "A scored capability a character has (Strength, Dexterity, ...). Governs skills "
    "and saving throws.",
)
species = _ruleset_lookup_table(
    "species",
    "species_id",
    "A playable ancestry (Human, Elf, ...). One of the identity-level references on "
    "character.characters (docs/architecture/DATABASE_MODEL.md §7.1).",
)
damage_types = _ruleset_lookup_table(
    "damage_types",
    "damage_type_id",
    "A category of damage (fire, slashing, ...) that resistances, vulnerabilities, "
    "and immunities key off.",
)
conditions = _ruleset_lookup_table(
    "conditions",
    "condition_id",
    "A status a character can be under (poisoned, prone, ...). Definitions only — "
    "campaign.character_conditions (Phase 4 timeline state) tracks who currently has "
    "one.",
)
creature_types = _ruleset_lookup_table(
    "creature_types",
    "creature_type_id",
    "A monster-manual classification (beast, fiend, undead, ...), distinct from "
    "species: a character has a species, any character or monster has a creature "
    "type.",
)
languages = _ruleset_lookup_table(
    "languages",
    "language_id",
    "A language a character can know or speak, referenced by character.character_languages.",
)
proficiency_types = _ruleset_lookup_table(
    "proficiency_types",
    "proficiency_type_id",
    "A category of proficiency (weapon, armor, tool, skill, saving throw) that "
    "character.character_proficiencies rows are typed by.",
)
resource_definitions = _ruleset_lookup_table(
    "resource_definitions",
    "resource_definition_id",
    "A depletable/rechargeable resource kind (spell slot, ki point, rage use, ...). "
    "Definitions only — campaign.character_resources (Phase 4 timeline state) tracks "
    "current and maximum amounts.",
)

for _t in (
    abilities,
    species,
    damage_types,
    conditions,
    creature_types,
    languages,
    proficiency_types,
    resource_definitions,
):
    Index(f"ix_{_t.name}_ruleset_version_id", _t.c.ruleset_version_id)
    Index(f"ix_{_t.name}_source_id", _t.c.source_id, postgresql_where=_t.c.source_id.isnot(None))
    Index(f"ix_{_t.name}_canon_status_id", _t.c.canon_status_id)

# target_kind added by revision 029, specific to proficiency_types alone —
# not part of the shared _ruleset_lookup_table shape.
proficiency_types.append_column(
    Column(
        "target_kind",
        Text(),
        nullable=False,
        comment=(
            "Which column of character.character_proficiencies a proficiency of this "
            "type must set: skill_id, saving_throw_ability_id, or the free-text "
            "target_label (weapon/armor/tool categories with no dedicated lookup yet). "
            "Enforced by trigger on character.character_proficiencies."
        ),
    )
)

skills = Table(
    "skills",
    metadata,
    _uuid_pk("skill_id"),
    Column(
        "ruleset_version_id",
        UUID(),
        ForeignKey("rules.ruleset_versions.ruleset_version_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "ability_id",
        UUID(),
        ForeignKey("rules.abilities.ability_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("code", Text(), nullable=False),
    Column("display_name", Text(), nullable=False),
    Column("description", Text()),
    *_provenance_columns(),
    *_timestamps(),
    UniqueConstraint("ruleset_version_id", "code", name="ux_skills_ruleset_version_code"),
    schema="rules",
    comment="A trained capability governed by one ability (Stealth -> Dexterity, ...).",
)

Index("ix_skills_ruleset_version_id", skills.c.ruleset_version_id)
Index("ix_skills_ability_id", skills.c.ability_id)
Index("ix_skills_source_id", skills.c.source_id, postgresql_where=skills.c.source_id.isnot(None))
Index("ix_skills_canon_status_id", skills.c.canon_status_id)

# ---------------------------------------------------------------------------
# rules — classes, subclasses, features, feats, spells (revision 015)
# ---------------------------------------------------------------------------

classes = Table(
    "classes",
    metadata,
    _uuid_pk("class_id"),
    Column(
        "ruleset_version_id",
        UUID(),
        ForeignKey("rules.ruleset_versions.ruleset_version_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("code", Text(), nullable=False),
    Column("display_name", Text(), nullable=False),
    Column("description", Text()),
    Column("hit_die", NONNEGATIVE_INTEGER, nullable=False),
    Column(
        "primary_ability_id",
        UUID(),
        ForeignKey("rules.abilities.ability_id", ondelete="RESTRICT"),
    ),
    *_provenance_columns(),
    *_timestamps(),
    UniqueConstraint("ruleset_version_id", "code", name="ux_classes_ruleset_version_code"),
    schema="rules",
    comment=(
        "A playable class definition (Fighter, Wizard, ...). character_class_levels "
        "references this to record a character's levels in it."
    ),
)

Index("ix_classes_ruleset_version_id", classes.c.ruleset_version_id)
Index(
    "ix_classes_primary_ability_id",
    classes.c.primary_ability_id,
    postgresql_where=classes.c.primary_ability_id.isnot(None),
)
Index("ix_classes_source_id", classes.c.source_id, postgresql_where=classes.c.source_id.isnot(None))
Index("ix_classes_canon_status_id", classes.c.canon_status_id)

subclasses = Table(
    "subclasses",
    metadata,
    _uuid_pk("subclass_id"),
    Column(
        "class_id",
        UUID(),
        ForeignKey("rules.classes.class_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "ruleset_version_id",
        UUID(),
        ForeignKey("rules.ruleset_versions.ruleset_version_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("code", Text(), nullable=False),
    Column("display_name", Text(), nullable=False),
    Column("description", Text()),
    *_provenance_columns(),
    *_timestamps(),
    UniqueConstraint("class_id", "code", name="ux_subclasses_class_code"),
    schema="rules",
    comment=(
        "A specialization within a class (Champion within Fighter, ...). Unique per "
        "class, not per ruleset version — two different classes may each define their "
        "own subclass with the same code."
    ),
)

Index("ix_subclasses_class_id", subclasses.c.class_id)
Index("ix_subclasses_ruleset_version_id", subclasses.c.ruleset_version_id)
Index(
    "ix_subclasses_source_id",
    subclasses.c.source_id,
    postgresql_where=subclasses.c.source_id.isnot(None),
)
Index("ix_subclasses_canon_status_id", subclasses.c.canon_status_id)

features = Table(
    "features",
    metadata,
    _uuid_pk("feature_id"),
    Column(
        "ruleset_version_id",
        UUID(),
        ForeignKey("rules.ruleset_versions.ruleset_version_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("class_id", UUID(), ForeignKey("rules.classes.class_id", ondelete="CASCADE")),
    Column("subclass_id", UUID(), ForeignKey("rules.subclasses.subclass_id", ondelete="CASCADE")),
    Column("species_id", UUID(), ForeignKey("rules.species.species_id", ondelete="CASCADE")),
    Column("code", Text(), nullable=False),
    Column("display_name", Text(), nullable=False),
    Column("description", Text()),
    Column(
        "granted_at_level",
        NONNEGATIVE_INTEGER,
        comment=(
            "The class or subclass level at which this feature is gained. NULL for "
            "species traits, which are not level-gated."
        ),
    ),
    *_provenance_columns(),
    *_timestamps(),
    UniqueConstraint("ruleset_version_id", "code", name="ux_features_ruleset_version_code"),
    schema="rules",
    comment=(
        "A granted trait or ability — a class feature, subclass feature, or species "
        "trait. The three associations are independently nullable, not mutually "
        "exclusive: which combinations are meaningful is rules content, not structure."
    ),
)

Index("ix_features_ruleset_version_id", features.c.ruleset_version_id)
Index(
    "ix_features_source_id", features.c.source_id, postgresql_where=features.c.source_id.isnot(None)
)
Index("ix_features_canon_status_id", features.c.canon_status_id)
Index("ix_features_class_id", features.c.class_id, postgresql_where=features.c.class_id.isnot(None))
Index(
    "ix_features_subclass_id",
    features.c.subclass_id,
    postgresql_where=features.c.subclass_id.isnot(None),
)
Index(
    "ix_features_species_id",
    features.c.species_id,
    postgresql_where=features.c.species_id.isnot(None),
)

feats = Table(
    "feats",
    metadata,
    _uuid_pk("feat_id"),
    Column(
        "ruleset_version_id",
        UUID(),
        ForeignKey("rules.ruleset_versions.ruleset_version_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("code", Text(), nullable=False),
    Column("display_name", Text(), nullable=False),
    Column("description", Text()),
    Column("prerequisite_description", Text()),
    *_provenance_columns(),
    *_timestamps(),
    UniqueConstraint("ruleset_version_id", "code", name="ux_feats_ruleset_version_code"),
    schema="rules",
    comment=(
        "An optional feat a character may take. prerequisite_description is free text "
        "for now — structured, machine-checkable prerequisites are a later refinement."
    ),
)

Index("ix_feats_ruleset_version_id", feats.c.ruleset_version_id)
Index("ix_feats_source_id", feats.c.source_id, postgresql_where=feats.c.source_id.isnot(None))
Index("ix_feats_canon_status_id", feats.c.canon_status_id)

spells = Table(
    "spells",
    metadata,
    _uuid_pk("spell_id"),
    Column(
        "ruleset_version_id",
        UUID(),
        ForeignKey("rules.ruleset_versions.ruleset_version_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("code", Text(), nullable=False),
    Column("display_name", Text(), nullable=False),
    Column("description", Text()),
    Column("level", NONNEGATIVE_INTEGER, nullable=False),
    Column("school", Text()),
    Column("casting_time", Text()),
    Column("range", Text()),
    Column("duration", Text()),
    Column(
        "damage_type_id",
        UUID(),
        ForeignKey("rules.damage_types.damage_type_id", ondelete="RESTRICT"),
    ),
    *_provenance_columns(),
    *_timestamps(),
    UniqueConstraint("ruleset_version_id", "code", name="ux_spells_ruleset_version_code"),
    schema="rules",
    comment=(
        "A spell definition. level 0 is a cantrip. damage_type_id is set only for "
        "spells that deal typed damage."
    ),
)

Index("ix_spells_ruleset_version_id", spells.c.ruleset_version_id)
Index(
    "ix_spells_damage_type_id",
    spells.c.damage_type_id,
    postgresql_where=spells.c.damage_type_id.isnot(None),
)
Index("ix_spells_source_id", spells.c.source_id, postgresql_where=spells.c.source_id.isnot(None))
Index("ix_spells_canon_status_id", spells.c.canon_status_id)

# ---------------------------------------------------------------------------
# rules — world_rulesets (revision 016)
# ---------------------------------------------------------------------------

world_rulesets = Table(
    "world_rulesets",
    metadata,
    Column(
        "world_id",
        UUID(),
        ForeignKey("core.worlds.world_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "ruleset_id",
        UUID(),
        ForeignKey("rules.rulesets.ruleset_id", ondelete="RESTRICT"),
        nullable=False,
    ),
    # is_default removed by revision 027: core.worlds.default_ruleset_id is
    # now the sole source of truth for a world's default ruleset, so this
    # table is a pure allow-list with no default concept of its own.
    Column("added_at", TIMESTAMP(timezone=True), nullable=False, server_default=text("now()")),
    PrimaryKeyConstraint("world_id", "ruleset_id"),
    schema="rules",
    comment=(
        "Associates a world with the rulesets it allows. A world may allow more than "
        "one ruleset; its default is core.worlds.default_ruleset_id alone (not "
        "represented here — see the reconciliation note in revision 027)."
    ),
)

Index("ix_world_rulesets_ruleset_id", world_rulesets.c.ruleset_id)
