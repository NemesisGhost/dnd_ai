-- =====================================================
-- Occupations Table
-- Requires: occupation_categories.sql
-- =====================================================

DROP TABLE IF EXISTS public.occupations CASCADE;

CREATE TABLE public.occupations (
    occupation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(200) NOT NULL UNIQUE,
    category_id UUID REFERENCES public.occupation_categories(category_id),
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Insert common occupations with category references
INSERT INTO public.occupations (name, category_id, description) VALUES
-- Service Industry
('Tavern Owner', (SELECT category_id FROM public.occupation_categories WHERE name = 'Service'), 'Owns and operates a tavern, serving drinks and meals to travelers and locals'),
('Innkeeper', (SELECT category_id FROM public.occupation_categories WHERE name = 'Service'), 'Provides lodging and hospitality services to travelers'),
('Shopkeeper', (SELECT category_id FROM public.occupation_categories WHERE name = 'Service'), 'Operates a retail establishment selling various goods'),
('Barkeep', (SELECT category_id FROM public.occupation_categories WHERE name = 'Service'), 'Serves drinks and maintains atmosphere in taverns and bars'),

-- Crafting & Trade
('Blacksmith', (SELECT category_id FROM public.occupation_categories WHERE name = 'Craft'), 'Works with metal to create tools, weapons, and armor'),
('Carpenter', (SELECT category_id FROM public.occupation_categories WHERE name = 'Craft'), 'Constructs and repairs wooden structures and furniture'),
('Jeweler', (SELECT category_id FROM public.occupation_categories WHERE name = 'Craft'), 'Creates and repairs jewelry and works with precious stones'),
('Alchemist', (SELECT category_id FROM public.occupation_categories WHERE name = 'Craft'), 'Mixes potions and studies chemical processes'),
('Tailor', (SELECT category_id FROM public.occupation_categories WHERE name = 'Craft'), 'Creates and alters clothing and fabric goods'),

-- Military & Security
('Guard Captain', (SELECT category_id FROM public.occupation_categories WHERE name = 'Military'), 'Leads and coordinates local security forces'),
('Town Guard', (SELECT category_id FROM public.occupation_categories WHERE name = 'Military'), 'Maintains order and security within settlements'),
('Soldier', (SELECT category_id FROM public.occupation_categories WHERE name = 'Military'), 'Professional warrior serving in organized military forces'),
('Mercenary', (SELECT category_id FROM public.occupation_categories WHERE name = 'Military'), 'Warrior for hire, taking contracts for combat services'),

-- Religious
('Priest', (SELECT category_id FROM public.occupation_categories WHERE name = 'Religious'), 'Religious leader who conducts ceremonies and provides spiritual guidance'),
('Temple Acolyte', (SELECT category_id FROM public.occupation_categories WHERE name = 'Religious'), 'Junior religious member assisting with temple duties'),
('Paladin', (SELECT category_id FROM public.occupation_categories WHERE name = 'Religious'), 'Holy warrior combining martial prowess with divine magic'),

-- Academic & Scholarly
('Scholar', (SELECT category_id FROM public.occupation_categories WHERE name = 'Academic'), 'Researcher and academic focused on advancing knowledge'),
('Librarian', (SELECT category_id FROM public.occupation_categories WHERE name = 'Academic'), 'Maintains and organizes collections of books and knowledge'),
('Sage', (SELECT category_id FROM public.occupation_categories WHERE name = 'Academic'), 'Wise individual with deep knowledge of various subjects'),
('Scribe', (SELECT category_id FROM public.occupation_categories WHERE name = 'Academic'), 'Professional writer and document keeper'),

-- Trade & Commerce
('Merchant', (SELECT category_id FROM public.occupation_categories WHERE name = 'Trade'), 'Buys and sells goods, often traveling between markets'),
('Caravan Leader', (SELECT category_id FROM public.occupation_categories WHERE name = 'Trade'), 'Organizes and leads trading expeditions'),
('Banker', (SELECT category_id FROM public.occupation_categories WHERE name = 'Trade'), 'Handles financial transactions and manages monetary systems'),

-- Governance & Law
('Mayor', (SELECT category_id FROM public.occupation_categories WHERE name = 'Government'), 'Elected or appointed leader of a settlement'),
('Tax Collector', (SELECT category_id FROM public.occupation_categories WHERE name = 'Government'), 'Gathers taxes and fees for government operations'),
('Judge', (SELECT category_id FROM public.occupation_categories WHERE name = 'Government'), 'Presides over legal proceedings and renders judgments'),

-- Entertainment & Arts
('Bard', (SELECT category_id FROM public.occupation_categories WHERE name = 'Entertainment'), 'Traveling performer who tells stories and plays music'),
('Storyteller', (SELECT category_id FROM public.occupation_categories WHERE name = 'Entertainment'), 'Specializes in sharing tales and oral traditions'),
('Artist', (SELECT category_id FROM public.occupation_categories WHERE name = 'Arts'), 'Creates visual art and artistic works'),

-- Labor & Agriculture
('Farmer', (SELECT category_id FROM public.occupation_categories WHERE name = 'Agriculture'), 'Cultivates crops and raises livestock'),
('Fisherman', (SELECT category_id FROM public.occupation_categories WHERE name = 'Agriculture'), 'Catches fish and other aquatic life for food'),
('Miner', (SELECT category_id FROM public.occupation_categories WHERE name = 'Labor'), 'Extracts minerals and ores from underground'),
('Dock Worker', (SELECT category_id FROM public.occupation_categories WHERE name = 'Labor'), 'Loads and unloads cargo at ports and docks'),

-- Criminal & Underground
('Thief', (SELECT category_id FROM public.occupation_categories WHERE name = 'Criminal'), 'Steals property and valuables through stealth'),
('Smuggler', (SELECT category_id FROM public.occupation_categories WHERE name = 'Criminal'), 'Illegally transports contraband goods'),
('Fence', (SELECT category_id FROM public.occupation_categories WHERE name = 'Criminal'), 'Buys and sells stolen goods'),

-- Wilderness & Exploration
('Hunter', (SELECT category_id FROM public.occupation_categories WHERE name = 'Wilderness'), 'Tracks and kills animals for food and materials'),
('Guide', (SELECT category_id FROM public.occupation_categories WHERE name = 'Wilderness'), 'Leads travelers through dangerous or unfamiliar terrain'),
('Ranger', (SELECT category_id FROM public.occupation_categories WHERE name = 'Wilderness'), 'Protects wilderness areas and tracks threats'),

-- Magic & Mystical
('Wizard', (SELECT category_id FROM public.occupation_categories WHERE name = 'Magical'), 'Studies and practices arcane magic through research and learning'),
('Sorcerer', (SELECT category_id FROM public.occupation_categories WHERE name = 'Magical'), 'Wields innate magical power through natural ability'),
('Warlock', (SELECT category_id FROM public.occupation_categories WHERE name = 'Magical'), 'Gains magical power through pacts with otherworldly entities'),
('Witch', (SELECT category_id FROM public.occupation_categories WHERE name = 'Magical'), 'Practices natural magic and traditional remedies'),

-- Unique Roles
('Oracle', (SELECT category_id FROM public.occupation_categories WHERE name = 'Mystical'), 'Provides prophetic visions and divine insights'),
('Hermit', (SELECT category_id FROM public.occupation_categories WHERE name = 'Solitary'), 'Lives in isolation, often pursuing spiritual or philosophical goals'),
('Noble', (SELECT category_id FROM public.occupation_categories WHERE name = 'Aristocracy'), 'Member of aristocratic class with inherited status'),
('Diplomat', (SELECT category_id FROM public.occupation_categories WHERE name = 'Government'), 'Represents governments in international relations');

-- Indexes for performance
CREATE INDEX idx_occupations_category_id ON public.occupations (category_id);
CREATE INDEX idx_occupations_name_search ON public.occupations USING gin(to_tsvector('english', name));

-- Comments
COMMENT ON TABLE public.occupations IS 'Standardized occupations with category references';