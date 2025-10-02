-- =====================================================
-- Settlement Religious Festivals Child Table
-- =====================================================

DROP TABLE IF EXISTS public.settlement_religious_festivals CASCADE;

CREATE TABLE public.settlement_religious_festivals (
    festival_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    settlement_religion_id UUID NOT NULL REFERENCES public.settlement_religions(settlement_religion_id) ON DELETE CASCADE,
    
    -- Festival details
    festival_name VARCHAR(200) NOT NULL,
    festival_type VARCHAR(50), -- Celebration, Observance, Fast, Pilgrimage, Ceremony, Seasonal
    celebration_date VARCHAR(100), -- When it occurs (e.g., "Spring Equinox", "Third week of Harvest Month")
    duration VARCHAR(50), -- Single day, Three days, Week-long, etc.
    
    -- Local adaptation
    local_significance TEXT, -- What this festival means specifically in this settlement
    local_traditions TEXT, -- How this settlement celebrates differently
    participation_rate VARCHAR(50), -- All Adherents, Most Adherents, Clergy Only, Optional, Mixed Community
    community_involvement BOOLEAN DEFAULT FALSE, -- Whether non-adherents participate
    
    -- Celebration details
    main_activities TEXT, -- Primary festival activities
    special_foods TEXT, -- Traditional foods for this festival
    decorations TEXT, -- Festival decorations and displays
    ceremonial_items TEXT, -- Special objects used
    public_events TEXT, -- Public ceremonies or events
    
    -- Economic and social impact
    economic_impact VARCHAR(50), -- None, Minor, Moderate, Major, Significant
    visitor_attraction BOOLEAN DEFAULT FALSE, -- Whether it draws visitors from other settlements
    business_closure BOOLEAN DEFAULT FALSE, -- Whether businesses close for the festival
    
    -- Organization
    organizers VARCHAR(200), -- Who organizes the festival (clergy, community, government)
    funding_source VARCHAR(100), -- Temple, Community, Government, Mixed, Self-funded
    volunteer_requirements TEXT, -- What help is needed from community
    
    -- Status and history
    festival_status VARCHAR(50) DEFAULT 'Active', -- Active, Declining, Growing, Suspended, Historical
    first_celebrated_year INTEGER, -- When this festival started in this settlement
    historical_changes TEXT, -- How the festival has evolved locally
    
    -- Metadata
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Ensure unique festival names within each settlement-religion pair
    UNIQUE(settlement_religion_id, festival_name)
);

-- Indexes for efficient queries
CREATE INDEX idx_settlement_religious_festivals_settlement_religion ON public.settlement_religious_festivals (settlement_religion_id);
CREATE INDEX idx_settlement_religious_festivals_type ON public.settlement_religious_festivals (festival_type);
CREATE INDEX idx_settlement_religious_festivals_status ON public.settlement_religious_festivals (festival_status);
CREATE INDEX idx_settlement_religious_festivals_participation ON public.settlement_religious_festivals (participation_rate);
CREATE INDEX idx_settlement_religious_festivals_impact ON public.settlement_religious_festivals (economic_impact);
CREATE INDEX idx_settlement_religious_festivals_name_search ON public.settlement_religious_festivals USING gin(to_tsvector('english', festival_name));

-- Trigger for updated_at
CREATE TRIGGER settlement_religious_festivals_updated_at_trigger
    BEFORE UPDATE ON public.settlement_religious_festivals
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

-- Comments
COMMENT ON TABLE public.settlement_religious_festivals IS 'Religious festivals and celebrations specific to settlement-religion combinations';
COMMENT ON COLUMN public.settlement_religious_festivals.local_significance IS 'What this festival means specifically in this settlement';
COMMENT ON COLUMN public.settlement_religious_festivals.community_involvement IS 'Whether non-adherents participate in the festival';
COMMENT ON COLUMN public.settlement_religious_festivals.visitor_attraction IS 'Whether the festival draws visitors from other settlements';

-- Sample data
-- Note: These INSERTs will only work if the referenced settlement_religions exist
/*
INSERT INTO public.settlement_religious_festivals (settlement_religion_id, festival_name, festival_type, celebration_date, duration, local_significance, participation_rate, community_involvement, main_activities, economic_impact) VALUES
((SELECT settlement_religion_id FROM public.settlement_religions sr 
  JOIN public.settlements s ON sr.settlement_id = s.settlement_id 
  JOIN public.religions r ON sr.religion_id = r.religion_id 
  WHERE s.name = 'Millbrook' AND r.name = 'Order of the Eternal Flame'), 
 'Festival of Dawn Light', 'Celebration', 'Summer Solstice', 'Three days', 
 'Celebrates the longest day and blessing of crops', 'All Adherents', TRUE,
 'Dawn prayers, community feast, blessing of fields, evening bonfires', 'Major'),
((SELECT settlement_religion_id FROM public.settlement_religions sr 
  JOIN public.settlements s ON sr.settlement_id = s.settlement_id 
  JOIN public.religions r ON sr.religion_id = r.religion_id 
  WHERE s.name = 'Millbrook' AND r.name = 'The Old Ways'), 
 'Harvest Moon Gathering', 'Seasonal', 'Autumn Equinox', 'Single day', 
 'Thanks for successful harvest and preparation for winter', 'Most Adherents', TRUE,
 'Grain offerings, communal feast with harvest foods, storytelling', 'Significant');
*/