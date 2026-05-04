ALTER TABLE IF EXISTS public.machine ADD COLUMN import_enabled boolean NOT NULL DEFAULT false;

ALTER TABLE IF EXISTS public.machine ADD COLUMN import_message character varying(200);
