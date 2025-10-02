-- =====================================================
-- Organization Leaders Relationship Table
-- Requires: organizations.sql, npcs.sql
-- =====================================================

DROP TABLE IF EXISTS public.organization_leaders CASCADE;

CREATE TABLE public.organization_leaders (
    -- Primary identification
    leader_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Foreign keys
    organization_id UUID NOT NULL REFERENCES public.organizations(organization_id) ON DELETE CASCADE,
    npc_id UUID NOT NULL REFERENCES public.npcs(npc_id) ON DELETE CASCADE,
    
    -- Leadership position details
    title_name VARCHAR(200) NOT NULL,
    rank_order INTEGER, -- 1 = highest rank, higher numbers = lower ranks (null for past leaders if hierarchy unclear)
    
    -- Leadership status
    leadership_status VARCHAR(50) NOT NULL DEFAULT 'Current', -- Current, Past, Interim, Vacant
    is_primary_leader BOOLEAN DEFAULT FALSE, -- Is this the main/top leader?
    
    -- Authority and responsibilities
    authority_level VARCHAR(50), -- Executive, Administrative, Advisory, Ceremonial
    responsibilities TEXT, -- What this role is responsible for
    required_qualifications TEXT, -- What's needed to hold this position
    
    -- Tenure tracking
    start_date VARCHAR(100), -- When they began this position (can be approximate)
    end_date VARCHAR(100), -- When their tenure ended (null for current leaders)
    tenure_length VARCHAR(100), -- How long they held the position
    
    -- Position mechanics
    term_length VARCHAR(100), -- Life, Fixed Term, Until Replaced, etc.
    selection_method TEXT, -- How someone gets this position
    succession_planned BOOLEAN DEFAULT FALSE, -- Is there a planned successor?
    
    -- Leadership context (primarily for past leaders)
    how_they_gained_power TEXT, -- How they became leader
    how_leadership_ended TEXT, -- How their tenure concluded
    end_reason VARCHAR(100), -- Death, Retirement, Overthrown, Promoted, etc.
    
    -- Leadership assessment
    leadership_style VARCHAR(100), -- Authoritarian, Democratic, Charismatic, etc.
    major_accomplishments TEXT, -- What they achieved while leading
    significant_failures TEXT, -- Major mistakes or disasters
    legacy_impact TEXT, -- How they're remembered
    
    -- Historical significance
    historical_importance VARCHAR(50) DEFAULT 'Standard', -- Legendary, Major, Standard, Minor
    reputation_among_members VARCHAR(50), -- Revered, Respected, Neutral, Disliked, Hated
    public_reputation VARCHAR(50), -- How outsiders remember them
    
    -- Organizational impact
    changes_made TEXT, -- How they changed the organization
    policies_established TEXT, -- Rules or practices they created
    traditions_started TEXT, -- Customs that began under their leadership
    organizational_growth TEXT, -- How the org changed size/scope under them
    
    -- Current relevance
    current_influence TEXT, -- How their legacy still affects the organization
    successors_influenced TEXT, -- Leaders who followed their example
    ongoing_projects TEXT, -- Things they started that continue today
    
    -- Adventure hooks
    unfinished_business TEXT, -- Things they left undone
    hidden_secrets TEXT, -- Information only they knew
    enemies_made TEXT, -- Conflicts that might resurface
    treasure_or_artifacts TEXT, -- Items associated with their leadership
    
    -- Information quality and sources
    historical_records_quality VARCHAR(50) DEFAULT 'Good', -- Excellent, Good, Fair, Poor, Legendary
    contradictory_accounts BOOLEAN DEFAULT FALSE, -- Are there conflicting stories?
    player_knowledge_level VARCHAR(50) DEFAULT 'Unknown', -- Unknown, Rumored, Known, Well-Known
    source_of_information TEXT, -- Where this information comes from
    
    -- Metadata
    dm_notes TEXT, -- Private DM information
    campaign_relevance TEXT, -- How this affects current story
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT unique_org_npc_title UNIQUE (organization_id, npc_id, title_name),
    CONSTRAINT unique_org_rank_current UNIQUE (organization_id, rank_order) 
        DEFERRABLE INITIALLY DEFERRED, -- Only for current leaders
    CONSTRAINT valid_rank_order CHECK (rank_order IS NULL OR rank_order > 0),
    CONSTRAINT valid_dates CHECK (
        start_date IS NULL OR end_date IS NULL OR start_date != end_date
    ),
    CONSTRAINT valid_current_leader CHECK (
        (leadership_status = 'Current' AND end_date IS NULL) OR
        (leadership_status != 'Current' AND end_date IS NOT NULL) OR
        (leadership_status = 'Interim') OR
        (leadership_status = 'Vacant')
    )
);

-- Indexes
CREATE INDEX idx_org_leaders_organization ON public.organization_leaders (organization_id);
CREATE INDEX idx_org_leaders_npc ON public.organization_leaders (npc_id);
CREATE INDEX idx_org_leaders_status ON public.organization_leaders (leadership_status);
CREATE INDEX idx_org_leaders_primary ON public.organization_leaders (is_primary_leader);
CREATE INDEX idx_org_leaders_rank_order ON public.organization_leaders (rank_order);
CREATE INDEX idx_org_leaders_historical_importance ON public.organization_leaders (historical_importance);
CREATE INDEX idx_org_leaders_reputation_members ON public.organization_leaders (reputation_among_members);
CREATE INDEX idx_org_leaders_end_reason ON public.organization_leaders (end_reason);
CREATE INDEX idx_org_leaders_player_knowledge ON public.organization_leaders (player_knowledge_level);
CREATE INDEX idx_org_leaders_current ON public.organization_leaders (leadership_status) WHERE leadership_status = 'Current';

-- Trigger for updated_at
CREATE TRIGGER organization_leaders_updated_at_trigger
    BEFORE UPDATE ON public.organization_leaders
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

-- Comments
COMMENT ON TABLE public.organization_leaders IS 'Many-to-many relationship between organizations and NPC leaders (current and historical)';
COMMENT ON COLUMN public.organization_leaders.leadership_status IS 'Current, Past, Interim, Vacant';
COMMENT ON COLUMN public.organization_leaders.rank_order IS '1 = highest rank, higher numbers = lower ranks (null for past leaders if hierarchy unclear)';
COMMENT ON COLUMN public.organization_leaders.authority_level IS 'Executive, Administrative, Advisory, Ceremonial';
COMMENT ON COLUMN public.organization_leaders.end_reason IS 'Death, Retirement, Overthrown, Promoted, etc.';
COMMENT ON COLUMN public.organization_leaders.historical_importance IS 'Legendary, Major, Standard, Minor';
COMMENT ON COLUMN public.organization_leaders.reputation_among_members IS 'Revered, Respected, Neutral, Disliked, Hated';
COMMENT ON COLUMN public.organization_leaders.historical_records_quality IS 'Excellent, Good, Fair, Poor, Legendary';
COMMENT ON COLUMN public.organization_leaders.player_knowledge_level IS 'Unknown, Rumored, Known, Well-Known';

-- Views removed as per requirements

-- Sample leadership data
-- Note: These would use actual UUIDs from the organizations and npcs tables
-- INSERT INTO public.organization_leaders (
--     organization_id, npc_id, title_name, rank_order, leadership_status,
--     is_primary_leader, authority_level, start_date, leadership_style
-- ) VALUES 
-- -- Current leader
-- (
--     (SELECT organization_id FROM public.organizations WHERE name = 'Merchants Guild of the Golden Road'),
--     (SELECT npc_id FROM public.npcs WHERE name = 'Current Guildmaster'),
--     'Guildmaster', 1, 'Current', TRUE, 'Executive',
--     '1456 DR', 'Democratic'
-- ),
-- -- Past leader
-- (
--     (SELECT organization_id FROM public.organizations WHERE name = 'Merchants Guild of the Golden Road'),
--     (SELECT npc_id FROM public.npcs WHERE name = 'Aldric the Golden'),
--     'Guildmaster', 1, 'Past', TRUE, 'Executive',
--     '1387 DR', 'Authoritarian'
-- );