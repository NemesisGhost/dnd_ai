-- =====================================================
-- Nation Languages Relationship Table (Many-to-Many)
-- =====================================================

DROP TABLE IF EXISTS public.nation_languages CASCADE;
CREATE TABLE public.nation_languages (
    relationship_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nation_id UUID NOT NULL REFERENCES public.nations(nation_id) ON DELETE CASCADE,
    language_id UUID NOT NULL REFERENCES public.languages(language_id) ON DELETE CASCADE,
    
    -- Language status
    status VARCHAR(50) NOT NULL, -- 'Official', 'Common', 'Regional', 'Minority', 'Trade', 'Religious', 'Academic'
    usage_context TEXT, -- Where and how this language is used
    speaker_percentage DECIMAL(5,2), -- Approximate percentage who speak it
    
    -- Official aspects
    government_usage BOOLEAN DEFAULT FALSE, -- Used in government/legal documents
    education_usage BOOLEAN DEFAULT FALSE, -- Taught in schools
    trade_usage BOOLEAN DEFAULT FALSE, -- Used for commerce
    
    -- Geographic and social distribution
    regional_usage TEXT, -- Where in the nation it's spoken
    social_classes_usage TEXT, -- Which social groups use it
    
    -- Status trends
    trend VARCHAR(50), -- 'Growing', 'Stable', 'Declining', 'Endangered'
    preservation_efforts TEXT, -- Efforts to maintain the language
    
    -- Metadata
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    UNIQUE(nation_id, language_id)
);

-- =====================================================
-- Indexes for Performance
-- =====================================================

CREATE INDEX idx_nation_languages_nation ON public.nation_languages (nation_id);
CREATE INDEX idx_nation_languages_language ON public.nation_languages (language_id);
CREATE INDEX idx_nation_languages_status ON public.nation_languages (status);

-- =====================================================
-- Triggers for Updated Timestamps
-- =====================================================

CREATE TRIGGER nation_languages_updated_at_trigger
    BEFORE UPDATE ON public.nation_languages
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

-- =====================================================
-- Comments
-- =====================================================

COMMENT ON TABLE public.nation_languages IS 'Many-to-many relationship between nations and their languages';
COMMENT ON COLUMN public.nation_languages.status IS 'Official, Common, Regional, Minority, Trade, Religious, or Academic';
COMMENT ON COLUMN public.nation_languages.speaker_percentage IS 'Approximate percentage of population who speak this language';