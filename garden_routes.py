import logging
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Header, Request
from models import (
    CreateGardenRequest, UpdateGardenRequest, GardenSummary, GardenDetail,
    CreateBedRequest, UpdateBedRequest, GardenBed,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _require_user(request: Request, authorization: Optional[str]) -> str:
    user_id = request.app.state.extract_user_id(authorization)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authorization required")
    return user_id


# ---------------------------------------------------------------------------
# Gardens
# ---------------------------------------------------------------------------

@router.get("/", response_model=List[GardenSummary])
async def list_gardens(
    request: Request,
    authorization: Optional[str] = Header(None),
):
    user_id = _require_user(request, authorization)
    sb = request.app.state.supabase

    result = (
        sb.table("gardens")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )
    gardens = result.data or []

    # Enrich with bed + planting counts
    enriched = []
    for g in gardens:
        beds = sb.table("garden_beds").select("id").eq("garden_id", g["id"]).execute()
        bed_ids = [b["id"] for b in (beds.data or [])]
        planting_count = 0
        if bed_ids:
            plantings = (
                sb.table("plantings")
                .select("id", count="exact")
                .in_("garden_bed_id", bed_ids)
                .execute()
            )
            planting_count = plantings.count or 0
        g["bed_count"] = len(bed_ids)
        g["planting_count"] = planting_count
        enriched.append(g)

    return enriched


@router.post("/", response_model=GardenSummary, status_code=201)
async def create_garden(
    body: CreateGardenRequest,
    request: Request,
    authorization: Optional[str] = Header(None),
):
    user_id = _require_user(request, authorization)
    sb = request.app.state.supabase

    result = (
        sb.table("gardens")
        .insert({
            "user_id": user_id,
            "name": body.name,
            "width_meters": body.width_meters,
            "height_meters": body.height_meters,
            "notes": body.notes,
        })
        .execute()
    )
    garden = result.data[0]
    garden["bed_count"] = 0
    garden["planting_count"] = 0
    return garden


@router.get("/{garden_id}", response_model=GardenDetail)
async def get_garden(
    garden_id: str,
    request: Request,
    authorization: Optional[str] = Header(None),
):
    user_id = _require_user(request, authorization)
    sb = request.app.state.supabase

    result = (
        sb.table("gardens")
        .select("*")
        .eq("id", garden_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Garden not found")

    garden = result.data[0]
    beds_result = (
        sb.table("garden_beds")
        .select("*")
        .eq("garden_id", garden_id)
        .order("created_at")
        .execute()
    )
    garden["beds"] = beds_result.data or []
    return garden


@router.patch("/{garden_id}", response_model=GardenSummary)
async def update_garden(
    garden_id: str,
    body: UpdateGardenRequest,
    request: Request,
    authorization: Optional[str] = Header(None),
):
    user_id = _require_user(request, authorization)
    sb = request.app.state.supabase

    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    result = (
        sb.table("gardens")
        .update(updates)
        .eq("id", garden_id)
        .eq("user_id", user_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Garden not found")

    garden = result.data[0]
    garden["bed_count"] = 0
    garden["planting_count"] = 0
    return garden


@router.delete("/{garden_id}", status_code=204)
async def delete_garden(
    garden_id: str,
    request: Request,
    authorization: Optional[str] = Header(None),
):
    user_id = _require_user(request, authorization)
    sb = request.app.state.supabase

    sb.table("gardens").delete().eq("id", garden_id).eq("user_id", user_id).execute()


# ---------------------------------------------------------------------------
# Garden Beds
# ---------------------------------------------------------------------------

@router.post("/{garden_id}/beds", response_model=GardenBed, status_code=201)
async def create_bed(
    garden_id: str,
    body: CreateBedRequest,
    request: Request,
    authorization: Optional[str] = Header(None),
):
    user_id = _require_user(request, authorization)
    sb = request.app.state.supabase

    # Verify garden ownership
    garden = (
        sb.table("gardens")
        .select("id")
        .eq("id", garden_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not garden.data:
        raise HTTPException(status_code=404, detail="Garden not found")

    result = (
        sb.table("garden_beds")
        .insert({
            "garden_id": garden_id,
            "user_id": user_id,
            "name": body.name,
            "bed_type": body.bed_type,
            "x_position": body.x_position,
            "y_position": body.y_position,
            "width": body.width,
            "height": body.height,
            "rotation": body.rotation,
            "soil_type": body.soil_type,
            "color": body.color,
            "notes": body.notes,
        })
        .execute()
    )
    return result.data[0]


@router.patch("/beds/{bed_id}", response_model=GardenBed)
async def update_bed(
    bed_id: str,
    body: UpdateBedRequest,
    request: Request,
    authorization: Optional[str] = Header(None),
):
    user_id = _require_user(request, authorization)
    sb = request.app.state.supabase

    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    result = (
        sb.table("garden_beds")
        .update(updates)
        .eq("id", bed_id)
        .eq("user_id", user_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Bed not found")
    return result.data[0]


@router.delete("/beds/{bed_id}", status_code=204)
async def delete_bed(
    bed_id: str,
    request: Request,
    authorization: Optional[str] = Header(None),
):
    user_id = _require_user(request, authorization)
    sb = request.app.state.supabase

    sb.table("garden_beds").delete().eq("id", bed_id).eq("user_id", user_id).execute()
