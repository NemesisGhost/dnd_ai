-- =====================================================
-- Topic Categories Lookup Table
-- =====================================================

DROP TABLE IF EXISTS public.topic_categories CASCADE;

CREATE TABLE public.topic_categories (
    category_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Insert topic categories
INSERT INTO public.topic_categories (name, description) VALUES
('Personal', 'Personal life, family, relationships, and private matters'),
('Professional', 'Work-related topics, career, and occupational knowledge'),
('Hobby', 'Personal interests, hobbies, and recreational activities'),
('Opinion', 'Personal views, beliefs, and perspectives on various subjects'),
('Memory', 'Past experiences, historical events, and nostalgic recollections'),
('Current Events', 'Recent happenings, news, and ongoing situations'),
('Local Knowledge', 'Information about the local area, people, and customs'),
('Rumors', 'Gossip, unconfirmed information, and hearsay'),
('Secrets', 'Confidential information and hidden knowledge'),
('Politics', 'Political views, governance, and power structures'),
('Religion', 'Spiritual beliefs, religious practices, and divine matters'),
('Trade', 'Commerce, business dealings, and economic matters'),
('Adventure', 'Dangerous exploits, quests, and heroic deeds'),
('Romance', 'Love interests, relationships, and matters of the heart'),
('Fear', 'Phobias, anxieties, and things that frighten the NPC'),
('Dreams', 'Aspirations, goals, and future ambitions'),
('Regrets', 'Past mistakes, missed opportunities, and things they wish they could change'),
('Philosophy', 'Deep thoughts about life, existence, and meaning'),
('Entertainment', 'Stories, jokes, games, and amusing diversions'),
('Education', 'Learning, teaching, and knowledge sharing');

-- Indexes for performance
CREATE INDEX idx_topic_categories_name ON public.topic_categories (name);

-- Comments
COMMENT ON TABLE public.topic_categories IS 'Categories for organizing conversation topics';