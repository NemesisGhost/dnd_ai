-- =====================================================
-- Organization Activities Table
-- Requires: organizations.sql
-- =====================================================

DROP TABLE IF EXISTS public.organization_activities CASCADE;

CREATE TABLE public.organization_activities (
    -- Primary identification
    activity_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Foreign key
    organization_id UUID NOT NULL REFERENCES public.organizations(organization_id) ON DELETE CASCADE,
    
    -- Activity details
    activity_name VARCHAR(200) NOT NULL,
    activity_description TEXT,
    activity_type VARCHAR(100), -- Regular, Seasonal, Special Event, Emergency Response, etc.
    
    -- Frequency and timing
    frequency VARCHAR(100), -- Daily, Weekly, Monthly, Annually, As Needed, etc.
    typical_duration VARCHAR(100), -- How long the activity usually takes
    seasonal_timing TEXT, -- When during the year this happens
    
    -- Participation
    participants_required INTEGER, -- Minimum people needed
    skill_requirements TEXT, -- What abilities are needed
    
    -- Operations
    resources_consumed TEXT, -- What the activity costs or uses
    expected_outcomes TEXT, -- What the activity is meant to achieve
    success_metrics TEXT, -- How success is measured
    
    -- Location and logistics
    equipment_needed TEXT, -- Tools or materials required
    preparation_required TEXT, -- What setup is needed
    
    -- Status and tracking
    activity_status VARCHAR(50) DEFAULT 'Active', -- Active, Suspended, Seasonal, Discontinued
    last_performed DATE, -- When this was last done
    next_scheduled DATE, -- When it's planned next
    
    -- Adventure relevance
    player_interaction_potential TEXT, -- How players might get involved
    plot_hooks TEXT, -- Story opportunities
    complications_possible TEXT, -- What could go wrong
    
    -- Metadata
    priority_level VARCHAR(50) DEFAULT 'Standard', -- Critical, High, Standard, Low
    secrecy_level VARCHAR(50) DEFAULT 'Open', -- Open, Members Only, Leadership Only, Secret
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT unique_org_activity UNIQUE (organization_id, activity_name)
);

-- Indexes
CREATE INDEX idx_org_activities_organization ON public.organization_activities (organization_id);
CREATE INDEX idx_org_activities_type ON public.organization_activities (activity_type);
CREATE INDEX idx_org_activities_status ON public.organization_activities (activity_status);
CREATE INDEX idx_org_activities_priority ON public.organization_activities (priority_level);
CREATE INDEX idx_org_activities_secrecy ON public.organization_activities (secrecy_level);
CREATE INDEX idx_org_activities_next_scheduled ON public.organization_activities (next_scheduled);

-- Trigger for updated_at
CREATE TRIGGER organization_activities_updated_at_trigger
    BEFORE UPDATE ON public.organization_activities
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

-- Comments
COMMENT ON TABLE public.organization_activities IS 'Activities and operations that organizations regularly perform';
COMMENT ON COLUMN public.organization_activities.activity_type IS 'Regular, Seasonal, Special Event, Emergency Response, etc.';
COMMENT ON COLUMN public.organization_activities.priority_level IS 'Critical, High, Standard, Low';
COMMENT ON COLUMN public.organization_activities.secrecy_level IS 'Open, Members Only, Leadership Only, Secret';