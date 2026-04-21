import logging
from typing import Optional
from datetime import date, timedelta
from fastapi import APIRouter, HTTPException, Header, Request, Query
from models import WeatherForecast, GardenWeatherSummary
from weatherkit_service import weatherkit_service

logger = logging.getLogger(__name__)
router = APIRouter()


def _require_user(request: Request, authorization: Optional[str]) -> str:
    user_id = request.app.state.extract_user_id(authorization)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authorization required")
    return user_id


def _should_refresh_cache(fetched_at_str: Optional[str]) -> bool:
    """Refresh if cache is older than 3 hours."""
    if not fetched_at_str:
        return True
    from datetime import datetime, timezone
    fetched = datetime.fromisoformat(fetched_at_str.replace("Z", "+00:00"))
    age = datetime.now(timezone.utc) - fetched
    return age.total_seconds() > 10800  # 3 hours


@router.get("/current")
async def get_current_weather(
    request: Request,
    lat: float = Query(...),
    lng: float = Query(...),
    authorization: Optional[str] = Header(None),
):
    """Get current weather conditions for a location."""
    _require_user(request, authorization)
    sb = request.app.state.supabase

    today = date.today().isoformat()
    lat_r = round(lat, 3)
    lng_r = round(lng, 3)

    # Check cache
    cache = (
        sb.table("weather_cache")
        .select("*")
        .eq("location_lat", lat_r)
        .eq("location_lng", lng_r)
        .eq("date", today)
        .maybe_single()
        .execute()
    )

    if cache.data and not _should_refresh_cache(cache.data.get("fetched_at")):
        return cache.data

    # Fetch fresh from WeatherKit
    try:
        weather = await weatherkit_service.get_weather(lat, lng, days=1)
    except Exception as e:
        logger.error(f"WeatherKit fetch failed: {e}")
        if cache.data:
            return cache.data
        raise HTTPException(status_code=503, detail="Weather service unavailable")

    current = weather.get("current", {})
    daily = weather.get("daily", [{}])
    today_data = daily[0] if daily else {}

    row = {
        "location_lat": lat_r,
        "location_lng": lng_r,
        "date": today,
        "temp_high_c": today_data.get("temp_high_c"),
        "temp_low_c": today_data.get("temp_low_c"),
        "humidity_pct": current.get("humidity_pct"),
        "rain_mm": today_data.get("rain_mm"),
        "sun_hours": today_data.get("sun_hours"),
        "wind_speed_kmh": current.get("wind_speed_kmh"),
        "conditions": current.get("conditions"),
        "raw_data": {"current": current, "today": today_data},
    }

    try:
        sb.table("weather_cache").upsert(row, on_conflict="location_lat,location_lng,date").execute()
    except Exception as e:
        logger.warning(f"Failed to cache weather: {e}")

    return {"current": current, "today": today_data}


@router.get("/forecast", response_model=WeatherForecast)
async def get_forecast(
    request: Request,
    lat: float = Query(...),
    lng: float = Query(...),
    days: int = Query(7, ge=1, le=10),
    authorization: Optional[str] = Header(None),
):
    """Get multi-day weather forecast."""
    _require_user(request, authorization)

    try:
        weather = await weatherkit_service.get_weather(lat, lng, days=days)
    except Exception as e:
        logger.error(f"WeatherKit forecast failed: {e}")
        raise HTTPException(status_code=503, detail="Weather service unavailable")

    return WeatherForecast(
        latitude=lat,
        longitude=lng,
        current=weather.get("current"),
        daily=weather.get("daily", [])[:days],
    )


@router.get("/garden-summary")
async def get_garden_weather_summary(
    request: Request,
    garden_id: str = Query(...),
    authorization: Optional[str] = Header(None),
):
    """Analyze recent weather vs plant watering needs for a garden."""
    user_id = _require_user(request, authorization)
    sb = request.app.state.supabase

    # Get garden location from user profile or garden record
    garden = (
        sb.table("gardens")
        .select("id")
        .eq("id", garden_id)
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    if not garden.data:
        raise HTTPException(status_code=404, detail="Garden not found")

    profile = (
        sb.table("user_profiles")
        .select("location_lat,location_lng")
        .eq("id", user_id)
        .maybe_single()
        .execute()
    )
    if not profile.data or not profile.data.get("location_lat"):
        raise HTTPException(status_code=400, detail="Location not set. Update your profile with a location.")

    lat = profile.data["location_lat"]
    lng = profile.data["location_lng"]

    # Get last 7 days weather from cache
    week_ago = (date.today() - timedelta(days=7)).isoformat()
    weather_rows = (
        sb.table("weather_cache")
        .select("rain_mm,temp_high_c,conditions")
        .eq("location_lat", round(lat, 3))
        .eq("location_lng", round(lng, 3))
        .gte("date", week_ago)
        .execute()
    )
    rows = weather_rows.data or []

    total_rain = sum(r.get("rain_mm") or 0 for r in rows)
    temps = [r.get("temp_high_c") for r in rows if r.get("temp_high_c")]
    avg_temp = sum(temps) / len(temps) if temps else None
    sunny_days = sum(1 for r in rows if r.get("conditions") and "sun" in r["conditions"].lower())

    watering_needed = total_rain < 15.0  # < 15mm in 7 days typically means watering needed
    watering_message = None
    if watering_needed:
        needed = max(0, 25.0 - total_rain)
        watering_message = f"Only {total_rain:.0f}mm rain in the past week. Plants may need ~{needed:.0f}mm more water."
    else:
        watering_message = f"Good rainfall this week ({total_rain:.0f}mm). Check individual plant needs."

    return GardenWeatherSummary(
        rain_last_7_days_mm=total_rain,
        avg_temp_c=avg_temp,
        sunny_days=sunny_days,
        watering_needed=watering_needed,
        watering_message=watering_message,
        alerts=[],
    )
