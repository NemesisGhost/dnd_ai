-- Table: public.npc_characterization

-- DROP TABLE IF EXISTS public.npc_characterization;

CREATE TABLE IF NOT EXISTS public.npc_characterization
(
    characterization_id SERIAL PRIMARY KEY,
    npc_id integer,
    characterization_type_id integer,
    description text COLLATE pg_catalog."default",
    CONSTRAINT npc_characterization_characterization_type_id_fkey FOREIGN KEY (characterization_type_id)
        REFERENCES public.characterization_type (characterization_type_id) MATCH SIMPLE
        ON UPDATE NO ACTION
        ON DELETE NO ACTION,
    CONSTRAINT npc_characterization_npc_id_fkey FOREIGN KEY (npc_id)
        REFERENCES public.npc (npc_id) MATCH SIMPLE
        ON UPDATE NO ACTION
        ON DELETE NO ACTION
)

TABLESPACE pg_default;

ALTER TABLE IF EXISTS public.npc_characterization
    OWNER to postgres;