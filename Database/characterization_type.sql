-- Table: public.characterization_type

-- DROP TABLE IF EXISTS public.characterization_type;

CREATE TABLE IF NOT EXISTS public.characterization_type
(
    characterization_type_id SERIAL PRIMARY KEY,
    name character varying(100) COLLATE pg_catalog."default" NOT NULL
)

TABLESPACE pg_default;

ALTER TABLE IF EXISTS public.characterization_type
    OWNER to postgres;