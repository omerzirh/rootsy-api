-- =============================================================================
-- Rootsy - Garden Planning App - Supabase Database Schema
-- Run this in your Supabase SQL editor.
-- =============================================================================


-- ---------------------------------------------------------------------------
-- TABLES
-- ---------------------------------------------------------------------------

-- User profiles (extends Supabase auth.users)
CREATE TABLE IF NOT EXISTS user_profiles (
  id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  display_name TEXT,
  location_lat FLOAT,
  location_lng FLOAT,
  location_name TEXT,
  hardiness_zone TEXT,
  language_preference TEXT DEFAULT 'en',
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Plant encyclopedia: curated 50 common garden plants + Trefle fallback cache
CREATE TABLE IF NOT EXISTS plants (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  trefle_id INTEGER UNIQUE,
  common_name TEXT NOT NULL,
  scientific_name TEXT,
  family TEXT,
  plant_type TEXT DEFAULT 'vegetable',
  cycle TEXT,
  watering TEXT,
  sunlight JSONB DEFAULT '[]',
  hardiness_zones JSONB DEFAULT '[]',
  growth_rate TEXT,
  care_level TEXT,
  description TEXT,
  image_url TEXT,
  sowing_info JSONB,
  harvest_days_min INTEGER,
  harvest_days_max INTEGER,
  companions JSONB DEFAULT '[]',
  avoid_near JSONB DEFAULT '[]',
  fetched_at TIMESTAMPTZ DEFAULT NOW(),
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- User's gardens
CREATE TABLE IF NOT EXISTS gardens (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  name TEXT NOT NULL DEFAULT 'My Garden',
  width_meters FLOAT NOT NULL DEFAULT 10.0,
  height_meters FLOAT NOT NULL DEFAULT 10.0,
  background_photo_url TEXT,
  notes TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Garden beds/zones within a garden (freeform positioning)
CREATE TABLE IF NOT EXISTS garden_beds (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  garden_id UUID NOT NULL REFERENCES gardens(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  bed_type TEXT NOT NULL DEFAULT 'raised'
    CHECK (bed_type IN ('raised', 'in_ground', 'container', 'greenhouse')),
  x_position FLOAT NOT NULL DEFAULT 0,
  y_position FLOAT NOT NULL DEFAULT 0,
  width FLOAT NOT NULL DEFAULT 1.2,
  height FLOAT NOT NULL DEFAULT 2.4,
  rotation FLOAT NOT NULL DEFAULT 0,
  soil_type TEXT,
  color TEXT DEFAULT '#A0785A',
  notes TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Individual plantings (a plant placed in a bed at a specific time)
CREATE TABLE IF NOT EXISTS plantings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  garden_bed_id UUID NOT NULL REFERENCES garden_beds(id) ON DELETE CASCADE,
  plant_id UUID NOT NULL REFERENCES plants(id),
  position_x FLOAT NOT NULL DEFAULT 0,
  position_y FLOAT NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'planted'
    CHECK (status IN ('planned', 'seeded', 'sprouted', 'growing', 'flowering', 'fruiting', 'harvested', 'removed')),
  planted_date DATE,
  expected_harvest_date DATE,
  actual_harvest_date DATE,
  quantity INTEGER DEFAULT 1,
  notes TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Planting progress photos/notes timeline
CREATE TABLE IF NOT EXISTS planting_progress (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  planting_id UUID NOT NULL REFERENCES plantings(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  photo_url TEXT,
  note TEXT,
  growth_stage TEXT
    CHECK (growth_stage IS NULL OR growth_stage IN ('seeded', 'sprouted', 'growing', 'flowering', 'fruiting', 'harvested')),
  recorded_at TIMESTAMPTZ DEFAULT NOW(),
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Care tasks and reminders
CREATE TABLE IF NOT EXISTS care_tasks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  planting_id UUID REFERENCES plantings(id) ON DELETE SET NULL,
  garden_bed_id UUID REFERENCES garden_beds(id) ON DELETE SET NULL,
  task_type TEXT NOT NULL DEFAULT 'custom'
    CHECK (task_type IN ('water', 'fertilize', 'prune', 'harvest', 'pest_check', 'weed', 'mulch', 'custom')),
  title TEXT NOT NULL,
  description TEXT,
  due_date DATE,
  due_time TIME,
  is_recurring BOOLEAN DEFAULT FALSE,
  recurrence_days INTEGER,
  is_completed BOOLEAN DEFAULT FALSE,
  completed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Weather data cache (per location per day)
CREATE TABLE IF NOT EXISTS weather_cache (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  location_lat FLOAT NOT NULL,
  location_lng FLOAT NOT NULL,
  date DATE NOT NULL,
  temp_high_c FLOAT,
  temp_low_c FLOAT,
  humidity_pct INTEGER,
  rain_mm FLOAT,
  sun_hours FLOAT,
  wind_speed_kmh FLOAT,
  conditions TEXT,
  uv_index FLOAT,
  raw_data JSONB,
  fetched_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(location_lat, location_lng, date)
);

-- AI conversation history
CREATE TABLE IF NOT EXISTS ai_conversations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
  content TEXT NOT NULL,
  metadata JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- AI plant diagnoses (image-based checkups). planting_id is nullable so users
-- can diagnose an untracked plant from the general Plants-tab flow.
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


-- ---------------------------------------------------------------------------
-- INDEXES
-- ---------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS idx_plants_common_name ON plants USING gin(to_tsvector('english', common_name));
CREATE INDEX IF NOT EXISTS idx_plants_trefle_id ON plants(trefle_id);
CREATE INDEX IF NOT EXISTS idx_plants_plant_type ON plants(plant_type);

CREATE INDEX IF NOT EXISTS idx_gardens_user_id ON gardens(user_id);
CREATE INDEX IF NOT EXISTS idx_garden_beds_garden_id ON garden_beds(garden_id);
CREATE INDEX IF NOT EXISTS idx_garden_beds_user_id ON garden_beds(user_id);

CREATE INDEX IF NOT EXISTS idx_plantings_user_id ON plantings(user_id);
CREATE INDEX IF NOT EXISTS idx_plantings_garden_bed_id ON plantings(garden_bed_id);
CREATE INDEX IF NOT EXISTS idx_plantings_plant_id ON plantings(plant_id);
CREATE INDEX IF NOT EXISTS idx_plantings_status ON plantings(user_id, status);

CREATE INDEX IF NOT EXISTS idx_planting_progress_planting_id ON planting_progress(planting_id);
CREATE INDEX IF NOT EXISTS idx_planting_progress_user_id ON planting_progress(user_id);

CREATE INDEX IF NOT EXISTS idx_care_tasks_user_id ON care_tasks(user_id);
CREATE INDEX IF NOT EXISTS idx_care_tasks_due_date ON care_tasks(user_id, due_date);
CREATE INDEX IF NOT EXISTS idx_care_tasks_pending ON care_tasks(user_id, is_completed, due_date)
  WHERE is_completed = FALSE;

CREATE INDEX IF NOT EXISTS idx_weather_cache_location_date ON weather_cache(location_lat, location_lng, date);
CREATE INDEX IF NOT EXISTS idx_ai_conversations_user_id ON ai_conversations(user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_plant_diagnoses_user_id ON plant_diagnoses(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_plant_diagnoses_planting_id ON plant_diagnoses(planting_id, created_at DESC);


-- ---------------------------------------------------------------------------
-- UPDATED_AT TRIGGER
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_user_profiles_updated_at
  BEFORE UPDATE ON user_profiles FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER trigger_gardens_updated_at
  BEFORE UPDATE ON gardens FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER trigger_garden_beds_updated_at
  BEFORE UPDATE ON garden_beds FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER trigger_plantings_updated_at
  BEFORE UPDATE ON plantings FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER trigger_care_tasks_updated_at
  BEFORE UPDATE ON care_tasks FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();


-- ---------------------------------------------------------------------------
-- ROW LEVEL SECURITY
-- ---------------------------------------------------------------------------

ALTER TABLE user_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE plants ENABLE ROW LEVEL SECURITY;
ALTER TABLE gardens ENABLE ROW LEVEL SECURITY;
ALTER TABLE garden_beds ENABLE ROW LEVEL SECURITY;
ALTER TABLE plantings ENABLE ROW LEVEL SECURITY;
ALTER TABLE planting_progress ENABLE ROW LEVEL SECURITY;
ALTER TABLE care_tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE weather_cache ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE plant_diagnoses ENABLE ROW LEVEL SECURITY;

-- plants: authenticated users can read, service_role can write (API caches Trefle data)
CREATE POLICY "plants_read" ON plants FOR SELECT TO authenticated USING (true);
CREATE POLICY "plants_write_service" ON plants FOR ALL TO service_role USING (true) WITH CHECK (true);

-- weather_cache: authenticated users can read, service_role writes
CREATE POLICY "weather_read" ON weather_cache FOR SELECT TO authenticated USING (true);
CREATE POLICY "weather_write_service" ON weather_cache FOR ALL TO service_role USING (true) WITH CHECK (true);

-- user_profiles: own row only
CREATE POLICY "profiles_select" ON user_profiles FOR SELECT TO authenticated USING (auth.uid() = id);
CREATE POLICY "profiles_insert" ON user_profiles FOR INSERT TO authenticated WITH CHECK (auth.uid() = id);
CREATE POLICY "profiles_update" ON user_profiles FOR UPDATE TO authenticated USING (auth.uid() = id) WITH CHECK (auth.uid() = id);
CREATE POLICY "profiles_service" ON user_profiles FOR ALL TO service_role USING (true) WITH CHECK (true);

-- gardens: user_id isolation
CREATE POLICY "gardens_select" ON gardens FOR SELECT TO authenticated USING (auth.uid() = user_id);
CREATE POLICY "gardens_insert" ON gardens FOR INSERT TO authenticated WITH CHECK (auth.uid() = user_id);
CREATE POLICY "gardens_update" ON gardens FOR UPDATE TO authenticated USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);
CREATE POLICY "gardens_delete" ON gardens FOR DELETE TO authenticated USING (auth.uid() = user_id);
CREATE POLICY "gardens_service" ON gardens FOR ALL TO service_role USING (true) WITH CHECK (true);

-- garden_beds: user_id isolation
CREATE POLICY "beds_select" ON garden_beds FOR SELECT TO authenticated USING (auth.uid() = user_id);
CREATE POLICY "beds_insert" ON garden_beds FOR INSERT TO authenticated WITH CHECK (auth.uid() = user_id);
CREATE POLICY "beds_update" ON garden_beds FOR UPDATE TO authenticated USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);
CREATE POLICY "beds_delete" ON garden_beds FOR DELETE TO authenticated USING (auth.uid() = user_id);
CREATE POLICY "beds_service" ON garden_beds FOR ALL TO service_role USING (true) WITH CHECK (true);

-- plantings: user_id isolation
CREATE POLICY "plantings_select" ON plantings FOR SELECT TO authenticated USING (auth.uid() = user_id);
CREATE POLICY "plantings_insert" ON plantings FOR INSERT TO authenticated WITH CHECK (auth.uid() = user_id);
CREATE POLICY "plantings_update" ON plantings FOR UPDATE TO authenticated USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);
CREATE POLICY "plantings_delete" ON plantings FOR DELETE TO authenticated USING (auth.uid() = user_id);
CREATE POLICY "plantings_service" ON plantings FOR ALL TO service_role USING (true) WITH CHECK (true);

-- planting_progress: user_id isolation
CREATE POLICY "progress_select" ON planting_progress FOR SELECT TO authenticated USING (auth.uid() = user_id);
CREATE POLICY "progress_insert" ON planting_progress FOR INSERT TO authenticated WITH CHECK (auth.uid() = user_id);
CREATE POLICY "progress_delete" ON planting_progress FOR DELETE TO authenticated USING (auth.uid() = user_id);
CREATE POLICY "progress_service" ON planting_progress FOR ALL TO service_role USING (true) WITH CHECK (true);

-- care_tasks: user_id isolation
CREATE POLICY "tasks_select" ON care_tasks FOR SELECT TO authenticated USING (auth.uid() = user_id);
CREATE POLICY "tasks_insert" ON care_tasks FOR INSERT TO authenticated WITH CHECK (auth.uid() = user_id);
CREATE POLICY "tasks_update" ON care_tasks FOR UPDATE TO authenticated USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);
CREATE POLICY "tasks_delete" ON care_tasks FOR DELETE TO authenticated USING (auth.uid() = user_id);
CREATE POLICY "tasks_service" ON care_tasks FOR ALL TO service_role USING (true) WITH CHECK (true);

-- ai_conversations: user_id isolation
CREATE POLICY "ai_select" ON ai_conversations FOR SELECT TO authenticated USING (auth.uid() = user_id);
CREATE POLICY "ai_insert" ON ai_conversations FOR INSERT TO authenticated WITH CHECK (auth.uid() = user_id);
CREATE POLICY "ai_delete" ON ai_conversations FOR DELETE TO authenticated USING (auth.uid() = user_id);
CREATE POLICY "ai_service" ON ai_conversations FOR ALL TO service_role USING (true) WITH CHECK (true);

-- plant_diagnoses: own rows only
CREATE POLICY "diagnoses_select" ON plant_diagnoses FOR SELECT TO authenticated USING (auth.uid() = user_id);
CREATE POLICY "diagnoses_insert" ON plant_diagnoses FOR INSERT TO authenticated WITH CHECK (auth.uid() = user_id);
CREATE POLICY "diagnoses_delete" ON plant_diagnoses FOR DELETE TO authenticated USING (auth.uid() = user_id);
CREATE POLICY "diagnoses_service" ON plant_diagnoses FOR ALL TO service_role USING (true) WITH CHECK (true);


-- ---------------------------------------------------------------------------
-- AUTO-CREATE USER PROFILE ON SIGNUP
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
  INSERT INTO user_profiles (id)
  VALUES (NEW.id)
  ON CONFLICT (id) DO NOTHING;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION handle_new_user();


-- ---------------------------------------------------------------------------
-- STORAGE BUCKETS (run in Supabase dashboard or via API)
-- ---------------------------------------------------------------------------
-- Bucket: plant-photos
--   Private: true
--   Allowed MIME types: image/jpeg, image/png, image/webp
--   Max file size: 5242880 (5MB)
--   Path convention: {user_id}/{planting_id}/{timestamp}.jpg
--
-- Bucket: garden-photos
--   Private: true
--   Allowed MIME types: image/jpeg, image/png, image/webp
--   Max file size: 10485760 (10MB)
--   Path convention: {user_id}/{garden_id}/background.jpg
