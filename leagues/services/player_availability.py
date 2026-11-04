"""Apply current and estimated injury availability to live/future projections."""
from copy import copy
from datetime import timedelta
from django.conf import settings
from django.core.cache import cache
from django.db.models import Q
from django.utils import timezone
from requests import RequestException
from scripts.commands.nflweek import get_current_nfl_week
from analyzer.injury_prediction import estimate_absence, load_duration_profiles

BLOCKED = {'OUT', 'DOUBTFUL', 'IR', 'INJUREDRESERVE', 'PUP', 'PHYSICALLYUNABLETOPERFORM'}


def normalize_status(value):
    return ''.join(c for c in (value or '').upper() if c.isalnum())


def injury_label(player):
    injury = normalize_status(player.injury_status)
    roster = normalize_status(player.status)
    labels = {'OUT': 'Out', 'DOUBTFUL': 'Doubtful', 'IR': 'IR',
              'INJUREDRESERVE': 'IR', 'PUP': 'PUP', 'QUESTIONABLE': 'Questionable'}
    return labels.get(roster) if roster in BLOCKED else labels.get(injury, '')


def active_week_for_season(season):
    today = timezone.localdate()
    active_season = today.year - 1 if today.month <= 2 else today.year
    if season != active_season:
        return None
    try:
        return get_current_nfl_week()
    except (RequestException, KeyError, TypeError, ValueError):
        return None


def live_week(season, week):
    return week == active_week_for_season(season)


def reports_for_week(season, week):
    from analyzer.models import PlayerInjuryReport
    key = f'player-reports:{season}:{week}'
    reports = cache.get(key)
    if reports is None:
        reports = {r.player_id: r for r in PlayerInjuryReport.objects.filter(season=season, week=week)}
        cache.set(key, reports, 60)
    return reports


def absence_start_weeks_for_reports(season, active_week, reports):
    """Batch prior injury reports and participation to anchor current absences."""
    from analyzer.models import PlayerInjuryReport, PlayerWeeklyStats

    key = f"absence-start-weeks:{season}:{active_week}"
    missing = object()
    cached = cache.get(key, missing)
    if cached is not missing:
        return cached

    current = {
        player_id: report
        for player_id, report in reports.items()
        if {normalize_status(report.injury_status), normalize_status(report.roster_status)} & BLOCKED
    }
    if not current:
        cache.set(key, {}, 300)
        return {}

    player_ids = list(current)
    previous_reports = PlayerInjuryReport.objects.filter(
        player_id__in=player_ids,
        season=season,
        week__lt=active_week,
    ).only("player_id", "week", "injury_status", "roster_status")
    report_by_player_week = {
        (report.player_id, report.week): report for report in previous_reports
    }
    participation_rows = PlayerWeeklyStats.objects.filter(
        player_id__in=player_ids,
        season=season,
        season_type="REG",
        week__lt=active_week,
    ).filter(
        Q(attempts__gt=0) | Q(carries__gt=0) | Q(targets__gt=0)
    ).values_list("player_id", "week")
    participation = set(participation_rows)

    starts = {}
    for player_id, report in current.items():
        start_week = report.week
        expected_week = active_week - 1
        while expected_week >= 1:
            previous = report_by_player_week.get((player_id, expected_week))
            if previous is None:
                break
            statuses = {
                normalize_status(previous.injury_status),
                normalize_status(previous.roster_status),
            }
            if not statuses.intersection(BLOCKED) or (player_id, expected_week) in participation:
                break
            start_week = expected_week
            expected_week -= 1
        starts[player_id] = start_week

    cache.set(key, starts, 300)
    return starts


def _absence_start_week(player, season, active_week, current_report):
    """Keep a continuing absence anchored to its first captured week."""
    from analyzer.models import PlayerInjuryReport, PlayerWeeklyStats

    start_week = getattr(current_report, "week", active_week)
    expected_week = active_week - 1
    if current_report is None:
        return start_week
    previous_reports = PlayerInjuryReport.objects.filter(
        player_id=player.pk,
        season=season,
        week__lt=active_week,
    ).order_by("-week")
    for previous in previous_reports:
        if previous.week != expected_week:
            break
        previous_statuses = {
            normalize_status(previous.injury_status),
            normalize_status(previous.roster_status),
        }
        if not previous_statuses.intersection(BLOCKED):
            break
        # Participation proves the previous absence ended, even if the status
        # feed was stale or contradictory that week.
        if PlayerWeeklyStats.objects.filter(
            player_id=player.pk,
            season=season,
            season_type="REG",
            week=previous.week,
        ).exists():
            break
        start_week = previous.week
        expected_week -= 1
    return start_week


def availability(player, season, week, reports=None, duration_profiles=None, absence_start_weeks=None):
    from analyzer.injury_outlooks import season_ending_player_ids
    season_absences = season_ending_player_ids(season, week)
    if season_absences and player.pk in season_absences:
        return 'unavailable_season', 0.0
    active_week = active_week_for_season(season)
    # Injury captures are current-state data: apply them to the live week and
    # future projections, never replay them against past weeks.
    if active_week is None or week < active_week:
        return '', 1.0
    now = timezone.now()
    reports = reports_for_week(season, active_week) if reports is None else reports
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
        if week == active_week or statuses.intersection(
            {'IR', 'INJUREDRESERVE', 'PUP', 'PHYSICALLYUNABLETOPERFORM'}
        ):
            return 'unavailable', 0.0
        duration_profiles = duration_profiles or load_duration_profiles()
        start_week = (absence_start_weeks or {}).get(player.pk)
        if start_week is None:
            start_week = _absence_start_week(player, season, active_week, report)
        estimate = estimate_absence(
            duration_profiles,
            position=player.position,
            injury_type=getattr(report, "injury_type", ""),
            start_week=start_week,
        )
        if estimate and week <= estimate['zero_through_week']:
            return 'unavailable_estimated', 0.0
        return '', 1.0
    if 'QUESTIONABLE' in statuses:
        if week == active_week:
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
    active_week = active_week_for_season(season)
    injury_active = active_week is not None and week >= active_week
    active = live_week(season, week)
    reports = reports_for_week(season, active_week) if injury_active else {}
    absence_starts = (
        absence_start_weeks_for_reports(season, active_week, reports)
        if injury_active else {}
    )
    return {
        'reports': reports,
        'absence_start_weeks': absence_starts,
        'duration_profiles': load_duration_profiles() if injury_active else {},
        'values': load_player_values(season, week) if active else {},
    }


def adjusted_forecast(player, season, week, points, status, metadata=None, *, rescore=False, context=None):
    from analyzer.waiver_value import load_player_values
    metadata = dict(metadata or {})
    from analyzer.injury_outlooks import season_ending_player_ids
    season_absences = season_ending_player_ids(season, week)
    active_week = active_week_for_season(season)
    injury_active = active_week is not None and week >= active_week
    if not injury_active and (not season_absences or player.pk not in season_absences):
        return points, status, metadata
    previous = metadata.get('_context', {})
    base = points if rescore else previous.get('base_points', points)
    base_status = previous.get('base_status', status)
    label, factor = availability(
        player,
        season,
        week,
        reports=context['reports'] if context else None,
        duration_profiles=context.get('duration_profiles') if context else None,
        absence_start_weeks=context.get('absence_start_weeks') if context else None,
    )
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
