import json
import logging
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Header, Request
import base64
import time
from datetime import datetime, date
from models import (
    ChatRequest, ChatResponse, ChatMessage,
    PhotoToMapRequest, PhotoToMapResponse, DetectedBed,
    PlantDiagnosisRequest, PlantDiagnosisResponse,
    PlantDiagnosisIssue, PlantDiagnosisAction,
    PlantDiagnosisSummary,
)
from openrouter_service import openrouter_service
from weatherkit_service import weatherkit_service
from storage_service import (
    diagnosis_photo_key, put_bytes, generate_download_url,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def _require_user(request: Request, authorization: Optional[str]) -> str:
    user_id = request.app.state.extract_user_id(authorization)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authorization required")
    return user_id


async def _build_garden_context(user_id: str, sb) -> str:
    """Build a concise garden context string for the AI system prompt."""
    try:
        profile = (
            sb.table("user_profiles")
            .select("display_name,location_name,hardiness_zone")
            .eq("id", user_id)
            .maybe_single()
            .execute()
        )
        p = profile.data or {}

        gardens = sb.table("gardens").select("name").eq("user_id", user_id).limit(3).execute()
        garden_names = [g["name"] for g in (gardens.data or [])]

        plantings = (
            sb.table("plantings")
            .select("status,planted_date,plants(common_name)")
            .eq("user_id", user_id)
            .not_.eq("status", "removed")
            .limit(20)
            .execute()
        )
        active_plants = []
        for pl in (plantings.data or []):
            plant_name = pl.get("plants", {}).get("common_name", "Unknown")
            active_plants.append(f"{plant_name} ({pl.get('status', 'planted')})")

        context_parts = [
            "USER GARDEN CONTEXT:",
            f"Name: {p.get('display_name', 'Gardener')}",
            f"Location: {p.get('location_name', 'Unknown location')}",
            f"Hardiness zone: {p.get('hardiness_zone', 'Unknown')}",
            f"Gardens: {', '.join(garden_names) if garden_names else 'None yet'}",
            f"Active plants: {', '.join(active_plants) if active_plants else 'None planted yet'}",
        ]
        return "\n".join(context_parts)
    except Exception as e:
        logger.warning(f"Failed to build garden context: {e}")
        return "USER GARDEN CONTEXT: Unable to load garden data."


GARDEN_ASSISTANT_SYSTEM_PROMPT = """You are Rootsy, a friendly and knowledgeable garden assistant.
You help home gardeners plan, grow, and care for their vegetable gardens.
Your advice is practical, encouraging, and based on organic/sustainable principles.
Keep responses concise and actionable. Use simple language.
When you don't know something specific to the user's conditions, say so honestly.

{garden_context}
"""


@router.post("/chat", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    request: Request,
    authorization: Optional[str] = Header(None),
):
    """Send a message to the AI garden assistant."""
    user_id = _require_user(request, authorization)
    sb = request.app.state.supabase

    # Build garden context for system prompt
    garden_context = ""
    if body.include_garden_context:
        garden_context = await _build_garden_context(user_id, sb)

    system_prompt = GARDEN_ASSISTANT_SYSTEM_PROMPT.format(garden_context=garden_context)

    # Load recent conversation history (last 20 messages)
    history_result = (
        sb.table("ai_conversations")
        .select("role,content")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(20)
        .execute()
    )
    history = list(reversed(history_result.data or []))

    messages = [{"role": m["role"], "content": m["content"]} for m in history]
    messages.append({"role": "user", "content": body.message})

    try:
        reply = await openrouter_service.chat(messages=messages, system_prompt=system_prompt)
    except Exception as e:
        logger.error(f"OpenRouter chat failed: {e}")
        raise HTTPException(status_code=503, detail="AI service unavailable")

    # Save user message and assistant reply
    sb.table("ai_conversations").insert([
        {"user_id": user_id, "role": "user", "content": body.message},
        {"user_id": user_id, "role": "assistant", "content": reply},
    ]).execute()

    return ChatResponse(message=reply)


@router.get("/history", response_model=List[ChatMessage])
async def get_history(
    request: Request,
    authorization: Optional[str] = Header(None),
):
    user_id = _require_user(request, authorization)
    sb = request.app.state.supabase

    result = (
        sb.table("ai_conversations")
        .select("role,content")
        .eq("user_id", user_id)
        .order("created_at")
        .limit(100)
        .execute()
    )
    return result.data or []


@router.delete("/history", status_code=204)
async def clear_history(
    request: Request,
    authorization: Optional[str] = Header(None),
):
    user_id = _require_user(request, authorization)
    sb = request.app.state.supabase

    sb.table("ai_conversations").delete().eq("user_id", user_id).execute()


@router.post("/photo-to-map", response_model=PhotoToMapResponse)
async def photo_to_map(
    body: PhotoToMapRequest,
    request: Request,
    authorization: Optional[str] = Header(None),
):
    """Analyze a garden photo and return detected bed layout as editable shapes."""
    _require_user(request, authorization)

    dim_hint = ""
    if body.garden_width_meters and body.garden_height_meters:
        dim_hint = f"The garden is approximately {body.garden_width_meters}m wide by {body.garden_height_meters}m tall."

    prompt = f"""Analyze this garden photo and identify the layout.
{dim_hint}

Return a JSON object with this exact structure:
{{
  "beds": [
    {{
      "name": "Bed 1",
      "bed_type": "raised",
      "x_pct": 10.0,
      "y_pct": 15.0,
      "width_pct": 30.0,
      "height_pct": 25.0,
      "rotation": 0.0
    }}
  ],
  "paths": [],
  "confidence": "high",
  "notes": "Optional observations about the garden"
}}

bed_type must be one of: raised, in_ground, container, greenhouse
x_pct, y_pct, width_pct, height_pct are percentages of image dimensions (0-100).
Only return the JSON object, no other text."""

    system = "You are a garden layout analyzer. Identify garden beds, containers, raised beds, and paths in garden photos. Return only valid JSON."

    try:
        raw = await openrouter_service.analyze_image(
            image_base64=body.image_base64,
            mime_type=body.image_mime_type,
            prompt=prompt,
            system_prompt=system,
        )
    except Exception as e:
        logger.error(f"Photo-to-map analysis failed: {e}")
        raise HTTPException(status_code=503, detail="AI vision service unavailable")

    # Parse JSON response
    try:
        # Strip markdown code fences if present
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1]) if lines[-1] == "```" else "\n".join(lines[1:])
        data = json.loads(text)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse photo-to-map response: {e}\nRaw: {raw}")
        raise HTTPException(status_code=422, detail="Could not parse garden layout from image. Try a clearer top-down photo.")

    beds = [DetectedBed(**b) for b in data.get("beds", [])]
    return PhotoToMapResponse(
        beds=beds,
        paths=data.get("paths", []),
        confidence=data.get("confidence"),
        notes=data.get("notes"),
    )


def _summarize_weather(weather: Optional[dict]) -> Optional[str]:
    """Render a weather snapshot into a short human-readable block for the prompt."""
    if not weather:
        return None
    parts = []
    cur = weather.get("current") or {}
    if cur.get("temperature_c") is not None:
        parts.append(f"now: {cur['temperature_c']:.0f}°C, {cur.get('conditions') or 'n/a'}")
    past = weather.get("past_days") or []
    if past:
        total_rain = sum((d.get("rain_mm") or 0) for d in past)
        highs = [d["temp_high_c"] for d in past if d.get("temp_high_c") is not None]
        lows = [d["temp_low_c"] for d in past if d.get("temp_low_c") is not None]
        line = f"last {len(past)} days: {total_rain:.0f}mm rain"
        if highs:
            line += f", high {min(highs):.0f}–{max(highs):.0f}°C"
        if lows:
            line += f", low {min(lows):.0f}–{max(lows):.0f}°C"
        parts.append(line)
    return " | ".join(parts) if parts else None


async def _planting_context(sb, user_id: str, planting_id: str) -> dict:
    """Fetch planting + plant + garden context for the prompt."""
    row = (
        sb.table("plantings")
        .select(
            "id,planted_date,status,quantity,notes,"
            "plants(common_name,scientific_name,plant_type,cycle,harvest_days_min,harvest_days_max),"
            "garden_beds(name,bed_type,gardens(name,location_lat,location_lng,location_name))"
        )
        .eq("id", planting_id)
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    data = (row and row.data) or {}
    plant = data.get("plants") or {}
    bed = data.get("garden_beds") or {}
    garden = bed.get("gardens") or {}

    age_days = None
    planted = data.get("planted_date")
    if planted:
        try:
            d = date.fromisoformat(planted)
            age_days = (date.today() - d).days
        except Exception:
            pass

    return {
        "common_name": plant.get("common_name"),
        "scientific_name": plant.get("scientific_name"),
        "plant_type": plant.get("plant_type"),
        "cycle": plant.get("cycle"),
        "harvest_days_min": plant.get("harvest_days_min"),
        "harvest_days_max": plant.get("harvest_days_max"),
        "status": data.get("status"),
        "planted_date": planted,
        "age_days": age_days,
        "notes": data.get("notes"),
        "bed_name": bed.get("name"),
        "bed_type": bed.get("bed_type"),
        "garden_name": garden.get("name"),
        "location_lat": garden.get("location_lat"),
        "location_lng": garden.get("location_lng"),
        "location_name": garden.get("location_name"),
    }


@router.post("/diagnose-plant", response_model=PlantDiagnosisResponse)
async def diagnose_plant(
    body: PlantDiagnosisRequest,
    request: Request,
    authorization: Optional[str] = Header(None),
):
    """Analyze a plant/seedling photo and return stage, health, and recommendations.
    If planting_id is provided, auto-attach plant/garden context and persist to history.
    """
    user_id = _require_user(request, authorization)
    sb = request.app.state.supabase

    # 1. Fetch planting context if provided
    ctx: dict = {}
    if body.planting_id:
        try:
            ctx = await _planting_context(sb, user_id, body.planting_id)
        except Exception as e:
            logger.warning(f"Failed to load planting context {body.planting_id}: {e}")

    # 2. Weather snapshot (cheap; free within WeatherKit quota)
    weather_snapshot: Optional[dict] = None
    if body.include_weather:
        lat = ctx.get("location_lat")
        lng = ctx.get("location_lng")
        # Fallback to user profile location
        if lat is None or lng is None:
            try:
                prof = (
                    sb.table("user_profiles")
                    .select("location_lat,location_lng")
                    .eq("id", user_id)
                    .maybe_single()
                    .execute()
                )
                if prof and prof.data:
                    lat = prof.data.get("location_lat")
                    lng = prof.data.get("location_lng")
            except Exception:
                pass
        if lat is not None and lng is not None:
            try:
                weather_snapshot = await weatherkit_service.get_weather_with_history(
                    lat=lat, lng=lng, past_days=7, forecast_days=3,
                )
            except Exception as e:
                logger.warning(f"Weather snapshot failed: {e}")

    # 3. Build prompt
    hint_lines = []
    if ctx.get("common_name"):
        line = f"Known plant: {ctx['common_name']}"
        if ctx.get("scientific_name"):
            line += f" ({ctx['scientific_name']})"
        if ctx.get("age_days") is not None:
            line += f", planted {ctx['age_days']} day(s) ago"
        if ctx.get("status"):
            line += f", status: {ctx['status']}"
        hint_lines.append(line + ".")
    elif body.plant_name_hint:
        hint_lines.append(f"The user says this is: {body.plant_name_hint}.")

    if ctx.get("bed_name") or ctx.get("garden_name"):
        loc = f"Growing in {ctx.get('bed_type') or 'bed'} '{ctx.get('bed_name') or 'unnamed'}'"
        if ctx.get("garden_name"):
            loc += f" in garden '{ctx['garden_name']}'"
        if ctx.get("location_name"):
            loc += f" ({ctx['location_name']})"
        hint_lines.append(loc + ".")

    weather_line = _summarize_weather(weather_snapshot)
    if weather_line:
        hint_lines.append(f"Recent weather — {weather_line}.")

    if body.user_note:
        hint_lines.append(f"User note: {body.user_note}")

    hint_block = "\n".join(hint_lines) if hint_lines else "No user hints provided."

    prompt = f"""You are inspecting a photo of a plant or seedling for a home gardener.
{hint_block}

Return ONLY a JSON object with this exact structure — no prose, no markdown:
{{
  "identified_as": "best guess of the plant (common name), or null if unsure",
  "stage": "one of: seed, seedling, vegetative, flowering, fruiting, mature, dormant, unknown",
  "stage_label": "short human-friendly label, e.g. 'True-leaf seedling (~2-3 weeks)'",
  "estimated_age": "rough age like '~2 weeks' or '3-4 weeks' or null",
  "health": "one of: healthy, mild_issues, stressed, diseased, dying, unknown",
  "health_score": 0-100 integer or null,
  "ready_to_transplant": true/false/null (only relevant for seedlings; true when it has 2+ sets of true leaves and a sturdy stem),
  "ready_to_harvest": true/false/null (only relevant for mature fruiting/leafy plants),
  "issues": [
    {{"label": "short issue name", "severity": "low|medium|high", "description": "what it looks like and likely cause"}}
  ],
  "recommendations": [
    {{"title": "short action", "detail": "how to do it", "urgency": "now|soon|later"}}
  ],
  "summary": "2-3 sentence plain-language summary for the gardener",
  "confidence": "low|medium|high"
}}

Guidelines:
- If the image is clearly not a plant, set stage=unknown, health=unknown, confidence=low and explain in summary.
- Be conservative: if you're not sure about disease, say "mild_issues" rather than "diseased".
- For seedlings, comment on leaf count, stem sturdiness, color, and whether it's leggy.
- For mature plants, comment on fruiting, flowering, pests, leaf color."""

    system = (
        "You are a careful horticulture assistant. You analyze plant photos and return "
        "structured JSON diagnoses. You never invent information you can't see in the image. "
        "You return ONLY valid JSON."
    )

    try:
        raw = await openrouter_service.analyze_image(
            image_base64=body.image_base64,
            mime_type=body.image_mime_type,
            prompt=prompt,
            system_prompt=system,
        )
    except Exception as e:
        logger.error(f"Plant diagnosis failed: {e}")
        raise HTTPException(status_code=503, detail="AI vision service unavailable")

    try:
        text = raw.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1]) if lines[-1] == "```" else "\n".join(lines[1:])
        data = json.loads(text)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse plant diagnosis response: {e}\nRaw: {raw}")
        raise HTTPException(status_code=422, detail="Could not read diagnosis from image. Try a clearer, well-lit photo of the plant.")

    issues = [PlantDiagnosisIssue(**i) for i in data.get("issues", []) if isinstance(i, dict)]
    recs = [PlantDiagnosisAction(**r) for r in data.get("recommendations", []) if isinstance(r, dict)]

    # 4. Upload image + persist diagnosis (only for tracked plantings)
    image_key: Optional[str] = None
    image_signed_url: Optional[str] = None
    record_id: Optional[str] = None
    created_at: Optional[str] = None

    if body.planting_id:
        try:
            ext = (body.image_mime_type.split("/")[-1] or "jpg").replace("jpeg", "jpg")
            filename = f"{body.planting_id}_{int(time.time())}.{ext}"
            image_key = diagnosis_photo_key(user_id, filename)
            put_bytes(image_key, base64.b64decode(body.image_base64), body.image_mime_type)
        except Exception as e:
            logger.warning(f"Diagnosis image upload failed: {e}")
            image_key = None

        try:
            row = {
                "user_id": user_id,
                "planting_id": body.planting_id,
                "image_url": image_key,
                "identified_as": data.get("identified_as"),
                "stage": data.get("stage"),
                "stage_label": data.get("stage_label"),
                "estimated_age": data.get("estimated_age"),
                "health": data.get("health"),
                "health_score": data.get("health_score"),
                "ready_to_transplant": data.get("ready_to_transplant"),
                "ready_to_harvest": data.get("ready_to_harvest"),
                "summary": data.get("summary"),
                "confidence": data.get("confidence"),
                "issues": [i.model_dump() for i in issues],
                "recommendations": [r.model_dump() for r in recs],
                "weather_snapshot": weather_snapshot,
                "plant_name_hint": body.plant_name_hint,
                "user_note": body.user_note,
            }
            inserted = sb.table("plant_diagnoses").insert(row).execute()
            if inserted.data:
                record_id = inserted.data[0].get("id")
                created_at = inserted.data[0].get("created_at")
        except Exception as e:
            logger.error(f"Failed to persist diagnosis: {e}")

        if image_key:
            try:
                image_signed_url = generate_download_url(image_key)
            except Exception:
                pass

    return PlantDiagnosisResponse(
        id=record_id,
        planting_id=body.planting_id,
        image_url=image_signed_url,
        identified_as=data.get("identified_as"),
        stage=data.get("stage", "unknown"),
        stage_label=data.get("stage_label"),
        estimated_age=data.get("estimated_age"),
        health=data.get("health", "unknown"),
        health_score=data.get("health_score"),
        ready_to_transplant=data.get("ready_to_transplant"),
        ready_to_harvest=data.get("ready_to_harvest"),
        issues=issues,
        recommendations=recs,
        summary=data.get("summary", ""),
        confidence=data.get("confidence"),
        created_at=created_at,
    )


@router.get("/diagnoses", response_model=List[PlantDiagnosisSummary])
async def list_diagnoses(
    request: Request,
    planting_id: Optional[str] = None,
    limit: int = 50,
    authorization: Optional[str] = Header(None),
):
    """List diagnoses for the current user, optionally filtered by planting."""
    user_id = _require_user(request, authorization)
    sb = request.app.state.supabase

    q = (
        sb.table("plant_diagnoses")
        .select("id,planting_id,image_url,identified_as,stage,stage_label,health,health_score,summary,created_at")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(max(1, min(limit, 200)))
    )
    if planting_id:
        q = q.eq("planting_id", planting_id)

    res = q.execute()
    out = []
    for r in (res.data or []):
        signed = None
        if r.get("image_url"):
            try:
                signed = generate_download_url(r["image_url"])
            except Exception:
                signed = None
        out.append(PlantDiagnosisSummary(
            id=r["id"],
            planting_id=r.get("planting_id"),
            image_url=signed,
            identified_as=r.get("identified_as"),
            stage=r.get("stage"),
            stage_label=r.get("stage_label"),
            health=r.get("health"),
            health_score=r.get("health_score"),
            summary=r.get("summary"),
            created_at=r["created_at"],
        ))
    return out


@router.get("/diagnoses/{diagnosis_id}", response_model=PlantDiagnosisResponse)
async def get_diagnosis(
    diagnosis_id: str,
    request: Request,
    authorization: Optional[str] = Header(None),
):
    """Fetch a single diagnosis in full."""
    user_id = _require_user(request, authorization)
    sb = request.app.state.supabase

    res = (
        sb.table("plant_diagnoses")
        .select("*")
        .eq("id", diagnosis_id)
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    r = res and res.data
    if not r:
        raise HTTPException(status_code=404, detail="Diagnosis not found")

    signed = None
    if r.get("image_url"):
        try:
            signed = generate_download_url(r["image_url"])
        except Exception:
            pass

    issues = [PlantDiagnosisIssue(**i) for i in (r.get("issues") or []) if isinstance(i, dict)]
    recs = [PlantDiagnosisAction(**a) for a in (r.get("recommendations") or []) if isinstance(a, dict)]

    return PlantDiagnosisResponse(
        id=r["id"],
        planting_id=r.get("planting_id"),
        image_url=signed,
        identified_as=r.get("identified_as"),
        stage=r.get("stage") or "unknown",
        stage_label=r.get("stage_label"),
        estimated_age=r.get("estimated_age"),
        health=r.get("health") or "unknown",
        health_score=r.get("health_score"),
        ready_to_transplant=r.get("ready_to_transplant"),
        ready_to_harvest=r.get("ready_to_harvest"),
        issues=issues,
        recommendations=recs,
        summary=r.get("summary") or "",
        confidence=r.get("confidence"),
        created_at=r.get("created_at"),
    )


@router.delete("/diagnoses/{diagnosis_id}")
async def delete_diagnosis(
    diagnosis_id: str,
    request: Request,
    authorization: Optional[str] = Header(None),
):
    user_id = _require_user(request, authorization)
    sb = request.app.state.supabase
    sb.table("plant_diagnoses").delete().eq("id", diagnosis_id).eq("user_id", user_id).execute()
    return {"ok": True}
