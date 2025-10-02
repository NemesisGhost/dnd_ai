-- =====================================================
-- Presence Levels Lookup Table
-- =====================================================

DROP TABLE IF EXISTS public.presence_levels CASCADE;

CREATE TABLE public.presence_levels (
    presence_level_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(50) NOT NULL UNIQUE,
    description TEXT,
    sort_order INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

INSERT INTO public.presence_levels (name, description, sort_order) VALUES
('Dominant', 'Controls or heavily influences the settlement', 1),
('Strong', 'Significant presence with notable influence', 2),
('Moderate', 'Established presence with some influence', 3),
('Weak', 'Minor presence with limited influence', 4),
('Hidden', 'Secret or covert presence', 5);

-- Index for sorting
CREATE INDEX idx_presence_levels_sort ON public.presence_levels (sort_order);
CREATE INDEX idx_presence_levels_name_search ON public.presence_levels USING gin(to_tsvector('english', name));

-- Comments
COMMENT ON TABLE public.presence_levels IS 'Standardized levels of organizational presence in settlements';