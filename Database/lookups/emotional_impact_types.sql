-- =====================================================
-- Emotional Impact Types Lookup Table
-- =====================================================

DROP TABLE IF EXISTS public.emotional_impact_types CASCADE;

CREATE TABLE public.emotional_impact_types (
    impact_type_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(50) NOT NULL UNIQUE,
    description TEXT,
    typical_behaviors TEXT, -- How NPCs with this impact type might behave
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Insert emotional impact types
INSERT INTO public.emotional_impact_types (name, description, typical_behaviors) VALUES
('Positive', 'Events that brought joy, satisfaction, or beneficial outcomes', 'More confident, optimistic, willing to share the story, proud demeanor'),
('Negative', 'Events that caused pain, loss, or harmful consequences', 'Defensive, reluctant to discuss, may show signs of trauma or sadness'),
('Neutral', 'Events that were significant but emotionally balanced', 'Matter-of-fact discussion, neither proud nor ashamed, practical perspective'),
('Mixed', 'Events with both positive and negative emotional elements', 'Complex reactions, conflicted feelings, nuanced perspectives on the experience'),
('Transformative', 'Events that fundamentally changed their worldview or personality', 'Deep reflection, philosophical outlook, references to "before and after"'),
('Bittersweet', 'Events that brought both joy and sorrow simultaneously', 'Wistful demeanor, nostalgic tendencies, appreciates complexity of life'),
('Conflicted', 'Events they have unresolved feelings about', 'Uncertainty, may change opinion about the event, seeks validation or closure'),
('Suppressed', 'Events they actively try not to think about', 'Avoidance behaviors, deflection, may become agitated if pressed');

-- Indexes for performance
CREATE INDEX idx_emotional_impact_types_name ON public.emotional_impact_types (name);

-- Comments
COMMENT ON TABLE public.emotional_impact_types IS 'Types of emotional impact that significant events can have on NPCs';