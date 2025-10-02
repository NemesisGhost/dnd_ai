-- =====================================================
-- Business Types Lookup Table
-- Simple lookup for categorizing different types of businesses
-- ==========================================================================================================
-- Business Types Lookup Table
-- =====================================================

DROP TABLE IF EXISTS public.business_types CASCADE;

CREATE TABLE public.business_types (
    business_type_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    category VARCHAR(100), -- Retail, Service, Government, Entertainment, etc.
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Insert common business types
INSERT INTO public.business_types (name, description, category) VALUES
('Shop', 'General retail establishment selling goods', 'Retail'),
('Tavern', 'Establishment serving food and drink', 'Entertainment'),
('Inn', 'Lodging establishment for travelers', 'Service'),
('Blacksmith', 'Metalworking and weapon/tool crafting', 'Crafting'),
('Government Office', 'Official administrative building', 'Government'),
('Temple', 'Religious worship and ceremony location', 'Religious'),
('Guild Hall', 'Organization headquarters and meeting place', 'Organization'),
('Market Stall', 'Small vendor booth in marketplace', 'Retail'),
('Workshop', 'Crafting and manufacturing location', 'Crafting'),
('Warehouse', 'Storage and distribution facility', 'Storage'),
('Stable', 'Horse and livestock care facility', 'Service'),
('Library', 'Repository of books and knowledge', 'Education'),
('School', 'Educational instruction facility', 'Education'),
('Hospital', 'Medical treatment facility', 'Medical'),
('Bank', 'Financial services institution', 'Financial'),
('Theater', 'Performance and entertainment venue', 'Entertainment'),
('Guard Post', 'Security and law enforcement station', 'Government'),
('Customs House', 'Trade regulation and tax collection', 'Government'),
('Courier Service', 'Message and package delivery', 'Service'),
('Transport Company', 'Passenger and cargo transportation', 'Service');

-- Indexes
CREATE INDEX idx_business_types_category ON public.business_types (category);
CREATE INDEX idx_business_types_name_search ON public.business_types USING gin(to_tsvector('english', name));

-- Comments
COMMENT ON TABLE public.business_types IS 'Standardized types of businesses and establishments';
COMMENT ON COLUMN public.business_types.category IS 'High-level grouping of business types';