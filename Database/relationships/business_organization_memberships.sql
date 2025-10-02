-- =====================================================
-- Business Organization Memberships Table
-- =====================================================

DROP TABLE IF EXISTS public.business_organization_memberships CASCADE;

CREATE TABLE public.business_organization_memberships (
    membership_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id UUID NOT NULL REFERENCES public.businesses(business_id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES public.organizations(organization_id) ON DELETE CASCADE,
    membership_type VARCHAR(100),
    membership_status VARCHAR(50) DEFAULT 'Active',
    membership_level VARCHAR(50),
    voting_rights BOOLEAN DEFAULT TRUE,
    membership_start_date DATE,
    membership_end_date DATE,
    last_dues_payment_date DATE,
    dues_amount TEXT,
    dues_frequency VARCHAR(50),
    dues_status VARCHAR(50) DEFAULT 'Current',
    additional_contributions TEXT,
    participation_level VARCHAR(50),
    leadership_positions TEXT,
    committee_memberships TEXT,
    benefits_received TEXT,
    membership_requirements_met BOOLEAN DEFAULT TRUE,
    special_obligations TEXT,
    attendance_requirements TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    notes TEXT,
    UNIQUE(business_id, organization_id),
    CHECK(membership_end_date IS NULL OR membership_end_date >= membership_start_date)
);

CREATE INDEX idx_business_memberships_business ON public.business_organization_memberships (business_id);
CREATE INDEX idx_business_memberships_organization ON public.business_organization_memberships (organization_id);
CREATE INDEX idx_business_memberships_type ON public.business_organization_memberships (membership_type);
CREATE INDEX idx_business_memberships_status ON public.business_organization_memberships (membership_status);
CREATE INDEX idx_business_memberships_level ON public.business_organization_memberships (membership_level);

CREATE TRIGGER business_memberships_updated_at_trigger
    BEFORE UPDATE ON public.business_organization_memberships
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

COMMENT ON TABLE public.business_organization_memberships IS 'Many-to-many relationship tracking business memberships in organizations';
COMMENT ON COLUMN public.business_organization_memberships.membership_level IS 'Level or tier of membership in the organization';
COMMENT ON COLUMN public.business_organization_memberships.dues_status IS 'Current status of membership dues payments';