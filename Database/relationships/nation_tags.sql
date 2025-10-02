-- =====================================================
-- Nation Tags Relationship Table (Many-to-Many)
-- Requires: nations_main.sql, tags.sql
-- =====================================================

DROP TABLE IF EXISTS public.nation_tags CASCADE;

CREATE TABLE public.nation_tags (
    relationship_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nation_id UUID NOT NULL REFERENCES public.nations(nation_id) ON DELETE CASCADE,
    tag_id UUID NOT NULL REFERENCES public.tags(tag_id) ON DELETE CASCADE,
    
    -- Tag relevance
    relevance_level VARCHAR(50) DEFAULT 'Standard', -- 'Primary', 'Standard', 'Minor', 'Historical'
    tag_context TEXT, -- Why this tag applies to this nation
    
    -- Temporal aspects
    tag_status VARCHAR(50) DEFAULT 'Current', -- 'Current', 'Historical', 'Emerging', 'Declining'
    applied_since VARCHAR(100), -- When this tag became relevant
    
    -- Metadata
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    UNIQUE(nation_id, tag_id)
);

-- =====================================================
-- Indexes
-- =====================================================

CREATE INDEX idx_nation_tags_nation ON public.nation_tags (nation_id);
CREATE INDEX idx_nation_tags_tag ON public.nation_tags (tag_id);
CREATE INDEX idx_nation_tags_relevance ON public.nation_tags (relevance_level);

-- =====================================================
-- Triggers
-- =====================================================

CREATE TRIGGER nation_tags_updated_at_trigger
    BEFORE UPDATE ON public.nation_tags
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

-- =====================================================
-- Comments
-- =====================================================

COMMENT ON TABLE public.nation_tags IS 'Many-to-many relationship between nations and tags';