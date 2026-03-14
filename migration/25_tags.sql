CREATE TABLE public.tag
(
    id integer NOT NULL GENERATED ALWAYS AS IDENTITY,
    title character varying(128) NOT NULL
);

ALTER TABLE public.tag ADD CONSTRAINT tag_pkey PRIMARY KEY (id);

CREATE TABLE public.machine_tag
(
    machine_id integer NOT NULL,
    tag_id integer NOT NULL,
    PRIMARY KEY (machine_id, tag_id),
    FOREIGN KEY (machine_id)
        REFERENCES public.machine (id) MATCH SIMPLE
        ON UPDATE CASCADE
        ON DELETE CASCADE
        NOT VALID,
    FOREIGN KEY (tag_id)
        REFERENCES public.tag (id) MATCH SIMPLE
        ON UPDATE CASCADE
        ON DELETE CASCADE
        NOT VALID
);
