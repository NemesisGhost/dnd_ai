-- =====================================================
-- Nation Allies Relationship Table (Many-to-Many Self-Referential)
-- Requires: nations_main.sql
-- =====================================================

DROP TABLE IF EXISTS public.nation_allies CASCADE;

CREATE TABLE public.nation_allies (
    relationship_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nation_id UUID NOT NULL REFERENCES public.nations(nation_id) ON DELETE CASCADE,
    ally_nation_id UUID NOT NULL REFERENCES public.nations(nation_id) ON DELETE CASCADE,
    
    -- Alliance details
    alliance_type VARCHAR(50) NOT NULL, -- 'Military', 'Trade', 'Defensive', 'Mutual Defense', 'Non-Aggression', 'Full Alliance'
    alliance_status VARCHAR(50) DEFAULT 'Active', -- 'Active', 'Suspended', 'Under Review', 'Expired', 'Broken'
    formality_level VARCHAR(50), -- 'Formal Treaty', 'Written Agreement', 'Verbal Agreement', 'Understood', 'Traditional'
    
    -- Treaty details
    treaty_name VARCHAR(200), -- Official name of the alliance/treaty
    signed_date VARCHAR(100), -- When the alliance was formed
    duration VARCHAR(100), -- How long the alliance lasts
    renewal_terms TEXT, -- How the alliance can be renewed
    
    -- Obligations and benefits
    mutual_obligations TEXT, -- What each nation owes the other
    military_commitments TEXT, -- Military support requirements
    economic_benefits TEXT, -- Trade advantages and economic cooperation
    diplomatic_support TEXT, -- How they support each other politically
    
    -- Terms and conditions
    activation_conditions TEXT, -- What triggers alliance obligations
    exemptions_and_limitations TEXT, -- What the alliance doesn't cover
    termination_conditions TEXT, -- How the alliance can end
    
    -- Practical aspects
    cooperation_level VARCHAR(50), -- 'Close', 'Good', 'Formal', 'Minimal', 'Strained'
    recent_cooperation TEXT, -- Examples of recent joint efforts
    joint_activities TEXT, -- Regular cooperative activities
    shared_resources TEXT, -- What they share with each other
    
    -- Historical context
    alliance_history TEXT, -- How the alliance developed
    previous_conflicts TEXT, -- Past disputes between allies
    relationship_evolution TEXT, -- How the relationship has changed
    
    -- Current status
    public_perception VARCHAR(50), -- How citizens view the alliance
    government_commitment VARCHAR(50), -- How committed leadership is
    potential_issues TEXT, -- Possible future problems
    
    -- Metadata
    last_reviewed DATE DEFAULT CURRENT_DATE,
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Prevent self-reference and duplicate relationships
    CHECK (nation_id != ally_nation_id),
    UNIQUE(nation_id, ally_nation_id)
);

-- =====================================================
-- Indexes
-- =====================================================

CREATE INDEX idx_nation_allies_nation ON public.nation_allies (nation_id);
CREATE INDEX idx_nation_allies_ally ON public.nation_allies (ally_nation_id);
CREATE INDEX idx_nation_allies_type ON public.nation_allies (alliance_type);
CREATE INDEX idx_nation_allies_status ON public.nation_allies (alliance_status);

-- =====================================================
-- Triggers
-- =====================================================

CREATE TRIGGER nation_allies_updated_at_trigger
    BEFORE UPDATE ON public.nation_allies
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

-- =====================================================
-- Comments
-- =====================================================

COMMENT ON TABLE public.nation_allies IS 'Many-to-many self-referential table for nation alliances';
COMMENT ON COLUMN public.nation_allies.alliance_type IS 'Military, Trade, Defensive, Mutual Defense, Non-Aggression, Full Alliance';