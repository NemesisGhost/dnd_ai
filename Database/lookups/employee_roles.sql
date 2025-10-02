-- =====================================================
-- Employee Roles Lookup Table
-- =====================================================

DROP TABLE IF EXISTS public.employee_roles CASCADE;

CREATE TABLE public.employee_roles (
    role_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    authority_level INTEGER DEFAULT 1, -- 1-10 scale of authority/responsibility
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Insert common employee roles
INSERT INTO public.employee_roles (name, description, authority_level) VALUES
('Owner', 'Business owner with full authority', 10),
('Manager', 'Day-to-day operations manager', 8),
('Assistant Manager', 'Secondary management role', 6),
('Supervisor', 'Oversees specific department or shift', 5),
('Senior Employee', 'Experienced worker with some authority', 4),
('Employee', 'Regular worker', 3),
('Apprentice', 'Learning the trade', 2),
('Temporary Worker', 'Short-term or seasonal help', 1),
('Partner', 'Co-owner or business partner', 9),
('Foreman', 'Leads work crews or projects', 6),
('Clerk', 'Administrative or record-keeping role', 3),
('Guard', 'Security and protection duties', 4),
('Artisan', 'Skilled craftsperson', 5),
('Merchant', 'Sales and customer relations', 4),
('Cook', 'Food preparation specialist', 3),
('Bartender', 'Serves drinks and manages bar area', 4),
('Stable Hand', 'Cares for animals and equipment', 2),
('Accountant', 'Manages finances and bookkeeping', 6),
('Secretary', 'Administrative support and correspondence', 4),
('Consultant', 'External advisor or specialist', 5);

-- Indexes
CREATE INDEX idx_employee_roles_authority ON public.employee_roles (authority_level DESC);

-- Comments
COMMENT ON TABLE public.employee_roles IS 'Standardized roles for business employees';
COMMENT ON COLUMN public.employee_roles.authority_level IS 'Level of authority and responsibility (1=lowest, 10=highest)';