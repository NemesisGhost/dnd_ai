-- Table: public.class_ability

-- DROP TABLE IF EXISTS public.class_ability;

CREATE TABLE IF NOT EXISTS public.class_ability
(
    class_id integer NOT NULL,
    ability_id integer NOT NULL,
    CONSTRAINT class_ability_pkey PRIMARY KEY (class_id, ability_id),
    CONSTRAINT class_ability_ability_id_fkey FOREIGN KEY (ability_id)
        REFERENCES public.ability (ability_id) MATCH SIMPLE
        ON UPDATE NO ACTION
        ON DELETE NO ACTION,
    CONSTRAINT class_ability_class_id_fkey FOREIGN KEY (class_id)
        REFERENCES public.class (class_id) MATCH SIMPLE
        ON UPDATE NO ACTION
        ON DELETE NO ACTION
)

TABLESPACE pg_default;

ALTER TABLE IF EXISTS public.class_ability
    OWNER to postgres;