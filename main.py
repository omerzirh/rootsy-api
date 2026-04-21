import os
import logging
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from supabase import create_client, Client

# Route modules
from plant_routes import router as plants_router
from garden_routes import router as garden_router
from planting_routes import router as plantings_router
from weather_routes import router as weather_router
from ai_routes import router as ai_router
from care_routes import router as care_router
from storage_routes import router as storage_router

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# JWT helper
# ---------------------------------------------------------------------------

def extract_user_id_from_token(authorization: Optional[str]) -> Optional[str]:
    """Extract user_id from Authorization: Bearer <token> header."""
    if not authorization:
        return None
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1]
    # UUID passthrough for local testing
    if len(token) == 36 and token.count("-") == 4:
        return token
    try:
        import jwt as pyjwt
        jwt_secret = os.getenv("SUPABASE_JWT_SECRET")
        decoded = None
        if jwt_secret:
            # Try with audience first, then without (some Supabase tokens omit it)
            for opts in [
                {"algorithms": ["HS256"], "audience": "authenticated"},
                {"algorithms": ["HS256"]},
            ]:
                try:
                    decoded = pyjwt.decode(token, jwt_secret, **opts)
                    break
                except Exception:
                    continue
        if decoded is None:
            # Fallback: extract sub without verifying signature (dev/misconfigured secret)
            decoded = pyjwt.decode(
                token, options={"verify_signature": False}, algorithms=["HS256"]
            )
        return decoded.get("sub")
    except Exception as e:
        logger.warning(f"Failed to decode JWT: {e}")
        return None


# ---------------------------------------------------------------------------
# Supabase client (service role — used by route handlers via app.state)
# ---------------------------------------------------------------------------

def get_supabase() -> Client:
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
    return create_client(url, key)


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(title="Rootsy API", version="1.0.0", description="Garden planning backend")

# CORS
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")
if ALLOWED_ORIGINS == ["*"]:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.on_event("startup")
async def startup():
    app.state.supabase = get_supabase()
    app.state.extract_user_id = extract_user_id_from_token
    logger.info("Rootsy API started")


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(plants_router, prefix="/api/plants", tags=["plants"])
app.include_router(garden_router, prefix="/api/garden", tags=["garden"])
app.include_router(plantings_router, prefix="/api/plantings", tags=["plantings"])
app.include_router(weather_router, prefix="/api/weather", tags=["weather"])
app.include_router(ai_router, prefix="/api/ai", tags=["ai"])
app.include_router(care_router, prefix="/api/care", tags=["care"])
app.include_router(storage_router, prefix="/api/storage", tags=["storage"])


# ---------------------------------------------------------------------------
# Core endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"status": "ok", "service": "rootsy-api"}


@app.get("/")
async def root():
    return {"message": "Rootsy API", "docs": "/docs"}


# ---------------------------------------------------------------------------
# Global exception handler
# ---------------------------------------------------------------------------

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    import traceback
    logger.error(f"Unhandled exception: {request.url} — {exc}")
    logger.error(traceback.format_exc())
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "details": str(exc), "type": type(exc).__name__},
    )
