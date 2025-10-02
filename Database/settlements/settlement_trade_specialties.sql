-- =====================================================
-- Settlement Trade Specialties Table
-- =====================================================

DROP TABLE IF EXISTS public.settlement_trade_specialties CASCADE;

CREATE TABLE public.settlement_trade_specialties (
    settlement_specialty_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    settlement_id UUID NOT NULL REFERENCES public.settlements(settlement_id) ON DELETE CASCADE,
    specialty_name VARCHAR(200) NOT NULL,
    specialty_type_id UUID REFERENCES public.trade_specialty_types(specialty_type_id),
    quality_level_id UUID REFERENCES public.quality_levels(quality_level_id),
    market_reach_id UUID REFERENCES public.market_reach_levels(market_reach_id),
    trade_volume_id UUID REFERENCES public.trade_volume_levels(trade_volume_id),
    reputation TEXT, -- What they're known for regarding this specialty
    pricing VARCHAR(50), -- Cheap, Fair, Premium, Luxury
    seasonal BOOLEAN DEFAULT FALSE,
    notes TEXT,
    
    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Ensure unique settlement-specialty pairs
    UNIQUE(settlement_id, specialty_name)
);

-- Indexes for efficient queries
CREATE INDEX idx_settlement_trade_specialties_settlement ON public.settlement_trade_specialties (settlement_id);
CREATE INDEX idx_settlement_trade_specialties_type ON public.settlement_trade_specialties (specialty_type_id);
CREATE INDEX idx_settlement_trade_specialties_quality ON public.settlement_trade_specialties (quality_level_id);
CREATE INDEX idx_settlement_trade_specialties_reach ON public.settlement_trade_specialties (market_reach_id);
CREATE INDEX idx_settlement_trade_specialties_volume ON public.settlement_trade_specialties (trade_volume_id);
CREATE INDEX idx_settlement_trade_specialties_name_search ON public.settlement_trade_specialties USING gin(to_tsvector('english', specialty_name));

-- Trigger for updated_at
CREATE TRIGGER settlement_trade_specialties_updated_at_trigger
    BEFORE UPDATE ON public.settlement_trade_specialties
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

-- Comments
COMMENT ON TABLE public.settlement_trade_specialties IS 'Trade specialties and products settlements are known for';
COMMENT ON COLUMN public.settlement_trade_specialties.specialty_type_id IS 'Foreign key to trade_specialty_types lookup table';
COMMENT ON COLUMN public.settlement_trade_specialties.quality_level_id IS 'Foreign key to quality_levels lookup table';
COMMENT ON COLUMN public.settlement_trade_specialties.market_reach_id IS 'Foreign key to market_reach_levels lookup table';
COMMENT ON COLUMN public.settlement_trade_specialties.trade_volume_id IS 'Foreign key to trade_volume_levels lookup table';

-- Sample data for Millbrook
-- Note: These INSERTs will only work if the Millbrook settlement exists
/*
INSERT INTO public.settlement_trade_specialties (settlement_id, specialty_name, specialty_type_id, quality_level_id, market_reach_id, trade_volume_id, reputation, pricing) VALUES
((SELECT settlement_id FROM public.settlements WHERE name = 'Millbrook'), 
 'Fine Flour',
 (SELECT specialty_type_id FROM public.trade_specialty_types WHERE name = 'Export'),
 (SELECT quality_level_id FROM public.quality_levels WHERE name = 'Excellent'),
 (SELECT market_reach_id FROM public.market_reach_levels WHERE name = 'Regional'),
 (SELECT trade_volume_id FROM public.trade_volume_levels WHERE name = 'High'),
 'Known throughout the valley for premium flour quality', 'Premium'),
((SELECT settlement_id FROM public.settlements WHERE name = 'Millbrook'), 
 'Wool Textiles',
 (SELECT specialty_type_id FROM public.trade_specialty_types WHERE name = 'Export'),
 (SELECT quality_level_id FROM public.quality_levels WHERE name = 'Good'),
 (SELECT market_reach_id FROM public.market_reach_levels WHERE name = 'Local'),
 (SELECT trade_volume_id FROM public.trade_volume_levels WHERE name = 'Moderate'),
 'Sturdy work clothes and blankets', 'Fair'),
((SELECT settlement_id FROM public.settlements WHERE name = 'Millbrook'), 
 'River Barges',
 (SELECT specialty_type_id FROM public.trade_specialty_types WHERE name = 'Service'),
 (SELECT quality_level_id FROM public.quality_levels WHERE name = 'Good'),
 (SELECT market_reach_id FROM public.market_reach_levels WHERE name = 'Regional'),
 (SELECT trade_volume_id FROM public.trade_volume_levels WHERE name = 'Moderate'),
 'Reliable river transport service', 'Fair');
*/