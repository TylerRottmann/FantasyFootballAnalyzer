"""Fetch and cache small league metadata outside user page requests."""
from django.core.cache import cache

from leagues.integrations.sleeper import SleeperLeagueService


def sleeper_playoff_cache_key(league):
    return f"sleeper_playoff_info:{league.sleeper_league_id}"


def get_cached_sleeper_playoff_info(league):
    return cache.get(sleeper_playoff_cache_key(league))


def refresh_sleeper_playoff_info(league, *, force=False):
    key = sleeper_playoff_cache_key(league)
    missing = object()
    cached = cache.get(key, missing)
    if not force and cached is not missing:
        return cached

    service = SleeperLeagueService(league.sleeper_league_id)
    service.REQUEST_TIMEOUT = 5
    payload = service.get_league() or {}
    settings_data = payload.get("settings") or {}
    playoff_teams = int(settings_data.get("playoff_teams") or 0)
    info = None
    if playoff_teams > 0:
        bracket_size = 1
        while bracket_size < playoff_teams:
            bracket_size *= 2
        info = {
            "playoff_teams": playoff_teams,
            "first_round_byes": max(0, bracket_size - playoff_teams),
        }
    cache.set(key, info, timeout=60 * 60 * 12)
    return info
