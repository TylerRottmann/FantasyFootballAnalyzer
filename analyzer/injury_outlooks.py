"""Reviewed return timelines supplement status-only injury feeds.

IR alone does not establish a season-ending absence. Each timeline needs a
source and a season/week boundary; records are data, not player-specific rules.
"""
import json
import logging
from pathlib import Path
from datetime import date
from django.core.cache import cache
from django.db.models import Q
from django.utils import timezone
from .models import Players, PlayerWeeklyStats, PlayerSnapCount

logger = logging.getLogger(__name__)
TIMELINE_PATH = Path(__file__).with_name('data') / 'injury_timelines.json'


def _load_timelines():
    try:
        rows = json.loads(TIMELINE_PATH.read_text(encoding='utf-8'))
        if not isinstance(rows,list):
            raise ValueError('Timeline file must contain a list.')
        return rows
    except (OSError, ValueError):
        logger.warning('Reviewed injury timelines are unavailable; no season-ending absence assumed.')
        return []


def season_ending_player_ids(season, week):
    key=f'season-ending:{season}:{week}'
    result=cache.get(key)
    if result is not None:
        return result
    records={}
    today=timezone.localdate()
    for row in _load_timelines():
        try:
            if (row['season'] == season and row['status']=='out_for_season'
                and 1 <= row['effective_week'] <= week <= 18
                and date.fromisoformat(row['verified_on']) <= today
                and row['source_url'].startswith('https://')):
                records[str(row['sleeper_id'])]=row
        except (KeyError, TypeError, ValueError, AttributeError):
            logger.warning('Invalid reviewed injury timeline ignored.')
    players = list(Players.objects.filter(sleeper_id__in=records).values_list('id', 'sleeper_id')) if records else []
    effective_weeks = {
        player_id: records[str(sleeper_id)]['effective_week']
        for player_id, sleeper_id in players
    }
    player_ids = set(effective_weeks)
    played_ids = set()
    if player_ids:
        first_effective_week = min(effective_weeks.values())
        snap_rows = PlayerSnapCount.objects.filter(
            player_id__in=player_ids,
            season=season,
            week__gte=first_effective_week,
            week__lt=week,
            offense_snaps__gt=0,
        ).values_list('player_id', 'week')
        for player_id, played_week in snap_rows:
            if played_week >= effective_weeks[player_id]:
                played_ids.add(player_id)

        # Fall back to stat participation where no positive snap record exists.
        remaining_ids = player_ids - played_ids
        if remaining_ids:
            stat_rows = PlayerWeeklyStats.objects.filter(
                player_id__in=remaining_ids,
                season=season,
                season_type='REG',
                week__gte=first_effective_week,
                week__lt=week,
            ).filter(Q(attempts__gt=0) | Q(carries__gt=0) | Q(targets__gt=0)).values_list(
                'player_id', 'week'
            )
            for player_id, played_week in stat_rows:
                if played_week >= effective_weeks[player_id]:
                    played_ids.add(player_id)

    result = player_ids - played_ids
    cache.set(key, result, 60 * 10)
    return result
