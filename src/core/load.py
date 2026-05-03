"""
core/load.py — append-only GeoJSON + CSV writer with dedup on article_id.
Same pattern as floodwire2/src/load_files.py, generalised.
"""

import csv
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _load_existing_ids(csv_path: Path) -> set[str]:
    """Return set of article_ids already in the CSV."""
    if not csv_path.exists():
        return set()
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return {row["article_id"] for row in reader if row.get("article_id")}


def _rows_to_features(rows: list[dict]) -> list[dict]:
    """Convert flat dicts to GeoJSON Feature objects."""
    features = []
    for r in rows:
        lat = r.get("lat")
        lon = r.get("lon")
        if lat is None or lon is None:
            continue
        props = {k: v for k, v in r.items() if k not in ("lat", "lon")}
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": props,
        })
    return features


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def write_outputs(
    rows: list[dict],
    wire: str,
    data_dir: str | Path = "data",
) -> tuple[int, int]:
    """
    Append new rows to data/<wire>.geojson and data/<wire>.csv.
    Deduplicates on article_id.

    Returns (new_rows_written, total_rows_in_file).
    """
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    geojson_path = data_dir / f"{wire}.geojson"
    csv_path = data_dir / f"{wire}.csv"

    # --- dedup ---
    existing_ids = _load_existing_ids(csv_path)
    new_rows = [r for r in rows if r.get("article_id") not in existing_ids]
    if not new_rows:
        logger.info(f"[{wire}] no new rows to write")
        return 0, len(existing_ids)

    run_at = datetime.now(timezone.utc).isoformat()
    for r in new_rows:
        r["run_at"] = run_at

    # --- CSV (append) ---
    all_keys = list(new_rows[0].keys())
    write_header = not csv_path.exists()
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=all_keys, extrasaction="ignore")
        if write_header:
            writer.writeheader()
        writer.writerows(new_rows)

    # --- GeoJSON (rewrite full file) ---
    # Load existing features
    if geojson_path.exists():
        with open(geojson_path, encoding="utf-8") as f:
            existing_fc = json.load(f)
        existing_features = existing_fc.get("features", [])
    else:
        existing_features = []

    new_features = _rows_to_features(new_rows)
    all_features = existing_features + new_features

    fc = {
        "type": "FeatureCollection",
        "features": all_features,
        "metadata": {
            "wire": wire,
            "last_updated": run_at,
            "total_features": len(all_features),
        },
    }
    with open(geojson_path, "w", encoding="utf-8") as f:
        json.dump(fc, f, indent=2)

    total = len(existing_ids) + len(new_rows)
    logger.info(f"[{wire}] wrote {len(new_rows)} new rows (total {total})")
    return len(new_rows), total
