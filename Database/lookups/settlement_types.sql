-- =====================================================
-- Settlement Types & Size Categories Combined Lookup Table
-- =====================================================

DROP TABLE IF EXISTS public.settlement_types CASCADE;
DROP TABLE IF EXISTS public.settlement_size_categories CASCADE;

CREATE TABLE public.settlement_types (
    settlement_type_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(50) NOT NULL UNIQUE,
    description TEXT,
    min_population INTEGER, -- For size categories only
    max_population INTEGER, -- For size categories only
    sort_order INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Settlement Types
INSERT INTO public.settlement_types (name, description, sort_order) VALUES
('Outpost', 'Small frontier settlement or military post', 1),
('Hamlet', 'Very small rural settlement', 2),
('Village', 'Small rural community', 3),
('Town', 'Medium-sized settlement with established trade', 4),
('City', 'Large urban center with diverse population', 5),
('Capital', 'Primary city of a nation or region', 6),
('Metropolis', 'Massive urban center with great influence', 7),
('Trading Post', 'Commercial settlement focused on trade', 8),
('Mining Camp', 'Settlement built around mining operations', 9),
('Logging Camp', 'Settlement focused on forestry', 10),
('Fortress', 'Heavily fortified military settlement', 11),
('Port', 'Coastal settlement focused on maritime trade', 12),
('Monastery', 'Religious community settlement', 13),
('Academy Town', 'Settlement built around educational institution', 14),
('Ruins', 'Abandoned or partially destroyed settlement', 15);

-- Settlement Size Categories
INSERT INTO public.settlement_types (name, description, min_population, max_population, sort_order) VALUES
('Thorp', 'Tiny settlement, a few families', 1, 20, 101),
('Hamlet Size', 'Very small rural community (size)', 21, 60, 102),
('Village Size', 'Small settlement with basic services (size)', 61, 200, 103),
('Small Town', 'Town with established trade and services', 201, 2000, 104),
('Large Town', 'Substantial town with diverse population', 2001, 5000, 105),
('Small City', 'Urban center with specialized districts', 5001, 12000, 106),
('Large City', 'Major urban center with significant influence', 12001, 25000, 107),
('Metropolis Size', 'Massive city with great regional importance (size)', 25001, 100000, 108),
('Megalopolis', 'Enormous urban center, capital-level', 100001, NULL, 109);

-- Indexes
CREATE INDEX idx_settlement_types_sort ON public.settlement_types (sort_order);
CREATE INDEX idx_settlement_types_population ON public.settlement_types (min_population, max_population);
CREATE INDEX idx_settlement_types_name_search ON public.settlement_types USING gin(to_tsvector('english', name));

-- Comments
COMMENT ON TABLE public.settlement_types IS 'Combined settlement type classifications and size categories';
COMMENT ON COLUMN public.settlement_types.min_population IS 'Minimum population for size categories (NULL for types)';
COMMENT ON COLUMN public.settlement_types.max_population IS 'Maximum population for size categories (NULL for unlimited or types)';