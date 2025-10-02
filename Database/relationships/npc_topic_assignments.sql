-- =====================================================
-- NPC Topic Assignments (Many-to-Many)
-- Which NPCs know about which topics and how they relate to them
-- Requires: npcs.sql, npc_topics_main.sql
-- =====================================================

DROP TABLE IF EXISTS public.npc_topic_assignments CASCADE;

CREATE TABLE public.npc_topic_assignments (
    assignment_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    npc_id UUID NOT NULL REFERENCES public.npcs(npc_id) ON DELETE CASCADE,
    topic_id UUID NOT NULL REFERENCES public.npc_topics(topic_id) ON DELETE CASCADE,
    enthusiasm_level INTEGER DEFAULT 5, -- 1-10 how excited they get about this topic
    knowledge_depth INTEGER DEFAULT 5, -- 1-10 how much they actually know
    willingness_to_discuss INTEGER DEFAULT 5, -- 1-10 how readily they'll talk about it
    emotional_association VARCHAR(50), -- Positive, Negative, Neutral, Complicated
    requires_trust_level INTEGER DEFAULT 1, -- 1-10 relationship level needed to discuss
    time_investment VARCHAR(50), -- Quick mention, Short discussion, Long conversation, etc.
    personal_spin TEXT, -- How this NPC specifically relates to or discusses this topic
    confidence_level INTEGER DEFAULT 5, -- 1-10 how confident the NPC is about this topic
    last_discussed_with_party DATE, -- When this NPC last discussed this topic with players
    times_discussed INTEGER DEFAULT 0, -- How many times this has come up
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(npc_id, topic_id)
);

-- =====================================================
-- Indexes
-- =====================================================

CREATE INDEX idx_npc_topic_assignments_npc ON public.npc_topic_assignments (npc_id);
CREATE INDEX idx_npc_topic_assignments_topic ON public.npc_topic_assignments (topic_id);
CREATE INDEX idx_npc_topic_assignments_enthusiasm ON public.npc_topic_assignments (enthusiasm_level DESC);
CREATE INDEX idx_npc_topic_assignments_willingness ON public.npc_topic_assignments (willingness_to_discuss DESC);
CREATE INDEX idx_npc_topic_assignments_trust_required ON public.npc_topic_assignments (requires_trust_level);
CREATE INDEX idx_npc_topic_assignments_confidence ON public.npc_topic_assignments (confidence_level DESC);
CREATE INDEX idx_npc_topic_assignments_discussed ON public.npc_topic_assignments (last_discussed_with_party);

-- =====================================================
-- Triggers
-- =====================================================

CREATE TRIGGER npc_topic_assignments_updated_at_trigger
    BEFORE UPDATE ON public.npc_topic_assignments
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

-- =====================================================
-- Comments
-- =====================================================

COMMENT ON TABLE public.npc_topic_assignments IS 'Which NPCs know about which topics and how they relate to them';
COMMENT ON COLUMN public.npc_topic_assignments.enthusiasm_level IS 'How excited this NPC gets when discussing this topic (1=reluctant, 10=passionate)';
COMMENT ON COLUMN public.npc_topic_assignments.knowledge_depth IS 'How much this NPC actually knows about this topic (1=surface, 10=expert)';
COMMENT ON COLUMN public.npc_topic_assignments.willingness_to_discuss IS 'How readily this NPC will talk about this topic (1=avoids, 10=eager)';
COMMENT ON COLUMN public.npc_topic_assignments.requires_trust_level IS 'Relationship level needed before this NPC will discuss this topic openly (1=anyone, 10=close friend)';
COMMENT ON COLUMN public.npc_topic_assignments.confidence_level IS 'How confident this specific NPC is about their knowledge of this topic';
COMMENT ON COLUMN public.npc_topic_assignments.personal_spin IS 'How this NPC specifically relates to or discusses this topic';