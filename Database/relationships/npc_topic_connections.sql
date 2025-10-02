-- =====================================================
-- NPC Topic Connections (Many-to-Many)
-- Connections between NPCs through shared topics and knowledge
-- Requires: npcs.sql, npc_topics_main.sql
-- =====================================================

DROP TABLE IF EXISTS public.npc_topic_connections CASCADE;

CREATE TABLE public.npc_topic_connections (
    connection_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    primary_npc_id UUID NOT NULL REFERENCES public.npcs(npc_id) ON DELETE CASCADE,
    connected_npc_id UUID NOT NULL REFERENCES public.npcs(npc_id) ON DELETE CASCADE,
    topic_id UUID NOT NULL REFERENCES public.npc_topics(topic_id) ON DELETE CASCADE,
    connection_type VARCHAR(50), -- knows_about, involved_in, expert_on, gossips_about, etc.
    connection_strength INTEGER DEFAULT 5, -- 1-10 how strongly connected they are to this topic
    is_public_knowledge BOOLEAN DEFAULT true, -- Whether this connection is commonly known
    notes TEXT, -- Additional context about the connection
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(primary_npc_id, connected_npc_id, topic_id)
);

-- =====================================================
-- Indexes
-- =====================================================

CREATE INDEX idx_npc_topic_connections_primary ON public.npc_topic_connections (primary_npc_id);
CREATE INDEX idx_npc_topic_connections_connected ON public.npc_topic_connections (connected_npc_id);
CREATE INDEX idx_npc_topic_connections_topic ON public.npc_topic_connections (topic_id);
CREATE INDEX idx_npc_topic_connections_type ON public.npc_topic_connections (connection_type);
CREATE INDEX idx_npc_topic_connections_strength ON public.npc_topic_connections (connection_strength DESC);
CREATE INDEX idx_npc_topic_connections_public ON public.npc_topic_connections (is_public_knowledge);

-- =====================================================
-- Triggers
-- =====================================================

CREATE TRIGGER npc_topic_connections_updated_at_trigger
    BEFORE UPDATE ON public.npc_topic_connections
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

-- =====================================================
-- Comments
-- =====================================================

COMMENT ON TABLE public.npc_topic_connections IS 'Connections between NPCs through shared topics and knowledge';
COMMENT ON COLUMN public.npc_topic_connections.connection_type IS 'Type of connection: knows_about, involved_in, expert_on, gossips_about, etc.';
COMMENT ON COLUMN public.npc_topic_connections.connection_strength IS 'How strongly this NPC is connected to the other NPC through this topic';
COMMENT ON COLUMN public.npc_topic_connections.is_public_knowledge IS 'Whether the connection between these NPCs regarding this topic is commonly known';
COMMENT ON COLUMN public.npc_topic_connections.notes IS 'Additional context about the connection between these NPCs through this topic';