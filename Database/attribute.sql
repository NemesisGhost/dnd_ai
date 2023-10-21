-- Table: public.attribute

-- DROP TABLE IF EXISTS public.attribute;

CREATE TABLE IF NOT EXISTS public.attribute
(
    attribute_id integer NOT NULL DEFAULT nextval('attribute_attribute_id_seq'::regclass),
    name character varying(100) COLLATE pg_catalog.'default' NOT NULL,
    CONSTRAINT attribute_pkey PRIMARY KEY (attribute_id)
)

TABLESPACE pg_default;

ALTER TABLE IF EXISTS public.attribute
    OWNER to postgres;
	
INSERT INTO attribute(name)
VALUES('Strength'), ('Dexterity'), ('Constitution'), ('Intelligence'), ('Wisdom'), ('Charisma')