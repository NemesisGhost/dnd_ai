-- =====================================================
-- Organization Chapters
-- Detailed chapter/branch tracking (replaces JSONB chapter_locations)
-- =====================================================

DROP TABLE IF EXISTS public.organization_chapters CASCADE;

CREATE TABLE public.organization_chapters (
    chapter_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES public.organizations(organization_id) ON DELETE CASCADE,
    location_id UUID NOT NULL REFERENCES public.locations(location_id) ON DELETE CASCADE,
    chapter_name VARCHAR(200), -- Local name of the chapter
    chapter_type VARCHAR(100), -- Chapter, Branch, Outpost, Cell, Lodge, etc.
    chapter_status VARCHAR(50), -- Active, Dormant, Disbanded, Secret, etc.
    chapter_size VARCHAR(50), -- Tiny, Small, Medium, Large, Massive
    establishment_date VARCHAR(100), -- When this chapter was founded
    member_count_estimate INTEGER, -- Approximate membership
    leadership_structure TEXT, -- How this chapter is organized
    local_leader_name VARCHAR(200), -- Who leads this chapter
    local_leader_title VARCHAR(100), -- Their title within the organization
    autonomy_level VARCHAR(50), -- Independent, Semi-autonomous, Controlled, Puppet, etc.
    reporting_relationship TEXT, -- Who they report to in the organization hierarchy
    local_activities TEXT, -- What this chapter specifically does
    local_reputation VARCHAR(100), -- How they're viewed locally
    secrecy_level VARCHAR(50), -- Open, Discreet, Secret, Hidden, etc.
    recruitment_status VARCHAR(50), -- Actively Recruiting, Selective, Closed, Secret, etc.
    current_projects TEXT, -- What they're working on now
    resources_available TEXT, -- What this chapter has access to
    challenges_faced TEXT, -- Problems this chapter is dealing with
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(organization_id, location_id, chapter_name)
);

-- =====================================================
-- Indexes
-- =====================================================

CREATE INDEX idx_org_chapters_org ON public.organization_chapters (organization_id);
CREATE INDEX idx_org_chapters_location ON public.organization_chapters (location_id);
CREATE INDEX idx_org_chapters_status ON public.organization_chapters (chapter_status);
CREATE INDEX idx_org_chapters_type ON public.organization_chapters (chapter_type);

-- =====================================================
-- Triggers
-- =====================================================

CREATE TRIGGER organization_chapters_updated_at_trigger
    BEFORE UPDATE ON public.organization_chapters
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

-- =====================================================
-- Comments
-- =====================================================

COMMENT ON TABLE public.organization_chapters IS 'Detailed information about organization chapters/branches at specific locations';