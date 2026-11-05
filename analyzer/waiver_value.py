"""Explainable role trends; thresholds are rules, not trained probabilities."""
from collections import defaultdict
from dataclasses import dataclass, replace
from statistics import mean
from datetime import timedelta
from django.core.cache import cache
from django.utils import timezone
from .models import PlayerSnapCount, PlayerInjuryReport, PlayerWeeklyStats
from .injury_outlooks import season_ending_player_ids
from leagues.services.player_availability import BLOCKED, normalize_status


@dataclass(frozen=True)
class PlayerValue:
    category: str = 'unknown'
    label: str = 'Not enough evidence'
    reason: str = 'Need four recent games with snaps and workload, plus depth and injury context.'
    multiplier: float = 1.0
    snap_change: float | None = None
    opportunity_change: float | None = None
    horizon: str = 'unknown'

    @property
    def value_label(self):
        return {'long': 'Long-term', 'short': 'Short-term', 'fading': 'Fading value', 'unknown': 'Unclear'}[self.horizon]

    @property
    def short_label(self):
        return {'long': 'Growing role', 'short': 'Growing role', 'declining': 'Losing work',
                'neutral': 'Steady role', 'uneven': 'Uneven usage', 'unknown': 'Still evaluating'}[self.category]

    @property
    def short_reason(self):
        return {'long': 'Earning a bigger role.', 'short': 'Could be filling in for an injured teammate.',
                'declining': 'Getting less playing time and fewer opportunities.', 'neutral': 'No clear change in role yet.',
                'uneven': 'Playing time and opportunities vary from week to week.',
                'unknown': 'We need more recent information to judge this player.'}[self.category]


def _classify_trend(games, *, injured_ahead=False, healthy_context=False, competitor_growing=False):
    # Compare the latest two games with up to four earlier games. A single
    # quiet game must not erase a sustained workload change.
    games = games[-6:]
    if len(games) < 4 or any(g.get('share') is None or g.get('opportunities') is None for g in games[-2:]):
        return PlayerValue()
    games = [g for g in games if g.get('share') is not None and g.get('opportunities') is not None]
    if len(games) < 4:
        return PlayerValue()
    if games[-1]['week'] - games[0]['week'] > 7:
        return PlayerValue(reason='The available games are too far apart to infer a current role trend.')
    old, recent = games[:-2], games[-2:]
    snaps = mean(g['share'] for g in recent) - mean(g['share'] for g in old)
    workload = mean(g['opportunities'] for g in recent) - mean(g['opportunities'] for g in old)
    baseline = mean(g['opportunities'] for g in old)
    threshold = max(1, baseline * 0.2)
    # Both recent games should support the trend; allow ordinary game-to-game noise.
    rising = snaps >= 0.05 and workload >= threshold and min(g['opportunities'] for g in recent) >= baseline * 0.75
    falling = snaps <= -0.05 and workload <= -threshold and max(g['opportunities'] for g in recent) <= baseline * 1.25
    change = f'Snap share {snaps * 100:+.0f} percentage points; workload {workload:+.1f} per game (last two vs prior {len(old)}).'
    if rising and injured_ahead:
        return PlayerValue('short', 'Short-term opportunity', change + ' A player ahead on the depth chart is unavailable; this may be temporary.', 1.05, snaps, workload)
    if rising:
        context = ' No current injury replacement was identified.' if healthy_context else ' Injury context is incomplete; lasting value is not certain.'
        return PlayerValue('long', 'Growing role', change + context, 1.10, snaps, workload)
    rebound = (recent[-1]['share'] - recent[-2]['share'] >= 0.10
               and recent[-1]['share'] >= mean(g['share'] for g in old) - 0.05)
    recent_four = games[-4:]
    fluctuating = (max(g['share'] for g in recent_four) - min(g['share'] for g in recent_four) >= 0.20
                   and max(g['opportunities'] for g in recent_four) - min(g['opportunities'] for g in recent_four)
                   >= max(3, mean(g['opportunities'] for g in recent_four) * 0.5))
    if (falling and rebound) or (not falling and fluctuating):
        return PlayerValue('uneven', 'Uneven usage', change + ' Recent playing time has rebounded or varied substantially; a lasting decline is not established.', 1.0, snaps, workload)
    if falling:
        context = ' A teammate at the same position is gaining work.' if competitor_growing else ' The player is seeing less playing time and fewer opportunities.'
        return PlayerValue('declining', 'Losing role', change + context, 0.90, snaps, workload)
    return PlayerValue('neutral', 'No clear value signal', change + ' The evidence does not establish a lasting gain or loss.', 1.0, snaps, workload)


def classify_value(games, *, injured_ahead=False, healthy_context=False, competitor_growing=False, position='WR'):
    trend = _classify_trend(games, injured_ahead=injured_ahead,
        healthy_context=healthy_context, competitor_growing=competitor_growing)
    valid = [g for g in games[-6:] if g.get('share') is not None and g.get('opportunities') is not None]
    if not valid or valid[-1]['week'] - valid[0]['week'] > 7:
        return trend
    recent = valid[-2:]
    meaningful = mean(g['opportunities'] for g in recent) >= 2 and mean(g['share'] for g in recent) >= .25
    # Duration is separate from direction: a replacement can be steady or rising.
    if injured_ahead and meaningful:
        return replace(trend, horizon='short', multiplier=1.05 if trend.category in ('long','short') else trend.multiplier,
            reason=trend.reason + ' Pickup value depends on a regular being absent; it may shrink when he returns.')
    if healthy_context and trend.category == 'declining':
        return replace(trend, horizon='fading')
    role_floor = {'RB': 8, 'WR': 4, 'TE': 3}.get(position)
    established = (role_floor is not None and len(valid) >= 4
        and mean(g['share'] for g in valid[-3:]) >= .50
        and mean(g['opportunities'] for g in valid[-3:]) >= role_floor
        and min(g['opportunities'] for g in valid[-3:]) >= role_floor * .5)
    if healthy_context and (trend.category == 'long' or established) and trend.category != 'declining':
        return replace(trend, horizon='long')
    # Missing injury context cannot establish that a growing role will last.
    return replace(trend, multiplier=1.0 if trend.category in ('long','short') else trend.multiplier)


def injury_dependent_role(report, teammates, histories, season_ending_ids=frozenset()):
    """Recognize returning regulars even when current depth order changed or they are questionable."""
    if not report:
        return False
    own = [g for g in histories.get(report.player_id, []) if g['team_id'] == report.team_id and g['opportunities'] is not None]
    for other in teammates:
        if other.player_id in season_ending_ids:
            continue
        statuses = {normalize_status(other.injury_status), normalize_status(other.roster_status)}
        theirs = [g for g in histories.get(other.player_id, []) if g['team_id'] == report.team_id and g['opportunities'] is not None and (g['share'] or 0) > 0]
        higher_depth = bool(report.depth_order and other.depth_order and other.depth_order < report.depth_order)
        prior_lead = False
        if len(theirs) >= 2:
            last_played = theirs[-1]['week']
            overlap = [g for g in own if g['week'] <= last_played]
            if overlap:
                prior_lead = (mean(g['opportunities'] for g in theirs[-3:]) >= mean(g['opportunities'] for g in overlap[-3:]) * 1.2 + 1
                    and mean(g['share'] for g in theirs[-3:]) > mean(g['share'] for g in overlap[-3:]))
        if not (higher_depth or prior_lead):
            continue
        if statuses & BLOCKED:
            return True
        if not statuses & {'QUESTIONABLE'} and not (higher_depth and prior_lead):
            continue
        # Questionable alone does not mean absent. Require missed team games
        # and a subsequent increase in the replacement's work. A returning
        # regular still creates duration risk after his injury label clears.
        if theirs:
            last_played = theirs[-1]['week']
            after = [g for g in own if g['week'] > last_played]
            before = [g for g in own if g['week'] <= last_played]
            if len(after) >= 2 and before and mean(g['opportunities'] for g in after[-2:]) >= max(2, mean(g['opportunities'] for g in before[-3:]) * 1.2):
                return True
    return False


def classify_quarterback_value(report, teammates, season_ending_ids=frozenset(), *, injury_dependency=False):
    if not report or not report.team_id or not report.depth_order:
        return PlayerValue(reason='A current quarterback depth chart is needed.')
    own_status = {normalize_status(report.injury_status), normalize_status(report.roster_status)}
    if own_status & BLOCKED:
        return PlayerValue(reason='The quarterback is unavailable; return timing needs confirmation.')
    ahead = [r for r in teammates if r.depth_order and r.depth_order < report.depth_order]
    if any(not ({normalize_status(r.injury_status), normalize_status(r.roster_status)} & BLOCKED)
           and r.player_id not in season_ending_ids for r in ahead):
        return PlayerValue(reason='A quarterback ahead on the depth chart is available.')
    if injury_dependency or any(r.player_id not in season_ending_ids for r in ahead):
        return PlayerValue('neutral', 'Temporary starting role',
            'The starting opportunity depends on an injured quarterback being absent.', horizon='short')
    if report.depth_order == 1 or ahead:
        return PlayerValue('neutral', 'Established starting role',
            'The current depth chart supports a starting role for the remaining season.', horizon='long')
    return PlayerValue(reason='The starting quarterback situation is not confirmed.')


def quarterback_injury_dependency(report, teammates, histories, season_ending_ids, prior_starter_ids):
    if report.depth_order == 1:
        # Earlier starts can belong to a backup who filled in for today's QB1.
        # Require a previously recorded QB1 who is actually ruled out before
        # calling today's QB1 an injury replacement.
        teammates = [r for r in teammates if r.player_id in prior_starter_ids
            and {normalize_status(r.injury_status), normalize_status(r.roster_status)} & BLOCKED]
    return injury_dependent_role(report, teammates, histories, season_ending_ids)


def load_player_values(season, week):
    key = f'player-values:{season}:{week}'
    cached = cache.get(key)
    if cached is not None:
        return cached
    snaps = list(PlayerSnapCount.objects.filter(season=season, week__lt=week, week__gte=max(1, week-8)).order_by('week'))
    reports = list(PlayerInjuryReport.objects.filter(season=season, week__lte=week, week__gte=max(1, week-5)))
    by_report = {(r.player_id, r.week): r for r in reports}
    cutoff = timezone.now() - timedelta(days=7)
    current = {r.player_id: r for r in reports if r.week == week and cutoff <= r.observed_at <= timezone.now()}
    stats = {(s.player_id, s.week): s for s in PlayerWeeklyStats.objects.filter(season=season, season_type='REG', week__lt=week, week__gte=max(1, week-8))} if snaps else {}
    histories = defaultdict(list)
    teams = {}
    for snap in snaps:
        report = by_report.get((snap.player_id, snap.week))
        if report and {normalize_status(report.injury_status), normalize_status(report.roster_status)} & BLOCKED and snap.offense_snaps == 0:
            continue
        stat = stats.get((snap.player_id, snap.week))
        # Zero offensive snaps are not proof of an injury; missing stats remain unknown.
        is_qb = current.get(snap.player_id) and current[snap.player_id].position == 'QB'
        workload = (stat.attempts if is_qb else stat.targets) if stat else None
        opportunities = None if stat is None or workload is None or stat.carries is None else workload + stat.carries
        histories[snap.player_id].append({'week': snap.week, 'share': snap.offense_share, 'opportunities': opportunities, 'team_id': snap.team_id})
        teams[snap.player_id] = snap.team_id
    season_ending_ids = season_ending_player_ids(season, week)
    prior_starter_ids = {r.player_id for r in reports if r.position == 'QB' and r.depth_order == 1 and r.week < week}
    results = {}
    for player_id, games in histories.items():
        games = [g for g in games if g['team_id'] == teams[player_id]]
        report = current.get(player_id)
        if report and report.position == 'QB':
            teammates = [r for r in current.values() if r.player_id != player_id and r.team_id == report.team_id and r.position == 'QB']
            dependency = quarterback_injury_dependency(report, teammates, histories, season_ending_ids, prior_starter_ids)
            results[player_id] = classify_quarterback_value(report, teammates, season_ending_ids, injury_dependency=dependency)
            continue
        if not games or games[-1]['week'] < week-2:
            results[player_id] = PlayerValue(reason='Playing-time data is too old for this week.')
            continue
        teammates = [r for r in current.values() if report and r.player_id != player_id and r.team_id == report.team_id and r.position == report.position]
        injured_ahead = injury_dependent_role(report, teammates, histories, season_ending_ids)
        # Current reports identify known temporary injury replacements. Missing
        # historical injury captures do not hide an observable workload trend.
        healthy = bool(report and report.depth_order and teammates and not injured_ahead
            and not ({normalize_status(report.injury_status), normalize_status(report.roster_status)} & BLOCKED))
        competitor = any(classify_value(histories.get(r.player_id, []), healthy_context=True).category == 'long' for r in teammates)
        results[player_id] = classify_value(games, injured_ahead=injured_ahead, healthy_context=healthy, competitor_growing=competitor, position=report.position if report else '')
    for report in current.values():
        if report.position == 'QB' and report.player_id not in results:
            teammates = [r for r in current.values() if r.player_id != report.player_id and r.team_id == report.team_id and r.position == 'QB']
            dependency = quarterback_injury_dependency(report, teammates, histories, season_ending_ids, prior_starter_ids)
            results[report.player_id] = classify_quarterback_value(report, teammates, season_ending_ids, injury_dependency=dependency)
    cache.set(key, results, 60)
    return results
