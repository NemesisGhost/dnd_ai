-- =====================================================
-- Quality Levels Lookup Table
-- =====================================================

DROP TABLE IF EXISTS public.quality_levels CASCADE;

CREATE TABLE public.quality_levels (
    quality_level_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(50) NOT NULL UNIQUE,
    description TEXT,
    quality_score INTEGER, -- 1-10 scale for quality rating
    price_modifier DECIMAL(4,2), -- Multiplier for base prices (0.5 = half price, 2.0 = double price)
    sort_order INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

INSERT INTO public.quality_levels (name, description, quality_score, price_modifier, sort_order) VALUES
('Poor', 'Below average quality, functional but flawed', 2, 0.5, 1),
('Fair', 'Average quality, meets basic expectations', 4, 0.8, 2),
('Good', 'Above average quality, reliable and well-made', 6, 1.0, 3),
('Excellent', 'High quality, superior craftsmanship', 8, 1.5, 4),
('Legendary', 'Exceptional quality, renowned across regions', 10, 3.0, 5);

-- Indexes
CREATE INDEX idx_quality_levels_sort ON public.quality_levels (sort_order);
CREATE INDEX idx_quality_levels_score ON public.quality_levels (quality_score);
CREATE INDEX idx_quality_levels_name_search ON public.quality_levels USING gin(to_tsvector('english', name));

-- Comments
COMMENT ON TABLE public.quality_levels IS 'Quality ratings for trade specialties and products';
COMMENT ON COLUMN public.quality_levels.quality_score IS 'Numeric quality rating from 1 (terrible) to 10 (legendary)';
COMMENT ON COLUMN public.quality_levels.price_modifier IS 'Price multiplier based on quality level';