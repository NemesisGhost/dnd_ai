-- =====================================================
-- Terrain Types Lookup Table
-- Simple lookup table for standardizing terrain descriptors
-- =====================================================

-- Terrain Types Lookup Table
DROP TABLE IF EXISTS public.terrain_types CASCADE;

CREATE TABLE public.terrain_types (
    terrain_type_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    typical_features TEXT, -- Common characteristics of this terrain
    movement_effects TEXT, -- How travel is affected
    resource_potential TEXT, -- What resources are typically found
    adventure_opportunities TEXT, -- Common adventure hooks for this terrain
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- =====================================================
-- Indexes for Performance
-- =====================================================

-- Terrain types indexes
CREATE INDEX idx_terrain_types_name ON public.terrain_types (name);

-- =====================================================
-- Triggers for Updated Timestamps
-- =====================================================

CREATE TRIGGER terrain_types_updated_at_trigger
    BEFORE UPDATE ON public.terrain_types
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

-- =====================================================
-- Comments
-- =====================================================

COMMENT ON TABLE public.terrain_types IS 'Standardized terrain type classifications';

-- =====================================================
-- Seed Data for Terrain Types
-- =====================================================

INSERT INTO public.terrain_types (name, description, typical_features, movement_effects, resource_potential) VALUES
('Mountains', 'High elevation rocky terrain with peaks and valleys', 'Snow-capped peaks, rocky cliffs, mountain passes, alpine meadows', 'Slow travel, requires mountaineering skills, altitude effects', 'Metals, gems, stone, rare herbs'),
('Forest', 'Heavily wooded areas with dense tree coverage', 'Tall trees, undergrowth, wildlife, streams, clearings', 'Reduced visibility, game trails, can get lost easily', 'Timber, game animals, herbs, mushrooms'),
('Plains', 'Flat or gently rolling grasslands', 'Open grasslands, few trees, wildflowers, gentle hills', 'Fast travel, good visibility, exposed to weather', 'Grain crops, grazing animals, wind power'),
('Desert', 'Arid regions with minimal precipitation', 'Sand dunes, rocky outcrops, oases, extreme temperatures', 'Water scarcity, extreme heat/cold, sandstorms', 'Salt, glass sand, rare gems, exotic spices'),
('Coastal', 'Areas along seas, oceans, or large lakes', 'Beaches, cliffs, tidal pools, harbors, sea caves', 'Marine travel options, tidal effects, storms', 'Fish, salt, pearls, seaweed, trade opportunities'),
('Swamp', 'Wetland areas with standing water and marsh', 'Murky water, cypress trees, moss, dangerous wildlife', 'Slow movement, disease risk, difficult navigation', 'Rare herbs, alchemical components, peat'),
('Hills', 'Rolling elevated terrain between plains and mountains', 'Gentle slopes, valleys, streams, scattered trees', 'Moderate travel difficulty, good defensive positions', 'Livestock grazing, vineyards, stone quarries'),
('Tundra', 'Cold, treeless plains with permanently frozen subsoil', 'Permafrost, low shrubs, caribou herds, harsh winters', 'Extreme cold, limited shelter, seasonal travel', 'Furs, ivory, rare cold-weather herbs'),
('River Valley', 'Low areas along major rivers', 'Fertile floodplains, river access, rich soil', 'Easy water travel, flood risks, bridge crossings', 'Agriculture, fresh water, river trade'),
('Badlands', 'Eroded terrain with exposed rock and minimal vegetation', 'Canyons, mesas, rock formations, sparse water', 'Difficult navigation, extreme temperatures, flash floods', 'Unusual minerals, fossils, hidden caves'),
('Jungle', 'Dense tropical forest with heavy precipitation', 'Thick canopy, vines, exotic wildlife, humidity', 'Very slow travel, disease, dangerous animals', 'Exotic woods, rare spices, medicinal plants'),
('Volcanic', 'Areas with active or dormant volcanic activity', 'Lava flows, ash fields, hot springs, fertile soil', 'Volcanic hazards, toxic gases, unstable ground', 'Obsidian, sulfur, geothermal energy, fertile farmland'),
('Arctic', 'Permanently frozen regions with ice and snow', 'Glaciers, ice sheets, blizzards, polar wildlife', 'Extreme cold, avalanche risk, white-out conditions', 'Ice fishing, seal hunting, whale oil'),
('Steppes', 'Semi-arid grasslands with scattered trees', 'Short grasses, occasional trees, nomadic herds', 'Good for mounted travel, seasonal water sources', 'Nomadic livestock, hardy grains, wind patterns'),
('Karst', 'Limestone terrain with caves and underground rivers', 'Sinkholes, cave systems, underground streams', 'Hidden passages, cave-ins, underground travel', 'Limestone, cave formations, underground water');