1-- Table: public.race

-- DROP TABLE IF EXISTS public.race;

CREATE TABLE IF NOT EXISTS public.race
(
    race_id integer NOT NULL DEFAULT nextval('race_race_id_seq'::regclass),
    name character varying(100) COLLATE pg_catalog.'default' NOT NULL,
    CONSTRAINT race_pkey PRIMARY KEY (race_id),
    CONSTRAINT race_name_key UNIQUE (name)
)

TABLESPACE pg_default;

ALTER TABLE IF EXISTS public.race
    OWNER to postgres;
	
INSERT INTO race(name)
VALUES ('Aarakocra'), ('Aasimar'), ('Bugbear'), ('Centaur'), ('Changeling'), ('Deep Gnome'), ('Dragonborn'), ('Duergar'), ('Dwarf'),('Eladrin'),
	('Elf'), ('Fairy'), ('Firbolg'), ('Genasi (Air)'), ('Genasi (Earth)'), ('Genasi (Fire)'), ('Genasi (Water)'), ('Githyanki'), ('Githzerai'),
	('Gnome'), ('Goblin'), ('Goliath'), ('Grung'), ('Half-Elf'), ('Half-Orc'), ('Halfling'), ('Harengon'), ('Hobgoblin'), ('Human'), ('Kenku'),
	('Kobold'), ('Lizardfolk'), ('Locathah'), ('Minotaur'), ('Orc'), ('Owlin'), ('Satyr'), ('Sea Elf'), ('Shadar-Kai'), ('Shifter'), ('Tabaxi'),
	('Tiefling'), ('Tortle'), ('Triton'), ('Verdan'), ('Yuan-Ti')