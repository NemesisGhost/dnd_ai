-- =====================================================
-- Current Relevance Levels Lookup Table
-- =====================================================

DROP TABLE IF EXISTS public.current_relevance_levels CASCADE;

CREATE TABLE public.current_relevance_levels (
    relevance_level_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(50) NOT NULL UNIQUE,
    description TEXT,
    behavioral_indicators TEXT, -- How this relevance level manifests in behavior
    conversation_likelihood VARCHAR(50), -- How likely they are to bring this up
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Insert current relevance levels
INSERT INTO public.current_relevance_levels (name, description, behavioral_indicators, conversation_likelihood) VALUES
('High', 'Event still actively influences daily decisions and behavior', 'References it frequently, shapes current choices, affects reactions to similar situations', 'Very Likely'),
('Moderate', 'Event has ongoing influence but is not dominating current life', 'Occasional references, influences some decisions, comes up in relevant contexts', 'Moderately Likely'),
('Low', 'Event is part of their history but rarely affects current behavior', 'Rarely mentioned unless directly asked, minimal impact on current decisions', 'Unlikely'),
('Resolved', 'Event has been processed and integrated, no longer actively troubling', 'Can discuss calmly, lessons learned have been integrated, closure achieved', 'Contextual'),
('Dormant', 'Event is not currently relevant but could become so under certain circumstances', 'No current impact, but specific triggers could reactivate its importance', 'Very Unlikely'),
('Escalating', 'Event is becoming more relevant or problematic over time', 'Increasing preoccupation, growing impact on behavior, may seek resolution', 'Increasingly Likely'),
('Cyclical', 'Event becomes relevant at certain times or anniversaries', 'Periodic relevance, seasonal or anniversary-based impact, predictable patterns', 'Seasonally Likely'),
('Suppressed', 'Event is being actively ignored despite its potential relevance', 'Deliberate avoidance, denial of impact, may manifest in unconscious behaviors', 'Avoided');

-- Indexes for performance
CREATE INDEX idx_current_relevance_levels_name ON public.current_relevance_levels (name);
CREATE INDEX idx_current_relevance_levels_likelihood ON public.current_relevance_levels (conversation_likelihood);

-- Comments
COMMENT ON TABLE public.current_relevance_levels IS 'Levels of current relevance that past events have on NPCs present behavior';