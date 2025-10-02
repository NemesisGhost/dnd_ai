-- =====================================================
-- Service Categories Lookup Table
-- Requires: skill_levels.sql
-- =====================================================

DROP TABLE IF EXISTS public.service_categories CASCADE;

CREATE TABLE public.service_categories (
    category_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    typical_cost_range VARCHAR(100), -- Low, Medium, High, Variable
    skill_level_id UUID REFERENCES public.skill_levels(skill_level_id),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Insert service categories
INSERT INTO public.service_categories (name, description, typical_cost_range, skill_level_id) VALUES
('Information', 'Providing knowledge, rumors, and intelligence', 'Low', (SELECT skill_level_id FROM public.skill_levels WHERE name = 'Basic')),
('Crafting', 'Creating, repairing, or modifying items', 'Medium', (SELECT skill_level_id FROM public.skill_levels WHERE name = 'Intermediate')),
('Transportation', 'Moving people or goods from one place to another', 'Medium', (SELECT skill_level_id FROM public.skill_levels WHERE name = 'Basic')),
('Combat', 'Fighting, protection, and martial services', 'High', (SELECT skill_level_id FROM public.skill_levels WHERE name = 'Advanced')),
('Magic', 'Spellcasting, enchanting, and magical services', 'High', (SELECT skill_level_id FROM public.skill_levels WHERE name = 'Advanced')),
('Healing', 'Medical treatment and recovery services', 'Medium', (SELECT skill_level_id FROM public.skill_levels WHERE name = 'Intermediate')),
('Training', 'Teaching skills or providing instruction', 'Medium', (SELECT skill_level_id FROM public.skill_levels WHERE name = 'Advanced')),
('Entertainment', 'Performance, storytelling, and amusement', 'Low', (SELECT skill_level_id FROM public.skill_levels WHERE name = 'Intermediate')),
('Investigation', 'Gathering evidence, tracking, and detective work', 'Medium', (SELECT skill_level_id FROM public.skill_levels WHERE name = 'Intermediate')),
('Negotiation', 'Mediation, diplomacy, and deal-making', 'Medium', (SELECT skill_level_id FROM public.skill_levels WHERE name = 'Advanced')),
('Religious', 'Spiritual services, blessings, and ceremonies', 'Variable', (SELECT skill_level_id FROM public.skill_levels WHERE name = 'Intermediate')),
('Criminal', 'Illegal or underground services', 'High', (SELECT skill_level_id FROM public.skill_levels WHERE name = 'Advanced')),
('Trade', 'Buying, selling, and commercial services', 'Variable', (SELECT skill_level_id FROM public.skill_levels WHERE name = 'Basic')),
('Construction', 'Building, renovation, and engineering services', 'High', (SELECT skill_level_id FROM public.skill_levels WHERE name = 'Advanced')),
('Agriculture', 'Farming, animal care, and food production', 'Low', (SELECT skill_level_id FROM public.skill_levels WHERE name = 'Basic')),
('Administrative', 'Record keeping, documentation, and bureaucratic services', 'Low', (SELECT skill_level_id FROM public.skill_levels WHERE name = 'Basic')),
('Social', 'Introductions, networking, and social facilitation', 'Medium', (SELECT skill_level_id FROM public.skill_levels WHERE name = 'Intermediate')),
('Technical', 'Specialized knowledge and technical expertise', 'High', (SELECT skill_level_id FROM public.skill_levels WHERE name = 'Master')),
('Wilderness', 'Survival, tracking, and nature-related services', 'Medium', (SELECT skill_level_id FROM public.skill_levels WHERE name = 'Intermediate')),
('Artistic', 'Creative works, commissioned art, and cultural services', 'Variable', (SELECT skill_level_id FROM public.skill_levels WHERE name = 'Advanced'));

-- Indexes for performance
CREATE INDEX idx_service_categories_name ON public.service_categories (name);
CREATE INDEX idx_service_categories_cost_range ON public.service_categories (typical_cost_range);
CREATE INDEX idx_service_categories_skill_level ON public.service_categories (skill_level_id);

-- Comments
COMMENT ON TABLE public.service_categories IS 'Categories of services that can be provided based on occupational skills';
COMMENT ON COLUMN public.service_categories.skill_level_id IS 'Foreign key to skill_levels table indicating minimum skill required';