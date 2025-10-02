-- =====================================================
-- Religious Influence Levels Lookup Table
-- =====================================================

DROP TABLE IF EXISTS public.religious_influence_levels CASCADE;

CREATE TABLE public.religious_influence_levels (
    influence_level_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(50) NOT NULL UNIQUE,
    description TEXT,
    political_power INTEGER, -- 1-10 scale of political influence
    social_impact INTEGER, -- 1-10 scale of social influence
    sort_order INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

INSERT INTO public.religious_influence_levels (name, description, political_power, social_impact, sort_order) VALUES
('Minimal', 'Very little influence on settlement affairs', 1, 1, 1),
('Moderate', 'Some influence on community decisions', 4, 4, 2),
('Strong', 'Significant influence on local politics and culture', 7, 7, 3),
('Dominant', 'Controls or heavily influences settlement governance', 10, 10, 4);

-- Index for sorting
CREATE INDEX idx_religious_influence_levels_sort ON public.religious_influence_levels (sort_order);
CREATE INDEX idx_religious_influence_levels_political ON public.religious_influence_levels (political_power);
CREATE INDEX idx_religious_influence_levels_social ON public.religious_influence_levels (social_impact);
CREATE INDEX idx_religious_influence_levels_name_search ON public.religious_influence_levels USING gin(to_tsvector('english', name));

-- Comments
COMMENT ON TABLE public.religious_influence_levels IS 'Levels of religious influence in settlements';
COMMENT ON COLUMN public.religious_influence_levels.political_power IS 'Political influence rating from 1 (none) to 10 (total control)';
COMMENT ON COLUMN public.religious_influence_levels.social_impact IS 'Social influence rating from 1 (none) to 10 (defines culture)';