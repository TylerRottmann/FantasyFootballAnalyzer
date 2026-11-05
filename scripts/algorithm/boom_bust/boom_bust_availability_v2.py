"""Leakage-aware availability and workload context for Boom/Bust v2."""

from datetime import datetime, timezone
from statistics import mean

from django.db import connection


def load_availability_context_v2(player_id, season, week, as_of):
    """Load information observable strictly before the prediction cutoff.

    Injury snapshots are used only when observed before as_of.
    Snap-count history excludes the target week and future weeks.
    """
    if type(player_id) is not int or player_id <= 0:
        raise ValueError("Invalid player ID.")
    if type(season) is not int or not 2000 <= season <= 2100:
        raise ValueError("Invalid season.")
    if type(week) is not int or not 1 <= week <= 18:
        raise ValueError("Invalid week.")
    if not isinstance(as_of, datetime) or as_of.tzinfo is None:
        raise ValueError("as_of must be a timezone-aware datetime.")

    cutoff = as_of.astimezone(timezone.utc)

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT injury_status, roster_status, depth_order, observed_at
            FROM analyzer_playerinjuryreport
            WHERE player_id = %s
              AND season = %s
              AND week = %s
              AND observed_at < %s
            ORDER BY observed_at DESC
            LIMIT 1
            """,
            [player_id, season, week, cutoff],
        )
        injury = cursor.fetchone()

        cursor.execute(
            """
            SELECT week, offense_share
            FROM analyzer_playersnapcount
            WHERE player_id = %s
              AND season = %s
              AND week < %s
              AND imported_at IS NOT NULL
              AND imported_at < %s
              AND offense_share BETWEEN 0 AND 1
            ORDER BY week DESC
            LIMIT 8
            """,
            [player_id, season, week, cutoff],
        )
        snaps = cursor.fetchall()

    shares = [float(share) for _, share in snaps]
    recent_3 = shares[:3]
    recent_8 = shares[:8]

    return {
        "injury_status": injury[0] if injury else None,
        "roster_status": injury[1] if injury else None,
        "depth_order": injury[2] if injury else None,
        "injury_observed_at": (
            injury[3].isoformat() if injury else None
        ),
        "snap_history_count": len(shares),
        "snap_share_l3": (
            round(mean(recent_3), 4) if recent_3 else None
        ),
        "snap_share_l8": (
            round(mean(recent_8), 4) if recent_8 else None
        ),
        "snap_share_trend_l3_l8": (
            round(mean(recent_3) - mean(recent_8), 4)
            if recent_3 and recent_8 else None
        ),
        "limited_snap_history": int(len(shares) < 3),
    }
