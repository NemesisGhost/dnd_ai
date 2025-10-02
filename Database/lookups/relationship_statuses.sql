
DROP TABLE IF EXISTS public.relationship_statuses CASCADE;

CREATE TABLE public.relationship_statuses (
    status_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(50) NOT NULL UNIQUE,
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

INSERT INTO public.relationship_statuses (name, description) VALUES
('Active', 'Current, ongoing relationship'),
('Inactive', 'Relationship exists but is not currently active'),
('Hostile', 'Antagonistic or conflict-based relationship'),
('Friendly', 'Positive, amicable relationship'),
('Neutral', 'Neither positive nor negative relationship'),
('Pending', 'Relationship being established or negotiated'),
('Suspended', 'Temporarily halted relationship'),
('Terminated', 'Ended relationship');

CREATE INDEX idx_relationship_statuses_name ON public.relationship_statuses (name);

CREATE TRIGGER relationship_statuses_updated_at_trigger
    BEFORE UPDATE ON public.relationship_statuses
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

COMMENT ON TABLE public.relationship_statuses IS 'Lookup table for relationship status values';
COMMENT ON COLUMN public.relationship_statuses.name IS 'Status of the relationship (Active, Inactive, Hostile, Friendly, etc.)';