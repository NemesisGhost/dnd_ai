-- =====================================================
-- Skill Levels Lookup Table
-- =====================================================

DROP TABLE IF EXISTS public.skill_levels CASCADE;

CREATE TABLE public.skill_levels (
    skill_level_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(50) NOT NULL UNIQUE,
    description TEXT,
    numeric_value INTEGER NOT NULL UNIQUE, -- For ordering and comparisons
    proficiency_range VARCHAR(100), -- Years of experience typically required
    examples TEXT, -- Example occupations or activities at this level
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Insert skill levels
INSERT INTO public.skill_levels (name, description, numeric_value, proficiency_range, examples) VALUES
('Basic', 'Entry-level skills that can be learned quickly with minimal training', 1, '0-2 years', 'Simple information sharing, basic labor, routine tasks'),
('Intermediate', 'Moderate skill level requiring some training and experience', 2, '2-5 years', 'Skilled crafting, specialized knowledge, moderate complexity services'),
('Advanced', 'High skill level requiring extensive training and significant experience', 3, '5-10 years', 'Master craftsmanship, combat expertise, complex problem solving'),
('Master', 'Expert-level skills representing the pinnacle of proficiency in a field', 4, '10+ years', 'Legendary artisans, archmages, renowned specialists, unique expertise'),
('Legendary', 'Mythical skill levels beyond normal mastery, often touched by destiny or magic', 5, 'Lifetime dedication', 'Heroes of renown, legendary figures, those blessed by gods or fate');

-- Indexes for performance
CREATE INDEX idx_skill_levels_name ON public.skill_levels (name);
CREATE INDEX idx_skill_levels_numeric_value ON public.skill_levels (numeric_value);

-- Comments
COMMENT ON TABLE public.skill_levels IS 'Standardized skill proficiency levels for services and abilities';
COMMENT ON COLUMN public.skill_levels.numeric_value IS 'Numeric representation for ordering and comparison operations';