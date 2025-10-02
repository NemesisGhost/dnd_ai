-- =====================================================
-- Location Routes
-- Detailed travel routes between locations
-- =====================================================

DROP TABLE IF EXISTS public.location_routes CASCADE;

CREATE TABLE public.location_routes (
    route_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    origin_location_id UUID NOT NULL REFERENCES public.locations(location_id) ON DELETE CASCADE,
    destination_location_id UUID NOT NULL REFERENCES public.locations(location_id) ON DELETE CASCADE,
    route_name VARCHAR(200), -- Named routes like "King's Road", "Merchant's Path"
    route_type VARCHAR(100), -- Road, River, Sea Route, Trail, Magical Portal, etc.
    route_quality VARCHAR(50), -- Excellent, Good, Fair, Poor, Dangerous, Impassable
    distance_description VARCHAR(100), -- 50 miles, A day's ride, etc.
    travel_time_foot VARCHAR(100), -- How long on foot
    travel_time_horse VARCHAR(100), -- How long on horseback
    travel_time_cart VARCHAR(100), -- How long with a cart/wagon
    travel_time_ship VARCHAR(100), -- How long by ship (for water routes)
    travel_difficulty VARCHAR(50), -- Easy, Moderate, Difficult, Dangerous, Extreme
    seasonal_variations TEXT, -- How travel changes with seasons
    hazards_present TEXT, -- Bandits, monsters, weather, etc.
    waypoints TEXT, -- Important stops along the route
    toll_requirements TEXT, -- Costs or permissions needed
    patrol_frequency VARCHAR(50), -- How often guards patrol this route
    maintenance_status VARCHAR(50), -- Well Maintained, Fair, Poor, Abandoned
    alternative_routes TEXT, -- Other ways to get between these locations
    historical_significance TEXT, -- Important events on this route
    notes TEXT,
    bidirectional BOOLEAN DEFAULT TRUE, -- Can be traveled both ways
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- =====================================================
-- Indexes
-- =====================================================

CREATE INDEX idx_location_routes_origin ON public.location_routes (origin_location_id);
CREATE INDEX idx_location_routes_destination ON public.location_routes (destination_location_id);
CREATE INDEX idx_location_routes_type ON public.location_routes (route_type);
CREATE INDEX idx_location_routes_quality ON public.location_routes (route_quality);

-- =====================================================
-- Triggers
-- =====================================================

CREATE TRIGGER location_routes_updated_at_trigger
    BEFORE UPDATE ON public.location_routes
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

-- =====================================================
-- Comments
-- =====================================================

COMMENT ON TABLE public.location_routes IS 'Travel routes and connections between locations with travel information';