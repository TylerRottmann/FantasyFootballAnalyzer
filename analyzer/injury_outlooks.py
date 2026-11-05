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
    result=set()
    if records:
        for player in Players.objects.filter(sleeper_id__in=records):
            effective=records[str(player.sleeper_id)]['effective_week']
            # Actual participation contradicts an old season-ending report.
            played=PlayerSnapCount.objects.filter(player_id=player.pk,season=season,
                week__gte=effective,week__lt=week,offense_snaps__gt=0).exists()
            if not played:
                played=PlayerWeeklyStats.objects.filter(player_id=player.pk,season=season,
                    season_type='REG',week__gte=effective,week__lt=week).filter(
                    Q(attempts__gt=0)|Q(carries__gt=0)|Q(targets__gt=0)).exists()
            if not played:
                result.add(player.pk)
    cache.set(key,result,60)
    return result
