-- =====================================================
-- Event NPC Connections (Many-to-Many)
-- =====================================================

DROP TABLE IF EXISTS public.event_npc_connections CASCADE;

CREATE TABLE public.event_npc_connections (
    connection_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID NOT NULL REFERENCES public.npc_significant_events(event_id) ON DELETE CASCADE,
    connected_npc_id UUID NOT NULL REFERENCES public.npcs(npc_id) ON DELETE CASCADE,
    primary_npc_id UUID NOT NULL REFERENCES public.npcs(npc_id) ON DELETE CASCADE,
    role_in_event VARCHAR(100),
    relationship_at_time VARCHAR(100),
    current_relationship_affected BOOLEAN DEFAULT true,
    knows_full_story BOOLEAN DEFAULT true,
    emotional_impact_on_connected VARCHAR(50),
    willing_to_discuss BOOLEAN DEFAULT true,
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CHECK(connected_npc_id != primary_npc_id)
);

CREATE INDEX idx_event_npc_connections_event ON public.event_npc_connections (event_id);
CREATE INDEX idx_event_npc_connections_connected_npc ON public.event_npc_connections (connected_npc_id);
CREATE INDEX idx_event_npc_connections_primary_npc ON public.event_npc_connections (primary_npc_id);
CREATE INDEX idx_event_npc_connections_role ON public.event_npc_connections (role_in_event);
CREATE INDEX idx_event_npc_connections_relationship_affected ON public.event_npc_connections (current_relationship_affected);
CREATE INDEX idx_event_npc_connections_knows_story ON public.event_npc_connections (knows_full_story);
CREATE INDEX idx_event_npc_connections_willing_discuss ON public.event_npc_connections (willing_to_discuss);

CREATE TRIGGER event_npc_connections_updated_at_trigger
    BEFORE UPDATE ON public.event_npc_connections
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

COMMENT ON TABLE public.event_npc_connections IS 'Other NPCs involved in significant events and their roles';
COMMENT ON COLUMN public.event_npc_connections.role_in_event IS 'What role this NPC played in the significant event';
COMMENT ON COLUMN public.event_npc_connections.knows_full_story IS 'Whether this connected NPC knows all the details of what happened';
COMMENT ON COLUMN public.event_npc_connections.current_relationship_affected IS 'Whether this past event still influences their current relationship';