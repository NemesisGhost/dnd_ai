-- =====================================================
-- Locations-Resources Many-to-Many Join Table
-- =====================================================

DROP TABLE IF EXISTS public.locations_resources CASCADE;
CREATE TABLE public.locations_resources (
    location_id UUID NOT NULL REFERENCES public.locations(location_id) ON DELETE CASCADE,
    resource_id UUID NOT NULL REFERENCES public.resources(resource_id) ON DELETE CASCADE,
    PRIMARY KEY (location_id, resource_id)
);

-- Index for fast lookup of resources by location
CREATE INDEX idx_locations_resources_location ON public.locations_resources (location_id);
CREATE INDEX idx_locations_resources_resource ON public.locations_resources (resource_id);
