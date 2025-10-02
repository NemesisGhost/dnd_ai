-- =====================================================
-- Organization Relationships Table
-- =====================================================

DROP TABLE IF EXISTS public.organization_relationships CASCADE;

CREATE TABLE public.organization_relationships (
    -- Primary identification
    relationship_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Organizations involved
    organization_id UUID NOT NULL REFERENCES public.organizations(organization_id) ON DELETE CASCADE,
    related_organization_id UUID NOT NULL REFERENCES public.organizations(organization_id) ON DELETE CASCADE,
    
    -- Relationship details
    relationship_type VARCHAR(50) NOT NULL, -- Allied, Rival, Neutral, Subsidiary, Parent, Trade Partner, etc.
    relationship_status VARCHAR(50) DEFAULT 'Active', -- Active, Dormant, Ended, Hostile, etc.
    strength_level VARCHAR(50), -- Weak, Moderate, Strong, Unbreakable
    
    -- Relationship specifics
    description TEXT, -- Details about the relationship
    formal_agreement BOOLEAN DEFAULT FALSE, -- Is there a formal treaty/contract?
    public_knowledge BOOLEAN DEFAULT TRUE, -- Is this relationship public knowledge?
    
    -- History and context
    established_date VARCHAR(100), -- When relationship began
    established_reason TEXT, -- Why the relationship formed
    key_events TEXT, -- Important moments in the relationship
    
    -- Current state
    current_projects TEXT, -- Joint activities or conflicts
    recent_interactions TEXT, -- Latest exchanges between organizations
    future_plans TEXT, -- Planned cooperation or conflict
    
    -- Game mechanics
    relationship_benefits TEXT, -- What each side gains
    relationship_obligations TEXT, -- What each side owes
    conflict_triggers TEXT, -- What could damage the relationship
    
    -- Metadata
    dm_notes TEXT, -- Private DM information
    player_knowledge_level VARCHAR(50) DEFAULT 'Unknown', -- What players know: Unknown, Rumored, Known, Detailed
    campaign_relevance TEXT, -- How this affects current story
    -- tags are now normalized into organization_relationship_tags table
    
    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT no_self_relationship CHECK (organization_id != related_organization_id),
    CONSTRAINT unique_relationship UNIQUE (organization_id, related_organization_id)
);

-- Indexes
CREATE INDEX idx_org_relationships_org_id ON public.organization_relationships (organization_id);
CREATE INDEX idx_org_relationships_related_org_id ON public.organization_relationships (related_organization_id);
CREATE INDEX idx_org_relationships_type ON public.organization_relationships (relationship_type);
CREATE INDEX idx_org_relationships_status ON public.organization_relationships (relationship_status);
CREATE INDEX idx_org_relationships_strength ON public.organization_relationships (strength_level);
-- CREATE INDEX idx_org_relationships_tags ON public.organization_relationships USING gin(tags);

-- Trigger for updated_at
CREATE TRIGGER organization_relationships_updated_at_trigger
    BEFORE UPDATE ON public.organization_relationships
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

-- Comments
COMMENT ON TABLE public.organization_relationships IS 'Relationships between organizations (alliances, rivalries, trade partnerships, etc.)';
COMMENT ON COLUMN public.organization_relationships.relationship_type IS 'Allied, Rival, Neutral, Subsidiary, Parent, Trade Partner, etc.';
COMMENT ON COLUMN public.organization_relationships.strength_level IS 'Weak, Moderate, Strong, Unbreakable';
COMMENT ON COLUMN public.organization_relationships.player_knowledge_level IS 'What players know: Unknown, Rumored, Known, Detailed';

-- Sample relationships
INSERT INTO public.organization_relationships (
    organization_id, related_organization_id, relationship_type, 
    relationship_status, strength_level, description, public_knowledge
) VALUES 
-- Note: These would use actual UUIDs from the organizations table
-- (
--     'org1-uuid', 'org2-uuid', 'Allied', 'Active', 'Strong',
--     'Long-standing trade agreement with mutual defense pact', TRUE
-- ),
-- (
--     'org1-uuid', 'org3-uuid', 'Rival', 'Active', 'Moderate', 
--     'Competing for control of lucrative trade routes', TRUE
-- ),
-- (
--     'org2-uuid', 'org3-uuid', 'Neutral', 'Active', 'Weak',
--     'Occasional information exchange, no formal agreements', FALSE
-- );

-- Views removed as per requirements