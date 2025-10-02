-- =====================================================
-- Tag Categories Lookup Table
-- =====================================================

DROP TABLE IF EXISTS public.tag_categories CASCADE;

CREATE TABLE public.tag_categories (
    category_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(50) NOT NULL UNIQUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Insert tag categories
INSERT INTO public.tag_categories (name) VALUES
('Role'),
('Personality'),
('Function'),
('Disposition'),
('Status'),
('Relationship'),
('Danger'),
('Knowledge'),
('Reliability'),
('Special');

-- Index for performance
CREATE INDEX idx_tag_categories_name ON public.tag_categories (name);

-- Comments
COMMENT ON TABLE public.tag_categories IS 'Categories for grouping NPC tags by type';