"""
drought/main.py — Drought Wire orchestrator.
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

from core import extract, screen, geocode, load, utils
from drought.sensor_join import join_sensor

logger = logging.getLogger(__name__)

WIRE = "drought"

QUERIES = [
    '"drought emergency" OR "drought declaration" OR "water shortage" United States',
    '"exceptional drought" OR "extreme drought" OR "D4 drought" OR "D3 drought" site:droughtmonitor.unl.edu OR site:noaa.gov',
    '"drought conditions" OR "driest on record" OR "drought relief" United States 2025 OR 2026',
]

EXCLUSION_PATTERNS = [
    r"\bdrought of talent\b",
    r"\bdrought of ideas\b",
    r"\bscoring drought\b",    # sports
    r"\bwinless drought\b",
    r"\bgoal drought\b",
]

SYSTEM_PROMPT = """You are a relevance screener for a drought news wire.
Answer YES if the article describes a real drought event, drought emergency declaration, water shortage,
reservoir depletion, groundwater decline, or crop loss due to drought in the United States.
Answer NO if it is about sports, figurative uses of 'drought', or events outside the US.
Respond with exactly one word: YES or NO."""

CLASSIFICATION_MAP = {
    "drought_declaration": ["drought declaration", "drought emergency", "drought disaster"],
    "water_shortage":      ["water shortage", "water restriction", "water ban", "water rationing"],
    "reservoir_low":       ["reservoir", "lake level", "water level", "storage capacity"],
    "crop_loss":           ["crop loss", "crop failure", "agricultural drought", "livestock"],
    "exceptional_drought": ["exceptional drought", "D4", "extreme drought", "D3"],
}


def classify(article: dict) -> str:
    text = f"{article.get('title','')} {article.get('snippet','')}".lower()
    for event_type, triggers in CLASSIFICATION_MAP.items():
        if any(t in text for t in triggers):
            return event_type
    return "drought_event"


def run(cfg: dict, test_mode: bool = False, no_screen: bool = False):
    api = cfg.get("api", {})
    geo = cfg.get("geocoding", {})
    etl = cfg.get("etl", {})

    serpapi_key = api.get("serpapi_key")
    ollama_key  = api.get("ollama_api_key")
    user_agent  = api.get("user_agent", "climatewire/1.0")
    lookback    = etl.get("lookback_days", 1)
    data_dir    = etl.get("data_dir", "data")
    rate_nom    = geo.get("rate_limit_sec", 1.0)
    timeout     = geo.get("timeout_sec", 10.0)
    screen_rate = cfg.get("screening", {}).get("rate_limit_sec", 0.5)

    if not serpapi_key:
        logger.error("SERPAPI_KEY not set — aborting")
        return

    articles = extract.fetch_articles(
        queries=QUERIES,
        api_key=serpapi_key,
        wire=WIRE,
        lookback_days=lookback,
        exclusion_patterns=EXCLUSION_PATTERNS,
    )

    if test_mode:
        articles = articles[:10]

    if not no_screen:
        articles = screen.screen_articles(articles, SYSTEM_PROMPT, ollama_key, rate_limit_sec=screen_rate)

    articles = geocode.geocode_articles(articles, user_agent, rate_nom, timeout)

    for a in articles:
        a["event_type"] = classify(a)

    articles = join_sensor(articles)

    if not test_mode:
        new, total = load.write_outputs(articles, WIRE, data_dir)
        logger.info(f"[{WIRE}] done — {new} new rows, {total} total")
    else:
        logger.info(f"[{WIRE}] test mode — would write {len(articles)} rows")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Drought Wire")
    parser.add_argument("--config", default=None)
    parser.add_argument("--test", action="store_true")
    parser.add_argument("--no-screen", action="store_true")
    args = parser.parse_args()

    cfg = utils.load_config(args.config)
    utils.setup_logging(cfg.get("etl", {}).get("log_level", "INFO"))
    run(cfg, test_mode=args.test, no_screen=args.no_screen)
