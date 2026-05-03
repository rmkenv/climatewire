"""
core/screen.py — shared Ollama Cloud LLM relevance screener.
Each wire passes its own system prompt / criteria.
"""

import time
import logging
import requests

logger = logging.getLogger(__name__)

OLLAMA_API_URL = "https://api.ollama.com/api/chat"
DEFAULT_MODEL = "gpt-oss:120b"


def _call_ollama(
    article: dict,
    system_prompt: str,
    api_key: str,
    model: str = DEFAULT_MODEL,
) -> bool:
    """
    Returns True if the article passes relevance screening.
    Falls back to True (keep) on API errors so we don't silently drop articles.
    """
    user_msg = (
        f"Title: {article.get('title', '')}\n"
        f"Snippet: {article.get('snippet', '')}\n"
        f"URL: {article.get('url', '')}\n\n"
        "Respond with exactly one word: YES or NO."
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
        ],
        "stream": False,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        r = requests.post(OLLAMA_API_URL, json=payload, headers=headers, timeout=30)
        r.raise_for_status()
        answer = r.json()["message"]["content"].strip().upper()
        return answer.startswith("YES")
    except Exception as e:
        logger.warning(f"Ollama error (keeping article): {e}")
        return True  # fail-open


def screen_articles(
    articles: list[dict],
    system_prompt: str,
    api_key: str | None,
    model: str = DEFAULT_MODEL,
    rate_limit_sec: float = 0.5,
) -> list[dict]:
    """
    Filter articles through the LLM. If api_key is None, screening is skipped.

    Parameters
    ----------
    articles      : output of core.extract.fetch_articles
    system_prompt : wire-specific relevance instructions
    api_key       : Ollama Cloud API key (None → skip screening)
    model         : Ollama model string
    rate_limit_sec: pause between Ollama calls
    """
    wire = articles[0]["wire"] if articles else "unknown"

    if not api_key:
        logger.warning(f"[{wire}] OLLAMA_API_KEY not set — skipping LLM screening")
        return articles

    passed = []
    for a in articles:
        keep = _call_ollama(a, system_prompt, api_key, model)
        if keep:
            passed.append(a)
        time.sleep(rate_limit_sec)

    logger.info(f"[{wire}] screened {len(articles)} → {len(passed)} passed")
    return passed
