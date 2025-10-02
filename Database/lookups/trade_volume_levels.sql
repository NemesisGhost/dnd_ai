-- =====================================================
-- Trade Volume Levels Lookup Table
-- =====================================================

DROP TABLE IF EXISTS public.trade_volume_levels CASCADE;

CREATE TABLE public.trade_volume_levels (
    trade_volume_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(50) NOT NULL UNIQUE,
    description TEXT,
    volume_score INTEGER, -- 1-10 scale for trade volume
    economic_impact VARCHAR(50), -- Impact on local economy
    employment_estimate VARCHAR(50), -- Estimated employment requirements
    sort_order INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

INSERT INTO public.trade_volume_levels (name, description, volume_score, economic_impact, employment_estimate, sort_order) VALUES
('Minimal', 'Very small scale, occasional trade', 1, 'Negligible', '1-5 people', 1),
('Low', 'Small but regular trade activity', 3, 'Minor', '5-20 people', 2),
('Moderate', 'Steady trade with consistent demand', 5, 'Moderate', '20-100 people', 3),
('High', 'Large volume with significant activity', 7, 'Major', '100-500 people', 4),
('Massive', 'Dominant trade activity, major operations', 9, 'Economic Driver', '500+ people', 5),
('Monopolistic', 'Complete control of the market', 10, 'Economic Foundation', 'Entire sectors', 6);

-- Indexes
CREATE INDEX idx_trade_volume_levels_sort ON public.trade_volume_levels (sort_order);
CREATE INDEX idx_trade_volume_levels_score ON public.trade_volume_levels (volume_score);
CREATE INDEX idx_trade_volume_levels_name_search ON public.trade_volume_levels USING gin(to_tsvector('english', name));

-- Comments
COMMENT ON TABLE public.trade_volume_levels IS 'Volume levels for trade activities and specialties';
COMMENT ON COLUMN public.trade_volume_levels.volume_score IS 'Numeric volume rating from 1 (minimal) to 10 (monopolistic)';
COMMENT ON COLUMN public.trade_volume_levels.economic_impact IS 'Impact level on local economy';
COMMENT ON COLUMN public.trade_volume_levels.employment_estimate IS 'Estimated employment requirements';