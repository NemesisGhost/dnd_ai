-- =====================================================
-- NPC Event Triggers Table (Normalized from npc_significant_events.triggers)
-- =====================================================

DROP TABLE IF EXISTS public.npc_event_triggers CASCADE;

CREATE TABLE public.npc_event_triggers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID NOT NULL REFERENCES public.npc_significant_events(event_id) ON DELETE CASCADE,
    trigger TEXT NOT NULL,
    notes TEXT,
    UNIQUE(event_id, trigger)
);

-- Indexes
CREATE INDEX idx_npc_event_triggers_event ON public.npc_event_triggers (event_id);

-- Comments
COMMENT ON TABLE public.npc_event_triggers IS 'Triggers for NPC significant events, normalized from TEXT[] array.';
COMMENT ON COLUMN public.npc_event_triggers.trigger IS 'Situation/item/person that might trigger memories of the event.';
