-- =====================================================
-- NPC Personality Traits Table
-- =====================================================

DROP TABLE IF EXISTS public.npc_personality_traits CASCADE;

CREATE TABLE public.npc_personality_traits (
    trait_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    npc_id UUID NOT NULL REFERENCES public.npcs(npc_id) ON DELETE CASCADE,
    trait_type VARCHAR(50) NOT NULL, -- personality, speech_pattern, mannerism, motivation, fear, secret
    trait_value TEXT NOT NULL,
    description TEXT,
    importance INTEGER DEFAULT 5, -- 1-10 scale for AI emphasis (higher = more important)
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX idx_npc_personality_traits_npc ON public.npc_personality_traits (npc_id);
CREATE INDEX idx_npc_personality_traits_type ON public.npc_personality_traits (trait_type);
CREATE INDEX idx_npc_personality_traits_importance ON public.npc_personality_traits (importance DESC);

-- Comments
COMMENT ON TABLE public.npc_personality_traits IS 'Individual personality traits, speech patterns, mannerisms, and other character aspects';
COMMENT ON COLUMN public.npc_personality_traits.trait_type IS 'Type of trait: personality, speech_pattern, mannerism, motivation, fear, secret, habit, quirk';
COMMENT ON COLUMN public.npc_personality_traits.importance IS 'Priority for AI roleplay (1=minor detail, 10=core defining trait)';