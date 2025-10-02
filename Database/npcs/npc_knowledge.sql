-- =====================================================
-- NPC Knowledge Areas Relationship Table
-- =====================================================

DROP TABLE IF EXISTS public.npc_knowledge CASCADE;

CREATE TABLE public.npc_knowledge (
    npc_knowledge_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    npc_id UUID NOT NULL REFERENCES public.npcs(npc_id) ON DELETE CASCADE,
    knowledge_area_id UUID NOT NULL REFERENCES public.knowledge_areas(knowledge_area_id) ON DELETE CASCADE,
    expertise_level INTEGER DEFAULT 5, -- 1-10 scale (1=basic, 10=world expert)
    notes TEXT, -- Specific details about their knowledge in this area
    source_of_knowledge VARCHAR(200), -- How they learned this (training, experience, etc.)
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(npc_id, knowledge_area_id)
);

-- Indexes for performance
CREATE INDEX idx_npc_knowledge_npc ON public.npc_knowledge (npc_id);
CREATE INDEX idx_npc_knowledge_area ON public.npc_knowledge (knowledge_area_id);
CREATE INDEX idx_npc_knowledge_expertise ON public.npc_knowledge (expertise_level DESC);
CREATE INDEX idx_npc_knowledge_composite ON public.npc_knowledge (npc_id, expertise_level DESC);

-- Comments
COMMENT ON TABLE public.npc_knowledge IS 'Many-to-many relationship between NPCs and their knowledge areas with expertise levels';
COMMENT ON COLUMN public.npc_knowledge.expertise_level IS 'Knowledge level: 1-3=basic, 4-6=competent, 7-8=expert, 9-10=master';
COMMENT ON COLUMN public.npc_knowledge.source_of_knowledge IS 'How they acquired this knowledge (apprenticeship, experience, formal education, etc.)';