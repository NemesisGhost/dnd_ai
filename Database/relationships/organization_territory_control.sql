-- =====================================================
-- Organization Territory Control
-- Relationships for organization areas of operation and territory control
-- =====================================================

DROP TABLE IF EXISTS public.organization_territory_control CASCADE;

CREATE TABLE public.organization_territory_control (
    control_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES public.organizations(organization_id) ON DELETE CASCADE,
    location_id UUID NOT NULL REFERENCES public.locations(location_id) ON DELETE CASCADE,
    control_type VARCHAR(100) NOT NULL, -- Controls, Influences, Operates In, Claims, Patrols, etc.
    control_strength VARCHAR(50), -- Full, Partial, Nominal, Contested, etc.
    control_method VARCHAR(100), -- Legal Authority, Military Force, Economic Control, Religious Influence, etc.
    established_date VARCHAR(100), -- When control was established
    recognition_status VARCHAR(50), -- Official, Unofficial, Disputed, Secret, etc.
    resistance_level VARCHAR(50), -- None, Minimal, Moderate, Strong, Rebellion, etc.
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(organization_id, location_id, control_type)
);

-- =====================================================
-- Indexes
-- =====================================================

CREATE INDEX idx_org_territory_org ON public.organization_territory_control (organization_id);
CREATE INDEX idx_org_territory_location ON public.organization_territory_control (location_id);
CREATE INDEX idx_org_territory_type ON public.organization_territory_control (control_type);

-- =====================================================
-- Triggers
-- =====================================================

CREATE TRIGGER organization_territory_control_updated_at_trigger
    BEFORE UPDATE ON public.organization_territory_control
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

-- =====================================================
-- Comments
-- =====================================================

COMMENT ON TABLE public.organization_territory_control IS 'Areas where organizations have control, influence, or operations';