-- =====================================================
-- Resources Main Table - Natural Resources, Materials, and Assets
-- Universal resource system for nations, organizations, and locations
-- =====================================================

DROP TABLE IF EXISTS public.resources CASCADE;

CREATE TABLE public.resources (
    -- Primary identification
    resource_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    
    -- Resource details
    name VARCHAR(200) NOT NULL UNIQUE,
    resource_type VARCHAR(100) NOT NULL, -- Natural, Financial, Information, Political, Military, Magical, Material, etc.
    category VARCHAR(100), -- More specific categorization (Metals, Gems, Crops, etc.)
    description TEXT,
    
    -- Physical characteristics
    rarity VARCHAR(50), -- Common, Uncommon, Rare, Very Rare, Legendary
    extraction_difficulty VARCHAR(50), -- Easy, Moderate, Difficult, Extreme
    processing_requirements TEXT, -- What's needed to make it useful
    storage_requirements TEXT, -- How it needs to be stored
    
    -- Economic aspects
    base_value_description VARCHAR(100), -- Cheap, Moderate, Expensive, Priceless
    market_volatility VARCHAR(50), -- Stable, Fluctuating, Volatile, Unpredictable
    trade_restrictions TEXT, -- Legal or practical limitations on trade
    
    -- Usage and applications
    common_uses TEXT, -- What it's typically used for
    magical_properties TEXT, -- Any magical aspects or uses
    crafting_applications TEXT, -- What can be made from it
    
    -- Metadata
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- =====================================================
-- Indexes
-- =====================================================

CREATE INDEX idx_resources_name ON public.resources (name);
CREATE INDEX idx_resources_type ON public.resources (resource_type);
CREATE INDEX idx_resources_category ON public.resources (category);
CREATE INDEX idx_resources_rarity ON public.resources (rarity);

-- =====================================================
-- Triggers
-- =====================================================

CREATE TRIGGER resources_updated_at_trigger
    BEFORE UPDATE ON public.resources
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

-- =====================================================
-- Comments
-- =====================================================

COMMENT ON TABLE public.resources IS 'Universal resources table for natural resources, materials, and assets';
COMMENT ON COLUMN public.resources.resource_type IS 'Natural, Financial, Information, Political, Military, Magical, Material, etc.';

-- =====================================================
-- Seed Data for Common Resources
-- =====================================================

INSERT INTO public.resources (name, resource_type, category, description, rarity, common_uses) VALUES
-- Natural Resources - Metals
('Iron Ore', 'Natural', 'Metals', 'Common metal ore used for tools, weapons, and construction', 'Common', 'Weapons, tools, construction, horseshoes'),
('Gold', 'Natural', 'Precious Metals', 'Precious metal used for currency and luxury items', 'Uncommon', 'Currency, jewelry, magical components'),
('Silver', 'Natural', 'Precious Metals', 'Precious metal with both monetary and practical uses', 'Uncommon', 'Currency, jewelry, anti-undead weapons, mirrors'),
('Copper', 'Natural', 'Metals', 'Versatile metal for tools and alloys', 'Common', 'Tools, pipes, coins, bronze alloys'),
('Tin', 'Natural', 'Metals', 'Metal used primarily for alloys', 'Common', 'Bronze alloy, pewter, preservation'),

-- Natural Resources - Gems
('Diamonds', 'Natural', 'Gems', 'Extremely hard precious stones', 'Rare', 'Jewelry, cutting tools, magical components'),
('Rubies', 'Natural', 'Gems', 'Red precious stones with magical properties', 'Rare', 'Jewelry, fire magic components, scrying'),
('Sapphires', 'Natural', 'Gems', 'Blue precious stones', 'Rare', 'Jewelry, water magic components, divination'),
('Emeralds', 'Natural', 'Gems', 'Green precious stones associated with nature', 'Rare', 'Jewelry, nature magic components, healing'),

-- Natural Resources - Materials
('Timber', 'Natural', 'Materials', 'Wood from various trees', 'Common', 'Construction, ships, tools, fuel'),
('Stone', 'Natural', 'Materials', 'Various types of building stone', 'Common', 'Construction, fortifications, sculptures'),
('Clay', 'Natural', 'Materials', 'Moldable earth material', 'Common', 'Pottery, bricks, art, alchemy'),
('Salt', 'Natural', 'Materials', 'Essential mineral for preservation and flavor', 'Common', 'Food preservation, trade, alchemy'),

-- Natural Resources - Agricultural
('Grain', 'Natural', 'Agricultural', 'Various cereal crops', 'Common', 'Food, bread, beer, livestock feed'),
('Livestock', 'Natural', 'Agricultural', 'Cattle, sheep, pigs, and other farm animals', 'Common', 'Food, leather, wool, transportation'),
('Spices', 'Natural', 'Agricultural', 'Exotic flavoring and preserving agents', 'Uncommon', 'Cooking, preservation, medicine, trade'),
('Medicinal Herbs', 'Natural', 'Agricultural', 'Plants with healing properties', 'Uncommon', 'Medicine, alchemy, magical components'),

-- Magical Resources
('Mithril', 'Magical', 'Metals', 'Legendary lightweight magical metal', 'Legendary', 'Elite weapons, magical items, armor'),
('Adamantine', 'Magical', 'Metals', 'Extremely hard magical metal', 'Very Rare', 'Weapons, armor, permanent structures'),
('Arcane Crystals', 'Magical', 'Materials', 'Crystals that store and channel magical energy', 'Rare', 'Magic items, spell components, power sources'),
('Dragon Scales', 'Magical', 'Materials', 'Scales from dragons with inherent magic', 'Very Rare', 'Armor, shields, magical protection'),

-- Information Resources
('Ancient Knowledge', 'Information', 'Knowledge', 'Lost lore and forgotten secrets', 'Rare', 'Research, magical advancement, historical insight'),
('Trade Routes', 'Information', 'Intelligence', 'Knowledge of profitable and safe trade paths', 'Uncommon', 'Commerce, economic advantage, travel'),
('Military Intelligence', 'Information', 'Intelligence', 'Information about enemy forces and plans', 'Rare', 'Military strategy, defense, espionage'),

-- Financial Resources
('Gold Reserves', 'Financial', 'Currency', 'Stored wealth in gold coins and bars', 'Uncommon', 'Trade, military funding, infrastructure'),
('Trade Agreements', 'Financial', 'Contracts', 'Formal trading partnerships and deals', 'Uncommon', 'Economic stability, resource access, diplomacy');