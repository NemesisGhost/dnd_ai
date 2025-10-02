-- =====================================================
-- Service Tags Relationship Table
-- Requires: services.sql, tags.sql
-- =====================================================

DROP TABLE IF EXISTS public.service_tags CASCADE;

CREATE TABLE public.service_tags (
    service_tag_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    service_id UUID NOT NULL REFERENCES public.services(service_id) ON DELETE CASCADE,
    tag_id UUID NOT NULL REFERENCES public.tags(tag_id) ON DELETE CASCADE,
    assigned_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    assigned_by VARCHAR(100), -- Who assigned this tag (DM, system, etc.)
    notes TEXT, -- Additional context for why this tag applies to this service
    UNIQUE(service_id, tag_id)
);

-- Indexes for performance
CREATE INDEX idx_service_tags_service ON public.service_tags (service_id);
CREATE INDEX idx_service_tags_tag ON public.service_tags (tag_id);
CREATE INDEX idx_service_tags_assigned_at ON public.service_tags (assigned_at);

-- Comments
COMMENT ON TABLE public.service_tags IS 'Many-to-many relationship linking services to descriptive tags';
COMMENT ON COLUMN public.service_tags.service_id IS 'The service being tagged';
COMMENT ON COLUMN public.service_tags.tag_id IS 'The tag being applied to the service';
COMMENT ON COLUMN public.service_tags.assigned_by IS 'Source of tag assignment for audit purposes';

-- Insert tag relationships for the sample services
-- First, we need to create the service-specific tags that don't exist in the general tags table
INSERT INTO public.tags (name, description) VALUES
('information', 'Related to sharing or gathering information'),
('gossip', 'Informal information sharing and rumors'),
('local-knowledge', 'Knowledge specific to a local area'),
('intelligence', 'Detailed and strategic information'),
('investigation', 'Research and evidence gathering'),
('crafting', 'Creating or modifying physical items'),
('weapons', 'Related to weapons and armaments'),
('repair', 'Fixing damaged items'),
('blacksmithing', 'Working with metal and forge'),
('custom', 'Specially made to order'),
('masterwork', 'Exceptional quality craftsmanship'),
('transportation', 'Moving people or goods'),
('cart', 'Using wheeled vehicles'),
('local', 'Within immediate area'),
('goods', 'Physical items and cargo'),
('caravan', 'Long-distance trade transport'),
('guard', 'Protection services'),
('protection', 'Defensive services'),
('travel', 'Movement between locations'),
('healing', 'Medical and recovery services'),
('first-aid', 'Basic medical treatment'),
('wounds', 'Injury treatment'),
('medical', 'Health and medicine related'),
('disease', 'Illness treatment'),
('diagnosis', 'Medical examination'),
('magic', 'Supernatural abilities'),
('enchantment', 'Magical enhancement of items'),
('items', 'Physical objects'),
('spellcasting', 'Using magical spells'),
('divination', 'Magical insight and prediction'),
('fortune-telling', 'Predicting future events'),
('insight', 'Understanding and perception'),
('criminal', 'Illegal activities'),
('lockpicking', 'Opening locks without keys'),
('theft', 'Taking others property'),
('infiltration', 'Entering restricted areas'),
('assassination', 'Contract killing'),
('murder', 'Taking life'),
('contract-killing', 'Paid assassination'),
('training', 'Teaching skills'),
('instruction', 'Educational services'),
('skills', 'Abilities and techniques'),
('teaching', 'Imparting knowledge'),
('mentorship', 'Personal guidance and development'),
('master', 'Expert level'),
('advanced', 'High-level techniques'),
('exclusive', 'Limited availability')
ON CONFLICT (name) DO NOTHING;

-- Now insert the tag relationships for services
INSERT INTO public.service_tags (service_id, tag_id, assigned_by) VALUES
-- Local Rumors and Gossip
((SELECT service_id FROM public.services WHERE service_name = 'Local Rumors and Gossip'), 
 (SELECT tag_id FROM public.tags WHERE name = 'information'), 'system'),
((SELECT service_id FROM public.services WHERE service_name = 'Local Rumors and Gossip'), 
 (SELECT tag_id FROM public.tags WHERE name = 'gossip'), 'system'),
((SELECT service_id FROM public.services WHERE service_name = 'Local Rumors and Gossip'), 
 (SELECT tag_id FROM public.tags WHERE name = 'local-knowledge'), 'system'),

-- Detailed Area Intelligence
((SELECT service_id FROM public.services WHERE service_name = 'Detailed Area Intelligence'), 
 (SELECT tag_id FROM public.tags WHERE name = 'information'), 'system'),
((SELECT service_id FROM public.services WHERE service_name = 'Detailed Area Intelligence'), 
 (SELECT tag_id FROM public.tags WHERE name = 'intelligence'), 'system'),
((SELECT service_id FROM public.services WHERE service_name = 'Detailed Area Intelligence'), 
 (SELECT tag_id FROM public.tags WHERE name = 'investigation'), 'system'),

-- Basic Weapon Repair
((SELECT service_id FROM public.services WHERE service_name = 'Basic Weapon Repair'), 
 (SELECT tag_id FROM public.tags WHERE name = 'crafting'), 'system'),
((SELECT service_id FROM public.services WHERE service_name = 'Basic Weapon Repair'), 
 (SELECT tag_id FROM public.tags WHERE name = 'weapons'), 'system'),
((SELECT service_id FROM public.services WHERE service_name = 'Basic Weapon Repair'), 
 (SELECT tag_id FROM public.tags WHERE name = 'repair'), 'system'),
((SELECT service_id FROM public.services WHERE service_name = 'Basic Weapon Repair'), 
 (SELECT tag_id FROM public.tags WHERE name = 'blacksmithing'), 'system'),

-- Custom Weapon Forging
((SELECT service_id FROM public.services WHERE service_name = 'Custom Weapon Forging'), 
 (SELECT tag_id FROM public.tags WHERE name = 'crafting'), 'system'),
((SELECT service_id FROM public.services WHERE service_name = 'Custom Weapon Forging'), 
 (SELECT tag_id FROM public.tags WHERE name = 'weapons'), 'system'),
((SELECT service_id FROM public.services WHERE service_name = 'Custom Weapon Forging'), 
 (SELECT tag_id FROM public.tags WHERE name = 'custom'), 'system'),
((SELECT service_id FROM public.services WHERE service_name = 'Custom Weapon Forging'), 
 (SELECT tag_id FROM public.tags WHERE name = 'blacksmithing'), 'system'),
((SELECT service_id FROM public.services WHERE service_name = 'Custom Weapon Forging'), 
 (SELECT tag_id FROM public.tags WHERE name = 'masterwork'), 'system'),

-- Local Cart Transport
((SELECT service_id FROM public.services WHERE service_name = 'Local Cart Transport'), 
 (SELECT tag_id FROM public.tags WHERE name = 'transportation'), 'system'),
((SELECT service_id FROM public.services WHERE service_name = 'Local Cart Transport'), 
 (SELECT tag_id FROM public.tags WHERE name = 'cart'), 'system'),
((SELECT service_id FROM public.services WHERE service_name = 'Local Cart Transport'), 
 (SELECT tag_id FROM public.tags WHERE name = 'local'), 'system'),
((SELECT service_id FROM public.services WHERE service_name = 'Local Cart Transport'), 
 (SELECT tag_id FROM public.tags WHERE name = 'goods'), 'system'),

-- Long Distance Caravan Guard
((SELECT service_id FROM public.services WHERE service_name = 'Long Distance Caravan Guard'), 
 (SELECT tag_id FROM public.tags WHERE name = 'transportation'), 'system'),
((SELECT service_id FROM public.services WHERE service_name = 'Long Distance Caravan Guard'), 
 (SELECT tag_id FROM public.tags WHERE name = 'caravan'), 'system'),
((SELECT service_id FROM public.services WHERE service_name = 'Long Distance Caravan Guard'), 
 (SELECT tag_id FROM public.tags WHERE name = 'guard'), 'system'),
((SELECT service_id FROM public.services WHERE service_name = 'Long Distance Caravan Guard'), 
 (SELECT tag_id FROM public.tags WHERE name = 'protection'), 'system'),
((SELECT service_id FROM public.services WHERE service_name = 'Long Distance Caravan Guard'), 
 (SELECT tag_id FROM public.tags WHERE name = 'travel'), 'system'),

-- Basic Wound Treatment
((SELECT service_id FROM public.services WHERE service_name = 'Basic Wound Treatment'), 
 (SELECT tag_id FROM public.tags WHERE name = 'healing'), 'system'),
((SELECT service_id FROM public.services WHERE service_name = 'Basic Wound Treatment'), 
 (SELECT tag_id FROM public.tags WHERE name = 'first-aid'), 'system'),
((SELECT service_id FROM public.services WHERE service_name = 'Basic Wound Treatment'), 
 (SELECT tag_id FROM public.tags WHERE name = 'wounds'), 'system'),
((SELECT service_id FROM public.services WHERE service_name = 'Basic Wound Treatment'), 
 (SELECT tag_id FROM public.tags WHERE name = 'medical'), 'system'),

-- Disease Treatment
((SELECT service_id FROM public.services WHERE service_name = 'Disease Treatment'), 
 (SELECT tag_id FROM public.tags WHERE name = 'healing'), 'system'),
((SELECT service_id FROM public.services WHERE service_name = 'Disease Treatment'), 
 (SELECT tag_id FROM public.tags WHERE name = 'disease'), 'system'),
((SELECT service_id FROM public.services WHERE service_name = 'Disease Treatment'), 
 (SELECT tag_id FROM public.tags WHERE name = 'medical'), 'system'),
((SELECT service_id FROM public.services WHERE service_name = 'Disease Treatment'), 
 (SELECT tag_id FROM public.tags WHERE name = 'diagnosis'), 'system'),

-- Minor Enchantment
((SELECT service_id FROM public.services WHERE service_name = 'Minor Enchantment'), 
 (SELECT tag_id FROM public.tags WHERE name = 'magic'), 'system'),
((SELECT service_id FROM public.services WHERE service_name = 'Minor Enchantment'), 
 (SELECT tag_id FROM public.tags WHERE name = 'enchantment'), 'system'),
((SELECT service_id FROM public.services WHERE service_name = 'Minor Enchantment'), 
 (SELECT tag_id FROM public.tags WHERE name = 'items'), 'system'),
((SELECT service_id FROM public.services WHERE service_name = 'Minor Enchantment'), 
 (SELECT tag_id FROM public.tags WHERE name = 'spellcasting'), 'system'),

-- Divination Consultation
((SELECT service_id FROM public.services WHERE service_name = 'Divination Consultation'), 
 (SELECT tag_id FROM public.tags WHERE name = 'magic'), 'system'),
((SELECT service_id FROM public.services WHERE service_name = 'Divination Consultation'), 
 (SELECT tag_id FROM public.tags WHERE name = 'divination'), 'system'),
((SELECT service_id FROM public.services WHERE service_name = 'Divination Consultation'), 
 (SELECT tag_id FROM public.tags WHERE name = 'fortune-telling'), 'system'),
((SELECT service_id FROM public.services WHERE service_name = 'Divination Consultation'), 
 (SELECT tag_id FROM public.tags WHERE name = 'insight'), 'system'),

-- Lockpicking
((SELECT service_id FROM public.services WHERE service_name = 'Lockpicking'), 
 (SELECT tag_id FROM public.tags WHERE name = 'criminal'), 'system'),
((SELECT service_id FROM public.services WHERE service_name = 'Lockpicking'), 
 (SELECT tag_id FROM public.tags WHERE name = 'lockpicking'), 'system'),
((SELECT service_id FROM public.services WHERE service_name = 'Lockpicking'), 
 (SELECT tag_id FROM public.tags WHERE name = 'theft'), 'system'),
((SELECT service_id FROM public.services WHERE service_name = 'Lockpicking'), 
 (SELECT tag_id FROM public.tags WHERE name = 'infiltration'), 'system'),

-- Assassination
((SELECT service_id FROM public.services WHERE service_name = 'Assassination'), 
 (SELECT tag_id FROM public.tags WHERE name = 'criminal'), 'system'),
((SELECT service_id FROM public.services WHERE service_name = 'Assassination'), 
 (SELECT tag_id FROM public.tags WHERE name = 'assassination'), 'system'),
((SELECT service_id FROM public.services WHERE service_name = 'Assassination'), 
 (SELECT tag_id FROM public.tags WHERE name = 'murder'), 'system'),
((SELECT service_id FROM public.services WHERE service_name = 'Assassination'), 
 (SELECT tag_id FROM public.tags WHERE name = 'contract-killing'), 'system'),

-- Basic Skill Instruction
((SELECT service_id FROM public.services WHERE service_name = 'Basic Skill Instruction'), 
 (SELECT tag_id FROM public.tags WHERE name = 'training'), 'system'),
((SELECT service_id FROM public.services WHERE service_name = 'Basic Skill Instruction'), 
 (SELECT tag_id FROM public.tags WHERE name = 'instruction'), 'system'),
((SELECT service_id FROM public.services WHERE service_name = 'Basic Skill Instruction'), 
 (SELECT tag_id FROM public.tags WHERE name = 'skills'), 'system'),
((SELECT service_id FROM public.services WHERE service_name = 'Basic Skill Instruction'), 
 (SELECT tag_id FROM public.tags WHERE name = 'teaching'), 'system'),

-- Master-Level Mentorship
((SELECT service_id FROM public.services WHERE service_name = 'Master-Level Mentorship'), 
 (SELECT tag_id FROM public.tags WHERE name = 'training'), 'system'),
((SELECT service_id FROM public.services WHERE service_name = 'Master-Level Mentorship'), 
 (SELECT tag_id FROM public.tags WHERE name = 'mentorship'), 'system'),
((SELECT service_id FROM public.services WHERE service_name = 'Master-Level Mentorship'), 
 (SELECT tag_id FROM public.tags WHERE name = 'master'), 'system'),
((SELECT service_id FROM public.services WHERE service_name = 'Master-Level Mentorship'), 
 (SELECT tag_id FROM public.tags WHERE name = 'advanced'), 'system'),
((SELECT service_id FROM public.services WHERE service_name = 'Master-Level Mentorship'), 
 (SELECT tag_id FROM public.tags WHERE name = 'exclusive'), 'system');