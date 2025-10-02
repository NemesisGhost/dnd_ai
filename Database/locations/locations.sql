-- =====================================================
-- Locations Table - Universal Location System
-- Supports settlements, regions, landmarks, territories, and all other location types
-- Replaces the need for separate settlement and geographic references
-- =====================================================

DROP TABLE IF EXISTS public.locations CASCADE;

-- Main Locations Table
CREATE TABLE public.locations (
    -- Primary identification
    location_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(200) NOT NULL,
    
    -- Location classification
    location_type_id UUID NOT NULL REFERENCES public.location_types(location_type_id),
    subtype VARCHAR(100), -- More specific categorization within type
    scale VARCHAR(50), -- Personal, Local, Regional, National, Continental, Global
    
    -- Hierarchical relationships
    parent_location_id UUID REFERENCES public.locations(location_id), -- What contains this location
    nation_id UUID, -- FK to nations table (for political hierarchy)
    
    -- Geographic information
    geographic_region VARCHAR(200), -- Named geographic region
    terrain_type_id UUID REFERENCES public.terrain_types(terrain_type_id), -- FK to terrain_types table
    climate_zone_id UUID REFERENCES public.climate_zones(climate_zone_id), -- FK to climate_zones table
    elevation_description VARCHAR(100), -- Sea level, Mountain peak, Underground, etc.
    notable_geography TEXT, -- Rivers, mountains, unique features nearby
    
    -- Physical characteristics
    physical_description TEXT, -- Overall appearance and characteristics
    layout_description TEXT, -- How it's organized/arranged (for settlements)
    architecture_style VARCHAR(200), -- Building styles, materials (for built locations)
    notable_features TEXT, -- Important aspects, landmarks, or characteristics
    size_description VARCHAR(100), -- Tiny, Small, Medium, Large, Massive, etc.
    
    -- For Settlements: Population and governance
    approximate_population INTEGER, -- Population count (for settlements)
    government_type VARCHAR(100), -- Democracy, Monarchy, Council, etc. (for settlements)
    current_leader VARCHAR(200), -- Name and title of leader (for settlements)
    leadership_structure TEXT, -- How governance works (for settlements)
    
    -- Cultural and social aspects
    -- languages_spoken now handled via locations_languages join table
    cultural_significance TEXT, -- Cultural importance and traditions
    religious_importance TEXT, -- Spiritual significance
    historical_significance TEXT, -- Historical importance
    
    -- Economic information (primarily for settlements)
    wealth_level VARCHAR(50), -- Impoverished, Poor, Modest, Prosperous, Wealthy
    trade_importance VARCHAR(50), -- Minor, Moderate, Major, Critical
    
    -- Accessibility and travel
    accessibility VARCHAR(50), -- Easy, Moderate, Difficult, Impossible
    travel_restrictions TEXT, -- Entry requirements, taxes, etc.
    transportation_hubs TEXT, -- Ports, stations, magical circles, etc.
    
    -- Current status and condition
    current_status VARCHAR(50) DEFAULT 'Active', -- Active, Abandoned, Ruined, Under Construction, etc.
    current_condition VARCHAR(50) DEFAULT 'Good', -- Excellent, Good, Fair, Poor, Ruined
    habitability VARCHAR(50), -- Thriving, Livable, Harsh, Dangerous, Uninhabitable
    
    -- Defenses and security (for settlements and strategic locations)
    fortification_level VARCHAR(50), -- None, Light, Moderate, Heavy, Fortress
    military_presence VARCHAR(50), -- None, Minimal, Moderate, Strong, Overwhelming
    security_notes TEXT, -- Details about defenses and guards
    
    -- Adventure and campaign relevance
    adventure_significance VARCHAR(50), -- None, Minor, Moderate, Major, Central
    secrets_and_mysteries TEXT, -- Hidden aspects players might discover
    dangers_present TEXT, -- Threats and hazards
    opportunities_available TEXT, -- Resources, quests, benefits
    
    -- Environmental factors
    magical_properties TEXT, -- Magical aspects or phenomena
    supernatural_presence VARCHAR(50), -- None, Minor, Moderate, Strong, Overwhelming
    climate_effects TEXT, -- Weather patterns, seasonal changes
    
    -- Knowledge and discovery
    public_knowledge_level VARCHAR(50), -- Unknown, Rumored, Known, Common Knowledge
    map_availability VARCHAR(50), -- Unmapped, Partially Mapped, Well Mapped
    exploration_status VARCHAR(50), -- Unexplored, Partially Explored, Well Known
    
    -- Metadata and organization
    dm_notes TEXT, -- Private DM information
    player_knowledge TEXT, -- What players have learned about this place
    campaign_relevance TEXT, -- Role in current story
    
    -- Documentation
    map_references TEXT, -- References to maps or visual aids
    source_material TEXT, -- Which books or documents describe this place
    inspiration_source TEXT, -- Real-world or fictional inspiration
    
    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);



-- Locations table indexes
CREATE INDEX idx_locations_name_search ON public.locations USING gin(to_tsvector('english', name));
CREATE INDEX idx_locations_type ON public.locations (location_type_id);
CREATE INDEX idx_locations_parent ON public.locations (parent_location_id);
CREATE INDEX idx_locations_nation ON public.locations (nation_id);
CREATE INDEX idx_locations_scale ON public.locations (scale);
CREATE INDEX idx_locations_status ON public.locations (current_status);
CREATE INDEX idx_locations_adventure_significance ON public.locations (adventure_significance);
CREATE INDEX idx_locations_knowledge_level ON public.locations (public_knowledge_level);
CREATE INDEX idx_locations_region ON public.locations (geographic_region);

-- =====================================================
-- Foreign key constraints now defined inline with column definitions
-- =====================================================

-- Trigger for updated_at on locations
CREATE TRIGGER locations_updated_at_trigger
    BEFORE UPDATE ON public.locations
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

-- =====================================================
-- Comments
-- =====================================================

COMMENT ON TABLE public.locations IS 'Universal locations table supporting all types of geographic, political, and structural locations';
COMMENT ON COLUMN public.locations.parent_location_id IS 'Self-referencing FK for hierarchical location relationships (city in region, district in city, etc.)';
COMMENT ON COLUMN public.locations.scale IS 'Geographic or political scale of the location';
COMMENT ON COLUMN public.locations.nation_id IS 'Political jurisdiction this location belongs to';

-- =====================================================
-- Sample Data
-- =====================================================

-- Sample locations for testing
INSERT INTO public.locations (
    name, location_type_id, scale, geographic_region,
    terrain_type_id, physical_description, current_status,
    public_knowledge_level
) VALUES 
(
    'The Whispering Woods',
    (SELECT location_type_id FROM public.location_types WHERE name = 'Forest'),
    'Regional',
    'Northern Reaches',
    (SELECT terrain_type_id FROM public.terrain_types WHERE name = 'Forest'),
    'Dense woodland where the trees seem to murmur secrets to those who listen carefully. Ancient oaks tower overhead, their branches forming a thick canopy that filters sunlight into dappled patterns.',
    'Active',
    'Common Knowledge'
),
(
    'Stormbreak Harbor',
    (SELECT location_type_id FROM public.location_types WHERE name = 'Harbor'),
    'Local',
    'Coastal Region',
    (SELECT terrain_type_id FROM public.terrain_types WHERE name = 'Coastal'),
    'A well-protected natural harbor with stone piers and lighthouse. The harbor can shelter dozens of ships during the fierce autumn storms.',
    'Active',
    'Common Knowledge'
),
(
    'The Sundered Bridge',
    (SELECT location_type_id FROM public.location_types WHERE name = 'Ruins'),
    'Local',
    'Central Valley',
    (SELECT terrain_type_id FROM public.terrain_types WHERE name = 'River Valley'),
    'Ancient stone bridge that once spanned the Great River. Now only the first two arches remain standing, the rest having collapsed into the churning waters below.',
    'Ruined',
    'Known'
);