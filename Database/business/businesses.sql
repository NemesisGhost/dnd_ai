-- =====================================================
-- Businesses Table - Shops, Services & Government Offices
-- Requires: business_types.sql, ../settlements.sql, business_relationships.sql, business_payment_methods.sql, business_tags.sql
-- =====================================================

DROP TABLE IF EXISTS public.businesses CASCADE;

CREATE TABLE public.businesses (
    -- Primary identification
    business_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(200) NOT NULL,
    
    -- Business classification
    business_type_id UUID REFERENCES public.business_types(business_type_id), -- Type from lookup table
    business_category VARCHAR(100), -- Blacksmith, General Store, Tax Office, etc.
    
    -- Location and premises
    settlement_location_id UUID NOT NULL REFERENCES public.locations(location_id), -- FK to locations table
    
    -- Premises information
    street_address TEXT, -- Specific location within settlement
    building_description TEXT, -- What the building looks like
    business_hours TEXT, -- When they're open
    seasonal_variations TEXT, -- Changes based on time of year
    
    -- Business operations
    size_description VARCHAR(50), -- Tiny, Small, Medium, Large, Massive
    customer_base TEXT, -- Who typically uses their services
    reputation VARCHAR(100), -- How they're viewed locally
    quality_of_service INTEGER CHECK (quality_of_service BETWEEN 1 AND 10), -- 1-10 rating of service quality
    pricing_level VARCHAR(50), -- Cheap, Fair, Expensive, Luxury
    
    -- Inventory and capabilities
    typical_inventory TEXT, -- What they usually have in stock
    rare_items_available TEXT, -- Special things they might have
    custom_services TEXT, -- Things they can make/do to order
    limitations TEXT, -- What they can't or won't do
    
    -- Government/Official businesses
    government_level VARCHAR(50), -- Local, Regional, National (if government office)
    authority_scope TEXT, -- What they have jurisdiction over
    bureaucracy_level INTEGER CHECK (bureaucracy_level BETWEEN 1 AND 10), -- 1-10 rating of bureaucracy level
    corruption_level INTEGER CHECK (corruption_level BETWEEN 1 AND 10), -- 1-10 rating of corruption level
    
    -- Economic information
    business_volume VARCHAR(50), -- Slow, Steady, Busy, Overwhelming
    financial_health VARCHAR(50), -- Struggling, Stable, Prospering, Wealthy
    credit_policies TEXT, -- Do they extend credit? To whom?
    
    -- Relationships and connections
    supplier_relationships TEXT, -- Where they get their goods/materials
    government_relations TEXT, -- How they interact with authorities
    
    -- Physical details and atmosphere
    interior_description TEXT, -- What it looks like inside
    atmosphere TEXT, -- The feel/mood of the place
    notable_features TEXT, -- Interesting aspects visitors notice
    security_measures TEXT, -- How they protect themselves/goods
    
    -- Historical and background info
    establishment_date VARCHAR(100), -- When it was founded
    business_history TEXT, -- How it came to be, major events
    previous_owners TEXT, -- Who owned it before
    local_significance TEXT, -- Why it matters to the community
    
    -- Adventure relevance
    quest_opportunities TEXT, -- How it might generate adventures
    information_available TEXT, -- Useful knowledge to be gained here
    rumors_heard_here TEXT, -- Gossip that passes through
    potential_problems TEXT, -- Issues that might need solving
    
    -- Social aspects
    social_gathering_spot BOOLEAN DEFAULT FALSE, -- Is it a community hub?
    events_hosted TEXT, -- Special occasions they hold
    local_customs TEXT, -- Special traditions associated with this place
    
    -- Current status and operations
    current_status VARCHAR(50) DEFAULT 'Operating', -- Operating, Closed, Seasonal, Struggling
    current_issues TEXT, -- Problems they're currently facing
    recent_changes TEXT, -- What's different lately
    future_plans TEXT, -- What they're planning to do
    
    -- Metadata
    dm_notes TEXT, -- Private information for DM
    campaign_importance TEXT, -- Role in current story
    source_material TEXT, -- Reference documents
    
    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_businesses_name_search ON public.businesses USING gin(to_tsvector('english', name));
CREATE INDEX idx_businesses_type ON public.businesses (business_type_id);
CREATE INDEX idx_businesses_location ON public.businesses (settlement_location_id);
CREATE INDEX idx_businesses_status ON public.businesses (current_status);

-- Foreign key constraints now defined inline with column definitions

-- Trigger for updated_at
CREATE TRIGGER businesses_updated_at_trigger
    BEFORE UPDATE ON public.businesses
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

-- Comments
COMMENT ON TABLE public.businesses IS 'Individual businesses, shops, services, and government offices';

-- Sample businesses
INSERT INTO public.businesses (
    name, business_type_id, business_category,
    settlement_location_id, reputation,
    typical_inventory, atmosphere
) VALUES 
(
    'The Prancing Pony Inn',
    (SELECT business_type_id FROM public.business_types WHERE name = 'Inn'),
    'Tavern & Lodging',
    NULL, -- Would reference actual settlement
    'Well-regarded by travelers, known for hearty meals',
    'Ale, wine, bread, stew, cheese, basic travel supplies',
    'Warm and welcoming, always busy with travelers sharing tales'
),
(
    'Ironforge Smithy',
    (SELECT business_type_id FROM public.business_types WHERE name = 'Blacksmith'),
    'Blacksmith',
    NULL, -- Would reference actual settlement
    'Finest metalwork in three settlements',
    'Common weapons, farming tools, horseshoes, nails, basic armor',
    'Hot, noisy workshop filled with the ring of hammer on anvil'
),
(
    'Office of the Tax Collector',
    (SELECT business_type_id FROM public.business_types WHERE name = 'Government Office'),
    'Tax Collection',
    NULL, -- Would reference actual settlement
    'Necessary but unpopular, known for being thorough',
    'Tax records, legal documents, official seals',
    'Formal and bureaucratic, lots of paperwork and long lines'
);