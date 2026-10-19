# scripts/algorithm/dst/scoring.py
#
# Single source of truth for D/ST fantasy scoring. Used by the import
# script (to fill team_weekly_stats.dst_fantasy_points) and by tests.
#
# Standard Sleeper-style D/ST scoring. Change the constants here if the
# app should target a different platform default, then re-run
# load_dst_stats.py so the stored column is recomputed.
#
# Not modeled (not in the data source): blocked kicks, return yardage
# bonuses, and defensive/ST TDs scored against the team (the real
# "points allowed" stat excludes those, ours uses full points_against).

SACK = 1.0
INTERCEPTION = 2.0
FUMBLE_RECOVERY = 2.0
SAFETY = 2.0
TOUCHDOWN = 6.0  # defensive + special teams TDs


def points_allowed_score(points_allowed):
    if points_allowed is None:
        return 0.0
    p = float(points_allowed)
    if p <= 0:
        return 10.0
    if p <= 6:
        return 7.0
    if p <= 13:
        return 4.0
    if p <= 20:
        return 1.0
    if p <= 27:
        return 0.0
    if p <= 34:
        return -1.0
    return -4.0


def dst_fantasy_points(
    sacks=0,
    interceptions=0,
    fumble_recoveries=0,
    safeties=0,
    touchdowns=0,
    points_allowed=None,
):
    def n(value):
        return float(value) if value is not None else 0.0

    return (
        n(sacks) * SACK
        + n(interceptions) * INTERCEPTION
        + n(fumble_recoveries) * FUMBLE_RECOVERY
        + n(safeties) * SAFETY
        + n(touchdowns) * TOUCHDOWN
        + points_allowed_score(points_allowed)
    )
