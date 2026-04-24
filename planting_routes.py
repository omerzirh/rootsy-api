import logging
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Header, Request, Query
from models import (
    CreatePlantingRequest, UpdatePlantingRequest, PlantingItem,
    AddProgressRequest, ProgressEntry,
    BulkCreatePlantingsRequest, ReorderPlantingsRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _require_user(request: Request, authorization: Optional[str]) -> str:
    user_id = request.app.state.extract_user_id(authorization)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authorization required")
    return user_id


def _enrich_planting(sb, planting: dict) -> dict:
    """Add plant_name and plant_image_url to a planting dict."""
    plant = (
        sb.table("plants")
        .select("common_name,image_url")
        .eq("id", planting["plant_id"])
        .limit(1)
        .execute()
    )
    if plant.data:
        planting["plant_name"] = plant.data[0].get("common_name")
        planting["plant_image_url"] = plant.data[0].get("image_url")
    return planting


@router.post("/", response_model=PlantingItem, status_code=201)
async def create_planting(
    body: CreatePlantingRequest,
    request: Request,
    authorization: Optional[str] = Header(None),
):
    user_id = _require_user(request, authorization)
    sb = request.app.state.supabase

    # Verify bed ownership
    bed = (
        sb.table("garden_beds")
        .select("id")
        .eq("id", body.garden_bed_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not bed.data:
        raise HTTPException(status_code=404, detail="Garden bed not found")

    result = (
        sb.table("plantings")
        .insert({
            "user_id": user_id,
            "garden_bed_id": body.garden_bed_id,
            "plant_id": body.plant_id,
            "position_x": body.position_x,
            "position_y": body.position_y,
            "status": body.status,
            "planted_date": body.planted_date,
            "expected_harvest_date": body.expected_harvest_date,
            "quantity": body.quantity,
            "notes": body.notes,
        })
        .execute()
    )
    return _enrich_planting(sb, result.data[0])


@router.post("/bulk", response_model=List[PlantingItem], status_code=201)
async def bulk_create_plantings(
    body: BulkCreatePlantingsRequest,
    request: Request,
    authorization: Optional[str] = Header(None),
):
    """Create multiple individual plantings in a single bed in one call.
    Each count creates that many rows with quantity=1 so each plant is an
    independent icon that can be placed and reordered separately.
    """
    user_id = _require_user(request, authorization)
    sb = request.app.state.supabase

    bed = (
        sb.table("garden_beds")
        .select("id")
        .eq("id", body.garden_bed_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not bed.data:
        raise HTTPException(status_code=404, detail="Garden bed not found")

    # Determine starting position_x (append after existing plants)
    existing = (
        sb.table("plantings")
        .select("position_x")
        .eq("garden_bed_id", body.garden_bed_id)
        .execute()
    )
    next_index = 0
    if existing.data:
        next_index = int(max((p.get("position_x") or 0) for p in existing.data)) + 1

    rows = []
    for item in body.items:
        n = max(1, int(item.count or 1))
        for _ in range(n):
            rows.append({
                "user_id": user_id,
                "garden_bed_id": body.garden_bed_id,
                "plant_id": item.plant_id,
                "position_x": next_index,
                "position_y": 0,
                "status": body.status,
                "planted_date": body.planted_date,
                "quantity": 1,
                "notes": item.notes,
            })
            next_index += 1

    if not rows:
        return []

    result = sb.table("plantings").insert(rows).execute()
    return [_enrich_planting(sb, p) for p in (result.data or [])]


@router.post("/reorder", status_code=204)
async def reorder_plantings(
    body: ReorderPlantingsRequest,
    request: Request,
    authorization: Optional[str] = Header(None),
):
    """Update position_x (order index) on many plantings at once."""
    user_id = _require_user(request, authorization)
    sb = request.app.state.supabase

    for entry in body.entries:
        sb.table("plantings").update({"position_x": entry.position_x}).eq("id", entry.id).eq("user_id", user_id).execute()


@router.get("/", response_model=List[PlantingItem])
async def list_plantings(
    request: Request,
    status: Optional[str] = Query(None),
    bed_id: Optional[str] = Query(None),
    authorization: Optional[str] = Header(None),
):
    user_id = _require_user(request, authorization)
    sb = request.app.state.supabase

    query = sb.table("plantings").select("*").eq("user_id", user_id)
    if status:
        query = query.eq("status", status)
    if bed_id:
        query = query.eq("garden_bed_id", bed_id)

    # When scoped to a single bed, order by position_x so drag-reorder sticks.
    # Globally we fall back to newest-first.
    if bed_id:
        result = query.order("position_x").order("created_at").execute()
    else:
        result = query.order("created_at", desc=True).execute()
    plantings = result.data or []

    return [_enrich_planting(sb, p) for p in plantings]


@router.get("/{planting_id}", response_model=PlantingItem)
async def get_planting(
    planting_id: str,
    request: Request,
    authorization: Optional[str] = Header(None),
):
    user_id = _require_user(request, authorization)
    sb = request.app.state.supabase

    result = (
        sb.table("plantings")
        .select("*")
        .eq("id", planting_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Planting not found")

    return _enrich_planting(sb, result.data[0])


@router.patch("/{planting_id}", response_model=PlantingItem)
async def update_planting(
    planting_id: str,
    body: UpdatePlantingRequest,
    request: Request,
    authorization: Optional[str] = Header(None),
):
    user_id = _require_user(request, authorization)
    sb = request.app.state.supabase

    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    result = (
        sb.table("plantings")
        .update(updates)
        .eq("id", planting_id)
        .eq("user_id", user_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Planting not found")

    return _enrich_planting(sb, result.data[0])


@router.delete("/{planting_id}", status_code=204)
async def delete_planting(
    planting_id: str,
    request: Request,
    authorization: Optional[str] = Header(None),
):
    user_id = _require_user(request, authorization)
    sb = request.app.state.supabase

    sb.table("plantings").delete().eq("id", planting_id).eq("user_id", user_id).execute()


# ---------------------------------------------------------------------------
# Progress timeline
# ---------------------------------------------------------------------------

@router.post("/{planting_id}/progress", response_model=ProgressEntry, status_code=201)
async def add_progress(
    planting_id: str,
    body: AddProgressRequest,
    request: Request,
    authorization: Optional[str] = Header(None),
):
    user_id = _require_user(request, authorization)
    sb = request.app.state.supabase

    # Verify planting ownership
    planting = (
        sb.table("plantings")
        .select("id")
        .eq("id", planting_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not planting.data:
        raise HTTPException(status_code=404, detail="Planting not found")

    result = (
        sb.table("planting_progress")
        .insert({
            "planting_id": planting_id,
            "user_id": user_id,
            "note": body.note,
            "growth_stage": body.growth_stage,
            "photo_url": body.photo_url,
        })
        .execute()
    )
    return result.data[0]


@router.get("/{planting_id}/progress", response_model=List[ProgressEntry])
async def get_progress(
    planting_id: str,
    request: Request,
    authorization: Optional[str] = Header(None),
):
    user_id = _require_user(request, authorization)
    sb = request.app.state.supabase

    # Verify planting ownership
    planting = (
        sb.table("plantings")
        .select("id")
        .eq("id", planting_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not planting.data:
        raise HTTPException(status_code=404, detail="Planting not found")

    result = (
        sb.table("planting_progress")
        .select("*")
        .eq("planting_id", planting_id)
        .order("recorded_at", desc=True)
        .execute()
    )
    return result.data or []
