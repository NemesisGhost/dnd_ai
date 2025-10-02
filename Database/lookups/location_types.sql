-- =====================================================
-- Location Types Lookup Table
-- =====================================================

DROP TABLE IF EXISTS public.location_types CASCADE;

-- Location Types Lookup Table
CREATE TABLE public.location_types (
    location_type_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL UNIQUE,
    category VARCHAR(50) NOT NULL, -- Settlement, Geographic, Landmark, Territory, Structure, etc.
    description TEXT,
    typical_scale VARCHAR(50), -- Personal, Local, Regional, National, Continental, Global
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- =====================================================
-- Indexes for Performance
-- =====================================================

-- Location types indexes
CREATE INDEX idx_location_types_category ON public.location_types (category);

-- =====================================================
-- Triggers
-- =====================================================

-- Trigger for updated_at on location_types
CREATE TRIGGER location_types_updated_at_trigger
    BEFORE UPDATE ON public.location_types
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

-- =====================================================
-- Comments
-- =====================================================

COMMENT ON TABLE public.location_types IS 'Lookup table for different types of locations (settlements, landmarks, territories, etc.)';

-- =====================================================
-- Seed Data for Location Types
-- =====================================================

INSERT INTO public.location_types (name, category, description, typical_scale) VALUES
-- Settlement types
('City', 'Settlement', 'Large urban settlement with significant population and infrastructure', 'Regional'),
('Town', 'Settlement', 'Medium-sized settlement with local governance and markets', 'Local'),
('Village', 'Settlement', 'Small rural settlement with basic amenities', 'Local'),
('Hamlet', 'Settlement', 'Tiny settlement, often just a few buildings', 'Local'),
('Metropolis', 'Settlement', 'Massive urban center, often a capital or major trade hub', 'National'),
('Outpost', 'Settlement', 'Small fortified settlement, often on frontiers', 'Local'),
('Trading Post', 'Settlement', 'Commercial settlement focused on trade', 'Local'),
('Fort', 'Settlement', 'Military settlement or fortification', 'Local'),

-- Geographic regions
('Region', 'Geographic', 'Large geographic or political region', 'Regional'),
('Province', 'Geographic', 'Political subdivision of a nation', 'Regional'),
('Territory', 'Geographic', 'Claimed or governed area', 'Regional'),
('Wilderness', 'Geographic', 'Untamed natural area', 'Regional'),
('Forest', 'Geographic', 'Large wooded area', 'Local'),
('Mountain Range', 'Geographic', 'Chain of mountains', 'Regional'),
('Valley', 'Geographic', 'Low area between hills or mountains', 'Local'),
('Plains', 'Geographic', 'Large flat grassland area', 'Regional'),
('Desert', 'Geographic', 'Arid, sandy or rocky wasteland', 'Regional'),
('Swamp', 'Geographic', 'Wetland area with standing water', 'Local'),
('Coast', 'Geographic', 'Area along a sea or ocean', 'Regional'),
('Island', 'Geographic', 'Land surrounded by water', 'Local'),
('Peninsula', 'Geographic', 'Land nearly surrounded by water', 'Local'),

-- Landmarks and structures
('Landmark', 'Landmark', 'Notable natural or constructed feature', 'Local'),
('Monument', 'Landmark', 'Constructed memorial or significant structure', 'Local'),
('Ruins', 'Landmark', 'Remains of ancient or destroyed structures', 'Local'),
('Temple', 'Structure', 'Religious building or complex', 'Local'),
('Castle', 'Structure', 'Fortified residence or stronghold', 'Local'),
('Tower', 'Structure', 'Tall defensive or magical structure', 'Local'),
('Bridge', 'Structure', 'Crossing over water or chasm', 'Local'),
('Road', 'Structure', 'Constructed travel route', 'Regional'),
('Mine', 'Structure', 'Resource extraction site', 'Local'),
('Dungeon', 'Structure', 'Underground complex or prison', 'Local'),

-- Magical and supernatural
('Magical Site', 'Supernatural', 'Location with magical properties or significance', 'Local'),
('Portal', 'Supernatural', 'Magical gateway between locations', 'Local'),
('Ley Line', 'Supernatural', 'Magical energy current', 'Regional'),
('Sacred Grove', 'Supernatural', 'Magically or religiously significant natural area', 'Local'),
('Cursed Land', 'Supernatural', 'Area under magical curse or blight', 'Local'),

-- Water features
('River', 'Geographic', 'Flowing waterway', 'Regional'),
('Lake', 'Geographic', 'Large body of standing water', 'Local'),
('Sea', 'Geographic', 'Large body of salt water', 'Continental'),
('Ocean', 'Geographic', 'Vast body of salt water', 'Global'),
('Bay', 'Geographic', 'Body of water partially enclosed by land', 'Local'),
('Harbor', 'Structure', 'Sheltered port area for ships', 'Local'),

-- Underground
('Cave', 'Geographic', 'Natural underground opening', 'Local'),
('Cavern System', 'Geographic', 'Network of connected underground spaces', 'Local'),
('Underground City', 'Settlement', 'Subterranean urban settlement', 'Local'),

-- Other
('Battlefield', 'Landmark', 'Site of significant military conflict', 'Local'),
('Cemetery', 'Landmark', 'Burial ground', 'Local'),
('Market', 'Structure', 'Commercial trading area', 'Local'),
('Campus', 'Structure', 'Educational or organizational complex', 'Local'),
('Estate', 'Structure', 'Large private property with buildings', 'Local');