-- =====================================================
-- NPC Disposition Lookup Table
-- =====================================================

DROP TABLE IF EXISTS public.npc_dispositions CASCADE;

CREATE TABLE public.npc_dispositions (
    disposition_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(50) NOT NULL UNIQUE,
    description TEXT,
    attitude_score INTEGER, -- -10 to +10 scale (negative=hostile, positive=friendly)
    color_code VARCHAR(7), -- Hex color for UI display
    sort_order INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

INSERT INTO public.npc_dispositions (name, description, attitude_score, color_code, sort_order) VALUES
-- Hostile Range (-10 to -6)
('Hostile', 'Actively aggressive and antagonistic', -10, '#FF0000', 1),
('Aggressive', 'Quick to anger and confrontation', -8, '#CC0000', 2),
('Angry', 'Currently upset or enraged', -7, '#990000', 3),
('Threatening', 'Makes intimidating gestures or statements', -6, '#660000', 4),

-- Unfriendly Range (-5 to -1)
('Unfriendly', 'Cold and unwelcoming', -5, '#FF6600', 5),
('Suspicious', 'Distrustful and wary', -4, '#CC4400', 6),
('Dismissive', 'Considers others beneath their notice', -3, '#996600', 7),
('Irritated', 'Mildly annoyed or bothered', -2, '#663300', 8),
('Aloof', 'Distant and detached', -1, '#333300', 9),

-- Neutral Range (0)
('Neutral', 'Neither particularly friendly nor hostile', 0, '#808080', 10),
('Indifferent', 'Shows little interest or concern', 0, '#666666', 11),
('Professional', 'Maintains formal, business-like demeanor', 0, '#404040', 12),

-- Friendly Range (1 to 5)
('Polite', 'Courteous and respectful', 1, '#006600', 13),
('Cordial', 'Warm and pleasant in interactions', 2, '#009900', 14),
('Friendly', 'Genuinely warm and welcoming', 3, '#00CC00', 15),
('Helpful', 'Eager to assist and support', 4, '#00FF00', 16),
('Warm', 'Emotionally open and caring', 5, '#66FF66', 17),

-- Very Friendly Range (6 to 10)
('Enthusiastic', 'Excited and energetic in interactions', 6, '#00FFCC', 18),
('Devoted', 'Deeply loyal and committed', 7, '#00CCFF', 19),
('Loving', 'Shows genuine affection and care', 8, '#0099FF', 20),
('Protective', 'Fiercely guards those they care about', 9, '#0066FF', 21),
('Fanatical', 'Extreme devotion or obsession', 10, '#0033FF', 22),

-- Special/Situational Dispositions
('Fearful', 'Afraid and seeking to avoid conflict', -3, '#FFFF00', 30),
('Nervous', 'Anxious and easily startled', -1, '#FFCC00', 31),
('Curious', 'Interested and inquisitive', 2, '#FF00FF', 32),
('Playful', 'Mischievous and fun-loving', 3, '#FF66FF', 33),
('Respectful', 'Shows deference and honor', 4, '#CCFFFF', 34),
('Grateful', 'Appreciative of past help or kindness', 5, '#99FFCC', 35),

-- Complex Emotional States
('Conflicted', 'Torn between different feelings or loyalties', 0, '#996699', 40),
('Melancholy', 'Sad and contemplative', -1, '#663399', 41),
('Proud', 'Takes satisfaction in achievements or status', 1, '#CC99FF', 42),
('Guilty', 'Feels remorse for past actions', -2, '#9966CC', 43),
('Hopeful', 'Optimistic about future possibilities', 3, '#CCCCFF', 44),
('Desperate', 'Willing to take extreme measures', -4, '#FF9999', 45),

-- Relationship-Based Dispositions
('Romantic', 'Shows romantic interest or affection', 6, '#FF99CC', 50),
('Jealous', 'Envious of others relationships or success', -5, '#CC6699', 51),
('Competitive', 'Sees interactions as contests to win', 1, '#FFCC99', 52),
('Mentoring', 'Takes teaching or guiding role', 4, '#99CCFF', 53),
('Parental', 'Shows protective, nurturing care', 7, '#CCFFCC', 54);

-- Indexes for common queries
CREATE INDEX idx_npc_dispositions_attitude ON public.npc_dispositions (attitude_score);
CREATE INDEX idx_npc_dispositions_sort ON public.npc_dispositions (sort_order);

-- Comments
COMMENT ON TABLE public.npc_dispositions IS 'Standardized disposition/attitude values for NPCs toward players and others';
COMMENT ON COLUMN public.npc_dispositions.attitude_score IS 'Numeric scale from -10 (most hostile) to +10 (most friendly)';
COMMENT ON COLUMN public.npc_dispositions.color_code IS 'Hex color code for UI representation of disposition';