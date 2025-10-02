-- =====================================================
-- NPC Occupations Relationship Table (Many-to-Many)
-- =====================================================

DROP TABLE IF EXISTS public.npc_occupations CASCADE;

CREATE TABLE public.npc_occupations (
    npc_occupation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    npc_id UUID NOT NULL REFERENCES public.npcs(npc_id) ON DELETE CASCADE,
    occupation_id UUID NOT NULL REFERENCES public.occupations(occupation_id) ON DELETE CASCADE,
    is_primary_occupation BOOLEAN DEFAULT FALSE, -- Whether this is their main job
    proficiency_level INTEGER DEFAULT 5, -- 1-10 skill level in this occupation
    years_experience INTEGER DEFAULT 1, -- How long they've worked in this occupation
    employment_status VARCHAR(50) DEFAULT 'Active', -- Active, Retired, Seasonal, Part-time
    employer_or_location TEXT, -- Who they work for or where they work
    income_level VARCHAR(50), -- Poor, Modest, Comfortable, Wealthy
    job_satisfaction INTEGER DEFAULT 5, -- 1-10 how much they enjoy this work
    reputation_in_field INTEGER DEFAULT 5, -- 1-10 their reputation in this occupation
    specialization TEXT, -- Specific area of expertise within the occupation
    started_date VARCHAR(100), -- When they began this occupation (can be approximate)
    notes TEXT, -- Additional context about their work in this occupation
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(npc_id, occupation_id)
);

-- =====================================================
-- Indexes for Performance
-- =====================================================

CREATE INDEX idx_npc_occupations_npc ON public.npc_occupations (npc_id);
CREATE INDEX idx_npc_occupations_occupation ON public.npc_occupations (occupation_id);
CREATE INDEX idx_npc_occupations_primary ON public.npc_occupations (is_primary_occupation);
CREATE INDEX idx_npc_occupations_proficiency ON public.npc_occupations (proficiency_level DESC);
CREATE INDEX idx_npc_occupations_employment_status ON public.npc_occupations (employment_status);

-- =====================================================
-- Triggers for Updated Timestamps
-- =====================================================

CREATE TRIGGER npc_occupations_updated_at_trigger
    BEFORE UPDATE ON public.npc_occupations
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

-- =====================================================
-- Comments
-- =====================================================

COMMENT ON TABLE public.npc_occupations IS 'Many-to-many relationship between NPCs and their occupations/jobs';
COMMENT ON COLUMN public.npc_occupations.is_primary_occupation IS 'Whether this is their main source of income and identity';
COMMENT ON COLUMN public.npc_occupations.proficiency_level IS '1-10 scale of skill level in this occupation';
COMMENT ON COLUMN public.npc_occupations.employment_status IS 'Active, Retired, Seasonal, Part-time status in this occupation';