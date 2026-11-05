"""Exclude recorded injury absences, never turn missed weeks into zero games."""
from django.core.cache import cache
from analyzer.models import PlayerInjuryReport, PlayerSnapCount, PlayerWeeklyStats
from leagues.services.player_availability import BLOCKED, normalize_status


def injury_absences(season):
    key = f'injury-absences:{season}'
    value = cache.get(key)
    if value is not None:
        return value
    blocked = {(r.player_id, r.week) for r in PlayerInjuryReport.objects.filter(season=season)
        if {normalize_status(r.injury_status), normalize_status(r.roster_status)} & BLOCKED}
    played = {(s.player_id, s.week) for s in PlayerSnapCount.objects.filter(season=season, offense_snaps__gt=0)}
    for row in PlayerWeeklyStats.objects.filter(season=season, season_type='REG').values(
            'player_id', 'week', 'attempts', 'carries', 'targets', 'receptions', 'completions'):
        if any((row[field] or 0) > 0 for field in ('attempts', 'carries', 'targets', 'receptions', 'completions')):
            played.add((row['player_id'], row['week']))
    value = blocked - played
    cache.set(key, value, 60)
    return value


def filter_injury_history(rows, player_id, season):
    absent = injury_absences(season)
    return [row for row in rows if (player_id, row[0]) not in absent]
