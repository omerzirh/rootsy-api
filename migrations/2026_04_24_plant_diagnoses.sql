-- Migration: plant diagnoses (AI checkup history)
-- Apply in Supabase SQL editor.

CREATE TABLE IF NOT EXISTS plant_diagnoses (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  planting_id UUID REFERENCES plantings(id) ON DELETE CASCADE,
  image_url TEXT,
  identified_as TEXT,
  stage TEXT,
  stage_label TEXT,
  estimated_age TEXT,
  health TEXT,
  health_score INTEGER,
  ready_to_transplant BOOLEAN,
  ready_to_harvest BOOLEAN,
  summary TEXT,
  confidence TEXT,
  issues JSONB DEFAULT '[]',
  recommendations JSONB DEFAULT '[]',
  weather_snapshot JSONB,
  plant_name_hint TEXT,
  user_note TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_plant_diagnoses_user_id ON plant_diagnoses(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_plant_diagnoses_planting_id ON plant_diagnoses(planting_id, created_at DESC);

ALTER TABLE plant_diagnoses ENABLE ROW LEVEL SECURITY;

CREATE POLICY "diagnoses_select" ON plant_diagnoses FOR SELECT TO authenticated USING (auth.uid() = user_id);
CREATE POLICY "diagnoses_insert" ON plant_diagnoses FOR INSERT TO authenticated WITH CHECK (auth.uid() = user_id);
CREATE POLICY "diagnoses_delete" ON plant_diagnoses FOR DELETE TO authenticated USING (auth.uid() = user_id);
CREATE POLICY "diagnoses_service" ON plant_diagnoses FOR ALL TO service_role USING (true) WITH CHECK (true);
