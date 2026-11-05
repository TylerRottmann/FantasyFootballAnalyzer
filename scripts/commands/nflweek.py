import logging
import os

import requests

from django.core.cache import cache


SLEEPER_STATE_URL = "https://api.sleeper.app/v1/state/nfl"
CURRENT_WEEK_CACHE_KEY = "fantasy:nfl:current-week"
LAST_KNOWN_WEEK_CACHE_KEY = "fantasy:nfl:last-known-week"
logger = logging.getLogger(__name__)


def refresh_current_nfl_week():
    """Fetch and cache Sleeper's NFL week; call from a scheduled job."""
    response = requests.get(SLEEPER_STATE_URL, timeout=5)
    response.raise_for_status()
    week = int(response.json()["week"])
    cache.set(CURRENT_WEEK_CACHE_KEY, week, timeout=300)
    cache.set(LAST_KNOWN_WEEK_CACHE_KEY, week, timeout=60 * 60 * 24 * 30)
    return week


def get_current_nfl_week():
    cached_week = cache.get(CURRENT_WEEK_CACHE_KEY)
    if cached_week is not None:
        return int(cached_week)

    # Serve stale state immediately; the scheduled refresh will update Redis.
    last_known_week = cache.get(LAST_KNOWN_WEEK_CACHE_KEY)
    if last_known_week is not None:
        return int(last_known_week)

    # One-time cold-cache fallback keeps a new/local installation usable.
    try:
        return refresh_current_nfl_week()
    except (requests.RequestException, KeyError, TypeError, ValueError) as exc:
        fallback = os.getenv("NFL_WEEK_FALLBACK")
        if fallback:
            try:
                return max(1, min(18, int(fallback)))
            except ValueError:
                pass
        logger.exception("NFL week is not cached and Sleeper lookup failed")
        raise RuntimeError("NFL week is unavailable; run refresh_external_cache.") from exc
