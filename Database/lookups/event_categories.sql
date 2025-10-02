-- =====================================================
-- Event Categories Lookup Table
-- =====================================================

DROP TABLE IF EXISTS public.event_categories CASCADE;

CREATE TABLE public.event_categories (
    category_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    typical_impact_range VARCHAR(50), -- Low, Medium, High, Variable
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Insert event categories
INSERT INTO public.event_categories (name, description, typical_impact_range) VALUES
('Personal', 'Private life events affecting family and relationships', 'Variable'),
('Professional', 'Career milestones, job changes, and work-related events', 'Medium'),
('Traumatic', 'Deeply disturbing or harmful experiences', 'High'),
('Achievement', 'Major accomplishments and successes', 'Medium'),
('Loss', 'Deaths, departures, and significant losses', 'High'),
('Romance', 'Love affairs, marriages, and romantic relationships', 'Variable'),
('Educational', 'Learning experiences, training, and skill development', 'Medium'),
('Adventure', 'Dangerous exploits, quests, and heroic deeds', 'High'),
('Criminal', 'Illegal activities, arrests, and law enforcement encounters', 'High'),
('Religious', 'Spiritual experiences, divine encounters, and faith-related events', 'Variable'),
('Political', 'Government involvement, political upheaval, and civic events', 'Medium'),
('Military', 'Combat experiences, war, and military service', 'High'),
('Magical', 'Supernatural experiences and magical encounters', 'Variable'),
('Social', 'Community events, social status changes, and public recognition', 'Medium'),
('Financial', 'Economic gains, losses, and financial turning points', 'Medium'),
('Health', 'Illness, injury, recovery, and medical experiences', 'Variable'),
('Discovery', 'Finding secrets, uncovering truths, and making revelations', 'Medium'),
('Betrayal', 'Trust broken by friends, family, or allies', 'High'),
('Rescue', 'Being saved from danger or saving others', 'Medium'),
('Exile', 'Banishment, forced departure, or voluntary isolation', 'High');

-- Indexes for performance
CREATE INDEX idx_event_categories_name ON public.event_categories (name);
CREATE INDEX idx_event_categories_impact_range ON public.event_categories (typical_impact_range);

-- Comments
COMMENT ON TABLE public.event_categories IS 'Categories for classifying significant life events';