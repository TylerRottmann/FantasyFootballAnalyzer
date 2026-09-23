from django.contrib.auth.models import AbstractUser
from django.db import models


class CustomUser(AbstractUser):
    email_notifications = models.BooleanField(
        default=True
    )

    nickname = models.CharField(
        max_length=150,
        default="",
    )

    sleeper_username = models.CharField(
        max_length=150,
        default="",
    )

    yahoo_username = models.CharField(
        max_length=150,
        default="",
    )

    espn_username = models.CharField(
        max_length=150,
        default="",
    )

    def __str__(self):
        return self.username

class FantasyLeagues(models.Model):
    id = models.BigAutoField(primary_key=True)
    sleeper_league_id = models.TextField(unique=True)
    name = models.TextField(blank=True, null=True)
    season = models.IntegerField(blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'fantasy_leagues'


class FantasyRosterPlayers(models.Model):
    id = models.BigAutoField(primary_key=True)
    roster = models.ForeignKey('FantasyRosters', models.DO_NOTHING)
    player = models.ForeignKey('Players', models.DO_NOTHING)
    created_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'fantasy_roster_players'
        unique_together = (('roster', 'player'),)


class FantasyRosters(models.Model):
    id = models.BigAutoField(primary_key=True)
    league = models.ForeignKey(FantasyLeagues, models.DO_NOTHING)
    sleeper_roster_id = models.IntegerField()
    owner_sleeper_id = models.TextField(blank=True, null=True)
    owner_name = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'fantasy_rosters'
        unique_together = (('league', 'sleeper_roster_id'),)


class PlayerWeeklyStats(models.Model):
    id = models.BigAutoField(primary_key=True)
    player = models.ForeignKey('Players', models.DO_NOTHING)
    nflverse_player_id = models.TextField(blank=True, null=True)
    season = models.IntegerField()
    week = models.IntegerField()
    season_type = models.CharField(max_length=10)
    game_id = models.TextField(blank=True, null=True)
    opponent_team = models.CharField(max_length=10, blank=True, null=True)
    completions = models.IntegerField(blank=True, null=True)
    attempts = models.IntegerField(blank=True, null=True)
    passing_yards = models.IntegerField(blank=True, null=True)
    passing_tds = models.IntegerField(blank=True, null=True)
    passing_interceptions = models.IntegerField(blank=True, null=True)
    carries = models.IntegerField(blank=True, null=True)
    rushing_yards = models.IntegerField(blank=True, null=True)
    rushing_tds = models.IntegerField(blank=True, null=True)
    targets = models.IntegerField(blank=True, null=True)
    receptions = models.IntegerField(blank=True, null=True)
    receiving_yards = models.IntegerField(blank=True, null=True)
    receiving_tds = models.IntegerField(blank=True, null=True)
    fumbles = models.IntegerField(blank=True, null=True)
    fumbles_lost = models.IntegerField(blank=True, null=True)
    fantasy_points = models.DecimalField(max_digits=10, decimal_places=5, blank=True, null=True)  # max_digits and decimal_places have been guessed, as this database handles decimal fields as float
    fantasy_points_ppr = models.DecimalField(max_digits=10, decimal_places=5, blank=True, null=True)  # max_digits and decimal_places have been guessed, as this database handles decimal fields as float
    created_at = models.DateTimeField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'player_weekly_stats'
        unique_together = (('player', 'season', 'week', 'season_type'),)


class Players(models.Model):
    id = models.BigAutoField(primary_key=True)
    sleeper_id = models.TextField(unique=True)
    first_name = models.TextField(blank=True, null=True)
    last_name = models.TextField(blank=True, null=True)
    full_name = models.TextField(blank=True, null=True)
    position = models.CharField(max_length=10, blank=True, null=True)
    age = models.IntegerField(blank=True, null=True)
    team = models.ForeignKey('Teams', models.DO_NOTHING, blank=True, null=True)
    headshot_url = models.TextField(blank=True, null=True)
    status = models.TextField(blank=True, null=True)
    injury_status = models.TextField(blank=True, null=True)
    years_exp = models.IntegerField(blank=True, null=True)
    jersey_number = models.IntegerField(blank=True, null=True)
    height = models.TextField(blank=True, null=True)
    weight = models.TextField(blank=True, null=True)
    college = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(blank=True, null=True)
    updated_at = models.DateTimeField(blank=True, null=True)
    owned_percentage = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True)

    class Meta:
        managed = False
        db_table = 'players'


class TeamAdvancedWeekly(models.Model):
    id = models.BigAutoField(primary_key=True)
    team = models.ForeignKey('Teams', models.DO_NOTHING)
    season = models.IntegerField()
    week = models.IntegerField()
    season_type = models.IntegerField()
    offensive_plays = models.IntegerField(blank=True, null=True)
    pass_attempts = models.IntegerField(blank=True, null=True)
    rush_attempts = models.IntegerField(blank=True, null=True)
    offensive_epa = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    offensive_epa_per_play = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    pass_epa = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    pass_epa_per_play = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    rush_epa = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    rush_epa_per_play = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    offensive_success_rate = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    pass_success_rate = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    rush_success_rate = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    explosive_pass_plays = models.IntegerField(blank=True, null=True)
    explosive_rush_plays = models.IntegerField(blank=True, null=True)
    explosive_plays = models.IntegerField(blank=True, null=True)
    defensive_epa = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    defensive_epa_per_play = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    defensive_success_rate = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    explosive_pass_plays_allowed = models.IntegerField(blank=True, null=True)
    explosive_rush_plays_allowed = models.IntegerField(blank=True, null=True)
    explosive_plays_allowed = models.IntegerField(blank=True, null=True)
    sacks = models.IntegerField(blank=True, null=True)
    qb_hits = models.IntegerField(blank=True, null=True)
    sack_rate = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    interceptions = models.IntegerField(blank=True, null=True)
    forced_fumbles = models.IntegerField(blank=True, null=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'team_advanced_weekly'
        unique_together = (('team', 'season', 'week', 'season_type'),)


class TeamFeatureSnapshots(models.Model):
    id = models.BigAutoField(primary_key=True)
    team = models.ForeignKey('Teams', models.DO_NOTHING)
    season = models.IntegerField()
    data_through_week = models.IntegerField()
    prediction_week = models.IntegerField()
    games_played = models.IntegerField()
    recent_games = models.IntegerField()
    points_for_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    total_yards_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    passing_yards_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    rushing_yards_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    points_against_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    total_yards_against_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    passing_yards_against_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    rushing_yards_against_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    turnovers_forced_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    interceptions_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    sacks_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    fumbles_forced_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    third_down_conversion_rate = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    third_down_defense_rate = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    fourth_down_conversion_rate = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    fourth_down_defense_rate = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    kicking_points_for_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    kicking_points_against_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    qb_fantasy_allowed_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    rb_fantasy_allowed_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    wr_fantasy_allowed_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    te_fantasy_allowed_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    offensive_epa_per_play = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    pass_epa_per_play = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    rush_epa_per_play = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    offensive_success_rate = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    pass_success_rate = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    rush_success_rate = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    explosive_pass_plays_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    explosive_rush_plays_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    explosive_plays_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    defensive_epa_per_play = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    defensive_success_rate = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    explosive_pass_plays_allowed_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    explosive_rush_plays_allowed_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    explosive_plays_allowed_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    advanced_sack_rate = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    qb_hits_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    recent_points_for_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    recent_points_against_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    recent_total_yards_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    recent_passing_yards_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    recent_rushing_yards_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    recent_total_yards_against_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    recent_passing_yards_against_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    recent_rushing_yards_against_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    recent_turnovers_forced_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    recent_qb_fantasy_allowed_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    recent_rb_fantasy_allowed_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    recent_wr_fantasy_allowed_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    recent_te_fantasy_allowed_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    recent_offensive_epa = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    recent_offensive_epa_per_play = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    recent_pass_epa_per_play = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    recent_rush_epa_per_play = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    recent_offensive_success_rate = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    recent_pass_success_rate = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    recent_rush_success_rate = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    recent_explosive_plays_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    recent_defensive_epa = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    recent_defensive_epa_per_play = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    recent_defensive_success_rate = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    recent_explosive_plays_allowed_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    recent_sack_rate = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    recent_qb_hits_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'team_feature_snapshots'
        unique_together = (('team', 'season', 'data_through_week'),)


class TeamMatchupFeatures(models.Model):
    id = models.BigAutoField(primary_key=True)
    team = models.ForeignKey('Teams', models.DO_NOTHING)
    opponent_team = models.ForeignKey('Teams', models.DO_NOTHING, related_name='teammatchupfeatures_opponent_team_set')
    season = models.IntegerField()
    prediction_week = models.IntegerField()
    is_home = models.BooleanField()
    game_date = models.DateTimeField(blank=True, null=True)
    opponent_points_against_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    opponent_total_yards_against_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    opponent_passing_yards_against_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    opponent_rushing_yards_against_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    opponent_turnovers_forced_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    opponent_interceptions_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    opponent_sacks_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    opponent_fumbles_forced_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    opponent_third_down_defense_rate = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    opponent_fourth_down_defense_rate = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    opponent_qb_fantasy_allowed_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    opponent_rb_fantasy_allowed_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    opponent_wr_fantasy_allowed_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    opponent_te_fantasy_allowed_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    opponent_defensive_epa_per_play = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    opponent_defensive_success_rate = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    opponent_explosive_pass_plays_allowed_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    opponent_explosive_rush_plays_allowed_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    opponent_explosive_plays_allowed_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    opponent_sack_rate = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    opponent_qb_hits_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    opponent_recent_points_against_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    opponent_recent_total_yards_against_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    opponent_recent_passing_yards_against_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    opponent_recent_rushing_yards_against_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    opponent_recent_turnovers_forced_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    opponent_recent_qb_fantasy_allowed_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    opponent_recent_rb_fantasy_allowed_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    opponent_recent_wr_fantasy_allowed_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    opponent_recent_te_fantasy_allowed_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    opponent_recent_defensive_epa_per_play = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    opponent_recent_defensive_success_rate = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    opponent_recent_explosive_plays_allowed_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    opponent_recent_sack_rate = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    opponent_recent_qb_hits_per_game = models.DecimalField(max_digits=10, decimal_places=4, blank=True, null=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'team_matchup_features'
        unique_together = (('team', 'season', 'prediction_week'),)


class TeamSeasonStats(models.Model):
    id = models.BigAutoField(primary_key=True)
    team = models.ForeignKey('Teams', models.DO_NOTHING)
    season = models.IntegerField()
    season_type = models.IntegerField()
    games_played = models.IntegerField()
    points_for = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    total_yards = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    passing_yards = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    rushing_yards = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    points_against = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    total_yards_against = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    passing_yards_against = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    rushing_yards_against = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    sacks = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    interceptions = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    fumbles_forced = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    defensive_touchdowns = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    third_down_attempts = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    third_down_conversions = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    fourth_down_attempts = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    fourth_down_conversions = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    fantasy_points_allowed = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    qb_fantasy_points_allowed = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    rb_fantasy_points_allowed = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    wr_fantasy_points_allowed = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    te_fantasy_points_allowed = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    kicker_fantasy_points_allowed = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    special_teams_touchdowns = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'team_season_stats'
        unique_together = (('team', 'season', 'season_type'),)


class TeamWeeklyStats(models.Model):
    id = models.BigAutoField(primary_key=True)
    team = models.ForeignKey('Teams', models.DO_NOTHING)
    season = models.IntegerField()
    week = models.IntegerField()
    season_type = models.IntegerField()
    opponent_team = models.ForeignKey('Teams', models.DO_NOTHING, related_name='teamweeklystats_opponent_team_set', blank=True, null=True)
    is_home = models.BooleanField()
    points_for = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    points_against = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    total_yards = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    passing_yards = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    rushing_yards = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    total_yards_against = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    passing_yards_against = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    rushing_yards_against = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    turnovers_forced = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    interceptions = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    sacks = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    fumbles_forced = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    third_down_attempts = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    third_down_conversions = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    third_down_attempts_against = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    third_down_conversions_against = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    fourth_down_attempts = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    fourth_down_conversions = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    fourth_down_attempts_against = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    fourth_down_conversions_against = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    kicking_points_for = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    kicking_points_against = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    qb_fantasy_points_allowed = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    rb_fantasy_points_allowed = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    wr_fantasy_points_allowed = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    te_fantasy_points_allowed = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    game_date = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'team_weekly_stats'
        unique_together = (('team', 'season', 'week', 'season_type'),)


class Teams(models.Model):
    id = models.BigAutoField(primary_key=True)
    external_id = models.TextField(unique=True)
    name = models.TextField()
    abbreviation = models.CharField(unique=True, max_length=5)
    conference = models.CharField(max_length=3)
    division = models.CharField(max_length=10)
    is_active = models.BooleanField()
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = 'teams'