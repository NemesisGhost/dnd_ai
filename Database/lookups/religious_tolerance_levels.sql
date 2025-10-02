-- =====================================================
-- Religious Tolerance Levels Lookup Table
-- =====================================================

DROP TABLE IF EXISTS public.religious_tolerance_levels CASCADE;

CREATE TABLE public.religious_tolerance_levels (
    tolerance_level_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(50) NOT NULL UNIQUE,
    description TEXT,
    tolerance_score INTEGER, -- -10 to +10 scale (negative = persecution, positive = acceptance)
    legal_status VARCHAR(100), -- Legal standing of the religion
    sort_order INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

INSERT INTO public.religious_tolerance_levels (name, description, tolerance_score, legal_status, sort_order) VALUES
('Banned', 'Completely prohibited, punishable by law', -10, 'Illegal', 1),
('Persecuted', 'Actively suppressed, followers face harassment', -7, 'Illegal but tolerated in private', 2),
('Discouraged', 'Officially discouraged but not illegal', -3, 'Legal but restricted', 3),
('Tolerated', 'Allowed but not encouraged', 0, 'Legal with limitations', 4),
('Accepted', 'Generally accepted by the community', 5, 'Full legal rights', 5),
('Favored', 'Actively supported by local authorities', 7, 'Legally protected and promoted', 6),
('Official', 'State or settlement sponsored religion', 10, 'Official state religion', 7);

-- Indexes
CREATE INDEX idx_religious_tolerance_levels_sort ON public.religious_tolerance_levels (sort_order);
CREATE INDEX idx_religious_tolerance_levels_score ON public.religious_tolerance_levels (tolerance_score);
CREATE INDEX idx_religious_tolerance_levels_name_search ON public.religious_tolerance_levels USING gin(to_tsvector('english', name));

-- Comments
COMMENT ON TABLE public.religious_tolerance_levels IS 'Levels of religious tolerance and acceptance in settlements';
COMMENT ON COLUMN public.religious_tolerance_levels.tolerance_score IS 'Tolerance rating from -10 (banned) to +10 (official)';
COMMENT ON COLUMN public.religious_tolerance_levels.legal_status IS 'Legal standing of religions at this tolerance level';