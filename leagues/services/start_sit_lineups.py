"""Cached Start / Sit lineup strategies and projected matchup margins."""
from hashlib import sha256

from django.core.cache import cache

from leagues.models import (
    DefenseProjection,
    FantasyMatchup,
    FantasyProjection,
)
from leagues.services.kicker_scoring import league_defense_projection, league_projection
from scripts.commands.lineup import (
    build_optimized_lineup,
    build_risk_adjusted_lineup,
    get_lineup_total,
)


LINEUP_STRATEGY_CACHE_TTL = 300


def _player_fingerprint(players):
    values = []
    for item in players:
        roster_player = item["roster_player"]
        prediction = item.get("prediction")
        boom_bust = item.get("boom_bust")
        values.append((
            roster_player.pk,
            roster_player.player_id,
            roster_player.team_id,
            roster_player.roster_slot,
            getattr(prediction, "projected_fantasy_points", None),
            getattr(prediction, "status", None),
            getattr(boom_bust, "boom_probability", None),
            getattr(boom_bust, "bust_probability", None),
        ))
    return sha256(repr(values).encode()).hexdigest()[:24]


def get_lineup_strategy_options(league, roster, week, players, starting_positions):
    """Get all three cached lineups; cache key follows roster/projection/risk inputs."""
    scoring = sha256(repr(league.scoring_settings).encode()).hexdigest()[:16]
    key = (
        f"start-sit-lineups:v1:{league.pk}:{roster.pk}:{league.season}:{week}:"
        f"{scoring}:{_player_fingerprint(players)}:{repr(tuple(starting_positions))}"
    )
    cached = cache.get(key)
    if cached is not None:
        return cached

    normal, normal_total = build_optimized_lineup(players, starting_positions)
    safe, safe_total = build_risk_adjusted_lineup(
        players, starting_positions, "safe", baseline_lineup=normal,
    )
    risky, risky_total = build_risk_adjusted_lineup(
        players, starting_positions, "risky", baseline_lineup=safe,
    )
    options = {
        "safe": {"lineup": safe, "total": safe_total},
        "normal": {"lineup": normal, "total": normal_total},
        "risky": {"lineup": risky, "total": risky_total},
    }
    cache.set(key, options, LINEUP_STRATEGY_CACHE_TTL)
    return options


def projected_matchup_margin(league, roster, platform, week, starting_positions, own_total, context=None):
    """Return this roster's normal projected score minus its opponent's, if available."""
    cache_key = (
        f"start-sit-matchup-margin:v1:{league.pk}:{roster.pk}:{league.season}:"
        f"{week}:{platform}:{own_total:.2f}"
    )
    missing = object()
    cached_margin = cache.get(cache_key, missing)
    if cached_margin is not missing:
        return cached_margin

    matchup = (
        FantasyMatchup.objects
        .filter(league=league, roster=roster, season=league.season, week=week, platform=platform)
        .select_related("opponent")
        .order_by("-updated_at", "-id")
        .first()
    )
    if matchup is None or matchup.opponent_id is None:
        cache.set(cache_key, None, LINEUP_STRATEGY_CACHE_TTL)
        return None

    entries = list(matchup.opponent.roster_players.select_related("player", "team"))
    if not entries:
        cache.set(cache_key, None, LINEUP_STRATEGY_CACHE_TTL)
        return None

    player_ids = {entry.player_id for entry in entries if entry.player_id is not None}
    team_ids = {entry.team_id for entry in entries if entry.player_id is None and entry.team_id is not None}
    projections = {
        row.player_id: league_projection(row, league, context=context)
        for row in FantasyProjection.objects.filter(
            player_id__in=player_ids,
            season=league.season,
            week=week,
            model_version="v2_stat",
        ).select_related("player")
    }
    defense_projections = {
        row.team_id: league_defense_projection(row, league)
        for row in DefenseProjection.objects.filter(
            team_id__in=team_ids,
            season=league.season,
            week=week,
            model_version="v2_stat",
        )
    }
    opponent_items = [{
        "player": entry.player,
        "roster_player": entry,
        "team": entry.team,
        "prediction": (
            projections.get(entry.player_id)
            if entry.player_id is not None
            else defense_projections.get(entry.team_id)
        ),
        "is_defense": entry.player_id is None,
    } for entry in entries]
    if not any(item["prediction"] is not None for item in opponent_items):
        cache.set(cache_key, None, LINEUP_STRATEGY_CACHE_TTL)
        return None
    opponent_total = get_lineup_total(
        build_optimized_lineup(opponent_items, starting_positions)[0]
    )
    margin = own_total - opponent_total
    cache.set(cache_key, margin, LINEUP_STRATEGY_CACHE_TTL)
    return margin


def recommended_lineup_strategy(margin):
    if margin is None:
        return "normal"
    if margin > 10:
        return "safe"
    if margin < -10:
        return "risky"
    return "normal"
