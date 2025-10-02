-- =====================================================
-- Rumor NPC Connections (Many-to-Many)
-- =====================================================

DROP TABLE IF EXISTS public.rumor_npc_connections CASCADE;

CREATE TABLE public.rumor_npc_connections (
    connection_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rumor_id UUID NOT NULL REFERENCES public.npc_rumors(rumor_id) ON DELETE CASCADE,
    mentioned_npc_id UUID NOT NULL REFERENCES public.npcs(npc_id) ON DELETE CASCADE,
    connection_type VARCHAR(100) DEFAULT 'mentioned',
    role_in_rumor TEXT,
    is_main_subject BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(rumor_id, mentioned_npc_id)
);

CREATE INDEX idx_rumor_npc_connections_rumor ON public.rumor_npc_connections (rumor_id);
CREATE INDEX idx_rumor_npc_connections_npc ON public.rumor_npc_connections (mentioned_npc_id);
CREATE INDEX idx_rumor_npc_connections_type ON public.rumor_npc_connections (connection_type);
CREATE INDEX idx_rumor_npc_connections_main_subject ON public.rumor_npc_connections (is_main_subject);

CREATE TRIGGER rumor_npc_connections_updated_at_trigger
    BEFORE UPDATE ON public.rumor_npc_connections
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

COMMENT ON TABLE public.rumor_npc_connections IS 'Many-to-many relationship connecting rumors to the NPCs they mention or involve';
COMMENT ON COLUMN public.rumor_npc_connections.connection_type IS 'How the NPC is connected to this rumor';
COMMENT ON COLUMN public.rumor_npc_connections.role_in_rumor IS 'Specific role or context for this NPCs involvement in the rumor';
COMMENT ON COLUMN public.rumor_npc_connections.is_main_subject IS 'Whether this rumor is primarily about this NPC';