"""
Fix plant image URLs — replaces broken Perenual images with Trefle/PlantNet URLs.
Run once after switching from Perenual to Trefle.

Usage:  python fix_images.py
"""

import asyncio
import os
import logging
from dotenv import load_dotenv
load_dotenv()

from supabase import create_client
from trefle_service import trefle_service, _normalize_plant
from seed_plants import _best_match, PREFERRED_GENERA, QUERY_OVERRIDES

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def _is_broken_image(url: str | None) -> bool:
    if not url:
        return True
    return "wasabisys" in url or "perenual" in url


async def fix_images():
    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_KEY"))

    # Fetch all plants with Perenual/missing images
    result = sb.table("plants").select("id,common_name,image_url").execute()
    broken = [p for p in result.data if _is_broken_image(p.get("image_url"))]
    logger.info(f"Plants needing image fix: {len(broken)}")

    fixed = skipped = failed = 0

    for plant in broken:
        name = plant["common_name"].lower()
        search_query = QUERY_OVERRIDES.get(name, name)

        try:
            r = await trefle_service.search_plants(query=search_query, page=1, raw=True)
            raw_plants = r.get("results", [])

            if not raw_plants:
                logger.warning(f"  No Trefle results for '{name}'")
                failed += 1
                continue

            best = _best_match(raw_plants, name)
            if not best:
                failed += 1
                continue

            image_url = best.get("image_url")
            if not image_url:
                logger.warning(f"  No image in Trefle for '{name}'")
                skipped += 1
                continue

            sb.table("plants").update({"image_url": image_url}).eq("id", plant["id"]).execute()
            logger.info(f"  ✓ Fixed: {plant['common_name']} → {image_url[:60]}")
            fixed += 1

            await asyncio.sleep(0.1)

        except Exception as e:
            logger.error(f"  ✗ Failed for '{name}': {e}")
            failed += 1

    logger.info(f"\n--- Done ---")
    logger.info(f"Fixed: {fixed} | Skipped: {skipped} | Failed: {failed}")


if __name__ == "__main__":
    asyncio.run(fix_images())
