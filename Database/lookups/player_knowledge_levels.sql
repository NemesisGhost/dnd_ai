-- =====================================================
-- Player Knowledge Levels Lookup Table
-- =====================================================

DROP TABLE IF EXISTS public.player_knowledge_levels CASCADE;

CREATE TABLE public.player_knowledge_levels (
    knowledge_level_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(50) NOT NULL UNIQUE,
    description TEXT,
    dm_guidance TEXT, -- How DMs should handle information at this level
    reveal_probability VARCHAR(50), -- Likelihood of information being shared
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Insert player knowledge levels
INSERT INTO public.player_knowledge_levels (name, description, dm_guidance, reveal_probability) VALUES
('Known', 'Players have full knowledge of this event and its details', 'Can freely reference and discuss, players can use this information', 'Already Known'),
('Suspected', 'Players have clues or hints but not complete information', 'Allow investigation and confirmation, reward careful questioning', 'High with Evidence'),
('Hinted', 'Players have received subtle indications something happened', 'Provide opportunities for discovery, use as plot hooks', 'Moderate with Trust'),
('Unknown', 'Players have no knowledge of this event', 'Protect as secret until appropriate reveal moment, build toward discovery', 'Low'),
('Rumored', 'Players may have heard conflicting stories or gossip', 'Mix truth with misinformation, allow for investigation to clarify', 'Moderate but Unclear'),
('Forbidden', 'Knowledge that would be dangerous or problematic if players learned it', 'Actively conceal, reveal only in dire circumstances or major plot moments', 'Very Low'),
('Discoverable', 'Information that players can learn through effort and investigation', 'Reward active investigation, provide multiple paths to discovery', 'High with Effort'),
('Context-Dependent', 'Revelation depends on specific circumstances or relationships', 'Tie to relationship building, specific situations, or trust levels', 'Variable');

-- Indexes for performance
CREATE INDEX idx_player_knowledge_levels_name ON public.player_knowledge_levels (name);
CREATE INDEX idx_player_knowledge_levels_probability ON public.player_knowledge_levels (reveal_probability);

-- Comments
COMMENT ON TABLE public.player_knowledge_levels IS 'Levels of player knowledge about NPC events, used for information management';