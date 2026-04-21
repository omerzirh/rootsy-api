import json
import logging
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Header, Request
from models import (
    ChatRequest, ChatResponse, ChatMessage,
    PhotoToMapRequest, PhotoToMapResponse, DetectedBed,
)
from openrouter_service import openrouter_service

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
