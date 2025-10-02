-- =====================================================
-- Services Table - Generic Services Available in the World
-- Requires: service_categories.sql, skill_levels.sql, rarity_levels.sql, cost_types.sql
-- =====================================================

DROP TABLE IF EXISTS public.services CASCADE;

CREATE TABLE public.services (
    service_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    service_category_id UUID NOT NULL REFERENCES public.service_categories(category_id) ON DELETE CASCADE,
    
    -- Service Identity
    service_name VARCHAR(200) NOT NULL,
    service_description TEXT,
    
    -- Service Characteristics
    cost_type_id UUID REFERENCES public.cost_types(cost_type_id), -- Type of cost/payment for this service
    cost_details TEXT, -- Specific details about cost (amounts, ranges, etc.)
    base_quality_level INTEGER DEFAULT 5, -- 1-10 scale of typical service quality
    typical_time_required VARCHAR(100), -- How long the service typically takes
    required_skill_level INTEGER DEFAULT 5, -- 1-10 minimum skill level needed to provide
    success_rate_range VARCHAR(50), -- "70-90%", "Variable", "Nearly certain", etc.
    
    -- Service Requirements and Limitations
    prerequisites TEXT, -- What's typically needed before this service can be provided
    equipment_required TEXT, -- Special tools or materials commonly needed
    location_requirements TEXT, -- Where this service must be performed
    legal_status VARCHAR(50) DEFAULT 'Legal', -- Legal, Restricted, Illegal, Variable
    
    -- Service Complexity and Risk
    complexity_level INTEGER DEFAULT 5, -- 1-10 how difficult this service is to provide
    risk_level INTEGER DEFAULT 1, -- 1-10 how dangerous/risky this service is
    potential_side_effects TEXT, -- Common complications or consequences
    failure_consequences TEXT, -- What happens if the service fails
    
    -- Availability Factors
    rarity_id UUID REFERENCES public.rarity_levels(rarity_id), -- How commonly available this service is
    seasonal_factors TEXT, -- Time-based considerations
    cultural_acceptance TEXT, -- How different societies view this service
    
    -- Quality Variations
    apprentice_description TEXT, -- How this service differs at apprentice level
    journeyman_description TEXT, -- How this service differs at journeyman level
    master_description TEXT, -- How this service differs at master level
    legendary_description TEXT, -- How this service differs at legendary level
    
    -- Examples and Variants
    common_variants TEXT, -- Different ways this service might be offered
    real_world_examples TEXT, -- Examples to help DMs understand the service
    specialization_options TEXT, -- Ways providers might specialize within this service
    
    -- Metadata
    source_material TEXT, -- Reference documents
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    notes TEXT, -- Additional context about this service
    
    -- Constraints
    UNIQUE(service_category_id, service_name),
    CHECK(base_quality_level BETWEEN 1 AND 10),
    CHECK(required_skill_level BETWEEN 1 AND 10),
    CHECK(complexity_level BETWEEN 1 AND 10),
    CHECK(risk_level BETWEEN 1 AND 10)
);

-- Indexes for performance
CREATE INDEX idx_services_category ON public.services (service_category_id);
CREATE INDEX idx_services_cost_type ON public.services (cost_type_id);
CREATE INDEX idx_services_name_search ON public.services USING gin(to_tsvector('english', service_name));
CREATE INDEX idx_services_description_search ON public.services USING gin(to_tsvector('english', service_description));
CREATE INDEX idx_services_complexity ON public.services (complexity_level);
CREATE INDEX idx_services_risk ON public.services (risk_level);
CREATE INDEX idx_services_skill_required ON public.services (required_skill_level);
CREATE INDEX idx_services_legal_status ON public.services (legal_status);
CREATE INDEX idx_services_rarity ON public.services (rarity_id);

-- Trigger for updated_at
CREATE TRIGGER services_updated_at_trigger
    BEFORE UPDATE ON public.services
    FOR EACH ROW
    EXECUTE FUNCTION update_timestamp();

-- Comments
COMMENT ON TABLE public.services IS 'Generic services that can be offered by NPCs or businesses';
COMMENT ON COLUMN public.services.service_category_id IS 'The category this service belongs to';
COMMENT ON COLUMN public.services.service_name IS 'The name of the service';
COMMENT ON COLUMN public.services.service_description IS 'Detailed description of what this service entails';
COMMENT ON COLUMN public.services.cost_type_id IS 'Foreign key to cost_types table indicating the payment structure for this service';
COMMENT ON COLUMN public.services.cost_details IS 'Specific cost details like amounts, ranges, or special conditions';
COMMENT ON COLUMN public.services.base_quality_level IS 'Baseline quality level for this service (1=poor, 10=masterwork)';
COMMENT ON COLUMN public.services.required_skill_level IS 'Minimum skill level needed to provide this service (1=novice, 10=master)';
COMMENT ON COLUMN public.services.complexity_level IS 'How difficult this service is to provide (1=simple, 10=extremely complex)';
COMMENT ON COLUMN public.services.risk_level IS 'How dangerous or risky this service is (1=safe, 10=extremely dangerous)';
COMMENT ON COLUMN public.services.rarity_id IS 'Foreign key to rarity_levels table indicating how commonly available this service is';
COMMENT ON COLUMN public.services.legal_status IS 'General legal standing of this service';

-- Sample services for different categories
INSERT INTO public.services (service_category_id, service_name, service_description, cost_type_id, cost_details, base_quality_level, required_skill_level, complexity_level, risk_level, rarity_id, legal_status) VALUES

-- Information Services
((SELECT category_id FROM public.service_categories WHERE name = 'Information'), 
'Local Rumors and Gossip', 
'Sharing recent news, local gossip, and general information about the area', 
(SELECT cost_type_id FROM public.cost_types WHERE name = 'Free Service'), 'Often shared freely, sometimes for the price of drinks', 3, 2, 2, 1, (SELECT rarity_id FROM public.rarity_levels WHERE name = 'Common'), 'Legal'),

((SELECT category_id FROM public.service_categories WHERE name = 'Information'), 
'Detailed Area Intelligence', 
'Comprehensive information about specific locations, people, or situations requiring investigation', 
(SELECT cost_type_id FROM public.cost_types WHERE name = 'Variable Gold Range'), '10-50 gold pieces depending on complexity and danger', 6, 6, 6, 3, (SELECT rarity_id FROM public.rarity_levels WHERE name = 'Uncommon'), 'Legal'),

-- Crafting Services
((SELECT category_id FROM public.service_categories WHERE name = 'Crafting'), 
'Basic Weapon Repair', 
'Repairing damaged weapons to functional condition', 
(SELECT cost_type_id FROM public.cost_types WHERE name = 'Variable Gold Range'), '5-20 gold pieces per weapon depending on damage', 5, 4, 3, 1, (SELECT rarity_id FROM public.rarity_levels WHERE name = 'Common'), 'Legal'),

((SELECT category_id FROM public.service_categories WHERE name = 'Crafting'), 
'Custom Weapon Forging', 
'Creating specially designed weapons to customer specifications', 
(SELECT cost_type_id FROM public.cost_types WHERE name = 'Variable Gold Range'), '100-500 gold pieces depending on materials and complexity', 8, 8, 8, 2, (SELECT rarity_id FROM public.rarity_levels WHERE name = 'Uncommon'), 'Legal'),

-- Transportation Services
((SELECT category_id FROM public.service_categories WHERE name = 'Transportation'), 
'Local Cart Transport', 
'Moving goods or people within a settlement or to nearby locations', 
(SELECT cost_type_id FROM public.cost_types WHERE name = 'Daily Wage'), '1-5 gold pieces per day depending on distance and cargo', 4, 2, 2, 2, (SELECT rarity_id FROM public.rarity_levels WHERE name = 'Common'), 'Legal'),

((SELECT category_id FROM public.service_categories WHERE name = 'Transportation'), 
'Long Distance Caravan Guard', 
'Protecting valuable cargo during extended travel between settlements', 
(SELECT cost_type_id FROM public.cost_types WHERE name = 'Variable Gold Range'), '50-200 gold pieces per journey plus hazard pay', 7, 7, 6, 7, (SELECT rarity_id FROM public.rarity_levels WHERE name = 'Uncommon'), 'Legal'),

-- Healing Services
((SELECT category_id FROM public.service_categories WHERE name = 'Healing'), 
'Basic Wound Treatment', 
'Cleaning and bandaging minor injuries, basic first aid', 
(SELECT cost_type_id FROM public.cost_types WHERE name = 'Fixed Gold Amount'), '1-5 gold pieces per treatment', 4, 3, 2, 1, (SELECT rarity_id FROM public.rarity_levels WHERE name = 'Common'), 'Legal'),

((SELECT category_id FROM public.service_categories WHERE name = 'Healing'), 
'Disease Treatment', 
'Diagnosing and treating illnesses and diseases', 
(SELECT cost_type_id FROM public.cost_types WHERE name = 'Variable Gold Range'), '20-100 gold pieces depending on severity and rarity', 7, 7, 7, 3, (SELECT rarity_id FROM public.rarity_levels WHERE name = 'Uncommon'), 'Legal'),

-- Magic Services
((SELECT category_id FROM public.service_categories WHERE name = 'Magic'), 
'Minor Enchantment', 
'Adding simple magical properties to items', 
(SELECT cost_type_id FROM public.cost_types WHERE name = 'Materials Cost Only'), '50-200 gold pieces plus magical materials', 6, 6, 6, 3, (SELECT rarity_id FROM public.rarity_levels WHERE name = 'Rare'), 'Legal'),

((SELECT category_id FROM public.service_categories WHERE name = 'Magic'), 
'Divination Consultation', 
'Using magical means to gain insight into past, present, or future events', 
(SELECT cost_type_id FROM public.cost_types WHERE name = 'Variable Gold Range'), '25-100 gold pieces per consultation depending on complexity', 7, 8, 7, 4, (SELECT rarity_id FROM public.rarity_levels WHERE name = 'Rare'), 'Legal'),

-- Criminal Services
((SELECT category_id FROM public.service_categories WHERE name = 'Criminal'), 
'Lockpicking', 
'Opening locks without the proper key', 
(SELECT cost_type_id FROM public.cost_types WHERE name = 'Variable Gold Range'), '10-50 gold pieces depending on lock complexity and risk', 6, 6, 5, 5, (SELECT rarity_id FROM public.rarity_levels WHERE name = 'Uncommon'), 'Illegal'),

((SELECT category_id FROM public.service_categories WHERE name = 'Criminal'), 
'Assassination', 
'Eliminating specific targets for payment', 
(SELECT cost_type_id FROM public.cost_types WHERE name = 'Blood Money'), '500-5000 gold pieces depending on target difficulty and risk', 9, 9, 9, 10, (SELECT rarity_id FROM public.rarity_levels WHERE name = 'Very Rare'), 'Illegal'),

-- Training Services
((SELECT category_id FROM public.service_categories WHERE name = 'Training'), 
'Basic Skill Instruction', 
'Teaching fundamental techniques in various skills', 
(SELECT cost_type_id FROM public.cost_types WHERE name = 'Variable Gold Range'), '5-20 gold pieces per lesson depending on skill complexity', 5, 6, 4, 1, (SELECT rarity_id FROM public.rarity_levels WHERE name = 'Common'), 'Legal'),

((SELECT category_id FROM public.service_categories WHERE name = 'Training'), 
'Master-Level Mentorship', 
'Advanced training from a recognized master in their field', 
(SELECT cost_type_id FROM public.cost_types WHERE name = 'Apprenticeship Terms'), '100-500 gold pieces plus proving worthiness and commitment', 9, 9, 7, 2, (SELECT rarity_id FROM public.rarity_levels WHERE name = 'Very Rare'), 'Legal');