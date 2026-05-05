"""
core/geocode.py — location extraction + OSM Nominatim geocoder.
Compatible with Python 3.9+.

Architecture
------------
Two-stage geocoding:

Stage 1 — Static lookup (instant, no API):
  If the best candidate is a known US state or major landmark,
  resolve it from a local lat/lon table. No Nominatim call needed.
  Covers the vast majority of climate news articles which reference
  states, major cities, rivers, lakes, and national parks.

Stage 2 — Nominatim (API, rate-limited):
  Only called when Stage 1 misses. Handles counties, smaller cities,
  specific place names not in the static table.

This design means state-level articles ("Colorado drought", "Florida
water shortage") never hit Nominatim and never fail due to USER_AGENT
or rate limit issues.
"""

import re
import time
import logging
import requests
from typing import List, Optional, Tuple, Dict

logger = logging.getLogger(__name__)

try:
    import spacy
    _nlp = spacy.load("en_core_web_sm")
    _SPACY_AVAILABLE = True
    logger.debug("spaCy loaded OK")
except Exception as e:
    _nlp = None
    _SPACY_AVAILABLE = False
    logger.warning("spaCy unavailable (%s) — using regex-only extraction", e)

try:
    from tenacity import (
        retry, stop_after_attempt, wait_exponential,
        retry_if_exception_type,
    )
    _TENACITY = True
except ImportError:
    _TENACITY = False
    logger.debug("tenacity not installed — Nominatim calls have no retry")

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
SPACY_MAX_CHARS = 5000

_PLACE_RE = re.compile(r"\b([A-Z][a-z]+(?: [A-Z][a-z]+)*(?:,\s*[A-Z]{2})?)\b")

_SKIP_TOKENS = {
    "I", "A", "The", "In", "At", "On", "To", "Of", "And", "Or", "For",
    "By", "As", "An", "Is", "It", "Be", "We", "He", "She", "They",
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
    "United", "States", "Americans", "American", "Officials", "Governor",
    "Commissioner", "District", "Department", "County", "National", "State",
    "New", "South", "North", "East", "West",
}

# ---------------------------------------------------------------------------
# Stage 1: Static lat/lon lookup table
# ---------------------------------------------------------------------------

# (lat, lon, osm_type) for static resolution
_STATIC_GEO = {
    # US States
    "alabama":        (32.806671, -86.791130, "state"),
    "alaska":         (61.370716, -152.404419, "state"),
    "arizona":        (33.729759, -111.431221, "state"),
    "arkansas":       (34.969704, -92.373123, "state"),
    "california":     (36.116203, -119.681564, "state"),
    "colorado":       (39.059811, -105.311104, "state"),
    "connecticut":    (41.597782, -72.755371, "state"),
    "delaware":       (39.318523, -75.507141, "state"),
    "florida":        (27.766279, -81.686783, "state"),
    "georgia":        (33.040619, -83.643074, "state"),
    "hawaii":         (21.094318, -157.498337, "state"),
    "idaho":          (44.240459, -114.478828, "state"),
    "illinois":       (40.349457, -88.986137, "state"),
    "indiana":        (39.849426, -86.258278, "state"),
    "iowa":           (42.011539, -93.210526, "state"),
    "kansas":         (38.526600, -96.726486, "state"),
    "kentucky":       (37.668140, -84.670067, "state"),
    "louisiana":      (31.169960, -91.867805, "state"),
    "maine":          (44.693947, -69.381927, "state"),
    "maryland":       (39.063946, -76.802101, "state"),
    "massachusetts":  (42.230171, -71.530106, "state"),
    "michigan":       (43.326618, -84.536095, "state"),
    "minnesota":      (45.694454, -93.900192, "state"),
    "mississippi":    (32.741646, -89.678696, "state"),
    "missouri":       (38.456085, -92.288368, "state"),
    "montana":        (46.921925, -110.454353, "state"),
    "nebraska":       (41.125370, -98.268082, "state"),
    "nevada":         (38.313515, -117.055374, "state"),
    "new hampshire":  (43.452492, -71.563896, "state"),
    "new jersey":     (40.298904, -74.521011, "state"),
    "new mexico":     (34.840515, -106.248482, "state"),
    "new york":       (42.165726, -74.948051, "state"),
    "north carolina": (35.630066, -79.806419, "state"),
    "north dakota":   (47.528912, -99.784012, "state"),
    "ohio":           (40.388783, -82.764915, "state"),
    "oklahoma":       (35.565342, -96.928917, "state"),
    "oregon":         (44.572021, -122.070938, "state"),
    "pennsylvania":   (40.590752, -77.209755, "state"),
    "rhode island":   (41.680893, -71.511780, "state"),
    "south carolina": (33.856892, -80.945007, "state"),
    "south dakota":   (44.299782, -99.438828, "state"),
    "tennessee":      (35.747845, -86.692345, "state"),
    "texas":          (31.054487, -97.563461, "state"),
    "utah":           (40.150032, -111.862434, "state"),
    "vermont":        (44.045876, -72.710686, "state"),
    "virginia":       (37.769337, -78.169968, "state"),
    "washington":     (47.400902, -121.490494, "state"),
    "washington state": (47.400902, -121.490494, "state"),
    "west virginia":  (38.491226, -80.954453, "state"),
    "wisconsin":      (44.268543, -89.616508, "state"),
    "wyoming":        (42.755966, -107.302490, "state"),
    # Major cities
    "los angeles":    (34.052235, -118.243683, "city"),
    "new york city":  (40.712776, -74.005974, "city"),
    "chicago":        (41.878113, -87.629799, "city"),
    "houston":        (29.760427, -95.369804, "city"),
    "phoenix":        (33.448376, -112.074036, "city"),
    "philadelphia":   (39.952583, -75.165222, "city"),
    "san antonio":    (29.424122, -98.493629, "city"),
    "san diego":      (32.715736, -117.161087, "city"),
    "dallas":         (32.776665, -96.796989, "city"),
    "san francisco":  (37.774929, -122.419418, "city"),
    "seattle":        (47.606209, -122.332071, "city"),
    "denver":         (39.739236, -104.984862, "city"),
    "las vegas":      (36.174969, -115.137341, "city"),
    "portland":       (45.523064, -122.676483, "city"),
    "miami":          (25.774266, -80.193659, "city"),
    "atlanta":        (33.748997, -84.387985, "city"),
    "minneapolis":    (44.977753, -93.265011, "city"),
    "tucson":         (32.222607, -110.974709, "city"),
    "albuquerque":    (35.084491, -106.651138, "city"),
    "corpus christi": (27.800583, -97.396381, "city"),
    "yakima":         (46.602076, -120.505898, "city"),
    # Major water bodies / regions
    "lake mead":          (36.015556, -114.737778, "lake"),
    "lake powell":        (37.068310, -111.258926, "lake"),
    "colorado river":     (36.105793, -113.034153, "river"),
    "mississippi river":  (35.149037, -90.048271, "river"),
    "columbia river":     (45.619946, -121.199837, "river"),
    "rio grande":         (29.736446, -99.104759, "river"),
    "great salt lake":    (41.180836, -112.584764, "lake"),
    "chesapeake bay":     (37.790985, -76.027283, "bay"),
    # National parks / forests / regions
    "yellowstone national park":     (44.427963, -110.588455, "park"),
    "grand canyon":                  (36.106965, -112.112997, "park"),
    "big cypress national preserve": (26.007800, -81.075600, "park"),
    "shasta":                        (40.766171, -122.289993, "peak"),
    "navajo nation":                 (36.507747, -108.671873, "region"),
    "pacific northwest":             (47.000000, -120.500000, "region"),
    "southwest":                     (34.048928, -111.093731, "region"),
    "southeast":                     (33.000000, -85.000000, "region"),
    "great plains":                  (41.000000, -100.000000, "region"),
    "midwest":                       (41.000000, -89.000000, "region"),
    "great lakes":                   (45.000000, -84.000000, "region"),
}


def _static_lookup(mention):
    # type: (str) -> Optional[Dict]
    """Check static table. Returns geo dict or None."""
    key = mention.lower().strip()
    # Exact match
    if key in _STATIC_GEO:
        lat, lon, osm_type = _STATIC_GEO[key]
        return {"lat": lat, "lon": lon,
                "osm_display": mention, "osm_type": osm_type,
                "source": "static"}
    # Strip possessives and trailing punctuation
    key2 = re.sub(r"['\u2019]s?\s*$", "", key).strip()
    if key2 in _STATIC_GEO:
        lat, lon, osm_type = _STATIC_GEO[key2]
        return {"lat": lat, "lon": lon,
                "osm_display": mention, "osm_type": osm_type,
                "source": "static"}
    # Partial match: candidate contains a known key
    for k, (lat, lon, osm_type) in _STATIC_GEO.items():
        if k in key and len(k) > 5:
            return {"lat": lat, "lon": lon,
                    "osm_display": mention, "osm_type": osm_type,
                    "source": "static_partial"}
    return None


# ---------------------------------------------------------------------------
# Nominatim (Stage 2)
# ---------------------------------------------------------------------------

def _validate_user_agent(user_agent):
    # type: (str) -> None
    blank = not user_agent or user_agent.strip() in (
        "", "climatewire/1.0", "yourname@example.com"
    )
    if blank:
        logger.warning(
            "USER_AGENT is '%s' — Nominatim calls will likely return 403. "
            "Set the USER_AGENT secret. Stage 1 static lookup is unaffected.",
            user_agent,
        )


def _nominatim_call(query, user_agent, timeout=10):
    # type: (str, str, int) -> list
    params = {
        "q": query,
        "format": "jsonv2",
        "limit": 1,
        "countrycodes": "us",
        "addressdetails": 1,
    }
    resp = requests.get(
        NOMINATIM_URL,
        params=params,
        headers={"User-Agent": user_agent},
        timeout=timeout,
    )
    if not resp.ok:
        logger.warning("Nominatim HTTP %d for '%s': %s",
                       resp.status_code, query, resp.text[:200])
        resp.raise_for_status()
    return resp.json()


if _TENACITY:
    _nominatim_call = retry(
        retry=retry_if_exception_type(requests.RequestException),
        wait=wait_exponential(multiplier=1, min=2, max=20),
        stop=stop_after_attempt(3),
        reraise=False,
    )(_nominatim_call)


def _nominatim_geocode(query, user_agent, timeout=10):
    # type: (str, str, int) -> Optional[Dict]
    try:
        results = _nominatim_call(query, user_agent, timeout=timeout)
    except Exception as exc:
        logger.warning("Nominatim error for '%s': %s", query, exc)
        return None
    if not results:
        logger.debug("Nominatim: no result for '%s'", query)
        return None
    hit = results[0]
    logger.debug("Nominatim: '%s' -> %s", query, hit.get("display_name", "")[:60])
    return {
        "lat":         float(hit["lat"]),
        "lon":         float(hit["lon"]),
        "osm_display": hit.get("display_name"),
        "osm_type":    hit.get("type") or hit.get("osm_type"),
        "source":      "nominatim",
    }


# ---------------------------------------------------------------------------
# Candidate extraction
# ---------------------------------------------------------------------------

def _regex_candidates(text):
    # type: (str) -> List[str]
    seen = set()
    result = []
    for m in _PLACE_RE.findall(text):
        m = m.strip()
        if m and m not in _SKIP_TOKENS and m not in seen and len(m) > 2:
            seen.add(m)
            result.append(m)
    return result


def _slug_to_text(url):
    # type: (str) -> str
    try:
        path = url.split("://", 1)[-1].split("/", 1)[-1]
        return path.replace("/", " ").replace("-", " ").replace("_", " ")
    except Exception:
        return ""


def _build_query(mention, region):
    # type: (str, Optional[str]) -> str
    if not region:
        return mention
    if region.lower() in mention.lower():
        return mention
    return "{}, {}".format(mention, region)


def _extract_candidates(title, snippet, slug, outlet_region):
    # type: (str, str, str, Optional[str]) -> List[Tuple[str, str]]
    """
    Extract (mention, query) pairs.
    spaCy runs on title+snippet+slug.
    Regex runs on title+snippet only (slug is lowercase, produces garbage).
    outlet_region is appended to query only if not already present in mention.
    """
    ner_text = " ".join(filter(None, [title, snippet, slug]))[:SPACY_MAX_CHARS]
    re_text  = " ".join(filter(None, [title, snippet]))[:SPACY_MAX_CHARS]

    candidates = []
    seen = set()

    def add(mention, query):
        key = query.lower().strip()
        if key and len(key) > 2 and key not in seen:
            seen.add(key)
            candidates.append((mention, query))

    if _SPACY_AVAILABLE and _nlp:
        doc = _nlp(ner_text)
        for ent in doc.ents:
            if ent.label_ in ("GPE", "LOC", "FAC"):
                mention = ent.text.strip()
                if len(mention) < 3:
                    continue
                add(mention, _build_query(mention, outlet_region))
        if not candidates:
            logger.debug("spaCy found no entities — falling back to regex")
            for m in _regex_candidates(re_text):
                add(m, _build_query(m, outlet_region))
    else:
        for m in _regex_candidates(re_text):
            add(m, _build_query(m, outlet_region))

    return candidates


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def geocode_articles(articles, user_agent, rate_limit_sec=1.0, timeout_sec=10.0):
    # type: (List[dict], str, float, float) -> List[dict]
    """
    Geocode each article.
    Stage 1: static lookup (states, cities, rivers, parks) — no API call.
    Stage 2: Nominatim — only for candidates that miss Stage 1.
    All articles returned; unresolved ones get null coords.
    """
    if not articles:
        return []

    wire = articles[0].get("wire", "unknown")
    _validate_user_agent(user_agent)
    logger.info("[%s] geocoding %d articles", wire, len(articles))

    static_hits = 0
    nominatim_hits = 0
    misses = 0
    results = []

    for a in articles:
        title         = a.get("title", "")
        snippet       = a.get("snippet", "")
        slug          = _slug_to_text(a.get("url", ""))
        outlet_region = a.get("outlet_region") or None

        candidates = _extract_candidates(title, snippet, slug, outlet_region)

        # If no candidates at all, try outlet_region directly
        if not candidates and outlet_region:
            candidates = [(outlet_region, outlet_region)]

        matched = False
        for mention, query in candidates:
            # Stage 1: static table
            geo = _static_lookup(query)
            if geo is None:
                geo = _static_lookup(mention)

            if geo:
                logger.debug("[%s] static hit: '%s' -> %.4f, %.4f",
                             wire, mention, geo["lat"], geo["lon"])
                static_hits += 1
            else:
                # Stage 2: Nominatim
                geo = _nominatim_geocode(query, user_agent, timeout=int(timeout_sec))
                time.sleep(rate_limit_sec)
                if geo is None and query != mention:
                    geo = _nominatim_geocode(mention, user_agent, timeout=int(timeout_sec))
                    time.sleep(rate_limit_sec)
                if geo:
                    nominatim_hits += 1

            if geo and geo.get("lat") is not None:
                row = dict(a)
                row["mention_text"] = mention
                row["lat"]          = geo["lat"]
                row["lon"]          = geo["lon"]
                row["osm_display"]  = geo.get("osm_display", "")
                row["osm_type"]     = geo.get("osm_type", "")
                row["geocoded"]     = True
                results.append(row)
                matched = True
                break

        if not matched:
            logger.warning("[%s] no geocode for: %s | candidates: %s",
                           wire, title[:80],
                           [q for _, q in candidates[:3]])
            misses += 1
            row = dict(a)
            row["mention_text"] = None
            row["lat"]          = None
            row["lon"]          = None
            row["osm_display"]  = None
            row["osm_type"]     = None
            row["geocoded"]     = False
            results.append(row)

    logger.info(
        "[%s] geocoding done: %d static + %d nominatim = %d geocoded, %d misses",
        wire, static_hits, nominatim_hits,
        static_hits + nominatim_hits, misses,
    )
    return results
