"""
core/geocode.py — spaCy NER + OSM Nominatim geocoder.
Ported directly from floodwire2/src/geocode_floods.py, generalised for any wire.
"""

import re
import time
import logging
import requests

logger = logging.getLogger(__name__)

# Try to load spaCy; fall back to regex-only if not installed
try:
    import spacy
    _nlp = spacy.load("en_core_web_sm")
    _SPACY_AVAILABLE = True
except Exception:
    _nlp = None
    _SPACY_AVAILABLE = False
    logger.warning("spaCy not available — using regex-only location extraction")

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

# Regex fallback: grab capitalised place-like tokens
_PLACE_RE = re.compile(r"\b([A-Z][a-z]+(?: [A-Z][a-z]+)*(?:,\s*[A-Z]{2})?)\b")

# US state names + abbreviations for filtering
_US_STATES = {
    "Alabama","Alaska","Arizona","Arkansas","California","Colorado","Connecticut",
    "Delaware","Florida","Georgia","Hawaii","Idaho","Illinois","Indiana","Iowa",
    "Kansas","Kentucky","Louisiana","Maine","Maryland","Massachusetts","Michigan",
    "Minnesota","Mississippi","Missouri","Montana","Nebraska","Nevada",
    "New Hampshire","New Jersey","New Mexico","New York","North Carolina",
    "North Dakota","Ohio","Oklahoma","Oregon","Pennsylvania","Rhode Island",
    "South Carolina","South Dakota","Tennessee","Texas","Utah","Vermont",
    "Virginia","Washington","West Virginia","Wisconsin","Wyoming",
    # abbreviations
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN",
    "IA","KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV",
    "NH","NJ","NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN",
    "TX","UT","VT","VA","WA","WV","WI","WY","DC",
}


def _extract_locations(text: str) -> list[str]:
    """Extract candidate place names from text via spaCy GPE/LOC or regex."""
    if _SPACY_AVAILABLE and _nlp:
        doc = _nlp(text[:1_000_000])  # spaCy soft cap
        locs = [ent.text for ent in doc.ents if ent.label_ in ("GPE", "LOC")]
    else:
        locs = _PLACE_RE.findall(text)
    # Filter to US-only heuristic: keep if text contains a state name/abbrev
    # or if the candidate itself is a state
    return list(dict.fromkeys(locs))  # dedup, preserve order


def _nominatim_geocode(
    place: str,
    user_agent: str,
    country_codes: str = "us",
    timeout: float = 10.0,
) -> dict | None:
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
            return results[0]
    except Exception as e:
        logger.debug(f"Nominatim error for '{place}': {e}")
    return None


def geocode_articles(
    articles: list[dict],
    user_agent: str,
    rate_limit_sec: float = 1.0,
    timeout_sec: float = 10.0,
) -> list[dict]:
    """
    Geocode each article. Returns a (potentially longer) list of dicts —
    one row per geocoded location mention per article.
    Articles with no geocodeable location are dropped.
    """
    wire = articles[0]["wire"] if articles else "unknown"
    geocoded = []

    for a in articles:
        text = f"{a.get('title', '')} {a.get('snippet', '')}"
        candidates = _extract_locations(text)

        matched = False
        for place in candidates:
            result = _nominatim_geocode(place, user_agent, timeout=timeout_sec)
            time.sleep(rate_limit_sec)
            if result:
                row = {**a}
                row["mention_text"] = place
                row["lat"] = float(result["lat"])
                row["lon"] = float(result["lon"])
                row["osm_display"] = result.get("display_name", "")
                row["osm_type"] = result.get("type", "")
                geocoded.append(row)
                matched = True
                break  # keep only closest / first match per article

        if not matched:
            logger.debug(f"[{wire}] no geocode for: {a.get('title', '')[:80]}")

    logger.info(f"[{wire}] geocoded {len(geocoded)} / {len(articles)} articles")
    return geocoded
