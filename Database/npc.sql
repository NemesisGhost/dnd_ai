-- Table: public.npc

-- DROP TABLE IF EXISTS public.npc;

CREATE TABLE IF NOT EXISTS public.npc
(
    npc_id integer NOT NULL DEFAULT nextval('npc_npc_id_seq'::regclass),
    name character varying(100) COLLATE pg_catalog."default" NOT NULL,
    race_id integer,
    class_id integer,
    level integer,
    background text COLLATE pg_catalog."default",
    personality text COLLATE pg_catalog."default",
    description text COLLATE pg_catalog."default",
    speech_pattern text COLLATE pg_catalog."default",
    CONSTRAINT npc_pkey PRIMARY KEY (npc_id),
    CONSTRAINT npc_class_id_fkey FOREIGN KEY (class_id)
        REFERENCES public.class (class_id) MATCH SIMPLE
        ON UPDATE NO ACTION
        ON DELETE NO ACTION,
    CONSTRAINT npc_race_id_fkey FOREIGN KEY (race_id)
        REFERENCES public.race (race_id) MATCH SIMPLE
        ON UPDATE NO ACTION
        ON DELETE NO ACTION
)

TABLESPACE pg_default;

ALTER TABLE IF EXISTS public.npc
    OWNER to postgres;