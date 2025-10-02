-- =====================================================
-- Nation Climate Zones (Many-to-Many) Relationship Table
-- =====================================================

-- Nation Climate Zones (Many-to-Many)
DROP TABLE IF EXISTS public.nation_climate_zones CASCADE;

CREATE TABLE public.nation_climate_zones (
    relationship_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nation_id UUID NOT NULL REFERENCES public.nations(nation_id) ON DELETE CASCADE,
    climate_zone_id UUID NOT NULL REFERENCES public.climate_zones(climate_zone_id) ON DELETE CASCADE,
    coverage_percentage INTEGER CHECK (coverage_percentage BETWEEN 0 AND 100), -- What % of nation has this climate
    prominence VARCHAR(50), -- Dominant, Major, Minor, Trace
    seasonal_notes TEXT, -- How this climate affects the nation seasonally
    regional_variation TEXT, -- How this climate varies within the nation
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(nation_id, climate_zone_id)
);

-- =====================================================
-- Indexes for Performance
-- =====================================================

-- Nation climate zones indexes
CREATE INDEX idx_nation_climate_nation ON public.nation_climate_zones (nation_id);
CREATE INDEX idx_nation_climate_zone ON public.nation_climate_zones (climate_zone_id);
CREATE INDEX idx_nation_climate_prominence ON public.nation_climate_zones (prominence);

-- =====================================================
-- Triggers for Updated Timestamps
-- =====================================================

CREATE TRIGGER nation_climate_zones_updated_at_trigger
    BEFORE UPDATE ON public.nation_climate_zones
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

-- =====================================================
-- Comments
-- =====================================================

COMMENT ON TABLE public.nation_climate_zones IS 'Many-to-many relationship between nations and their climate zones';
COMMENT ON COLUMN public.nation_climate_zones.coverage_percentage IS 'Approximate percentage of nation with this climate zone';