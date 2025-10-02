-- =====================================================
-- Age Categories Lookup Table
-- =====================================================

DROP TABLE IF EXISTS public.age_categories CASCADE;

CREATE TABLE public.age_categories (
    age_category_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(50) NOT NULL UNIQUE,
    description TEXT,
    sort_order INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

INSERT INTO public.age_categories (name, description, sort_order) VALUES
('Child', 'Young, not yet adult', 1),
('Young Adult', 'Recently matured', 2),
('Adult', 'Prime adult years', 3),
('Middle-aged', 'Experienced adult', 4),
('Elderly', 'Advanced in years', 5),
('Ancient', 'Extremely old', 6),
('Ageless', 'Timeless or immortal beings', 7);

-- Index for sorting
CREATE INDEX idx_age_categories_sort ON public.age_categories (sort_order);

-- Comments
COMMENT ON TABLE public.age_categories IS 'Standardized age categories for character development and roleplay';