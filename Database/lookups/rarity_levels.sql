-- =====================================================
-- Rarity Levels Lookup Table
-- =====================================================

DROP TABLE IF EXISTS public.rarity_levels CASCADE;

CREATE TABLE public.rarity_levels (
    rarity_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(50) NOT NULL UNIQUE,
    description TEXT,
    sort_order INTEGER NOT NULL UNIQUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Insert rarity levels in order of increasing rarity
INSERT INTO public.rarity_levels (name, description, sort_order) VALUES
('Common', 'Widely available services that can be found in most settlements', 1),
('Uncommon', 'Services that require some searching or specific conditions to find', 2),
('Rare', 'Services that are difficult to find and may require special connections', 3),
('Very Rare', 'Extremely difficult to find services, often requiring significant effort or resources to locate', 4),
('Legendary', 'Nearly mythical services that are almost impossible to find and may be unique', 5);

-- Index for performance
CREATE INDEX idx_rarity_levels_sort_order ON public.rarity_levels (sort_order);

-- Comments
COMMENT ON TABLE public.rarity_levels IS 'Standardized rarity levels for services, items, and other game elements';
COMMENT ON COLUMN public.rarity_levels.sort_order IS 'Numeric ordering from most common (1) to rarest (5)';