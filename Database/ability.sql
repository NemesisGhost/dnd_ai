-- Table: public.ability

-- DROP TABLE IF EXISTS public.ability;

CREATE TABLE IF NOT EXISTS public.ability
(
    ability_id integer NOT NULL DEFAULT nextval('ability_ability_id_seq'::regclass),
    name character varying(100) COLLATE pg_catalog."default" NOT NULL,
    description text COLLATE pg_catalog."default",
    CONSTRAINT ability_pkey PRIMARY KEY (ability_id),
    CONSTRAINT ability_name_key UNIQUE (name)
)

TABLESPACE pg_default;

ALTER TABLE IF EXISTS public.ability
    OWNER to postgres;
