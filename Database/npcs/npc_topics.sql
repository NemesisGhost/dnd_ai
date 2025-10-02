-- =====================================================
-- NPC Topics Table
-- Master list of conversation topics available in the world
-- Requires: topic_categories.sql
-- =====================================================

DROP TABLE IF EXISTS public.npc_topics CASCADE;

CREATE TABLE public.npc_topics (
    topic_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    topic_name VARCHAR(200) NOT NULL,
    topic_description TEXT,
    category_id UUID REFERENCES public.topic_categories(category_id),
    player_interest_shown BOOLEAN DEFAULT false, -- Have players shown interest in this topic
    last_discussed DATE, -- When this topic was last brought up
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- =====================================================
-- Indexes
-- =====================================================

CREATE INDEX idx_npc_topics_category ON public.npc_topics (category_id);
CREATE INDEX idx_npc_topics_player_interest ON public.npc_topics (player_interest_shown);
CREATE INDEX idx_npc_topics_name ON public.npc_topics (topic_name);
CREATE INDEX idx_npc_topics_last_discussed ON public.npc_topics (last_discussed);

-- =====================================================
-- Triggers
-- =====================================================

CREATE TRIGGER npc_topics_updated_at_trigger
    BEFORE UPDATE ON public.npc_topics
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

-- =====================================================
-- Comments
-- =====================================================

COMMENT ON TABLE public.npc_topics IS 'Master list of conversation topics available in the world';
COMMENT ON COLUMN public.npc_topics.player_interest_shown IS 'Have players shown interest in this topic';
COMMENT ON COLUMN public.npc_topics.last_discussed IS 'When this topic was last brought up';