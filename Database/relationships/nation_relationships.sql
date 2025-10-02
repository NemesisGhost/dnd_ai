-- =====================================================
-- Nation Relationships
-- Relationships between nations (neighboring, allied, etc.)
-- =====================================================

DROP TABLE IF EXISTS public.nation_relationships CASCADE;

CREATE TABLE public.nation_relationships (
    relationship_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nation_id_1 UUID NOT NULL REFERENCES public.nations(nation_id) ON DELETE CASCADE,
    nation_id_2 UUID NOT NULL REFERENCES public.nations(nation_id) ON DELETE CASCADE,
    relationship_type VARCHAR(100) NOT NULL, -- Neighbors, Allies, Enemies, Trade Partners, etc.
    relationship_strength VARCHAR(50), -- Weak, Moderate, Strong, Hostile, etc.
    diplomatic_status VARCHAR(100), -- Peace, War, Alliance, Trade Agreement, etc.
    established_date VARCHAR(100), -- When this relationship began
    current_status VARCHAR(50), -- Active, Suspended, Under Review, etc.
    bidirectional BOOLEAN DEFAULT TRUE, -- Whether relationship applies both ways
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(nation_id_1, nation_id_2, relationship_type)
);

-- =====================================================
-- Indexes
-- =====================================================

CREATE INDEX idx_nation_rel_nation1 ON public.nation_relationships (nation_id_1);
CREATE INDEX idx_nation_rel_nation2 ON public.nation_relationships (nation_id_2);
CREATE INDEX idx_nation_rel_type ON public.nation_relationships (relationship_type);

-- =====================================================
-- Triggers
-- =====================================================

CREATE TRIGGER nation_relationships_updated_at_trigger
    BEFORE UPDATE ON public.nation_relationships
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

-- =====================================================
-- Comments
-- =====================================================

COMMENT ON TABLE public.nation_relationships IS 'Relationships between different nations (neighbors, allies, enemies, etc.)';