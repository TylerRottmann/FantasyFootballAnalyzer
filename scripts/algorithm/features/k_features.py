"""Earlier-game kicker production and team opportunity context."""
import json
from collections import Counter, defaultdict
from pathlib import Path
from psycopg.rows import dict_row
from scripts.algorithm.features.qb_features import average, get_connection
from scripts.algorithm.features.rb_features import RBSeasonData, normalize_team, paired_rate
from scripts.algorithm.k.feature_names import PLAYER_STATS, TEAM_STATS, OPPONENT_STATS, WINDOWS

DATA_PATH = Path(__file__).resolve().parents[1] / 'k' / 'kicker_weekly.json'

class KSourceUnavailable(ValueError):
    """The local source snapshot needs to be prepared or refreshed."""


class KSeasonData:
    # Share the established historical/team-trade/complete-schedule safeguards.
    def game_context(self, player, week):
        context = RBSeasonData.game_context(self, player, week)
        if context['game_status'] == 'UNKNOWN':
            historical = next((g for g in self.players.get(player.id, []) if g['week'] == week), None)
            if historical is not None:
                team = self.team_ids.get(normalize_team(historical.get('source_team')))
                opponent = self.team_ids.get(normalize_team(historical.get('opponent_team')))
                if team is not None and opponent is not None and team != opponent:
                    context.update(game_status='GAME', team_id=team, opponent_team_id=opponent,
                                   opponent_team=self.abbreviations.get(opponent))
        return context

    def __init__(self, season, player_games, team_games, teams, schedules):
        self.season = season
        self.players = defaultdict(list)
        self.team_games = defaultdict(list)
        self.historical_matchups = {}
        for game in player_games:
            self.players[game['player_id']].append(dict(game))
        for games in self.players.values():
            games.sort(key=lambda g: g['week'])
        for game in team_games:
            self.team_games[game['team_id']].append(game)
            self.historical_matchups[(game['opponent_team_id'], game['week'])] = game
        for games in self.team_games.values():
            games.sort(key=lambda g: g['week'])
        self.team_ids = {normalize_team(t['abbreviation']): t['id'] for t in teams}
        self.abbreviations = {t['id']: t['abbreviation'] for t in teams}
        self.schedules = schedules
        self.schedule_counts = Counter(t for g in schedules for t in (g['home_team_id'], g['away_team_id']))

    @classmethod
    def load(cls, season):
        if not DATA_PATH.exists():
            raise FileNotFoundError('Prepare kicker_weekly.json with scripts.imports.prepare_kicker_data.')
        payload = json.loads(DATA_PATH.read_text(encoding='utf-8'))
        if payload.get('schema_version') != 2:
            raise KSourceUnavailable('Rebuild the kicker source snapshot.')
        if season not in payload['seasons']:
            raise KSourceUnavailable('Requested season is absent from the kicker source snapshot.')
        games = [g for g in payload['games'] if g['season'] == season]
        with get_connection().cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT id, abbreviation FROM teams")
            teams = cur.fetchall()
            cur.execute("""SELECT team_id, opponent_team_id, week, is_home,
                points_for, total_yards, kicking_points_for,
                points_against, total_yards_against, kicking_points_against
                FROM team_weekly_stats WHERE season=%s AND season_type=1 ORDER BY week""", (season,))
            team_games = cur.fetchall()
            cur.execute("""SELECT week, home_team_id, away_team_id FROM nfl_games
                WHERE season=%s AND game_type='REG'""", (season,))
            schedules = cur.fetchall()
        return cls(season, games, team_games, teams, schedules)

def build_k_features(player, season, week, data=None):
    if not 1 <= week <= 18:
        raise ValueError('Kicker projections require regular-season weeks 1 through 18.')
    data = data if data is not None else KSeasonData.load(season)
    if data.season != season:
        raise ValueError('Kicker snapshot must match the requested season.')
    history = [g for g in data.players.get(player.id, []) if g['week'] < week]
    context = data.game_context(player, week)
    features = {'player_id': player.id, 'season': season, 'week': week,
                'games_played': len(history), **context}
    for window in WINDOWS:
        games = history if window == 'season' else history[-int(window[1:]):]
        for stat in PLAYER_STATS:
            features[f'{stat}_{window}'] = average([g.get(stat) for g in games])
        features[f'fg_rate_{window}'] = paired_rate(games, 'fg_made', 'fg_att')
        features[f'pat_rate_{window}'] = paired_rate(games, 'pat_made', 'pat_att')
    for prefix, team_id, stats in (
        ('team', context['team_id'], TEAM_STATS),
        ('opponent', context['opponent_team_id'], OPPONENT_STATS),
    ):
        history = [g for g in data.team_games.get(team_id, []) if g['week'] < week]
        for window in ('l3', 'season'):
            games = history[-3:] if window == 'l3' else history
            for stat in stats:
                features[f'{prefix}_{stat}_{window}'] = average([g[stat] for g in games])
    return features
