-- =====================================================
-- Nation Political Factions Relationship Table (Many-to-Many with Organizations)
-- Requires: nations_main.sql, organizations.sql
-- =====================================================

DROP TABLE IF EXISTS public.nation_political_factions CASCADE;

CREATE TABLE public.nation_political_factions (
    relationship_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nation_id UUID NOT NULL REFERENCES public.nations(nation_id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES public.organizations(organization_id) ON DELETE CASCADE,
    
    -- Faction status in nation
    faction_status VARCHAR(50) NOT NULL, -- 'Ruling Party', 'Major Opposition', 'Minor Party', 'Banned', 'Underground', 'Emerging'
    political_influence VARCHAR(50), -- 'Dominant', 'Major', 'Moderate', 'Minor', 'Negligible'
    legal_status VARCHAR(50), -- 'Legal', 'Tolerated', 'Restricted', 'Illegal', 'Secret'
    
    -- Political position and goals
    political_ideology TEXT, -- What they believe politically
    primary_agenda TEXT, -- What they're trying to achieve
    policy_positions TEXT, -- Their stance on key issues
    reform_goals TEXT, -- Changes they want to make
    
    -- Support and membership
    support_base TEXT, -- Who supports them (demographics)
    membership_estimate INTEGER, -- Approximate number of members
    popular_support_percentage DECIMAL(5,2), -- Estimated public support
    geographic_strongholds TEXT, -- Where they're most popular
    
    -- Political activities
    political_methods TEXT, -- How they pursue their goals
    propaganda_efforts TEXT, -- How they spread their message
    recruitment_tactics TEXT, -- How they gain new supporters
    funding_sources TEXT, -- How they finance their activities
    
    -- Government interaction
    government_positions TEXT, -- Offices they hold
    official_representation BOOLEAN DEFAULT FALSE, -- Do they have formal representation
    government_relations VARCHAR(50), -- How they relate to current government
    opposition_activities TEXT, -- How they oppose current government
    
    -- Relationships with other factions
    allied_factions TEXT, -- Other groups they work with
    rival_factions TEXT, -- Groups they oppose
    faction_conflicts TEXT, -- Disputes with other factions
    
    -- Historical context
    formation_date VARCHAR(100), -- When this faction emerged
    key_historical_events TEXT, -- Important moments in their history
    past_successes TEXT, -- What they've accomplished
    past_failures TEXT, -- What they've failed to achieve
    leadership_changes TEXT, -- How leadership has evolved
    
    -- Current status and activities
    current_activities TEXT, -- What they're doing now
    recent_developments TEXT, -- Recent changes or events
    future_prospects VARCHAR(50), -- Growing, Stable, Declining, Uncertain
    
    -- Security and intelligence
    intelligence_capabilities TEXT, -- Their information gathering abilities
    security_measures TEXT, -- How they protect themselves
    infiltration_concerns TEXT, -- Worries about spies or sabotage
    
    -- Adventure relevance
    quest_opportunities TEXT, -- How players might work with them
    conflict_potential TEXT, -- How they might oppose players
    information_access TEXT, -- What useful information they have
    
    -- Metadata
    relationship_since VARCHAR(100), -- When they became active in this nation
    last_assessment DATE DEFAULT CURRENT_DATE,
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    UNIQUE(nation_id, organization_id)
);

-- =====================================================
-- Indexes
-- =====================================================

CREATE INDEX idx_nation_political_factions_nation ON public.nation_political_factions (nation_id);
CREATE INDEX idx_nation_political_factions_organization ON public.nation_political_factions (organization_id);
CREATE INDEX idx_nation_political_factions_status ON public.nation_political_factions (faction_status);
CREATE INDEX idx_nation_political_factions_influence ON public.nation_political_factions (political_influence);

-- =====================================================
-- Triggers
-- =====================================================

CREATE TRIGGER nation_political_factions_updated_at_trigger
    BEFORE UPDATE ON public.nation_political_factions
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

-- =====================================================
-- Comments
-- =====================================================

COMMENT ON TABLE public.nation_political_factions IS 'Many-to-many relationship between nations and political organizations';
COMMENT ON COLUMN public.nation_political_factions.faction_status IS 'Ruling Party, Major Opposition, Minor Party, Banned, Underground, Emerging';