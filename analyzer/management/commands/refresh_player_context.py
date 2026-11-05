"""Refresh current injuries/depth and completed-game snap counts from public feeds."""
import math
import requests
from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from analyzer.models import Players, Teams, PlayerInjuryReport, PlayerSnapCount, PlayerWeeklyStats


class Command(BaseCommand):
    help = 'Import Sleeper injury/depth reports and nflverse offensive snap counts.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--injuries-only', action='store_true')

    def handle(self, *args, **options):
        try:
            response = requests.get('https://api.sleeper.app/v1/state/nfl', timeout=20)
            response.raise_for_status()
            state = response.json()
            season, week = int(state['season']), int(state['week'])
            if not 1 <= week <= 18 or state.get('season_type') != 'regular':
                raise ValueError('Injury capture requires a current regular-season week.')
            response = requests.get('https://api.sleeper.app/v1/players/nfl', timeout=60)
            response.raise_for_status()
            source = response.json()
            if not isinstance(source, dict) or not source:
                raise ValueError('Empty or invalid player feed; existing reports retained.')
        except (requests.RequestException, KeyError, TypeError, ValueError) as exc:
            raise CommandError(f'No changes made: {exc}') from exc
        players = {str(p.sleeper_id): p for p in Players.objects.filter(position__in=['QB','RB','WR','TE','K'])}
        team_ids = {t.abbreviation: t.pk for t in Teams.objects.all()}
        now = timezone.now()
        injury_rows = []
        for sleeper_id, player in players.items():
            row = source.get(sleeper_id)
            # A missing field is not a clean bill of health. Explicit null clears a recovered injury.
            if not isinstance(row, dict) or 'injury_status' not in row or 'status' not in row:
                continue
            order = row.get('depth_chart_order')
            order = int(order) if str(order).isdigit() and int(order) > 0 else None
            team = row.get('team')
            team = 'LAR' if team == 'LA' else team
            injury_rows.append((player, {
                'injury_status': row['injury_status'] or '', 'roster_status': row['status'] or '',
                'depth_order': order, 'team_id': team_ids.get(team),
                'position': row.get('position') or '', 'source': 'sleeper', 'observed_at': now,
            }))
        snap_rows = []
        stat_rows = []
        if not options['injuries_only']:
            import nflreadpy as nfl
            try:
                data = nfl.load_snap_counts(seasons=season)
                ids = nfl.load_ff_playerids()
                required = {'season', 'week', 'game_type', 'pfr_player_id', 'team', 'offense_snaps', 'offense_pct'}
                if not required.issubset(data.columns) or not {'pfr_id', 'sleeper_id'}.issubset(ids.columns):
                    raise ValueError('Snap count or player ID schema changed.')
                mapping = {}
                for row in ids.select(['pfr_id', 'sleeper_id']).to_dicts():
                    player = players.get(str(row['sleeper_id']))
                    if player and row['pfr_id']:
                        prior = mapping.get(row['pfr_id'])
                        if prior and prior.pk != player.pk:
                            raise ValueError('Ambiguous PFR player mapping.')
                        mapping[row['pfr_id']] = player
                seen = set()
                for row in data.to_dicts():
                    player = mapping.get(row['pfr_player_id'])
                    if not player or row['season'] != season or row['game_type'] != 'REG' or not 1 <= row['week'] < week:
                        continue
                    share, snaps = row['offense_pct'], row['offense_snaps']
                    if share is None or snaps is None or not math.isfinite(share) or not 0 <= share <= 1 or snaps < 0:
                        continue
                    identity = (player.pk, row['week'])
                    if identity in seen:
                        raise ValueError('Duplicate player-week snap counts; import not applied.')
                    seen.add(identity)
                    team = 'LAR' if row['team'] == 'LA' else row['team']
                    snap_rows.append((player, row['week'], {'team_id': team_ids.get(team),
                        'offense_share': share, 'offense_snaps': int(snaps), 'source': 'nflverse_pfr'}))
                weekly = nfl.load_player_stats(seasons=season)
                stat_fields = ['completions','attempts','passing_yards','passing_tds','passing_interceptions',
                    'carries','rushing_yards','rushing_tds','targets','receptions','receiving_yards',
                    'receiving_tds','fantasy_points','fantasy_points_ppr']
                if not {'player_id','week','season','season_type','opponent_team',*stat_fields}.issubset(weekly.columns):
                    raise ValueError('Weekly workload schema changed.')
                if 'gsis_id' not in ids.columns:
                    raise ValueError('GSIS player mapping unavailable.')
                gsis = {str(r['gsis_id']): players[str(r['sleeper_id'])]
                    for r in ids.select(['gsis_id','sleeper_id']).to_dicts()
                    if r['gsis_id'] and str(r['sleeper_id']) in players}
                for row in weekly.to_dicts():
                    player = gsis.get(str(row['player_id']))
                    if not player or row['season'] != season or row['season_type'] != 'REG' or not 1 <= row['week'] < week:
                        continue
                    defaults = {field:row[field] for field in stat_fields}
                    defaults.update(nflverse_player_id=row['player_id'],opponent_team=row['opponent_team'],
                        game_id=row.get('game_id'), fumbles=row.get('fumbles_total'),
                        fumbles_lost=row.get('fumbles_lost_total'), updated_at=now)
                    stat_rows.append(PlayerWeeklyStats(player_id=player.pk,season=season,week=row['week'],
                        season_type='REG',created_at=now,**defaults))
            except Exception as exc:
                raise CommandError(f'No changes made; snap source unavailable: {exc}. Use --injuries-only to refresh injuries separately.') from exc
        self.stdout.write(f'Season {season}, week {week}: {len(injury_rows)} injury/depth reports; {len(snap_rows)} completed-game snap rows; {len(stat_rows)} weekly stat rows.')
        if options['dry_run']:
            self.stdout.write('Dry run: no database changes.')
            return
        if not injury_rows:
            raise CommandError('No mapped injury reports; existing data retained.')
        with transaction.atomic():
            reports = [PlayerInjuryReport(player_id=player.pk, season=season, week=week, **defaults)
                for player, defaults in injury_rows]
            PlayerInjuryReport.objects.bulk_create(reports, batch_size=250, update_conflicts=True,
                unique_fields=['player', 'season', 'week'],
                update_fields=['injury_status','roster_status','depth_order','team_id','position','source','observed_at'])
            updated_players = []
            for player, defaults in injury_rows:
                player.injury_status = defaults['injury_status'] or None
                player.status = defaults['roster_status']
                player.updated_at = now
                updated_players.append(player)
            Players.objects.bulk_update(updated_players, ['injury_status','status','updated_at'], batch_size=250)
            snaps = [PlayerSnapCount(player_id=player.pk,season=season,week=snap_week,**defaults)
                for player,snap_week,defaults in snap_rows]
            PlayerSnapCount.objects.bulk_create(snaps,batch_size=250,update_conflicts=True,
                unique_fields=['player','season','week'],
                update_fields=['team_id','offense_share','offense_snaps','source','imported_at'])
            if stat_rows:
                PlayerWeeklyStats.objects.bulk_create(stat_rows,batch_size=250,update_conflicts=True,
                    unique_fields=['player','season','week','season_type'],
                    update_fields=[*stat_fields,'nflverse_player_id','opponent_team','game_id','fumbles','fumbles_lost','updated_at'])
        cache.delete(f'player-reports:{season}:{week}')
        cache.delete(f'player-values:{season}:{week}')
        cache.delete(f'injury-absences:{season}')
        cache.set('fantasy:nfl:current-week', week, timeout=300)
        cache.set('fantasy:nfl:last-known-week', week, timeout=60*60*24*30)
        self.stdout.write(self.style.SUCCESS('Player context refreshed. Run regularly; this command does not schedule itself.'))
