-- =====================================================
-- Organization Core Values Table
-- Requires: organizations.sql
-- =====================================================

DROP TABLE IF EXISTS public.organization_core_values CASCADE;

CREATE TABLE public.organization_core_values (
    -- Primary identification
    value_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Foreign key
    organization_id UUID NOT NULL REFERENCES public.organizations(organization_id) ON DELETE CASCADE,
    
    -- Value details
    value_name VARCHAR(200) NOT NULL,
    value_description TEXT,
    value_category VARCHAR(100), -- Moral, Ethical, Practical, Religious, Cultural, etc.
    
    
    -- Metadata
    secrecy_level VARCHAR(50) DEFAULT 'Public', -- Public, Internal, Leadership Only, Secret
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT unique_org_value UNIQUE (organization_id, value_name),
    CONSTRAINT valid_importance_rank CHECK (importance_rank IS NULL OR importance_rank > 0)
);

-- Indexes
CREATE INDEX idx_org_values_organization ON public.organization_core_values (organization_id);
CREATE INDEX idx_org_values_category ON public.organization_core_values (value_category);
CREATE INDEX idx_org_values_secrecy ON public.organization_core_values (secrecy_level);

-- Trigger for updated_at
CREATE TRIGGER organization_core_values_updated_at_trigger
    BEFORE UPDATE ON public.organization_core_values
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

-- Comments
COMMENT ON TABLE public.organization_core_values IS 'Fundamental beliefs and principles that guide organization behavior';
COMMENT ON COLUMN public.organization_core_values.value_category IS 'Moral, Ethical, Practical, Religious, Cultural, etc.';
COMMENT ON COLUMN public.organization_core_values.secrecy_level IS 'Public, Internal, Leadership Only, Secret';