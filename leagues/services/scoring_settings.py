"""Normalize platform league scoring into a stable internal representation."""
from __future__ import annotations

import math
import re


SCHEMA_VERSION = 1

# Platform-native names mapped to the internal names used by the scorer.
SLEEPER_RULES = {
    "pass_yd": "pass_yd", "pass_td": "pass_td", "pass_int": "pass_int",
    "pass_2pt": "pass_2pt", "bonus_pass_yd_300": "pass_yd_300",
    "bonus_pass_yd_400": "pass_yd_400", "bonus_rec_yd_100": "rec_yd_100",
    "bonus_rec_yd_200": "rec_yd_200", "bonus_rush_yd_100": "rush_yd_100",
    "bonus_rush_yd_200": "rush_yd_200",
    "rush_yd": "rush_yd", "rush_td": "rush_td", "rush_2pt": "rush_2pt",
    "rec": "rec", "rec_yd": "rec_yd", "rec_td": "rec_td",
    "rec_2pt": "rec_2pt", "bonus_rec_te": "bonus_rec_te",
    "fum_lost": "fum_lost", "fum_rec": "dst_fum", "sack": "dst_sack",
    "ff": "dst_ff", "fum_rec_td": "dst_fum_rec_td",
    "int": "dst_int", "safe": "dst_safety", "blk_kick": "dst_blocked_kick",
    "def_td": "dst_def_td", "def_st_td": "dst_st_td", "pts_allow_0": "pts_allow_0",
    "pts_allow_1": "pts_allow_1_6", "pts_allow_6": "pts_allow_1_6",
    "pts_allow_1_6": "pts_allow_1_6",
    "pts_allow_7": "pts_allow_7_13", "pts_allow_13": "pts_allow_7_13",
    "pts_allow_7_13": "pts_allow_7_13",
    "pts_allow_14": "pts_allow_14_20", "pts_allow_20": "pts_allow_14_20",
    "pts_allow_14_20": "pts_allow_14_20",
    "pts_allow_21": "pts_allow_21_27", "pts_allow_27": "pts_allow_21_27",
    "pts_allow_21_27": "pts_allow_21_27",
    "pts_allow_28": "pts_allow_28_34", "pts_allow_34": "pts_allow_28_34",
    "pts_allow_28_34": "pts_allow_28_34",
    "pts_allow_35": "pts_allow_35_plus", "pts_allow_35p": "pts_allow_35_plus",
    "pts_allow_35_plus": "pts_allow_35_plus",
    **{f"fgm_{bucket}": f"fgm_{bucket}" for bucket in ("0_19", "20_29", "30_39", "40_49", "50_59", "60_")},
    **{f"fgmiss_{bucket}": f"fgmiss_{bucket}" for bucket in ("0_19", "20_29", "30_39", "40_49", "50_59", "60_")},
    "fgm": "fgm", "fgm_yds": "fgm_yds", "fgm_yds_over_30": "fgm_yds_over_30",
    "fgm_50p": "fgm_50p", "fgm_60p": "fgm_60p", "fgmiss": "fgmiss",
    "fgmiss_50p": "fgmiss_50p", "fgmiss_60p": "fgmiss_60p", "xpm": "xpm", "xpmiss": "xpmiss",
}

YAHOO_RULE_LABELS = {
    "passing yards bonus 300": "pass_yd_300", "passing yards bonus 400": "pass_yd_400",
    "rushing yards bonus 100": "rush_yd_100", "rushing yards bonus 200": "rush_yd_200",
    "receiving yards bonus 100": "rec_yd_100", "receiving yards bonus 200": "rec_yd_200",
    "defensive interception": "dst_int", "defensive touchdown": "dst_def_td",
    "special teams touchdown": "dst_st_td", "interception thrown": "pass_int",
    "passing touchdown": "pass_td", "passing yards": "pass_yd", "interception": "pass_int",
    "rushing touchdown": "rush_td", "rushing yards": "rush_yd",
    "reception": "rec", "receiving touchdown": "rec_td",
    "receiving yards": "rec_yd", "fumble lost": "fum_lost",
    "passing 2-point conversion": "pass_2pt", "passing 2 point conversion": "pass_2pt",
    "passing 2pt conversion": "pass_2pt",
    "rushing 2-point conversion": "rush_2pt", "rushing 2 point conversion": "rush_2pt",
    "rushing 2pt conversion": "rush_2pt",
    "receiving 2-point conversion": "rec_2pt", "receiving 2 point conversion": "rec_2pt",
    "receiving 2pt conversion": "rec_2pt",
    "sack": "dst_sack", "fumble recovery": "dst_fum", "safety": "dst_safety",
}

def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def normalize_sleeper_settings(raw):
    """Return normalized rules while retaining the original Sleeper payload."""
    raw = raw if isinstance(raw, dict) else {}
    rules, unsupported = {}, []
    for name, value in raw.items():
        number = _number(value)
        if number is None:
            if value not in (None, ""):
                unsupported.append(str(name))
            continue
        canonical = SLEEPER_RULES.get(str(name))
        if canonical:
            # Multiple platform keys can describe the same DST threshold; keep
            # the direct boundary value when duplicate aliases are present.
            rules[canonical] = number
        elif number != 0:
            unsupported.append(str(name))
    return {
        **raw,
        "schema_version": SCHEMA_VERSION,
        "source": "sleeper",
        "rules": rules,
        "unsupported_rules": sorted(set(unsupported)),
        "raw": raw,
    }


def normalize_yahoo_settings(raw):
    """Normalize Yahoo stat modifiers using the labels supplied by Yahoo."""
    raw = raw if isinstance(raw, dict) else {}
    modifiers, unsupported = {}, []
    nodes = list(_walk(raw))
    labels = {str(node["stat_id"]): str(node.get("name", "")).strip().lower()
              for node in nodes if "stat_id" in node and node.get("name")}
    for node in nodes:
        if "stat_id" not in node or "value" not in node:
            continue
        label = re.sub(r"\s+", " ", labels.get(str(node["stat_id"]), ""))
        number = _number(node["value"])
        if number is None:
            unsupported.append(label or str(node["stat_id"]))
            continue
        canonical = next((rule for phrase, rule in YAHOO_RULE_LABELS.items() if phrase in label), None)
        if canonical:
            modifiers[canonical] = number
        elif number != 0:
            unsupported.append(label or str(node["stat_id"]))
    stat_modifiers = {str(node["stat_id"]): node["value"] for node in nodes
                      if "stat_id" in node and "value" in node}
    return {
        "yahoo": raw,
        "stat_modifiers": stat_modifiers,
        "schema_version": SCHEMA_VERSION,
        "source": "yahoo",
        "rules": modifiers,
        "unsupported_rules": sorted(set(unsupported)),
        "raw": raw,
    }


def normalize_scoring_settings(raw, source=None):
    """Normalize an imported scoring payload based on its platform."""
    source = (source or "").lower()
    if source == "yahoo" or (isinstance(raw, dict) and "yahoo" in raw):
        payload = raw.get("yahoo", raw) if isinstance(raw, dict) else {}
        return normalize_yahoo_settings(payload)
    return normalize_sleeper_settings(raw)


def _walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)
