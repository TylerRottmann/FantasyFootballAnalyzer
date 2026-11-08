"""Pregame scoring-history retrieval for Boom/Bust v2."""

from django.db import connection


SUPPORTED_POSITIONS = frozenset({"QB", "RB", "WR", "TE"})


def load_previous_points(player, season, week):
    """Return regular-season PPR scores strictly before the target week.

    Matches the season-local scoring history used during v2 training.
    No target-week or future scores are included.
    """
    if player.position not in SUPPORTED_POSITIONS:
        raise ValueError(
            f"Unsupported position: {player.position}"
        )

    if not isinstance(season, int) or not 2000 <= season <= 2100:
        raise ValueError("Invalid season.")

    if not isinstance(week, int) or not 1 <= week <= 18:
        raise ValueError("Week must be between 1 and 18.")

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT week, fantasy_points_ppr
            FROM player_weekly_stats
            WHERE player_id = %s
              AND season = %s
              AND season_type = 'REG'
              AND week < %s
              AND fantasy_points_ppr IS NOT NULL
            ORDER BY week
            """,
            [player.id, season, week],
        )
        records = cursor.fetchall()

    seen_weeks = set()
    previous_points = []

    for historical_week, points in records:
        if historical_week in seen_weeks:
            raise ValueError(
                "Duplicate historical scoring record."
            )

        seen_weeks.add(historical_week)
        previous_points.append(float(points))

    return previous_points



def load_pregame_scoring_profile(player, season, week):
    """Build the scoring profile using the v2 training definitions."""
    from scripts.algorithm.boom_bust.boom_bust_features_v2 import (
        historical_scoring_features,
    )
    from scripts.algorithm.boom_bust.boom_bust_dataset_v2 import (
        position_baseline_before_week,
    )

    previous_points = load_previous_points(player, season, week)
    scoring = historical_scoring_features(previous_points)

    if scoring["baseline"] is not None:
        baseline_source = "player_history"
    else:
        fallback = position_baseline_before_week(
            season, week, player.position
        )
        scoring["baseline"] = fallback
        baseline_source = (
            "position_history" if fallback is not None else "unavailable"
        )

    return {
        "previous_points": previous_points,
        "scoring": scoring,
        "baseline_source": baseline_source,
    }
