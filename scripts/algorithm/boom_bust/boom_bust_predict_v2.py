"""Standalone, schedule-verified Boom/Bust v2 inference."""

import math

import pandas as pd

from scripts.algorithm.boom_bust.boom_bust_artifacts_v2 import (
    POSITIONS,
)
from scripts.algorithm.boom_bust.boom_bust_context_v2 import (
    GameContextUnavailable,
    PlayerOnBye,
    validate_prediction_context,
)
from scripts.algorithm.boom_bust.boom_bust_features_v2 import (
    build_boom_bust_features_v2,
)
from scripts.algorithm.boom_bust.boom_bust_history_v2 import (
    load_pregame_scoring_profile,
)
from scripts.algorithm.boom_bust.boom_bust_schedule_v2 import (
    resolve_schedule_context,
)
from scripts.algorithm.boom_bust.boom_bust_kickoff_v2 import (
    validate_before_kickoff,
)
from scripts.algorithm.boom_bust.boom_bust_storage_v2 import (
    load_model_artifact,
)


def prepare_prediction_frame(features, feature_columns):
    """Reproduce training-time numeric conversion and column order."""
    if not isinstance(features, dict):
        raise ValueError("Features must be a dictionary.")

    if not isinstance(feature_columns, list) or not feature_columns:
        raise ValueError("Feature schema must be a nonempty list.")

    if len(feature_columns) != len(set(feature_columns)):
        raise ValueError("Duplicate feature columns.")

    missing = [name for name in feature_columns if name not in features]

    if missing:
        raise ValueError(
            f"Missing required feature keys: {missing[:10]}"
        )

    frame = pd.DataFrame([features])
    frame = frame.reindex(columns=feature_columns)
    frame = frame.apply(pd.to_numeric, errors="coerce")

    if frame.shape != (1, len(feature_columns)):
        raise ValueError("Unexpected inference feature dimensions.")

    return frame


def predict_boom_bust_v2(player, season, week):
    """Predict calibrated outcome probabilities for a verified game."""
    if player.position not in POSITIONS:
        raise ValueError(
            f"Unsupported position: {player.position}"
        )

    if type(season) is not int or not 2000 <= season <= 2100:
        raise ValueError("Invalid season.")

    if type(week) is not int or not 1 <= week <= 18:
        raise ValueError("Invalid regular-season week.")

    # Verify the schedule before building features or loading a model.
    schedule = resolve_schedule_context(player, season, week)

    validate_prediction_context(schedule, player)

    validate_before_kickoff(
        season=season,
        week=week,
        team_id=schedule["team_id"],
        opponent_team_id=schedule["opponent_team_id"],
        is_home=schedule["is_home"],
    )

    profile = load_pregame_scoring_profile(player, season, week)

    kwargs = {
        "player": player,
        "season": season,
        "week": week,
        "previous_points": profile["previous_points"],
    }

    if player.position == "RB":
        from scripts.algorithm.features.rb_features import RBSeasonData

        # The RB builder filters all historical statistics to weeks < week.
        kwargs["data"] = RBSeasonData.load(
            season,
            through_week=week - 1,
        )

    features = build_boom_bust_features_v2(**kwargs)

    if features is None:
        raise GameContextUnavailable(
            "Feature builder could not resolve the matchup."
        )

    expected_context_keys = (
        "game_status",
        "team_id",
        "opponent_team_id",
        "opponent_team",
        "is_home",
    )

    for key in expected_context_keys:
        if features.get(key) != schedule.get(key):
            raise GameContextUnavailable(
                f"Feature/schedule mismatch for {key}: "
                f"{features.get(key)!r} != {schedule.get(key)!r}"
            )

    validate_prediction_context(features, player)

    # Apply the identical pregame scoring fallback used in training.
    features.update(profile["scoring"])

    artifact = load_model_artifact(player.position)

    frame = prepare_prediction_frame(
        features,
        artifact["feature_columns"],
    )

    probabilities = artifact["model"].predict_proba(frame)

    if getattr(probabilities, "shape", None) != (1, 3):
        raise ValueError("Unexpected probability output dimensions.")

    values = [float(value) for value in probabilities[0]]

    if (
        any(not math.isfinite(value) for value in values)
        or any(value < 0 or value > 1 for value in values)
        or not math.isclose(
            sum(values),
            1.0,
            rel_tol=0,
            abs_tol=1e-6,
        )
    ):
        raise ValueError("Invalid calibrated probabilities.")

    outcomes = dict(zip(artifact["classes"], values))

    if set(outcomes) != {"boom", "bust", "normal"}:
        raise ValueError("Unexpected probability classes.")

    return {
        "player_id": player.id,
        "position": player.position,
        "season": season,
        "week": week,
        "game_status": "GAME",
        "team_id": schedule["team_id"],
        "opponent_team": schedule["opponent_team"],
        "is_home": schedule["is_home"],
        "baseline": profile["scoring"]["baseline"],
        "baseline_source": profile["baseline_source"],
        "probabilities": {
            "boom": outcomes["boom"],
            "bust": outcomes["bust"],
            "normal": outcomes["normal"],
        },
        "model_version": artifact["artifact_version"],
    }
