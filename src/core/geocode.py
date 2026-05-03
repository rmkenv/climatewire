"""
core/geocode.py — spaCy NER + OSM Nominatim geocoder.
Ported from floodwire2/src/geocode_floods.py, generalised for any wire.

Compatible with Python 3.9+ (no X | Y union type hints).
"""

import re
import time
import logging
import requests
from typing import List, Optional

logger = logging.getLogger(__name__)

# Try to load spaCy; fall back to regex-only if not installed
try:
    import spacy
    _nlp = spacy.load("en_core_web_sm")
    _SPACY_AVAILABLE = True
    logger.debug("spaCy loaded OK")
except Exception:
    _nlp = None
    _SPACY_AVAILABLE = False
    logger.warning("spaCy not available — using regex-only location extraction")

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

# Regex fallback: grab capitalised place-like tokens
_PLACE_RE = re.compile(r"\b([A-Z][a-z]+(?: [A-Z][a-z]+)*(?:,\s*[A-Z]{2})?)\b")

# Tokens to skip even if capitalised
_SKIP_TOKENS = {
    "I", "A", "The", "In", "At", "On", "To", "Of", "And", "Or", "For",
    "By", "As", "An", "Is", "It", "Be", "We", "He", "She", "They",
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
}

SPACY_MAX_CHARS = 100_000  # safe cap for spaCy processing


def _extract_locations(text: str) -> List[str]:
    """Extract candidate place names from text via spaCy GPE/LOC or regex."""
    text = text[:SPACY_MAX_CHARS]
    if _SPACY_AVAILABLE and _nlp:
        doc = _nlp(text)
        locs = [ent.text.strip() for ent in doc.ents if ent.label_ in ("GPE", "LOC")]
    else:
        raw_matches = _PLACE_RE.findall(text)
        locs = [m for m in raw_matches if m not in _SKIP_TOKENS]

    # Dedup preserving order, filter empty
    seen = set()
    result = []
    for loc in locs:
        loc = loc.strip()
        if loc and loc not in seen:
            seen.add(loc)
            result.append(loc)
    return result


def _nominatim_geocode(
    place: str,
    user_agent: str,
    country_codes: str = "us",
    timeout: float = 10.0,
) -> Optional[dict]:
    """Query OSM Nominatim and return first result or None."""
    params = {
        "q": place,
        "format": "json",
        "limit": 1,
        "countrycodes": country_codes,
    }
    headers = {"User-Agent": user_agent}
    try:
        r = requests.get(NOMINATIM_URL, params=params, headers=headers, timeout=timeout)
        r.raise_for_status()
        results = r.json()
        if results:
            logger.debug("Nominatim: '%s' → %s", place, results[0].get("display_name", "")[:60])
            return results[0]
        logger.debug("Nominatim: no result for '%s'", place)
    except requests.exceptions.Timeout:
        logger.debug("Nominatim timeout for '%s'", place)
    except Exception as e:
        logger.debug("Nominatim error for '%s': %s", place, e)
    return None


def geocode_articles(
    articles: List[dict],
    user_agent: str,
    rate_limit_sec: float = 1.0,
    timeout_sec: float = 10.0,
) -> List[dict]:
    """
    Geocode each article. Returns one row per article that could be geocoded.
    Articles with no geocodeable location are dropped.
    Only the first successfully geocoded location per article is kept.
    """
    if not articles:
        return []

    wire = articles[0].get("wire", "unknown")
    geocoded = []

    for a in articles:
        text = "{} {}".format(a.get("title", ""), a.get("snippet", ""))
        candidates = _extract_locations(text)
        logger.debug("[%s] candidates for '%s': %s",
                     wire, a.get("title", "")[:50], candidates[:5])

        matched = False
        for place in candidates:
            result = _nominatim_geocode(place, user_agent, timeout=timeout_sec)
            time.sleep(rate_limit_sec)
            if result:
                try:
                    lat = float(result["lat"])
                    lon = float(result["lon"])
                except (KeyError, ValueError, TypeError) as e:
                    logger.debug("Bad lat/lon from Nominatim for '%s': %s", place, e)
                    continue

                row = dict(a)
                row["mention_text"] = place
                row["lat"]          = lat
                row["lon"]          = lon
                row["osm_display"]  = result.get("display_name", "")
                row["osm_type"]     = result.get("type", "")
                geocoded.append(row)
                matched = True
                break  # keep only first match per article

        if not matched:
            logger.debug("[%s] no geocode for: %s", wire, a.get("title", "")[:80])

    logger.info("[%s] geocoded %d / %d articles", wire, len(geocoded), len(articles))
    return geocoded
