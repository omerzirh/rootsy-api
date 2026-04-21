from typing import Optional, List, Any, Dict
from datetime import datetime, date
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# User Profile
# ---------------------------------------------------------------------------

class UserProfileUpdate(BaseModel):
    display_name: Optional[str] = None
    location_lat: Optional[float] = None
    location_lng: Optional[float] = None
    location_name: Optional[str] = None
    hardiness_zone: Optional[str] = None
    language_preference: Optional[str] = None


class UserProfile(BaseModel):
    id: str
    display_name: Optional[str] = None
    location_lat: Optional[float] = None
    location_lng: Optional[float] = None
    location_name: Optional[str] = None
    hardiness_zone: Optional[str] = None
    language_preference: str = 'en'
    created_at: str
    updated_at: str


# ---------------------------------------------------------------------------
# Plants (Perenual cache)
# ---------------------------------------------------------------------------

class PlantSummary(BaseModel):
    id: str
    perenual_id: Optional[int] = None
    common_name: str
    scientific_name: Optional[str] = None
    plant_type: Optional[str] = None
    cycle: Optional[str] = None
    watering: Optional[str] = None
    care_level: Optional[str] = None
    image_url: Optional[str] = None
    harvest_days_min: Optional[int] = None
    harvest_days_max: Optional[int] = None


class PlantDetail(BaseModel):
    id: str
    perenual_id: Optional[int] = None
    common_name: str
    scientific_name: Optional[str] = None
    family: Optional[str] = None
    plant_type: Optional[str] = None
    cycle: Optional[str] = None
    watering: Optional[str] = None
    sunlight: List[str] = []
    hardiness_zones: List[str] = []
    growth_rate: Optional[str] = None
    care_level: Optional[str] = None
    description: Optional[str] = None
    image_url: Optional[str] = None
    sowing_info: Optional[Dict[str, Any]] = None
    harvest_days_min: Optional[int] = None
    harvest_days_max: Optional[int] = None
    companions: List[str] = []
    avoid_near: List[str] = []


class PlantSearchResponse(BaseModel):
    results: List[PlantSummary]
    total: int
    page: int


# ---------------------------------------------------------------------------
# Gardens
# ---------------------------------------------------------------------------

class CreateGardenRequest(BaseModel):
    name: str = 'My Garden'
    width_meters: float = 10.0
    height_meters: float = 10.0
    notes: Optional[str] = None


class UpdateGardenRequest(BaseModel):
    name: Optional[str] = None
    width_meters: Optional[float] = None
    height_meters: Optional[float] = None
    notes: Optional[str] = None
    background_photo_url: Optional[str] = None


class GardenSummary(BaseModel):
    id: str
    name: str
    width_meters: float
    height_meters: float
    background_photo_url: Optional[str] = None
    notes: Optional[str] = None
    bed_count: int = 0
    planting_count: int = 0
    created_at: str
    updated_at: str


# ---------------------------------------------------------------------------
# Garden Beds
# ---------------------------------------------------------------------------

class CreateBedRequest(BaseModel):
    name: str
    bed_type: str = 'raised'  # raised | in_ground | container | greenhouse
    x_position: float = 0.0
    y_position: float = 0.0
    width: float = 1.2
    height: float = 2.4
    rotation: float = 0.0
    soil_type: Optional[str] = None
    color: Optional[str] = None
    notes: Optional[str] = None


class UpdateBedRequest(BaseModel):
    name: Optional[str] = None
    bed_type: Optional[str] = None
    x_position: Optional[float] = None
    y_position: Optional[float] = None
    width: Optional[float] = None
    height: Optional[float] = None
    rotation: Optional[float] = None
    soil_type: Optional[str] = None
    color: Optional[str] = None
    notes: Optional[str] = None


class GardenBed(BaseModel):
    id: str
    garden_id: str
    name: str
    bed_type: str
    x_position: float
    y_position: float
    width: float
    height: float
    rotation: float = 0.0
    soil_type: Optional[str] = None
    color: Optional[str] = None
    notes: Optional[str] = None
    created_at: str
    updated_at: str


class GardenDetail(BaseModel):
    id: str
    name: str
    width_meters: float
    height_meters: float
    background_photo_url: Optional[str] = None
    notes: Optional[str] = None
    beds: List[GardenBed] = []
    created_at: str
    updated_at: str


# ---------------------------------------------------------------------------
# Plantings
# ---------------------------------------------------------------------------

class CreatePlantingRequest(BaseModel):
    garden_bed_id: str
    plant_id: str
    position_x: float = 0.0
    position_y: float = 0.0
    status: str = 'planted'
    planted_date: Optional[str] = None
    expected_harvest_date: Optional[str] = None
    quantity: int = 1
    notes: Optional[str] = None


class UpdatePlantingRequest(BaseModel):
    status: Optional[str] = None
    planted_date: Optional[str] = None
    expected_harvest_date: Optional[str] = None
    actual_harvest_date: Optional[str] = None
    quantity: Optional[int] = None
    notes: Optional[str] = None
    position_x: Optional[float] = None
    position_y: Optional[float] = None


class PlantingItem(BaseModel):
    id: str
    garden_bed_id: str
    plant_id: str
    plant_name: Optional[str] = None
    plant_image_url: Optional[str] = None
    position_x: float
    position_y: float
    status: str
    planted_date: Optional[str] = None
    expected_harvest_date: Optional[str] = None
    actual_harvest_date: Optional[str] = None
    quantity: int = 1
    notes: Optional[str] = None
    created_at: str
    updated_at: str


# ---------------------------------------------------------------------------
# Planting Progress
# ---------------------------------------------------------------------------

class AddProgressRequest(BaseModel):
    note: Optional[str] = None
    growth_stage: Optional[str] = None
    photo_url: Optional[str] = None


class ProgressEntry(BaseModel):
    id: str
    planting_id: str
    photo_url: Optional[str] = None
    note: Optional[str] = None
    growth_stage: Optional[str] = None
    recorded_at: str
    created_at: str


# ---------------------------------------------------------------------------
# Care Tasks
# ---------------------------------------------------------------------------

class CreateCareTaskRequest(BaseModel):
    title: str
    task_type: str = 'custom'
    description: Optional[str] = None
    planting_id: Optional[str] = None
    garden_bed_id: Optional[str] = None
    due_date: Optional[str] = None
    due_time: Optional[str] = None
    is_recurring: bool = False
    recurrence_days: Optional[int] = None


class UpdateCareTaskRequest(BaseModel):
    title: Optional[str] = None
    task_type: Optional[str] = None
    description: Optional[str] = None
    due_date: Optional[str] = None
    due_time: Optional[str] = None
    is_recurring: Optional[bool] = None
    recurrence_days: Optional[int] = None
    is_completed: Optional[bool] = None


class CareTask(BaseModel):
    id: str
    user_id: str
    planting_id: Optional[str] = None
    garden_bed_id: Optional[str] = None
    task_type: str
    title: str
    description: Optional[str] = None
    due_date: Optional[str] = None
    due_time: Optional[str] = None
    is_recurring: bool = False
    recurrence_days: Optional[int] = None
    is_completed: bool = False
    completed_at: Optional[str] = None
    created_at: str
    updated_at: str


# ---------------------------------------------------------------------------
# Weather
# ---------------------------------------------------------------------------

class WeatherCurrent(BaseModel):
    temperature_c: Optional[float] = None
    feels_like_c: Optional[float] = None
    humidity_pct: Optional[int] = None
    conditions: Optional[str] = None
    condition_code: Optional[str] = None
    wind_speed_kmh: Optional[float] = None
    uv_index: Optional[float] = None
    visibility_km: Optional[float] = None
    precipitation_mm: Optional[float] = None
    is_day: Optional[bool] = None
    observed_at: Optional[str] = None


class WeatherDay(BaseModel):
    date: str
    temp_high_c: Optional[float] = None
    temp_low_c: Optional[float] = None
    humidity_pct: Optional[int] = None
    rain_mm: Optional[float] = None
    sun_hours: Optional[float] = None
    uv_index: Optional[float] = None
    wind_speed_kmh: Optional[float] = None
    conditions: Optional[str] = None
    condition_code: Optional[str] = None
    sunrise: Optional[str] = None
    sunset: Optional[str] = None
    precipitation_chance: Optional[float] = None


class WeatherForecast(BaseModel):
    location_name: Optional[str] = None
    latitude: float
    longitude: float
    timezone: Optional[str] = None
    current: Optional[WeatherCurrent] = None
    daily: List[WeatherDay] = []


class GardenWeatherSummary(BaseModel):
    rain_last_7_days_mm: float = 0.0
    avg_temp_c: Optional[float] = None
    sunny_days: int = 0
    watering_needed: bool = False
    watering_message: Optional[str] = None
    alerts: List[str] = []


# ---------------------------------------------------------------------------
# AI
# ---------------------------------------------------------------------------

class ChatMessage(BaseModel):
    role: str  # user | assistant
    content: str


class ChatRequest(BaseModel):
    message: str
    include_garden_context: bool = True


class ChatResponse(BaseModel):
    message: str
    role: str = 'assistant'


class PhotoToMapRequest(BaseModel):
    image_base64: str
    image_mime_type: str = 'image/jpeg'
    garden_width_meters: Optional[float] = None
    garden_height_meters: Optional[float] = None


class DetectedBed(BaseModel):
    name: str
    bed_type: str = 'in_ground'
    x_pct: float
    y_pct: float
    width_pct: float
    height_pct: float
    rotation: float = 0.0


class PhotoToMapResponse(BaseModel):
    beds: List[DetectedBed] = []
    paths: List[Dict[str, Any]] = []
    confidence: Optional[str] = None
    notes: Optional[str] = None
