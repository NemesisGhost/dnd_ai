-- =====================================================
-- Business Tags Relationship Table
-- Many-to-many relationship between businesses and tags
-- Requires: businesses.sql, ../tags.sql
-- =====================================================

-- Business Tags Relationship Table
DROP TABLE IF EXISTS public.business_tags CASCADE;

CREATE TABLE public.business_tags (
    business_tag_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id UUID NOT NULL REFERENCES public.businesses(business_id) ON DELETE CASCADE,
    tag_id UUID NOT NULL REFERENCES public.tags(tag_id) ON DELETE CASCADE,
    
    -- Tag application details
    is_primary BOOLEAN DEFAULT FALSE, -- Is this a primary/main tag for this business?
    relevance_score INTEGER CHECK (relevance_score BETWEEN 1 AND 10), -- How relevant is this tag (1-10)?
    tag_source VARCHAR(50) DEFAULT 'Manual', -- Manual, Auto-Generated, Player-Applied, DM-Applied
    
    -- Context and notes
    context_notes TEXT, -- Why this tag applies to this business
    visibility VARCHAR(50) DEFAULT 'Public', -- Public, DM-Only, Player-Discovered
    
    -- Status tracking
    is_active BOOLEAN DEFAULT TRUE, -- Is this tag currently applicable?
    date_applied DATE DEFAULT CURRENT_DATE, -- When this tag was first applied
    date_removed DATE, -- When tag was removed (if applicable)
    applied_by VARCHAR(100), -- Who applied this tag
    
    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Constraints
    UNIQUE(business_id, tag_id), -- Each business can only have each tag once
    CHECK(date_removed IS NULL OR date_removed >= date_applied)
);

-- Indexes for performance
CREATE INDEX idx_business_tags_business ON public.business_tags (business_id);
CREATE INDEX idx_business_tags_tag ON public.business_tags (tag_id);
CREATE INDEX idx_business_tags_primary ON public.business_tags (is_primary) WHERE is_primary = TRUE;
CREATE INDEX idx_business_tags_active ON public.business_tags (is_active) WHERE is_active = TRUE;
CREATE INDEX idx_business_tags_visibility ON public.business_tags (visibility);
CREATE INDEX idx_business_tags_relevance ON public.business_tags (relevance_score);

-- Trigger for updated_at
CREATE TRIGGER business_tags_updated_at_trigger
    BEFORE UPDATE ON public.business_tags
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

-- Comments
COMMENT ON TABLE public.business_tags IS 'Many-to-many relationship between businesses and descriptive tags';
COMMENT ON COLUMN public.business_tags.is_primary IS 'Whether this is a primary/defining tag for the business';
COMMENT ON COLUMN public.business_tags.relevance_score IS 'Numeric score (1-10) indicating how relevant this tag is to the business';
COMMENT ON COLUMN public.business_tags.tag_source IS 'Source of the tag assignment (Manual, Auto-Generated, Player-Applied, DM-Applied)';
COMMENT ON COLUMN public.business_tags.visibility IS 'Who can see this tag (Public, DM-Only, Player-Discovered)';
COMMENT ON COLUMN public.business_tags.context_notes IS 'Explanation of why this tag applies to this specific business';

-- Sample data showing how businesses would be tagged
-- These would be populated after businesses and tags are created

/*
-- Example: Prancing Pony Inn tags
INSERT INTO public.business_tags (business_id, tag_id, is_primary, relevance_score, tag_source, context_notes) VALUES 
(
    (SELECT business_id FROM public.businesses WHERE name = 'The Prancing Pony Inn'),
    (SELECT tag_id FROM public.tags WHERE name = 'tavern'),
    TRUE, -- Primary tag
    10, -- Highest relevance
    'Manual',
    'Primary business type - serves food and drink'
),
(
    (SELECT business_id FROM public.businesses WHERE name = 'The Prancing Pony Inn'),
    (SELECT tag_id FROM public.tags WHERE name = 'inn'),
    TRUE, -- Also primary
    10,
    'Manual',
    'Provides lodging for travelers'
),
(
    (SELECT business_id FROM public.businesses WHERE name = 'The Prancing Pony Inn'),
    (SELECT tag_id FROM public.tags WHERE name = 'social-hub'),
    FALSE, -- Important but not primary
    8,
    'Manual',
    'Central gathering place where people share news and stories'
),
(
    (SELECT business_id FROM public.businesses WHERE name = 'The Prancing Pony Inn'),
    (SELECT tag_id FROM public.tags WHERE name = 'information-broker'),
    FALSE,
    6,
    'DM-Applied',
    'Bartender and patrons are good sources of local information'
);

-- Example: Ironforge Smithy tags
INSERT INTO public.business_tags (business_id, tag_id, is_primary, relevance_score, tag_source, context_notes) VALUES 
(
    (SELECT business_id FROM public.businesses WHERE name = 'Ironforge Smithy'),
    (SELECT tag_id FROM public.tags WHERE name = 'blacksmith'),
    TRUE,
    10,
    'Manual',
    'Primary business - metalworking and forging'
),
(
    (SELECT business_id FROM public.businesses WHERE name = 'Ironforge Smithy'),
    (SELECT tag_id FROM public.tags WHERE name = 'weapons'),
    TRUE,
    9,
    'Manual',
    'Specializes in weapon crafting and repair'
),
(
    (SELECT business_id FROM public.businesses WHERE name = 'Ironforge Smithy'),
    (SELECT tag_id FROM public.tags WHERE name = 'armor'),
    FALSE,
    7,
    'Manual',
    'Also creates and repairs armor, though less specialized'
),
(
    (SELECT business_id FROM public.businesses WHERE name = 'Ironforge Smithy'),
    (SELECT tag_id FROM public.tags WHERE name = 'crafting'),
    FALSE,
    8,
    'Manual',
    'High-quality craftsmanship and custom work'
);

-- Example: Tax Office tags  
INSERT INTO public.business_tags (business_id, tag_id, is_primary, relevance_score, tag_source, context_notes) VALUES 
(
    (SELECT business_id FROM public.businesses WHERE name = 'Office of the Tax Collector'),
    (SELECT tag_id FROM public.tags WHERE name = 'government'),
    TRUE,
    10,
    'Manual',
    'Official government office'
),
(
    (SELECT business_id FROM public.businesses WHERE name = 'Office of the Tax Collector'),
    (SELECT tag_id FROM public.tags WHERE name = 'bureaucracy'),
    TRUE,
    9,
    'Manual',
    'Heavy bureaucratic processes and paperwork'
),
(
    (SELECT business_id FROM public.businesses WHERE name = 'Office of the Tax Collector'),
    (SELECT tag_id FROM public.tags WHERE name = 'official'),
    FALSE,
    8,
    'Manual',
    'Represents official authority and legal processes'
),
(
    (SELECT business_id FROM public.businesses WHERE name = 'Office of the Tax Collector'),
    (SELECT tag_id FROM public.tags WHERE name = 'records'),
    FALSE,
    7,
    'Manual',
    'Maintains extensive financial and legal records'
);
*/