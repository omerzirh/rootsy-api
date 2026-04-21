import os
import logging
from typing import Optional, List, Dict, Any
import httpx

logger = logging.getLogger(__name__)

PERENUAL_BASE_URL = "https://perenual.com/api"


class PerenualService:
    def __init__(self):
        self.api_key = os.getenv("PERENUAL_API_KEY")
        if not self.api_key:
            logger.warning("PERENUAL_API_KEY not set — Perenual calls will fail")
        self.base_url = PERENUAL_BASE_URL

    def _normalize_plant(self, data: dict) -> dict:
        """Normalize a Perenual species object to our internal shape."""
        scientific = data.get("scientific_name", [])
        if isinstance(scientific, list):
            scientific = scientific[0] if scientific else None

        image = data.get("default_image") or {}
        image_url = image.get("regular_url") or image.get("medium_url") or image.get("small_url")

        hardiness = data.get("hardiness", {})
        hardiness_zones = []
        if isinstance(hardiness, dict):
            min_zone = hardiness.get("min", "")
            max_zone = hardiness.get("max", "")
            if min_zone:
                hardiness_zones = [min_zone, max_zone] if max_zone else [min_zone]

        sunlight = data.get("sunlight", [])
        if isinstance(sunlight, str):
            sunlight = [sunlight]

        return {
            "perenual_id": data.get("id"),
            "common_name": (data.get("common_name") or "Unknown").title(),
            "scientific_name": scientific,
            "family": data.get("family"),
            "plant_type": data.get("type") or "vegetable",
            "cycle": data.get("cycle"),
            "watering": data.get("watering"),
            "sunlight": sunlight,
            "hardiness_zones": hardiness_zones,
            "growth_rate": data.get("growth_rate"),
            "care_level": data.get("care_level"),
            "description": data.get("description"),
            "image_url": image_url,
            "sowing_info": None,
            "harvest_days_min": None,
            "harvest_days_max": None,
            "companions": [],
            "avoid_near": [],
        }

    async def search_plants(self, query: str, page: int = 1) -> Dict[str, Any]:
        """Search plants by name. Returns {results, total, page}."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self.base_url}/species-list",
                params={"key": self.api_key, "q": query, "page": page},
            )
            resp.raise_for_status()
            data = resp.json()

        results = [self._normalize_plant(p) for p in data.get("data", [])]
        return {
            "results": results,
            "total": data.get("total", len(results)),
            "page": data.get("current_page", page),
        }

    async def get_plant_detail(self, perenual_id: int) -> Optional[Dict[str, Any]]:
        """Fetch full details for a single plant by its Perenual ID."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self.base_url}/species/details/{perenual_id}",
                params={"key": self.api_key},
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()

        return self._normalize_plant(data)

    async def get_popular_vegetables(self, page: int = 1) -> Dict[str, Any]:
        """Fetch popular edible plants (vegetables, herbs, fruits)."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self.base_url}/species-list",
                params={"key": self.api_key, "edible": 1, "page": page},
            )
            resp.raise_for_status()
            data = resp.json()

        results = [self._normalize_plant(p) for p in data.get("data", [])]
        return {
            "results": results,
            "total": data.get("total", len(results)),
            "page": data.get("current_page", page),
        }


perenual_service = PerenualService()
