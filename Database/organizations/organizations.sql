-- =====================================================
-- Organizations Table - Guilds, Factions, Groups & World Entities
-- =====================================================

DROP TABLE IF EXISTS public.organizations CASCADE;

CREATE TABLE public.organizations (
    -- Primary identification
    organization_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(200) NOT NULL,
    
    -- Entity classification (expanded to include world entities)
    entity_type VARCHAR(100) NOT NULL DEFAULT 'Organization', -- Organization, Landmark, Event, Artifact, Legend, Custom
    organization_type VARCHAR(100), -- Guild, Religious Order, Military, Secret Society, etc. (when entity_type = 'Organization')
    subtype VARCHAR(100), -- Thieves' Guild/Monument, Merchant Guild/Festival, Knightly Order/Magical Item, etc.
    size_scope VARCHAR(50), -- Local, Regional, National, International
    significance_level VARCHAR(50), -- Local, Regional, National, International, World-spanning, Legendary
    membership_estimate INTEGER, -- Approximate number of members (for organizations)
    
    -- Basic description (enhanced for all entity types)
    short_description TEXT, -- Brief summary for quick reference
    detailed_description TEXT, -- Full description with all relevant details
    physical_appearance TEXT, -- What it looks like (for landmarks, artifacts, etc.)
    notable_features TEXT, -- Special characteristics that stand out
    
    -- Leadership and hierarchy (for organizations)
    leadership_structure VARCHAR(100), -- Hierarchical, Democratic, Single Leader, Council, etc.
    -- NOTE: Current and past leaders are now stored in the organization_leaders relationship table
    succession_method VARCHAR(100), -- How leadership changes
    
    -- Purpose and activities (enhanced for all entity types)
    primary_purpose TEXT, -- Main reason for existence
    stated_goals TEXT, -- Official objectives (for organizations)
    hidden_agenda TEXT, -- Secret goals (for organizations)
    -- NOTE: Main activities are now stored in the organization_activities table
    
    -- Membership information (for organizations)
    membership_requirements TEXT, -- How to join
    membership_benefits TEXT, -- What members receive
    membership_obligations TEXT, -- What members must do
    initiation_process TEXT, -- How new members are inducted
    
    -- Geographic presence (enhanced for all entity types)
    headquarters_location_id UUID REFERENCES public.locations(location_id), -- FK to locations table
    primary_location_id UUID REFERENCES public.locations(location_id), -- FK to locations table (alternative for non-organizations)
    geographic_region TEXT, -- General area where it exists/occurred
    specific_location TEXT, -- Precise location details
    -- areas_of_operation now normalized into organization_areas_of_operation table
    area_of_influence TEXT, -- Geographic scope of its effects/importance
    -- chapter_locations now normalized into organization_chapters table
    territory_controlled TEXT, -- Areas they control or influence
    
    -- Temporal aspects (for events, recurring phenomena, etc.)
    duration TEXT, -- How long it lasts/lasted
    seasonal_aspects TEXT, -- Times of year when it's relevant
    
    -- Resources and capabilities (primarily for organizations)
    wealth_level VARCHAR(50), -- Poor, Modest, Wealthy, Extremely Wealthy
    -- NOTE: Primary resources are now stored in the organization_resources table
    assets_owned TEXT, -- Buildings, ships, businesses they control
    notable_equipment TEXT, -- Special items, magical artifacts, etc.
    
    -- Rules and mechanics (world rules, magical properties, etc.)
    special_properties TEXT, -- Unique characteristics or abilities
    rules_or_conditions TEXT, -- How it works or what governs it
    limitations_or_restrictions TEXT, -- What it cannot do or limitations
    activation_requirements TEXT, -- What's needed to use/access it
    
    -- Relationships and politics (enhanced for all entity types)
    public_reputation VARCHAR(100), -- How general public views them
    conflicting_entities TEXT, -- Things that oppose or conflict with it
    
    -- Culture and identity (for organizations and cultural entities)
    -- NOTE: Core values are now stored in the organization_core_values table
    traditions_and_customs TEXT, -- Internal practices
    symbols_and_regalia TEXT, -- Identifying marks, colors, emblems
    motto_or_creed TEXT, -- Official saying or belief statement
    dress_code_or_uniforms TEXT, -- How members identify themselves
    
    -- Communication and operations (for organizations)
    communication_methods TEXT, -- How they stay in contact
    meeting_places TEXT, -- Where they gather
    recruitment_methods TEXT, -- How they find new members
    security_measures TEXT, -- How they protect themselves
    codes_or_signals TEXT, -- Secret methods of identification
    
    -- Legal and moral standing (primarily for organizations)
    legal_status VARCHAR(100), -- Legal, Tolerated, Outlawed, Secret
    moral_alignment VARCHAR(50), -- Good, Neutral, Evil (general tendency)
    ethical_codes TEXT, -- Rules members must follow
    punishments_for_betrayal TEXT, -- What happens to traitors
    
    -- Historical information (enhanced for all entity types)
    founding_date VARCHAR(100), -- When established (can be approximate)
    founding_story TEXT, -- How and why it was created
    origin_story TEXT, -- How it came to be (alternative field)
    significant_events TEXT, -- Important moments in history
    historical_significance TEXT, -- Why it matters in world history
    -- NOTE: Notable past leaders are now stored in the organization_leaders relationship table
    historical_achievements TEXT, -- What they've accomplished
    related_events TEXT, -- Other historical events it connects to
    
    -- Cultural and social impact (for all entity types)
    cultural_significance TEXT, -- What it means to various cultures
    religious_importance TEXT, -- Spiritual/religious aspects
    political_implications TEXT, -- How it affects politics/power
    economic_impact TEXT, -- Economic effects or value
    
    -- Knowledge and accessibility (for all entity types)
    public_knowledge_level VARCHAR(50), -- Unknown, Rumored, Known, Common Knowledge
    how_people_learn_about_it TEXT, -- How information spreads
    who_has_detailed_knowledge TEXT, -- Experts or keepers of information
    misinformation_or_legends TEXT, -- False beliefs or distorted stories
    
    -- Current status and activities (enhanced for all entity types)
    current_status VARCHAR(50) DEFAULT 'Active', -- Active, Declining, Growing, Disbanded, etc.
    current_condition VARCHAR(50) DEFAULT 'Stable', -- Active, Dormant, Destroyed, Changing, etc.
    current_major_projects TEXT, -- What they're working on now (for organizations)
    current_challenges TEXT, -- Problems they're facing
    recent_activities TEXT, -- What they've done lately
    recent_changes TEXT, -- What's happened to it lately
    current_guardians_or_caretakers TEXT, -- Who watches over it now
    accessibility VARCHAR(50), -- Easy, Moderate, Difficult, Impossible
    
    -- Adventure relevance (enhanced for all entity types)
    quest_opportunities TEXT, -- How players might work with them
    quest_potential TEXT, -- How it might generate adventures
    conflict_potential TEXT, -- How they might oppose players
    information_they_possess TEXT, -- What they know that's useful
    rewards_they_offer TEXT, -- What they can give players
    treasure_or_rewards TEXT, -- What players might gain from it
    dangers_or_risks TEXT, -- Threats associated with it
    required_preparation TEXT, -- What's needed to interact safely
    
    -- Mysteries and secrets (for all entity types)
    hidden_aspects TEXT, -- Secret properties or information
    unsolved_mysteries TEXT, -- Questions that remain unanswered
    prophecies_or_predictions TEXT, -- Future events predicted about it
    conspiracy_theories TEXT, -- Wild theories people believe
    
    -- Sensory details (for all entity types)
    sounds_associated TEXT, -- Audio characteristics
    smells_or_atmosphere TEXT, -- Olfactory or atmospheric qualities
    magical_aura TEXT, -- Magical sensations or energy
    emotional_impact TEXT, -- How it makes people feel
    
    -- Documentation and references (for all entity types)
    known_records TEXT, -- Where information about it is recorded
    artistic_depictions TEXT, -- Paintings, songs, stories about it
    scholarly_studies TEXT, -- Academic or research work done
    witness_accounts TEXT, -- Personal testimonies about it
    
    -- Variations and instances (for all entity types)
    similar_entities TEXT, -- Related or comparable things
    regional_variations TEXT, -- How it differs in different places
    multiple_instances BOOLEAN DEFAULT FALSE, -- Are there multiple versions?
    unique_identifier TEXT, -- What makes this specific instance special
    
    -- Metadata and organization (enhanced for all entity types)
    dm_notes TEXT, -- Private DM information
    campaign_relevance TEXT, -- Role in current story
    campaign_role TEXT, -- How it fits into current story (alternative field)
    potential_plot_hooks TEXT, -- Story ideas involving this entity
    
    -- Organization and references (enhanced for all entity types)
    inspiration_source TEXT, -- Real-world or fictional inspiration
    source_material TEXT, -- Reference documents or books
    cross_references TEXT, -- Related entries in other tables
    
    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_organizations_name_search ON public.organizations USING gin(to_tsvector('english', name));
CREATE INDEX idx_organizations_entity_type ON public.organizations (entity_type);
CREATE INDEX idx_organizations_organization_type ON public.organizations (organization_type);
CREATE INDEX idx_organizations_type_subtype ON public.organizations (entity_type, subtype);
CREATE INDEX idx_organizations_scope ON public.organizations (size_scope);
CREATE INDEX idx_organizations_headquarters ON public.organizations (headquarters_location_id);
CREATE INDEX idx_organizations_primary_location ON public.organizations (primary_location_id);
CREATE INDEX idx_organizations_status ON public.organizations (current_status);
CREATE INDEX idx_organizations_condition ON public.organizations (current_condition);
CREATE INDEX idx_organizations_tags ON public.organizations USING gin(tags);
CREATE INDEX idx_organizations_knowledge_level ON public.organizations (public_knowledge_level);

-- Foreign key constraints now defined inline with column definitions

-- Trigger for updated_at
CREATE TRIGGER organizations_updated_at_trigger
    BEFORE UPDATE ON public.organizations
    FOR EACH ROW

COMMENT ON TABLE public.organizations IS 'Organizations, landmarks, artifacts, events, legends, and other world-building entities';
COMMENT ON COLUMN public.organizations.entity_type IS 'Organization, Landmark, Event, Artifact, Legend, Custom';
COMMENT ON COLUMN public.organizations.organization_type IS 'Guild, Religious Order, Military, Secret Society, etc. (when entity_type = Organization)';
-- chapter_locations now normalized into organization_chapters table
-- areas_of_operation now normalized into organization_areas_of_operation table
-- government_relations, connected_entities, and player_knowledge are planned for future normalization

-- Sample organizations and world entities
    primary_purpose, membership_requirements, headquarters_location_id, current_status,
    short_description, tags
) VALUES 
-- Organizations
    'Merchants Guild of the Golden Road',
    'Organization',
    'Trade Guild',
    'Merchant Guild',
    'Regional',
    'Facilitate and protect trade along major routes, maintain quality standards for goods',
    'Must be established trader with good reputation and pay membership dues',
    NULL, -- Would reference actual settlement
    'Active',
    'Powerful trade guild controlling major commercial routes',
    ARRAY['merchant', 'trade', 'economic', 'influential']
),
(
    'Order of the Silver Dawn',
    'Organization',
    'Religious Order',
    'Knightly Order', 
    'National',
    'National',
    'Protect pilgrims, fight undead, uphold justice in the name of the Dawn God',
    'Must be lawful good alignment, pass trials of faith and combat',
    NULL, -- Would reference actual settlement
    'Active',
    'Holy order of paladins dedicated to fighting darkness',
    ARRAY['religious', 'military', 'good-aligned', 'undead-hunters']
),
(
    'The Whispered Word',
    'Organization',
    'Secret Society',
    'Information Brokers',
    'International',
    'International',
    'Gather and trade information, influence political events from the shadows',
    'Invitation only, must prove useful skills and absolute discretion',
    NULL, -- Unknown/hidden headquarters
    'Active',
    'Secretive network of spies and information brokers',
    ARRAY['secret', 'information', 'spy-network', 'political']
);

-- Add some world entities as well
INSERT INTO public.organizations (
    name, entity_type, subtype, significance_level, short_description,
    time_period, cultural_significance, public_knowledge_level, current_condition,
    primary_location_id, tags
) VALUES 
(
    'Landmark',
    'Monument',
    'Regional',
    'A massive standing stone that constantly weeps a clear, sweet liquid that never pools or runs away.',
    'Ancient - exists for thousands of years',
    'Local pilgrims believe the tears heal minor ailments and bring good fortune. Site of marriage proposals and peace treaties.',
    'Common Knowledge',
    'Stable',
    NULL, -- Would reference actual settlement
    ARRAY['landmark', 'mystery', 'pilgrimage-site', 'healing']
),
(
    'Festival of the Autumn Moon',
    'Event',
    'Festival',
    'Regional',
    'Annual three-day celebration marking the harvest season with feasts, competitions, and the choosing of the Harvest King and Queen.',
    'Present - occurs every autumn',
    'Most important social event of the year, brings together communities from dozens of miles around. Marriages often planned around it.',
    'Common Knowledge',
    'Active',
    NULL,
    ARRAY['festival', 'harvest', 'social-event', 'tradition']
),
(
    'The Crown of Whispers',
    'Artifact',
    'Magical Item',
    'Legendary',
    'A silver crown that allows its wearer to hear the thoughts of others within a mile radius, but slowly drives them mad.',
    'Lost for 200 years',
    'Symbol of the fallen Shadowmere Dynasty. Some believe it still influences politics from wherever it lies hidden.',
    'Rumored',
    'Dormant',
    NULL,
    ARRAY['artifact', 'cursed', 'lost-treasure', 'political', 'dangerous']
),
(
    'The Prophecy of the Crimson Dawn',
    'Legend',
    'Prophecy',
    'World-spanning',
    'Ancient prophecy speaking of a time when the sun will rise red for seven days, and a chosen one will either save or doom the world.',
    'Future event',
    'Debated by scholars and priests across many nations. Some actively seek to fulfill it, others to prevent it.',
    'Known',
    'Stable',
    NULL,
    ARRAY['prophecy', 'end-times', 'chosen-one', 'world-changing', 'contested']
);