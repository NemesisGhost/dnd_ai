-- =====================================================
-- NPC Services Relationship Table
-- Requires: services.sql, occupations.sql, npcs.sql, cost_types.sql
-- Three-way many-to-many relationship: NPC + Occupation + Service
-- =====================================================

DROP TABLE IF EXISTS public.npc_services CASCADE;

CREATE TABLE public.npc_services (
    npc_service_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    npc_id UUID NOT NULL REFERENCES public.npcs(npc_id) ON DELETE CASCADE,
    occupation_id UUID NOT NULL REFERENCES public.occupations(occupation_id) ON DELETE CASCADE,
    service_id UUID NOT NULL REFERENCES public.services(service_id) ON DELETE CASCADE,
    
    -- NPC-Specific Service Provision
    proficiency_level INTEGER DEFAULT 5, -- 1-10 skill level this NPC has in providing this service
    is_actively_offered BOOLEAN DEFAULT TRUE, -- Whether they currently offer this service
    reputation_in_service INTEGER DEFAULT 5, -- 1-10 their reputation for this specific service
    years_experience INTEGER DEFAULT 1, -- How long they've been providing this service
    specialization TEXT, -- Specific area of expertise within this service
    
    -- NPC-Specific Service Details
    personal_cost_type_id UUID REFERENCES public.cost_types(cost_type_id), -- This NPC's specific cost type (overrides service default)
    personal_cost_details TEXT, -- This NPC's specific pricing details
    availability VARCHAR(100), -- This NPC's availability (Always, By appointment, etc.)
    quality_level INTEGER DEFAULT 5, -- 1-10 scale of this NPC's service quality
    reputation_requirement VARCHAR(100), -- Who this NPC is willing to serve
    personal_prerequisites TEXT, -- This NPC's specific requirements
    personal_time_required VARCHAR(100), -- How long this NPC takes to provide the service
    location_provided VARCHAR(200), -- Where this NPC provides this service
    personal_success_rate INTEGER, -- This NPC's success rate (1-100 percentage)
    personal_side_effects TEXT, -- This NPC's specific complications or quirks
    
    -- NPC-Specific Availability & Access
    is_secret_offering BOOLEAN DEFAULT false, -- Whether this NPC keeps this service secret
    referral_required BOOLEAN DEFAULT false, -- Must be referred by someone trusted
    max_concurrent_clients INTEGER DEFAULT 1, -- How many clients this NPC can serve simultaneously
    seasonal_restrictions TEXT, -- This NPC's time-based limitations
    personal_equipment TEXT, -- Special tools or materials this NPC uses
    
    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    notes TEXT, -- Additional context about this NPC's provision of this service
    
    -- Constraints
    UNIQUE(npc_id, occupation_id, service_id),
    CHECK(proficiency_level BETWEEN 1 AND 10),
    CHECK(reputation_in_service BETWEEN 1 AND 10),
    CHECK(job_satisfaction BETWEEN 1 AND 10),
    CHECK(years_experience >= 0),
    CHECK(personal_success_rate IS NULL OR (personal_success_rate BETWEEN 0 AND 100)),
    CHECK(max_concurrent_clients >= 1)
);

-- Indexes for performance
CREATE INDEX idx_npc_services_npc ON public.npc_services (npc_id);
CREATE INDEX idx_npc_services_occupation ON public.npc_services (occupation_id);
CREATE INDEX idx_npc_services_service ON public.npc_services (service_id);
CREATE INDEX idx_npc_services_cost_type ON public.npc_services (personal_cost_type_id);
CREATE INDEX idx_npc_services_proficiency ON public.npc_services (proficiency_level DESC);
CREATE INDEX idx_npc_services_active ON public.npc_services (is_actively_offered);
CREATE INDEX idx_npc_services_reputation ON public.npc_services (reputation_in_service DESC);
CREATE INDEX idx_npc_services_experience ON public.npc_services (years_experience DESC);
CREATE INDEX idx_npc_services_quality ON public.npc_services (quality_level DESC);
CREATE INDEX idx_npc_services_secret ON public.npc_services (is_secret_offering);
CREATE INDEX idx_npc_services_availability ON public.npc_services (availability);
CREATE INDEX idx_npc_services_referral_required ON public.npc_services (referral_required);
CREATE INDEX idx_npc_services_success_rate ON public.npc_services (personal_success_rate DESC);

-- Trigger for updated_at
CREATE TRIGGER npc_services_updated_at_trigger
    BEFORE UPDATE ON public.npc_services
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

-- Comments
COMMENT ON TABLE public.npc_services IS 'Three-way relationship table connecting NPCs to services they can provide through specific occupations';

-- Core relationship comments
COMMENT ON COLUMN public.npc_services.npc_id IS 'The NPC providing this service';
COMMENT ON COLUMN public.npc_services.occupation_id IS 'The occupation that qualifies them to provide this service';
COMMENT ON COLUMN public.npc_services.service_id IS 'The specific service being provided (references services table)';

-- NPC-specific capability comments
COMMENT ON COLUMN public.npc_services.proficiency_level IS 'This NPC''s skill level in providing this service (1=novice, 10=master)';
COMMENT ON COLUMN public.npc_services.reputation_in_service IS 'This NPC''s public reputation for this specific service (1=poor, 10=renowned)';
COMMENT ON COLUMN public.npc_services.specialization IS 'This NPC''s specific area of expertise within the service';
COMMENT ON COLUMN public.npc_services.years_experience IS 'How long this NPC has been providing this type of service';

-- NPC-specific service detail comments
COMMENT ON COLUMN public.npc_services.personal_cost_type_id IS 'This NPC''s specific cost type (overrides generic service cost type)';
COMMENT ON COLUMN public.npc_services.personal_cost_details IS 'This NPC''s specific pricing details (amounts, terms, etc.)';
COMMENT ON COLUMN public.npc_services.quality_level IS 'This NPC''s quality level for this specific service (1=poor, 10=masterwork)';
COMMENT ON COLUMN public.npc_services.personal_success_rate IS 'This NPC''s success rate for service completion (if applicable)';
COMMENT ON COLUMN public.npc_services.max_concurrent_clients IS 'Maximum number of clients this NPC can serve simultaneously for this service';