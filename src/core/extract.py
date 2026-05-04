"""
core/extract.py — shared SerpAPI Google News fetch + regex pre-filter.
Each wire passes its own queries and exclusion patterns.

Compatible with Python 3.9+.

v2 changes:
- _normalise now extracts outlet_region from source domain (like floodwire)
  and falls back to scanning the title/snippet for US state names.
  outlet_region is used by geocode.py to build better Nominatim queries
  e.g. "Union County, North Carolina" instead of just "Union County".
"""

import re
import time
import logging
import requests
from datetime import datetime, timezone
from typing import List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# State lookup tables
# ---------------------------------------------------------------------------

# Source domain keyword → US state name
_SOURCE_STATE_MAP = {
    "baltimoresun":      "Maryland",
    "capitalgazette":    "Maryland",
    "wbaltv":            "Maryland",
    "wmar":              "Maryland",
    "washingtonpost":    "DC",
    "wtop":              "DC",
    "wusa":              "DC",
    "nytimes":           "New York",
    "nypost":            "New York",
    "silive":            "New York",
    "latimes":           "California",
    "sfgate":            "California",
    "sacbee":            "California",
    "mercurynews":       "California",
    "fresnobee":         "California",
    "desertsun":         "California",
    "voiceofsandiego":   "California",
    "denverpost":        "Colorado",
    "coloradosun":       "Colorado",
    "gazette":           "Colorado",
    "kiowacountypress":  "Colorado",
    "chron":             "Texas",
    "dallasnews":        "Texas",
    "statesman":         "Texas",
    "star-telegram":     "Texas",
    "expressnews":       "Texas",
    "miamiherald":       "Florida",
    "sun-sentinel":      "Florida",
    "tampabay":          "Florida",
    "orlandosentinel":   "Florida",
    "firstcoastnews":    "Florida",
    "ajc":               "Georgia",
    "charlotteobserver": "North Carolina",
    "newsobserver":      "North Carolina",
    "philly":            "Pennsylvania",
    "inquirer":          "Pennsylvania",
    "bostonglobe":       "Massachusetts",
    "masslive":          "Massachusetts",
    "chicagotribune":    "Illinois",
    "suntimes":          "Illinois",
    "seattletimes":      "Washington",
    "oregonlive":        "Oregon",
    "kgw":               "Oregon",
    "azcentral":         "Arizona",
    "tucson":            "Arizona",
    "ktar":              "Arizona",
    "reviewjournal":     "Nevada",
    "klas":              "Nevada",
    "tennessean":        "Tennessee",
    "commercialappeal":  "Tennessee",
    "clarionledger":     "Mississippi",
    "nola":              "Louisiana",
    "theadvocate":       "Louisiana",
    "arkansasonline":    "Arkansas",
    "oklahoman":         "Oklahoma",
    "tulsaworld":        "Oklahoma",
    "kansascity":        "Missouri",
    "stltoday":          "Missouri",
    "omaha":             "Nebraska",
    "desmoinesregister": "Iowa",
    "startribune":       "Minnesota",
    "duluthnewstribune": "Minnesota",
    "jsonline":          "Wisconsin",
    "freep":             "Michigan",
    "mlive":             "Michigan",
    "cleveland":         "Ohio",
    "dispatch":          "Ohio",
    "cincinnati":        "Ohio",
    "indystar":          "Indiana",
    "courier-journal":   "Kentucky",
    "wvgazettemail":     "West Virginia",
    "postandcourier":    "South Carolina",
    "islandpacket":      "South Carolina",
    "idahostatesman":    "Idaho",
    "mtstandard":        "Montana",
    "trib":              "Wyoming",
    "sltrib":            "Utah",
    "deseret":           "Utah",
    "newmexican":        "New Mexico",
    "abqjournal":        "New Mexico",
    "alaskajournal":     "Alaska",
    "staradvertiser":    "Hawaii",
}

# US state names and common abbreviations for title scanning
_STATE_NAMES = [
    "Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado",
    "Connecticut", "Delaware", "Florida", "Georgia", "Hawaii", "Idaho",
    "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky", "Louisiana",
    "Maine", "Maryland", "Massachusetts", "Michigan", "Minnesota",
    "Mississippi", "Missouri", "Montana", "Nebraska", "Nevada",
    "New Hampshire", "New Jersey", "New Mexico", "New York",
    "North Carolina", "North Dakota", "Ohio", "Oklahoma", "Oregon",
    "Pennsylvania", "Rhode Island", "South Carolina", "South Dakota",
    "Tennessee", "Texas", "Utah", "Vermont", "Virginia", "Washington",
    "West Virginia", "Wisconsin", "Wyoming",
]

# Compiled regex: matches any US state name in text
_STATE_RE = re.compile(
    r"\b(" + "|".join(re.escape(s) for s in _STATE_NAMES) + r")\b"
)


def _infer_outlet_region(source_name):
    # type: (str) -> Optional[str]
    """Map source domain name to US state. Returns None if unknown."""
    src = source_name.lower()
    for key, state in _SOURCE_STATE_MAP.items():
        if key in src:
            return state
    return None


def _extract_state_from_text(text):
    # type: (str) -> Optional[str]
    """Scan title/snippet for the first US state name mentioned."""
    m = _STATE_RE.search(text)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# SerpAPI helpers
# ---------------------------------------------------------------------------

def _fetch_serpapi(query, api_key, lookback_days=1):
    # type: (str, str, int) -> List[dict]
    params = {
        "engine":  "google_news",
        "q":       query,
        "api_key": api_key,
        "num":     100,
        "tbs":     "qdr:d{}".format(lookback_days),
    }
    try:
        r = requests.get("https://serpapi.com/search", params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        results = data.get("news_results", [])
        logger.debug("SerpAPI returned %d results for: %s", len(results), query[:80])
        return results
    except requests.exceptions.HTTPError as e:
        logger.error("SerpAPI HTTP error %s for '%s': %s",
                     e.response.status_code if e.response else "?", query, e)
        return []
    except requests.exceptions.Timeout:
        logger.error("SerpAPI timeout for query '%s'", query)
        return []
    except Exception as e:
        logger.error("SerpAPI unexpected error for '%s': %s", query, e)
        return []


def _deduplicate(articles):
    # type: (List[dict]) -> List[dict]
    seen = set()
    out = []
    for a in articles:
        uid = a.get("link", "") or a.get("title", "")
        if uid and uid not in seen:
            seen.add(uid)
            out.append(a)
    return out


def _apply_exclusions(articles, exclusion_patterns):
    # type: (List[dict], List[str]) -> List[dict]
    if not exclusion_patterns:
        return articles
    compiled = [re.compile(p, re.IGNORECASE) for p in exclusion_patterns]
    out = []
    dropped = 0
    for a in articles:
        text = "{} {}".format(a.get("title", ""), a.get("snippet", ""))
        if any(p.search(text) for p in compiled):
            logger.debug("Exclusion dropped: %s", a.get("title", "")[:80])
            dropped += 1
        else:
            out.append(a)
    if dropped:
        logger.debug("Exclusion filter dropped %d articles", dropped)
    return out


def _normalise(raw, wire):
    # type: (List[dict], str) -> List[dict]
    """
    Flatten SerpAPI article dict into our standard shape.

    outlet_region is derived from:
      1. Source domain map (e.g. kiowacountypress → Colorado)
      2. First US state name found in title + snippet
    This is used by geocode.py to build better Nominatim queries.
    """
    now = datetime.now(timezone.utc).isoformat()
    results = []
    for a in raw:
        source = a.get("source", {})
        source_name = source.get("name", "") if isinstance(source, dict) else str(source)

        title   = a.get("title", "")
        snippet = a.get("snippet", "")
        text    = "{} {}".format(title, snippet)

        # Try domain map first, then scan text for state name
        outlet_region = _infer_outlet_region(source_name)
        if not outlet_region:
            outlet_region = _extract_state_from_text(text)

        if outlet_region:
            logger.debug("[%s] outlet_region='%s' for: %s", wire, outlet_region, title[:60])

        results.append({
            "article_id":    a.get("link", ""),
            "title":         title,
            "snippet":       snippet,
            "url":           a.get("link", ""),
            "source":        source_name,
            "published_at":  a.get("date", ""),
            "wire":          wire,
            "fetched_at":    now,
            "outlet_region": outlet_region,  # NEW — used by geocoder
        })
    return results


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def fetch_articles(
    queries,
    api_key,
    wire,
    lookback_days=1,
    exclusion_patterns=None,
    rate_limit_sec=1.0,
):
    # type: (List[str], str, str, int, Optional[List[str]], float) -> List[dict]
    exclusion_patterns = exclusion_patterns or []
    raw = []
    for q in queries:
        logger.info("[%s] fetching: %s", wire, q[:100])
        results = _fetch_serpapi(q, api_key, lookback_days)
        raw.extend(results)
        if len(queries) > 1:
            time.sleep(rate_limit_sec)

    before_dedup = len(raw)
    raw = _deduplicate(raw)
    logger.debug("[%s] dedup: %d → %d", wire, before_dedup, len(raw))

    raw = _apply_exclusions(raw, exclusion_patterns)
    articles = _normalise(raw, wire)
    logger.info("[%s] %d articles after fetch + dedup + exclusions", wire, len(articles))
    return articles
