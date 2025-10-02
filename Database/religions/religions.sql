-- =====================================================
-- Religions Table
-- =====================================================

DROP TABLE IF EXISTS public.religions CASCADE;

CREATE TABLE public.religions (
    religion_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(200) NOT NULL UNIQUE,
    religion_type VARCHAR(100),
    alignment VARCHAR(50),
    primary_deity VARCHAR(200),
    pantheon_name VARCHAR(200),
    core_beliefs TEXT,
    moral_code TEXT,
    afterlife_beliefs TEXT,
    creation_myth TEXT,
    worship_practices TEXT,
    rituals_and_ceremonies TEXT,
    pilgrimage_sites TEXT[],
    symbols_and_iconography TEXT,
    temples_and_shrines TEXT,
    geographic_spread VARCHAR(100),
    influence_level VARCHAR(50),
    membership_estimate INTEGER,
    attitudes_toward_magic VARCHAR(100),
    attitudes_toward_other_races TEXT,
    founding_history TEXT,
    significant_events TEXT,
    notable_figures TEXT,
    current_status VARCHAR(50) DEFAULT 'Active',
    dm_notes TEXT,
    source_material TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for common queries
CREATE INDEX idx_religions_name_search ON public.religions USING gin(to_tsvector('english', name));
CREATE INDEX idx_religions_type ON public.religions (religion_type);
CREATE INDEX idx_religions_alignment ON public.religions (alignment);
CREATE INDEX idx_religions_primary_deity ON public.religions (primary_deity);
CREATE INDEX idx_religions_pantheon ON public.religions (pantheon_name);
CREATE INDEX idx_religions_spread ON public.religions (geographic_spread);
CREATE INDEX idx_religions_influence ON public.religions (influence_level);
CREATE INDEX idx_religions_status ON public.religions (current_status);

-- Trigger for updated_at
CREATE TRIGGER religions_updated_at_trigger
    BEFORE UPDATE ON public.religions
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

-- Comments
COMMENT ON TABLE public.religions IS 'Religions, faiths, and belief systems in the world';
COMMENT ON COLUMN public.religions.religion_type IS 'Classification of the religious system';
COMMENT ON COLUMN public.religions.geographic_spread IS 'How widely this religion is practiced';
COMMENT ON COLUMN public.religions.influence_level IS 'How much influence this religion has';