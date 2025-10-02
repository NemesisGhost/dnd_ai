-- =====================================================
-- Trade Specialty Types Lookup Table
-- =====================================================

DROP TABLE IF EXISTS public.trade_specialty_types CASCADE;

CREATE TABLE public.trade_specialty_types (
    specialty_type_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(50) NOT NULL UNIQUE,
    description TEXT,
    sort_order INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

INSERT INTO public.trade_specialty_types (name, description, sort_order) VALUES
('Export', 'Goods produced locally and sold to other settlements', 1),
('Import', 'Goods brought in from other settlements for local use', 2),
('Transit', 'Goods that pass through for trade elsewhere', 3),
('Production', 'Manufacturing or processing of goods', 4),
('Service', 'Services provided to traders and travelers', 5),
('Processing', 'Converting raw materials into finished goods', 6),
('Distribution', 'Hub for distributing goods to multiple destinations', 7);

-- Index for sorting
CREATE INDEX idx_trade_specialty_types_sort ON public.trade_specialty_types (sort_order);
CREATE INDEX idx_trade_specialty_types_name_search ON public.trade_specialty_types USING gin(to_tsvector('english', name));

-- Comments
COMMENT ON TABLE public.trade_specialty_types IS 'Types of trade specialties settlements can have';