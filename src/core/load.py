"""
core/load.py — append-only GeoJSON + CSV writer.
Modeled on floodwire/src/load_files.py.

Key changes from original climatewire load.py:
- GeoJSON only contains rows with valid coordinates (no null-geometry features)
- Dedup key is (article_id, mention_text) not just article_id
- CSV dedup uses same composite key
- Explicit field list for CSV (stable column order)
- Logs feature count after every write
"""

import csv
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple

logger = logging.getLogger(__name__)

CSV_FIELDS = [
    "article_id", "title", "snippet", "url", "source",
    "published_at", "wire", "fetched_at",
    "mention_text", "osm_display", "osm_type", "geocoded",
    "event_type",
    "usdm_dm_category", "usdm_dm_label", "usdm_in_drought",
    "lat", "lon",
    "run_at",
]


def write_outputs(rows, wire, data_dir):
    # type: (List[dict], str, object) -> Tuple[int, int]
    """
    Append new rows to data/<wire>.geojson and data/<wire>.csv.

    GeoJSON: only rows with valid lat/lon (no null-geometry features).
    CSV: all rows including ungeocodeable ones (geocoded=False).
    Dedup key: (article_id, mention_text).

    Returns (new_rows_written, total_rows_in_geojson).
    """
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    geojson_path = data_dir / "{}.geojson".format(wire)
    csv_path     = data_dir / "{}.csv".format(wire)

    run_at = datetime.now(timezone.utc).isoformat()
    for r in rows:
        r["run_at"] = run_at

    geo_written  = _append_geojson(rows, geojson_path, wire)
    csv_written  = _append_csv(rows, csv_path)

    logger.info("[%s] write_outputs done — %d GeoJSON features written, %d CSV rows written",
                wire, geo_written, csv_written)
    return geo_written, geo_written


def _append_geojson(rows, path, wire):
    # type: (List[dict], Path, str) -> int
    """Append geocoded rows to GeoJSON. Skips null-coord rows entirely."""
    existing_keys = set()
    features = []

    if path.exists():
        try:
            fc = json.loads(path.read_text(encoding="utf-8"))
            features = fc.get("features", [])
            for f in features:
                props = f.get("properties", {})
                existing_keys.add((props.get("article_id", ""), props.get("mention_text", "")))
        except Exception as e:
            logger.warning("[%s] Could not parse existing GeoJSON, starting fresh: %s", wire, e)
            features = []

    appended = 0
    skipped_no_geo = 0
    skipped_dupe = 0

    for row in rows:
        lat = row.get("lat")
        lon = row.get("lon")

        if lat is None or lon is None:
            skipped_no_geo += 1
            continue

        key = (row.get("article_id", ""), row.get("mention_text", ""))
        if key in existing_keys:
            skipped_dupe += 1
            continue

        existing_keys.add(key)
        props = {k: v for k, v in row.items() if k not in ("lat", "lon")}
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": props,
        })
        appended += 1

    if skipped_no_geo:
        logger.info("[%s] GeoJSON: skipped %d rows with no coordinates", wire, skipped_no_geo)
    if skipped_dupe:
        logger.info("[%s] GeoJSON: skipped %d duplicate rows", wire, skipped_dupe)

    fc = {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "wire":           wire,
            "last_updated":   datetime.now(timezone.utc).isoformat(),
            "total_features": len(features),
        },
    }
    try:
        path.write_text(json.dumps(fc, indent=2), encoding="utf-8")
        logger.info("[%s] GeoJSON written: %s (%d total features, +%d new)",
                    wire, path, len(features), appended)
    except Exception as e:
        logger.error("[%s] GeoJSON write failed: %s", wire, e)

    return appended


def _append_csv(rows, path):
    # type: (List[dict], Path) -> int
    """Append all rows (including ungeocodeable) to CSV."""
    existing_keys = set()
    write_header = not path.exists() or path.stat().st_size == 0

    if not write_header:
        try:
            with path.open(newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for r in reader:
                    existing_keys.add((r.get("article_id", ""), r.get("mention_text", "")))
        except Exception as e:
            logger.warning("Could not read existing CSV, starting fresh: %s", e)
            write_header = True

    new_rows = []
    for row in rows:
        key = (row.get("article_id", ""), row.get("mention_text", ""))
        if key not in existing_keys:
            existing_keys.add(key)
            new_rows.append(row)

    if not new_rows:
        logger.info("CSV: no new rows to write")
        return 0

    try:
        with path.open("a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
            if write_header:
                writer.writeheader()
            writer.writerows(new_rows)
        logger.info("CSV written: %s (+%d rows)", path, len(new_rows))
    except Exception as e:
        logger.error("CSV write failed: %s", e)

    return len(new_rows)
