-- =====================================================
-- Occupation Categories Lookup Table
-- =====================================================

DROP TABLE IF EXISTS public.occupation_categories CASCADE;

CREATE TABLE public.occupation_categories (
    category_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Insert occupation categories
INSERT INTO public.occupation_categories (name, description) VALUES
('Service', 'Occupations focused on providing services to customers and communities'),
('Craft', 'Skilled artisans and creators of goods'),
('Military', 'Combat-related professions and security roles'),
('Religious', 'Occupations related to faith, worship, and spiritual guidance'),
('Academic', 'Scholarly pursuits and knowledge-based professions'),
('Trade', 'Commercial activities, buying and selling goods'),
('Government', 'Administrative and political roles in governance'),
('Entertainment', 'Performers and those who provide amusement'),
('Arts', 'Creative professionals focused on artistic expression'),
('Agriculture', 'Food production and farming-related occupations'),
('Labor', 'Physical work and manual labor professions'),
('Criminal', 'Illegal or underground occupations'),
('Wilderness', 'Occupations dealing with nature and untamed lands'),
('Magical', 'Professions involving the use of magic and arcane arts'),
('Mystical', 'Occupations dealing with divination and otherworldly knowledge'),
('Solitary', 'Isolated professions with minimal social contact'),
('Aristocracy', 'Noble and high-class occupations');

-- Indexes for performance
CREATE INDEX idx_occupation_categories_name ON public.occupation_categories (name);

-- Comments
COMMENT ON TABLE public.occupation_categories IS 'Categories for grouping related occupations';