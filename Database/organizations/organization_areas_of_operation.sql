-- =====================================================
-- Organization Areas of Operation Table (Normalized from organizations.areas_of_operation)
-- =====================================================

DROP TABLE IF EXISTS public.organization_areas_of_operation CASCADE;

CREATE TABLE public.organization_areas_of_operation (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES public.organizations(organization_id) ON DELETE CASCADE,
    location_id UUID NOT NULL REFERENCES public.locations(location_id) ON DELETE CASCADE,
    notes TEXT,
    UNIQUE(organization_id, location_id)
);

-- Indexes
CREATE INDEX idx_org_areas_org ON public.organization_areas_of_operation (organization_id);
CREATE INDEX idx_org_areas_location ON public.organization_areas_of_operation (location_id);

-- Comments
COMMENT ON TABLE public.organization_areas_of_operation IS 'Many-to-many relationship between organizations and locations for areas of operation.';
COMMENT ON COLUMN public.organization_areas_of_operation.notes IS 'Additional notes about the area of operation.';
