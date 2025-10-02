-- =====================================================
-- Settlement Organizations Many-to-Many Relationship Table
-- =====================================================

DROP TABLE IF EXISTS public.settlement_organizations CASCADE;

CREATE TABLE public.settlement_organizations (
    settlement_organization_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    settlement_id UUID NOT NULL REFERENCES public.settlements(settlement_id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES public.organizations(organization_id) ON DELETE CASCADE,
    
    -- Relationship details
    presence_level_id UUID REFERENCES public.presence_levels(presence_level_id),
    influence_type_id UUID REFERENCES public.influence_types(influence_type_id),
    relationship_status_id UUID REFERENCES public.relationship_statuses(relationship_status_id),
    establishment_date DATE, -- When they established presence here
    notes TEXT, -- Additional details about their presence
    
    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Ensure unique settlement-organization pairs
    UNIQUE(settlement_id, organization_id)
);

-- Indexes for efficient queries
CREATE INDEX idx_settlement_organizations_settlement ON public.settlement_organizations (settlement_id);
CREATE INDEX idx_settlement_organizations_organization ON public.settlement_organizations (organization_id);
CREATE INDEX idx_settlement_organizations_presence ON public.settlement_organizations (presence_level_id);
CREATE INDEX idx_settlement_organizations_influence ON public.settlement_organizations (influence_type_id);
CREATE INDEX idx_settlement_organizations_relationship ON public.settlement_organizations (relationship_status_id);

-- Trigger for updated_at
CREATE TRIGGER settlement_organizations_updated_at_trigger
    BEFORE UPDATE ON public.settlement_organizations
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

-- Comments
COMMENT ON TABLE public.settlement_organizations IS 'Many-to-many relationship between settlements and organizations (guilds, factions, etc.)';
COMMENT ON COLUMN public.settlement_organizations.presence_level_id IS 'Foreign key to presence_levels lookup table';
COMMENT ON COLUMN public.settlement_organizations.influence_type_id IS 'Foreign key to influence_types lookup table';
COMMENT ON COLUMN public.settlement_organizations.relationship_status_id IS 'Foreign key to relationship_statuses lookup table';

-- Sample data (assuming Millbrook settlement and some organizations exist)
-- Note: These INSERTs will only work if the referenced settlements and organizations exist
/*
INSERT INTO public.settlement_organizations (settlement_id, organization_id, presence_level_id, influence_type_id, relationship_status_id, notes) VALUES
((SELECT settlement_id FROM public.settlements WHERE name = 'Millbrook'), 
 (SELECT organization_id FROM public.organizations WHERE name = 'Millers Guild'), 
 (SELECT presence_level_id FROM public.presence_levels WHERE name = 'Strong'),
 (SELECT influence_type_id FROM public.influence_types WHERE name = 'Economic'),
 (SELECT relationship_status_id FROM public.relationship_statuses WHERE name = 'Allied'),
 'Controls most grain milling operations in town'),
((SELECT settlement_id FROM public.settlements WHERE name = 'Millbrook'), 
 (SELECT organization_id FROM public.organizations WHERE name = 'River Traders Association'), 
 (SELECT presence_level_id FROM public.presence_levels WHERE name = 'Moderate'),
 (SELECT influence_type_id FROM public.influence_types WHERE name = 'Economic'),
 (SELECT relationship_status_id FROM public.relationship_statuses WHERE name = 'Friendly'),
 'Regular traders who use the river routes'),
((SELECT settlement_id FROM public.settlements WHERE name = 'Millbrook'), 
 (SELECT organization_id FROM public.organizations WHERE name = 'Order of the Stone Bridge'), 
 (SELECT presence_level_id FROM public.presence_levels WHERE name = 'Weak'),
 (SELECT influence_type_id FROM public.influence_types WHERE name = 'Religious'),
 (SELECT relationship_status_id FROM public.relationship_statuses WHERE name = 'Neutral'),
 'Small shrine maintained by traveling clerics');
*/