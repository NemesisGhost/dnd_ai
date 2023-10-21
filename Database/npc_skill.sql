-- Table: public.npc_skill

-- DROP TABLE IF EXISTS public.npc_skill;

CREATE TABLE IF NOT EXISTS public.npc_skill
(
    npc_id integer NOT NULL,
    skill_id integer NOT NULL,
    proficiency_bonus integer,
    expert boolean,
    CONSTRAINT npc_skill_pkey PRIMARY KEY (npc_id, skill_id),
    CONSTRAINT npc_skill_npc_id_fkey FOREIGN KEY (npc_id)
        REFERENCES public.npc (npc_id) MATCH SIMPLE
        ON UPDATE NO ACTION
        ON DELETE NO ACTION,
    CONSTRAINT npc_skill_skill_id_fkey FOREIGN KEY (skill_id)
        REFERENCES public.skill (skill_id) MATCH SIMPLE
        ON UPDATE NO ACTION
        ON DELETE NO ACTION
)

TABLESPACE pg_default;

ALTER TABLE IF EXISTS public.npc_skill
    OWNER to postgres;