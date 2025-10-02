-- =====================================================
-- NPCs Table - Normalized World Building & Roleplay Focus
-- =====================================================

DROP TABLE IF EXISTS public.npcs CASCADE;

CREATE TABLE public.npcs (
    npc_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(200) NOT NULL,
    race_id UUID REFERENCES public.races(race_id),
    age_category_id UUID REFERENCES public.age_categories(age_category_id),
    gender VARCHAR(50),
    physical_description TEXT,
    distinguishing_features TEXT,
    social_status_id UUID REFERENCES public.social_statuses(status_id),
    reputation TEXT,
    current_location_id UUID REFERENCES public.locations(location_id),
    origin_location_id UUID REFERENCES public.locations(location_id),
    frequently_found_at TEXT,
    backstory TEXT,
    current_goals TEXT,
    conversation_style_notes TEXT,
    personality_prompt TEXT,
    current_status_id UUID REFERENCES public.npc_statuses(status_id),
    disposition_id UUID REFERENCES public.npc_dispositions(disposition_id),
    availability_schedule TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    dm_notes TEXT,
    player_visible_notes TEXT,
    portrait_image_url TEXT,
    source_material TEXT
);

-- Indexes for common queries
CREATE INDEX idx_npcs_name_search ON public.npcs USING gin(to_tsvector('english', name));
CREATE INDEX idx_npcs_race ON public.npcs (race_id);
CREATE INDEX idx_npcs_social_status ON public.npcs (social_status_id);
CREATE INDEX idx_npcs_age_category ON public.npcs (age_category_id);
CREATE INDEX idx_npcs_current_location ON public.npcs (current_location_id);
CREATE INDEX idx_npcs_origin_location ON public.npcs (origin_location_id);
CREATE INDEX idx_npcs_current_status ON public.npcs (current_status_id);
CREATE INDEX idx_npcs_disposition ON public.npcs (disposition_id);

CREATE TRIGGER npcs_updated_at_trigger
    BEFORE UPDATE ON public.npcs
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

COMMENT ON TABLE public.npcs IS 'Normalized NPCs table focused on world-building and roleplay aspects with foreign key references';
COMMENT ON COLUMN public.npcs.race_id IS 'Foreign key to races lookup table';
COMMENT ON COLUMN public.npcs.age_category_id IS 'Foreign key to age_categories lookup table';
COMMENT ON COLUMN public.npcs.social_status_id IS 'Foreign key to social_statuses lookup table';
COMMENT ON COLUMN public.npcs.current_status_id IS 'Foreign key to npc_statuses lookup table';
COMMENT ON COLUMN public.npcs.disposition_id IS 'Foreign key to npc_dispositions lookup table';