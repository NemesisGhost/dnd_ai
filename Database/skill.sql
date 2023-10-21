-- Table: public.skill

-- DROP TABLE IF EXISTS public.skill;

CREATE TABLE IF NOT EXISTS public.skill
(
    skill_id integer NOT NULL DEFAULT nextval('skill_skill_id_seq'::regclass),
    name character varying(100) COLLATE pg_catalog.'default' NOT NULL,
    CONSTRAINT skill_pkey PRIMARY KEY (skill_id),
    CONSTRAINT skill_name_key UNIQUE (name)
)

TABLESPACE pg_default;

ALTER TABLE IF EXISTS public.skill
    OWNER to postgres;
	
INSERT INTO skill(name)
VALUES ('Acrobatics'), ('Animal Handling'), ('Arcana'), ('Athletics'), ('Deception'), ('History'), ('Insight'), ('Intimidation'), ('Investigation')
	('Medicine'), ('Nature'), ('Perception'), ('Performance'), ('Persuasion'), ('Religion'), ('Sleight of Hand'), ('Stealth'), ('Survival')