-- =====================================================
-- NPC Organization Memberships Relationship Table
-- =====================================================

DROP TABLE IF EXISTS public.npc_organization_memberships CASCADE;

CREATE TABLE public.npc_organization_memberships (
    membership_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    npc_id UUID NOT NULL REFERENCES public.npcs(npc_id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES public.organizations(organization_id) ON DELETE CASCADE,
    role VARCHAR(200), -- Their role within the organization
    status VARCHAR(100), -- Active, Inactive, Former, Secret, Suspended, etc.
    rank_or_position VARCHAR(200), -- Specific title or rank within organization
    joined_date VARCHAR(100), -- Can be approximate like "5 years ago" or "Recently"
    left_date VARCHAR(100), -- When they left (if applicable)
    membership_type VARCHAR(100), -- Full Member, Associate, Honorary, Probationary, etc.
    influence_level INTEGER, -- 1-10 scale of their influence within the organization
    notes TEXT, -- Additional details about their membership
    is_public BOOLEAN DEFAULT true, -- Whether this membership is publicly known
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(npc_id, organization_id)
);

-- Indexes for performance
CREATE INDEX idx_npc_memberships_npc ON public.npc_organization_memberships (npc_id);
CREATE INDEX idx_npc_memberships_org ON public.npc_organization_memberships (organization_id);
CREATE INDEX idx_npc_memberships_status ON public.npc_organization_memberships (status);
CREATE INDEX idx_npc_memberships_public ON public.npc_organization_memberships (is_public);
CREATE INDEX idx_npc_memberships_influence ON public.npc_organization_memberships (influence_level DESC);

-- Trigger for updated_at
CREATE TRIGGER npc_memberships_updated_at_trigger
    BEFORE UPDATE ON public.npc_organization_memberships
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

-- Comments
COMMENT ON TABLE public.npc_organization_memberships IS 'Detailed relationships between NPCs and organizations they belong to';
COMMENT ON COLUMN public.npc_organization_memberships.influence_level IS 'How much sway they have within the organization (1=none, 10=controls it)';
COMMENT ON COLUMN public.npc_organization_memberships.is_public IS 'Whether this membership is known to the general public';