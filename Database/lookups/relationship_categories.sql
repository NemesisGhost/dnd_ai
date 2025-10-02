-- =====================================================
-- Relationship Categories Lookup Table
-- =====================================================

DROP TABLE IF EXISTS public.relationship_categories CASCADE;

CREATE TABLE public.relationship_categories (
    category_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(50) NOT NULL UNIQUE,
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

INSERT INTO public.relationship_categories (name, description) VALUES
('Competition', 'Businesses competing for the same market or customers'),
('Alliance', 'Businesses working together in partnership or collaboration'),
('Neutral', 'Businesses with no significant competitive or collaborative relationship'),
('Mixed', 'Complex relationships with both competitive and collaborative elements');

CREATE INDEX idx_relationship_categories_name ON public.relationship_categories (name);

CREATE TRIGGER relationship_categories_updated_at_trigger
    BEFORE UPDATE ON public.relationship_categories
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

COMMENT ON TABLE public.relationship_categories IS 'Lookup table for high-level business relationship categories';
COMMENT ON COLUMN public.relationship_categories.name IS 'Category name (Competition, Alliance, Neutral, Mixed)';