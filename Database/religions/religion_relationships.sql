-- =====================================================
-- Religion Relationships Many-to-Many Table
-- =====================================================

DROP TABLE IF EXISTS public.religion_relationships CASCADE;

CREATE TABLE public.religion_relationships (
    religion_relationship_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    religion_id UUID NOT NULL REFERENCES public.religions(religion_id) ON DELETE CASCADE,
    related_religion_id UUID NOT NULL REFERENCES public.religions(religion_id) ON DELETE CASCADE,
    
    -- Relationship details
    relationship_type VARCHAR(50) NOT NULL, -- Allied, Rival, Enemy, Neutral, Tolerant, Competitive, Cooperative
    relationship_strength VARCHAR(50) DEFAULT 'Moderate', -- Weak, Moderate, Strong, Absolute
    relationship_status VARCHAR(50) DEFAULT 'Active', -- Active, Historical, Dormant, Changing
    
    -- Relationship context
    relationship_basis TEXT, -- Why this relationship exists (doctrine, history, politics, etc.)
    public_knowledge BOOLEAN DEFAULT TRUE, -- Whether this relationship is publicly known
    formal_agreement BOOLEAN DEFAULT FALSE, -- Whether there's an official alliance/treaty
    mutual_recognition BOOLEAN DEFAULT TRUE, -- Whether both religions acknowledge this relationship
    
    -- Historical context
    relationship_start_date DATE, -- When this relationship began
    relationship_history TEXT, -- How the relationship has evolved
    key_events TEXT, -- Important events that shaped this relationship
    
    -- Current interaction
    cooperation_areas TEXT, -- Areas where they work together (if allied)
    conflict_areas TEXT, -- Areas of disagreement or competition
    diplomatic_status VARCHAR(50), -- Formal, Informal, Strained, Hostile, Cordial
    regular_interaction BOOLEAN DEFAULT FALSE, -- Whether they interact regularly
    
    -- Metadata
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Ensure unique religion pairs and prevent self-relationships
    UNIQUE(religion_id, related_religion_id),
    CHECK (religion_id != related_religion_id)
);

-- Indexes for efficient queries
CREATE INDEX idx_religion_relationships_religion ON public.religion_relationships (religion_id);
CREATE INDEX idx_religion_relationships_related ON public.religion_relationships (related_religion_id);
CREATE INDEX idx_religion_relationships_type ON public.religion_relationships (relationship_type);
CREATE INDEX idx_religion_relationships_strength ON public.religion_relationships (relationship_strength);
CREATE INDEX idx_religion_relationships_status ON public.religion_relationships (relationship_status);
CREATE INDEX idx_religion_relationships_diplomatic ON public.religion_relationships (diplomatic_status);

-- Trigger for updated_at
CREATE TRIGGER religion_relationships_updated_at_trigger
    BEFORE UPDATE ON public.religion_relationships
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

-- Comments
COMMENT ON TABLE public.religion_relationships IS 'Relationships between different religions (alliances, rivalries, etc.)';
COMMENT ON COLUMN public.religion_relationships.relationship_type IS 'Type of relationship between the religions';
COMMENT ON COLUMN public.religion_relationships.mutual_recognition IS 'Whether both religions acknowledge this relationship';
COMMENT ON COLUMN public.religion_relationships.formal_agreement IS 'Whether there is an official treaty or agreement';

-- Sample relationships
-- Note: These INSERTs will only work if the referenced religions exist
/*
INSERT INTO public.religion_relationships (religion_id, related_religion_id, relationship_type, relationship_strength, relationship_basis, formal_agreement) VALUES
((SELECT religion_id FROM public.religions WHERE name = 'Order of the Eternal Flame'), 
 (SELECT religion_id FROM public.religions WHERE name = 'Pantheon of the Seven Stars'), 
 'Allied', 'Moderate', 'Both oppose chaotic evil forces and share similar moral codes', TRUE),
((SELECT religion_id FROM public.religions WHERE name = 'Order of the Eternal Flame'), 
 (SELECT religion_id FROM public.religions WHERE name = 'The Old Ways'), 
 'Tolerant', 'Weak', 'Different approaches but both value protection and balance', FALSE),
((SELECT religion_id FROM public.religions WHERE name = 'The Old Ways'), 
 (SELECT religion_id FROM public.religions WHERE name = 'Pantheon of the Seven Stars'), 
 'Competitive', 'Moderate', 'Disagree on intervention in natural cycles vs. divine will', FALSE);
*/