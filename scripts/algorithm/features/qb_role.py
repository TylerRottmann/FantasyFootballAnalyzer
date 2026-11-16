"""Usage-based starting-QB detection.

The Sleeper depth chart only covers the live week and only when a fresh report
exists. This fallback reads who has actually been taking the snaps, so backups are
also caught in future weeks and when the chart is missing or stale.
"""
import logging

logger = logging.getLogger(__name__)

RECENT_TEAM_WEEKS = 3          # look at the team's last N games with QB attempts
MIN_TEAM_WEEKS = 2             # need at least this many games to judge a role
MIN_TEAM_ATTEMPTS = 40         # ...and this many team pass attempts in the window
STARTER_MIN_RECENT_SHARE = 0.60
BACKUP_MAX_RECENT_SHARE = 0.25
BACKUP_MAX_SEASON_SHARE = 0.30  # keeps a healthy starter who just missed games from being flagged


def infer_backup(usage, player_id, week, blocked_ids=()):
    """Decide whether `player_id` is a backup behind a clear starter.

    usage: {player_id: {week: pass_attempts}} for the QBs currently on one team.
    blocked_ids: teammates currently Out/IR. If the leader is out, the backup is
    the expected starter and is never flagged.
    Returns (is_backup, detail). Conservative: any doubt returns False so a real
    starter is never zeroed.
    """
    prior = {pid: {w: a for w, a in weeks.items() if w < week and a} for pid, weeks in usage.items()}
    team_weeks = sorted({w for weeks in prior.values() for w in weeks})
    if len(team_weeks) < MIN_TEAM_WEEKS:
        return False, {"reason": "not_enough_team_games"}

    recent = team_weeks[-RECENT_TEAM_WEEKS:]
    recent_att = {pid: sum(weeks.get(w, 0) for w in recent) for pid, weeks in prior.items()}
    season_att = {pid: sum(weeks.values()) for pid, weeks in prior.items()}
    recent_total, season_total = sum(recent_att.values()), sum(season_att.values())
    if recent_total < MIN_TEAM_ATTEMPTS or season_total <= 0:
        return False, {"reason": "not_enough_team_attempts"}

    leader = max(recent_att, key=recent_att.get)
    leader_share = recent_att[leader] / recent_total
    mine_recent = recent_att.get(player_id, 0) / recent_total
    mine_season = season_att.get(player_id, 0) / season_total
    detail = {"leader_id": leader, "leader_recent_share": round(leader_share, 3),
              "recent_share": round(mine_recent, 3), "season_share": round(mine_season, 3)}

    if leader == player_id:
        return False, {**detail, "reason": "is_starter"}
    if leader_share < STARTER_MIN_RECENT_SHARE:
        return False, {**detail, "reason": "no_clear_starter"}
    if leader in blocked_ids:
        return False, {**detail, "reason": "starter_unavailable"}
    if mine_recent <= BACKUP_MAX_RECENT_SHARE and mine_season <= BACKUP_MAX_SEASON_SHARE:
        return True, {**detail, "reason": "backup_by_usage"}
    return False, {**detail, "reason": "meaningful_role"}


def load_team_qb_usage(team_id, season, week):
    """{player_id: {week: attempts}} for QBs on this team, games before `week`."""
    from analyzer.models import PlayerWeeklyStats
    from leagues.models import Player

    ids = list(Player.objects.filter(position="QB", team_id=team_id).values_list("id", flat=True))
    usage = {pid: {} for pid in ids}
    rows = PlayerWeeklyStats.objects.filter(
        player_id__in=ids, season=season, season_type="REG", week__lt=week, attempts__gt=0,
    ).values_list("player_id", "week", "attempts")
    for player_id, game_week, attempts in rows:
        usage[player_id][game_week] = int(attempts)
    return usage


def usage_based_qb_backup(player, season, week, reports=None, usage_cache=None):
    """True when usage says `player` is a backup QB who is not expected to start."""
    from django.db import DatabaseError
    from leagues.services.player_availability import BLOCKED, normalize_status

    if not getattr(player, "team_id", None):
        return False
    key = (player.team_id, season, week)
    if usage_cache is not None and key in usage_cache:
        usage = usage_cache[key]
    else:
        try:
            usage = load_team_qb_usage(player.team_id, season, week)
        except DatabaseError:
            # Fail safe: if usage can't be read, don't zero anyone on a guess.
            logger.warning("QB usage lookup failed for team %s", player.team_id, exc_info=True)
            return False
        if usage_cache is not None:
            usage_cache[key] = usage
    blocked = {
        pid for pid, report in (reports or {}).items()
        if pid in usage
        and {normalize_status(report.injury_status), normalize_status(report.roster_status)} & BLOCKED
    }
    return infer_backup(usage, player.pk, week, blocked)[0]
