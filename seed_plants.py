"""
Rootsy — Plant Database Seed Script

Wipes the `plants` table and reseeds it from the curated data in plants_data.py.
Each plant's image_url is resolved from Wikipedia's REST API using the
`wiki_title` field, giving every plant its own unique, stable photo.

Usage:
    cp .env.example .env   # fill in SUPABASE_URL, SUPABASE_SERVICE_KEY
    python seed_plants.py
"""

import asyncio
import os
import logging
import httpx
from dotenv import load_dotenv
load_dotenv()

from supabase import create_client
from plants_data import PLANTS

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

WIKI_SUMMARY_URL = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"


async def _fetch_wiki_image(client: httpx.AsyncClient, title: str) -> str | None:
    """Return the original or thumbnail image URL for a Wikipedia article, or None."""
    try:
        resp = await client.get(
            WIKI_SUMMARY_URL.format(title=title),
            headers={"User-Agent": "Rootsy/1.0 (garden planner seed script)"},
        )
        if resp.status_code != 200:
            logger.warning(f"  Wikipedia returned {resp.status_code} for '{title}'")
            return None
        data = resp.json()
        original = (data.get("originalimage") or {}).get("source")
        thumb = (data.get("thumbnail") or {}).get("source")
        return original or thumb
    except Exception as e:
        logger.warning(f"  Wikipedia fetch failed for '{title}': {e}")
        return None


async def seed():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_KEY")
    if not url or not key:
        logger.error("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env")
        return

    sb = create_client(url, key)

    # Wipe existing data. Requires the plants.id column, which always exists.
    logger.info("Truncating existing plants table…")
    sb.table("plants").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()

    seeded = failed = 0

    async with httpx.AsyncClient(timeout=15.0) as client:
        for plant in PLANTS:
            name = plant["common_name"]
            try:
                wiki_title = plant.pop("wiki_title", None)
                image_url = await _fetch_wiki_image(client, wiki_title) if wiki_title else None
                if not image_url:
                    logger.warning(f"  No image for {name} (title: {wiki_title})")

                row = {**plant, "image_url": image_url}
                sb.table("plants").insert(row).execute()
                logger.info(f"  ✓ Seeded: {name}")
                seeded += 1
                await asyncio.sleep(0.1)  # be polite to Wikipedia

            except Exception as e:
                logger.error(f"  ✗ Failed for '{name}': {e}")
                failed += 1

    logger.info(f"\n--- Seed complete ---")
    logger.info(f"Seeded: {seeded} | Failed: {failed}")
    total = sb.table("plants").select("id", count="exact").execute()
    logger.info(f"Total plants in DB: {total.count}")


if __name__ == "__main__":
    asyncio.run(seed())
