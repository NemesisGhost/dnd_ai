-- =====================================================
-- Nation Exports Relationship Table (Many-to-Many with Resources)
-- Requires: nations_main.sql, resources.sql
-- =====================================================

DROP TABLE IF EXISTS public.nation_exports CASCADE;

CREATE TABLE public.nation_exports (
    relationship_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nation_id UUID NOT NULL REFERENCES public.nations(nation_id) ON DELETE CASCADE,
    resource_id UUID NOT NULL REFERENCES public.resources(resource_id) ON DELETE CASCADE,
    
    -- Export details
    export_volume VARCHAR(50), -- Massive, Large, Moderate, Small, Minimal
    export_percentage DECIMAL(5,2), -- Percentage of national production exported
    annual_value_estimate VARCHAR(100), -- Economic value of exports
    
    -- Trade aspects
    primary_destinations TEXT, -- Which nations/regions buy this
    transport_methods TEXT, -- How it's shipped/moved
    trade_routes TEXT, -- Specific routes used
    seasonal_patterns TEXT, -- Times of year when exports peak
    
    -- Economic importance
    economic_significance VARCHAR(50), -- Critical, Major, Important, Minor, Negligible
    employment_impact TEXT, -- How many jobs depend on this export
    tax_revenue_contribution VARCHAR(50), -- Portion of government income
    
    -- Market conditions
    market_competition VARCHAR(50), -- Monopoly, Dominant, Competitive, Struggling
    price_trends VARCHAR(50), -- Rising, Stable, Falling, Volatile
    demand_outlook VARCHAR(50), -- Growing, Stable, Declining, Uncertain
    
    -- Challenges and risks
    export_challenges TEXT, -- Problems with exporting this resource
    supply_chain_risks TEXT, -- Vulnerabilities in production/transport
    political_risks TEXT, -- How politics affects this export
    
    -- Metadata
    export_since VARCHAR(100), -- When exports began
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    UNIQUE(nation_id, resource_id)
);

-- =====================================================
-- Indexes
-- =====================================================

CREATE INDEX idx_nation_exports_nation ON public.nation_exports (nation_id);
CREATE INDEX idx_nation_exports_resource ON public.nation_exports (resource_id);
CREATE INDEX idx_nation_exports_significance ON public.nation_exports (economic_significance);

-- =====================================================
-- Triggers
-- =====================================================

CREATE TRIGGER nation_exports_updated_at_trigger
    BEFORE UPDATE ON public.nation_exports
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

-- =====================================================
-- Comments
-- =====================================================

COMMENT ON TABLE public.nation_exports IS 'Many-to-many relationship between nations and resources they export';