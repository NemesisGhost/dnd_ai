"""Field-level data classification and the safe audit/receipt builders
(Phase 15 checkpoint 15.2A-3; see docs/adr/0016-data-classification-and-private-data-handling.md
once 15.2A-5 lands, and docs/DATABASE_CONVENTIONS.md §24).

Three things live here, none of which touch the database:

- `DataClass` and `COLUMN_CLASSES`: a class for every TEXT/JSONB column of the
  authored and state tables (`schema.table.column`). A test introspects the live
  schema and fails when a new such column has no entry, so adding a free-text
  column forces a classification decision. Lookup and ruleset-reference tables
  (`REFERENCE_DATA_TABLES`) are public reference data and need no entry.
- `audit_change` / `audit_initial`: the **default-deny** builders every typed
  authoring command uses for `audit.change_log.changed_fields`. Only fields named
  in `AUDIT_STRUCTURAL_FIELDS` (names, identifiers, enumerations, numbers) keep
  their values; every other field -- narrative, notes, statements, descriptions --
  records `{"redacted": true}` and nothing else. Audit is an accountability
  record ("this field changed"), never content history; canonical revision
  history is a separate store (15.2R).
- `content_receipt`: the minimal idempotency replay body. Replay storage and
  responses carry ids, `row_version`, and `created`/`changed` flags only.

`PLAYER_PRIVATE` is a reserved class: no column maps to it in Phase 15, and Phase
16 must not store its values in audit or replay storage either.
"""

import enum
import uuid
from collections.abc import Mapping
from typing import Any

REDACTED: dict[str, bool] = {"redacted": True}

# Structural values are short and non-narrative: names, identifiers, enumerated
# codes, numbers. Value-bearing in audit.
AUDIT_VALUE_MAX_LENGTH = 200


class DataClass(enum.Enum):
    PUBLIC_WORLD = "public_world"  # published canon any campaign member may read
    CAMPAIGN_VISIBLE = "campaign_visible"  # members of this campaign
    GM_ONLY = "gm_only"  # canon.edit holders only
    CHARACTER_VISIBLE = "character_visible"  # holders of a character's matching capability
    PARTY_VISIBLE = "party_visible"  # party-perspective holders
    PLAYER_PRIVATE = "player_private"  # reserved for Phase 16; unused in Phase 15
    SECRET = "secret"  # credentials, tokens, CSRF values
    STRUCTURAL = "structural"  # identifier, code, enumeration, number, system value


# Lookup and ruleset-reference tables: public reference data, no free text of
# consequence, so their text columns need no per-column classification. Kept in
# step with migration 115's `REPORTING_READABLE_TABLES` by a test.
REFERENCE_DATA_TABLES: frozenset[str] = frozenset(
    {
        "ai.agent_roles",
        "audit.change_actions",
        "campaign.connection_statuses",
        "campaign.hazard_statuses",
        "campaign.interactable_statuses",
        "campaign.objective_statuses",
        "campaign.organization_statuses",
        "campaign.quest_statuses",
        "campaign.relationship_statuses",
        "core.canon_statuses",
        "core.lifecycle_statuses",
        "core.name_types",
        "core.source_types",
        "core.world_time_precisions",
        "interaction.interaction_types",
        "knowledge.expertise_domains",
        "knowledge.knowledge_types",
        "knowledge.truth_statuses",
        "narrative.event_participant_roles",
        "narrative.event_statuses",
        "narrative.event_types",
        "narrative.objective_types",
        "rules.item_categories",
        "world.connection_types",
        "world.organization_types",
        "world.relationship_participant_roles",
        "world.relationship_types",
        "rules.abilities",
        "rules.classes",
        "rules.conditions",
        "rules.creature_types",
        "rules.damage_types",
        "rules.feats",
        "rules.features",
        "rules.languages",
        "rules.proficiency_types",
        "rules.resource_definitions",
        "rules.ruleset_versions",
        "rules.rulesets",
        "rules.skills",
        "rules.species",
        "rules.spells",
        "rules.subclasses",
        "core.alembic_version",
    }
)

_P = DataClass.PUBLIC_WORLD
_C = DataClass.CAMPAIGN_VISIBLE
_G = DataClass.GM_ONLY
_H = DataClass.CHARACTER_VISIBLE
_Y = DataClass.PARTY_VISIBLE
_S = DataClass.STRUCTURAL


def _table(prefix: str, columns: Mapping[str, DataClass]) -> dict[str, DataClass]:
    return {f"{prefix}.{column}": cls for column, cls in columns.items()}


# Every TEXT/JSONB column outside the reference tables above, by schema.table.column.
COLUMN_CLASSES: dict[str, DataClass] = {
    **_table("campaign.area_feature_state", {"condition_notes": _G}),
    **_table("campaign.campaigns", {"description": _C, "name": _C}),
    **_table("campaign.character_conditions", {"source_description": _G}),
    **_table("campaign.location_state", {"condition_notes": _G}),
    **_table("campaign.parties", {"description": _C, "name": _C}),
    **_table("campaign.party_knowledge", {"awareness_level": _S, "interpretation": _Y}),
    **_table("campaign.party_memberships", {"joined_reason": _G, "left_reason": _G}),
    **_table("campaign.relationship_state", {"emotional_tone": _G, "private_interpretation": _G}),
    **_table("campaign.session_participants", {"participation_role": _S}),
    **_table("campaign.sessions", {"summary": _C, "title": _C}),
    **_table("campaign.timelines", {"description": _C, "name": _C}),
    **_table("character.character_builds", {"label": _H}),
    **_table("character.character_descriptions", {"appearance": _C, "background": _C, "notes": _G}),
    **_table("character.character_movements", {"movement_type": _S}),
    **_table("character.character_proficiencies", {"target_label": _S}),
    **_table(
        "character.character_religious_affiliations",
        {"belief_status": _S, "conflicts": _H, "interpretation": _H, "practice": _H},
    ),
    **_table("character.character_senses", {"sense_type": _S}),
    **_table("character.characters", {"size_category": _S}),
    **_table("core.calendar_months", {"name": _P}),
    **_table(
        "core.calendars",
        {"code": _S, "description": _P, "display_name": _P, "epoch_label": _P},
    ),
    **_table("core.entities", {"canonical_name": _P, "summary": _P}),
    **_table("core.entity_names", {"language": _S, "name": _P, "notes": _G}),
    **_table("core.entity_revisions", {"revision_kind": _S, "snapshot": _G}),
    **_table(
        "core.entity_types",
        {
            "code": _S,
            "description": _S,
            "display_name": _S,
            "required_subtype_pk_column": _S,
            "required_subtype_table": _S,
        },
    ),
    **_table(
        "core.source_documents",
        {
            "classification": _G,
            "file_hash": _S,
            "file_hash_algorithm": _S,
            "publisher_or_author": _G,
            "removal_reason": _G,
            "source_version_label": _G,
            "status": _S,
            "title": _G,
            "usage_rights_notes": _G,
            "usage_rights_status": _S,
            "visibility": _S,
        },
    ),
    **_table("core.sources", {"description": _G, "reference": _G, "title": _G}),
    **_table("core.tags", {"code": _S, "description": _P, "display_name": _P}),
    **_table("core.world_times", {"label": _P}),
    **_table("core.worlds", {"description": _P, "name": _P, "slug": _S}),
    **_table("interaction.actions", {"description": _G}),
    **_table(
        "interaction.check_requests",
        {"advantage_state": _S, "check_kind": _S, "modifiers": _G, "stakes": _G},
    ),
    **_table("interaction.check_results", {"degree_of_success": _S, "external_system_source": _S}),
    **_table("interaction.combat_actions", {"action_kind": _S}),
    **_table("interaction.consequences", {"consequence_type": _S, "description": _G, "status": _S}),
    **_table(
        "interaction.external_messages",
        {"external_id": _S, "raw_payload": _G, "source_system": _S},
    ),
    **_table("interaction.interactions", {"status": _S, "summary": _G}),
    **_table("interaction.targets", {"target_component": _S, "target_description": _G}),
    **_table("knowledge.character_expertise", {"notes": _G, "proficiency_level": _S}),
    **_table("knowledge.entity_knowledge", {"awareness_level": _S, "interpretation": _H}),
    **_table(
        "knowledge.information_transfers", {"modified_interpretation": _H, "transfer_method": _S}
    ),
    **_table(
        "knowledge.item_identification",
        {"identification_level": _S, "known_properties_jsonb": _H},
    ),
    **_table("knowledge.knowledge_items", {"canonical_statement": _G, "sensitivity": _S}),
    **_table("knowledge.knowledge_versions", {"distortion_type": _S, "version_statement": _G}),
    **_table("knowledge.public_knowledge", {"awareness_level": _S}),
    **_table("narrative.encounter_participants", {"outcome": _S, "side": _S}),
    **_table("narrative.encounter_turns", {"notes": _G}),
    **_table("narrative.encounters", {"status": _S, "summary": _G}),
    **_table("narrative.event_causes", {"cause_description": _G}),
    **_table("narrative.event_corrections", {"correction_kind": _S, "reason": _G}),
    **_table(
        "narrative.event_effects",
        {
            "application_status": _S,
            "new_value": _G,
            "previous_value": _G,
            "target_component": _S,
        },
    ),
    **_table("narrative.event_locations", {"event_location_role": _S}),
    **_table("narrative.event_observations", {"observation_text": _H}),
    **_table("narrative.event_participants", {"notes": _G}),
    **_table("narrative.events", {"details": _G}),
    **_table("narrative.objective_dependencies", {"dependency_type": _S}),
    **_table(
        "narrative.quest_objectives",
        {
            "completion_mode": _S,
            "completion_rule": _G,
            "description": _C,
            "name": _C,
            "requirement_level": _S,
            "visibility_policy": _S,
        },
    ),
    **_table(
        "narrative.quest_outcomes",
        {"code": _S, "description": _G, "name": _G, "outcome_category": _S},
    ),
    **_table("narrative.quest_participants", {"participant_role": _S}),
    **_table("narrative.quests", {"gm_notes": _G}),
    **_table("narrative.quest_rewards", {"description": _G, "reward_type": _S}),
    **_table("narrative.quest_stages", {"description": _C, "name": _C, "stage_type": _S}),
    **_table("narrative.story_arcs", {"description": _G, "name": _C, "status": _S}),
    **_table(
        "rules.item_definitions",
        {
            "code": _S,
            "description": _P,
            "display_name": _P,
            "properties_jsonb": _G,
            "rarity": _S,
        },
    ),
    **_table(
        "world.area_connections",
        {"condition_description": _G, "description": _G, "required_check_kind": _S},
    ),
    **_table("world.area_features", {"description": _G, "feature_type": _S}),
    **_table("world.area_hazards", {"description": _G, "hazard_type": _S}),
    **_table("world.area_interactables", {"description": _G, "interactable_type": _S}),
    **_table("world.buildings", {"building_use": _P}),
    **_table("world.businesses", {"business_type": _S, "operating_status": _S}),
    **_table(
        "world.dungeon_areas",
        {"area_type": _P, "dimensions": _P, "environmental_properties": _G},
    ),
    **_table("world.employment_relationships", {"job_title": _C}),
    **_table("world.family_relationships", {"family_unit_name": _C}),
    **_table("world.governments", {"government_form": _P}),
    **_table("world.item_instances", {"origin_notes": _G}),
    **_table("world.military_units", {"unit_type": _S}),
    **_table("world.organization_memberships", {"rank": _C, "role": _C}),
    **_table("world.organizations", {"internal_description": _G, "public_description": _P}),
    **_table("world.political_factions", {"ideology": _P}),
    **_table("world.political_relationships", {"treaty_terms": _G}),
    **_table("world.relationship_participants", {"notes": _G}),
    **_table(
        "world.relationship_perspectives", {"emotional_tone": _G, "private_interpretation": _G}
    ),
    **_table("world.relationships", {"description": _G}),
    **_table("world.religions", {"pantheon_structure": _P}),
}


# --- Audit builders (default deny) ------------------------------------------------------

# Audit field names (the keys typed authoring commands pass) whose values are
# names, identifiers, enumerated codes, or numbers. Everything else is redacted.
AUDIT_STRUCTURAL_FIELDS: frozenset[str] = frozenset(
    {
        "name",
        "category",
        "kind",
        "population",
        "size_category",
        "species_id",
        "origin_location_id",
        "parent_location_id",
        "parent_organization_id",
        "headquarters_location_id",
        "religion_id",
        "subject_entity_id",
        "target_entity_id",
        "knowledge_type",
        "sensitivity",
        "truth_status",
        "completion_mode",
        "objective_type",
        "requirement_level",
        "sequence_number",
        "stage_type",
        "quantity_required",
        "visibility_policy",
        "objectives_removed",
        "rewards_removed",
        "organization_type",
        "calendar_id",
        "current_world_time_id",
        "year",
        "month_number",
        "day",
        "hour",
        "minute",
        "precision",
        "sort_key",
        "days_per_week",
        "month_count",
        "operating_status",
        "reputation",
        "superseded_by_entity_id",
        "ruleset_version_id",
        "character_build_id",
        "current_hit_points",
        "maximum_hit_points",
        "ability_count",
        "class_level_count",
        "proficiency_count",
        "feature_count",
        "spellcasting_count",
        "spell_count",
        "scheduled_for",
        "participation_role",
        "dependency_type",
        "objective_id",
        "depends_on_objective_id",
        "outcome_category",
        "reward_type",
        "participant_role",
        "quest_outcome_id",
        "code",
        "event_status",
        "awareness_level",
        "confidence",
        "willing_to_share",
        "transfer_method",
        "knowledge_item_id",
        "knower_entity_id",
        "recipient_entity_id",
        "location_id",
        "quest_status",
        "objective_status",
        "correction_kind",
        "start_world_time_id",
        "end_world_time_id",
        "world_time_id",
        "party_id",
        "member_entity_id",
        "effective_from_world_time_id",
        "effective_to_world_time_id",
    }
)


def _audit_value(field: str, value: object) -> object:
    """The audit representation of one field value: kept (bounded) when the
    field is structural, `{"redacted": true}` when it carries content, and
    `None` stays `None` (absence is not content)."""
    if value is None:
        return None
    if field in AUDIT_STRUCTURAL_FIELDS:
        if isinstance(value, str) and len(value) > AUDIT_VALUE_MAX_LENGTH:
            return {"value": value[:AUDIT_VALUE_MAX_LENGTH], "truncated": True}
        return value
    return dict(REDACTED)


def audit_change(field: str, old: object, new: object) -> dict[str, object]:
    """`{"from": ..., "to": ...}` for one changed field, content redacted."""
    return {"from": _audit_value(field, old), "to": _audit_value(field, new)}


def audit_initial(values: Mapping[str, object]) -> dict[str, object]:
    """Initial values for a `created` audit row (non-null fields only), content
    redacted."""
    return {key: _audit_value(key, value) for key, value in values.items() if value is not None}


def audit_diff(
    before: Mapping[str, object], after: Mapping[str, object]
) -> dict[str, dict[str, object]]:
    """`{field: {"from", "to"}}` for every field whose value changed."""
    return {
        key: audit_change(key, before.get(key), new_value)
        for key, new_value in after.items()
        if before.get(key) != new_value
    }


# --- Idempotency receipts --------------------------------------------------------------


def content_receipt(
    *,
    id_field: str,
    entity_id: uuid.UUID,
    row_version: int,
    created: bool,
    changed: bool,
    record_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """The minimal replay body: ids, `row_version`, and flags -- never a name,
    statement, note, or nested view. `record_id` names a child record (a quest
    stage or objective) the command wrote."""
    body: dict[str, Any] = {
        id_field: str(entity_id),
        "row_version": row_version,
        "created": created,
        "changed": changed,
    }
    if record_id is not None and record_id != entity_id:
        body["record_id"] = str(record_id)
    return body
