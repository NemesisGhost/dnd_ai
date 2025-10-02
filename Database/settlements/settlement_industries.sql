-- =====================================================
-- Settlement Industries Table
-- =====================================================

DROP TABLE IF EXISTS public.settlement_industries CASCADE;

CREATE TABLE public.settlement_industries (
    settlement_industry_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    settlement_id UUID NOT NULL REFERENCES public.settlements(settlement_id) ON DELETE CASCADE,
    industry_name VARCHAR(200) NOT NULL,
    importance_level INTEGER, -- Order of importance to the settlement
    economic_impact TEXT, -- Description of economic impact
    employment_percentage DECIMAL(5,2), -- Percentage of population employed in this industry
    seasonal BOOLEAN DEFAULT FALSE, -- Whether this is seasonal work
    notes TEXT,
    
    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Ensure unique settlement-industry pairs
    UNIQUE(settlement_id, industry_name)
);

-- Indexes for efficient queries
CREATE INDEX idx_settlement_industries_settlement ON public.settlement_industries (settlement_id);
CREATE INDEX idx_settlement_industries_type ON public.settlement_industries (industry_type);
CREATE INDEX idx_settlement_industries_importance ON public.settlement_industries (importance_level);
CREATE INDEX idx_settlement_industries_name_search ON public.settlement_industries USING gin(to_tsvector('english', industry_name));

-- Trigger for updated_at
CREATE TRIGGER settlement_industries_updated_at_trigger
    BEFORE UPDATE ON public.settlement_industries
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

-- Comments
COMMENT ON TABLE public.settlement_industries IS 'Industries and economic activities in settlements';
COMMENT ON COLUMN public.settlement_industries.industry_type IS 'Classification: primary (raw materials), secondary (manufacturing), tertiary (services)';
COMMENT ON COLUMN public.settlement_industries.importance_level IS 'How important this industry is to the settlement';
COMMENT ON COLUMN public.settlement_industries.employment_percentage IS 'Percentage of population employed in this industry';

-- Sample data for Millbrook
-- Note: These INSERTs will only work if the Millbrook settlement exists
/*
INSERT INTO public.settlement_industries (settlement_id, industry_name, industry_type, importance_level, employment_percentage, notes) VALUES
((SELECT settlement_id FROM public.settlements WHERE name = 'Millbrook'), 
 'Grain Milling', 'secondary', 'Primary', 35.0, 'The main economic driver, multiple mills along the river'),
((SELECT settlement_id FROM public.settlements WHERE name = 'Millbrook'), 
 'River Trade', 'tertiary', 'Primary', 25.0, 'River transport and trading operations'),
((SELECT settlement_id FROM public.settlements WHERE name = 'Millbrook'), 
 'Sheep Farming', 'primary', 'Standard', 20.0, 'Surrounding hills provide excellent grazing'),
((SELECT settlement_id FROM public.settlements WHERE name = 'Millbrook'), 
 'Wool Processing', 'secondary', 'Secondary', 10.0, 'Processing wool from local sheep farms');
*/