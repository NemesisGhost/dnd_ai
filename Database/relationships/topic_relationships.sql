-- =====================================================
-- Topic Relationships (Many-to-Many)
-- How topics connect to and lead to other topics in conversation
-- Requires: npc_topics_main.sql
-- =====================================================

DROP TABLE IF EXISTS public.topic_relationships CASCADE;

CREATE TABLE public.topic_relationships (
    relationship_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_topic_id UUID NOT NULL REFERENCES public.npc_topics(topic_id) ON DELETE CASCADE,
    target_topic_id UUID NOT NULL REFERENCES public.npc_topics(topic_id) ON DELETE CASCADE,
    relationship_type VARCHAR(50) DEFAULT 'leads_to', -- leads_to, related_to, contradicts, etc.
    transition_probability INTEGER DEFAULT 5, -- 1-10 likelihood of moving from source to target
    notes TEXT, -- Additional context about the relationship
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(source_topic_id, target_topic_id, relationship_type),
    CHECK(source_topic_id != target_topic_id) -- Prevent self-references
);

-- =====================================================
-- Indexes
-- =====================================================

CREATE INDEX idx_topic_relationships_source ON public.topic_relationships (source_topic_id);
CREATE INDEX idx_topic_relationships_target ON public.topic_relationships (target_topic_id);
CREATE INDEX idx_topic_relationships_type ON public.topic_relationships (relationship_type);
CREATE INDEX idx_topic_relationships_probability ON public.topic_relationships (transition_probability DESC);

-- =====================================================
-- Triggers
-- =====================================================

CREATE TRIGGER topic_relationships_updated_at_trigger
    BEFORE UPDATE ON public.topic_relationships
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

-- =====================================================
-- Comments
-- =====================================================

COMMENT ON TABLE public.topic_relationships IS 'How topics connect to and lead to other topics in conversation';
COMMENT ON COLUMN public.topic_relationships.relationship_type IS 'Type of relationship: leads_to, related_to, contradicts, etc.';
COMMENT ON COLUMN public.topic_relationships.transition_probability IS 'Likelihood (1-10) that discussing the source topic will lead to the target topic';
COMMENT ON COLUMN public.topic_relationships.notes IS 'Additional context about the relationship between these topics';