-- =====================================================
-- Organization Tags Relationship Table
-- Requires: organizations.sql, tags.sql
-- =====================================================

DROP TABLE IF EXISTS public.organization_tags CASCADE;

CREATE TABLE public.organization_tags (
    -- Primary identification
    organization_tag_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Foreign keys
    organization_id UUID NOT NULL REFERENCES public.organizations(organization_id) ON DELETE CASCADE,
    tag_id UUID NOT NULL REFERENCES public.tags(tag_id) ON DELETE CASCADE,
    
    -- Tag application details
    relevance_level VARCHAR(50) DEFAULT 'Standard', -- Primary, Standard, Minor, Historical
    visibility VARCHAR(50) DEFAULT 'Public', -- Public, Members Only, Leadership Only, DM Only
    
    -- Context and metadata
    assigned_date TIMESTAMP WITH TIME ZONE DEFAULT NOW(), -- When tag was applied
    assigned_by VARCHAR(100) DEFAULT 'system', -- Who assigned this tag (DM, system, player discovery, etc.)
      
    -- Tag strength and context
    intensity_level INTEGER DEFAULT 5, -- 1-10 how strongly this tag applies
    
    -- Campaign relevance
    story_importance VARCHAR(50) DEFAULT 'Background', -- Critical, Important, Standard, Background, Flavor
    plot_hooks TEXT, -- Story opportunities related to this tag
    adventure_relevance TEXT, -- How this might affect adventures

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT unique_org_tag UNIQUE (organization_id, tag_id),
    CONSTRAINT valid_intensity CHECK (intensity_level BETWEEN 1 AND 10)
);

-- Indexes
CREATE INDEX idx_org_tags_organization ON public.organization_tags (organization_id);
CREATE INDEX idx_org_tags_tag ON public.organization_tags (tag_id);
CREATE INDEX idx_org_tags_relevance ON public.organization_tags (relevance_level);
CREATE INDEX idx_org_tags_visibility ON public.organization_tags (visibility);
CREATE INDEX idx_org_tags_story_importance ON public.organization_tags (story_importance);
CREATE INDEX idx_org_tags_intensity ON public.organization_tags (intensity_level);

-- Trigger for updated_at
CREATE TRIGGER organization_tags_updated_at_trigger
    BEFORE UPDATE ON public.organization_tags
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

-- Comments
COMMENT ON TABLE public.organization_tags IS 'Many-to-many relationship between organizations and descriptive tags';
COMMENT ON COLUMN public.organization_tags.relevance_level IS 'Primary, Standard, Minor, Historical - how important this tag is';
COMMENT ON COLUMN public.organization_tags.visibility IS 'Who can see this tag application: Public, Members Only, Leadership Only, DM Only';
COMMENT ON COLUMN public.organization_tags.intensity_level IS 'How strongly this tag applies (1-10 scale)';
COMMENT ON COLUMN public.organization_tags.story_importance IS 'Critical, Important, Standard, Background, Flavor';

-- Views removed as per requirements

-- Sample organization tag assignments
-- Note: These would use actual UUIDs from the organizations and tags tables
-- INSERT INTO public.organization_tags (
--     organization_id, tag_id, relevance_level, intensity_level,
--     story_importance, plot_hooks
-- ) VALUES 
-- (
--     (SELECT organization_id FROM public.organizations WHERE name = 'Merchants Guild of the Golden Road'),
--     (SELECT tag_id FROM public.tags WHERE name = 'wealthy'),
--     'Primary', 8, 'Important',
--     'Guild controls major trade routes and has significant financial resources'
-- ),
-- (
--     (SELECT organization_id FROM public.organizations WHERE name = 'Order of the Silver Dawn'),
--     (SELECT tag_id FROM public.tags WHERE name = 'trustworthy'),
--     'Primary', 9, 'Standard',
--     'Reputation for honor and keeping oaths aligns with trustworthy nature'
-- ),
-- (
--     (SELECT organization_id FROM public.organizations WHERE name = 'The Whispered Word'),
--     (SELECT tag_id FROM public.tags WHERE name = 'mysterious'),
--     'Primary', 10, 'Critical',
--     'Secret society with hidden membership and unknown true goals'
-- );