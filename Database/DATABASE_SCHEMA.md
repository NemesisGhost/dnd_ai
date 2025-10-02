# **D&D AI Database Schema Documentation**

This document provides comprehensive documentation for the PostgreSQL database schema used in the D&D AI system. The database is designed specifically for world-building and AI integration, emphasizing narrative elements over mechanical D&D stats.

## **Database Design Philosophy**

### **Core Design Principles**
- **Narrative Focus**: Emphasizes personality, relationships, and story elements over game mechanics
- **AI Integration**: Structured for ChatGPT personality modeling and contextual responses
- **Flexible Relationships**: JSONB fields and many-to-many tables for complex data structures
- **Search Optimization**: Full-text search indexes for natural language queries
- **Player Knowledge Management**: Separate DM and player information to maintain discovery and mystery

### **Key Features**
- **118 SQL tables** with normalized, 3NF-compliant design
- **Fully normalized structure** with minimal complex types for optimal performance
- **Complex relationship modeling** for realistic NPC interactions
- **Full-text search optimization** for natural language queries
- **Player knowledge management** with information asymmetry support

## **Database Statistics**

- **Total Tables**: 118
- **Primary Key Strategy**: UUID-based for distributed system compatibility
- **Foreign Key Relationships**: Comprehensive referential integrity
- **Indexes**: 300+ optimized for query performance
- **Full-Text Search**: Enabled on all text fields
- **JSONB Fields**: 0 (all normalized into proper relationship tables)

## **Recent Normalization Improvements**

The database has been fully normalized to eliminate complex types and improve performance:

### **Eliminated Complex Types**:
- **`organizations.chapter_locations` JSONB** → `organization_chapters` table with FK to `locations`
- **`organizations.areas_of_operation` TEXT[]** → `organization_areas_of_operation` many-to-many table
- **`npc_significant_events.triggers` TEXT[]** → `npc_event_triggers` child table
- **`organization_relationships.tags` TEXT[]** → `organization_relationship_tags` many-to-many table
- **`organization_services.tags` TEXT[]** → `organization_service_tags` many-to-many table

### **Remaining Minimal Complex Types**:
- **`settlements.languages_spoken` TEXT[]** - Simple language list for settlements
- **`religions.pilgrimage_sites` TEXT[]** - Simple site name list for religions

### **Benefits of Normalization**:
- **Better Performance**: Proper indexing on normalized relationships
- **Data Integrity**: Foreign key constraints ensure referential integrity
- **Query Flexibility**: Join tables allow complex queries and filtering
- **Scalability**: Normalized structure handles growth better than embedded JSON/arrays

## **Complete Database Schema Structure**

```
                           D&D AI Database Schema - Complete UML Structure
                         ══════════════════════════════════════════════════════

┌─────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                            CORE NPC SYSTEM                                                      │
├─────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                                                 │
│   ┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐    ┌──────────────────┐                  │
│   │ races           │    │ age_categories   │    │ social_statuses │    │ npc_statuses     │                  │
│   ├─────────────────┤    ├──────────────────┤    ├─────────────────┤    ├──────────────────┤                  │
│   │ race_id (PK)    │    │ category_id (PK) │    │ status_id (PK)  │    │ status_id (PK)   │                  │
│   │ name            │    │ name             │    │ name            │    │ name             │                  │
│   │ description     │    │ description      │    │ description     │    │ description      │                  │
│   │ typical_traits  │    │ age_range        │    │ social_power    │    │ impact_on_npc    │                  │
│   └─────────────────┘    │ maturity_level   │    │ wealth_level    │    └──────────────────┘                  │
│            │             │ life_experience  │    │ influence       │             │                             │
│            │             └──────────────────┘    └─────────────────┘             │                             │
│            │                      │                       │                      │                             │
│            └──────────────────────┼───────────────────────┼──────────────────────┘                             │
│                                   │                       │                                                    │
│                                   ▼                       ▼                                                    │
│                            ┌─────────────────────────────────────────────────────────────┐                     │
│                            │                      npcs                                  │                     │
│                            ├─────────────────────────────────────────────────────────────┤                     │
│                            │ npc_id (PK)                                                 │                     │
│                            │ name, race_id (FK), age_category_id (FK)                    │                     │
│                            │ social_status_id (FK), current_status_id (FK)               │                     │
│                            │ personality_summary, conversation_style                     │                     │
│                            │ speech_pattern, mannerisms, motivations                     │                     │
│                            │ occupation, reputation, location                            │                     │
│                            │ personality_prompt, dm_notes                                │                     │
│                            │ NOTE: triggers now normalized into npc_event_triggers       │                     │
│                            └─────────────────────────────────────────────────────────────┘                     │
│                                                     │                                                           │
└─────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
                                                      │
┌─────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                           OCCUPATION SYSTEM                                                     │
├─────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                                                 │
│   ┌─────────────────────┐              ┌─────────────────────┐              ┌─────────────────────┐             │
│   │occupation_categories│              │    occupations      │              │  knowledge_areas    │             │
│   ├─────────────────────┤              ├─────────────────────┤              ├─────────────────────┤             │
│   │ category_id (PK)    │◄─────────────┤ occupation_id (PK)  │              │ knowledge_area_id   │             │
│   │ name                │              │ name                │              │ (PK)                │             │
│   │ description         │              │ category_id (FK)    │              │ name, category      │             │
│   └─────────────────────┘              │ description         │              │ description, rarity │             │
│                                        └─────────────────────┘              └─────────────────────┘             │
│                                                 │                                       ▲                       │
│                                                 │                                       │                       │
│                                                 ▼                                       │                       │
│                                   ┌─────────────────────────────────────────────────────────┐                 │
│                                   │         occupation_knowledge_areas                      │                 │
│                                   ├─────────────────────────────────────────────────────────┤                 │
│                                   │ occupation_id (FK), knowledge_area_id (FK)              │                 │
│                                   │ proficiency_level, is_typical                           │                 │
│                                   │ PRIMARY KEY (occupation_id, knowledge_area_id)          │                 │
│                                   └─────────────────────────────────────────────────────────┘                 │
│                                                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
                                                      │
┌─────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                         WORLD ENTITIES SYSTEM                                                   │
├─────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                                                 │
│ ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────────────┐   │
│ │ settlements  │  │   nations    │  │organizations │  │  businesses  │  │         locations                │   │
│ ├──────────────┤  ├──────────────┤  ├──────────────┤  ├──────────────┤  ├──────────────────────────────────┤   │
│ │settlement_id │  │ nation_id    │  │organization_ │  │ business_id  │  │ location_id (PK)                 │   │
│ │(PK)          │  │(PK)          │  │id (PK)       │  │(PK)          │  │ name, location_type_id           │   │
│ │name, type    │  │name, govt    │  │name, type    │  │name, type    │  │ parent_location_id, nation_id    │   │
│ │population    │  │territory     │  │purpose       │  │services      │  │ terrain_type_id, climate_zone_id │   │
│ │government    │  │demographics  │  │membership    │  │ownership     │  │ physical_description             │   │
│ │economy       │  │military      │  │activities    │  │reputation    │  │ current_status                   │   │
│ │culture       │  │relations     │  │influence     │  │atmosphere    │  │ adventure_significance           │   │
│ │notable_npcs  │  │current_events│  │secrets       │  │adventure_    │  │ public_knowledge_level           │   │
│ │adventure_    │  │adventure_    │  │adventure_    │  │relevance     │  │ NOTE: Organizations table now    │   │
│ │hooks         │  │opportunities │  │opportunities │  └──────────────┘  │ includes world entities          │   │
│ └──────────────┘  └──────────────┘  └──────────────┘                     └──────────────────────────────────┘   │
│                                                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
                                                      │
┌─────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                        TOPICS & CONVERSATION SYSTEM                                             │
├─────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                                                 │
│   ┌─────────────────┐                    ┌─────────────────────────────────────┐                               │
│   │topic_categories │                    │              npc_topics             │                               │
│   ├─────────────────┤                    ├─────────────────────────────────────┤                               │
│   │ category_id (PK)│◄───────────────────┤ topic_id (PK)                       │                               │
│   │ name            │                    │ topic_name, category_id (FK)        │                               │
│   │ description     │                    │ topic_description                   │                               │
│   └─────────────────┘                    │ enthusiasm_level, knowledge_depth   │                               │
│                                          │ willingness_to_discuss              │                               │
│                                          │ emotional_association               │                               │
│                                          │ conversation_triggers               │                               │
│                                          │ requires_trust_level                │                               │
│                                          └─────────────────────────────────────┘                               │
│                                                         │                                                       │
│                                                         │                                                       │
│                 ┌───────────────────────────────────────┼─────────────────────────────────────┐                 │
│                 │                                       │                                     │                 │
│                 ▼                                       ▼                                     ▼                 │
│   ┌─────────────────────────────┐        ┌─────────────────────────────┐        ┌─────────────────────────────┐ │
│   │ npc_topic_assignments       │        │   topic_relationships       │        │ npc_topic_connections       │ │
│   ├─────────────────────────────┤        ├─────────────────────────────┤        ├─────────────────────────────┤ │
│   │ assignment_id (PK)          │        │ relationship_id (PK)        │        │ connection_id (PK)          │ │
│   │ npc_id (FK), topic_id (FK)  │        │ source_topic_id (FK)        │        │ primary_npc_id (FK)         │ │
│   │ personal_spin               │        │ target_topic_id (FK)        │        │ connected_npc_id (FK)       │ │
│   │ confidence_level            │        │ relationship_type           │        │ topic_id (FK)               │ │
│   │ last_discussed_with_party   │        │ transition_probability      │        │ connection_type             │ │
│   │ times_discussed             │        │ notes                       │        │ connection_strength         │ │
│   │ UNIQUE(npc_id, topic_id)    │        │ UNIQUE(source, target, type)│        │ is_public_knowledge         │ │
│   └─────────────────────────────┘        └─────────────────────────────┘        │ UNIQUE(primary,connected,   │ │
│                                                                                   │        topic)               │ │
│                                                                                   └─────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
                                                      │
┌─────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                        EVENTS & RELATIONSHIPS SYSTEM                                            │
├─────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                                                 │
│ ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────────┐                           │
│ │event_categories │ │emotional_impact │ │current_relevance│ │player_knowledge     │                           │
│ │                 │ │_types           │ │_levels          │ │_levels              │                           │
│ ├─────────────────┤ ├─────────────────┤ ├─────────────────┤ ├─────────────────────┤                           │
│ │ category_id (PK)│ │impact_type_id   │ │relevance_level_ │ │knowledge_level_id   │                           │
│ │ name            │ │(PK)             │ │id (PK)          │ │(PK)                 │                           │
│ │ description     │ │ name            │ │ name            │ │ name                │                           │
│ │ typical_impact  │ │ description     │ │ description     │ │ description         │                           │
│ │_range           │ │ typical_        │ │ behavioral_     │ │ dm_guidance         │                           │
│ └─────────────────┘ │ behaviors       │ │ indicators      │ │ reveal_probability  │                           │
│          │          └─────────────────┘ │ conversation_   │ └─────────────────────┘                           │
│          │                   │          │ likelihood      │          │                                        │
│          │                   │          └─────────────────┘          │                                        │
│          └───────────────────┼──────────────────┬────────────────────┘                                        │
│                              │                  │                                                             │
│                              ▼                  ▼                                                             │
│                   ┌─────────────────────────────────────────────────────────────┐                            │
│                   │               npc_significant_events                        │                            │
│                   ├─────────────────────────────────────────────────────────────┤                            │
│                   │ event_id (PK), npc_id (FK)                                  │                            │
│                   │ event_title, event_description                              │                            │
│                   │ category_id (FK), emotional_impact_id (FK)                  │                            │
│                   │ current_relevance_id (FK), player_knowledge_id (FK)         │                            │
│                   │ event_date, impact_level                                    │                            │
│                   │ affects_personality, dm_notes                               │                            │
│                   │ NOTE: triggers now normalized into npc_event_triggers       │                            │
│                   └─────────────────────────────────────────────────────────────┘                            │
│                                              │                                                                │
│                              ┌───────────────┼─────────────────┐                                              │
│                              │               │                 │                                              │
│                              ▼               ▼                 ▼                                              │
│             ┌─────────────────────────────┐ ┌─────────────────────────────┐ ┌─────────────────────────────┐  │
│             │event_location_connections   │ │  event_npc_connections      │ │   npc_relationships         │  │
│             ├─────────────────────────────┤ ├─────────────────────────────┤ ├─────────────────────────────┤  │
│             │ connection_id (PK)          │ │ connection_id (PK)          │ │ relationship_id (PK)        │  │
│             │ event_id (FK)               │ │ event_id (FK)               │ │ npc_id (FK)                 │  │
│             │ location_name               │ │ connected_npc_id (FK)       │ │ related_npc_id (FK)         │  │
│             │ location_type               │ │ primary_npc_id (FK)         │ │ relationship_type           │  │
│             │ significance_to_event       │ │ role_in_event               │ │ relationship_strength       │  │
│             │ emotional_association       │ │ relationship_at_time        │ │ current_status              │  │
│             │ can_return, notes           │ │ current_relationship_       │ │ history, public_knowledge   │  │
│             └─────────────────────────────┘ │ affected                    │ │ affects_interactions        │  │
│                                             │ knows_full_story            │ │ trust_level, emotional_     │  │
│                                             │ emotional_impact_on_        │ │ context                     │  │
│                                             │ connected                   │ │ last_interaction_date       │  │
│                                             │ willing_to_discuss          │ │ UNIQUE(npc_id,related_npc)  │  │
│                                             │ CHECK(connected≠primary)    │ └─────────────────────────────┘  │
│                                             └─────────────────────────────┘                                  │
│                                                                                                               │
└─────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
                                                      │
┌─────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                         KNOWLEDGE & INFORMATION SYSTEM                                          │
├─────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                                                 │
│             ┌─────────────────────────────────────────────────────────────────────────────────────────┐       │
│             │                              npc_knowledge                                               │       │
│             ├─────────────────────────────────────────────────────────────────────────────────────────┤       │
│             │ knowledge_id (PK)                                                                         │       │
│             │ npc_id (FK), knowledge_area_id (FK)                                                       │       │
│             │ knowledge_level, confidence_level, source_of_knowledge                                    │       │
│             │ last_updated, is_secret, willing_to_share                                                 │       │
│             │ verification_status, notes                                                                │       │
│             │ UNIQUE(npc_id, knowledge_area_id)                                                         │       │
│             └─────────────────────────────────────────────────────────────────────────────────────────┘       │
│                                         │                       ▲                                             │
│                                         │                       │                                             │
│                                         ▼                       │                                             │
│                              ┌─────────────────────────────────────────────┐                                 │
│                              │        npc_organization_memberships        │                                 │
│                              ├─────────────────────────────────────────────┤                                 │
│                              │ membership_id (PK)                          │                                 │
│                              │ npc_id (FK), organization_name              │                                 │
│                              │ role, membership_type, status               │                                 │
│                              │ join_date, influence_level                  │                                 │
│                              │ public_knowledge, benefits                  │                                 │
│                              │ obligations, notes                          │                                 │
│                              └─────────────────────────────────────────────┘                                 │
│                                                                                                               │
└─────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘

                                         TAGGING & CLASSIFICATION SYSTEM
                         ════════════════════════════════════════════════════════════════════════════════
┌─────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                                                                                                 │
│   ┌─────────────────┐              ┌─────────────────────┐              ┌─────────────────────────────────────┐ │
│   │tag_categories   │              │        tags         │              │    ENTITY-SPECIFIC TAG TABLES       │ │
│   ├─────────────────┤              ├─────────────────────┤              ├─────────────────────────────────────┤ │
│   │ category_id (PK)│◄─────────────┤ tag_id (PK)         │              │ • npc_tag_assignments               │ │
│   │ name            │              │ name                │              │ • business_tags                     │ │
│   │ description     │              │ category_id (FK)    │──────────────│ • organization_tags                 │ │
│   │ color_code      │              │ description         │              │ • settlement_tags                   │ │
│   │ icon            │              │ color, icon         │              │ • nation_tags                       │ │
│   │ usage_guidelines│              │ usage_guidelines    │              │ • religion_tag_assignments         │ │
│   └─────────────────┘              │ is_system_tag       │              │ • service_tags                      │ │
│                                    └─────────────────────┘              │                                     │ │
│                                                                         │ Each follows pattern:               │ │
│                                                                         │ entity_id (FK), tag_id (FK)        │ │
│                                                                         │ assignment metadata                 │ │
│                                                                         └─────────────────────────────────────┘ │
│                                                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

## **Core Entity Tables**
- `settlement_id` (UUID PK), `name`, `settlement_type_id` (FK)
- `nation_id` (FK), `terrain_type`, `approximate_population`
- `government_type`, `current_leader`, `wealth_level`
- `languages_spoken` (TEXT[]), `cultural_notes`, `defenses`
**Relationships**: Links to nations, settlement_types, multiple relationship tables

### `nations.sql` - Political Entities
**Purpose**: Kingdoms, empires, republics with political and cultural data
**Key Fields**:
- `nation_id` (UUID PK), `name`, `government_type`
- `capital_city_id` (FK to locations), `current_ruler`
- `trade_relationships` (JSONB), `diplomatic_status` (JSONB)
- `total_population_estimate`, `military_strength`
**Relationships**: Links to locations, multiple child and relationship tables

### `locations/locations.sql` - Universal Location System
**Purpose**: Comprehensive location system supporting all geographic and structural entities
**Key Fields**:
- `location_id` (UUID PK), `name`, `location_type_id` (FK)
- `parent_location_id` (self-referencing FK), `nation_id` (FK)
- `terrain_type_id` (FK), `climate_zone_id` (FK)
- `approximate_population`, `accessibility`, `magical_properties`
**Relationships**: Self-referencing hierarchy, links to nations, terrain_types, climate_zones

### `religions/religions.sql` - Faith Systems
**Purpose**: Religions, deities, belief systems
**Key Fields**:
- `religion_id` (UUID PK), `name`, `religion_type`, `alignment`
- `primary_deity`, `pantheon_name`, `core_beliefs`
- `pilgrimage_sites` (TEXT[]), `geographic_spread`, `influence_level`
**Relationships**: Links to NPCs via npc_religions, settlements via settlement_religions

---

## 2. Lookup/Reference Tables

All located in `lookups/` directory (25 total):

### Core Demographics
- `races.sql` - Character races (Human, Elf, Dwarf, etc.)
- `age_categories.sql` - Age classifications
- `languages.sql` - Spoken languages
- `social_statuses.sql` - Social standing levels

### Geographic/Environmental
- `climate_zones.sql` - Climate classifications
- `terrain_types.sql` - Terrain categories
- `location_types.sql` - Location classifications
- `settlement_types.sql` - Settlement categories and size ranges

### Business/Economic
- `service_categories.sql` - Service type classifications
- `cost_types.sql` - Cost categorizations
- `quality_levels.sql` - Quality ratings
- `market_reach_levels.sql` - Market scope classifications
- `trade_specialty_types.sql` - Trade specialization types
- `trade_volume_levels.sql` - Trade volume categories

### Social/Political
- `relationship_types.sql` - Relationship classifications
- `relationship_categories.sql` - Relationship groupings
- `relationship_intensity_levels.sql` - Relationship strength
- `relationship_statuses.sql` - Relationship states
- `occupation_categories.sql` - Job classifications
- `employee_roles.sql` - Employee position types

### Game/Campaign Management
- `player_knowledge_levels.sql` - What players know
- `current_relevance_levels.sql` - Campaign relevance
- `sensitivity_levels.sql` - Information sensitivity
- `rumor_categories.sql` - Rumor types
- `event_categories.sql` - Event classifications
- `topic_categories.sql` - Discussion topic types

### Religious/Cultural
- `religious_influence_levels.sql` - Religious power levels
- `religious_tolerance_levels.sql` - Religious acceptance
- `skill_levels.sql` - Skill proficiency levels
- `presence_levels.sql` - Presence/influence strength
- `rarity_levels.sql` - Item/information rarity
- `influence_types.sql` - Types of influence
- `emotional_impact_types.sql` - Emotional effect categories
- `knowledge_areas.sql` - Fields of knowledge
- `tag_categories.sql` - Tag classifications

---

## 3. Relationship/Junction Tables

### NPC Relationships (14 tables in `npcs/`)
- `npc_organization_memberships.sql` - NPCs ↔ Organizations (many-to-many)
- `npc_relationships.sql` - NPC ↔ NPC social connections (with relationship details)
- `npc_occupations.sql` - NPCs ↔ Occupations (many-to-many)
- `npc_religions.sql` - NPCs ↔ Religions (many-to-many) 
- `npc_services.sql` - Services provided by NPCs
- `npc_tag_assignments.sql` - NPCs ↔ Tags (many-to-many)
- `npc_topics.sql` - Discussion topics associated with NPCs
- `npc_knowledge.sql` - Knowledge areas NPCs possess
- `npc_rumors.sql` - Rumors associated with NPCs
- `npc_significant_events.sql` - Important events in NPC lives
- `npc_event_triggers.sql` - Event triggers for significant events (normalized from TEXT[])
- `npc_dispositions.sql` - NPC attitude/mood states
- `npc_statuses.sql` - Current status of NPCs
- `npc_personality_traits.sql` - NPC personality characteristics

### Business Relationships (6 tables in `business/`)
- `business_relationships.sql` - Business ↔ Business connections
- `business_services.sql` - Services offered by businesses
- `business_tags.sql` - Business ↔ Tags (many-to-many)
- `business_employees.sql` - Businesses ↔ NPCs (employment)
- `business_payment_methods.sql` - Payment options accepted
- `business_types.sql` - Business type classifications

### Organization Relationships (12 tables in `organizations/`)
- `organization_associations.sql` - Organization ↔ Organization relationships
- `organization_relationships.sql` - Detailed org-to-org connections
- `organization_npc_associations.sql` - Organizations ↔ NPCs
- `organization_activities.sql` - Activities organizations perform
- `organization_core_values.sql` - Core values of organizations
- `organization_tags.sql` - Organization ↔ Tags (many-to-many)
- `organization_services.sql` - Services provided by organizations
- `organization_chapters.sql` - Chapter/branch locations (normalized from JSONB)
- `organization_leaders.sql` - Leadership positions and holders
- `organization_areas_of_operation.sql` - Organizations ↔ Locations (areas of operation, normalized from TEXT[])
- `organization_relationship_tags.sql` - Organization Relationships ↔ Tags (normalized from TEXT[])
- `organization_service_tags.sql` - Organization Services ↔ Tags (normalized from TEXT[])

### Location Relationships (3 tables in `locations/`)
- `locations_languages.sql` - Locations ↔ Languages (many-to-many)
- `locations_resources.sql` - Locations ↔ Resources (many-to-many)
- `location_relationships.sql` - Location ↔ Location connections

### Settlement Relationships (6 tables in `settlements/`)
- `settlement_races.sql` - Settlements ↔ Races (demographics)
- `settlement_religions.sql` - Settlements ↔ Religions (presence)
- `settlement_organizations.sql` - Settlements ↔ Organizations
- `settlement_industries.sql` - Settlement economic activities
- `settlement_tags.sql` - Settlement ↔ Tags (many-to-many)
- `settlement_trade_specialties.sql` - Settlement trade focuses
- `settlement_religious_festivals.sql` - Religious celebrations

### Nation Relationships (14 tables in `relationships/`)
- `nation_allies.sql` - Nation ↔ Nation alliances
- `nation_relationships.sql` - Nation ↔ Nation diplomatic relations
- `nation_races.sql` - Nations ↔ Races (demographics)
- `nation_languages.sql` - Nations ↔ Languages (official/common)
- `nation_resources.sql` - Nations ↔ Resources (natural resources)
- `nation_exports.sql` - Nation export products
- `nation_imports.sql` - Nation import needs
- `nation_tags.sql` - Nations ↔ Tags (many-to-many)
- `nation_climate_zones.sql` - Nations ↔ Climate Zones
- `nation_terrain_types.sql` - Nations ↔ Terrain Types
- `nation_location_relationships.sql` - Nations ↔ Locations
- `nation_political_factions.sql` - Internal political groups

### Cross-Entity Relationships (8 tables in `relationships/`)
- `business_organization_memberships.sql` - Businesses ↔ Organizations
- `event_location_connections.sql` - Events ↔ Locations
- `event_npc_connections.sql` - Events ↔ NPCs
- `location_routes.sql` - Travel routes between locations
- `npc_topic_assignments.sql` - NPCs ↔ Topics (knowledge)
- `npc_topic_connections.sql` - NPC ↔ Topic relationships
- `occupation_knowledge_areas.sql` - Occupations ↔ Knowledge Areas
- `organization_territory_control.sql` - Organizations ↔ Territory control
- `organization_resources.sql` - Organizations ↔ Resources
- `religion_tag_assignments.sql` - Religions ↔ Tags
- `rumor_npc_connections.sql` - Rumors ↔ NPCs
- `topic_relationships.sql` - Topic ↔ Topic connections

### Nation Detail Tables (2 tables in `nations/`)
- `nation_holidays.sql` - National holidays and celebrations
- `nation_social_classes.sql` - Social class hierarchies

### Religion Relationships (2 tables in `religions/`)
- `religion_relationships.sql` - Religion ↔ Religion connections
- `religion_tags_extension.sql` - Extended religion tagging

---

## 4. Attribute/Detail Tables

### Top-level Shared Tables (6 tables in root)
- `tags.sql` - Universal tagging system
- `services.sql` - Service definitions
- `service_tags.sql` - Services ↔ Tags
- `resources.sql` - Natural/economic resources
- `occupations.sql` - Job/profession definitions

---

## 5. Complex Fields & JSONB Usage

### Confirmed JSONB Fields:
**None remaining** - All previously documented JSONB fields have been normalized into proper relationship tables.

### Array Fields:
- `settlements.sql`: `languages_spoken` (TEXT[])
- `religions.sql`: `pilgrimage_sites` (TEXT[])

### Complex TEXT Fields (Potential JSONB Candidates):
- Most entities use TEXT fields for flexible narrative content that could benefit from structured JSONB storage
- Examples: cultural_notes, relationships, special_properties, historical_events

---

## 6. Complete Table Inventory

**Total: 118 SQL files organized as:**

- **Root Level**: 1 file (tags.sql)
- **business/**: 7 files (core table + 6 relationship/detail tables)
- **locations/**: 3 files (core table + 2 relationship tables)
- **lookups/**: 35 files (all reference/enumeration tables)
- **migrations/**: 0 files (empty folder for schema changes)
- **nations/**: 2 files (child tables for holidays and social classes)
- **npcs/**: 15 files (core table + 14 relationship/detail tables)
- **organizations/**: 13 files (core table + 12 relationship/detail tables)
- **relationships/**: 26 files (cross-entity relationship tables)
- **religions/**: 3 files (core table + 2 relationship tables)
- **settlements/**: 8 files (core table + 7 relationship/detail tables)
- **world/**: 5 files (nations, occupations, resources, services, service_tags)

---

## 7. Relationships & Dependencies

### Dependency Hierarchy:
1. **Level 1 (No Dependencies)**: All lookup tables in `lookups/`
2. **Level 2 (Basic Entities)**: `races`, `languages`, `terrain_types`, `climate_zones`
3. **Level 3 (Geographic)**: `locations` (depends on location_types, terrain_types, climate_zones)
4. **Level 4 (Political)**: `nations` (depends on locations)
5. **Level 5 (Settlements)**: `settlements` (depends on nations, locations, settlement_types)
6. **Level 6 (Complex Entities)**: `npcs`, `businesses`, `organizations`, `religions`
7. **Level 7 (Relationships)**: All junction/relationship tables

### Key Relationship Patterns:
- **Self-Referencing**: `locations` (parent_location_id), `npc_relationships`
- **Many-to-Many**: Extensive use of junction tables for flexible relationships
- **One-to-Many**: Core entities to their detail/attribute tables
- **Cross-References**: Entities reference each other (NPCs ↔ Businesses ↔ Organizations)

---

## 8. Normalization Analysis

### 3rd Normal Form Compliance:
✅ **1NF**: All tables use atomic values, no repeating groups
✅ **2NF**: All non-key attributes depend on complete primary key  
✅ **3NF**: No transitive dependencies - all lookup data separated

### Normalization Strengths:
- Extensive use of lookup tables eliminates redundancy
- Junction tables properly handle many-to-many relationships
- Attribute tables separate optional/multiple-value data
- Foreign key constraints ensure referential integrity

### Potential Improvements:
- Some JSONB fields could be further normalized if complex queries are needed
- Consider partitioning large tables (npcs, organizations) if they grow significantly
- Array fields (TEXT[]) could use junction tables for better query performance

### JSONB vs. Normalization Trade-offs:
- Most TEXT fields: Appropriate for narrative content
- All complex relationship data: Now properly normalized into dedicated relationship tables
- Array fields: Remaining TEXT[] arrays are for simple lists (languages, pilgrimage sites)
- Database is now fully normalized with minimal complex types

---

**Total Tables Documented: 118**  
**Last Updated**: October 1, 2025  
**Schema Status**: Fully normalized, 3NF compliant, optimized for D&D world-building and AI integration
