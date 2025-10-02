-- =====================================================
-- Relationship Intensity Levels Lookup Table
-- =====================================================

DROP TABLE IF EXISTS public.relationship_intensity_levels CASCADE;

CREATE TABLE public.relationship_intensity_levels (
    intensity_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(50) NOT NULL UNIQUE,
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

INSERT INTO public.relationship_intensity_levels (name, description) VALUES
-- Competition intensity
('Low', 'Minimal competition with little market overlap or conflict'),
('Moderate', 'Standard competitive relationship with some market overlap'),
('High', 'Intense competition with significant market overlap and active rivalry'),
('Fierce', 'Extremely intense competition with direct confrontation'),
-- Alliance intensity
('Weak', 'Casual or informal alliance with minimal integration'),
('Strong', 'Well-established alliance with significant collaboration'),
('Strategic', 'Deep strategic partnership with extensive integration and shared goals');

CREATE INDEX idx_relationship_intensity_levels_name ON public.relationship_intensity_levels (name);

CREATE TRIGGER relationship_intensity_levels_updated_at_trigger
    BEFORE UPDATE ON public.relationship_intensity_levels
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

COMMENT ON TABLE public.relationship_intensity_levels IS 'Lookup table for relationship intensity levels';
COMMENT ON COLUMN public.relationship_intensity_levels.name IS 'Intensity level (Low, Moderate, High, Fierce, Weak, Strong, Strategic)';