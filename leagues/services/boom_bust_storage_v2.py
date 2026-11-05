"""Persist validated Boom/Bust v2 predictions to Supabase PostgreSQL."""

import math

from django.db import transaction

from leagues.models import BoomBustWeeklyPrediction


def save_boom_bust_prediction_v2(result):
    """Idempotently store a validated pregame prediction.

    This function must be called explicitly; the prediction GET endpoint
    does not write to the database.
    """
    if result.get("game_status") != "GAME":
        raise ValueError("Only verified game predictions can be saved.")

    position = result["position"]
    if position not in {"QB", "RB", "WR", "TE"}:
        raise ValueError("Unsupported position.")

    week = int(result["week"])
    season = int(result["season"])
    player_id = int(result["player_id"])
    version = str(result["model_version"])

    if not 1 <= week <= 18 or season < 2000 or player_id <= 0:
        raise ValueError("Invalid prediction identifiers.")

    probabilities = result["probabilities"]
    values = {
        name: float(probabilities[name])
        for name in ("boom", "bust", "normal")
    }

    if not all(math.isfinite(value) and 0 <= value <= 1
               for value in values.values()):
        raise ValueError("Invalid probability.")

    if abs(sum(values.values()) - 1.0) > 0.001:
        raise ValueError("Probabilities must sum to one.")

    baseline = result.get("baseline")
    if baseline is not None:
        baseline = float(baseline)
        if not math.isfinite(baseline):
            raise ValueError("Invalid baseline.")

    defaults = {
        "position": position,
        "boom_probability": values["boom"],
        "bust_probability": values["bust"],
        "normal_probability": values["normal"],
        "baseline": baseline,
        "baseline_source": str(result.get("baseline_source") or ""),
        "opponent_team": str(result.get("opponent_team") or ""),
        "is_home": result.get("is_home"),
        "prediction_data": result,
    }

    with transaction.atomic():
        prediction, created = BoomBustWeeklyPrediction.objects.update_or_create(
            player_id=player_id,
            season=season,
            week=week,
            model_version=version,
            defaults=defaults,
        )

    return prediction, created
