-- =====================================================
-- NPC Tag Assignments Relationship Table
-- =====================================================

DROP TABLE IF EXISTS public.npc_tag_assignments CASCADE;

CREATE TABLE public.npc_tag_assignments (
    assignment_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    npc_id UUID NOT NULL REFERENCES public.npcs(npc_id) ON DELETE CASCADE,
    tag_id UUID NOT NULL REFERENCES public.tags(tag_id) ON DELETE CASCADE,
    assigned_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    assigned_by VARCHAR(100), -- Who assigned this tag (DM, system, player, etc.)
    notes TEXT, -- Additional context for why this tag applies
    UNIQUE(npc_id, tag_id)
);

-- Indexes for performance
CREATE INDEX idx_npc_tags_npc ON public.npc_tag_assignments (npc_id);
CREATE INDEX idx_npc_tags_tag ON public.npc_tag_assignments (tag_id);
CREATE INDEX idx_npc_tags_assigned_at ON public.npc_tag_assignments (assigned_at);

-- Comments
COMMENT ON TABLE public.npc_tag_assignments IS 'Many-to-many relationship linking NPCs to descriptive tags';
COMMENT ON COLUMN public.npc_tag_assignments.assigned_by IS 'Source of tag assignment for audit purposes';