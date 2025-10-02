-- =====================================================
-- Occupation Knowledge Areas Junction Table
-- Many-to-many relationship between occupations and knowledge areas
-- =====================================================

DROP TABLE IF EXISTS public.occupation_knowledge_areas CASCADE;

CREATE TABLE public.occupation_knowledge_areas (
    occupation_id UUID REFERENCES public.occupations(occupation_id) ON DELETE CASCADE,
    knowledge_area_id UUID REFERENCES public.knowledge_areas(knowledge_area_id) ON DELETE CASCADE,
    proficiency_level VARCHAR(50) DEFAULT 'Common', -- Common, Proficient, Expert
    is_typical BOOLEAN DEFAULT TRUE, -- Whether this knowledge is typical for this occupation
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    PRIMARY KEY (occupation_id, knowledge_area_id)
);

-- Insert typical knowledge areas for each occupation
-- Service Industry
INSERT INTO public.occupation_knowledge_areas (occupation_id, knowledge_area_id, proficiency_level, is_typical)
SELECT 
    o.occupation_id,
    ka.knowledge_area_id,
    'Proficient',
    TRUE
FROM public.occupations o
CROSS JOIN public.knowledge_areas ka
WHERE 
    (o.name = 'Tavern Owner' AND ka.name IN ('Local gossip', 'Town politics', 'Regional trade')) OR
    (o.name = 'Innkeeper' AND ka.name IN ('Local gossip', 'Regional geography', 'Local customs')) OR
    (o.name = 'Shopkeeper' AND ka.name IN ('Market prices', 'Regional trade', 'Local customs')) OR
    (o.name = 'Barkeep' AND ka.name IN ('Local gossip', 'Local customs')) OR
    
    -- Crafting & Trade
    (o.name = 'Blacksmith' AND ka.name IN ('Crafting techniques', 'Weapon expertise', 'Market prices')) OR
    (o.name = 'Carpenter' AND ka.name IN ('Crafting techniques', 'Engineering principles', 'Market prices')) OR
    (o.name = 'Jeweler' AND ka.name IN ('Crafting techniques', 'Market prices', 'Regional trade')) OR
    (o.name = 'Alchemist' AND ka.name IN ('Alchemical processes', 'Herbal medicine', 'Magical theory')) OR
    (o.name = 'Tailor' AND ka.name IN ('Crafting techniques', 'Local customs', 'Market prices')) OR
    
    -- Military & Security
    (o.name = 'Guard Captain' AND ka.name IN ('Military tactics', 'Criminal networks', 'Local gossip')) OR
    (o.name = 'Town Guard' AND ka.name IN ('Criminal networks', 'Local gossip', 'Security systems')) OR
    (o.name = 'Soldier' AND ka.name IN ('Military tactics', 'Weapon expertise', 'Fortification design')) OR
    (o.name = 'Mercenary' AND ka.name IN ('Military tactics', 'Weapon expertise', 'Regional geography')) OR
    
    -- Religious
    (o.name = 'Priest' AND ka.name IN ('Religious doctrine', 'Divine magic', 'Local customs')) OR
    (o.name = 'Temple Acolyte' AND ka.name IN ('Religious doctrine', 'Local customs')) OR
    (o.name = 'Paladin' AND ka.name IN ('Divine magic', 'Military tactics', 'Religious doctrine')) OR
    
    -- Academic & Scholarly
    (o.name = 'Scholar' AND ka.name IN ('Ancient history', 'Magical theory', 'Arcane lore')) OR
    (o.name = 'Librarian' AND ka.name IN ('Ancient history', 'Local customs', 'Academic')) OR
    (o.name = 'Sage' AND ka.name IN ('Ancient history', 'Magical theory', 'Lost civilizations')) OR
    (o.name = 'Scribe' AND ka.name IN ('Local customs', 'Noble genealogy', 'Court etiquette')) OR
    
    -- Trade & Commerce
    (o.name = 'Merchant' AND ka.name IN ('Regional trade', 'Market prices', 'Merchant networks')) OR
    (o.name = 'Caravan Leader' AND ka.name IN ('Regional trade', 'Regional geography', 'Merchant networks')) OR
    (o.name = 'Banker' AND ka.name IN ('Financial systems', 'Regional trade', 'Noble genealogy')) OR
    
    -- Governance & Law
    (o.name = 'Mayor' AND ka.name IN ('Town politics', 'Local customs', 'Diplomatic protocol')) OR
    (o.name = 'Tax Collector' AND ka.name IN ('Financial systems', 'Local customs', 'Noble genealogy')) OR
    (o.name = 'Judge' AND ka.name IN ('Court etiquette', 'Noble genealogy', 'Local customs')) OR
    
    -- Entertainment & Arts
    (o.name = 'Bard' AND ka.name IN ('Heroic legends', 'Local gossip', 'Court etiquette')) OR
    (o.name = 'Storyteller' AND ka.name IN ('Heroic legends', 'Ancient history', 'Local customs')) OR
    (o.name = 'Artist' AND ka.name IN ('Court etiquette', 'Noble genealogy', 'Local customs')) OR
    
    -- Labor & Agriculture
    (o.name = 'Farmer' AND ka.name IN ('Weather patterns', 'Herbal medicine', 'Market prices')) OR
    (o.name = 'Fisherman' AND ka.name IN ('Weather patterns', 'Animal behavior', 'Market prices')) OR
    (o.name = 'Miner' AND ka.name IN ('Engineering principles', 'Regional geography', 'Market prices')) OR
    (o.name = 'Dock Worker' AND ka.name IN ('Regional trade', 'Weather patterns', 'Merchant networks')) OR
    
    -- Criminal & Underground
    (o.name = 'Thief' AND ka.name IN ('Criminal networks', 'Security systems', 'Local gossip')) OR
    (o.name = 'Smuggler' AND ka.name IN ('Criminal networks', 'Regional geography', 'Black market operations')) OR
    (o.name = 'Fence' AND ka.name IN ('Criminal networks', 'Black market operations', 'Market prices')) OR
    
    -- Wilderness & Exploration
    (o.name = 'Hunter' AND ka.name IN ('Animal behavior', 'Wilderness survival', 'Regional geography')) OR
    (o.name = 'Guide' AND ka.name IN ('Regional geography', 'Wilderness survival', 'Monster lore')) OR
    (o.name = 'Ranger' AND ka.name IN ('Wilderness survival', 'Monster lore', 'Animal behavior')) OR
    
    -- Magic & Mystical
    (o.name = 'Wizard' AND ka.name IN ('Arcane lore', 'Magical theory', 'Ancient history')) OR
    (o.name = 'Sorcerer' AND ka.name IN ('Magical theory', 'Arcane lore', 'Elemental powers')) OR
    (o.name = 'Warlock' AND ka.name IN ('Eldritch mysteries', 'Fiendish lore', 'Forbidden knowledge')) OR
    (o.name = 'Witch' AND ka.name IN ('Herbal medicine', 'Necromantic arts', 'Local customs')) OR
    
    -- Unique Roles
    (o.name = 'Oracle' AND ka.name IN ('Divination arts', 'Divine prophecies', 'Religious doctrine')) OR
    (o.name = 'Hermit' AND ka.name IN ('Wilderness survival', 'Ancient history', 'Religious doctrine')) OR
    (o.name = 'Noble' AND ka.name IN ('Court etiquette', 'Noble genealogy', 'Political intrigue')) OR
    (o.name = 'Diplomat' AND ka.name IN ('Diplomatic protocol', 'Political intrigue', 'Court etiquette'));

CREATE INDEX idx_occupation_knowledge_areas_occupation ON public.occupation_knowledge_areas (occupation_id);
CREATE INDEX idx_occupation_knowledge_areas_knowledge ON public.occupation_knowledge_areas (knowledge_area_id);
CREATE INDEX idx_occupation_knowledge_areas_proficiency ON public.occupation_knowledge_areas (proficiency_level);

COMMENT ON TABLE public.occupation_knowledge_areas IS 'Many-to-many relationship between occupations and knowledge areas with proficiency levels';
COMMENT ON COLUMN public.occupation_knowledge_areas.proficiency_level IS 'Level of knowledge: Common, Proficient, Expert';
COMMENT ON COLUMN public.occupation_knowledge_areas.is_typical IS 'Whether this knowledge area is typical for this occupation';