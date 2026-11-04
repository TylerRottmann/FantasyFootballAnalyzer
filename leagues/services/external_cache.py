"""Fetch and cache small Sleeper league settings outside user page requests."""
from django.core.cache import cache


SLEEPER_PLAYOFF_CACHE_TTL = 60 * 60 * 24 * 30


def sleeper_playoff_cache_key(league):
    # Version the key so old negative cache entries from earlier implementations
    # cannot suppress playoff highlights after this fix is deployed.
    return f"sleeper_playoff_info:v2:{league.sleeper_league_id}"


def _playoff_info_from_payload(payload):
    settings_data = (payload or {}).get("settings") or {}
    try:
        playoff_teams = int(settings_data.get("playoff_teams") or 0)
    except (TypeError, ValueError):
        playoff_teams = 0

    if playoff_teams <= 0:
        return None

    bracket_size = 1
    while bracket_size < playoff_teams:
        bracket_size *= 2
    return {
        "playoff_teams": playoff_teams,
        "first_round_byes": max(0, bracket_size - playoff_teams),
    }


def cache_sleeper_playoff_info(league, payload):
    """Save settings from a Sleeper league payload already in hand."""
    info = _playoff_info_from_payload(payload)
    cache.set(
        sleeper_playoff_cache_key(league),
        info,
        timeout=SLEEPER_PLAYOFF_CACHE_TTL,
    )
    return info


def get_cached_sleeper_playoff_info(league, default=None):
    return cache.get(sleeper_playoff_cache_key(league), default)


def refresh_sleeper_playoff_info(league, *, force=False):
    key = sleeper_playoff_cache_key(league)
    missing = object()
    cached = cache.get(key, missing)
    if not force and cached is not missing:
        return cached

    # Lazy import avoids a cycle: SleeperLeagueService seeds this cache while
    # importing the same league payload.
    from leagues.integrations.sleeper import SleeperLeagueService

    service = SleeperLeagueService(league.sleeper_league_id)
    service.REQUEST_TIMEOUT = 5
    payload = service.get_league() or {}
    return cache_sleeper_playoff_info(league, payload)
