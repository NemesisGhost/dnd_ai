-- =====================================================
-- Organization Resources Relationship Table (Many-to-Many)
-- Requires: organizations.sql, resources_main.sql
-- =====================================================

DROP TABLE IF EXISTS public.organization_resources CASCADE;

CREATE TABLE public.organization_resources (
    relationship_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES public.organizations(organization_id) ON DELETE CASCADE,
    resource_id UUID NOT NULL REFERENCES public.resources(resource_id) ON DELETE CASCADE,
    
    -- Quantity and availability
    quantity_available VARCHAR(100), -- Abundant, Moderate, Limited, Scarce, or specific amounts
    accessibility VARCHAR(50), -- Immediate, Requires Planning, Restricted Access, Emergency Only
    renewal_rate VARCHAR(100), -- How quickly this resource replenishes
    
    -- Source and control
    controlling_authority VARCHAR(200), -- Who decides how it's used
    sharing_restrictions TEXT, -- Limitations on who can access it
    acquisition_method TEXT, -- How the organization obtained this resource
    
    -- Usage tracking
    primary_usage TEXT, -- How this organization uses this resource
    strategic_importance VARCHAR(50), -- Critical, Important, Useful, Minor
    
    -- Status and metadata
    resource_status VARCHAR(50) DEFAULT 'Available', -- Available, Depleted, Growing, Threatened, Lost
    last_assessed DATE DEFAULT CURRENT_DATE,
    secrecy_level VARCHAR(50) DEFAULT 'Known', -- Public, Known, Rumored, Secret, Top Secret
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    UNIQUE(organization_id, resource_id)
);

-- =====================================================
-- Indexes
-- =====================================================

CREATE INDEX idx_org_resources_organization ON public.organization_resources (organization_id);
CREATE INDEX idx_org_resources_resource ON public.organization_resources (resource_id);
CREATE INDEX idx_org_resources_status ON public.organization_resources (resource_status);
CREATE INDEX idx_org_resources_importance ON public.organization_resources (strategic_importance);
CREATE INDEX idx_org_resources_secrecy ON public.organization_resources (secrecy_level);

-- =====================================================
-- Triggers
-- =====================================================

CREATE TRIGGER organization_resources_updated_at_trigger
    BEFORE UPDATE ON public.organization_resources
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

-- =====================================================
-- Comments
-- =====================================================

COMMENT ON TABLE public.organization_resources IS 'Many-to-many relationship between organizations and their available resources';
COMMENT ON COLUMN public.organization_resources.secrecy_level IS 'Public, Known, Rumored, Secret, Top Secret';
COMMENT ON COLUMN public.organization_resources.quantity_available IS 'Abundant, Moderate, Limited, Scarce, or specific amounts';
COMMENT ON COLUMN public.organization_resources.strategic_importance IS 'Critical, Important, Useful, Minor';
COMMENT ON COLUMN public.organization_resources.resource_status IS 'Available, Depleted, Growing, Threatened, Lost';