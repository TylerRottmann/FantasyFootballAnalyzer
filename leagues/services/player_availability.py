"""Week-scoped injury rules. Current injuries never rewrite other weeks."""
from copy import copy
from datetime import timedelta
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from requests import RequestException
from scripts.commands.nflweek import get_current_nfl_week

BLOCKED = {'OUT', 'DOUBTFUL', 'IR', 'INJUREDRESERVE', 'PUP', 'PHYSICALLYUNABLETOPERFORM'}


def normalize_status(value):
    return ''.join(c for c in (value or '').upper() if c.isalnum())


def injury_label(player):
    injury = normalize_status(player.injury_status)
    roster = normalize_status(player.status)
    labels = {'OUT': 'Out', 'DOUBTFUL': 'Doubtful', 'IR': 'IR',
              'INJUREDRESERVE': 'IR', 'PUP': 'PUP', 'QUESTIONABLE': 'Questionable'}
    return labels.get(roster) if roster in BLOCKED else labels.get(injury, '')


def live_week(season, week):
    today = timezone.localdate()
    active_season = today.year - 1 if today.month <= 2 else today.year
    if season != active_season:
        return False
    try:
        return week == get_current_nfl_week()
    except (RequestException, KeyError, TypeError, ValueError):
        return False


def reports_for_week(season, week):
    from analyzer.models import PlayerInjuryReport
    key = f'player-reports:{season}:{week}'
    reports = cache.get(key)
    if reports is None:
        reports = {r.player_id: r for r in PlayerInjuryReport.objects.filter(season=season, week=week)}
        cache.set(key, reports, 60)
    return reports


def availability(player, season, week, reports=None):
    from analyzer.injury_outlooks import season_ending_player_ids
    season_absences = season_ending_player_ids(season, week)
    if season_absences and player.pk in season_absences:
        return 'unavailable_season', 0.0
    # Reports are current-state captures, so do not replay them on historical weeks.
    if not live_week(season, week):
        return '', 1.0
    now = timezone.now()
    reports = reports_for_week(season, week) if reports is None else reports
    report = reports.get(player.pk)
    if report is not None and now - timedelta(days=7) <= report.observed_at <= now:
        injury, roster = report.injury_status, report.roster_status
    elif (getattr(player, 'updated_at', None) is not None
          and now - timedelta(days=7) <= player.updated_at <= now):
        injury, roster = player.injury_status, player.status
    else:
        return '', 1.0
    statuses = {normalize_status(injury), normalize_status(roster)}
    if statuses & BLOCKED:
        return 'unavailable', 0.0
    if 'QUESTIONABLE' in statuses:
        return 'questionable', float(getattr(settings, 'QUESTIONABLE_PROJECTION_FACTOR', 0.8))
    return '', 1.0


def quarterback_role(player, season, week, reports=None):
    """Use fresh current-week depth reports, never today's chart for past games."""
    if player.position != 'QB' or not live_week(season, week):
        return None
    reports = reports_for_week(season, week) if reports is None else reports
    now = timezone.now()
    fresh = lambda r: now - timedelta(days=7) <= r.observed_at <= now
    own = reports.get(player.pk)
    if not own or not fresh(own) or not own.team_id or own.team_id != player.team_id:
        return None
    if not own.depth_order:
        return 'qb_uncertain'
    if own.depth_order == 1:
        return None
    ahead = [r for r in reports.values() if r.position == 'QB' and r.team_id == own.team_id
             and r.depth_order and r.depth_order < own.depth_order and fresh(r)]
    # Questionable does not announce a starting-QB change. Out/IR does.
    if any(not ({normalize_status(r.injury_status), normalize_status(r.roster_status)} & BLOCKED) for r in ahead):
        return 'qb_backup'
    return None if ahead else 'qb_uncertain'


def projection_context(season, week):
    from analyzer.waiver_value import load_player_values
    active = live_week(season, week)
    return {'reports': reports_for_week(season, week) if active else {},
            'values': load_player_values(season, week) if active else {}}


def adjusted_forecast(player, season, week, points, status, metadata=None, *, rescore=False, context=None):
    from analyzer.waiver_value import load_player_values
    metadata = dict(metadata or {})
    from analyzer.injury_outlooks import season_ending_player_ids
    season_absences = season_ending_player_ids(season, week)
    if not live_week(season, week) and (not season_absences or player.pk not in season_absences):
        return points, status, metadata
    previous = metadata.get('_context', {})
    base = points if rescore else previous.get('base_points', points)
    base_status = previous.get('base_status', status)
    label, factor = availability(player, season, week, reports=context['reports'] if context else None)
    qb_role = quarterback_role(player, season, week, reports=context['reports'] if context else None)
    values = context['values'] if context else None
    role = ((values if values is not None else load_player_values(season, week)).get(player.pk)
            if live_week(season, week) and player.position in ('RB', 'WR', 'TE') else None)
    multiplier = role.multiplier if role else 1.0
    value = base
    if base_status == 'bye':
        value = 0.0
    elif factor == 0:
        value, status = 0.0, 'injury_out'
    elif qb_role == 'qb_backup':
        value, status = 0.0, 'qb_backup'
    elif qb_role == 'qb_uncertain':
        value, status = None, 'qb_uncertain'
    elif base is not None:
        value = round(base + max(base, 0) * (multiplier * factor - 1), 2)
        status = base_status
    metadata['_context'] = {'base_points': base, 'base_status': base_status,
        'injury': label, 'injury_factor': factor, 'qb_role': qb_role, 'role_factor': multiplier,
        'role': role.category if role else 'unknown', 'reason': role.reason if role else ''}
    return value, status, metadata


def apply_availability(projection, *, rescore=False, context=None):
    result = copy(projection)
    result.projected_fantasy_points, result.status, result.projected_stats = adjusted_forecast(
        result.player, result.season, result.week, result.projected_fantasy_points,
        result.status, getattr(result, 'projected_stats', None), rescore=rescore, context=context)
    return result
