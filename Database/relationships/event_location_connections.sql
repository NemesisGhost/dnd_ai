-- =====================================================
-- Event Location Connections (Many-to-Many)
-- =====================================================

DROP TABLE IF EXISTS public.event_location_connections CASCADE;

CREATE TABLE public.event_location_connections (
    connection_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id UUID NOT NULL REFERENCES public.npc_significant_events(event_id) ON DELETE CASCADE,
    location_name VARCHAR(200) NOT NULL,
    location_type VARCHAR(100),
    significance_to_event VARCHAR(100),
    emotional_association VARCHAR(50),
    can_return BOOLEAN DEFAULT true,
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_event_location_connections_event ON public.event_location_connections (event_id);
CREATE INDEX idx_event_location_connections_location ON public.event_location_connections (location_name);
CREATE INDEX idx_event_location_connections_type ON public.event_location_connections (location_type);
CREATE INDEX idx_event_location_connections_significance ON public.event_location_connections (significance_to_event);
CREATE INDEX idx_event_location_connections_can_return ON public.event_location_connections (can_return);

CREATE TRIGGER event_location_connections_updated_at_trigger
    BEFORE UPDATE ON public.event_location_connections
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

COMMENT ON TABLE public.event_location_connections IS 'Locations where significant events occurred, with context about their role';
COMMENT ON COLUMN public.event_location_connections.significance_to_event IS 'How important this location was to the event (Primary, Secondary, etc.)';
COMMENT ON COLUMN public.event_location_connections.can_return IS 'Whether the location still exists and is accessible';