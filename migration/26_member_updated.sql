ALTER TABLE public.member ADD COLUMN updated timestamp DEFAULT CURRENT_TIMESTAMP NOT NULL;

CREATE OR REPLACE FUNCTION update_updated_column()
RETURNS TRIGGER AS $$
BEGIN
   NEW.updated = now(); 
   RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_member_updated BEFORE UPDATE
    ON public.member FOR EACH ROW EXECUTE PROCEDURE
    update_updated_column();



CREATE OR REPLACE FUNCTION notify_member_update()
RETURNS TRIGGER AS $$
BEGIN
    PERFORM pg_notify(
        CAST('member_updated' AS text),
        row_to_json(NEW)::text
    );
  RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER notify_member_inserted
  AFTER INSERT ON public.member
  FOR EACH ROW
  EXECUTE PROCEDURE notify_member_update();

CREATE TRIGGER notify_member_updated
  AFTER UPDATE ON public.member
  FOR EACH ROW
  EXECUTE PROCEDURE notify_member_update();
