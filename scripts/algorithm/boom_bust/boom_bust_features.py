from scripts.algorithm.features.qb_features import build_qb_features
from scripts.algorithm.features.rb_features import (
    build_rb_features,
    RBSeasonData,
)
from scripts.algorithm.features.wr_features import build_wr_features
from scripts.algorithm.features.te_features import build_te_features


FEATURE_BUILDERS = {
    "QB": build_qb_features,
    "RB": build_rb_features,
    "WR": build_wr_features,
    "TE": build_te_features,
}


def build_boom_bust_features(player, season, week, data=None):
    """
    Build pregame features for boom/bust probability prediction.
    """
    builder = FEATURE_BUILDERS.get(player.position)

    if builder is None:
        raise ValueError(
            f"Boom/Bust does not support position: {player.position}"
        )

    if player.position == "RB":
        if data is None:
            data = RBSeasonData.load(season, player.id, week)

        features = builder(player, season, week, data=data)
    else:
        features = builder(player, season, week)

    features = dict(features)

    if player.position == "RB":
        history = [
            game["fantasy_points_ppr"]
            for game in data.players.get(player.id, [])
            if game["week"] < week
            and game["fantasy_points_ppr"] is not None
        ]

        features["baseline"] = (
            round(sum(float(p) for p in history[-3:]) / 3, 2)
            if len(history) >= 3
            else None
        )

    features["boom_bust_volatility"] = features.get(
        "fantasy_points_stddev_l5"
    )

    if player.position == "RB":
        features["boom_bust_workload_trend"] = features.get(
            "touches_trend_l3_l8"
        )
    elif player.position in ("WR", "TE"):
        features["boom_bust_workload_trend"] = features.get(
            "targets_trend_l3_l8"
        )
    else:
        features["boom_bust_workload_trend"] = None

    return features