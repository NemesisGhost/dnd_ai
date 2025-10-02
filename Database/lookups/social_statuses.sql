-- =====================================================
-- Social Statuses Lookup Table
-- =====================================================

DROP TABLE IF EXISTS public.social_statuses CASCADE;

CREATE TABLE public.social_statuses (
    status_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    influence_level INTEGER, -- 1-10 scale of social influence and power
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

INSERT INTO public.social_statuses (name, description, influence_level) VALUES
-- Bottom Tier
('Outcast', 'Shunned by society, actively avoided', 1),
('Vagrant', 'Homeless wanderer with no fixed status', 1),
('Slave', 'Owned by others, no personal freedom', 1),

-- Lower Class  
('Peasant', 'Rural agricultural worker, subsistence living', 2),
('Beggar', 'Destitute, dependent on charity', 2),
('Laborer', 'Unskilled manual worker', 2),

-- Working Class
('Commoner', 'Ordinary citizen with basic rights', 3),
('Apprentice', 'Learning a trade, low skill level', 3),
('Servant', 'Employed in domestic service', 3),

-- Skilled Class
('Craftsman', 'Skilled tradesperson with established business', 4),
('Artisan', 'Master of artistic or specialized craft', 4),
('Journeyman', 'Experienced tradesperson, not yet master', 4),

-- Professional Class
('Merchant', 'Successful trader with established business', 5),
('Guild Member', 'Member of professional organization', 5),
('Clerk', 'Administrative or scholarly worker', 5),

-- Upper Middle Class
('Guild Leader', 'Leader of professional organization', 6),
('Wealthy Merchant', 'Very successful trader with extensive business', 6),
('Master Craftsman', 'Renowned expert in their field', 6),

-- Lower Nobility
('Minor Noble', 'Lesser nobility, small land holdings', 7),
('Landed Gentry', 'Non-noble with significant property', 7),
('Knight', 'Noble warrior with lands and title', 7),

-- Nobility
('Noble', 'Established nobility with significant holdings', 8),
('Court Official', 'High-ranking government position', 8),
('Baron/Baroness', 'Low-tier noble with hereditary lands', 8),

-- High Nobility
('Count/Countess', 'Mid-tier noble ruling large territories', 9),
('Duke/Duchess', 'High-tier noble with extensive domains', 9),
('High Noble', 'Major noble house with significant power', 9),

-- Royalty & Highest Tier
('Prince/Princess', 'Royal family member, heir to throne', 10),
('King/Queen', 'Monarch, ultimate authority', 10),
('Emperor/Empress', 'Ruler of multiple kingdoms or vast empire', 10),

-- Special Categories
('Religious Leader', 'High-ranking religious authority', 8),
('Archmage', 'Most powerful magical practitioner', 8),
('Legendary Hero', 'Renowned for great deeds', 9),
('Divine Avatar', 'Representative or embodiment of deity', 10);

-- Index for influence level queries
CREATE INDEX idx_social_statuses_influence ON public.social_statuses (influence_level);
CREATE INDEX idx_social_statuses_name_search ON public.social_statuses USING gin(to_tsvector('english', name));

-- Comments
COMMENT ON TABLE public.social_statuses IS 'Social hierarchy classifications with influence power ratings';
COMMENT ON COLUMN public.social_statuses.influence_level IS 'Social influence rating from 1 (lowest) to 10 (highest)';