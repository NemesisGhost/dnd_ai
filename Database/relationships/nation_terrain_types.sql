-- =====================================================
-- Nation Terrain Types (Many-to-Many) Relationship Table
-- =====================================================

-- Nation Terrain Types (Many-to-Many)
DROP TABLE IF EXISTS public.nation_terrain_types CASCADE;

CREATE TABLE public.nation_terrain_types (
    relationship_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nation_id UUID NOT NULL REFERENCES public.nations(nation_id) ON DELETE CASCADE,
    terrain_type_id UUID NOT NULL REFERENCES public.terrain_types(terrain_type_id) ON DELETE CASCADE,
    coverage_percentage INTEGER CHECK (coverage_percentage BETWEEN 0 AND 100), -- What % of nation is this terrain
    prominence VARCHAR(50), -- Dominant, Major, Minor, Trace
    regional_notes TEXT, -- Specific notes about this terrain in this nation
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(nation_id, terrain_type_id)
);

-- =====================================================
-- Indexes for Performance
-- =====================================================

-- Nation terrain types indexes
CREATE INDEX idx_nation_terrain_nation ON public.nation_terrain_types (nation_id);
CREATE INDEX idx_nation_terrain_type ON public.nation_terrain_types (terrain_type_id);
CREATE INDEX idx_nation_terrain_prominence ON public.nation_terrain_types (prominence);

-- =====================================================
-- Triggers for Updated Timestamps
-- =====================================================

CREATE TRIGGER nation_terrain_types_updated_at_trigger
    BEFORE UPDATE ON public.nation_terrain_types
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

-- =====================================================
-- Comments
-- =====================================================

COMMENT ON TABLE public.nation_terrain_types IS 'Many-to-many relationship between nations and their terrain types';
COMMENT ON COLUMN public.nation_terrain_types.coverage_percentage IS 'Approximate percentage of nation covered by this terrain type';