-- =====================================================
-- Business Employees Relationship Table
-- Requires: businesses.sql, ../npcs/npcs.sql, ../occupations.sql, ../lookups/employee_roles.sql, ../lookups/cost_types.sql
-- =====================================================

DROP TABLE IF EXISTS public.business_employees CASCADE;

CREATE TABLE public.business_employees (
    business_employee_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id UUID NOT NULL REFERENCES public.businesses(business_id) ON DELETE CASCADE,
    npc_id UUID NOT NULL REFERENCES public.npcs(npc_id) ON DELETE CASCADE,
    role_id UUID NOT NULL REFERENCES public.employee_roles(role_id) ON DELETE CASCADE,
    
    -- Employment details
    employment_status VARCHAR(50) DEFAULT 'Active', -- Active, Retired, Seasonal, Part-time, Temporary
    hire_date DATE,
    termination_date DATE,
    is_family_member BOOLEAN DEFAULT FALSE, -- Is this person family of the owner?
    
    -- Work arrangement
    work_schedule VARCHAR(100), -- Full-time, Part-time, Seasonal, Nights, etc.
    compensation_type_id UUID REFERENCES public.cost_types(cost_type_id), -- Type of compensation structure
    compensation_details TEXT, -- Specific compensation details (amounts, terms, etc.)
    benefits TEXT, -- What benefits they receive
    
    -- Performance and relationships
    job_satisfaction INTEGER DEFAULT 5, -- 1-10 how much they enjoy this job
    performance_level INTEGER DEFAULT 5, -- 1-10 how well they perform
    loyalty_level INTEGER DEFAULT 5, -- 1-10 how loyal they are to the business
    years_experience INTEGER DEFAULT 0, -- Years of experience in this type of work
    
    -- Business context (moved from npc_services)
    income_level VARCHAR(50), -- Poor, Modest, Comfortable, Wealthy
    primary_income_source BOOLEAN DEFAULT FALSE, -- Is this their main job?
    employer_relationship TEXT, -- How they get along with management
    
    -- Authority and responsibilities
    has_hiring_authority BOOLEAN DEFAULT FALSE, -- Can they hire others?
    has_financial_authority BOOLEAN DEFAULT FALSE, -- Can they handle money/make purchases?
    key_responsibilities TEXT, -- What they're specifically responsible for
    areas_of_expertise TEXT, -- What they're particularly good at
    
    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    notes TEXT, -- Additional context about this employment relationship
    
    -- Constraints
    UNIQUE(business_id, npc_id, role_id),
    CHECK(job_satisfaction BETWEEN 1 AND 10),
    CHECK(performance_level BETWEEN 1 AND 10),
    CHECK(loyalty_level BETWEEN 1 AND 10),
    CHECK(years_experience >= 0),
    CHECK(termination_date IS NULL OR termination_date >= hire_date)
);

-- Indexes for performance
CREATE INDEX idx_business_employees_business ON public.business_employees (business_id);
CREATE INDEX idx_business_employees_npc ON public.business_employees (npc_id);
CREATE INDEX idx_business_employees_role ON public.business_employees (role_id);
CREATE INDEX idx_business_employees_compensation_type ON public.business_employees (compensation_type_id);
CREATE INDEX idx_business_employees_status ON public.business_employees (employment_status);
CREATE INDEX idx_business_employees_family ON public.business_employees (is_family_member);
CREATE INDEX idx_business_employees_primary_income ON public.business_employees (primary_income_source);
CREATE INDEX idx_business_employees_satisfaction ON public.business_employees (job_satisfaction DESC);
CREATE INDEX idx_business_employees_performance ON public.business_employees (performance_level DESC);
CREATE INDEX idx_business_employees_loyalty ON public.business_employees (loyalty_level DESC);

-- Trigger for updated_at
CREATE TRIGGER business_employees_updated_at_trigger
    BEFORE UPDATE ON public.business_employees
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

-- Comments
COMMENT ON TABLE public.business_employees IS 'This table handles all business roles including owners and managers.';
COMMENT ON COLUMN public.business_employees.employment_status IS 'Current work status: Active, Retired, Seasonal, Part-time, Temporary';
COMMENT ON COLUMN public.business_employees.compensation_type_id IS 'Type of compensation structure (salary, hourly, commission, etc.)';
COMMENT ON COLUMN public.business_employees.compensation_details IS 'Specific compensation amounts, terms, and conditions';
COMMENT ON COLUMN public.business_employees.job_satisfaction IS 'How much this NPC enjoys working at this business (1=hates it, 10=loves it)';
COMMENT ON COLUMN public.business_employees.performance_level IS 'How well this NPC performs their job (1=poor, 10=excellent)';
COMMENT ON COLUMN public.business_employees.loyalty_level IS 'How loyal this NPC is to the business (1=disloyal, 10=extremely loyal)';
COMMENT ON COLUMN public.business_employees.income_level IS 'Economic level this job provides: Poor, Modest, Comfortable, Wealthy';
COMMENT ON COLUMN public.business_employees.primary_income_source IS 'Whether this job is the NPC''s main source of income';