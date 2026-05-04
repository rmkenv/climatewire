"""
core/geocode.py — spaCy NER + OSM Nominatim geocoder.

Compatible with Python 3.9+ (no X | Y union type hints).

PATCH NOTES
-----------
v2:
- Text fed to location extractor now includes title + snippet + URL slug,
  since local news snippets are often empty but URLs contain place names.
- spaCy NER is now followed by regex as a second-pass fallback when NER
  returns zero candidates (e.g. short titles with no clear GPE).
- Articles that cannot be geocoded are kept with null coords (not dropped).
- USER_AGENT validation warns loudly if blank.
- Geocode hit/miss summary logged at INFO level.
"""

import re
import time
import logging
import requests
from typing import List, Optional

logger = logging.getLogger(__name__)

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

_PLACE_RE = re.compile(r"\b([A-Z][a-z]+(?: [A-Z][a-z]+)*(?:,\s*[A-Z]{2})?)\b")

_SKIP_TOKENS = {
    "I", "A", "The", "In", "At", "On", "To", "Of", "And", "Or", "For",
    "By", "As", "An", "Is", "It", "Be", "We", "He", "She", "They",
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
}

SPACY_MAX_CHARS = 100_000

# US state names and abbreviations for slug parsing
_US_STATES = {
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
    "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
    "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana",
    "maine", "maryland", "massachusetts", "michigan", "minnesota",
    "mississippi", "missouri", "montana", "nebraska", "nevada",
    "new-hampshire", "new-jersey", "new-mexico", "new-york",
    "north-carolina", "north-dakota", "ohio", "oklahoma", "oregon",
    "pennsylvania", "rhode-island", "south-carolina", "south-dakota",
    "tennessee", "texas", "utah", "vermont", "virginia", "washington",
    "west-virginia", "wisconsin", "wyoming",
}


def _slug_to_text(url):
    # type: (str) -> str
    """Extract human-readable words from a URL path slug."""
    try:
        path = url.split("://", 1)[-1].split("/", 1)[-1]  # strip scheme+domain
        slug = path.replace("/", " ").replace("-", " ").replace("_", " ")
        return slug
    except Exception:
        return ""


def _validate_user_agent(user_agent):
    # type: (str) -> None
    if not user_agent or user_agent.strip() in ("", "climatewire/1.0", "yourname@example.com"):
        logger.warning(
            "USER_AGENT is blank or placeholder ('%s'). "
            "OSM Nominatim requires a meaningful User-Agent. "
            "Set the USER_AGENT GitHub Actions secret.",
            user_agent,
        )


def _regex_candidates(text):
    # type: (str) -> List[str]
    raw = _PLACE_RE.findall(text)
    seen = set()
    result = []
    for m in raw:
        m = m.strip()
        if m and m not in _SKIP_TOKENS and m not in seen:
            seen.add(m)
            result.append(m)
    return result


def _extract_locations(text):
    # type: (str) -> List[str]
    """Extract candidate place names. spaCy first, regex as fallback/supplement."""
    text = text[:SPACY_MAX_CHARS]
    candidates = []

    if _SPACY_AVAILABLE and _nlp:
        doc = _nlp(text)
        spacy_locs = [ent.text.strip() for ent in doc.ents if ent.label_ in ("GPE", "LOC")]
        # Dedup
        seen = set()
        for loc in spacy_locs:
            if loc and loc not in seen:
                seen.add(loc)
                candidates.append(loc)

        # If spaCy found nothing, fall back to regex
        if not candidates:
            logger.debug("spaCy found no GPE/LOC — trying regex fallback")
            candidates = _regex_candidates(text)
    else:
        candidates = _regex_candidates(text)

    return candidates


def _nominatim_geocode(place, user_agent, country_codes="us", timeout=10.0):
    # type: (str, str, str, float) -> Optional[dict]
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
            logger.debug("Nominatim: '%s' -> %s", place, results[0].get("display_name", "")[:60])
            return results[0]
        logger.debug("Nominatim: no result for '%s'", place)
    except requests.exceptions.Timeout:
        logger.debug("Nominatim timeout for '%s'", place)
    except Exception as e:
        logger.debug("Nominatim error for '%s': %s", place, e)
    return None


def geocode_articles(articles, user_agent, rate_limit_sec=1.0, timeout_sec=10.0):
    # type: (List[dict], str, float, float) -> List[dict]
    """
    Geocode each article. Returns ALL articles.
    Successfully geocoded ones get lat/lon/osm_* populated.
    Ungeocodeable ones get null coords — they still land in the CSV.

    Text sources used (in order of extraction):
      1. title
      2. snippet
      3. URL slug (catches local news URLs that embed place names)
    """
    if not articles:
        return []

    wire = articles[0].get("wire", "unknown")
    _validate_user_agent(user_agent)

    geocoded_count = 0
    results = []

    for a in articles:
        # Build richest possible text: title + snippet + URL slug
        title   = a.get("title", "")
        snippet = a.get("snippet", "")
        slug    = _slug_to_text(a.get("url", ""))
        text    = " ".join(filter(None, [title, snippet, slug]))

        candidates = _extract_locations(text)
        logger.debug("[%s] candidates for '%s': %s",
                     wire, title[:50], candidates[:5])

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
                row["geocoded"]     = True
                results.append(row)
                geocoded_count += 1
                matched = True
                break

        if not matched:
            logger.debug("[%s] no geocode for: %s", wire, title[:80])
            row = dict(a)
            row["mention_text"] = None
            row["lat"]          = None
            row["lon"]          = None
            row["osm_display"]  = None
            row["osm_type"]     = None
            row["geocoded"]     = False
            results.append(row)

    logger.info(
        "[%s] geocoding complete: %d/%d geocoded, %d null coords",
        wire, geocoded_count, len(articles), len(articles) - geocoded_count,
    )
    return results
