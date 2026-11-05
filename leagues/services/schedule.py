"""Distinguish a confirmed regular-season bye from incomplete schedule data."""
from collections import defaultdict
from analyzer.models import NFLGame


def confirmed_bye_team_ids(season, week):
    weeks = defaultdict(set)
    for home, away, game_week in NFLGame.objects.filter(
        season=season, game_type='REG',
    ).values_list('home_team_id', 'away_team_id', 'week'):
        if 1 <= game_week <= 18:
            weeks[home].add(game_week)
            weeks[away].add(game_week)
    return {team for team, scheduled in weeks.items()
            if len(scheduled) == 17 and week not in scheduled}
