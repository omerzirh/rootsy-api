import logging
from typing import Optional, List
from datetime import date, timedelta
from fastapi import APIRouter, HTTPException, Header, Request, Query
from models import CreateCareTaskRequest, UpdateCareTaskRequest, CareTask

logger = logging.getLogger(__name__)
router = APIRouter()


def _require_user(request: Request, authorization: Optional[str]) -> str:
    user_id = request.app.state.extract_user_id(authorization)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authorization required")
    return user_id


# Watering frequency defaults by plant type (days between watering)
WATERING_DEFAULTS = {
    "frequent": 2,
    "average": 3,
    "minimum": 7,
}


@router.get("/tasks", response_model=List[CareTask])
async def list_tasks(
    request: Request,
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    status: Optional[str] = Query(None),  # pending | completed | all
    authorization: Optional[str] = Header(None),
):
    user_id = _require_user(request, authorization)
    sb = request.app.state.supabase

    query = sb.table("care_tasks").select("*").eq("user_id", user_id)

    if from_date:
        query = query.gte("due_date", from_date)
    if to_date:
        query = query.lte("due_date", to_date)
    if status == "pending":
        query = query.eq("is_completed", False)
    elif status == "completed":
        query = query.eq("is_completed", True)

    result = query.order("due_date").order("created_at").execute()
    return result.data or []


@router.post("/tasks", response_model=CareTask, status_code=201)
async def create_task(
    body: CreateCareTaskRequest,
    request: Request,
    authorization: Optional[str] = Header(None),
):
    user_id = _require_user(request, authorization)
    sb = request.app.state.supabase

    result = (
        sb.table("care_tasks")
        .insert({
            "user_id": user_id,
            "title": body.title,
            "task_type": body.task_type,
            "description": body.description,
            "planting_id": body.planting_id,
            "garden_bed_id": body.garden_bed_id,
            "due_date": body.due_date,
            "due_time": body.due_time,
            "is_recurring": body.is_recurring,
            "recurrence_days": body.recurrence_days,
            "is_completed": False,
        })
        .execute()
    )
    return result.data[0]


@router.patch("/tasks/{task_id}", response_model=CareTask)
async def update_task(
    task_id: str,
    body: UpdateCareTaskRequest,
    request: Request,
    authorization: Optional[str] = Header(None),
):
    user_id = _require_user(request, authorization)
    sb = request.app.state.supabase

    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    # If marking complete, set completed_at and spawn next recurrence
    if updates.get("is_completed") is True:
        from datetime import datetime, timezone
        updates["completed_at"] = datetime.now(timezone.utc).isoformat()

    result = (
        sb.table("care_tasks")
        .update(updates)
        .eq("id", task_id)
        .eq("user_id", user_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Task not found")

    task = result.data[0]

    # Auto-create next recurrence if recurring task was completed
    if updates.get("is_completed") is True and task.get("is_recurring") and task.get("recurrence_days") and task.get("due_date"):
        try:
            next_due = (date.fromisoformat(task["due_date"]) + timedelta(days=task["recurrence_days"])).isoformat()
            sb.table("care_tasks").insert({
                "user_id": user_id,
                "title": task["title"],
                "task_type": task["task_type"],
                "description": task.get("description"),
                "planting_id": task.get("planting_id"),
                "garden_bed_id": task.get("garden_bed_id"),
                "due_date": next_due,
                "due_time": task.get("due_time"),
                "is_recurring": True,
                "recurrence_days": task["recurrence_days"],
                "is_completed": False,
            }).execute()
        except Exception as e:
            logger.warning(f"Failed to create recurrence for task {task_id}: {e}")

    return task


@router.delete("/tasks/{task_id}", status_code=204)
async def delete_task(
    task_id: str,
    request: Request,
    authorization: Optional[str] = Header(None),
):
    user_id = _require_user(request, authorization)
    sb = request.app.state.supabase

    sb.table("care_tasks").delete().eq("id", task_id).eq("user_id", user_id).execute()


@router.post("/generate")
async def generate_care_schedule(
    request: Request,
    planting_id: str = Query(...),
    authorization: Optional[str] = Header(None),
):
    """Auto-generate a care task schedule for a planting based on plant type."""
    user_id = _require_user(request, authorization)
    sb = request.app.state.supabase

    # Get planting + plant info
    planting = (
        sb.table("plantings")
        .select("*")
        .eq("id", planting_id)
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    if not planting.data:
        raise HTTPException(status_code=404, detail="Planting not found")

    p = planting.data
    plant = (
        sb.table("plants")
        .select("common_name,watering,care_level,harvest_days_max")
        .eq("id", p["plant_id"])
        .maybe_single()
        .execute()
    )
    plant_data = plant.data or {}
    plant_name = plant_data.get("common_name", "Plant")
    watering = plant_data.get("watering", "average")
    today = date.today()
    planted = date.fromisoformat(p["planted_date"]) if p.get("planted_date") else today

    water_days = WATERING_DEFAULTS.get(watering, 3)
    tasks_to_create = []

    # Watering schedule (recurring)
    tasks_to_create.append({
        "user_id": user_id,
        "title": f"Water {plant_name}",
        "task_type": "water",
        "description": f"Water your {plant_name}. Check soil moisture first.",
        "planting_id": planting_id,
        "due_date": today.isoformat(),
        "is_recurring": True,
        "recurrence_days": water_days,
        "is_completed": False,
    })

    # Fertilize at 2 weeks
    fertilize_date = planted + timedelta(weeks=2)
    if fertilize_date >= today:
        tasks_to_create.append({
            "user_id": user_id,
            "title": f"Fertilize {plant_name}",
            "task_type": "fertilize",
            "description": "Apply balanced fertilizer or compost.",
            "planting_id": planting_id,
            "due_date": fertilize_date.isoformat(),
            "is_recurring": True,
            "recurrence_days": 14,
            "is_completed": False,
        })

    # Pest check at 1 week
    pest_date = planted + timedelta(weeks=1)
    if pest_date >= today:
        tasks_to_create.append({
            "user_id": user_id,
            "title": f"Pest check — {plant_name}",
            "task_type": "pest_check",
            "description": "Check leaves (top and bottom) for insects, signs of disease.",
            "planting_id": planting_id,
            "due_date": pest_date.isoformat(),
            "is_recurring": True,
            "recurrence_days": 7,
            "is_completed": False,
        })

    # Harvest reminder
    harvest_days = plant_data.get("harvest_days_max")
    if harvest_days and p.get("planted_date"):
        harvest_date = planted + timedelta(days=int(harvest_days))
        reminder_date = harvest_date - timedelta(days=7)
        if reminder_date >= today:
            tasks_to_create.append({
                "user_id": user_id,
                "title": f"Harvest {plant_name} soon",
                "task_type": "harvest",
                "description": f"Expected harvest around {harvest_date.isoformat()}. Check ripeness.",
                "planting_id": planting_id,
                "due_date": reminder_date.isoformat(),
                "is_recurring": False,
                "is_completed": False,
            })

    created = []
    for task in tasks_to_create:
        result = sb.table("care_tasks").insert(task).execute()
        if result.data:
            created.append(result.data[0])

    return {"created": len(created), "tasks": created}
