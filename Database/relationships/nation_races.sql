-- =====================================================
-- Nation Races Relationship Table (Many-to-Many)
-- =====================================================

DROP TABLE IF EXISTS public.nation_races CASCADE;
CREATE TABLE public.nation_races (
    relationship_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nation_id UUID NOT NULL REFERENCES public.nations(nation_id) ON DELETE CASCADE,
    race_id UUID NOT NULL REFERENCES public.races(race_id) ON DELETE CASCADE,
    
    -- Race demographics
    demographic_type VARCHAR(50) NOT NULL, -- 'Dominant', 'Major', 'Minor', 'Rare'
    population_percentage DECIMAL(5,2), -- Approximate percentage of total population
    population_estimate INTEGER, -- Estimated number of individuals
    
    -- Integration and status
    social_status VARCHAR(100), -- How this race is viewed in society
    integration_level VARCHAR(50), -- 'Fully Integrated', 'Accepted', 'Tolerated', 'Marginalized', 'Oppressed'
    rights_and_privileges TEXT, -- What legal/social rights they have
    common_occupations TEXT, -- What jobs they typically hold
    
    -- Geographic distribution
    regional_concentration TEXT, -- Where in the nation they're most common
    settlement_patterns TEXT, -- How they organize their communities
    
    -- Cultural aspects
    cultural_contribution TEXT, -- How they influence national culture
    maintained_traditions TEXT, -- Unique cultural practices they preserve
    
    -- Metadata
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    UNIQUE(nation_id, race_id)
);

-- =====================================================
-- Indexes for Performance
-- =====================================================

CREATE INDEX idx_nation_races_nation ON public.nation_races (nation_id);
CREATE INDEX idx_nation_races_race ON public.nation_races (race_id);
CREATE INDEX idx_nation_races_demographic_type ON public.nation_races (demographic_type);

-- =====================================================
-- Triggers for Updated Timestamps
-- =====================================================

CREATE TRIGGER nation_races_updated_at_trigger
    BEFORE UPDATE ON public.nation_races
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

-- =====================================================
-- Comments
-- =====================================================

COMMENT ON TABLE public.nation_races IS 'Many-to-many relationship between nations and their racial demographics';
COMMENT ON COLUMN public.nation_races.demographic_type IS 'Dominant, Major, Minor, or Rare population within the nation';
COMMENT ON COLUMN public.nation_races.population_percentage IS 'Approximate percentage of total national population';
COMMENT ON COLUMN public.nation_races.integration_level IS 'Level of social acceptance and integration within the nation';