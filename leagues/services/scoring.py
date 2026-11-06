"""League-specific fantasy scoring for projected stat lines."""
from __future__ import annotations

import math

from leagues.services.scoring_settings import normalize_scoring_settings

REFERENCE_SKILL_SCORING = {
    "schema_version": 1,
    "source": "reference",
    "rules": {
        "pass_yd": 0.04, "pass_td": 4, "pass_int": -2, "pass_2pt": 2,
        "rush_yd": 0.1, "rush_td": 6, "rush_2pt": 2,
        "rec": 1, "rec_yd": 0.1, "rec_td": 6, "rec_2pt": 2,
        "fum_lost": -2, "dst_sack": 1, "dst_int": 2,
        "dst_fum": 2, "dst_ff": 1, "dst_fum_rec_td": 6,
        "dst_def_td": 6, "dst_st_td": 6, "dst_safety": 2,
        "pts_allow_0": 10, "pts_allow_1_6": 7, "pts_allow_7_13": 4,
        "pts_allow_14_20": 1, "pts_allow_21_27": 0,
        "pts_allow_28_34": -1, "pts_allow_35_plus": -4,
    },
    "unsupported_rules": [],
}


STAT_RULES = {
    "pass_yd": ("passing_yards", "pass_yd"),
    "pass_td": ("passing_tds", "pass_td"),
    "pass_int": ("passing_interceptions", "interceptions_thrown", "pass_int"),
    "pass_2pt": ("passing_2pt_conversions", "pass_2pt"),
    "rush_yd": ("rushing_yards", "rush_yd"),
    "rush_td": ("rushing_tds", "rush_td"),
    "rush_2pt": ("rushing_2pt_conversions", "rush_2pt"),
    "rec": ("receptions", "rec"),
    "rec_yd": ("receiving_yards", "rec_yd"),
    "rec_td": ("receiving_tds", "rec_td"),
    "rec_2pt": ("receiving_2pt_conversions", "rec_2pt"),
    "fum_lost": ("fumbles_lost", "fum_lost"),
    "dst_sack": ("sacks", "dst_sack"),
    "dst_int": ("interceptions", "dst_int"),
    "dst_fum": ("fumble_recoveries", "dst_fum"),
    "dst_ff": ("forced_fumbles", "dst_ff"),
    "dst_def_td": ("defensive_tds", "dst_def_td"),
    "dst_st_td": ("special_teams_tds", "dst_st_td"),
    "dst_safety": ("safeties", "dst_safety"),
    "dst_blocked_kick": ("blocked_kicks", "dst_blocked_kick"),
}


def _normalized_settings(scoring_settings):
    if isinstance(scoring_settings, dict) and scoring_settings.get("schema_version"):
        settings = scoring_settings
        if settings.get("source") in {"sleeper", "yahoo"} and isinstance(settings.get("raw"), dict):
            return normalize_scoring_settings(settings["raw"], source=settings["source"])
        return settings
    return normalize_scoring_settings(scoring_settings)


def _rules(scoring_settings, position=None):
    settings = _normalized_settings(scoring_settings)
    # Unknown scoring modifiers are omitted from the calculation. They should
    # not suppress all otherwise scoreable projections for a league.
    rules = settings.get("rules", {})
    if not isinstance(rules, dict):
        raise ValueError("League scoring rules are malformed.")

    if settings.get("source") == "espn":
        position_ids = {
            "QB": "1",
            "RB": "2",
            "WR": "3",
            "TE": "4",
            "K": "5",
            "DEF": "16",
            "DST": "16",
            "D/ST": "16",
        }
        position_id = position_ids.get(str(position or "").upper())
        overrides = settings.get("position_overrides", {})

        if position_id and position_id in overrides:
            rules = {**rules, **overrides[position_id]}

    return rules


def _stat(stat_line, aliases):
    for name in aliases:
        if name in stat_line:
            value = float(stat_line[name] or 0)
            if not math.isfinite(value):
                raise ValueError(f"Non-finite projected stat: {name}")
            return value
    raise ValueError(f"Projected stat is missing: {aliases[0]}")


def score_stat_line(stat_line, scoring_settings, position=None):
    """Score projected component stats using one league's normalized rules.

    Stat names use the imported weekly-stat vocabulary (for example
    ``passing_tds`` and ``receiving_yards``). Kicker components are delegated
    to the established distance-aware scorer.
    """
    if not isinstance(stat_line, dict):
        raise ValueError("Projected stat line must be an object.")
    uncertainty = stat_line.get("_uncertainty", {})
    uncertainty = uncertainty if isinstance(uncertainty, dict) else {}
    # Metadata is kept beside component stats in stored projections.
    stat_line = {key: value for key, value in stat_line.items() if not str(key).startswith("_")}
    settings = _normalized_settings(scoring_settings)
    if settings.get("source") == "espn":
        unsupported = settings.get("unsupported_rules", [])
        global_unsupported = [
            rule for rule in unsupported
            if rule.startswith(("statId:", "invalid_", "malformed_", "conflicting_"))
        ]

        # ESPN IDs identified as kicker or defensive/return scoring.
        # Do not treat these as unsupported ordinary offensive stats.
        non_offensive_espn_ids = {
            63, 77, 80, 85, 86, 93, 101, 102, 103,
            104, 198, 201, 206, 209,
        }

        if str(position or "").upper() in {"QB", "RB", "WR", "TE"}:
            global_unsupported = [
                rule for rule in global_unsupported
                if not (
                    rule.startswith("statId:")
                    and rule[7:].isdigit()
                    and int(rule[7:]) in non_offensive_espn_ids
                )
            ]

        rules_for_position = _rules(scoring_settings, position)
        position_unsupported = [
            name for name, value in rules_for_position.items()
            if name.startswith("_unsupported_statId:") and value
        ]

        if str(position or "").upper() in {"QB", "RB", "WR", "TE"}:
            position_unsupported = [
                name for name in position_unsupported
                if not (
                    name.removeprefix("_unsupported_statId:").isdigit()
                    and int(name.removeprefix("_unsupported_statId:"))
                    in non_offensive_espn_ids
                )
            ]

        if global_unsupported or position_unsupported:
            raise ValueError(
                "Unsupported ESPN scoring rules: "
                + ", ".join(global_unsupported + position_unsupported)
            )

    rules = _rules(scoring_settings, position)
    if position == "K" or "fg_made_0_19" in stat_line:
        from scripts.algorithm.k.scoring import score_kicking
        return score_kicking(stat_line, rules)

    is_defense = position in {"DEF", "DST", "D/ST"}
    points = 0.0
    for rule_name, aliases in STAT_RULES.items():
        if rule_name.startswith("dst_") != is_defense:
            continue
        # The current D/ST model has no blocked-kick stat target, so skip it.
        if is_defense and rule_name == "dst_blocked_kick":
            continue
        weight = float(rules.get(rule_name, 0) or 0)
        if not math.isfinite(weight):
            raise ValueError(f"Non-finite scoring weight: {rule_name}")
        if weight:
            points += _stat(stat_line, aliases) * weight

    # Yahoo/Sleeper bonuses for receiving TD tiers and long plays are only
    # scored when corresponding projected components are available.
    for bonus_name, aliases, stat_name, threshold in (() if is_defense else (
        ("rec_td_40p", ("receiving_tds_40_plus", "rec_td_40p"), None, None),
        ("pass_td_40p", ("passing_tds_40_plus", "pass_td_40p"), None, None),
        ("rush_td_40p", ("rushing_tds_40_plus", "rush_td_40p"), None, None),
        ("rec_yd_100", ("receiving_yards_100_plus", "rec_yd_100"), "receiving_yards", 100),
        ("rec_yd_200", ("receiving_yards_200_plus", "rec_yd_200"), "receiving_yards", 200),
        ("rush_yd_100", ("rushing_yards_100_plus", "rush_yd_100"), "rushing_yards", 100),
        ("rush_yd_200", ("rushing_yards_200_plus", "rush_yd_200"), "rushing_yards", 200),
        ("pass_yd_300", ("passing_yards_300_plus", "pass_yd_300"), "passing_yards", 300),
        ("pass_yd_400", ("passing_yards_400_plus", "pass_yd_400"), "passing_yards", 400),
    )):
        weight = float(rules.get(bonus_name, 0) or 0)
        if weight:
            if stat_name and threshold:
                points += weight * _probability_at_least(
                    _stat(stat_line, (stat_name,)), uncertainty.get(stat_name), threshold
                )
            else:
                points += _stat(stat_line, aliases) * weight

    if position == "TE" and rules.get("bonus_rec_te"):
        points += _stat(stat_line, STAT_RULES["rec"]) * float(rules["bonus_rec_te"])

    # D/ST points-allowed scoring is tiered, not a per-point multiplier.
    points_allowed_rules = {
        "pts_allow_0": (lambda value: value == 0),
        "pts_allow_1_6": (lambda value: 1 <= value <= 6),
        "pts_allow_7_13": (lambda value: 7 <= value <= 13),
        "pts_allow_14_20": (lambda value: 14 <= value <= 20),
        "pts_allow_21_27": (lambda value: 21 <= value <= 27),
        "pts_allow_28_34": (lambda value: 28 <= value <= 34),
        "pts_allow_35_plus": (lambda value: value >= 35),
    }
    if is_defense and any(name in rules for name in points_allowed_rules):
        allowed = _stat(stat_line, ("points_allowed",))
        scale = _uncertainty_scale(uncertainty.get("points_allowed"))
        if scale <= 0:
            points += sum(float(rules.get(name, 0) or 0) for name, condition in points_allowed_rules.items() if condition(allowed))
        else:
            intervals = {
                "pts_allow_0": (None, 0.5),
                "pts_allow_1_6": (0.5, 6.5),
                "pts_allow_7_13": (6.5, 13.5),
                "pts_allow_14_20": (13.5, 20.5),
                "pts_allow_21_27": (20.5, 27.5),
                "pts_allow_28_34": (27.5, 34.5),
                "pts_allow_35_plus": (34.5, None),
            }
            for name, (low, high) in intervals.items():
                points += float(rules.get(name, 0) or 0) * _normal_interval_probability(
                    allowed, scale, low, high
                )
    return float(points)


def _uncertainty_scale(value):
    try:
        scale = float(value)
        return scale if math.isfinite(scale) and scale > 0 else 0.0
    except (TypeError, ValueError):
        return 0.0


def _normal_cdf(value, mean, scale):
    return 0.5 * (1.0 + math.erf((value - mean) / (scale * math.sqrt(2.0))))


def _normal_interval_probability(mean, scale, low, high):
    lower = 0.0 if low is None else _normal_cdf(low, mean, scale)
    upper = 1.0 if high is None else _normal_cdf(high, mean, scale)
    return max(0.0, min(1.0, upper - lower))


def _probability_at_least(stat_mean, uncertainty, threshold):
    scale = _uncertainty_scale(uncertainty)
    if scale <= 0:
        return float(stat_mean >= threshold)
    return 1.0 - _normal_cdf(threshold - 0.5, stat_mean, scale)


def league_uses_compatible_ppr(league):
    """Whether a legacy PPR point-only forecast can safely represent a league."""
    try:
        rules = _rules(league.scoring_settings)
    except (TypeError, ValueError):
        return False
    expected = {
        "pass_yd": 0.04, "pass_td": 4.0, "pass_int": -2.0,
        "rush_yd": 0.1, "rush_td": 6.0,
        "rec": 1.0, "rec_yd": 0.1, "rec_td": 6.0, "fum_lost": -2.0,
    }
    if any(rules.get(key, 0) != value for key, value in expected.items()):
        return False
    position_specific = {key for key in rules if key.startswith(("dst_", "fg", "xp", "pts_allow_"))}
    return not any(value for key, value in rules.items() if key not in expected and key not in position_specific)


def score_projection(prediction, league):
    """Score a prediction for a league, returning None when stats are absent."""
    stat_line = prediction.get("projected_stats")
    if stat_line:
        try:
            return score_stat_line(stat_line, league.scoring_settings, prediction.get("position"))
        except (TypeError, ValueError):
            return None
    if league_uses_compatible_ppr(league):
        return prediction.get("projected_fantasy_points")
    return None
