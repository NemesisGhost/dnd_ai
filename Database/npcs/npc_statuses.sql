-- =====================================================
-- NPC Status Lookup Table
-- =====================================================

DROP TABLE IF EXISTS public.npc_statuses CASCADE;

CREATE TABLE public.npc_statuses (
    status_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(50) NOT NULL UNIQUE,
    description TEXT,
    is_active BOOLEAN DEFAULT true, -- Whether this status indicates an active/available NPC
    sort_order INTEGER,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

INSERT INTO public.npc_statuses (name, description, is_active, sort_order) VALUES
-- Active States
('Active', 'Currently available and engaged in normal activities', true, 1),
('Available', 'Present and willing to interact', true, 2),
('Busy', 'Occupied but may be interrupted', true, 3),
('Working', 'Engaged in their occupation or duties', true, 4),

-- Travel/Movement States  
('Traveling', 'Away from usual location, moving between places', false, 10),
('On Journey', 'Undertaking a specific trip or quest', false, 11),
('Visiting', 'Temporarily at a different location', true, 12),
('Returning', 'In the process of coming back to normal location', true, 13),

-- Temporary Unavailability
('Resting', 'Taking a break or sleeping', false, 20),
('Ill', 'Sick or recovering from illness', false, 21),
('Injured', 'Wounded and recovering', false, 22),
('Detained', 'Held against their will or under arrest', false, 23),
('In Hiding', 'Concealed for safety or other reasons', false, 24),

-- Social/Political States
('In Meeting', 'Engaged in important discussions or negotiations', false, 30),
('At Court', 'Attending royal or noble court functions', false, 31),
('On Duty', 'Performing official responsibilities', true, 32),
('Off Duty', 'Not currently working but available', true, 33),

-- Permanent/Long-term States
('Retired', 'No longer active in their former role', true, 40),
('Exiled', 'Banished from their home location', true, 41),
('Missing', 'Whereabouts unknown', false, 42),
('Dead', 'Deceased', false, 43),
('Transformed', 'Magically or otherwise changed form', true, 44),

-- Special States
('Imprisoned', 'Locked up in jail or dungeon', false, 50),
('Cursed', 'Under the effect of a magical curse', true, 51),
('Possessed', 'Controlled by an external entity', true, 52),
('Sleeping', 'Magically or naturally asleep for extended period', false, 53),
('Petrified', 'Turned to stone or similar condition', false, 54);

-- Index for common queries
CREATE INDEX idx_npc_statuses_active ON public.npc_statuses (is_active);
CREATE INDEX idx_npc_statuses_sort ON public.npc_statuses (sort_order);

-- Comments
COMMENT ON TABLE public.npc_statuses IS 'Standardized current status values for NPCs indicating availability and condition';
COMMENT ON COLUMN public.npc_statuses.is_active IS 'Whether NPCs with this status are generally available for interaction';