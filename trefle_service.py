import os
import logging
from typing import Optional, Dict, Any
import httpx

logger = logging.getLogger(__name__)

TREFLE_BASE_URL = "https://trefle.io/api/v1"

# Herb families for plant_type detection
HERB_FAMILIES = {
    "lamiaceae", "apiaceae", "asteraceae", "zingiberaceae",
    "verbenaceae", "boraginaceae",
}


def _map_light(light: Optional[int]) -> list[str]:
    """Convert Trefle 0-10 light scale to sunlight strings."""
    if light is None:
        return []
    if light <= 3:
        return ["part shade"]
    if light <= 6:
        return ["part sun/shade"]
    return ["full sun"]


def _map_watering(soil_humidity: Optional[int]) -> Optional[str]:
    """Convert Trefle 0-5 soil_humidity scale to watering frequency."""
    if soil_humidity is None:
        return None
    if soil_humidity <= 1:
        return "Minimum"
    if soil_humidity <= 3:
        return "Average"
    return "Frequent"


def _plant_type(data: dict, main_species: Optional[dict]) -> str:
    if data.get("vegetable"):
        return "vegetable"
    family = (data.get("family") or "").lower()
    if family in HERB_FAMILIES:
        return "herb"
    if main_species:
        if main_species.get("vegetable"):
            return "vegetable"
    return "plant"


def _normalize_plant(data: dict) -> dict:
    """Normalize a Trefle plant object to our internal DB shape.

    Works for both search results (basic) and detail responses (with main_species).
    """
    main = data.get("main_species") or {}
    growth = main.get("growth") or {}
    specs = main.get("specifications") or {}

    # Image: detail has images dict, search/list has image_url at top level
    image_url = data.get("image_url")
    if not image_url and main:
        images = main.get("images") or {}
        for category in ("habit", "flower", "fruit", "leaf", "bark"):
            imgs = images.get(category, [])
            if imgs:
                image_url = imgs[0].get("image_url") or imgs[0].get("url")
                break

    days = growth.get("days_to_harvest")

    return {
        "trefle_id": data.get("id"),
        "common_name": (data.get("common_name") or "Unknown").title(),
        "scientific_name": data.get("scientific_name"),
        "family": data.get("family"),
        "plant_type": _plant_type(data, main or None),
        "cycle": specs.get("growth_form") or growth.get("ph_minimum") and "perennial" or None,
        "watering": _map_watering(growth.get("soil_humidity")),
        "sunlight": _map_light(growth.get("light")),
        "hardiness_zones": [],
        "growth_rate": (specs.get("growth_rate") or "").title() or None,
        "care_level": None,
        "description": growth.get("description"),
        "image_url": image_url,
        "sowing_info": None,
        "harvest_days_min": days,
        "harvest_days_max": days,
        "companions": [],
        "avoid_near": [],
    }


class TrefleService:
    def __init__(self):
        self.token = os.getenv("TREFLE_API_TOKEN")
        if not self.token:
            logger.warning("TREFLE_API_TOKEN not set — Trefle calls will fail")
        self.base_url = TREFLE_BASE_URL

    def _params(self, extra: Optional[dict] = None) -> dict:
        p = {"token": self.token}
        if extra:
            p.update(extra)
        return p

    async def search_plants(self, query: str, page: int = 1, raw: bool = False) -> Dict[str, Any]:
        """Search plants by name. Returns {results, total, page}.
        Pass raw=True to get unnormalized Trefle dicts (used by seed script for best-match ranking)."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self.base_url}/plants/search",
                params=self._params({"q": query, "page": page}),
            )
            resp.raise_for_status()
            data = resp.json()

        raw_plants = data.get("data", [])
        results = raw_plants if raw else [_normalize_plant(p) for p in raw_plants]
        total = (data.get("meta") or {}).get("total", len(results))
        return {"results": results, "total": total, "page": page}

    async def get_plant_detail(self, trefle_id: int) -> Optional[Dict[str, Any]]:
        """Fetch full details for a single plant by its Trefle ID."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self.base_url}/plants/{trefle_id}",
                params=self._params(),
            )
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()

        plant_data = data.get("data") or data
        return _normalize_plant(plant_data)

    async def get_popular_vegetables(self, page: int = 1) -> Dict[str, Any]:
        """Fetch vegetable plants from Trefle."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{self.base_url}/plants",
                params=self._params({"filter[vegetable]": "true", "page": page}),
            )
            resp.raise_for_status()
            data = resp.json()

        results = [_normalize_plant(p) for p in data.get("data", [])]
        total = (data.get("meta") or {}).get("total", len(results))
        return {"results": results, "total": total, "page": page}


trefle_service = TrefleService()
