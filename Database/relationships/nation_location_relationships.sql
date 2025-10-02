-- =====================================================
-- Nation-Location Relationships
-- Relationships between nations and their regions/territories
-- =====================================================

DROP TABLE IF EXISTS public.nation_location_relationships CASCADE;

CREATE TABLE public.nation_location_relationships (
    relationship_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nation_id UUID NOT NULL REFERENCES public.nations(nation_id) ON DELETE CASCADE,
    location_id UUID NOT NULL REFERENCES public.locations(location_id) ON DELETE CASCADE,
    relationship_type VARCHAR(100) NOT NULL, -- Owns, Controls, Claims, Disputes, Borders, Major Region, etc.
    relationship_strength VARCHAR(50), -- Full Control, Partial Control, Disputed, Claimed, etc.
    administrative_level VARCHAR(50), -- Province, Region, Territory, District, etc.
    established_date VARCHAR(100), -- When this relationship was established
    legal_status VARCHAR(50), -- Official, Recognized, Disputed, Occupied, etc.
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(nation_id, location_id, relationship_type)
);

-- =====================================================
-- Indexes
-- =====================================================

CREATE INDEX idx_nation_location_rel_nation ON public.nation_location_relationships (nation_id);
CREATE INDEX idx_nation_location_rel_location ON public.nation_location_relationships (location_id);
CREATE INDEX idx_nation_location_rel_type ON public.nation_location_relationships (relationship_type);

-- =====================================================
-- Triggers
-- =====================================================

CREATE TRIGGER nation_location_relationships_updated_at_trigger
    BEFORE UPDATE ON public.nation_location_relationships
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

-- =====================================================
-- Comments
-- =====================================================

COMMENT ON TABLE public.nation_location_relationships IS 'Relationships between nations and locations they control, claim, or are associated with';