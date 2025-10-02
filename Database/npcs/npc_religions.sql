-- =====================================================
-- NPC Religions Many-to-Many Relationship Table
-- =====================================================

DROP TABLE IF EXISTS public.npc_religions CASCADE;

CREATE TABLE public.npc_religions (
    npc_religion_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    npc_id UUID NOT NULL REFERENCES public.npcs(npc_id) ON DELETE CASCADE,
    religion_id UUID NOT NULL REFERENCES public.religions(religion_id) ON DELETE CASCADE,
    
    -- Religious devotion details
    devotion_level VARCHAR(50) DEFAULT 'Moderate', -- Atheist, Skeptical, Casual, Moderate, Devout, Fanatical
    religious_role VARCHAR(100), -- Layperson, Acolyte, Priest, High Priest, Prophet, etc.
    ordination_date DATE, -- When they joined clergy (if applicable)
    religious_rank VARCHAR(100), -- Specific title or position
    
    -- Practice details
    worship_frequency VARCHAR(50), -- Never, Rarely, Occasionally, Regularly, Daily, Constantly
    religious_knowledge VARCHAR(50), -- Basic, Moderate, Extensive, Scholarly, Authoritative
    public_display BOOLEAN DEFAULT TRUE, -- Whether they openly display their faith
    missionary_activity BOOLEAN DEFAULT FALSE, -- Whether they actively spread their faith
    
    -- Personal relationship with faith
    conversion_story TEXT, -- How they came to this faith
    personal_interpretation TEXT, -- Their unique take on the religion
    religious_conflicts TEXT, -- Struggles with faith or doctrine
    sacred_vows TEXT, -- Any special religious commitments
    
    -- Social aspects
    religious_community_role VARCHAR(100), -- Role in local religious community
    religious_influence VARCHAR(50) DEFAULT 'None', -- None, Local, Regional, National, International
    patron_relationships TEXT, -- Relationship with religious patrons or sponsors
    
    -- Current status
    current_status VARCHAR(50) DEFAULT 'Active', -- Active, Lapsed, Questioning, Excommunicated, Reformed
    status_change_date DATE, -- When status last changed
    
    -- Metadata
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Ensure unique npc-religion pairs
    UNIQUE(npc_id, religion_id)
);

-- Indexes for efficient queries
CREATE INDEX idx_npc_religions_npc ON public.npc_religions (npc_id);
CREATE INDEX idx_npc_religions_religion ON public.npc_religions (religion_id);
CREATE INDEX idx_npc_religions_devotion ON public.npc_religions (devotion_level);
CREATE INDEX idx_npc_religions_role ON public.npc_religions (religious_role);
CREATE INDEX idx_npc_religions_rank ON public.npc_religions (religious_rank);
CREATE INDEX idx_npc_religions_influence ON public.npc_religions (religious_influence);
CREATE INDEX idx_npc_religions_status ON public.npc_religions (current_status);

-- Trigger for updated_at
CREATE TRIGGER npc_religions_updated_at_trigger
    BEFORE UPDATE ON public.npc_religions
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

-- Comments
COMMENT ON TABLE public.npc_religions IS 'Religious affiliations and devotion of NPCs';
COMMENT ON COLUMN public.npc_religions.devotion_level IS 'How devoted the NPC is to this religion';
COMMENT ON COLUMN public.npc_religions.religious_role IS 'Official position in the religious hierarchy';
COMMENT ON COLUMN public.npc_religions.religious_influence IS 'Geographic scope of their religious influence';