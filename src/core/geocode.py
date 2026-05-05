"""
core/geocode.py — spaCy NER + OSM Nominatim geocoder.
Compatible with Python 3.9+.

Modeled on floodwire/src/geocode_floods.py.

Key differences from original climatewire geocode.py:
- Uses jsonv2 + addressdetails=1 on Nominatim (richer results)
- tenacity retry with exponential backoff on all Nominatim calls
- outlet_region context appended to NER candidates (improves hit rate)
- Outlet city/region as explicit fallback when NER + regex find nothing
- spaCy + regex dual pass
- URL slug as supplemental text source
- All articles returned; ungeocodeable get null coords (not dropped)
- Verbose HTTP error logging so CI surfaces the real failure cause
"""

import re
import time
import logging
import requests
from typing import List, Optional, Tuple

try:
    from tenacity import (
        retry,
        stop_after_attempt,
        wait_exponential,
        retry_if_exception_type,
    )
    _TENACITY = True
except ImportError:
    _TENACITY = False

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

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

_PLACE_RE = re.compile(r"\b([A-Z][a-z]+(?: [A-Z][a-z]+)*(?:,\s*[A-Z]{2})?)\b")

_SKIP_TOKENS = {
    "I", "A", "The", "In", "At", "On", "To", "Of", "And", "Or", "For",
    "By", "As", "An", "Is", "It", "Be", "We", "He", "She", "They",
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
    "United", "States", "Americans", "American",
}

SPACY_MAX_CHARS = 5000  # match floodwire cap


def _validate_user_agent(user_agent):
    # type: (str) -> None
    blank = not user_agent or user_agent.strip() in ("", "climatewire/1.0", "yourname@example.com")
    if blank:
        logger.warning(
            "USER_AGENT is '%s' — Nominatim will likely return 403. "
            "Set the USER_AGENT secret to e.g. 'climatewire/1.0 (you@email.com)'.",
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


def _extract_locations(text, outlet_region=None, text_for_regex=None):
    # type: (str, Optional[str], Optional[str]) -> List[Tuple[str, str]]
    """
    Returns list of (mention_text, osm_query_string).
    osm_query appends outlet_region for better Nominatim hit rate,
    matching floodwire's approach.
    text_for_regex is used for the regex pass (title+snippet only, no slug).
    """
    text = text[:SPACY_MAX_CHARS]
    re_text = (text_for_regex or text)[:SPACY_MAX_CHARS]
    candidates = []
    seen_queries = set()

    def _build_query(mention, region):
        # type: (str, Optional[str]) -> str
        # Don't append region if the mention already contains it
        if not region:
            return mention
        if region.lower() in mention.lower():
            return mention
        return "{}, {}".format(mention, region)

    def add(mention, query):
        key = query.lower().strip()
        if key and key not in seen_queries and len(key) > 2:
            seen_queries.add(key)
            candidates.append((mention, query))

    if _SPACY_AVAILABLE and _nlp:
        doc = _nlp(text)
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


def _nominatim_search(query, user_agent, timeout=10):
    # type: (str, str, int) -> list
    params = {
        "q": query,
        "format": "jsonv2",
        "limit": 1,
        "countrycodes": "us",
        "addressdetails": 1,
    }
    headers = {"User-Agent": user_agent}
    resp = requests.get(NOMINATIM_URL, params=params, headers=headers, timeout=timeout)
    if not resp.ok:
        logger.warning("Nominatim HTTP %d for '%s': %s", resp.status_code, query, resp.text[:200])
        resp.raise_for_status()
    return resp.json()


if _TENACITY:
    _nominatim_search = retry(
        retry=retry_if_exception_type(requests.RequestException),
        wait=wait_exponential(multiplier=1, min=2, max=20),
        stop=stop_after_attempt(3),
        reraise=False,
    )(_nominatim_search)


def _geocode_query(query, user_agent, timeout=10):
    # type: (str, str, int) -> dict
    """Geocode a single query string. Returns dict with lat/lon or all-None."""
    try:
        results = _nominatim_search(query, user_agent, timeout=timeout)
    except Exception as exc:
        logger.debug("Nominatim error for '%s': %s", query, exc)
        return {"lat": None, "lon": None, "osm_display": None, "osm_type": None}

    if not results:
        logger.debug("Nominatim: no result for '%s'", query)
        return {"lat": None, "lon": None, "osm_display": None, "osm_type": None}

    hit = results[0]
    logger.debug("Nominatim: '%s' -> %s", query, hit.get("display_name", "")[:60])
    return {
        "lat":         float(hit["lat"]),
        "lon":         float(hit["lon"]),
        "osm_display": hit.get("display_name"),
        "osm_type":    hit.get("type") or hit.get("osm_type"),
    }


def geocode_articles(articles, user_agent, rate_limit_sec=1.0, timeout_sec=10.0):
    # type: (List[dict], str, float, float) -> List[dict]
    """
    Geocode each article. Returns ALL articles — geocoded ones get lat/lon,
    ungeocodeable ones get null coords.

    Text sources (richest possible input to NER):
      title + snippet + url slug

    Fallback chain per article:
      1. spaCy GPE/LOC/FAC entities (with outlet_region appended to query)
      2. Regex capitalised tokens (with outlet_region appended)
      3. outlet_region alone (state-level fallback, confidence=low)
    """
    if not articles:
        return []

    wire = articles[0].get("wire", "unknown")
    _validate_user_agent(user_agent)
    logger.info("[%s] geocoding %d articles", wire, len(articles))

    geocoded_count = 0
    results = []

    for a in articles:
        title   = a.get("title", "")
        snippet = a.get("snippet", "")
        slug    = _slug_to_text(a.get("url", ""))
        # Full text for spaCy (slug adds context); title+snippet only for regex
        # (slug is lowercase and produces garbage regex candidates)
        text         = " ".join(filter(None, [title, snippet, slug]))
        text_for_ner = text  # spaCy handles lowercase fine
        text_for_re  = " ".join(filter(None, [title, snippet]))  # regex needs capitalised

        outlet_region = a.get("outlet_region") or None

        candidates = _extract_locations(text_for_ner, outlet_region=outlet_region,
                                          text_for_regex=text_for_re)

        # Fallback: if nothing extracted, try a bare state/region name from title
        if not candidates and outlet_region:
            candidates = [(outlet_region, outlet_region)]

        logger.debug("[%s] '%s' -> candidates: %s",
                     wire, title[:50], [q for _, q in candidates[:5]])

        matched = False
        for mention, query in candidates:
            geo = _geocode_query(query, user_agent, timeout=int(timeout_sec))
            time.sleep(rate_limit_sec)

            # If compound query failed, retry with bare mention
            if geo["lat"] is None and query != mention:
                logger.debug("Retrying bare mention: '%s'", mention)
                geo = _geocode_query(mention, user_agent, timeout=int(timeout_sec))
                time.sleep(rate_limit_sec)

            if geo["lat"] is not None:
                row = dict(a)
                row["mention_text"] = mention
                row["lat"]          = geo["lat"]
                row["lon"]          = geo["lon"]
                row["osm_display"]  = geo["osm_display"]
                row["osm_type"]     = geo["osm_type"]
                row["geocoded"]     = True
                results.append(row)
                geocoded_count += 1
                matched = True
                break

        if not matched:
            logger.warning("[%s] no geocode for: %s | candidates: %s",
                           wire, title[:80], [q for _, q in candidates[:3]])
            row = dict(a)
            row["mention_text"] = None
            row["lat"]          = None
            row["lon"]          = None
            row["osm_display"]  = None
            row["osm_type"]     = None
            row["geocoded"]     = False
            results.append(row)

    logger.info("[%s] geocoding done: %d/%d geocoded, %d null coords",
                wire, geocoded_count, len(articles), len(articles) - geocoded_count)
    return results
