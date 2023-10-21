-- Table: public.npc_attribute

-- DROP TABLE IF EXISTS public.npc_attribute;

CREATE TABLE IF NOT EXISTS public.npc_attribute
(
    npc_id integer NOT NULL,
    attribute_id integer NOT NULL,
    value integer,
    CONSTRAINT npc_attribute_pkey PRIMARY KEY (npc_id, attribute_id),
    CONSTRAINT npc_attribute_attribute_id_fkey FOREIGN KEY (attribute_id)
        REFERENCES public.attribute (attribute_id) MATCH SIMPLE
        ON UPDATE NO ACTION
        ON DELETE NO ACTION,
    CONSTRAINT npc_attribute_npc_id_fkey FOREIGN KEY (npc_id)
        REFERENCES public.npc (npc_id) MATCH SIMPLE
        ON UPDATE NO ACTION
        ON DELETE NO ACTION
)

TABLESPACE pg_default;

ALTER TABLE IF EXISTS public.npc_attribute
    OWNER to postgres;