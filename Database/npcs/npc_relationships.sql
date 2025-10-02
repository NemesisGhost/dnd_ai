-- =====================================================
-- NPC Relationships Table
-- =====================================================

DROP TABLE IF EXISTS public.npc_relationships CASCADE;

CREATE TABLE public.npc_relationships (
    relationship_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    npc_id UUID NOT NULL REFERENCES public.npcs(npc_id) ON DELETE CASCADE,
    related_npc_id UUID REFERENCES public.npcs(npc_id) ON DELETE CASCADE, -- Can be NULL for external people
    related_npc_name VARCHAR(200), -- Name if related_npc_id is NULL (external person)
    relationship_type VARCHAR(100) NOT NULL, -- Family, Professional, Romantic, Enemy, etc.
    relationship_subtype VARCHAR(100), -- Father, Business Partner, Ex-lover, Rival, etc.
    relationship_strength INTEGER DEFAULT 5, -- 1-10 scale of relationship intensity
    relationship_status VARCHAR(50) DEFAULT 'Active', -- Active, Strained, Broken, Reconciled, etc.
    emotional_tone VARCHAR(50), -- Love, Hate, Respect, Fear, Indifference, etc.
    history_summary TEXT, -- How this relationship developed
    current_situation TEXT, -- Present state of the relationship
    shared_secrets TEXT, -- What they know together that others don't
    points_of_conflict TEXT, -- Areas where they disagree or have tension
    mutual_goals TEXT, -- Things they want to achieve together
    public_perception VARCHAR(100), -- How others view this relationship
    is_reciprocal BOOLEAN DEFAULT true, -- Whether the other party feels the same way
    is_public BOOLEAN DEFAULT true, -- Whether this relationship is publicly known
    is_player_known BOOLEAN DEFAULT false, -- Whether players know about this relationship
    last_interaction DATE, -- When they last met or communicated
    interaction_frequency VARCHAR(50), -- Daily, Weekly, Monthly, Rarely, etc.
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Ensure we have either an NPC reference or a name, not both
    CONSTRAINT check_related_identity CHECK (
        (related_npc_id IS NOT NULL AND related_npc_name IS NULL) OR
        (related_npc_id IS NULL AND related_npc_name IS NOT NULL)
    )
);

-- Indexes
CREATE INDEX idx_npc_relationships_npc ON public.npc_relationships (npc_id);
CREATE INDEX idx_npc_relationships_related ON public.npc_relationships (related_npc_id);
CREATE INDEX idx_npc_relationships_type ON public.npc_relationships (relationship_type);
CREATE INDEX idx_npc_relationships_subtype ON public.npc_relationships (relationship_subtype);
CREATE INDEX idx_npc_relationships_strength ON public.npc_relationships (relationship_strength DESC);
CREATE INDEX idx_npc_relationships_status ON public.npc_relationships (relationship_status);
CREATE INDEX idx_npc_relationships_public ON public.npc_relationships (is_public);
CREATE INDEX idx_npc_relationships_player_known ON public.npc_relationships (is_player_known);

-- Trigger for updated_at
CREATE TRIGGER npc_relationships_updated_at_trigger
    BEFORE UPDATE ON public.npc_relationships
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

-- Views removed as per requirements

-- Function to create reciprocal relationships
CREATE OR REPLACE FUNCTION create_reciprocal_relationship(
    p_npc_id_1 UUID,
    p_npc_id_2 UUID,
    p_relationship_type_1 VARCHAR(100),
    p_relationship_subtype_1 VARCHAR(100),
    p_relationship_type_2 VARCHAR(100) DEFAULT NULL,
    p_relationship_subtype_2 VARCHAR(100) DEFAULT NULL,
    p_strength INTEGER DEFAULT 5,
    p_history TEXT DEFAULT NULL
) RETURNS void AS $$
BEGIN
    -- Create first relationship
    INSERT INTO public.npc_relationships (
        npc_id, related_npc_id, relationship_type, relationship_subtype,
        relationship_strength, history_summary
    ) VALUES (
        p_npc_id_1, p_npc_id_2, p_relationship_type_1, p_relationship_subtype_1,
        p_strength, p_history
    );
    
    -- Create reciprocal relationship
    INSERT INTO public.npc_relationships (
        npc_id, related_npc_id, relationship_type, relationship_subtype,
        relationship_strength, history_summary
    ) VALUES (
        p_npc_id_2, p_npc_id_1, 
        COALESCE(p_relationship_type_2, p_relationship_type_1),
        COALESCE(p_relationship_subtype_2, p_relationship_subtype_1),
        p_strength, p_history
    );
END;
$$ LANGUAGE plpgsql;

-- Comments
COMMENT ON TABLE public.npc_relationships IS 'Relationships between NPCs and other people (NPCs or external)';
COMMENT ON COLUMN public.npc_relationships.relationship_strength IS 'Intensity of relationship (1=weak connection, 10=extremely significant)';
COMMENT ON COLUMN public.npc_relationships.related_npc_name IS 'Name of external person if not in NPC database';
COMMENT ON FUNCTION create_reciprocal_relationship IS 'Helper function to create two-way relationships between NPCs';

-- Sample relationship types for reference
INSERT INTO public.npc_relationships (npc_id, related_npc_name, relationship_type, relationship_subtype, relationship_strength, history_summary, is_player_known)
SELECT 
    npc_id, 
    'Sample External Person', 
    'Family', 
    'Father', 
    8, 
    'Raised the NPC and taught them their trade', 
    false
FROM public.npcs 
WHERE name = 'Marta Greenhill'
LIMIT 1;