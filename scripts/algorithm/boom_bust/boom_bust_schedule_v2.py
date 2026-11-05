"""Verified regular-season schedule context for Boom/Bust v2."""

from collections import Counter

from django.db import connection

from scripts.algorithm.boom_bust.boom_bust_context_v2 import (
    GameContextUnavailable,
)


def resolve_schedule_context(player, season, week):
    """Resolve a matchup only when the complete schedule is available."""
    if not isinstance(season, int) or isinstance(season, bool):
        raise ValueError("Season must be an integer.")

    if not isinstance(week, int) or isinstance(week, bool):
        raise ValueError("Week must be an integer.")

    if not 1 <= week <= 18:
        raise ValueError("Regular-season week must be 1 through 18.")

    team_id = getattr(player, "team_id", None)

    if team_id is None:
        raise GameContextUnavailable(
            "Player has no assigned team."
        )

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT week, home_team_id, away_team_id
            FROM nfl_games
            WHERE season = %s AND game_type = 'REG'
            """,
            (season,),
        )
        games = cursor.fetchall()

        cursor.execute(
            "SELECT id, abbreviation FROM teams"
        )
        abbreviations = dict(cursor.fetchall())

    if len(games) != 272:
        raise GameContextUnavailable(
            "Regular-season schedule is incomplete."
        )

    counts = Counter()
    weekly_counts = Counter()
    unique_games = set()

    for game_week, home_id, away_id in games:
        if (
            not isinstance(game_week, int)
            or isinstance(game_week, bool)
            or not 1 <= game_week <= 18
            or home_id is None
            or away_id is None
            or home_id == away_id
        ):
            raise GameContextUnavailable(
                "Schedule contains an invalid matchup."
            )

        game_key = (game_week, home_id, away_id)

        if game_key in unique_games:
            raise GameContextUnavailable(
                "Schedule contains a duplicate game."
            )

        unique_games.add(game_key)

        for scheduled_team in (home_id, away_id):
            counts[scheduled_team] += 1
            weekly_counts[(game_week, scheduled_team)] += 1

            if weekly_counts[(game_week, scheduled_team)] > 1:
                raise GameContextUnavailable(
                    "Team is scheduled more than once in a week."
                )

    if (
        len(counts) != 32
        or any(count != 17 for count in counts.values())
    ):
        raise GameContextUnavailable(
            "Team schedule coverage is incomplete."
        )

    if team_id not in counts:
        raise GameContextUnavailable(
            "Player team is absent from the schedule."
        )

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT home_team_id, away_team_id
            FROM nfl_games
            WHERE season = %s
              AND week = %s
              AND game_type = 'REG'
            """,
            (season, week),
        )
        weekly_games = cursor.fetchall()

    matchups = [
        (home_id, away_id)
        for home_id, away_id in weekly_games
        if team_id in (home_id, away_id)
    ]

    if len(matchups) > 1:
        raise GameContextUnavailable(
            "Team has multiple scheduled games this week."
        )

    if not matchups:
        return {
            "game_status": "BYE",
            "team_id": team_id,
            "opponent_team_id": None,
            "opponent_team": None,
            "is_home": None,
        }

    home_id, away_id = matchups[0]
    is_home = team_id == home_id
    opponent_id = away_id if is_home else home_id
    opponent = abbreviations.get(opponent_id)

    if not opponent:
        raise GameContextUnavailable(
            "Opponent abbreviation is missing."
        )

    return {
        "game_status": "GAME",
        "team_id": team_id,
        "opponent_team_id": opponent_id,
        "opponent_team": opponent,
        "is_home": is_home,
    }
