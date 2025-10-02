-- =====================================================
-- Nations Main Table - Political Entities & Kingdoms
-- Requires: locations.sql
-- =====================================================

DROP TABLE IF EXISTS public.nations CASCADE;

CREATE TABLE public.nations (
    -- Primary identification
    nation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(200) NOT NULL,
    
    -- Political structure
    government_type VARCHAR(100) NOT NULL, -- Kingdom, Empire, Republic, Federation, etc.
    current_ruler VARCHAR(200), -- Name and title of head of state
    ruling_dynasty VARCHAR(200), -- Royal family or ruling house
    succession_type VARCHAR(100), -- Hereditary, Elected, Appointed, etc.
    capital_city_id UUID REFERENCES public.locations(location_id), -- FK to locations table
    
    -- Geographic information
    total_area_description TEXT, -- Size and scope in narrative terms
    -- natural_resources moved to nation_resources relationship table
    
    -- Borders and neighbors
    disputed_territories TEXT, -- Areas of conflict or unclear ownership
    border_security VARCHAR(100), -- Open, Guarded, Fortified, Hostile, etc.
    
    -- Demographics and culture
    total_population_estimate INTEGER,
    -- dominant_races moved to nation_races relationship table
    -- minority_races moved to nation_races relationship table
    -- official_languages moved to nation_languages relationship table
    -- common_languages moved to nation_languages relationship table
    dominant_religion VARCHAR(200), -- Primary faith or belief system
    religious_tolerance VARCHAR(100), -- How other faiths are treated
    
    -- Social structure
    -- social_classes moved to nation_social_classes child table
    mobility_between_classes VARCHAR(100), -- Rigid, Limited, Moderate, High
    cultural_values TEXT, -- What the society values most
    social_customs TEXT, -- Important traditions and norms
    education_system TEXT, -- How learning and knowledge are handled
    
    -- Military and defense
    military_structure TEXT, -- How armed forces are organized
    military_strength VARCHAR(100), -- Weak, Moderate, Strong, Dominant
    fortifications TEXT, -- Major defensive structures
    military_traditions TEXT, -- Warrior culture, codes of honor, etc.
    
    -- Economy and trade
    economic_system VARCHAR(100), -- Feudal, Mercantile, Mixed, etc.
    wealth_level VARCHAR(50), -- Impoverished, Struggling, Stable, Prosperous, Wealthy
    currency_system TEXT, -- What money they use
    taxation_system TEXT, -- How taxes work
    
    -- Magic and technology
    magic_prevalence VARCHAR(100), -- Rare, Uncommon, Common, Widespread
    magic_regulation VARCHAR(100), -- Banned, Restricted, Regulated, Free
    technology_level VARCHAR(100), -- Medieval, Renaissance, etc.
    
    -- International relations
    current_conflicts TEXT, -- Wars or major disputes
    historical_conflicts TEXT, -- Past wars and their outcomes
    -- alliances moved to nation_allies relationship table
    reputation_abroad TEXT, -- How other nations view them
    
    -- Internal politics
    current_political_climate VARCHAR(100), -- Stable, Tense, Chaotic, etc.
    -- major_political_factions moved to nation_political_factions relationship table
    internal_conflicts TEXT, -- Civil issues, rebellions, etc.
    succession_issues TEXT, -- Problems with leadership transition
    
    -- History and lore
    founding_story TEXT, -- How the nation came to be
    significant_historical_events TEXT, -- Major events in chronological order
    legendary_figures TEXT, -- Important historical people
    national_symbols TEXT, -- Flags, emblems, colors, etc.
    -- national_holidays moved to nation_holidays child table
    
    -- Adventure relevance
    current_major_events TEXT, -- What's happening now that affects adventures
    adventure_opportunities TEXT, -- Potential quest hooks
    dangers_and_threats TEXT, -- Problems the nation faces
    
    -- Status and metadata
    current_status VARCHAR(50) DEFAULT 'Stable', -- Stable, At War, In Crisis, Declining, etc.
    last_major_change TEXT, -- Recent significant events
    dm_notes TEXT, -- Private information for DM
    player_knowledge TEXT, -- What players have learned
    campaign_relevance TEXT, -- How this fits into current story
    
    -- Organization
    -- tags moved to nation_tags relationship table
    source_material TEXT, -- Reference documents
    
    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- =====================================================
-- Indexes
-- =====================================================

CREATE INDEX idx_nations_name_search ON public.nations USING gin(to_tsvector('english', name));
CREATE INDEX idx_nations_government ON public.nations (government_type);
CREATE INDEX idx_nations_capital ON public.nations (capital_city_id);
CREATE INDEX idx_nations_status ON public.nations (current_status);

-- =====================================================
-- Triggers
-- =====================================================

CREATE TRIGGER nations_updated_at_trigger
    BEFORE UPDATE ON public.nations
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

-- =====================================================
-- Comments
-- =====================================================

COMMENT ON TABLE public.nations IS 'Political entities like kingdoms, empires, and nations';