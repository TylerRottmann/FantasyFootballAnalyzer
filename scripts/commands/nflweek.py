import logging

import requests

from django.core.cache import cache


SLEEPER_STATE_URL = "https://api.sleeper.app/v1/state/nfl"
CURRENT_WEEK_CACHE_KEY = "fantasy:nfl:current-week"
LAST_KNOWN_WEEK_CACHE_KEY = "fantasy:nfl:last-known-week"
logger = logging.getLogger(__name__)


def get_current_nfl_week():
    cached_week = cache.get(CURRENT_WEEK_CACHE_KEY)
    if cached_week is not None:
        return int(cached_week)

    try:
        response = requests.get(
            SLEEPER_STATE_URL,
            timeout=5,
        )
        response.raise_for_status()
        week = int(response.json()["week"])
    except (requests.RequestException, KeyError, TypeError, ValueError):
        last_known_week = cache.get(LAST_KNOWN_WEEK_CACHE_KEY)
        if last_known_week is not None:
            logger.warning(
                "Sleeper week lookup failed; using cached week %s",
                last_known_week,
            )
            return int(last_known_week)
        raise

    cache.set(CURRENT_WEEK_CACHE_KEY, week, timeout=300)
    cache.set(LAST_KNOWN_WEEK_CACHE_KEY, week, timeout=60 * 60 * 24 * 30)
    return week
