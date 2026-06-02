#!/usr/bin/env python3
"""
OPTIONAL one-off: write correct image URLs into recipes.image_url.

You normally DON'T need this — recipe_images.resolve_image runs automatically in
db._row_to_dict, so every recipe (existing and future) is served with a correct
image already. Run this only if you want the stored column itself cleaned, or to
pull real per-dish photos from TheMealDB with --mealdb.

Uses the SAME resolver as the live app (recipe_images.py) so there's one source
of truth — no drift as you add recipes.

Usage (from mealskart-backend/, with .env containing Supabase creds):
    python scripts/fix_recipe_images.py --dry-run          # preview only
    python scripts/fix_recipe_images.py --apply            # write to Supabase
    python scripts/fix_recipe_images.py --apply --mealdb   # also use TheMealDB real photos
    python scripts/fix_recipe_images.py --apply --force    # overwrite existing photos too
"""
from __future__ import annotations

import argparse
import os
import sys
import time

import httpx
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

from auth.supabase_client import supabase_admin          # noqa: E402
from recipe_images import resolve_image                  # noqa: E402  — single source of truth


def mealdb_image(name: str, client: httpx.Client) -> str | None:
    """Return TheMealDB photo for `name` only if the dish names clearly match."""
    try:
        r = client.get("https://www.themealdb.com/api/json/v1/1/search.php",
                        params={"s": name}, timeout=15)
        meals = (r.json() or {}).get("meals") or []
        want = "".join(ch for ch in name.lower() if ch.isalnum())
        for m in meals:
            got = "".join(ch for ch in (m.get("strMeal") or "").lower() if ch.isalnum())
            if got and (got in want or want in got):
                return m.get("strMealThumb")
    except Exception:
        return None
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="Clean recipes.image_url in Supabase.")
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    ap.add_argument("--dry-run", action="store_true", help="preview only")
    ap.add_argument("--mealdb", action="store_true", help="also pull real photos from TheMealDB (slower)")
    ap.add_argument("--force", action="store_true", help="overwrite existing real photos too")
    ap.add_argument("--limit", type=int, default=0, help="process only first N (testing)")
    args = ap.parse_args()
    apply = args.apply and not args.dry_run

    print("Loading recipes from Supabase…")
    rows = (supabase_admin.table("recipes").select("id, name, image_url").order("id").execute().data) or []
    if args.limit:
        rows = rows[: args.limit]
    print(f"  {len(rows)} recipes · mode={'APPLY' if apply else 'DRY-RUN'}"
          f"{' +mealdb' if args.mealdb else ''}{' +force' if args.force else ''}\n")

    client = httpx.Client() if args.mealdb else None
    updates, changed = [], 0
    for r in rows:
        name, existing = r.get("name") or "", r.get("image_url") or ""
        new_url = None
        if args.mealdb and client is not None:
            new_url = mealdb_image(name, client)
            time.sleep(0.2)  # be polite
        if not new_url:
            # --force: ignore the existing photo so a category image is chosen.
            new_url = resolve_image(name, "" if args.force else existing, r.get("id"))
        if new_url and new_url != existing:
            changed += 1
            updates.append({"id": r["id"], "image_url": new_url})
            if changed <= 40:
                print(f"  [{changed:4}] {name[:34]:34} → {new_url.split('/')[-1][:40]}")
    if client:
        client.close()

    print(f"\n{changed}/{len(rows)} recipes would change.")
    if not apply:
        print("Dry-run — nothing written. Re-run with --apply to save.")
        return 0
    print("Writing (batched)…")
    for i in range(0, len(updates), 100):
        supabase_admin.table("recipes").upsert(updates[i:i + 100], on_conflict="id").execute()
        print(f"  wrote {min(i + 100, len(updates))}/{len(updates)}")
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
