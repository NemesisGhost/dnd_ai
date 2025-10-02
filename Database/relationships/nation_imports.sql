-- =====================================================
-- Nation Imports Relationship Table (Many-to-Many with Resources)
-- Requires: nations_main.sql, resources.sql
-- =====================================================

DROP TABLE IF EXISTS public.nation_imports CASCADE;

CREATE TABLE public.nation_imports (
    relationship_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nation_id UUID NOT NULL REFERENCES public.nations(nation_id) ON DELETE CASCADE,
    resource_id UUID NOT NULL REFERENCES public.resources(resource_id) ON DELETE CASCADE,
    
    -- Import details
    import_volume VARCHAR(50), -- Massive, Large, Moderate, Small, Minimal
    dependency_level VARCHAR(50), -- Critical, High, Moderate, Low, Optional
    annual_cost_estimate VARCHAR(100), -- Economic cost of imports
    
    -- Source and supply
    primary_sources TEXT, -- Which nations/regions supply this
    supply_reliability VARCHAR(50), -- Very Reliable, Reliable, Uncertain, Unreliable
    alternative_sources TEXT, -- Backup suppliers
    
    -- Usage and distribution
    primary_usage TEXT, -- What the resource is used for domestically
    domestic_distribution TEXT, -- How it's distributed within the nation
    stockpiling_practices TEXT, -- How much is kept in reserve
    
    -- Economic impact
    economic_necessity VARCHAR(50), -- Essential, Important, Useful, Luxury
    price_sensitivity VARCHAR(50), -- How price changes affect demand
    impact_of_shortage TEXT, -- What happens if supply is disrupted
    
    -- Strategic aspects
    strategic_importance VARCHAR(50), -- Critical, High, Moderate, Low, None
    national_security_impact TEXT, -- How import affects security
    self_sufficiency_efforts TEXT, -- Attempts to produce domestically
    
    -- Trade relationships
    trade_agreements TEXT, -- Special deals for this import
    payment_methods TEXT, -- How imports are paid for
    diplomatic_implications TEXT, -- How imports affect foreign relations
    
    -- Metadata
    importing_since VARCHAR(100), -- When imports began
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    UNIQUE(nation_id, resource_id)
);

-- =====================================================
-- Indexes
-- =====================================================

CREATE INDEX idx_nation_imports_nation ON public.nation_imports (nation_id);
CREATE INDEX idx_nation_imports_resource ON public.nation_imports (resource_id);
CREATE INDEX idx_nation_imports_dependency ON public.nation_imports (dependency_level);

-- =====================================================
-- Triggers
-- =====================================================

CREATE TRIGGER nation_imports_updated_at_trigger
    BEFORE UPDATE ON public.nation_imports
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

-- =====================================================
-- Comments
-- =====================================================

COMMENT ON TABLE public.nation_imports IS 'Many-to-many relationship between nations and resources they import';