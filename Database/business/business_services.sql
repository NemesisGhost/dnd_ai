-- =====================================================
-- Business Services Relationship Table
-- Requires: businesses.sql, ../services.sql, ../lookups/cost_types.sql
-- =====================================================

DROP TABLE IF EXISTS public.business_services CASCADE;

CREATE TABLE public.business_services (
    business_service_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id UUID NOT NULL REFERENCES public.businesses(business_id) ON DELETE CASCADE,
    service_id UUID NOT NULL REFERENCES public.services(service_id) ON DELETE CASCADE,
    
    -- Business-specific service details
    is_primary_service BOOLEAN DEFAULT FALSE, -- Is this a main service offered?
    is_specialty BOOLEAN DEFAULT FALSE, -- Is this business known for this service?
    quality_level INTEGER DEFAULT 5, -- 1-10 quality level this business provides
    cost_type_id UUID REFERENCES public.cost_types(cost_type_id), -- This business's cost structure for this service
    cost_details TEXT, -- Specific pricing details for this business
    availability VARCHAR(100) DEFAULT 'Regular Hours', -- When this service is available
    capacity_level VARCHAR(50), -- Low, Medium, High capacity for this service
    
    -- Service-specific details
    custom_description TEXT, -- How this business specifically provides this service
    equipment_or_facilities TEXT, -- Special equipment this business has for this service
    staff_assigned TEXT, -- Who handles this service at this business
    success_reputation INTEGER DEFAULT 5, -- 1-10 reputation for this specific service
    
    -- Business context
    years_offering INTEGER DEFAULT 1, -- How long they've offered this service
    seasonal_availability BOOLEAN DEFAULT FALSE, -- Only available certain times of year
    requires_appointment BOOLEAN DEFAULT FALSE, -- Must be scheduled in advance
    walk_in_accepted BOOLEAN DEFAULT TRUE, -- Accepts customers without appointment
    
    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    notes TEXT, -- Additional context about this service offering
    
    -- Constraints
    UNIQUE(business_id, service_id),
    CHECK(quality_level BETWEEN 1 AND 10),
    CHECK(success_reputation BETWEEN 1 AND 10),
    CHECK(years_offering >= 0)
);

-- Indexes for performance
CREATE INDEX idx_business_services_business ON public.business_services (business_id);
CREATE INDEX idx_business_services_service ON public.business_services (service_id);
CREATE INDEX idx_business_services_cost_type ON public.business_services (cost_type_id);
CREATE INDEX idx_business_services_primary ON public.business_services (is_primary_service);
CREATE INDEX idx_business_services_specialty ON public.business_services (is_specialty);
CREATE INDEX idx_business_services_quality ON public.business_services (quality_level DESC);
CREATE INDEX idx_business_services_reputation ON public.business_services (success_reputation DESC);

-- Trigger for updated_at
CREATE TRIGGER business_services_updated_at_trigger
    BEFORE UPDATE ON public.business_services
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

-- Comments
COMMENT ON TABLE public.business_services IS 'Many-to-many relationship linking businesses to services they offer';
COMMENT ON COLUMN public.business_services.is_primary_service IS 'Whether this is one of the main services this business is known for';
COMMENT ON COLUMN public.business_services.is_specialty IS 'Whether this business has a particular reputation or expertise in this service';
COMMENT ON COLUMN public.business_services.quality_level IS 'The quality level this business provides for this specific service';
COMMENT ON COLUMN public.business_services.cost_type_id IS 'The cost structure this business uses for this service';
COMMENT ON COLUMN public.business_services.cost_details IS 'Specific pricing details for this business''s provision of this service';
COMMENT ON COLUMN public.business_services.success_reputation IS 'This business''s reputation specifically for this service';