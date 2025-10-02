-- =====================================================
-- Knowledge Areas Lookup Table
-- =====================================================

DROP TABLE IF EXISTS public.knowledge_areas CASCADE;

CREATE TABLE public.knowledge_areas (
    knowledge_area_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(200) NOT NULL UNIQUE,
    category VARCHAR(100), -- Academic, Trade, Local, Military, Religious, etc.
    description TEXT,
    rarity VARCHAR(50), -- Common, Uncommon, Rare, Secret
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Insert knowledge areas organized by category and rarity
INSERT INTO public.knowledge_areas (name, category, description, rarity) VALUES

-- LOCAL KNOWLEDGE (Common)
('Local gossip', 'Local', 'Current rumors and news within the community', 'Common'),
('Town politics', 'Local', 'Local government affairs and political dynamics', 'Common'),
('Regional geography', 'Local', 'Knowledge of nearby areas, landmarks, and terrain', 'Common'),
('Local customs', 'Local', 'Traditions, festivals, and social norms of the area', 'Common'),
('Market prices', 'Local', 'Current costs of goods and services in the area', 'Common'),
('Weather patterns', 'Local', 'Seasonal changes and climate knowledge for the region', 'Common'),

-- TRADE & ECONOMICS (Common to Uncommon)
('Regional trade', 'Trade', 'Trade routes, merchants, and commercial relationships', 'Common'),
('Crafting techniques', 'Trade', 'Knowledge of creating goods and materials', 'Common'),
('Merchant networks', 'Trade', 'Connections and relationships in commercial circles', 'Uncommon'),
('Foreign markets', 'Trade', 'International trade opportunities and exotic goods', 'Uncommon'),
('Financial systems', 'Trade', 'Banking, loans, investments, and monetary policy', 'Uncommon'),
('Black market operations', 'Trade', 'Illegal trade networks and contraband goods', 'Rare'),

-- ACADEMIC KNOWLEDGE (Uncommon to Rare)
('Ancient history', 'Academic', 'Events and civilizations from distant past', 'Uncommon'),
('Magical theory', 'Academic', 'Understanding of how magic works and its principles', 'Uncommon'),
('Arcane lore', 'Academic', 'Deep knowledge of magical arts and spellcasting', 'Rare'),
('Planar cosmology', 'Academic', 'Knowledge of other planes of existence', 'Rare'),
('Lost civilizations', 'Academic', 'Knowledge of forgotten empires and their secrets', 'Rare'),
('Forbidden knowledge', 'Academic', 'Dangerous or taboo information', 'Secret'),

-- RELIGIOUS & SPIRITUAL (Common to Secret)
('Religious doctrine', 'Religious', 'Teachings and beliefs of established faiths', 'Common'),
('Divine magic', 'Religious', 'Understanding of clerical and divine spellcasting', 'Uncommon'),
('Celestial beings', 'Religious', 'Knowledge of angels, archons, and good outsiders', 'Uncommon'),
('Fiendish lore', 'Religious', 'Understanding of demons, devils, and evil outsiders', 'Rare'),
('Heretical texts', 'Religious', 'Forbidden or suppressed religious knowledge', 'Secret'),
('Divine prophecies', 'Religious', 'Sacred predictions and their interpretations', 'Secret'),

-- MILITARY & SECURITY (Common to Rare)
('Military tactics', 'Military', 'Combat strategies and battlefield coordination', 'Common'),
('Weapon expertise', 'Military', 'Deep knowledge of weapons and their use', 'Common'),
('Fortification design', 'Military', 'Castle and defensive construction knowledge', 'Uncommon'),
('Siege warfare', 'Military', 'Advanced military engineering and tactics', 'Uncommon'),
('Espionage techniques', 'Military', 'Spy craft and intelligence gathering', 'Rare'),
('Assassination methods', 'Military', 'Specialized knowledge of eliminating targets', 'Secret'),

-- NATURAL & WILDERNESS (Common to Rare)
('Animal behavior', 'Natural', 'Understanding of creature habits and patterns', 'Common'),
('Herbal medicine', 'Natural', 'Healing properties of plants and natural remedies', 'Common'),
('Wilderness survival', 'Natural', 'Skills for surviving in untamed environments', 'Common'),
('Monster lore', 'Natural', 'Knowledge of dangerous creatures and their weaknesses', 'Uncommon'),
('Druidic secrets', 'Natural', 'Sacred knowledge of natural balance and primal magic', 'Rare'),
('Elemental powers', 'Natural', 'Understanding of elemental forces and beings', 'Rare'),

-- SOCIAL & POLITICAL (Common to Secret)
('Noble genealogy', 'Social', 'Family trees and bloodlines of aristocracy', 'Common'),
('Court etiquette', 'Social', 'Proper behavior in noble and royal settings', 'Common'),
('Diplomatic protocol', 'Social', 'International relations and negotiation customs', 'Uncommon'),
('Political intrigue', 'Social', 'Hidden agendas and power struggles', 'Rare'),
('Royal secrets', 'Social', 'Classified information about ruling families', 'Secret'),
('Conspiracy networks', 'Social', 'Secret organizations and their hidden activities', 'Secret'),

-- CRIMINAL & UNDERWORLD (Uncommon to Secret)
('Criminal networks', 'Criminal', 'Underground organizations and their operations', 'Uncommon'),
('Security systems', 'Criminal', 'Knowledge of locks, traps, and protective measures', 'Uncommon'),
('Thieves cant', 'Criminal', 'Secret language and symbols of criminal organizations', 'Rare'),
('Smuggling routes', 'Criminal', 'Hidden paths for moving illegal goods', 'Rare'),
('Assassination guilds', 'Criminal', 'Secret organizations of professional killers', 'Secret'),
('Criminal masterminds', 'Criminal', 'Identity and operations of major crime bosses', 'Secret'),

-- MYSTICAL & OCCULT (Rare to Secret)
('Divination arts', 'Mystical', 'Fortune telling and future sight techniques', 'Uncommon'),
('Necromantic arts', 'Mystical', 'Magic dealing with death and undeath', 'Rare'),
('Demonology', 'Mystical', 'Summoning and binding of fiendish entities', 'Rare'),
('Eldritch mysteries', 'Mystical', 'Incomprehensible cosmic truths and alien knowledge', 'Secret'),
('Soul magic', 'Mystical', 'Manipulation of spiritual essence and life force', 'Secret'),
('Reality alteration', 'Mystical', 'Power to change fundamental laws of existence', 'Secret'),

-- HISTORICAL & LEGENDARY (Uncommon to Secret)
('Legendary artifacts', 'Historical', 'Knowledge of powerful magical items from history', 'Rare'),
('Fallen empires', 'Historical', 'Detailed history of collapsed civilizations', 'Uncommon'),
('War chronicles', 'Historical', 'Detailed accounts of major historical conflicts', 'Common'),
('Heroic legends', 'Historical', 'Stories and deeds of famous heroes', 'Common'),
('Lost treasures', 'Historical', 'Location of hidden wealth and valuable items', 'Rare'),
('Temporal anomalies', 'Historical', 'Knowledge of time magic and chronological disruptions', 'Secret'),

-- TECHNOLOGICAL & ENGINEERING (Common to Rare)
('Engineering principles', 'Technical', 'Construction and mechanical knowledge', 'Common'),
('Alchemical processes', 'Technical', 'Chemical reactions and potion brewing', 'Uncommon'),
('Clockwork mechanisms', 'Technical', 'Complex mechanical devices and automation', 'Uncommon'),
('Magical item creation', 'Technical', 'Crafting of enchanted objects and artifacts', 'Rare'),
('Artificer secrets', 'Technical', 'Advanced magical engineering and construction', 'Rare'),
('Planar mechanics', 'Technical', 'How planes of existence function and interact', 'Secret');

-- Indexes for common queries
CREATE INDEX idx_knowledge_areas_category ON public.knowledge_areas (category);
CREATE INDEX idx_knowledge_areas_rarity ON public.knowledge_areas (rarity);
CREATE INDEX idx_knowledge_areas_name_search ON public.knowledge_areas USING gin(to_tsvector('english', name));

-- Comments
COMMENT ON TABLE public.knowledge_areas IS 'Standardized knowledge domains with categories and rarity classifications';
COMMENT ON COLUMN public.knowledge_areas.rarity IS 'How common this knowledge is: Common, Uncommon, Rare, Secret';