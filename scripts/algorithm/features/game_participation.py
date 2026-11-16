"""Keep games a player did not really play out of his own history.

player_weekly_stats only has a row for games where a player recorded a stat, so a
missed game is not a zero. The distortions are (1) partial games, where he left
hurt, was benched, or came in for relief, and (2) team stats from games he missed.
"""

# Under half of the team's offensive snaps = not a normal game for this player.
FULL_ROLE_SNAP_SHARE = 0.5


def normalize_snap_share(value):
    """Snap share as a 0-1 fraction (tolerates 0-100 percentages); None if unknown."""
    if value is None:
        return None
    value = float(value)
    return value / 100.0 if value > 1.0 else value


def is_full_role_game(snap_share, threshold=FULL_ROLE_SNAP_SHARE):
    """True when the player had a normal role. Unknown snap share is kept, never guessed."""
    share = normalize_snap_share(snap_share)
    return share is None or share >= threshold


def drop_partial_games(rows, share_index, threshold=FULL_ROLE_SNAP_SHARE):
    """Remove history rows where the player played under `threshold` of team snaps."""
    return [row for row in rows if is_full_role_game(row[share_index], threshold)]


def restrict_to_player_weeks(team_rows, player_weeks, week_index=0, min_games=2):
    """Team-context rows only for weeks the player played.

    Falls back to every team row when too few remain (for example a starter who
    just came back), because some team context beats none.
    """
    played = set(player_weeks)
    kept = [row for row in team_rows if row[week_index] in played]
    return kept if len(kept) >= min_games else list(team_rows)


# ----------------------------------------------------------------------------
# WR / TE: judge each game against the player's OWN usual snap share.
# A flat 50% cutoff would erase normal WR3 / TE2 games, so the cutoff is relative.
# ----------------------------------------------------------------------------
RELATIVE_SNAP_FRACTION = 0.4   # under 40% of his usual snap share = shortened game
MIN_BASELINE_SHARE = 0.30      # below this he is a fringe player; swings are not injuries
MIN_BASELINE_GAMES = 3         # need this many games with a known snap share


def drop_injury_shortened_games(rows, share_index=None, fraction=RELATIVE_SNAP_FRACTION,
                                min_baseline=MIN_BASELINE_SHARE, min_games=MIN_BASELINE_GAMES,
                                *, share_key=None):
    """Remove games where the player played far fewer snaps than he normally does.

    Rows are tuples (use `share_index`) or dicts (use `share_key`). The baseline is
    the median share over the rows given (prior games only when building features, so
    nothing from the prediction week leaks in). Too little history, a fringe role, or an
    unknown share all keep the row.
    """
    if share_key is not None:
        get_share = lambda row: row.get(share_key)
    else:
        get_share = lambda row: row[share_index]
    shares = [s for s in (normalize_snap_share(get_share(row)) for row in rows) if s is not None]
    if len(shares) < min_games:
        return list(rows)
    ordered = sorted(shares)
    mid = len(ordered) // 2
    baseline = ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2
    if baseline < min_baseline:
        return list(rows)
    cutoff = baseline * fraction
    return [row for row in rows
            if normalize_snap_share(get_share(row)) is None
            or normalize_snap_share(get_share(row)) >= cutoff]


def skill_games_sql(season, player_ids):
    """(sql, params) for WR/TE training games, excluding injury-shortened ones.

    Returns the same 16 columns the training scripts already unpack. The baseline
    here is the player's full-season median: it only decides which labels to skip,
    never what a feature sees.
    """
    sql = """
        WITH base AS (
            SELECT pws.*,
                   CASE WHEN o.offense_snap_share > 1 THEN o.offense_snap_share / 100.0
                        ELSE o.offense_snap_share END AS snap
            FROM player_weekly_stats pws
            LEFT JOIN player_weekly_opportunity_stats o
              ON o.player_id = pws.player_id AND o.season = pws.season AND o.week = pws.week
            WHERE pws.season = %s
              AND pws.season_type = 'REG'
              AND pws.player_id = ANY(%s)
        ), baseline AS (
            SELECT player_id, PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY snap) AS median_snap
            FROM base
            WHERE snap IS NOT NULL
            GROUP BY player_id
            HAVING COUNT(*) >= %s
        )
        SELECT
            b.player_id,
            b.week,
            COALESCE(b.passing_yards, 0), COALESCE(b.passing_tds, 0),
            COALESCE(b.passing_interceptions, 0), COALESCE(b.passing_2pt_conversions, 0),
            COALESCE(b.carries, 0),
            COALESCE(b.rushing_yards, 0), COALESCE(b.rushing_tds, 0),
            COALESCE(b.rushing_2pt_conversions, 0),
            COALESCE(b.targets, 0), COALESCE(b.receptions, 0),
            COALESCE(b.receiving_yards, 0), COALESCE(b.receiving_tds, 0),
            COALESCE(b.receiving_2pt_conversions, 0),
            COALESCE(b.fumbles_lost, 0)
        FROM base b
        LEFT JOIN baseline m ON m.player_id = b.player_id
        WHERE b.snap IS NULL
           OR m.median_snap IS NULL
           OR m.median_snap < %s
           OR b.snap >= m.median_snap * %s
        ORDER BY b.player_id, b.week
    """
    params = (season, list(player_ids), MIN_BASELINE_GAMES, MIN_BASELINE_SHARE, RELATIVE_SNAP_FRACTION)
    return sql, params
