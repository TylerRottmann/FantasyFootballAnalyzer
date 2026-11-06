"""ESPN D/ST projection adapter using existing model statistics.

This module does not modify the existing scoring engine.
Unsupported scoring categories are reported rather than silently ignored.
"""
import math

from leagues.services.espn_dst_yards import (
    expected_yards_allowed_points,
    YARDS_ALLOWED_TIERS,
)


ESPN_DST_STATS = {
    95: "interceptions",
    96: "fumble_recoveries",
    98: "safeties",
    99: "sacks",
}

POINTS_ALLOWED_TIERS = {
    89: (0, 0),
    90: (1, 6),
    91: (7, 13),
    92: (14, 17),
    122: (22, 27),
    123: (28, 34),
    124: (35, 45),
    125: (46, float("inf")),
}

YARDS_ALLOWED_IDS = {
    127, 128, 129, 130, 131, 132,
    133, 134, 135, 136,
}

# Scoring categories belonging to offensive players or kickers.
NON_DST_IDS = {
    3, 4, 19, 20, 24, 25, 26,
    42, 43, 44, 53, 63, 72,
    77, 80, 85, 86, 198, 201,
}


def _normal_cdf(x, mean, std):
    if std <= 0:
        return float(mean <= x)
    return 0.5 * (
        1 + math.erf((x - mean) / (std * math.sqrt(2)))
    )


def score_espn_dst(stats, raw_settings, yards_estimate=None):
    """Return supported score components and unmodeled ESPN stat IDs."""
    if not isinstance(stats, dict) or not stats:
        raise ValueError("D/ST projected statistics are missing.")

    scoring = raw_settings.get("scoringSettings", {})
    items = scoring.get("scoringItems", [])

    total = 0.0
    unsupported = set()
    components = {}

    mean = stats.get("points_allowed")
    uncertainty = stats.get("_uncertainty") or {}
    std = uncertainty.get("points_allowed", 0)

    for item in items:
        stat_id = int(item["statId"])
        overrides = item.get("pointsOverrides") or {}
        weight = float(overrides.get("16", item.get("points", 0)))

        if not weight:
            continue

        if stat_id in NON_DST_IDS:
            continue

        if stat_id in ESPN_DST_STATS:
            name = ESPN_DST_STATS[stat_id]
            if name not in stats:
                unsupported.add(stat_id)
                continue

            contribution = float(stats[name]) * weight
            components[name] = components.get(name, 0) + contribution
            total += contribution

        elif stat_id in POINTS_ALLOWED_TIERS:
            if mean is None:
                unsupported.add(stat_id)
                continue

            low, high = POINTS_ALLOWED_TIERS[stat_id]
            probability = (
                1 - _normal_cdf(low - 0.5, mean, std)
                if math.isinf(high)
                else _normal_cdf(high + 0.5, mean, std)
                - _normal_cdf(low - 0.5, mean, std)
            )
            contribution = weight * max(0.0, min(1.0, probability))
            components[f"points_allowed_{stat_id}"] = contribution
            total += contribution

        else:
            unsupported.add(stat_id)

    # Aggregate touchdown predictions cannot be separated into individual
    # return types. Use them only when the relevant ESPN categories have
    # identical scoring weights, avoiding duplicate touchdown credit.
    touchdown_groups = {
        "defensive_tds": {103, 104},
        "special_teams_tds": {101, 102},
    }

    for name, stat_ids in touchdown_groups.items():
        relevant = []
        for item in items:
            stat_id = int(item["statId"])
            if stat_id not in stat_ids:
                continue
            overrides = item.get("pointsOverrides") or {}
            weight = float(overrides.get("16", item.get("points", 0)))
            relevant.append((stat_id, weight))

        if not relevant:
            continue

        weights = {weight for _, weight in relevant}

        if name in stats and len(weights) == 1 and len(relevant) == len(stat_ids):
            weight = weights.pop()
            contribution = float(stats[name]) * weight
            components[name] = contribution
            total += contribution
            unsupported.difference_update(stat_ids)

    if yards_estimate is not None:
        yards_result = expected_yards_allowed_points(
            yards_estimate, items
        )
        total += yards_result["expected_points"]

        for stat_id, contribution in yards_result["components"].items():
            components[f"yards_allowed_{stat_id}"] = contribution

        unsupported.difference_update(YARDS_ALLOWED_TIERS)

    return {
        "supported_points": round(total, 2),
        "components": components,
        "unsupported_stat_ids": sorted(unsupported),
        "complete": not unsupported,
    }
