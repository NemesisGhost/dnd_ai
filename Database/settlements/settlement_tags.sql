-- =====================================================
-- Settlement Tags Many-to-Many Relationship Table
-- =====================================================

DROP TABLE IF EXISTS public.settlement_tags CASCADE;

CREATE TABLE public.settlement_tags (
    settlement_tag_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    settlement_id UUID NOT NULL REFERENCES public.settlements(settlement_id) ON DELETE CASCADE,
    tag_id UUID NOT NULL REFERENCES public.tags(tag_id) ON DELETE CASCADE,
    
    -- Tag application details
    relevance_level VARCHAR(50) DEFAULT 'Standard', -- High, Standard, Low
    applied_date DATE DEFAULT CURRENT_DATE,
    applied_by VARCHAR(100), -- Who added this tag (DM name, system, etc.)
    notes TEXT, -- Why this tag applies or additional context
    
    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Ensure unique settlement-tag pairs
    UNIQUE(settlement_id, tag_id)
);

-- Indexes for efficient queries
CREATE INDEX idx_settlement_tags_settlement ON public.settlement_tags (settlement_id);
CREATE INDEX idx_settlement_tags_tag ON public.settlement_tags (tag_id);
CREATE INDEX idx_settlement_tags_relevance ON public.settlement_tags (relevance_level);
CREATE INDEX idx_settlement_tags_applied_date ON public.settlement_tags (applied_date);

-- Trigger for updated_at
CREATE TRIGGER settlement_tags_updated_at_trigger
    BEFORE UPDATE ON public.settlement_tags
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

-- Comments
COMMENT ON TABLE public.settlement_tags IS 'Many-to-many relationship between settlements and tags for categorization and search';
COMMENT ON COLUMN public.settlement_tags.relevance_level IS 'How relevant this tag is to the settlement';
COMMENT ON COLUMN public.settlement_tags.applied_by IS 'Who added this tag for tracking purposes';
COMMENT ON COLUMN public.settlement_tags.notes IS 'Additional context for why this tag applies';

-- Sample data (assuming Millbrook settlement and some common tags exist)
-- Note: These INSERTs will only work if the referenced settlements and tags exist
/*
INSERT INTO public.settlement_tags (settlement_id, tag_id, relevance_level, applied_by, notes) VALUES
((SELECT settlement_id FROM public.settlements WHERE name = 'Millbrook'), 
 (SELECT tag_id FROM public.tags WHERE name = 'trading-post'), 
 'High', 'DM', 'Major grain trading hub for the region'),
((SELECT settlement_id FROM public.settlements WHERE name = 'Millbrook'), 
 (SELECT tag_id FROM public.tags WHERE name = 'quest-hub'), 
 'Standard', 'DM', 'Town council often posts notices for adventurers'),
((SELECT settlement_id FROM public.settlements WHERE name = 'Millbrook'), 
 (SELECT tag_id FROM public.tags WHERE name = 'safe-haven'), 
 'High', 'DM', 'Well-defended with friendly guards'),
((SELECT settlement_id FROM public.settlements WHERE name = 'Millbrook'), 
 (SELECT tag_id FROM public.tags WHERE name = 'river-town'), 
 'High', 'DM', 'Built along the Miller River');
*/