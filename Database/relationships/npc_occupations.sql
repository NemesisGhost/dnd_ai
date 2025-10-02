-- =====================================================
-- NPC Occupations Junction Table (Many-to-Many)
-- =====================================================

DROP TABLE IF EXISTS public.npc_occupations CASCADE;

CREATE TABLE public.npc_occupations (
    npc_occupation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    npc_id UUID NOT NULL REFERENCES public.npcs(npc_id) ON DELETE CASCADE,
    occupation_id UUID NOT NULL REFERENCES public.occupations(occupation_id) ON DELETE CASCADE,
    is_primary_occupation BOOLEAN DEFAULT FALSE,
    proficiency_level INTEGER DEFAULT 5,
    years_experience INTEGER DEFAULT 1,
    employment_status VARCHAR(50) DEFAULT 'Active',
    employer_or_location TEXT,
    income_level VARCHAR(50),
    job_satisfaction INTEGER DEFAULT 5,
    reputation_in_field INTEGER DEFAULT 5,
    specialization TEXT,
    started_date VARCHAR(100),
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(npc_id, occupation_id)
);

CREATE INDEX idx_npc_occupations_npc ON public.npc_occupations (npc_id);
CREATE INDEX idx_npc_occupations_occupation ON public.npc_occupations (occupation_id);
CREATE INDEX idx_npc_occupations_primary ON public.npc_occupations (is_primary_occupation);
CREATE INDEX idx_npc_occupations_proficiency ON public.npc_occupations (proficiency_level DESC);
CREATE INDEX idx_npc_occupations_employment_status ON public.npc_occupations (employment_status);
CREATE INDEX idx_npc_occupations_reputation ON public.npc_occupations (reputation_in_field DESC);
CREATE INDEX idx_npc_occupations_experience ON public.npc_occupations (years_experience DESC);

CREATE TRIGGER npc_occupations_updated_at_trigger
    BEFORE UPDATE ON public.npc_occupations
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

COMMENT ON TABLE public.npc_occupations IS 'Many-to-many relationship between NPCs and their occupations, allowing multiple jobs per NPC';
COMMENT ON COLUMN public.npc_occupations.is_primary_occupation IS 'Whether this is the NPCs main profession or a secondary job';
COMMENT ON COLUMN public.npc_occupations.proficiency_level IS 'Skill level in this occupation (1=novice, 10=master craftsman)';
COMMENT ON COLUMN public.npc_occupations.employment_status IS 'Current work status: Active, Retired, Seasonal, Part-time, etc.';
COMMENT ON COLUMN public.npc_occupations.job_satisfaction IS 'How much the NPC enjoys this work (1=hates it, 10=passionate)';
COMMENT ON COLUMN public.npc_occupations.reputation_in_field IS 'How well-regarded they are in this profession (1=poor reputation, 10=legendary)';