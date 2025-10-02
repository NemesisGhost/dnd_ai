-- =====================================================
-- Organization Services Relationship Table
-- Requires: organizations.sql, services.sql
-- =====================================================

DROP TABLE IF EXISTS public.organization_services CASCADE;

CREATE TABLE public.organization_services (
    -- Primary identification
    organization_service_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Foreign keys
    organization_id UUID NOT NULL REFERENCES public.organizations(organization_id) ON DELETE CASCADE,
    service_id UUID NOT NULL REFERENCES public.services(service_id) ON DELETE CASCADE,
    
    -- Service provision details
    availability_status VARCHAR(50) DEFAULT 'Available', -- Available, Limited, Suspended, By Request Only
    quality_modifier INTEGER DEFAULT 0, -- -3 to +3 modifier to base service quality
    cost_modifier_percentage INTEGER DEFAULT 0, -- Percentage adjustment to base cost (-50 to +200)
    wait_time_modifier VARCHAR(100), -- How this org's wait time differs from typical
    
    -- Organization-specific service details
    specialized_description TEXT, -- How this org's version differs from the standard
    service_requirements TEXT, -- Special requirements this org has for the service
    service_limitations TEXT, -- What this org cannot or will not do
    preferred_clients TEXT, -- Who gets priority or better service
    
    -- Provisioning information
    primary_provider VARCHAR(200), -- Name/title of who typically provides this
    provider_skill_level INTEGER, -- 1-10 skill level of the provider
    backup_providers TEXT, -- Who else can provide if primary unavailable
    training_requirements TEXT, -- What training the org requires for providers
    
    -- Business aspects
    pricing_structure TEXT, -- How they price this service
    payment_terms TEXT, -- When and how payment is expected
    discounts_offered TEXT, -- Member discounts, bulk rates, etc.
    premium_options TEXT, -- Upgraded versions available
    
    -- Operational details
    service_hours VARCHAR(100), -- When this service is available
    location_restrictions TEXT, -- Where within the org this is offered
    equipment_provided TEXT, -- What tools/materials the org supplies
    client_requirements TEXT, -- What clients must provide or meet
    
    -- Reputation and track record
    service_reputation VARCHAR(50), -- Poor, Fair, Good, Excellent, Legendary
    success_rate_modifier INTEGER DEFAULT 0, -- -20 to +20 percentage points
    notable_successes TEXT, -- Famous examples of excellent service
    notable_failures TEXT, -- Known problems or disasters
    client_testimonials TEXT, -- What people say about their service
    
    -- Relationships and politics
    competing_providers TEXT, -- Other orgs that offer similar services
    service_partnerships TEXT, -- Other orgs they work with for this service
    referral_arrangements TEXT, -- Who they send overflow to
    
    -- Availability and scheduling
    seasonal_availability TEXT, -- Time-based service availability
    capacity_limits INTEGER, -- Maximum concurrent clients
    booking_lead_time VARCHAR(50), -- How far in advance to schedule
    cancellation_policy TEXT, -- Terms for canceling service
    
    -- Service evolution
    service_history TEXT, -- How long they've offered this service
    planned_improvements TEXT, -- How they plan to enhance the service
    expansion_plans TEXT, -- Plans to offer this service elsewhere
    
    -- Adventure hooks
    service_related_quests TEXT, -- Adventures that could involve this service
    service_complications TEXT, -- Problems that could arise with this service
    plot_opportunities TEXT, -- Story hooks related to this service offering
    
    -- Metadata
    added_date TIMESTAMP WITH TIME ZONE DEFAULT NOW(), -- When org started offering this
    last_updated TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    dm_notes TEXT, -- Private DM information about this service offering
    player_knowledge_level VARCHAR(50) DEFAULT 'Unknown', -- What players know about this
    campaign_relevance TEXT, -- How this affects current story
    -- tags are now normalized into organization_service_tags table
    
    -- Constraints
    CONSTRAINT unique_org_service UNIQUE (organization_id, service_id),
    CONSTRAINT valid_quality_modifier CHECK (quality_modifier BETWEEN -3 AND 3),
    CONSTRAINT valid_cost_modifier CHECK (cost_modifier_percentage BETWEEN -50 AND 200),
    CONSTRAINT valid_provider_skill CHECK (provider_skill_level BETWEEN 1 AND 10),
    CONSTRAINT valid_success_modifier CHECK (success_rate_modifier BETWEEN -20 AND 20)
);

-- Indexes
CREATE INDEX idx_org_services_organization ON public.organization_services (organization_id);
CREATE INDEX idx_org_services_service ON public.organization_services (service_id);
CREATE INDEX idx_org_services_availability ON public.organization_services (availability_status);
CREATE INDEX idx_org_services_quality ON public.organization_services (quality_modifier);
CREATE INDEX idx_org_services_reputation ON public.organization_services (service_reputation);
CREATE INDEX idx_org_services_provider_skill ON public.organization_services (provider_skill_level);
-- CREATE INDEX idx_org_services_tags ON public.organization_services USING gin(tags);

-- Trigger for updated_at
CREATE TRIGGER organization_services_updated_at_trigger
    BEFORE UPDATE ON public.organization_services
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

-- Comments
COMMENT ON TABLE public.organization_services IS 'Many-to-many relationship between organizations and the services they offer';
COMMENT ON COLUMN public.organization_services.availability_status IS 'Available, Limited, Suspended, By Request Only';
COMMENT ON COLUMN public.organization_services.quality_modifier IS 'Adjustment to base service quality (-3 to +3)';
COMMENT ON COLUMN public.organization_services.cost_modifier_percentage IS 'Percentage adjustment to base cost (-50% to +200%)';
COMMENT ON COLUMN public.organization_services.provider_skill_level IS 'Skill level of the person providing this service (1-10)';
COMMENT ON COLUMN public.organization_services.service_reputation IS 'How well known this org is for this service';
COMMENT ON COLUMN public.organization_services.success_rate_modifier IS 'Adjustment to base success rate (-20 to +20 percentage points)';
COMMENT ON COLUMN public.organization_services.player_knowledge_level IS 'What players know: Unknown, Rumored, Known, Detailed';

-- Views removed as per requirements

-- Sample organization service offerings
-- Note: These would use actual UUIDs from the organizations and services tables
-- INSERT INTO public.organization_services (
--     organization_id, service_id, availability_status, quality_modifier,
--     specialized_description, primary_provider, provider_skill_level,
--     service_reputation, pricing_structure
-- ) VALUES 
-- (
--     (SELECT organization_id FROM public.organizations WHERE name = 'Merchants Guild of the Golden Road'),
--     (SELECT service_id FROM public.services WHERE service_name = 'Local Cart Transport'),
--     'Available', 1,
--     'Guild-certified transport with insurance coverage and priority scheduling',
--     'Guild Transport Division', 6,
--     'Excellent', 'Guild member rates: 20% discount, Non-members: standard rates'
-- ),
-- (
--     (SELECT organization_id FROM public.organizations WHERE name = 'Order of the Silver Dawn'),
--     (SELECT service_id FROM public.services WHERE service_name = 'Basic Wound Treatment'),
--     'Available', 2,
--     'Blessed healing combining mundane medicine with divine blessing',
--     'Temple Healers', 7,
--     'Excellent', 'Free for pilgrims and good-aligned individuals, donations accepted'
-- ),
-- (
--     (SELECT organization_id FROM public.organizations WHERE name = 'The Whispered Word'),
--     (SELECT service_id FROM public.services WHERE service_name = 'Detailed Area Intelligence'),
--     'By Request Only', 3,
--     'Comprehensive intelligence including secrets not available through normal channels',
--     'Information Brokers', 9,
--     'Legendary', 'High fees, payment in gold or equivalent favors'
-- );