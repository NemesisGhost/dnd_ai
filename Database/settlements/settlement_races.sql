-- =====================================================
-- Settlement Races Many-to-Many Relationship Table
-- =====================================================

DROP TABLE IF EXISTS public.settlement_races CASCADE;

CREATE TABLE public.settlement_races (
    settlement_race_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    settlement_id UUID NOT NULL REFERENCES public.settlements(settlement_id) ON DELETE CASCADE,
    race_id UUID NOT NULL REFERENCES public.races(race_id) ON DELETE CASCADE,
    
    -- Population details
    population_percentage DECIMAL(5,2), -- Percentage of settlement population
    population_estimate INTEGER, -- Estimated number of individuals
    dominance_rank INTEGER, -- 1=most dominant, 2=second most, etc.
    integration_level VARCHAR(50) DEFAULT 'Integrated', -- Segregated, Separated, Mixed, Integrated, Dominant
    district_concentration VARCHAR(200), -- Specific areas where they concentrate
    arrival_period VARCHAR(100), -- When they first settled here
    cultural_influence VARCHAR(50) DEFAULT 'Moderate', -- Minimal, Moderate, Strong, Defining
    notes TEXT,
    
    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Ensure unique settlement-race pairs
    UNIQUE(settlement_id, race_id)
);

-- Indexes for efficient queries
CREATE INDEX idx_settlement_races_settlement ON public.settlement_races (settlement_id);
CREATE INDEX idx_settlement_races_race ON public.settlement_races (race_id);
CREATE INDEX idx_settlement_races_dominance ON public.settlement_races (dominance_rank);
CREATE INDEX idx_settlement_races_population ON public.settlement_races (population_percentage);
CREATE INDEX idx_settlement_races_integration ON public.settlement_races (integration_level);

-- Trigger for updated_at
CREATE TRIGGER settlement_races_updated_at_trigger
    BEFORE UPDATE ON public.settlement_races
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

-- Comments
COMMENT ON TABLE public.settlement_races IS 'Racial demographics and distribution in settlements';
COMMENT ON COLUMN public.settlement_races.dominance_rank IS 'Ranking of population size (1=largest group)';
COMMENT ON COLUMN public.settlement_races.integration_level IS 'How integrated this race is with the broader community';
COMMENT ON COLUMN public.settlement_races.cultural_influence IS 'How much this race influences settlement culture';

-- Sample data for Millbrook
-- Note: These INSERTs will only work if the Millbrook settlement and races exist
/*
INSERT INTO public.settlement_races (settlement_id, race_id, population_percentage, dominance_rank, integration_level, cultural_influence, notes) VALUES
((SELECT settlement_id FROM public.settlements WHERE name = 'Millbrook'), 
 (SELECT race_id FROM public.races WHERE name = 'Human'), 
 60.0, 1, 'Integrated', 'Defining', 'Founding population, established the town culture'),
((SELECT settlement_id FROM public.settlements WHERE name = 'Millbrook'), 
 (SELECT race_id FROM public.races WHERE name = 'Halfling'), 
 25.0, 2, 'Integrated', 'Strong', 'Major farming community, influential in local politics'),
((SELECT settlement_id FROM public.settlements WHERE name = 'Millbrook'), 
 (SELECT race_id FROM public.races WHERE name = 'Dwarf'), 
 15.0, 3, 'Integrated', 'Moderate', 'Skilled craftsmen and the current mayor');
*/