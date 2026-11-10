
from collections import Counter

from psycopg.rows import dict_row

from leagues.models import Player
from scripts.algorithm.features.qb_features import get_connection
from scripts.algorithm.features.rb_features import RBSeasonData
from scripts.algorithm.boom_bust.boom_bust_features import (
    build_boom_bust_features,
)
from scripts.algorithm.boom_bust.boom_bust_labels import (
    label_boom_bust,
)


def build_rb_training_dataset(season):
    """
    Build historical RB training rows for one season.

    Each row contains pregame features and a boom/bust label.
    """

    # Load season data once to avoid repeated database queries.
    data = RBSeasonData.load(season)

    # Find RBs with recorded regular-season performances.
    with get_connection().cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT DISTINCT p.player_id
            FROM player_weekly_stats p
            JOIN players pl ON pl.id = p.player_id
            WHERE p.season = %s
              AND p.season_type = 'REG'
              AND pl.position = 'RB'
              AND p.fantasy_points_ppr IS NOT NULL
            """,
            (season,),
        )
        player_ids = [row["player_id"] for row in cur.fetchall()]

    players = {
        player.id: player
        for player in Player.objects.filter(id__in=player_ids)
    }

    rows = []

    for player_id in player_ids:
        player = players.get(player_id)

        if player is None:
            continue

        games = data.players.get(player_id, [])
        previous_points = []

        for game in games:
            actual_points = game["fantasy_points_ppr"]

            if actual_points is None:
                continue

            label_info = label_boom_bust(
                previous_points,
                actual_points,
            )

            if label_info is not None:
                features = build_boom_bust_features(
                    player,
                    season,
                    game["week"],
                    data=data,
                )

                rows.append({
                    **features,
                    "actual_points": actual_points,
                    "baseline": label_info["baseline"],
                    "label": label_info["label"],
                })

            # Update history only after labeling this game.
            previous_points.append(actual_points)

    return rows


def summarize_labels(rows):
    return dict(Counter(row["label"] for row in rows))
