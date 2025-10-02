-- =====================================================
-- Location Relationships Table (Many-to-Many)
-- For complex relationships between locations
-- =====================================================

DROP TABLE IF EXISTS public.location_relationships CASCADE;

CREATE TABLE public.location_relationships (
    relationship_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    location_id_1 UUID NOT NULL REFERENCES public.locations(location_id) ON DELETE CASCADE,
    location_id_2 UUID NOT NULL REFERENCES public.locations(location_id) ON DELETE CASCADE,
    relationship_type VARCHAR(100) NOT NULL, -- Connected by road, Trade partner, Rival, etc.
    relationship_strength VARCHAR(50), -- Weak, Moderate, Strong
    distance_description VARCHAR(100), -- A day's walk, Across the sea, etc.
    travel_time VARCHAR(100), -- 3 days by horse, 1 week by ship, etc.
    travel_difficulty VARCHAR(50), -- Easy, Moderate, Difficult, Dangerous
    bidirectional BOOLEAN DEFAULT TRUE, -- Whether relationship works both ways
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(location_id_1, location_id_2, relationship_type)
);

-- =====================================================
-- Indexes for Performance
-- =====================================================

-- Location relationships indexes
CREATE INDEX idx_location_relationships_loc1 ON public.location_relationships (location_id_1);
CREATE INDEX idx_location_relationships_loc2 ON public.location_relationships (location_id_2);
CREATE INDEX idx_location_relationships_type ON public.location_relationships (relationship_type);

-- =====================================================
-- Triggers
-- =====================================================

-- Trigger for updated_at on location_relationships
CREATE TRIGGER location_relationships_updated_at_trigger
    BEFORE UPDATE ON public.location_relationships
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

-- =====================================================
-- Comments
-- =====================================================

COMMENT ON TABLE public.location_relationships IS 'Many-to-many relationships between locations (trade routes, political connections, etc.)';
COMMENT ON COLUMN public.location_relationships.bidirectional IS 'Whether the relationship applies in both directions';