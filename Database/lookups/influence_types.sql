-- =====================================================
-- Influence Types Lookup Table
-- =====================================================

DROP TABLE IF EXISTS public.influence_types CASCADE;

CREATE TABLE public.influence_types (
    influence_type_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    sort_order INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

INSERT INTO public.influence_types (name, description, sort_order) VALUES
('Economic', 'Financial, trade, and commercial influence', 1),
('Political', 'Governmental and administrative influence', 2),
('Military', 'Armed forces and defense influence', 3),
('Religious', 'Spiritual and faith-based influence', 4),
('Social', 'Cultural and community influence', 5),
('Criminal', 'Illegal and underground influence', 6),
('Magical', 'Arcane and supernatural influence', 7),
('Academic', 'Educational and scholarly influence', 8),
('Artisan', 'Craft and trade skill influence', 9),
('Information', 'Knowledge and intelligence influence', 10);

-- Index for sorting
CREATE INDEX idx_influence_types_sort ON public.influence_types (sort_order);
CREATE INDEX idx_influence_types_name_search ON public.influence_types USING gin(to_tsvector('english', name));

-- Comments
COMMENT ON TABLE public.influence_types IS 'Types of influence organizations can have in settlements';