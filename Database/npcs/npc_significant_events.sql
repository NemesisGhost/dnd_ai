-- =====================================================
-- NPC Significant Events Table
-- Requires: event_categories.sql, emotional_impact_types.sql, 
--           current_relevance_levels.sql, player_knowledge_levels.sql
-- =====================================================

DROP TABLE IF EXISTS public.npc_significant_events CASCADE;

CREATE TABLE public.npc_significant_events (
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    npc_id UUID NOT NULL REFERENCES public.npcs(npc_id) ON DELETE CASCADE,
    event_title VARCHAR(200) NOT NULL,
    event_description TEXT NOT NULL,
    category_id UUID REFERENCES public.event_categories(category_id),
    event_date VARCHAR(100),
    emotional_impact_id UUID REFERENCES public.emotional_impact_types(impact_type_id),
    impact_level INTEGER DEFAULT 5,
    current_relevance_id UUID REFERENCES public.current_relevance_levels(relevance_level_id),
    player_knowledge_id UUID REFERENCES public.player_knowledge_levels(knowledge_level_id),
    affects_personality BOOLEAN DEFAULT true,
    -- triggers are now normalized into npc_event_triggers table
    dm_notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_npc_events_npc ON public.npc_significant_events (npc_id);
CREATE INDEX idx_npc_events_category ON public.npc_significant_events (category_id);
CREATE INDEX idx_npc_events_impact ON public.npc_significant_events (impact_level DESC);
CREATE INDEX idx_npc_events_emotional_impact ON public.npc_significant_events (emotional_impact_id);
CREATE INDEX idx_npc_events_relevance ON public.npc_significant_events (current_relevance_id);
CREATE INDEX idx_npc_events_player_knowledge ON public.npc_significant_events (player_knowledge_id);
CREATE INDEX idx_npc_events_affects_personality ON public.npc_significant_events (affects_personality);

CREATE TRIGGER npc_events_updated_at_trigger
    BEFORE UPDATE ON public.npc_significant_events
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

COMMENT ON TABLE public.npc_significant_events IS 'Major life events that shaped NPCs personality and behavior';
COMMENT ON COLUMN public.npc_significant_events.impact_level IS 'How much this event shaped their personality (1=minor, 10=life-defining)';
-- COMMENT ON COLUMN public.npc_significant_events.triggers IS 'Array of situations/items/people that might trigger memories of this event';
COMMENT ON COLUMN public.npc_significant_events.dm_notes IS 'Private DM notes about this event for campaign management';