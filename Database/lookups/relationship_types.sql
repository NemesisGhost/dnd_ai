-- =====================================================
-- Relationship Types Lookup Table
-- =====================================================

DROP TABLE IF EXISTS public.relationship_types CASCADE;

CREATE TABLE public.relationship_types (
    type_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

INSERT INTO public.relationship_types (name, description) VALUES
-- Competition types
('Direct Competition', 'Direct competitors offering similar products/services to same customers'),
('Indirect Competition', 'Competitors serving similar needs but with different approaches'),
('Seasonal Competition', 'Competition that varies by season or time period'),
('Regional Competition', 'Competition limited to specific geographic areas'),
-- Alliance types
('Partnership', 'General business partnership arrangement'),
('Referral Partnership', 'Businesses that refer customers to each other'),
('Supply Chain Alliance', 'Supplier-customer relationship or supply chain partnership'),
('Joint Venture', 'Shared business venture or project'),
('Marketing Alliance', 'Collaborative marketing and promotional arrangements'),
('Resource Sharing', 'Sharing of facilities, equipment, or other resources'),
-- Neutral/Mixed types
('Supplier Relationship', 'Standard supplier-customer relationship'),
('Professional Network', 'Professional connections without formal business ties'),
('Historical Relationship', 'Past business relationship that may influence current interactions');

CREATE INDEX idx_relationship_types_name ON public.relationship_types (name);

CREATE TRIGGER relationship_types_updated_at_trigger
    BEFORE UPDATE ON public.relationship_types
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

COMMENT ON TABLE public.relationship_types IS 'Lookup table for specific types of business relationships';
COMMENT ON COLUMN public.relationship_types.name IS 'Specific type of relationship (Direct Competition, Partnership, etc.)';