-- =====================================================
-- Settlement Religions Many-to-Many Relationship Table
-- =====================================================

DROP TABLE IF EXISTS public.settlement_religions CASCADE;

CREATE TABLE public.settlement_religions (
    settlement_religion_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    settlement_id UUID NOT NULL REFERENCES public.settlements(settlement_id) ON DELETE CASCADE,
    religion_id UUID NOT NULL REFERENCES public.religions(religion_id) ON DELETE CASCADE,
    
    -- Religious presence details
    adherent_percentage DECIMAL(5,2), -- Percentage of population following this religion
    adherent_estimate INTEGER, -- Estimated number of followers
    dominance_rank INTEGER, -- 1=most practiced, 2=second most, etc.
    influence_level_id UUID REFERENCES public.religious_influence_levels(influence_level_id),
    tolerance_level_id UUID REFERENCES public.religious_tolerance_levels(tolerance_level_id),
    
    -- Religious infrastructure
    temples_count INTEGER DEFAULT 0, -- Number of temples/major religious buildings
    shrines_count INTEGER DEFAULT 0, -- Number of shrines/minor religious sites
    clergy_count INTEGER DEFAULT 0, -- Number of religious officials
    religious_district VARCHAR(200), -- Specific areas with religious concentration
    
    -- Practice details
    public_worship BOOLEAN DEFAULT TRUE, -- Whether worship is done publicly
    local_customs TEXT, -- How the religion is practiced locally
    patron_status VARCHAR(50), -- Whether this is a patron religion of the settlement
    
    -- Historical context
    establishment_date DATE, -- When this religion was established here
    introduction_method VARCHAR(100), -- How it arrived (Missionary, Migration, Conquest, etc.)
    historical_significance TEXT, -- Important religious events in this settlement
    
    -- Metadata
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Ensure unique settlement-religion pairs
    UNIQUE(settlement_id, religion_id)
);

-- Indexes for efficient queries
CREATE INDEX idx_settlement_religions_settlement ON public.settlement_religions (settlement_id);
CREATE INDEX idx_settlement_religions_religion ON public.settlement_religions (religion_id);
CREATE INDEX idx_settlement_religions_dominance ON public.settlement_religions (dominance_rank);
CREATE INDEX idx_settlement_religions_influence ON public.settlement_religions (influence_level_id);
CREATE INDEX idx_settlement_religions_tolerance ON public.settlement_religions (tolerance_level_id);
CREATE INDEX idx_settlement_religions_patron ON public.settlement_religions (patron_status);

-- Trigger for updated_at
CREATE TRIGGER settlement_religions_updated_at_trigger
    BEFORE UPDATE ON public.settlement_religions
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

-- Comments
COMMENT ON TABLE public.settlement_religions IS 'Religious practices and presence in settlements';
COMMENT ON COLUMN public.settlement_religions.dominance_rank IS 'Ranking by number of adherents (1=most followers)';
COMMENT ON COLUMN public.settlement_religions.tolerance_level_id IS 'Foreign key to religious_tolerance_levels lookup table';
COMMENT ON COLUMN public.settlement_religions.patron_status IS 'Whether this religion has special status in the settlement';

-- Sample data (assuming Millbrook settlement and some religions exist)
-- Note: These INSERTs will only work if the referenced settlements and religions exist
/*
INSERT INTO public.settlement_religions (settlement_id, religion_id, adherent_percentage, dominance_rank, influence_level_id, tolerance_level_id, temples_count, shrines_count, patron_status, notes) VALUES
((SELECT settlement_id FROM public.settlements WHERE name = 'Millbrook'), 
 (SELECT religion_id FROM public.religions WHERE name = 'Order of the Eternal Flame'), 
 45.0, 1, 
 (SELECT influence_level_id FROM public.religious_influence_levels WHERE name = 'Moderate'),
 (SELECT tolerance_level_id FROM public.religious_tolerance_levels WHERE name = 'Accepted'),
 1, 2, 'Primary', 'Main temple serves as community center'),
((SELECT settlement_id FROM public.settlements WHERE name = 'Millbrook'), 
 (SELECT religion_id FROM public.religions WHERE name = 'The Old Ways'), 
 35.0, 2,
 (SELECT influence_level_id FROM public.religious_influence_levels WHERE name = 'Strong'),
 (SELECT tolerance_level_id FROM public.religious_tolerance_levels WHERE name = 'Favored'),
 0, 3, 'Traditional', 'Deeply rooted in local farming culture'),
((SELECT settlement_id FROM public.settlements WHERE name = 'Millbrook'), 
 (SELECT religion_id FROM public.religions WHERE name = 'Pantheon of the Seven Stars'), 
 20.0, 3,
 (SELECT influence_level_id FROM public.religious_influence_levels WHERE name = 'Minimal'),
 (SELECT tolerance_level_id FROM public.religious_tolerance_levels WHERE name = 'Tolerated'),
 0, 1, NULL, 'Followed mainly by traveling merchants');
*/