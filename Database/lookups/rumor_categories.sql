-- =====================================================
-- Rumor Categories Lookup Table
-- =====================================================

DROP TABLE IF EXISTS public.rumor_categories CASCADE;

CREATE TABLE public.rumor_categories (
    category_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL UNIQUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Insert rumor categories
INSERT INTO public.rumor_categories (name) VALUES
('Local gossip'),
('Political intrigue'),
('Personal secrets'),
('Business dealings'),
('Criminal activity'),
('Religious matters'),
('Military information'),
('Romantic affairs'),
('Family disputes'),
('Trade secrets'),
('Historical events'),
('Supernatural occurrences'),
('Health concerns'),
('Financial troubles'),
('Social scandals'),
('Professional rivalries'),
('Hidden connections'),
('Past misdeeds'),
('Future plans'),
('Mysterious disappearances');

-- Index for performance
CREATE INDEX idx_rumor_categories_name ON public.rumor_categories (name);

-- Comments
COMMENT ON TABLE public.rumor_categories IS 'Categories for classifying different types of rumors and gossip';