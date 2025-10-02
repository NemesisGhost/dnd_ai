-- =====================================================
-- Nation Social Classes Child Table
-- Requires: nations_main.sql
-- =====================================================

DROP TABLE IF EXISTS public.nation_social_classes CASCADE;

CREATE TABLE public.nation_social_classes (
    class_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nation_id UUID NOT NULL REFERENCES public.nations(nation_id) ON DELETE CASCADE,
    
    -- Class details
    class_name VARCHAR(100) NOT NULL, -- Nobility, Merchants, Commoners, Peasants, etc.
    hierarchy_level INTEGER, -- 1 = highest, higher numbers = lower status
    population_percentage DECIMAL(5,2), -- Approximate percentage of population
    
    -- Economic aspects
    typical_wealth_level VARCHAR(50), -- Wealthy, Comfortable, Modest, Poor, Destitute
    common_occupations TEXT, -- What jobs this class typically holds
    economic_power TEXT, -- Their influence on the economy
    
    -- Social aspects
    social_privileges TEXT, -- Special rights or benefits
    social_obligations TEXT, -- Duties and responsibilities
    dress_codes TEXT, -- How they're expected to dress
    behavioral_expectations TEXT, -- Social rules they must follow
    
    -- Political aspects
    political_influence VARCHAR(50), -- None, Limited, Moderate, Significant, Dominant
    voting_rights BOOLEAN DEFAULT FALSE, -- Can they participate in elections
    office_eligibility TEXT, -- What positions they can hold
    
    -- Mobility
    mobility_into_class TEXT, -- How someone can join this class
    mobility_out_of_class TEXT, -- How someone can leave this class
    generational_expectations TEXT, -- Do children inherit class status
    
    -- Metadata
    historical_development TEXT, -- How this class evolved
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- =====================================================
-- Indexes
-- =====================================================

CREATE INDEX idx_nation_social_classes_nation ON public.nation_social_classes (nation_id);
CREATE INDEX idx_nation_social_classes_hierarchy ON public.nation_social_classes (hierarchy_level);
CREATE INDEX idx_nation_social_classes_political_influence ON public.nation_social_classes (political_influence);

-- =====================================================
-- Triggers
-- =====================================================

CREATE TRIGGER nation_social_classes_updated_at_trigger
    BEFORE UPDATE ON public.nation_social_classes
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

-- =====================================================
-- Comments
-- =====================================================

COMMENT ON TABLE public.nation_social_classes IS 'Child table for nation social class hierarchies';