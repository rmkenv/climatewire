"""
core/extract.py — shared SerpAPI Google News fetch + regex pre-filter.
Each wire passes its own queries and exclusion patterns.
"""

import re
import time
import logging
import requests
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _fetch_serpapi(query: str, api_key: str, lookback_days: int = 1) -> list[dict]:
    """Hit SerpAPI Google News endpoint and return raw article dicts."""
    params = {
        "engine": "google_news",
        "q": query,
        "api_key": api_key,
        "num": 100,
        "tbs": f"qdr:d{lookback_days}",
    }
    try:
        r = requests.get("https://serpapi.com/search", params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        return data.get("news_results", [])
    except Exception as e:
        logger.error(f"SerpAPI error for query '{query}': {e}")
        return []


def _deduplicate(articles: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for a in articles:
        uid = a.get("link", "") or a.get("title", "")
        if uid and uid not in seen:
            seen.add(uid)
            out.append(a)
    return out


def _apply_exclusions(articles: list[dict], exclusion_patterns: list[str]) -> list[dict]:
    """Drop articles whose title or snippet matches any exclusion regex."""
    compiled = [re.compile(p, re.IGNORECASE) for p in exclusion_patterns]
    out = []
    for a in articles:
        text = f"{a.get('title', '')} {a.get('snippet', '')}"
        if not any(p.search(text) for p in compiled):
            out.append(a)
    return out


def _normalise(raw: list[dict], wire: str) -> list[dict]:
    """Flatten SerpAPI article dict into our standard shape."""
    now = datetime.now(timezone.utc).isoformat()
    results = []
    for a in raw:
        source = a.get("source", {})
        results.append({
            "article_id": a.get("link", ""),
            "title": a.get("title", ""),
            "snippet": a.get("snippet", ""),
            "url": a.get("link", ""),
            "source": source.get("name", "") if isinstance(source, dict) else str(source),
            "published_at": a.get("date", ""),
            "wire": wire,
            "fetched_at": now,
        })
    return results


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def fetch_articles(
    queries: list[str],
    api_key: str,
    wire: str,
    lookback_days: int = 1,
    exclusion_patterns: list[str] | None = None,
    rate_limit_sec: float = 1.0,
) -> list[dict]:
    """
    Fetch news articles for a wire.

    Parameters
    ----------
    queries : list of SerpAPI query strings
    api_key : SerpAPI key
    wire    : wire name used to tag output rows
    lookback_days : how many days back to search
    exclusion_patterns : list of regex strings to drop irrelevant articles
    rate_limit_sec : pause between SerpAPI calls
    """
    exclusion_patterns = exclusion_patterns or []
    raw = []
    for q in queries:
        logger.info(f"[{wire}] fetching: {q}")
        raw.extend(_fetch_serpapi(q, api_key, lookback_days))
        time.sleep(rate_limit_sec)

    raw = _deduplicate(raw)
    raw = _apply_exclusions(raw, exclusion_patterns)
    articles = _normalise(raw, wire)
    logger.info(f"[{wire}] {len(articles)} articles after dedup + exclusions")
    return articles
