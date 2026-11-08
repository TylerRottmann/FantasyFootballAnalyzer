"""Historical training dataset for Boom/Bust v2."""

from functools import lru_cache

from leagues.models import Player

from scripts.algorithm.features.rb_features import RBSeasonData
from scripts.algorithm.boom_bust.boom_bust_features_v2 import (
    build_boom_bust_features_v2,
)


def build_rb_dataset_v2(season):
    """Build RB examples using strictly pregame scoring history."""
    data = RBSeasonData.load(season)
    player_ids = list(data.players.keys())

    players = {
        player.id: player
        for player in Player.objects.filter(
            id__in=player_ids,
            position="RB",
        )
    }

    rows = []
    baseline_cache = {}

    for player_id, games in data.players.items():
        player = players.get(player_id)

        if player is None:
            continue

        previous_points = []

        for game in games:
            actual_points = game["fantasy_points_ppr"]

            if actual_points is None:
                continue

            features = build_boom_bust_features_v2(
                player,
                season,
                game["week"],
                previous_points,
                data=data,
            )

            if features["game_status"] == "GAME":
                from scripts.algorithm.boom_bust.boom_bust_labels_v2 import (
                    label_boom_bust_v2,
                )

                baseline = features["baseline"]
                baseline_source = "player_history"

                if baseline is None:
                    target_week = game["week"]
                    if target_week not in baseline_cache:
                        baseline_cache[target_week] = position_baseline_before_week(
                            season, target_week, "RB"
                        )
                    baseline = baseline_cache[target_week]
                    baseline_source = "position_history"

                outcome = label_boom_bust_v2(actual_points, baseline)

                rows.append({
                    **features,
                    "season": season,
                    "week": game["week"],
                    "player_id": player_id,
                    "baseline": baseline,
                    "baseline_source": baseline_source if baseline is not None else "unavailable",
                    "actual_points": float(actual_points),
                    "label": outcome["label"] if outcome else None,
                    "boom_threshold": outcome["boom_threshold"] if outcome else None,
                    "bust_threshold": outcome["bust_threshold"] if outcome else None,
                })

            previous_points.append(float(actual_points))

    return rows


@lru_cache(maxsize=256)
def position_baseline_before_week(season, week, position):
    """Average prior-week PPR scores for a position, without future data."""
    from django.db import connection

    if position not in ("QB", "RB", "WR", "TE"):
        raise ValueError(f"Unsupported position: {position}")

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT AVG(pws.fantasy_points_ppr)
            FROM player_weekly_stats pws
            JOIN players p ON p.id = pws.player_id
            WHERE pws.season = %s
              AND pws.week < %s
              AND pws.season_type = 'REG'
              AND p.position = %s
              AND pws.fantasy_points_ppr IS NOT NULL
            """,
            [season, week, position],
        )
        result = cursor.fetchone()[0]

    return round(float(result), 3) if result is not None else None


def build_other_positions_dataset_v2(season):
    """Build recorded-game historical examples for QB, WR, and TE."""
    # Feature builders share a read-only Psycopg connection.
    # Avoid leaving transactions open during large historical builds.
    from scripts.algorithm.features.qb_features import get_connection
    feature_connection = get_connection()
    if not feature_connection.autocommit:
        from psycopg.pq import TransactionStatus

        status = feature_connection.info.transaction_status
        if status in (TransactionStatus.INTRANS, TransactionStatus.INERROR):
            feature_connection.rollback()
        elif status != TransactionStatus.IDLE:
            raise RuntimeError(
                f"Cannot change autocommit while connection is {status.name}"
            )

        feature_connection.autocommit = True

    from django.db import connection
    from scripts.algorithm.boom_bust.boom_bust_labels_v2 import label_boom_bust_v2

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT pws.player_id, pws.week, pws.fantasy_points_ppr
            FROM player_weekly_stats pws
            JOIN players p ON p.id = pws.player_id
            WHERE pws.season = %s
              AND pws.season_type = 'REG'
              AND p.position IN ('QB', 'WR', 'TE')
              AND pws.fantasy_points_ppr IS NOT NULL
            ORDER BY pws.player_id, pws.week
        """, [season])
        records = cursor.fetchall()

    player_ids = {record[0] for record in records}
    players = {
        player.id: player
        for player in Player.objects.filter(id__in=player_ids)
    }

    history = {}
    baseline_cache = {}
    rows = []

    for player_id, week, actual_points in records:
        player = players.get(player_id)
        if player is None:
            continue

        previous_points = history.setdefault(player_id, [])

        features = build_boom_bust_features_v2(
            player,
            season,
            week,
            previous_points,
            historical=True,
        )

        if features is not None and features["game_status"] == "GAME":
            baseline = features["baseline"]
            baseline_source = "player_history"

            if baseline is None:
                cache_key = (player.position, week)
                if cache_key not in baseline_cache:
                    baseline_cache[cache_key] = position_baseline_before_week(
                        season, week, player.position
                    )
                baseline = baseline_cache[cache_key]
                baseline_source = "position_history"

            outcome = label_boom_bust_v2(actual_points, baseline)

            rows.append({
                **features,
                "season": season,
                "week": week,
                "player_id": player_id,
                "baseline": baseline,
                "baseline_source": (
                    baseline_source if baseline is not None else "unavailable"
                ),
                "actual_points": float(actual_points),
                "label": outcome["label"] if outcome else None,
                "boom_threshold": (
                    outcome["boom_threshold"] if outcome else None
                ),
                "bust_threshold": (
                    outcome["bust_threshold"] if outcome else None
                ),
            })

        previous_points.append(float(actual_points))

    return rows
