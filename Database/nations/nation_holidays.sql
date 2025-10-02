-- =====================================================
-- Nation Holidays Child Table
-- Requires: nations_main.sql
-- =====================================================

DROP TABLE IF EXISTS public.nation_holidays CASCADE;

CREATE TABLE public.nation_holidays (
    holiday_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nation_id UUID NOT NULL REFERENCES public.nations(nation_id) ON DELETE CASCADE,
    
    -- Holiday details
    name VARCHAR(200) NOT NULL,
    holiday_type VARCHAR(50), -- 'Religious', 'National', 'Seasonal', 'Historical', 'Royal', 'Harvest', 'Military'
    significance_level VARCHAR(50), -- 'Major', 'Important', 'Local', 'Minor', 'Regional'
    
    -- Timing and duration
    date_type VARCHAR(50), -- 'Fixed Date', 'Lunar Calendar', 'Seasonal', 'Variable', 'Royal Decree'
    specific_date VARCHAR(100), -- When it occurs (can be descriptive)
    duration_days INTEGER DEFAULT 1, -- How many days it lasts
    preparation_period TEXT, -- How long people prepare beforehand
    
    -- Historical significance
    origin_story TEXT, -- Why the holiday was created
    historical_significance TEXT, -- What historical event it commemorates
    founding_date VARCHAR(100), -- When the holiday was first celebrated
    evolution_over_time TEXT, -- How the holiday has changed
    
    -- Observance and traditions
    traditional_activities TEXT, -- What people typically do
    religious_ceremonies TEXT, -- Religious aspects of the celebration
    public_events TEXT, -- Government or community organized events
    private_traditions TEXT, -- What families/individuals do
    special_foods TEXT, -- Traditional meals or treats
    customary_dress TEXT, -- Special clothing worn
    
    -- Participation and scope
    participation_level VARCHAR(50), -- 'Universal', 'Widespread', 'Common', 'Limited', 'Elite Only'
    geographic_scope VARCHAR(50), -- 'National', 'Regional', 'Local', 'Capital Only', 'Rural Only'
    mandatory_observance BOOLEAN DEFAULT FALSE, -- Is participation required by law
    
    -- Economic and social impact
    economic_impact TEXT, -- How it affects commerce and trade
    work_stoppage BOOLEAN DEFAULT FALSE, -- Do people stop working
    government_closure BOOLEAN DEFAULT FALSE, -- Do government offices close
    social_expectations TEXT, -- Social pressure to participate
    
    -- Modern relevance
    current_popularity VARCHAR(50), -- How much people care about it now
    changing_traditions TEXT, -- How observance is evolving
    generational_differences TEXT, -- How different ages view the holiday
    
    -- Adventure relevance
    adventure_opportunities TEXT, -- How this holiday can create adventures
    security_concerns TEXT, -- Special risks during the holiday
    visitor_participation TEXT, -- How foreigners can participate
    
    -- Metadata
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- =====================================================
-- Indexes
-- =====================================================

CREATE INDEX idx_nation_holidays_nation ON public.nation_holidays (nation_id);
CREATE INDEX idx_nation_holidays_type ON public.nation_holidays (holiday_type);
CREATE INDEX idx_nation_holidays_significance ON public.nation_holidays (significance_level);

-- =====================================================
-- Triggers
-- =====================================================

CREATE TRIGGER nation_holidays_updated_at_trigger
    BEFORE UPDATE ON public.nation_holidays
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

-- =====================================================
-- Comments
-- =====================================================

COMMENT ON TABLE public.nation_holidays IS 'Child table for national holidays and celebrations';