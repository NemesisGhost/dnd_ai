-- =====================================================
-- Business Relationships Table (Combined Competitors and Alliances)
-- =====================================================

DROP TABLE IF EXISTS public.business_relationships CASCADE;

CREATE TABLE public.business_relationships (
    relationship_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id UUID NOT NULL REFERENCES public.businesses(business_id) ON DELETE CASCADE,
    related_business_id UUID NOT NULL REFERENCES public.businesses(business_id) ON DELETE CASCADE,
    relationship_category_id UUID NOT NULL REFERENCES public.relationship_categories(category_id),
    relationship_type_id UUID REFERENCES public.relationship_types(type_id),
    relationship_intensity_id UUID REFERENCES public.relationship_intensity_levels(intensity_id),
    relationship_status_id UUID REFERENCES public.relationship_statuses(status_id),
    relationship_start_date DATE,
    relationship_end_date DATE,
    relationship_history TEXT,
    notable_incidents TEXT,
    market_overlap_percentage INTEGER,
    competitive_advantages TEXT,
    shared_customers BOOLEAN DEFAULT FALSE,
    price_competition BOOLEAN DEFAULT FALSE,
    quality_competition BOOLEAN DEFAULT FALSE,
    mutual_benefit_description TEXT,
    formal_agreement BOOLEAN DEFAULT FALSE,
    renewal_terms TEXT,
    termination_conditions TEXT,
    shared_resources TEXT,
    joint_marketing BOOLEAN DEFAULT FALSE,
    referral_arrangement BOOLEAN DEFAULT FALSE,
    exclusive_arrangement BOOLEAN DEFAULT FALSE,
    revenue_sharing_percentage INTEGER,
    cost_sharing_arrangement TEXT,
    financial_commitments TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    notes TEXT,
    UNIQUE(business_id, related_business_id),
    CHECK(business_id != related_business_id),
    CHECK(relationship_end_date IS NULL OR relationship_end_date >= relationship_start_date),
    CHECK(market_overlap_percentage IS NULL OR (market_overlap_percentage BETWEEN 0 AND 100)),
    CHECK(revenue_sharing_percentage IS NULL OR (revenue_sharing_percentage BETWEEN 0 AND 100))
);

CREATE INDEX idx_business_relationships_business ON public.business_relationships (business_id);
CREATE INDEX idx_business_relationships_related ON public.business_relationships (related_business_id);
CREATE INDEX idx_business_relationships_category ON public.business_relationships (relationship_category_id);
CREATE INDEX idx_business_relationships_type ON public.business_relationships (relationship_type_id);
CREATE INDEX idx_business_relationships_intensity ON public.business_relationships (relationship_intensity_id);
CREATE INDEX idx_business_relationships_status ON public.business_relationships (relationship_status_id);
CREATE INDEX idx_business_relationships_dates ON public.business_relationships (relationship_start_date, relationship_end_date);

CREATE TRIGGER business_relationships_updated_at_trigger
    BEFORE UPDATE ON public.business_relationships
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

COMMENT ON TABLE public.business_relationships IS 'Many-to-many relationship tracking all types of relationships between businesses (competitive, alliance, neutral)';
COMMENT ON COLUMN public.business_relationships.relationship_category_id IS 'Foreign key to relationship_categories lookup table';
COMMENT ON COLUMN public.business_relationships.relationship_type_id IS 'Foreign key to relationship_types lookup table';
COMMENT ON COLUMN public.business_relationships.relationship_intensity_id IS 'Foreign key to relationship_intensity_levels lookup table';
COMMENT ON COLUMN public.business_relationships.relationship_status_id IS 'Foreign key to relationship_statuses lookup table';
COMMENT ON COLUMN public.business_relationships.market_overlap_percentage IS 'Percentage of market overlap between businesses';
COMMENT ON COLUMN public.business_relationships.revenue_sharing_percentage IS 'Percentage of revenue shared between businesses';