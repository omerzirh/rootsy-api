import os
import time
import logging
from typing import Optional, Dict, Any
import httpx
import jwt

logger = logging.getLogger(__name__)

WEATHERKIT_BASE_URL = "https://weatherkit.apple.com/api/v1"


class WeatherKitService:
    """Apple WeatherKit REST API client.

    Authentication: short-lived JWT signed with your Apple Developer private key (ES256).
    Docs: https://developer.apple.com/documentation/weatherkitrestapi
    """

    def __init__(self):
        self.team_id = os.getenv("APPLE_TEAM_ID")
        self.key_id = os.getenv("APPLE_KEY_ID")
        self.service_id = os.getenv("APPLE_SERVICE_ID", "com.rootsy.weatherkit")
        self.base_url = WEATHERKIT_BASE_URL
        self._private_key: Optional[str] = None

        if not self.team_id or not self.key_id:
            logger.warning("APPLE_TEAM_ID / APPLE_KEY_ID not set — WeatherKit calls will fail")

    def _load_private_key(self) -> str:
        if self._private_key:
            return self._private_key
        # Try file path first, then inline env var
        key_path = os.getenv("APPLE_PRIVATE_KEY_PATH")
        if key_path and os.path.isfile(key_path):
            with open(key_path, "r") as f:
                self._private_key = f.read()
            return self._private_key
        key_inline = os.getenv("APPLE_PRIVATE_KEY")
        if key_inline:
            self._private_key = key_inline.replace("\\n", "\n")
            return self._private_key
        raise RuntimeError("Apple private key not found. Set APPLE_PRIVATE_KEY_PATH or APPLE_PRIVATE_KEY.")

    def _make_jwt(self) -> str:
        """Generate a short-lived JWT for WeatherKit REST API authentication."""
        private_key = self._load_private_key()
        now = int(time.time())
        payload = {
            "iss": self.team_id,
            "iat": now,
            "exp": now + 3600,  # 1 hour
            "sub": self.service_id,
        }
        headers = {
            "alg": "ES256",
            "kid": self.key_id,
            "id": f"{self.team_id}.{self.service_id}",
        }
        return jwt.encode(payload, private_key, algorithm="ES256", headers=headers)

    def _parse_current(self, data: dict) -> dict:
        cw = data.get("currentWeather", {})
        return {
            "temperature_c": cw.get("temperature"),
            "feels_like_c": cw.get("temperatureApparent"),
            "humidity_pct": int(cw.get("humidity", 0) * 100) if cw.get("humidity") is not None else None,
            "conditions": cw.get("conditionCode"),
            "condition_code": cw.get("conditionCode"),
            "wind_speed_kmh": cw.get("windSpeed"),
            "uv_index": cw.get("uvIndex"),
            "visibility_km": cw.get("visibility"),
            "precipitation_mm": cw.get("precipitationIntensity"),
            "is_day": cw.get("daylight"),
            "observed_at": cw.get("asOf"),
        }

    def _parse_daily(self, data: dict) -> list:
        forecast = data.get("forecastDaily", {})
        days = forecast.get("days", [])
        result = []
        for d in days:
            result.append({
                "date": d.get("forecastStart", "")[:10],
                "temp_high_c": d.get("temperatureMax"),
                "temp_low_c": d.get("temperatureMin"),
                "humidity_pct": int(d.get("daytimeForecast", {}).get("humidity", 0) * 100)
                    if d.get("daytimeForecast", {}).get("humidity") is not None else None,
                "rain_mm": d.get("precipitationAmount"),
                "sun_hours": None,  # WeatherKit doesn't provide this directly
                "uv_index": d.get("maxUvIndex"),
                "wind_speed_kmh": d.get("windSpeedAvg"),
                "conditions": d.get("conditionCode"),
                "condition_code": d.get("conditionCode"),
                "sunrise": d.get("sunrise"),
                "sunset": d.get("sunset"),
                "precipitation_chance": d.get("precipitationChance"),
            })
        return result

    async def get_weather(self, lat: float, lng: float, days: int = 7) -> Dict[str, Any]:
        """Fetch current weather + daily forecast for a location."""
        token = self._make_jwt()
        data_sets = "currentWeather,forecastDaily"
        url = f"{self.base_url}/weather/en/{lat}/{lng}"
        params = {
            "dataSets": data_sets,
            "dailyEnd": None,
        }
        headers = {"Authorization": f"Bearer {token}"}

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers=headers, params={"dataSets": data_sets})
            resp.raise_for_status()
            data = resp.json()

        return {
            "latitude": lat,
            "longitude": lng,
            "current": self._parse_current(data),
            "daily": self._parse_daily(data)[:days],
        }


weatherkit_service = WeatherKitService()
