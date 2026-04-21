"""
Rootsy — Plant Database Seed Script
Run once to pre-populate the plants table with common vegetables and herbs.
Uses the Trefle API (120 req/min free tier — much more generous than Perenual).

Usage:
    cp .env.example .env   # fill in SUPABASE_URL, SUPABASE_SERVICE_KEY, TREFLE_API_TOKEN
    python seed_plants.py
"""

import asyncio
import os
import logging
from dotenv import load_dotenv
load_dotenv()

from supabase import create_client
from trefle_service import trefle_service, _normalize_plant

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# Some common names differ from what Trefle indexes — override the search query here
QUERY_OVERRIDES: dict[str, str] = {
    "corn": "maize",
    "zucchini": "courgette",
}

COMMON_GARDEN_PLANTS = [
    # Vegetables
    "tomato", "cherry tomato", "cucumber", "zucchini", "carrot",
    "lettuce", "spinach", "kale", "swiss chard", "arugula",
    "bell pepper", "chili pepper", "eggplant", "broccoli", "cauliflower",
    "cabbage", "brussels sprouts", "pea", "green bean", "broad bean",
    "radish", "beet", "turnip", "parsnip", "sweet potato",
    "potato", "garlic", "onion", "leek", "shallot",
    "corn", "pumpkin", "butternut squash", "watermelon", "cantaloupe",
    # Herbs
    "basil", "parsley", "cilantro", "dill", "chive",
    "rosemary", "thyme", "oregano", "sage", "mint",
    "lavender", "lemon balm", "tarragon", "fennel", "chamomile",
]


# Maps query name -> preferred genera (genus part of scientific_name, lowercase)
# Ensures we pick the actual garden plant rather than a wild plant sharing the word
PREFERRED_GENERA: dict[str, list[str]] = {
    "tomato":           ["solanum", "lycopersicon"],
    "cherry tomato":    ["solanum", "lycopersicon"],
    "cucumber":         ["cucumis"],
    "zucchini":         ["cucurbita"],
    "carrot":           ["daucus"],
    "lettuce":          ["lactuca"],
    "spinach":          ["spinacia"],
    "kale":             ["brassica"],
    "swiss chard":      ["beta"],
    "arugula":          ["eruca"],
    "bell pepper":      ["capsicum"],
    "chili pepper":     ["capsicum"],
    "eggplant":         ["solanum"],
    "broccoli":         ["brassica"],
    "cauliflower":      ["brassica"],
    "cabbage":          ["brassica"],
    "brussels sprouts": ["brassica"],
    "pea":              ["pisum"],
    "green bean":       ["phaseolus"],
    "broad bean":       ["vicia"],
    "radish":           ["raphanus"],
    "beet":             ["beta"],
    "turnip":           ["brassica"],
    "parsnip":          ["pastinaca"],
    "sweet potato":     ["ipomoea"],
    "potato":           ["solanum"],
    "garlic":           ["allium"],
    "onion":            ["allium"],
    "leek":             ["allium"],
    "shallot":          ["allium"],
    "corn":             ["zea"],
    "pumpkin":          ["cucurbita"],
    "butternut squash": ["cucurbita"],
    "watermelon":       ["citrullus"],
    "cantaloupe":       ["cucumis"],
    "basil":            ["ocimum"],
    "parsley":          ["petroselinum"],
    "cilantro":         ["coriandrum"],
    "dill":             ["anethum"],
    "chive":            ["allium"],
    "rosemary":         ["salvia", "rosmarinus"],
    "thyme":            ["thymus"],
    "oregano":          ["origanum"],
    "sage":             ["salvia"],
    "mint":             ["mentha"],
    "lavender":         ["lavandula"],
    "lemon balm":       ["melissa"],
    "tarragon":         ["artemisia"],
    "fennel":           ["foeniculum"],
    "chamomile":        ["matricaria", "chamaemelum"],
}


def _genus(plant: dict) -> str:
    sci = (plant.get("scientific_name") or "").lower()
    return sci.split()[0] if sci else ""


def _best_match(raw_plants: list, query: str) -> dict | None:
    """Pick best Trefle plant, preferring known vegetable/herb genera.
    Priority: preferred-genus exact > preferred-genus starts > preferred-genus any
             > exact > starts > shortest-containing > first."""
    q = query.lower()
    preferred = PREFERRED_GENERA.get(q, [])

    def name(p):
        return (p.get("common_name") or "").lower()

    def is_preferred(p):
        return _genus(p) in preferred

    # Try within preferred genera first
    if preferred:
        pref_pool = [p for p in raw_plants if is_preferred(p)]
        if pref_pool:
            exact = [p for p in pref_pool if name(p) == q]
            if exact:
                return exact[0]
            starts = [p for p in pref_pool if name(p).startswith(q)]
            if starts:
                return min(starts, key=lambda p: len(name(p)))
            return pref_pool[0]   # any plant in the right genus

    # Fall back: name-based matching across all results
    exact = [p for p in raw_plants if name(p) == q]
    if exact:
        return exact[0]
    starts = [p for p in raw_plants if name(p).startswith(q)]
    if starts:
        return min(starts, key=lambda p: len(name(p)))
    contains = [p for p in raw_plants if q in name(p)]
    if contains:
        return min(contains, key=lambda p: len(name(p)))
    return raw_plants[0] if raw_plants else None


async def seed():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_KEY")
    if not url or not key:
        logger.error("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env")
        return
    if not trefle_service.token:
        logger.error("TREFLE_API_TOKEN must be set in .env")
        return

    sb = create_client(url, key)

    existing = sb.table("plants").select("id", count="exact").execute()
    logger.info(f"Plants already in DB: {existing.count or 0}")

    seeded = skipped = failed = 0

    for plant_name in COMMON_GARDEN_PLANTS:
        try:
            # Check DB first — skip Trefle entirely if already cached
            db_check = (
                sb.table("plants")
                .select("id")
                .ilike("common_name", plant_name)
                .limit(1)
                .execute()
            )
            if db_check.data:
                logger.info(f"  Already exists: {plant_name} — skipping")
                skipped += 1
                continue

            search_query = QUERY_OVERRIDES.get(plant_name, plant_name)
            logger.info(f"Fetching from Trefle: {plant_name} (query: {search_query})…")
            result = await trefle_service.search_plants(query=search_query, page=1, raw=True)
            raw_plants = result.get("results", [])

            if not raw_plants:
                logger.warning(f"  No results for '{plant_name}'")
                failed += 1
                continue

            best_raw = _best_match(raw_plants, plant_name)
            if not best_raw:
                failed += 1
                continue
            plant_data = _normalize_plant(best_raw)
            trefle_id = plant_data.get("perenual_id")   # column reused for Trefle ID
            if trefle_id:
                dup = (
                    sb.table("plants")
                    .select("id")
                    .eq("perenual_id", trefle_id)
                    .limit(1)
                    .execute()
                )
                if dup.data:
                    logger.info(f"  Already exists: {plant_data['common_name']}")
                    skipped += 1
                    continue

            sb.table("plants").upsert(plant_data, on_conflict="perenual_id").execute()
            logger.info(f"  ✓ Seeded: {plant_data['common_name']}")
            seeded += 1

            # Trefle: 120 req/min — small delay to be polite
            await asyncio.sleep(0.15)

        except Exception as e:
            logger.error(f"  ✗ Failed for '{plant_name}': {e}")
            failed += 1

    logger.info(f"\n--- Seed complete ---")
    logger.info(f"Seeded: {seeded} | Skipped: {skipped} | Failed: {failed}")
    total = sb.table("plants").select("id", count="exact").execute()
    logger.info(f"Total plants in DB: {total.count}")


if __name__ == "__main__":
    asyncio.run(seed())
