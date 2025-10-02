-- =====================================================
-- NPC Rumors Table
-- Requires: rumor_categories.sql, sensitivity_levels.sql
-- =====================================================

DROP TABLE IF EXISTS public.npc_rumors CASCADE;

CREATE TABLE public.npc_rumors (
    rumor_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    npc_id UUID NOT NULL REFERENCES public.npcs(npc_id) ON DELETE CASCADE,
    rumor_text TEXT NOT NULL,
    category_id UUID REFERENCES public.rumor_categories(category_id),
    accuracy_percentage INTEGER DEFAULT 50,
    sensitivity_level_id UUID REFERENCES public.sensitivity_levels(sensitivity_level_id),
    source_type VARCHAR(100),
    verification_difficulty INTEGER DEFAULT 5,
    consequences_if_shared TEXT,
    is_player_known BOOLEAN DEFAULT false,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CHECK(accuracy_percentage BETWEEN 0 AND 100),
    CHECK(verification_difficulty BETWEEN 1 AND 10)
);

CREATE INDEX idx_npc_rumors_npc ON public.npc_rumors (npc_id);
CREATE INDEX idx_npc_rumors_category ON public.npc_rumors (category_id);
CREATE INDEX idx_npc_rumors_sensitivity ON public.npc_rumors (sensitivity_level_id);
CREATE INDEX idx_npc_rumors_accuracy ON public.npc_rumors (accuracy_percentage);
CREATE INDEX idx_npc_rumors_player_known ON public.npc_rumors (is_player_known);
CREATE INDEX idx_npc_rumors_verification ON public.npc_rumors (verification_difficulty);

CREATE TRIGGER npc_rumors_updated_at_trigger
    BEFORE UPDATE ON public.npc_rumors
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

COMMENT ON TABLE public.npc_rumors IS 'Rumors, gossip, and information that NPCs possess';
COMMENT ON COLUMN public.npc_rumors.category_id IS 'Foreign key to rumor_categories table';
COMMENT ON COLUMN public.npc_rumors.accuracy_percentage IS 'How accurate this rumor is (0=completely false, 100=completely true)';
COMMENT ON COLUMN public.npc_rumors.sensitivity_level_id IS 'Foreign key to sensitivity_levels table';
COMMENT ON COLUMN public.npc_rumors.verification_difficulty IS 'How hard it is to verify this rumor (1=easy, 10=nearly impossible)';