"""Prior-season role and position priors for sparse current-season histories."""
from functools import lru_cache

from scripts.algorithm.features.qb_features import get_connection


PLAYER_PRIOR_FEATURE_NAMES = (
    "prior_season_games",
    "prior_season_ppr_points",
    "prior_season_targets",
    "prior_season_carries",
    "prior_season_snap_share",
    "prior_season_is_player_history",
    "team_changed_since_prior_season",
    "position_prior_avg_ppr_points",
    "position_prior_avg_targets",
    "position_prior_avg_carries",
    "position_prior_avg_snap_share",
)


@lru_cache(maxsize=32)
def _position_priors(season, position):
    """Cache a season/position fallback; only past-season rows are queried."""
    query = """
        SELECT AVG(pws.fantasy_points_ppr), AVG(pws.targets), AVG(pws.carries),
               AVG(opp.offense_snap_share)
        FROM player_weekly_stats pws
        JOIN players p ON p.id = pws.player_id
        LEFT JOIN player_weekly_opportunity_stats opp
          ON opp.player_id = pws.player_id AND opp.season = pws.season AND opp.week = pws.week
        WHERE pws.season = %s AND pws.season_type = 'REG' AND p.position = %s
    """
    with get_connection().cursor() as cur:
        cur.execute(query, (season, position))
        row = cur.fetchone()
    return tuple(None if value is None else float(value) for value in row)


@lru_cache(maxsize=16384)
def _player_priors(player_id, prior_season, position, current_team_id):
    query = """
        SELECT COUNT(*), AVG(pws.fantasy_points_ppr), AVG(pws.targets), AVG(pws.carries),
               AVG(opp.offense_snap_share),
               (SELECT own.team_id
                FROM player_weekly_stats past
                JOIN teams opponent
                  ON opponent.abbreviation = CASE WHEN past.opponent_team = 'LA' THEN 'LAR'
                                                  ELSE past.opponent_team END
                JOIN team_weekly_stats own
                  ON own.season = past.season AND own.week = past.week
                 AND own.season_type = 1 AND own.opponent_team_id = opponent.id
                WHERE past.player_id = %s AND past.season = %s
                  AND past.season_type = 'REG'
                ORDER BY past.week DESC LIMIT 1)
        FROM player_weekly_stats pws
        LEFT JOIN player_weekly_opportunity_stats opp
          ON opp.player_id = pws.player_id AND opp.season = pws.season AND opp.week = pws.week
        WHERE pws.player_id = %s AND pws.season = %s AND pws.season_type = 'REG'
    """
    with get_connection().cursor() as cur:
        cur.execute(query, (player_id, prior_season, player_id, prior_season))
        row = cur.fetchone()
    games = int(row[0] or 0)
    position_ppr, position_targets, position_carries, position_snaps = _position_priors(
        prior_season, position
    )
    values = {
        "prior_season_games": games,
        "prior_season_ppr_points": row[1] if row[1] is not None else position_ppr,
        "prior_season_targets": row[2] if row[2] is not None else position_targets,
        "prior_season_carries": row[3] if row[3] is not None else position_carries,
        "prior_season_snap_share": row[4] if row[4] is not None else position_snaps,
        "prior_season_is_player_history": int(games > 0),
        "team_changed_since_prior_season": (
            int(row[5] != current_team_id)
            if row[5] is not None and current_team_id is not None else None
        ),
        "position_prior_avg_ppr_points": position_ppr,
        "position_prior_avg_targets": position_targets,
        "position_prior_avg_carries": position_carries,
        "position_prior_avg_snap_share": position_snaps,
    }
    return values


def build_player_prior_features(player, season, current_team_id=None):
    """Blend player-specific prior usage with a position baseline for rookies."""
    return _player_priors(player.id, season - 1, player.position, current_team_id)
