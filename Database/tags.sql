-- =====================================================
-- NPC Tags Lookup Table
-- Requires: tag_categories.sql
-- =====================================================

DROP TABLE IF EXISTS public.tags CASCADE;

CREATE TABLE public.tags (
    tag_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL UNIQUE,
    category_id UUID REFERENCES public.tag_categories(category_id),
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

INSERT INTO public.tags (name, category_id, description) VALUES

-- ROLE TAGS (What they do)
('informant', (SELECT category_id FROM public.tag_categories WHERE name = 'Role'), 'Provides information and rumors to players'),
('merchant', (SELECT category_id FROM public.tag_categories WHERE name = 'Role'), 'Buys and sells goods to players'),
('quest-giver', (SELECT category_id FROM public.tag_categories WHERE name = 'Role'), 'Offers missions and tasks to players'),
('skill-trainer', (SELECT category_id FROM public.tag_categories WHERE name = 'Role'), 'Can teach abilities or knowledge to players'),
('guide', (SELECT category_id FROM public.tag_categories WHERE name = 'Role'), 'Can lead players to locations or through areas'),
('contact', (SELECT category_id FROM public.tag_categories WHERE name = 'Role'), 'Serves as connection to other NPCs or organizations'),
('rival', (SELECT category_id FROM public.tag_categories WHERE name = 'Role'), 'Competes with or opposes players in non-hostile way'),
('ally', (SELECT category_id FROM public.tag_categories WHERE name = 'Role'), 'Supports and assists players'),
('patron', (SELECT category_id FROM public.tag_categories WHERE name = 'Role'), 'Sponsors or funds player activities'),
('employer', (SELECT category_id FROM public.tag_categories WHERE name = 'Role'), 'Hires players for work or services'),

-- PERSONALITY TAGS (How they act)
('friendly', (SELECT category_id FROM public.tag_categories WHERE name = 'Personality'), 'Warm, welcoming, and helpful disposition'),
('hostile', (SELECT category_id FROM public.tag_categories WHERE name = 'Personality'), 'Aggressive, unfriendly, or antagonistic'),
('suspicious', (SELECT category_id FROM public.tag_categories WHERE name = 'Personality'), 'Distrustful and wary of others'),
('mysterious', (SELECT category_id FROM public.tag_categories WHERE name = 'Personality'), 'Enigmatic with hidden motives or secrets'),
('eccentric', (SELECT category_id FROM public.tag_categories WHERE name = 'Personality'), 'Quirky, unusual, or unconventional behavior'),
('gruff', (SELECT category_id FROM public.tag_categories WHERE name = 'Personality'), 'Rough, stern, or intimidating manner'),
('cheerful', (SELECT category_id FROM public.tag_categories WHERE name = 'Personality'), 'Optimistic, happy, and upbeat'),
('melancholy', (SELECT category_id FROM public.tag_categories WHERE name = 'Personality'), 'Sad, thoughtful, or prone to brooding'),
('arrogant', (SELECT category_id FROM public.tag_categories WHERE name = 'Personality'), 'Prideful, condescending, or self-important'),
('humble', (SELECT category_id FROM public.tag_categories WHERE name = 'Personality'), 'Modest, unassuming, and down-to-earth'),

-- FUNCTION TAGS (What purpose they serve)
('social-hub', (SELECT category_id FROM public.tag_categories WHERE name = 'Function'), 'Central meeting place for community interaction'),
('information-broker', (SELECT category_id FROM public.tag_categories WHERE name = 'Function'), 'Deals in knowledge and secrets'),
('problem-solver', (SELECT category_id FROM public.tag_categories WHERE name = 'Function'), 'Helps resolve conflicts or challenges'),
('gatekeeper', (SELECT category_id FROM public.tag_categories WHERE name = 'Function'), 'Controls access to people, places, or information'),
('comic-relief', (SELECT category_id FROM public.tag_categories WHERE name = 'Function'), 'Provides humor and lighthearted moments'),
('exposition', (SELECT category_id FROM public.tag_categories WHERE name = 'Function'), 'Delivers important background information'),
('plot-hook', (SELECT category_id FROM public.tag_categories WHERE name = 'Function'), 'Introduces new story elements or adventures'),
('red-herring', (SELECT category_id FROM public.tag_categories WHERE name = 'Function'), 'Misleads players or provides false clues'),
('deus-ex-machina', (SELECT category_id FROM public.tag_categories WHERE name = 'Function'), 'Can resolve impossible situations'),
('mentor', (SELECT category_id FROM public.tag_categories WHERE name = 'Function'), 'Provides guidance and wisdom to players'),

-- DISPOSITION TAGS (Current attitude)
('neutral', (SELECT category_id FROM public.tag_categories WHERE name = 'Disposition'), 'Neither particularly helpful nor hostile'),
('helpful', (SELECT category_id FROM public.tag_categories WHERE name = 'Disposition'), 'Willing to assist and cooperate'),
('obstructive', (SELECT category_id FROM public.tag_categories WHERE name = 'Disposition'), 'Creates difficulties or barriers'),
('indifferent', (SELECT category_id FROM public.tag_categories WHERE name = 'Disposition'), 'Uninterested in player affairs'),
('curious', (SELECT category_id FROM public.tag_categories WHERE name = 'Disposition'), 'Interested in player activities and news'),
('fearful', (SELECT category_id FROM public.tag_categories WHERE name = 'Disposition'), 'Afraid or anxious about something'),
('desperate', (SELECT category_id FROM public.tag_categories WHERE name = 'Disposition'), 'In urgent need of help or resolution'),
('confident', (SELECT category_id FROM public.tag_categories WHERE name = 'Disposition'), 'Self-assured and certain of their abilities'),
('nervous', (SELECT category_id FROM public.tag_categories WHERE name = 'Disposition'), 'Anxious, jumpy, or easily startled'),
('protective', (SELECT category_id FROM public.tag_categories WHERE name = 'Disposition'), 'Guards something or someone important'),

-- STATUS TAGS (Current situation)
('wealthy', (SELECT category_id FROM public.tag_categories WHERE name = 'Status'), 'Has significant financial resources'),
('poor', (SELECT category_id FROM public.tag_categories WHERE name = 'Status'), 'Lacks money or resources'),
('influential', (SELECT category_id FROM public.tag_categories WHERE name = 'Status'), 'Has significant social or political power'),
('connected', (SELECT category_id FROM public.tag_categories WHERE name = 'Status'), 'Well-networked with many relationships'),
('isolated', (SELECT category_id FROM public.tag_categories WHERE name = 'Status'), 'Cut off from social networks or support'),
('busy', (SELECT category_id FROM public.tag_categories WHERE name = 'Status'), 'Has many responsibilities or activities'),
('available', (SELECT category_id FROM public.tag_categories WHERE name = 'Status'), 'Has time and willingness to interact'),
('traveling', (SELECT category_id FROM public.tag_categories WHERE name = 'Status'), 'Frequently moves between locations'),
('settled', (SELECT category_id FROM public.tag_categories WHERE name = 'Status'), 'Firmly established in current location'),
('new-in-town', (SELECT category_id FROM public.tag_categories WHERE name = 'Status'), 'Recently arrived and unfamiliar with area'),

-- RELATIONSHIP TAGS (Connection to players/story)
('family-member', (SELECT category_id FROM public.tag_categories WHERE name = 'Relationship'), 'Related to player characters by blood or marriage'),
('old-friend', (SELECT category_id FROM public.tag_categories WHERE name = 'Relationship'), 'Has positive history with players'),
('former-enemy', (SELECT category_id FROM public.tag_categories WHERE name = 'Relationship'), 'Previously opposed players but situation has changed'),
('love-interest', (SELECT category_id FROM public.tag_categories WHERE name = 'Relationship'), 'Potential romantic connection'),
('colleague', (SELECT category_id FROM public.tag_categories WHERE name = 'Relationship'), 'Professional or working relationship'),
('student', (SELECT category_id FROM public.tag_categories WHERE name = 'Relationship'), 'Learning from players or their associates'),
('teacher', (SELECT category_id FROM public.tag_categories WHERE name = 'Relationship'), 'Instructs players or their associates'),
('debtor', (SELECT category_id FROM public.tag_categories WHERE name = 'Relationship'), 'Players owe them something'),
('creditor', (SELECT category_id FROM public.tag_categories WHERE name = 'Relationship'), 'Players owe them something'),
('witness', (SELECT category_id FROM public.tag_categories WHERE name = 'Relationship'), 'Has seen important events relevant to players'),

-- DANGER LEVEL TAGS
('harmless', (SELECT category_id FROM public.tag_categories WHERE name = 'Danger'), 'Poses no threat to players'),
('non-combatant', (SELECT category_id FROM public.tag_categories WHERE name = 'Danger'), 'Will not engage in violence'),
('dangerous', (SELECT category_id FROM public.tag_categories WHERE name = 'Danger'), 'Capable of harming players if provoked'),
('deadly', (SELECT category_id FROM public.tag_categories WHERE name = 'Danger'), 'Represents serious threat to player survival'),
('unknown-threat', (SELECT category_id FROM public.tag_categories WHERE name = 'Danger'), 'Danger level is uncertain or hidden'),

-- KNOWLEDGE TAGS (What they know)
('well-informed', (SELECT category_id FROM public.tag_categories WHERE name = 'Knowledge'), 'Knows much about local affairs and events'),
('scholarly', (SELECT category_id FROM public.tag_categories WHERE name = 'Knowledge'), 'Has academic or theoretical knowledge'),
('street-smart', (SELECT category_id FROM public.tag_categories WHERE name = 'Knowledge'), 'Understands practical, everyday survival'),
('specialized', (SELECT category_id FROM public.tag_categories WHERE name = 'Knowledge'), 'Expert in specific field or area'),
('naive', (SELECT category_id FROM public.tag_categories WHERE name = 'Knowledge'), 'Lacks worldly experience or understanding'),
('worldly', (SELECT category_id FROM public.tag_categories WHERE name = 'Knowledge'), 'Has broad experience from travel or life'),

-- RELIABILITY TAGS
('trustworthy', (SELECT category_id FROM public.tag_categories WHERE name = 'Reliability'), 'Can be counted on to keep promises'),
('unreliable', (SELECT category_id FROM public.tag_categories WHERE name = 'Reliability'), 'May not follow through on commitments'),
('honest', (SELECT category_id FROM public.tag_categories WHERE name = 'Reliability'), 'Tells the truth as they understand it'),
('deceptive', (SELECT category_id FROM public.tag_categories WHERE name = 'Reliability'), 'May lie or mislead others'),
('loyal', (SELECT category_id FROM public.tag_categories WHERE name = 'Reliability'), 'Faithful to friends and allies'),
('opportunistic', (SELECT category_id FROM public.tag_categories WHERE name = 'Reliability'), 'Changes allegiance based on advantage'),

-- SPECIAL TAGS
('magical', (SELECT category_id FROM public.tag_categories WHERE name = 'Special'), 'Has magical abilities or knowledge'),
('non-human', (SELECT category_id FROM public.tag_categories WHERE name = 'Special'), 'Belongs to fantasy race other than human'),
('undead', (SELECT category_id FROM public.tag_categories WHERE name = 'Special'), 'Deceased but animated being'),
('construct', (SELECT category_id FROM public.tag_categories WHERE name = 'Special'), 'Artificial or magically created being'),
('shapeshifter', (SELECT category_id FROM public.tag_categories WHERE name = 'Special'), 'Can change physical form'),
('cursed', (SELECT category_id FROM public.tag_categories WHERE name = 'Special'), 'Under the effect of magical curse'),
('blessed', (SELECT category_id FROM public.tag_categories WHERE name = 'Special'), 'Has divine favor or magical benefit'),
('immortal', (SELECT category_id FROM public.tag_categories WHERE name = 'Special'), 'Does not age or die naturally'),
('time-displaced', (SELECT category_id FROM public.tag_categories WHERE name = 'Special'), 'From different time period'),
('plane-touched', (SELECT category_id FROM public.tag_categories WHERE name = 'Special'), 'Has connection to other planes of existence');

-- Indexes for common queries
CREATE INDEX idx_tags_category ON public.tags (category_id);
CREATE INDEX idx_tags_name_search ON public.tags USING gin(to_tsvector('english', name));

-- Comments
COMMENT ON TABLE public.tags IS 'Standardized tags for categorizing and describing entities (NPCs, services, etc.)';
COMMENT ON COLUMN public.tags.category_id IS 'Foreign key to tag_categories table for grouping related tag types';