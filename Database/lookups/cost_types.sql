-- =====================================================
-- Costs/Compensation Types Lookup Table
-- =====================================================

DROP TABLE IF EXISTS public.cost_types CASCADE;

CREATE TABLE public.cost_types (
    cost_type_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    category VARCHAR(50), -- Monetary, Barter, Service, Favor, Mixed, etc.
    is_monetary BOOLEAN DEFAULT TRUE, -- Whether this involves actual currency
    typical_range TEXT, -- General range or structure for this cost type
    examples TEXT, -- Specific examples of this cost type
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Insert common cost/compensation types
INSERT INTO public.cost_types (name, description, category, is_monetary, typical_range, examples) VALUES

-- Monetary Types
('Fixed Gold Amount', 'Specific amount of gold pieces', 'Monetary', TRUE, '1-1000+ gold pieces', '25 gold pieces, 150 gold pieces'),
('Variable Gold Range', 'Range of gold pieces depending on factors', 'Monetary', TRUE, '10-100 gold pieces', '10-50 gold depending on complexity'),
('Copper/Silver Amount', 'Lower denomination currency', 'Monetary', TRUE, '1-100 silver/copper', '5 silver pieces, 50 copper coins'),
('Percentage of Value', 'Percentage of item/service value', 'Monetary', TRUE, '5-25% of total value', '10% of item value, 20% of profits'),

-- Employment Compensation
('Hourly Wage', 'Payment per hour worked', 'Monetary', TRUE, '1-10 gold per hour', '2 gold per hour, 5 silver per hour'),
('Daily Wage', 'Payment per day worked', 'Monetary', TRUE, '5-50 gold per day', '10 gold per day, 25 gold per day'),
('Weekly Salary', 'Fixed weekly payment', 'Monetary', TRUE, '20-200 gold per week', '50 gold per week, 100 gold per week'),
('Monthly Salary', 'Fixed monthly payment', 'Monetary', TRUE, '100-1000 gold per month', '300 gold per month, 500 gold per month'),
('Commission Based', 'Payment based on sales/results', 'Monetary', TRUE, '10-30% commission', '15% of sales, 25% of contracts closed'),
('Profit Sharing', 'Share of business profits', 'Monetary', TRUE, '5-50% of profits', '10% of monthly profits, 25% of yearly profits'),

-- Non-Monetary Types
('Room and Board', 'Free housing and meals', 'Service', FALSE, 'Basic to luxury accommodations', 'Small room and meals, luxury suite and fine dining'),
('Barter Trade', 'Exchange of goods or services', 'Barter', FALSE, 'Equivalent value exchange', 'Sword for armor repair, information for healing'),
('Personal Favor', 'Owe a favor to be called in later', 'Favor', FALSE, 'Single favor of reasonable scope', 'One favor within reason, help when needed'),
('Multiple Favors', 'Owe several favors over time', 'Favor', FALSE, '2-5 favors of varying scope', 'Three small favors, two significant favors'),
('Information Exchange', 'Trade information for information', 'Barter', FALSE, 'Equivalent information value', 'Secret for secret, rumor for rumor'),
('Service Exchange', 'Trade service for service', 'Barter', FALSE, 'Equivalent service value', 'Healing for protection, teaching for crafting'),

-- Mixed/Special Types
('Free Service', 'No payment required', 'Service', FALSE, 'Completely free', 'Given freely, no cost, charity'),
('Donation Based', 'Pay what you can/want', 'Mixed', TRUE, 'Voluntary payment', 'Whatever you can afford, suggested donation'),
('Membership Fee', 'Payment for ongoing access', 'Monetary', TRUE, '10-100 gold annually', '25 gold yearly membership, 50 gold per year'),
('Materials Cost Only', 'Cost of materials plus small fee', 'Monetary', TRUE, 'Material cost + 10-50%', 'Materials plus 20%, raw cost plus markup'),
('Reputation Payment', 'Payment in reputation/standing', 'Service', FALSE, 'Social credit or standing', 'Good word to contacts, recommendation letter'),
('Apprenticeship Terms', 'Work in exchange for training', 'Service', FALSE, '6 months to 3 years service', 'One year service, two years apprenticeship'),

-- Risk-Based Types
('High Risk Premium', 'Extra payment for dangerous work', 'Monetary', TRUE, '150-300% normal rate', 'Double normal fee, triple payment'),
('Success Bonus', 'Extra payment for successful completion', 'Monetary', TRUE, '25-100% bonus', '50% bonus on success, double pay if successful'),
('Retainer Fee', 'Upfront payment to secure services', 'Monetary', TRUE, '25-50% of total cost', 'Half payment upfront, 100 gold retainer'),
('Completion Payment', 'Payment only upon successful completion', 'Monetary', TRUE, 'Full payment on success', 'All payment on completion, no payment if failed'),

-- Special Circumstances
('Family Discount', 'Reduced rate for family members', 'Monetary', TRUE, '25-75% normal rate', 'Half price for family, 25% discount'),
('Friend Rate', 'Reduced rate for friends', 'Monetary', TRUE, '50-90% normal rate', '10% discount for friends, friend pricing'),
('Bulk Discount', 'Reduced rate for multiple services', 'Monetary', TRUE, '10-30% reduction', '20% off for 5+ items, bulk rate'),
('First Time Discount', 'Reduced rate for new customers', 'Monetary', TRUE, '10-25% reduction', '15% off first service, new customer rate'),
('Loyalty Reward', 'Benefits for repeat customers', 'Mixed', TRUE, 'Various rewards/discounts', 'Every 10th free, loyalty points'),

-- Illegal/Criminal Types
('Blood Money', 'Payment for illegal/immoral acts', 'Monetary', TRUE, '100-10000 gold', '500 gold for assassination, 1000 gold for betrayal'),
('Hush Money', 'Payment for silence/secrecy', 'Monetary', TRUE, '50-1000 gold', '100 gold to keep quiet, 500 gold for silence'),
('Protection Fee', 'Payment to avoid trouble', 'Monetary', TRUE, '10-100 gold regularly', '25 gold monthly protection, 50 gold per week'),
('Blackmail Payment', 'Payment to prevent exposure', 'Monetary', TRUE, '100-5000 gold', '200 gold to avoid scandal, 1000 gold for secrets');

-- Indexes
CREATE INDEX idx_cost_types_category ON public.cost_types (category);
CREATE INDEX idx_cost_types_monetary ON public.cost_types (is_monetary);
CREATE INDEX idx_cost_types_name_search ON public.cost_types USING gin(to_tsvector('english', name));

-- Comments
COMMENT ON TABLE public.cost_types IS 'Standardized cost and compensation types for services, employment, and transactions';
COMMENT ON COLUMN public.cost_types.category IS 'High-level grouping: Monetary, Barter, Service, Favor, Mixed, etc.';
COMMENT ON COLUMN public.cost_types.is_monetary IS 'Whether this cost type involves actual currency exchange';
COMMENT ON COLUMN public.cost_types.typical_range IS 'General range or structure description for this cost type';
COMMENT ON COLUMN public.cost_types.examples IS 'Specific examples to help understand this cost type';