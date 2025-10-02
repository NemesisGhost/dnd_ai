-- =====================================================
-- Business Payment Methods Table
-- Many-to-many relationship between businesses and accepted payment methods
-- Requires: businesses.sql, ../lookups/cost_types.sql
-- =====================================================

-- Business Payment Methods Relationship Table
DROP TABLE IF EXISTS public.business_payment_methods CASCADE;

CREATE TABLE public.business_payment_methods (
    payment_method_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id UUID NOT NULL REFERENCES public.businesses(business_id) ON DELETE CASCADE,
    cost_type_id UUID NOT NULL REFERENCES public.cost_types(cost_type_id) ON DELETE CASCADE,
    
    -- Payment method details
    is_preferred BOOLEAN DEFAULT FALSE, -- Is this a preferred payment method for this business?
    acceptance_conditions TEXT, -- Special conditions for accepting this payment method
    exchange_rate_notes TEXT, -- How they handle conversion rates (for barter, services, etc.)
    minimum_amount TEXT, -- Minimum transaction amount for this payment method
    maximum_amount TEXT, -- Maximum transaction amount for this payment method 
    verification_required BOOLEAN DEFAULT FALSE, -- Do they need to verify this payment method?
    
    -- Status and notes
    currently_accepted BOOLEAN DEFAULT TRUE, -- Are they currently accepting this payment method?
   
    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    notes TEXT,
    
    -- Constraints
    UNIQUE(business_id, cost_type_id) -- Each business can only have one record per payment method
);

-- Indexes for performance
CREATE INDEX idx_business_payment_methods_business ON public.business_payment_methods (business_id);
CREATE INDEX idx_business_payment_methods_cost_type ON public.business_payment_methods (cost_type_id);
CREATE INDEX idx_business_payment_methods_preferred ON public.business_payment_methods (is_preferred) WHERE is_preferred = TRUE;
CREATE INDEX idx_business_payment_methods_accepted ON public.business_payment_methods (currently_accepted) WHERE currently_accepted = TRUE;

-- Trigger for updated_at
CREATE TRIGGER business_payment_methods_updated_at_trigger
    BEFORE UPDATE ON public.business_payment_methods
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

-- Comments
COMMENT ON TABLE public.business_payment_methods IS 'Many-to-many relationship tracking payment methods accepted by businesses';
COMMENT ON COLUMN public.business_payment_methods.is_preferred IS 'Whether this business prefers this payment method over others';
COMMENT ON COLUMN public.business_payment_methods.acceptance_conditions IS 'Special conditions or requirements for accepting this payment method';
COMMENT ON COLUMN public.business_payment_methods.exchange_rate_notes IS 'How the business handles conversion rates for non-standard payments';
COMMENT ON COLUMN public.business_payment_methods.verification_required IS 'Whether the business needs to verify this payment method before accepting';
COMMENT ON COLUMN public.business_payment_methods.currently_accepted IS 'Whether the business is currently accepting this payment method';

-- Sample data showing how businesses accept different payment methods
-- These would be populated after businesses and cost_types are created

/*
-- Example: Prancing Pony Inn accepts various payments
INSERT INTO public.business_payment_methods (
    business_id, 
    cost_type_id, 
    is_preferred, 
    acceptance_conditions,
    processing_time,
    notes
) VALUES 
(
    (SELECT business_id FROM public.businesses WHERE name = 'The Prancing Pony Inn'),
    (SELECT cost_type_id FROM public.cost_types WHERE name = 'Gold Pieces'),
    TRUE, -- Preferred payment
    'Standard rates, no special conditions',
    'Immediate',
    'Primary payment method, always preferred'
),
(
    (SELECT business_id FROM public.businesses WHERE name = 'The Prancing Pony Inn'),
    (SELECT cost_type_id FROM public.cost_types WHERE name = 'Silver Pieces'),
    TRUE, -- Also preferred
    'Standard conversion rates apply',
    'Immediate',
    'Common payment for meals and drinks'
),
(
    (SELECT business_id FROM public.businesses WHERE name = 'The Prancing Pony Inn'),
    (SELECT cost_type_id FROM public.cost_types WHERE name = 'Barter/Trade'),
    FALSE, -- Not preferred but accepted
    'Must be food, drink, or travel supplies of equal value',
    'Same Day', -- Need to evaluate barter items
    'Accepts quality goods in trade, especially rare ingredients'
),
(
    (SELECT business_id FROM public.businesses WHERE name = 'The Prancing Pony Inn'),
    (SELECT cost_type_id FROM public.cost_types WHERE name = 'Services'),
    FALSE,
    'Entertainment services only (music, storytelling, news)',
    'Immediate',
    'Welcomes traveling bards and storytellers'
);

-- Example: Blacksmith has different payment preferences
INSERT INTO public.business_payment_methods (
    business_id, 
    cost_type_id, 
    is_preferred, 
    acceptance_conditions,
    processing_time,
    barter_preferences,
    notes
) VALUES 
(
    (SELECT business_id FROM public.businesses WHERE name = 'Ironforge Smithy'),
    (SELECT cost_type_id FROM public.cost_types WHERE name = 'Gold Pieces'),
    TRUE,
    'Standard rates for all work',
    'Immediate',
    NULL,
    'Preferred for large orders and commissioned work'
),
(
    (SELECT business_id FROM public.businesses WHERE name = 'Ironforge Smithy'),
    (SELECT cost_type_id FROM public.cost_types WHERE name = 'Barter/Trade'),
    TRUE, -- Smiths often prefer trade
    'Quality metals, rare ores, or masterwork items only',
    '1-3 Days', -- Time to evaluate materials
    'Mithril, adamantine, rare gems, or exceptional crafted items',
    'Prefers raw materials and rare metals over coin'
),
(
    (SELECT business_id FROM public.businesses WHERE name = 'Ironforge Smithy'),
    (SELECT cost_type_id FROM public.cost_types WHERE name = 'Services'),
    FALSE,
    'Manual labor or specialized skills related to smithing',
    'By Appointment',
    NULL,
    'Accepts apprentice work or mining services'
);
*/