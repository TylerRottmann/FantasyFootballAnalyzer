"""Historical-baseline estimator for ESPN D/ST yards allowed."""

import math

YARDS_ALLOWED_TIERS = {
    128: (0, 99),
    129: (100, 199),
    130: (200, 299),
    132: (350, 399),
    133: (400, 449),
    134: (450, 499),
    135: (500, 549),
    136: (550, math.inf),
}

# Approximate historical residual standard deviation from 2024-2025.
HISTORICAL_STD_YARDS = 80.0


def estimate_yards_allowed(features):
    """Return estimated yards allowed and historical uncertainty.

    Uses only pre-game features. Returns None if required data is missing.
    """
    defense = features.get("total_yards_against_l5")
    offense = features.get("opponent_total_yards_l5")

    if defense is None or offense is None:
        return None

    defense = float(defense)
    offense = float(offense)

    if not all(map(math.isfinite, (defense, offense))):
        return None

    if defense < 0 or offense < 0:
        return None

    return {
        "mean": (defense + offense) / 2.0,
        "std": HISTORICAL_STD_YARDS,
        "method": "historical_l5_matchup_baseline",
    }


def _normal_cdf(value, mean, std):
    return 0.5 * (
        1.0 + math.erf((value - mean) / (std * math.sqrt(2.0)))
    )


def expected_yards_allowed_points(estimate, scoring_items):
    """Compute expected ESPN D/ST yards-allowed fantasy points."""
    mean = float(estimate["mean"])
    std = float(estimate["std"])

    if not math.isfinite(mean) or not math.isfinite(std) or std <= 0:
        raise ValueError("Invalid yards-allowed distribution")

    total = 0.0
    components = {}

    for item in scoring_items:
        stat_id = int(item["statId"])

        if stat_id not in YARDS_ALLOWED_TIERS:
            continue

        overrides = item.get("pointsOverrides") or {}
        weight = float(
            overrides.get("16", item.get("points", 0))
        )

        low, high = YARDS_ALLOWED_TIERS[stat_id]

        lower_probability = _normal_cdf(low - 0.5, mean, std)

        if math.isinf(high):
            probability = 1.0 - lower_probability
        else:
            probability = (
                _normal_cdf(high + 0.5, mean, std)
                - lower_probability
            )

        probability = max(0.0, min(1.0, probability))
        contribution = weight * probability

        components[stat_id] = contribution
        total += contribution

    return {
        "expected_points": round(total, 2),
        "components": components,
    }
