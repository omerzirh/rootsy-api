import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Header, Request, Query
from models import PlantSummary, PlantDetail, PlantSearchResponse
from trefle_service import trefle_service

logger = logging.getLogger(__name__)
router = APIRouter()

# In-memory set of trefle IDs already cached — avoids redundant DB checks
# (stored in perenual_id column for backward compat)
_cached_trefle_ids: set[int] = set()

_PLANT_SELECT = (
    "id,perenual_id,common_name,scientific_name,plant_type,cycle,"
    "watering,care_level,image_url,harvest_days_min,harvest_days_max"
)


def _require_user(request: Request, authorization: Optional[str]) -> str:
    user_id = request.app.state.extract_user_id(authorization)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authorization required")
    return user_id


def _cache_plants(sb, plants: list) -> None:
    """Upsert plants from Trefle into the DB, skipping already-known ones."""
    for p in plants:
        pid = p.get("perenual_id")   # column reused for Trefle ID
        if pid and pid in _cached_trefle_ids:
            continue
        try:
            sb.table("plants").upsert(p, on_conflict="perenual_id").execute()
            if pid:
                _cached_trefle_ids.add(pid)
        except Exception as e:
            logger.warning(f"Failed to cache plant {p.get('common_name')}: {e}")


@router.get("/search", response_model=PlantSearchResponse)
async def search_plants(
    request: Request,
    q: str = Query(..., min_length=1),
    page: int = Query(1, ge=1),
    authorization: Optional[str] = Header(None),
):
    """Search the plant library. DB-first; falls back to Trefle when query
    is 3+ chars and local cache returns nothing."""
    _require_user(request, authorization)
    sb = request.app.state.supabase

    cache_result = (
        sb.table("plants")
        .select(_PLANT_SELECT)
        .ilike("common_name", f"%{q}%")
        .limit(20)
        .execute()
    )
    cached = cache_result.data or []

    if len(cached) == 0 and len(q) >= 3:
        try:
            api_data = await trefle_service.search_plants(query=q, page=page)
            _cache_plants(sb, api_data["results"])

            cache_result2 = (
                sb.table("plants")
                .select(_PLANT_SELECT)
                .ilike("common_name", f"%{q}%")
                .limit(20)
                .execute()
            )
            cached = cache_result2.data or []
        except Exception as e:
            logger.error(f"Trefle search failed: {e}")

    return PlantSearchResponse(results=cached, total=len(cached), page=page)


@router.get("/popular", response_model=PlantSearchResponse)
async def get_popular_plants(
    request: Request,
    page: int = Query(1, ge=1),
    authorization: Optional[str] = Header(None),
):
    """Return cached edible plants. Seeds from Trefle only if DB is empty."""
    _require_user(request, authorization)
    sb = request.app.state.supabase

    result = (
        sb.table("plants")
        .select(_PLANT_SELECT)
        .in_("plant_type", ["vegetable", "herb", "fruit", "edible", "plant"])
        .order("common_name")
        .range((page - 1) * 20, page * 20 - 1)
        .execute()
    )
    plants = result.data or []

    if not plants:
        try:
            api_data = await trefle_service.get_popular_vegetables(page=page)
            _cache_plants(sb, api_data["results"])
            result2 = (
                sb.table("plants")
                .select(_PLANT_SELECT)
                .order("common_name")
                .limit(20)
                .execute()
            )
            plants = result2.data or []
        except Exception as e:
            logger.error(f"Trefle popular plants failed: {e}")

    return PlantSearchResponse(results=plants, total=len(plants), page=page)


@router.get("/recommendations", response_model=PlantSearchResponse)
async def get_recommendations(
    request: Request,
    zone: Optional[str] = Query(None),
    month: Optional[int] = Query(None, ge=1, le=12),
    authorization: Optional[str] = Header(None),
):
    _require_user(request, authorization)
    sb = request.app.state.supabase

    result = (
        sb.table("plants")
        .select(_PLANT_SELECT)
        .in_("plant_type", ["vegetable", "herb", "fruit", "edible", "plant"])
        .order("common_name")
        .limit(20)
        .execute()
    )
    plants = result.data or []
    return PlantSearchResponse(results=plants, total=len(plants), page=1)


@router.get("/{plant_id}", response_model=PlantDetail)
async def get_plant(
    plant_id: str,
    request: Request,
    authorization: Optional[str] = Header(None),
):
    _require_user(request, authorization)
    sb = request.app.state.supabase

    result = sb.table("plants").select("*").eq("id", plant_id).limit(1).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Plant not found")

    return result.data[0]
