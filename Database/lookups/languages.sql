-- =====================================================
-- Languages Lookup Table
-- =====================================================

-- Languages lookup table
DROP TABLE IF EXISTS public.languages CASCADE;
CREATE TABLE public.languages (
    language_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL UNIQUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Insert common D&D languages
INSERT INTO public.languages (name) VALUES
('Common'), ('Elvish'), ('Dwarvish'), ('Halfling'), ('Gnomish'), ('Orcish'), 
('Giant'), ('Goblin'), ('Draconic'), ('Celestial'), ('Infernal'), ('Abyssal'),
('Primordial'), ('Sylvan'), ('Undercommon'), ('Thieves Cant'), ('Druidic'),
('Deep Speech'), ('Aquan'), ('Auran'), ('Ignan'), ('Terran');