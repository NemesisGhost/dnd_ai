-- Table: public.race_ability

-- DROP TABLE IF EXISTS public.race_ability;

CREATE TABLE IF NOT EXISTS public.race_ability
(
    race_id integer NOT NULL,
    ability_id integer NOT NULL,
    CONSTRAINT race_ability_pkey PRIMARY KEY (race_id, ability_id),
    CONSTRAINT race_ability_ability_id_fkey FOREIGN KEY (ability_id)
        REFERENCES public.ability (ability_id) MATCH SIMPLE
        ON UPDATE NO ACTION
        ON DELETE NO ACTION,
    CONSTRAINT race_ability_race_id_fkey FOREIGN KEY (race_id)
        REFERENCES public.race (race_id) MATCH SIMPLE
        ON UPDATE NO ACTION
        ON DELETE NO ACTION
)

TABLESPACE pg_default;

ALTER TABLE IF EXISTS public.race_ability
    OWNER to postgres;