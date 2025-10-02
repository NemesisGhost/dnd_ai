-- =====================================================
-- Locations-Languages Many-to-Many Join Table
-- =====================================================

DROP TABLE IF EXISTS public.locations_languages CASCADE;
CREATE TABLE public.locations_languages (
    location_id UUID NOT NULL REFERENCES public.locations(location_id) ON DELETE CASCADE,
    language_id UUID NOT NULL REFERENCES public.languages(language_id) ON DELETE CASCADE,
    PRIMARY KEY (location_id, language_id)
);

-- Index for fast lookup of languages by location
CREATE INDEX idx_locations_languages_location ON public.locations_languages (location_id);
CREATE INDEX idx_locations_languages_language ON public.locations_languages (language_id);
