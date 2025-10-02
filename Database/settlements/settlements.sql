-- =====================================================
-- Cities/Towns Table - Settlemen-- Indexes for common queries
CREATE INDEX idx_settlements_name_search ON public.settlements USING gin(to_tsvector('english', name));
CREATE INDEX idx_settlements_nation ON public.settlements (nation_id);
CREATE INDEX idx_settlements_type ON public.settlements (settlement_type_id);
CREATE INDEX idx_settlements_region ON public.settlements (region);d Building
-- =====================================================

DROP TABLE IF EXISTS public.settlements CASCADE;

CREATE TABLE public.settlements (
    -- Primary identification
    settlement_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(200) NOT NULL,
    
    -- Settlement classification
    settlement_type_id UUID NOT NULL REFERENCES public.settlement_types(settlement_type_id), -- FK to settlement_types lookup table (category='type')
    approximate_population INTEGER,
    
    -- Geographic information
    region VARCHAR(200), -- Geographic region name
    nation_id UUID REFERENCES public.nations(nation_id), -- FK to nations table
    terrain_type VARCHAR(100), -- Coastal, Mountain, Forest, Plains, Desert, etc.
    climate VARCHAR(100), -- Temperate, Tropical, Arctic, Arid, etc.
    notable_geography TEXT, -- Rivers, mountains, unique features nearby
    
    -- Physical description
    layout_description TEXT, -- How the settlement is organized/arranged
    architecture_style VARCHAR(200), -- Building styles, materials, cultural influences
    notable_landmarks TEXT, -- Important buildings, monuments, natural features
    districts_or_quarters TEXT, -- Named areas within the settlement
    
    -- Government & Leadership
    government_type VARCHAR(100), -- Democracy, Monarchy, Council, Guild-run, etc.
    current_leader VARCHAR(200), -- Name and title of leader
    leadership_structure TEXT, -- How governance works
    laws_and_customs TEXT, -- Important local rules and traditions
    
    -- Economic information
    wealth_level VARCHAR(50), -- Impoverished, Poor, Modest, Prosperous, Wealthy
    currency_used VARCHAR(100), -- Standard coins, local currency, barter, etc.
    market_days TEXT, -- When and where markets occur
    
    -- Cultural aspects
    languages_spoken TEXT[], -- Common languages heard here
    cultural_notes TEXT, -- Traditions, festivals, social norms
    education_level VARCHAR(50), -- Illiterate, Basic, Educated, Scholarly
    
    -- Social atmosphere
    general_attitude VARCHAR(100), -- Friendly, Suspicious, Hostile, Welcoming, etc.
    attitude_toward_outsiders VARCHAR(100), -- How they treat strangers
    attitude_toward_magic VARCHAR(100), -- Accepted, Feared, Regulated, Banned, etc.
    social_issues TEXT, -- Current problems or tensions
    
    -- Notable features
    defenses TEXT, -- Walls, guards, military presence
    notable_businesses TEXT, -- Important shops, inns, services
    secrets_and_rumors TEXT, -- Hidden aspects players might discover
    
    -- Travel & Access
    accessibility TEXT, -- How easy it is to reach
    major_roads_or_routes TEXT, -- Important travel connections
    transportation_options TEXT, -- Ships, caravans, magical travel, etc.
    travel_restrictions TEXT, -- Entry requirements, taxes, etc.
    
    -- Adventure hooks
    current_events TEXT, -- What's happening now
    problems_needing_solutions TEXT, -- Potential quests or issues
    opportunities TEXT, -- Things players might pursue here
    
    -- Historical information
    founding_history TEXT, -- How and when it was established
    significant_historical_events TEXT, -- Important past events
    historical_figures TEXT, -- Notable people from the past
    
    -- Status & Metadata
    current_status VARCHAR(50) DEFAULT 'Thriving', -- Thriving, Declining, Under Siege, Abandoned, etc.
    last_updated DATE DEFAULT CURRENT_DATE,
    dm_notes TEXT, -- Private DM information
    player_knowledge TEXT, -- What players have learned about this place
    adventure_relevance TEXT, -- How this relates to current campaigns
    
    -- References and organization
    map_references TEXT, -- References to maps or visual aids
    source_material TEXT, -- Which books or documents describe this place
    
    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for common queries
CREATE INDEX idx_settlements_name_search ON public.settlements USING gin(to_tsvector('english', name));
CREATE INDEX idx_settlements_nation ON public.settlements (nation_id);
CREATE INDEX idx_settlements_type ON public.settlements (settlement_type_id);
CREATE INDEX idx_settlements_region ON public.settlements (region);
CREATE INDEX idx_settlements_industries ON public.settlements USING gin(primary_industries);

-- Foreign key constraints now defined inline with column definitions

-- Trigger for updated_at
CREATE TRIGGER settlements_updated_at_trigger
    BEFORE UPDATE ON public.settlements
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

-- Comments
COMMENT ON TABLE public.settlements IS 'Cities, towns, and settlements with world-building focus';
COMMENT ON COLUMN public.settlements.districts_or_quarters IS 'Named neighborhoods or districts within the settlement';

-- Sample settlement
INSERT INTO public.settlements (
    name, settlement_type_id, approximate_population,
    region, terrain_type, layout_description,
    government_type, current_leader,
    general_attitude, notable_landmarks,
    current_events
) VALUES (
    'Millbrook',
    (SELECT settlement_type_id FROM public.settlement_types WHERE name = 'Town'),
    800,
    'Greendale Valley',
    'River Valley',
    'Built along both sides of the Miller River, connected by an ancient stone bridge. Most buildings are timber and stone, clustered around the central market square.',
    'Town Council',
    'Mayor Aldric Stoneheart (Dwarf)',
    'Friendly and welcoming to travelers',
    'The Old Mill (converted to town hall), Stone Bridge (dwarven construction), Riverside Inn',
    'Recent increase in goblin raids has the town council considering hiring adventurers'
);