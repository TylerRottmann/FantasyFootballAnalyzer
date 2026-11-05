"""Shared, read-only player context for player cards and Assistant GM."""
import json
from copy import copy
from datetime import timedelta
from math import isfinite
from statistics import mean, pstdev

from django.utils import timezone
from django.db.models import Q

from .models import PlayerADP, PlayerInjuryReport, PlayerSnapCount, PlayerWeeklyStats, NFLGame
from .waiver_predictions import load_waiver_predictions, predict_waiver_player
from .waiver_value import load_player_values, PlayerValue
from leagues.models import FantasyProjection
from leagues.services.player_availability import injury_label, BLOCKED, normalize_status
from leagues.services.kicker_scoring import _league_kicker_projection


def number(value):
    try:
        result = float(value)
        return result if isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _saved_probability(stats, kind):
    # Accept only explicit units; a missing estimate is never a 0% estimate.
    for key, scale in ((f'{kind}_probability', 100), (f'{kind}_pct', 1)):
        value = number(stats.get(key))
        if value is not None and 0 <= value <= 100 / scale:
            return round(value * scale, 1)
    return None


def _kicker_games(player, season):
    from scripts.algorithm.features.k_features import DATA_PATH
    try:
        payload = json.loads(DATA_PATH.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return []
    if payload.get('schema_version') != 2:
        return []
    return [dict(game) for game in payload.get('games', [])
        if game.get('player_id') == player.pk and game.get('season') == season]


def _games(player, season, through_week, scoring_settings=None):
    if player.position == 'K':
        from scripts.algorithm.k.scoring import score_kicking
        games = _kicker_games(player, season)
        for game in games:
            try:
                game['fantasy_points_ppr'] = score_kicking(game, scoring_settings or {})
            except (TypeError, ValueError):
                game['fantasy_points_ppr'] = None
    else:
        games = list(PlayerWeeklyStats.objects.filter(player_id=player.pk, season=season,
            season_type__iexact='REG', week__lte=through_week).order_by('-week').values())
    return sorted((game for game in games if game['week'] <= through_week), key=lambda g: g['week'], reverse=True)


def _consistency(games, injury_reports, snaps):
    scores = []
    for game in games:
        report = injury_reports.get(game['week'])
        played_snaps = snaps.get(game['week'])
        participated = bool(played_snaps and played_snaps.offense_snaps > 0) or any(game.get(key) for key in ('attempts', 'carries', 'targets', 'fg_att', 'pat_att'))
        if report and not participated and {normalize_status(report.injury_status), normalize_status(report.roster_status)} & BLOCKED:
            continue
        points = number(game.get('fantasy_points_ppr'))
        if points is not None:
            scores.append(points)
        if len(scores) == 6:
            break
    average = mean(scores) if scores else None
    if len(scores) < 4:
        label = 'Still evaluating'
    elif average is None or average <= 0:
        label = 'Scoring varies'
    else:
        variation = pstdev(scores) / average
        label = 'Steady scoring' if variation <= .35 else 'Scoring varies' if variation >= .70 else 'Some ups and downs'
    return {'label': label, 'games': len(scores), 'average': average,
        'low': min(scores) if scores else None, 'high': max(scores) if scores else None}


def build_player_profile(player, league, week, history_season=None):
    today = timezone.localdate()
    season = league.season if league and league.season else today.year - (today.month <= 2)
    history_season = history_season or season
    values = load_player_values(season, week)
    value = values.get(player.pk, PlayerValue())
    forecasts = load_waiver_predictions([player.pk], league, week) if league else {}
    saved = list(FantasyProjection.objects.select_related('player').filter(player_id=player.pk, season=season,
        model_version='v1', week__gte=1, week__lte=18).order_by('week'))
    by_week = {row.week: row for row in saved}
    current = by_week.get(week)
    stats = current.projected_stats if current and isinstance(current.projected_stats, dict) else {}
    games = list(NFLGame.objects.filter(season=season, game_type='REG')
        .filter(Q(home_team_id=player.team_id) | Q(away_team_id=player.team_id))
        .select_related('home_team', 'away_team')) if player.team_id else []
    matchups = {g.week: ('vs ' + g.away_team.abbreviation if g.home_team_id == player.team_id else '@ ' + g.home_team.abbreviation) for g in games}
    bye_weeks = set(range(1, 19)) - set(matchups) if len(matchups) == 17 else set()
    invalid_byes = {w for w, row in by_week.items() if row.status == 'bye' and w in matchups}
    for w in invalid_byes:
        forecasts.pop((player.pk, w), None)
    prediction = predict_waiver_player(player, league, week, forecasts)
    weekly = []
    for w in range(week, 19):
        row = by_week.get(w)
        weekly.append({'week': w, 'points': forecasts.get((player.pk, w)),
            'opponent': matchups.get(w) or ('BYE' if (row and row.status == 'bye') or w in bye_weeks else '—'),
            'status': row.status.replace('_', ' ').capitalize() if row else 'No saved prediction',
            'stats': [{'label': key.replace('_', ' ').capitalize(), 'value': val} for key, val in (row.projected_stats or {}).items()
                if not key.startswith('_') and number(val) is not None] if row and isinstance(row.projected_stats, dict) else []})
    reports = list(PlayerInjuryReport.objects.filter(player_id=player.pk, season=season, week__lte=week).order_by('-week'))
    active_history = _games(player, season, week - 1, getattr(league, 'scoring_settings', {}))
    active_snaps = {s.week: s for s in PlayerSnapCount.objects.filter(player_id=player.pk, season=season, week__lt=week)}
    consistency = _consistency(active_history, {r.week: r for r in reports}, active_snaps)
    history = active_history if history_season == season else _games(player, history_season, 18, getattr(league, 'scoring_settings', {}))
    snaps = active_snaps if history_season == season else {s.week: s for s in PlayerSnapCount.objects.filter(player_id=player.pk, season=history_season, week__lte=18)}
    columns = [('fantasy_points_ppr', 'PPR pts'), ('carries', 'Carries'), ('rushing_yards', 'Rush yds'), ('rushing_tds', 'Rush TD'),
        ('targets', 'Targets'), ('receptions', 'Catches'), ('receiving_yards', 'Rec yds'), ('receiving_tds', 'Rec TD')]
    if player.position == 'QB':
        columns = [('fantasy_points_ppr', 'PPR pts'), ('completions', 'Comp'), ('attempts', 'Attempts'), ('passing_yards', 'Pass yds'),
            ('passing_tds', 'Pass TD'), ('passing_interceptions', 'INT'), ('carries', 'Carries'), ('rushing_yards', 'Rush yds'), ('rushing_tds', 'Rush TD')]
    elif player.position == 'K':
        columns = [('fantasy_points_ppr', 'Points'), ('fg_made', 'FG made'), ('fg_att', 'FG att'), ('fg_missed', 'FG missed'), ('pat_made', 'XP made'), ('pat_missed', 'XP missed')]
    for game in history:
        game['cells'] = [number(game.get(key)) for key, label in columns]
        snap = snaps.get(game['week'])
        game['snap_share'] = snap.offense_share * 100 if snap else None
        game['snaps'] = snap.offense_snaps if snap else None
        shown = {key for key, label in columns} | {'id', 'player_id', 'season', 'week', 'cells', 'snap_share', 'snaps'}
        game['details'] = [{'label': field.replace('_', ' ').capitalize(), 'value': number(val)}
            for field, val in game.items() if field not in shown and number(val) is not None]
    actual_by_week = {game['week']: game for game in history}
    projected_by_week = {row['week']: row for row in weekly} if history_season == season else {}
    history_saved = saved if history_season == season else list(FantasyProjection.objects.select_related('player').filter(
        player_id=player.pk, season=history_season, model_version='v1', week__gte=1, week__lte=18))
    history_by_week = {row.week: row for row in history_saved}
    for row in history_saved:
        if history_season == season and row.week >= week:
            continue
        # Past forecasts stay as saved; today's injuries and role changes must not rewrite them.
        scored = _league_kicker_projection(row, league) if league and player.position == 'K' else row
        valid = (scored.status in ('ml_model', 'projected', 'bye', 'inactive', 'injury_out', 'qb_backup')
            and not (history_season == season and row.week in invalid_byes))
        projected_by_week[row.week] = {'points': number(scored.projected_fantasy_points) if league and valid else None,
            'opponent': 'BYE' if row.status == 'bye' else '—',
            'stats': [{'label': key.replace('_', ' ').capitalize(), 'value': val}
                for key, val in (row.projected_stats or {}).items() if not key.startswith('_') and number(val) is not None]
                if isinstance(row.projected_stats, dict) else []}
    season_weeks = []
    for w in range(1, 19):
        actual = actual_by_week.get(w)
        projected = projected_by_week.get(w)
        actual_stats = ([{'label': label, 'value': cell} for (key, label), cell in zip(columns[1:], actual['cells'][1:])]
            + [{'label': 'Snaps', 'value': actual['snaps']}, {'label': 'Playing time %', 'value': actual['snap_share']}]
            + actual['details']) if actual else []
        saved_row = history_by_week.get(w)
        opponent = (actual.get('opponent_team') if actual else None) or (matchups.get(w) if history_season == season else None)
        if opponent == 'LA':
            opponent = 'LAR'
        is_bye = not opponent and ((saved_row and saved_row.status == 'bye') or (history_season == season and w in bye_weeks))
        if actual and saved_row and saved_row.status == 'bye' and projected:
            projected = {**projected, 'points': None}
        season_weeks.append({'week': w,
            'opponent': 'BYE' if is_bye else opponent or (projected['opponent'] if projected else '—'),
            'actual_points': number(actual.get('fantasy_points_ppr')) if actual else None,
            'projected_points': projected['points'] if projected else None,
            'actual_stats': actual_stats, 'projected_stats': projected['stats'] if projected else []})
    stat_columns = list(dict.fromkeys((kind, stat['label']) for row in season_weeks
        for kind in ('actual_stats', 'projected_stats') for stat in row[kind]))
    for row in season_weeks:
        stat_values = {(kind, stat['label']): stat['value'] for kind in ('actual_stats', 'projected_stats') for stat in row[kind]}
        row['stat_cells'] = [stat_values.get(column) for column in stat_columns]
    season_stat_columns = [('Projected ' if kind == 'projected_stats' else '') + label for kind, label in stat_columns]
    seasons = set(PlayerWeeklyStats.objects.filter(player_id=player.pk, season__lte=season).values_list('season', flat=True))
    if player.position == 'K':
        from scripts.algorithm.features.k_features import DATA_PATH
        try:
            seasons |= {g['season'] for g in json.loads(DATA_PATH.read_text(encoding='utf-8')).get('games', []) if g.get('player_id') == player.pk and g['season'] <= season}
        except (OSError, ValueError):
            pass
    seasons.add(season)
    summaries = {
        'long': 'His current role supports holding him for the rest of this season.',
        'short': 'His opportunity may shrink when an injured regular returns.',
        'fading': 'His playing time and workload are falling, which lowers his appeal as a hold.',
        'unknown': 'There is not enough current role information to judge how long his value will last.',
    }
    summary = summaries[value.horizon]
    if value.category in {'long', 'declining', 'uneven'}:
        summary += ' ' + value.short_reason
    if consistency['average'] is not None:
        summary += f' He averaged {consistency["average"]:.1f} points over his last {consistency["games"]} recorded games.'
    if consistency['games'] >= 4:
        summary += ' ' + consistency['label'] + '.'
    injury_player = copy(player)
    now = timezone.now()
    fresh_report = next((r for r in reports if r.week == week and now - timedelta(days=7) <= r.observed_at <= now), None)
    if fresh_report:
        injury_player.injury_status = fresh_report.injury_status
        injury_player.status = fresh_report.roster_status
    label = injury_label(injury_player)
    if label:
        summary += f' Listed injury status: {label}.'
    if not league:
        summary += ' Connect a league to see projections and scoring context.'
    profile = {
        'player': {'id': player.pk, 'name': player.full_name, 'position': player.position, 'age': player.age,
            'team': player.team.abbreviation if player.team else None, 'team_name': player.team.name if player.team else None,
            'headshot_url': player.headshot_url, 'initials': ''.join(part[0] for part in (player.full_name or '').split()[:2]),
            'injury': label, 'status': player.status, 'updated_at': player.updated_at.isoformat() if player.updated_at else None},
        'season': season, 'week': week, 'history_season': history_season, 'history_seasons': sorted(seasons, reverse=True),
        'weekly_points': prediction.this_week, 'rest_of_season': prediction.rest_of_season,
        'boom_pct': _saved_probability(stats, 'boom'), 'bust_pct': _saved_probability(stats, 'bust'),
        'value': {'horizon': value.horizon, 'label': value.value_label, 'trend': value.short_label, 'reason': value.reason},
        'summary': summary, 'consistency': consistency, 'projections': weekly, 'game_log': history, 'season_weeks': season_weeks,
        'season_stat_columns': season_stat_columns,
        'game_columns': [label for key, label in columns],
        'facts': [{'label': label, 'value': getattr(player, key) if getattr(player, key) not in (None, '') else None} for key, label in [('years_exp', 'Experience'),
            ('jersey_number', 'Jersey'), ('height', 'Height'), ('weight', 'Weight'), ('college', 'College'), ('owned_percentage', 'Rostered %')]],
        'adp': [{'format': a.get_scoring_format_display(), 'value': float(a.adp), 'source': a.source, 'updated_at': a.updated_at.isoformat()} for a in PlayerADP.objects.filter(player_id=player.pk, season=season)],
        'injuries': [{'week': r.week, 'status': r.injury_status or r.roster_status or 'No injury listed', 'depth': r.depth_order,
            'source': r.source, 'observed_at': r.observed_at.isoformat()} for r in reports],
        'projections_updated': current.updated_at.isoformat() if current else None,
        'scoring_note': 'Kicker points follow league scoring.' if player.position == 'K' else 'Game logs and skill-position models use PPR points.',
    }
    facts = {fact['label']: fact['value'] for fact in profile['facts']}
    header_facts = []
    for key in ('Height', 'Weight', 'Rostered %'):
        display = facts[key]
        numeric = number(display)
        if key == 'Height' and numeric is not None and numeric.is_integer() and 48 <= numeric <= 100:
            display = f'{int(numeric) // 12}′{int(numeric) % 12}″'
        elif key == 'Weight' and numeric is not None:
            display = f'{numeric:g} lb'
        elif key == 'Rostered %' and numeric is not None:
            display = f'{numeric:g}%'
        header_facts.append({'label': 'Rostered' if key == 'Rostered %' else key, 'value': display})
    profile['header_facts'] = header_facts
    return profile


def profile_overview_text(profile, include_estimates=False):
    """The chatbot uses the same overview and numbers displayed in the card."""
    parts = [profile['player']['name'] + ': ' + profile['summary']]
    weekly = profile['weekly_points']
    season = profile['rest_of_season']
    parts.append(f'Week {profile["week"]}: {weekly:.1f} projected points.' if weekly is not None else f'Week {profile["week"]} projection is unavailable.')
    parts.append(f'Rest of season: {season:.1f} projected points.' if season is not None else 'Rest-of-season total is unavailable; forecasts may be incomplete or the role/return timing uncertain.')
    if include_estimates:
        for kind in ('boom', 'bust'):
            value = profile[kind + '_pct']
            parts.append(f'{kind.capitalize()}: {value:.1f}% (saved estimate).' if value is not None else f'{kind.capitalize()} estimate is unavailable.')
    return '\n'.join(parts)
