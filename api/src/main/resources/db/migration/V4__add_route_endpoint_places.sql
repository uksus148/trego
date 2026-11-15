ALTER TABLE routes
    ADD COLUMN start_place_id uuid REFERENCES places(id) ON DELETE RESTRICT,
    ADD COLUMN end_place_id uuid REFERENCES places(id) ON DELETE RESTRICT;

CREATE INDEX routes_start_place_idx ON routes(start_place_id) WHERE start_place_id IS NOT NULL;
CREATE INDEX routes_end_place_idx ON routes(end_place_id) WHERE end_place_id IS NOT NULL;
