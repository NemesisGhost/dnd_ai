-- =====================================================
-- Organization NPC Associations Table
-- Requires: organizations.sql, npcs.sql
-- =====================================================

DROP TABLE IF EXISTS public.organization_npc_associations CASCADE;

CREATE TABLE public.organization_npc_associations (
    -- Primary identification
    association_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Foreign keys
    organization_id UUID NOT NULL REFERENCES public.organizations(organization_id) ON DELETE CASCADE,
    npc_id UUID NOT NULL REFERENCES public.npcs(npc_id) ON DELETE CASCADE,
    
    -- Association details
    association_type VARCHAR(100), -- Contact, Ally, Enemy, Informant, Client, etc.
    relationship_strength VARCHAR(50) DEFAULT 'Neutral', -- Strong, Moderate, Weak, Hostile
    
    -- Context
    description TEXT, -- How they're connected
    how_they_met TEXT, -- Origin of the relationship
    
    -- Status
    association_status VARCHAR(50) DEFAULT 'Active', -- Active, Inactive, Ended
    player_knowledge_level VARCHAR(50) DEFAULT 'Unknown', -- Unknown, Suspected, Known
    
    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT unique_org_npc_association UNIQUE (organization_id, npc_id)
);

-- Indexes
CREATE INDEX idx_org_npc_assoc_organization ON public.organization_npc_associations (organization_id);
CREATE INDEX idx_org_npc_assoc_npc ON public.organization_npc_associations (npc_id);
CREATE INDEX idx_org_npc_assoc_type ON public.organization_npc_associations (association_type);
CREATE INDEX idx_org_npc_assoc_status ON public.organization_npc_associations (association_status);

-- Trigger for updated_at
CREATE TRIGGER organization_npc_associations_updated_at_trigger
    BEFORE UPDATE ON public.organization_npc_associations
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

-- Comments
COMMENT ON TABLE public.organization_npc_associations IS 'Many-to-many relationships between organizations/entities and NPCs';
COMMENT ON COLUMN public.organization_npc_associations.association_type IS 'Contact, Ally, Enemy, Informant, Client, etc.';
COMMENT ON COLUMN public.organization_npc_associations.relationship_strength IS 'Strong, Moderate, Weak, Hostile';
COMMENT ON COLUMN public.organization_npc_associations.player_knowledge_level IS 'Unknown, Suspected, Known';