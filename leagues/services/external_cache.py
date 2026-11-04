"""Cache small Sleeper league settings already present in league payloads."""
from django.core.cache import cache


SLEEPER_PLAYOFF_CACHE_TTL = 60 * 60 * 24 * 30


def sleeper_playoff_cache_key(league):
    return f"sleeper_playoff_info:v2:{league.sleeper_league_id}"


def cache_sleeper_playoff_info(league, payload):
    settings_data = (payload or {}).get("settings") or {}
    try:
        playoff_teams = int(settings_data.get("playoff_teams") or 0)
    except (TypeError, ValueError):
        playoff_teams = 0

    info = None
    if playoff_teams > 0:
        bracket_size = 1
        while bracket_size < playoff_teams:
            bracket_size *= 2
        info = {
            "playoff_teams": playoff_teams,
            "first_round_byes": max(0, bracket_size - playoff_teams),
        }

    cache.set(
        sleeper_playoff_cache_key(league),
        info,
        timeout=SLEEPER_PLAYOFF_CACHE_TTL,
    )
    return info
