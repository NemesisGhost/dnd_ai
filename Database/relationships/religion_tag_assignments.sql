-- =====================================================
-- Religion Tag Assignments Junction Table
-- =====================================================

DROP TABLE IF EXISTS public.religion_tag_assignments CASCADE;

CREATE TABLE public.religion_tag_assignments (
    assignment_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    religion_id UUID NOT NULL REFERENCES public.religions(religion_id) ON DELETE CASCADE,
    tag_id UUID NOT NULL REFERENCES public.tags(tag_id) ON DELETE CASCADE,
    assigned_by VARCHAR(100) DEFAULT 'system',
    assigned_date TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    notes TEXT,
    UNIQUE(religion_id, tag_id)
);

-- Indexes for religion tag assignments
CREATE INDEX idx_religion_tag_assignments_religion ON public.religion_tag_assignments (religion_id);
CREATE INDEX idx_religion_tag_assignments_tag ON public.religion_tag_assignments (tag_id);
CREATE INDEX idx_religion_tag_assignments_assigned_by ON public.religion_tag_assignments (assigned_by);

-- Comments
COMMENT ON TABLE public.religion_tag_assignments IS 'Many-to-many relationship between religions and tags';
COMMENT ON COLUMN public.religion_tag_assignments.assigned_by IS 'Who or what system assigned this tag';
COMMENT ON COLUMN public.religion_tag_assignments.notes IS 'Optional context for why this tag was assigned';