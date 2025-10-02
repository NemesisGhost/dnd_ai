-- =====================================================
-- Organization Relationship Tags Table (Normalized from organization_relationships.tags)
-- =====================================================

DROP TABLE IF EXISTS public.organization_relationship_tags CASCADE;

CREATE TABLE public.organization_relationship_tags (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    relationship_id UUID NOT NULL REFERENCES public.organization_relationships(relationship_id) ON DELETE CASCADE,
    tag_id UUID NOT NULL REFERENCES public.tags(tag_id) ON DELETE CASCADE,
    notes TEXT,
    UNIQUE(relationship_id, tag_id)
);

-- Indexes
CREATE INDEX idx_org_rel_tags_rel ON public.organization_relationship_tags (relationship_id);
CREATE INDEX idx_org_rel_tags_tag ON public.organization_relationship_tags (tag_id);

-- Comments
COMMENT ON TABLE public.organization_relationship_tags IS 'Many-to-many relationship between organization relationships and tags.';
COMMENT ON COLUMN public.organization_relationship_tags.notes IS 'Additional notes about the tag assignment.';
