"""
core/geocode.py — spaCy NER + OSM Nominatim geocoder.
Compatible with Python 3.9+.

v3 changes:
- Logs the actual HTTP status and response body on Nominatim failures
  so the cause (blank User-Agent, 403, rate limit) is visible in CI logs.
- Falls back to a broader search (no countrycodes filter) if US-scoped
  search returns zero results, catching articles about US events filed
  by international outlets with non-US Nominatim results.
- spaCy + regex dual pass retained from v2.
- URL slug extraction retained from v2.
- Ungeocodeable articles kept with null coords (not dropped).
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
except Exception as e:
    _nlp = None
    _SPACY_AVAILABLE = False
    logger.warning("spaCy unavailable (%s) — using regex-only location extraction", e)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

_PLACE_RE = re.compile(r"\b([A-Z][a-z]+(?: [A-Z][a-z]+)*(?:,\s*[A-Z]{2})?)\b")

_SKIP_TOKENS = {
    "I", "A", "The", "In", "At", "On", "To", "Of", "And", "Or", "For",
    "By", "As", "An", "Is", "It", "Be", "We", "He", "She", "They",
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
    "United", "States",  # too broad alone; caught as "United States" by spaCy
}

SPACY_MAX_CHARS = 100_000


def _validate_user_agent(user_agent):
    # type: (str) -> None
    if not user_agent or user_agent.strip() in ("", "climatewire/1.0", "yourname@example.com"):
        logger.warning(
            "USER_AGENT is '%s' — OSM Nominatim will likely return 403 or empty results. "
            "Set the USER_AGENT secret to something like 'climatewire/1.0 (you@email.com)'.",
            user_agent,
        )


def _slug_to_text(url):
    # type: (str) -> str
    try:
        path = url.split("://", 1)[-1].split("/", 1)[-1]
        return path.replace("/", " ").replace("-", " ").replace("_", " ")
    except Exception:
        return ""


def _regex_candidates(text):
    # type: (str) -> List[str]
    seen = set()
    result = []
    for m in _PLACE_RE.findall(text):
        m = m.strip()
        if m and m not in _SKIP_TOKENS and m not in seen:
            seen.add(m)
            result.append(m)
    return result


def _extract_locations(text):
    # type: (str) -> List[str]
    text = text[:SPACY_MAX_CHARS]
    candidates = []

    if _SPACY_AVAILABLE and _nlp:
        doc = _nlp(text)
        seen = set()
        for ent in doc.ents:
            if ent.label_ in ("GPE", "LOC"):
                loc = ent.text.strip()
                if loc and loc not in seen:
                    seen.add(loc)
                    candidates.append(loc)
        if not candidates:
            logger.debug("spaCy found no GPE/LOC entities — falling back to regex")
            candidates = _regex_candidates(text)
    else:
        candidates = _regex_candidates(text)

    return candidates


def _nominatim_geocode(place, user_agent, country_codes="us", timeout=10.0):
    # type: (str, str, str, float) -> Optional[dict]
    """
    Query Nominatim. Tries US-scoped first; falls back to global if no result.
    Logs HTTP errors verbosely so failures are visible in CI.
    """
    for scope, cc in [("US-scoped", country_codes), ("global fallback", "")]:
        params = {"q": place, "format": "json", "limit": 1}
        if cc:
            params["countrycodes"] = cc
        headers = {"User-Agent": user_agent}
        try:
            r = requests.get(NOMINATIM_URL, params=params, headers=headers, timeout=timeout)
            if not r.ok:
                logger.warning(
                    "Nominatim HTTP %d for '%s' (%s) — body: %s",
                    r.status_code, place, scope, r.text[:200],
                )
                continue
            results = r.json()
            if results:
                logger.debug("Nominatim %s: '%s' -> %s", scope, place,
                             results[0].get("display_name", "")[:60])
                return results[0]
            logger.debug("Nominatim %s: no result for '%s'", scope, place)
        except requests.exceptions.Timeout:
            logger.warning("Nominatim timeout for '%s' (%s)", place, scope)
        except Exception as e:
            logger.warning("Nominatim error for '%s' (%s): %s", place, scope, e)

        if not cc:
            break  # already tried global, stop
        time.sleep(0.5)  # small pause between US and global attempt

    return None


def geocode_articles(articles, user_agent, rate_limit_sec=1.0, timeout_sec=10.0):
    # type: (List[dict], str, float, float) -> List[dict]
    """
    Geocode each article. ALL articles are returned — geocoded ones get
    lat/lon populated, ungeocodeable ones get null coords.
    """
    if not articles:
        return []

    wire = articles[0].get("wire", "unknown")
    _validate_user_agent(user_agent)
    logger.info("[%s] geocoding %d articles — user_agent='%s'",
                wire, len(articles), user_agent[:40] if user_agent else "")

    geocoded_count = 0
    results = []

    for a in articles:
        title   = a.get("title", "")
        snippet = a.get("snippet", "")
        slug    = _slug_to_text(a.get("url", ""))
        text    = " ".join(filter(None, [title, snippet, slug]))

        candidates = _extract_locations(text)
        logger.debug("[%s] '%s' -> candidates: %s", wire, title[:50], candidates[:5])

        matched = False
        for place in candidates:
            result = _nominatim_geocode(place, user_agent, timeout=timeout_sec)
            time.sleep(rate_limit_sec)
            if result:
                try:
                    lat = float(result["lat"])
                    lon = float(result["lon"])
                except (KeyError, ValueError, TypeError) as e:
                    logger.debug("Bad lat/lon for '%s': %s", place, e)
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
            logger.warning("[%s] no geocode for: %s | candidates were: %s",
                           wire, title[:80], candidates[:5])
            row = dict(a)
            row["mention_text"] = None
            row["lat"]          = None
            row["lon"]          = None
            row["osm_display"]  = None
            row["osm_type"]     = None
            row["geocoded"]     = False
            results.append(row)

    logger.info(
        "[%s] geocoding done: %d/%d geocoded, %d null coords",
        wire, geocoded_count, len(articles), len(articles) - geocoded_count,
    )
    return results
