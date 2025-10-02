-- =====================================================
-- Market Reach Levels Lookup Table
-- =====================================================

DROP TABLE IF EXISTS public.market_reach_levels CASCADE;

CREATE TABLE public.market_reach_levels (
    market_reach_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(50) NOT NULL UNIQUE,
    description TEXT,
    reach_distance_km INTEGER, -- Approximate reach in kilometers
    typical_travel_time VARCHAR(50), -- How long to reach the market boundary
    sort_order INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

INSERT INTO public.market_reach_levels (name, description, reach_distance_km, typical_travel_time, sort_order) VALUES
('Local', 'Within the settlement and immediate surroundings', 25, '1-2 days walk', 1),
('Regional', 'Covers the surrounding region or province', 150, '1-2 weeks travel', 2),
('National', 'Spans across the entire nation or kingdom', 500, '1-2 months travel', 3),
('International', 'Reaches multiple nations or kingdoms', 1500, '2-6 months travel', 4),
('Continental', 'Spans entire continents or trade routes', 5000, '6 months to 1 year', 5),
('Planar', 'Extends to other planes of existence', NULL, 'Variable via magic', 6);

-- Indexes
CREATE INDEX idx_market_reach_levels_sort ON public.market_reach_levels (sort_order);
CREATE INDEX idx_market_reach_levels_distance ON public.market_reach_levels (reach_distance_km);
CREATE INDEX idx_market_reach_levels_name_search ON public.market_reach_levels USING gin(to_tsvector('english', name));

-- Comments
COMMENT ON TABLE public.market_reach_levels IS 'Geographic reach of trade specialties and markets';
COMMENT ON COLUMN public.market_reach_levels.reach_distance_km IS 'Approximate reach distance in kilometers';
COMMENT ON COLUMN public.market_reach_levels.typical_travel_time IS 'Typical travel time to reach market boundary';