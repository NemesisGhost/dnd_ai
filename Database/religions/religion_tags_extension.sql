-- =====================================================
-- Religion-Specific Tag Categories and Tags Extension
-- This file extends the existing tags system with religion-specific categories
-- =====================================================

-- Add religion-specific tag categories
INSERT INTO public.tag_categories (name) VALUES
('Religious Doctrine'),
('Religious Practice'),
('Religious Influence'),
('Religious Alignment')
ON CONFLICT (name) DO NOTHING;

-- Add religion-specific tags
INSERT INTO public.tags (name, category_id, description) VALUES

-- RELIGIOUS DOCTRINE TAGS
('monotheistic', (SELECT category_id FROM public.tag_categories WHERE name = 'Religious Doctrine'), 'Worships a single deity'),
('polytheistic', (SELECT category_id FROM public.tag_categories WHERE name = 'Religious Doctrine'), 'Worships multiple deities'),
('pantheistic', (SELECT category_id FROM public.tag_categories WHERE name = 'Religious Doctrine'), 'Sees divinity in all of nature'),
('dualistic', (SELECT category_id FROM public.tag_categories WHERE name = 'Religious Doctrine'), 'Focuses on opposing forces of good and evil'),
('ancestral', (SELECT category_id FROM public.tag_categories WHERE name = 'Religious Doctrine'), 'Worships ancestors and family spirits'),
('philosophical', (SELECT category_id FROM public.tag_categories WHERE name = 'Religious Doctrine'), 'Based on philosophical principles rather than deities'),
('apocalyptic', (SELECT category_id FROM public.tag_categories WHERE name = 'Religious Doctrine'), 'Focuses on end times and final judgment'),
('redemptive', (SELECT category_id FROM public.tag_categories WHERE name = 'Religious Doctrine'), 'Emphasizes salvation and forgiveness'),
('fatalistic', (SELECT category_id FROM public.tag_categories WHERE name = 'Religious Doctrine'), 'Believes in predetermined destiny'),
('progressive', (SELECT category_id FROM public.tag_categories WHERE name = 'Religious Doctrine'), 'Adapts teachings to modern circumstances'),

-- RELIGIOUS PRACTICE TAGS
('ritualistic', (SELECT category_id FROM public.tag_categories WHERE name = 'Religious Practice'), 'Emphasizes complex ceremonies and rituals'),
('ascetic', (SELECT category_id FROM public.tag_categories WHERE name = 'Religious Practice'), 'Practices self-denial and simple living'),
('mystical', (SELECT category_id FROM public.tag_categories WHERE name = 'Religious Practice'), 'Seeks direct spiritual experience through meditation'),
('evangelical', (SELECT category_id FROM public.tag_categories WHERE name = 'Religious Practice'), 'Actively seeks to convert others'),
('contemplative', (SELECT category_id FROM public.tag_categories WHERE name = 'Religious Practice'), 'Focuses on prayer, meditation, and reflection'),
('communal', (SELECT category_id FROM public.tag_categories WHERE name = 'Religious Practice'), 'Emphasizes group worship and shared activities'),
('pilgrimage-focused', (SELECT category_id FROM public.tag_categories WHERE name = 'Religious Practice'), 'Requires or encourages religious journeys'),
('sacrifice-based', (SELECT category_id FROM public.tag_categories WHERE name = 'Religious Practice'), 'Uses offerings and sacrifices in worship'),
('seasonal', (SELECT category_id FROM public.tag_categories WHERE name = 'Religious Practice'), 'Tied to natural cycles and calendar events'),
('scholarly', (SELECT category_id FROM public.tag_categories WHERE name = 'Religious Practice'), 'Emphasizes study and learning of texts'),

-- RELIGIOUS INFLUENCE TAGS
('state-religion', (SELECT category_id FROM public.tag_categories WHERE name = 'Religious Influence'), 'Official religion of a government'),
('underground', (SELECT category_id FROM public.tag_categories WHERE name = 'Religious Influence'), 'Practices in secret due to persecution'),
('militant', (SELECT category_id FROM public.tag_categories WHERE name = 'Religious Influence'), 'Uses violence to advance religious goals'),
('peaceful', (SELECT category_id FROM public.tag_categories WHERE name = 'Religious Influence'), 'Strictly opposes violence and conflict'),
('political', (SELECT category_id FROM public.tag_categories WHERE name = 'Religious Influence'), 'Heavily involved in governance and politics'),
('charitable', (SELECT category_id FROM public.tag_categories WHERE name = 'Religious Influence'), 'Focuses on helping the poor and needy'),
('exclusive', (SELECT category_id FROM public.tag_categories WHERE name = 'Religious Influence'), 'Believes only they possess religious truth'),
('inclusive', (SELECT category_id FROM public.tag_categories WHERE name = 'Religious Influence'), 'Accepts other religions as valid paths'),
('reformist', (SELECT category_id FROM public.tag_categories WHERE name = 'Religious Influence'), 'Seeks to change society according to religious principles'),
('traditionalist', (SELECT category_id FROM public.tag_categories WHERE name = 'Religious Influence'), 'Maintains ancient practices without change'),

-- RELIGIOUS ALIGNMENT TAGS (For D&D morality system)
('lawful-good', (SELECT category_id FROM public.tag_categories WHERE name = 'Religious Alignment'), 'Promotes order, justice, and compassion'),
('lawful-neutral', (SELECT category_id FROM public.tag_categories WHERE name = 'Religious Alignment'), 'Values order and stability above good or evil'),
('lawful-evil', (SELECT category_id FROM public.tag_categories WHERE name = 'Religious Alignment'), 'Uses law and order to oppress and control'),
('neutral-good', (SELECT category_id FROM public.tag_categories WHERE name = 'Religious Alignment'), 'Focuses on doing good regardless of law or chaos'),
('true-neutral', (SELECT category_id FROM public.tag_categories WHERE name = 'Religious Alignment'), 'Seeks balance between all opposing forces'),
('neutral-evil', (SELECT category_id FROM public.tag_categories WHERE name = 'Religious Alignment'), 'Selfish and harmful but not systematically so'),
('chaotic-good', (SELECT category_id FROM public.tag_categories WHERE name = 'Religious Alignment'), 'Values freedom and individual good over law'),
('chaotic-neutral', (SELECT category_id FROM public.tag_categories WHERE name = 'Religious Alignment'), 'Prizes personal freedom above all else'),
('chaotic-evil', (SELECT category_id FROM public.tag_categories WHERE name = 'Religious Alignment'), 'Seeks to spread chaos and destruction'),

-- GENERAL RELIGIOUS TAGS (that can apply to religions, not just NPCs)
('healing-focused', (SELECT category_id FROM public.tag_categories WHERE name = 'Special'), 'Specializes in divine healing and medicine'),
('war-deity', (SELECT category_id FROM public.tag_categories WHERE name = 'Special'), 'Deity of war, battle, and conflict'),
('nature-deity', (SELECT category_id FROM public.tag_categories WHERE name = 'Special'), 'Deity of nature, animals, and wilderness'),
('knowledge-deity', (SELECT category_id FROM public.tag_categories WHERE name = 'Special'), 'Deity of wisdom, learning, and secrets'),
('death-deity', (SELECT category_id FROM public.tag_categories WHERE name = 'Special'), 'Deity of death, undeath, or the afterlife'),
('trickster-deity', (SELECT category_id FROM public.tag_categories WHERE name = 'Special'), 'Deity of lies, tricks, and deception'),
('forge-deity', (SELECT category_id FROM public.tag_categories WHERE name = 'Special'), 'Deity of crafting, smithing, and creation'),
('storm-deity', (SELECT category_id FROM public.tag_categories WHERE name = 'Special'), 'Deity of weather, storms, and the sky'),
('sea-deity', (SELECT category_id FROM public.tag_categories WHERE name = 'Special'), 'Deity of oceans, rivers, and water'),
('sun-deity', (SELECT category_id FROM public.tag_categories WHERE name = 'Special'), 'Deity of sun, light, and dawn'),
('moon-deity', (SELECT category_id FROM public.tag_categories WHERE name = 'Special'), 'Deity of moon, night, and dreams'),
('love-deity', (SELECT category_id FROM public.tag_categories WHERE name = 'Special'), 'Deity of love, beauty, and passion'),
('harvest-deity', (SELECT category_id FROM public.tag_categories WHERE name = 'Special'), 'Deity of agriculture, crops, and fertility')

ON CONFLICT (name) DO NOTHING;

-- =====================================================
-- Views removed as per requirements
-- =====================================================

-- =====================================================
-- Sample Usage of Extended Religion Tags
-- =====================================================

-- Example: Update the sample religions with more specific tags
DO $$
DECLARE
    eternal_flame_id UUID;
    old_ways_id UUID;
    seven_stars_id UUID;
BEGIN
    -- Get religion IDs
    SELECT religion_id INTO eternal_flame_id FROM public.religions WHERE name = 'Order of the Eternal Flame';
    SELECT religion_id INTO old_ways_id FROM public.religions WHERE name = 'The Old Ways';
    SELECT religion_id INTO seven_stars_id FROM public.religions WHERE name = 'Pantheon of the Seven Stars';
    
    -- Add specific religious tags for Order of the Eternal Flame
    IF eternal_flame_id IS NOT NULL THEN
        PERFORM add_religion_tag(eternal_flame_id, 'monotheistic', 'system', 'Worships Solarus the Light Bearer');
        PERFORM add_religion_tag(eternal_flame_id, 'lawful-good', 'system', 'Promotes justice and protection');
        PERFORM add_religion_tag(eternal_flame_id, 'ritualistic', 'system', 'Daily prayers and flame lighting ceremonies');
        PERFORM add_religion_tag(eternal_flame_id, 'sun-deity', 'system', 'Solarus is associated with light and dawn');
        PERFORM add_religion_tag(eternal_flame_id, 'healing-focused', 'system', 'Known for divine healing abilities');
    END IF;
    
    -- Add specific religious tags for The Old Ways
    IF old_ways_id IS NOT NULL THEN
        PERFORM add_religion_tag(old_ways_id, 'pantheistic', 'system', 'Sees divinity in all of nature');
        PERFORM add_religion_tag(old_ways_id, 'true-neutral', 'system', 'Seeks balance in all things');
        PERFORM add_religion_tag(old_ways_id, 'seasonal', 'system', 'Practices tied to natural cycles');
        PERFORM add_religion_tag(old_ways_id, 'nature-deity', 'system', 'Worships nature spirits');
        PERFORM add_religion_tag(old_ways_id, 'contemplative', 'system', 'Communion with nature through meditation');
        PERFORM add_religion_tag(old_ways_id, 'traditionalist', 'system', 'Maintains ancient druidic practices');
    END IF;
    
    -- Add specific religious tags for Pantheon of the Seven Stars
    IF seven_stars_id IS NOT NULL THEN
        PERFORM add_religion_tag(seven_stars_id, 'polytheistic', 'system', 'Worships seven celestial deities');
        PERFORM add_religion_tag(seven_stars_id, 'true-neutral', 'system', 'Balance between multiple divine aspects');
        PERFORM add_religion_tag(seven_stars_id, 'ritualistic', 'system', 'Complex star-watching ceremonies');
        PERFORM add_religion_tag(seven_stars_id, 'knowledge-deity', 'system', 'Some stars govern wisdom and learning');
        PERFORM add_religion_tag(seven_stars_id, 'inclusive', 'system', 'Multiple deities allow for diverse worship');
        PERFORM add_religion_tag(seven_stars_id, 'state-religion', 'system', 'Has strong national influence');
    END IF;
END $$;