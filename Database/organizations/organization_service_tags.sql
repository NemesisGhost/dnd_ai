-- =====================================================
-- Organization Service Tags Table (Normalized from organization_services.tags)
-- =====================================================

DROP TABLE IF EXISTS public.organization_service_tags CASCADE;

CREATE TABLE public.organization_service_tags (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_service_id UUID NOT NULL REFERENCES public.organization_services(organization_service_id) ON DELETE CASCADE,
    tag_id UUID NOT NULL REFERENCES public.tags(tag_id) ON DELETE CASCADE,
    notes TEXT,
    UNIQUE(organization_service_id, tag_id)
);

-- Indexes
CREATE INDEX idx_org_service_tags_service ON public.organization_service_tags (organization_service_id);
CREATE INDEX idx_org_service_tags_tag ON public.organization_service_tags (tag_id);

-- Comments
COMMENT ON TABLE public.organization_service_tags IS 'Many-to-many relationship between organization services and tags.';
COMMENT ON COLUMN public.organization_service_tags.notes IS 'Additional notes about the tag assignment.';
