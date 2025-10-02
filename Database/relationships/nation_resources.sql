-- =====================================================
-- Nation Resources Relationship Table (Many-to-Many)
-- Requires: nations_main.sql, resources_main.sql
-- =====================================================

DROP TABLE IF EXISTS public.nation_resources CASCADE;

CREATE TABLE public.nation_resources (
    relationship_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nation_id UUID NOT NULL REFERENCES public.nations(nation_id) ON DELETE CASCADE,
    resource_id UUID NOT NULL REFERENCES public.resources(resource_id) ON DELETE CASCADE,
    
    -- Abundance and distribution
    abundance_level VARCHAR(50), -- Abundant, Plentiful, Moderate, Limited, Scarce, Trace
    geographic_distribution TEXT, -- Where in the nation this resource is found
    extraction_locations TEXT, -- Specific mines, forests, etc.
    
    -- Economic aspects
    economic_importance VARCHAR(50), -- Critical, Major, Moderate, Minor, Negligible
    export_percentage INTEGER CHECK (export_percentage BETWEEN 0 AND 100), -- What % is exported
    government_control VARCHAR(50), -- State Monopoly, Regulated, Taxed, Free Market
    
    -- Extraction and production
    extraction_method TEXT, -- How it's harvested/mined/produced
    annual_production_estimate VARCHAR(100), -- Rough production numbers
    extraction_challenges TEXT, -- Problems with getting the resource
    
    -- Strategic aspects
    strategic_value VARCHAR(50), -- Critical, High, Moderate, Low
    military_applications TEXT, -- How it's used for defense/war
    trade_significance TEXT, -- Role in international trade
    
    -- Status and trends
    depletion_risk VARCHAR(50), -- None, Low, Moderate, High, Critical
    sustainability_practices TEXT, -- How extraction is managed long-term
    recent_discoveries TEXT, -- New finds or developments
    
    -- Metadata
    discovery_date VARCHAR(100), -- When this resource was first found
    last_surveyed DATE DEFAULT CURRENT_DATE,
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    UNIQUE(nation_id, resource_id)
);

-- =====================================================
-- Indexes
-- =====================================================

CREATE INDEX idx_nation_resources_nation ON public.nation_resources (nation_id);
CREATE INDEX idx_nation_resources_resource ON public.nation_resources (resource_id);
CREATE INDEX idx_nation_resources_abundance ON public.nation_resources (abundance_level);
CREATE INDEX idx_nation_resources_importance ON public.nation_resources (economic_importance);
CREATE INDEX idx_nation_resources_strategic ON public.nation_resources (strategic_value);

-- =====================================================
-- Triggers
-- =====================================================

CREATE TRIGGER nation_resources_updated_at_trigger
    BEFORE UPDATE ON public.nation_resources
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

-- =====================================================
-- Comments
-- =====================================================

COMMENT ON TABLE public.nation_resources IS 'Many-to-many relationship between nations and their natural/economic resources';
COMMENT ON COLUMN public.nation_resources.abundance_level IS 'Abundant, Plentiful, Moderate, Limited, Scarce, Trace';
COMMENT ON COLUMN public.nation_resources.export_percentage IS 'Percentage of production that is exported to other nations';
COMMENT ON COLUMN public.nation_resources.economic_importance IS 'Critical, Major, Moderate, Minor, Negligible';
COMMENT ON COLUMN public.nation_resources.strategic_value IS 'Critical, High, Moderate, Low';