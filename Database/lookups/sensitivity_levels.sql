-- =====================================================
-- Sensitivity Levels Lookup Table
-- =====================================================

DROP TABLE IF EXISTS public.sensitivity_levels CASCADE;

CREATE TABLE public.sensitivity_levels (
    sensitivity_level_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(50) NOT NULL UNIQUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Insert sensitivity levels
INSERT INTO public.sensitivity_levels (name) VALUES
('Public'),
('Private'),
('Secret'),
('Dangerous');

-- Index for performance
CREATE INDEX idx_sensitivity_levels_name ON public.sensitivity_levels (name);

-- Comments
COMMENT ON TABLE public.sensitivity_levels IS 'Levels of sensitivity for rumors and information';