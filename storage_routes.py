import time
from typing import Optional
from fastapi import APIRouter, HTTPException, Header, Request
from pydantic import BaseModel
from storage_service import (
    generate_upload_url, generate_download_url,
    plant_photo_key, garden_photo_key,
)

router = APIRouter()


def _require_user(request: Request, authorization: Optional[str]) -> str:
    user_id = request.app.state.extract_user_id(authorization)
    if not user_id:
        raise HTTPException(status_code=401, detail="Authorization required")
    return user_id


class UploadUrlRequest(BaseModel):
    type: str           # "plant_photo" | "garden_photo"
    planting_id: str | None = None
    garden_id: str | None = None
    content_type: str = "image/jpeg"


class UploadUrlResponse(BaseModel):
    upload_url: str
    object_key: str


class SignedUrlResponse(BaseModel):
    signed_url: str


@router.post("/upload-url", response_model=UploadUrlResponse)
async def get_upload_url(
    body: UploadUrlRequest,
    request: Request,
    authorization: Optional[str] = Header(None),
):
    user_id = _require_user(request, authorization)
    ext = body.content_type.split("/")[-1] or "jpg"

    if body.type == "plant_photo":
        if not body.planting_id:
            raise HTTPException(400, "planting_id required for plant_photo")
        key = plant_photo_key(user_id, body.planting_id, f"{int(time.time())}.{ext}")

    elif body.type == "garden_photo":
        if not body.garden_id:
            raise HTTPException(400, "garden_id required for garden_photo")
        key = garden_photo_key(user_id, body.garden_id)

    else:
        raise HTTPException(400, f"Unknown upload type: {body.type}")

    url = generate_upload_url(key, body.content_type)
    return UploadUrlResponse(upload_url=url, object_key=key)


@router.get("/signed-url", response_model=SignedUrlResponse)
async def get_signed_url(
    object_key: str,
    request: Request,
    authorization: Optional[str] = Header(None),
):
    user_id = _require_user(request, authorization)
    # Basic ownership check — key must contain the user_id segment
    if user_id not in object_key:
        raise HTTPException(403, "Access denied")
    url = generate_download_url(object_key)
    return SignedUrlResponse(signed_url=url)
