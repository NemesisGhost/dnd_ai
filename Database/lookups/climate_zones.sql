-- =====================================================
-- Climate Zones Lookup Table
-- Simple lookup table for standardizing climate descriptors
-- =====================================================

-- Climate Zones Lookup Table
DROP TABLE IF EXISTS public.climate_zones CASCADE;

CREATE TABLE public.climate_zones (
    climate_zone_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    temperature_range TEXT, -- Typical temperature characteristics
    precipitation_pattern TEXT, -- Rain/snow patterns
    seasonal_variations TEXT, -- How seasons change
    survival_challenges TEXT, -- Environmental hazards or difficulties
    flora_fauna_notes TEXT, -- Typical plants and animals
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- =====================================================
-- Indexes for Performance
-- =====================================================

-- Climate zones indexes
CREATE INDEX idx_climate_zones_name ON public.climate_zones (name);

-- =====================================================
-- Triggers for Updated Timestamps
-- =====================================================

CREATE TRIGGER climate_zones_updated_at_trigger
    BEFORE UPDATE ON public.climate_zones
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

-- =====================================================
-- Comments
-- =====================================================

COMMENT ON TABLE public.climate_zones IS 'Standardized climate zone classifications';

-- =====================================================
-- Seed Data for Climate Zones
-- =====================================================

INSERT INTO public.climate_zones (name, description, temperature_range, precipitation_pattern, seasonal_variations) VALUES
('Tropical', 'Hot and humid year-round with heavy rainfall', 'Consistently warm 70-90°F (21-32°C)', 'Heavy rainfall, wet and dry seasons', 'Minimal temperature variation, monsoon seasons'),
('Subtropical', 'Warm temperatures with mild winters', 'Warm summers 70-85°F, mild winters 40-65°F', 'Moderate to heavy rainfall, possible dry season', 'Distinct but mild seasons, hurricane/typhoon season'),
('Temperate', 'Moderate temperatures with distinct seasons', 'Warm summers 60-80°F, cold winters 20-45°F', 'Moderate rainfall throughout year', 'Four distinct seasons with significant variation'),
('Continental', 'Large temperature variations between seasons', 'Hot summers 70-90°F, very cold winters -10-30°F', 'Moderate rainfall, potential for drought', 'Extreme seasonal variation, harsh winters'),
('Mediterranean', 'Warm dry summers and mild wet winters', 'Warm summers 70-85°F, mild winters 45-65°F', 'Dry summers, wet winters', 'Two main seasons: wet winter, dry summer'),
('Arid', 'Very low precipitation with extreme temperatures', 'Hot days 85-115°F, cold nights 40-70°F', 'Minimal rainfall, less than 10 inches per year', 'Large daily temperature swings, minimal seasonal change'),
('Semi-Arid', 'Low precipitation with grassland conditions', 'Hot summers 75-95°F, cool winters 30-55°F', 'Low rainfall, 10-20 inches per year', 'Distinct seasons, drought-prone'),
('Subarctic', 'Short cool summers and long harsh winters', 'Cool summers 50-70°F, frigid winters -30-10°F', 'Low to moderate precipitation, mostly snow', 'Very long winters, brief summers'),
('Arctic', 'Permanently cold with minimal precipitation', 'Cool summers 32-50°F, extreme winters -40--10°F', 'Very low precipitation, mostly snow', 'Polar night and midnight sun, permafrost'),
('Alpine', 'High altitude climate with thin air', 'Cool temperatures, varies by elevation', 'Moderate precipitation, heavy snow at elevation', 'Altitude-dependent, extreme weather changes'),
('Oceanic', 'Moderate temperatures influenced by nearby ocean', 'Mild temperatures 50-70°F year-round', 'High precipitation, frequent fog and mist', 'Small temperature variation, wet and stormy'),
('Monsoon', 'Distinct wet and dry seasons with heavy rains', 'Warm to hot 70-95°F year-round', 'Extreme seasonal variation: very wet/very dry', 'Dramatic seasonal precipitation changes'),
('Highland', 'Mountain climate varying by elevation and exposure', 'Varies greatly by altitude and aspect', 'Orographic precipitation, rain shadows', 'Microclimates, altitude-dependent seasons'),
('Polar', 'Extremely cold with ice and snow year-round', 'Always below freezing, summers 20-40°F', 'Very low precipitation, all snow', 'Polar day/night cycles, brief "summer" thaw'),
('Savanna', 'Hot climate with distinct wet and dry seasons', 'Hot year-round 75-95°F', 'Distinct wet/dry seasons, 20-50 inches annually', 'Pronounced dry season, wildlife migrations');