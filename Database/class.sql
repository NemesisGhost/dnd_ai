-- Table: public.class

-- DROP TABLE IF EXISTS public.class;

CREATE TABLE IF NOT EXISTS public.class
(
    class_id integer NOT NULL DEFAULT nextval('class_class_id_seq'::regclass),
    name character varying(100) COLLATE pg_catalog.'default' NOT NULL,
    CONSTRAINT class_pkey PRIMARY KEY (class_id),
    CONSTRAINT class_name_key UNIQUE (name)
)

TABLESPACE pg_default;

ALTER TABLE IF EXISTS public.class
    OWNER to postgres;
	
INSERT INTO class(name)
VALUES ('Artificer'), ('Barbarian'), ('Bard'), ('Blood Hunter'), ('Cleric'), ('Druid'), ('Fighter'), ('Monk'), ('Paladin'), ('Ranger'), 
	('Rogue'), ('Sorcerer'), ('Warlock'), ('Wizard')