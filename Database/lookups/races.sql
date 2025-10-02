-- =====================================================
-- Races Lookup Table
-- =====================================================

DROP TABLE IF EXISTS public.races CASCADE;

CREATE TABLE public.races (
    race_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    typical_lifespan VARCHAR(100),
    common_traits TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Insert common D&D races
INSERT INTO public.races (name, description, typical_lifespan) VALUES
('Human', 'Versatile and adaptable mortals', '80-100 years'),
('Elf', 'Long-lived magical beings', '700+ years'),
('Dwarf', 'Sturdy mountain folk', '300-400 years'),
('Halfling', 'Small, cheerful folk', '150-200 years'),
('Gnome', 'Small, curious tinkerers', '300-500 years'),
('Half-Elf', 'Mixed heritage', '150-200 years'),
('Half-Orc', 'Mixed heritage', '70-100 years'),
('Dragonborn', 'Draconic humanoids', '80-100 years'),
('Tiefling', 'Infernal heritage', '80-100 years'),
('Goliath', 'Mountain giants', '80-100 years'),
('Firbolg', 'Giant-kin forest dwellers', '400-500 years'),
('Kenku', 'Cursed bird-like humanoids', '60-70 years'),
('Tabaxi', 'Curious cat-folk', '80-100 years'),
('Warforged', 'Constructed beings', 'Unknown'),
('Githyanki', 'Astral plane warriors', '100+ years');

-- Index for searching
CREATE INDEX idx_races_name_search ON public.races USING gin(to_tsvector('english', name));

-- Comments
COMMENT ON TABLE public.races IS 'Standardized races for NPCs with descriptions and lifespans';