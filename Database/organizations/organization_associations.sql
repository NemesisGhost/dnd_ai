-- =====================================================
-- Organization Associations Table
-- Requires: organizations.sql
-- =====================================================

DROP TABLE IF EXISTS public.organization_associations CASCADE;

CREATE TABLE public.organization_associations (
    -- Primary identification
    association_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Foreign keys
    organization_id UUID NOT NULL REFERENCES public.organizations(organization_id) ON DELETE CASCADE,
    related_organization_id UUID NOT NULL REFERENCES public.organizations(organization_id) ON DELETE CASCADE,
    
    -- Association details
    association_type VARCHAR(100), -- Interested Party, Rival, Supporter, Client, Contractor, etc.
    relationship_strength VARCHAR(50) DEFAULT 'Neutral', -- Strong, Moderate, Weak, Hostile
    
    -- Context
    description TEXT, -- How they're connected
    mutual_relationship BOOLEAN DEFAULT TRUE, -- Is this a two-way relationship?
    
    -- Status
    association_status VARCHAR(50) DEFAULT 'Active', -- Active, Inactive, Ended
    player_knowledge_level VARCHAR(50) DEFAULT 'Unknown', -- Unknown, Suspected, Known
    
    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT unique_org_association UNIQUE (organization_id, related_organization_id),
    CONSTRAINT no_self_association CHECK (organization_id != related_organization_id)
);

-- Indexes
CREATE INDEX idx_org_assoc_organization ON public.organization_associations (organization_id);
CREATE INDEX idx_org_assoc_related_org ON public.organization_associations (related_organization_id);
CREATE INDEX idx_org_assoc_type ON public.organization_associations (association_type);
CREATE INDEX idx_org_assoc_status ON public.organization_associations (association_status);

-- Trigger for updated_at
CREATE TRIGGER organization_associations_updated_at_trigger
    BEFORE UPDATE ON public.organization_associations
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

-- Comments
COMMENT ON TABLE public.organization_associations IS 'Many-to-many relationships between organizations/entities';
COMMENT ON COLUMN public.organization_associations.association_type IS 'Interested Party, Rival, Supporter, Client, Contractor, etc.';
COMMENT ON COLUMN public.organization_associations.relationship_strength IS 'Strong, Moderate, Weak, Hostile';
COMMENT ON COLUMN public.organization_associations.mutual_relationship IS 'Is this a two-way relationship?';
COMMENT ON COLUMN public.organization_associations.player_knowledge_level IS 'Unknown, Suspected, Known';