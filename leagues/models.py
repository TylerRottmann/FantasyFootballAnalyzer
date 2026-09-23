from django.conf import settings
from django.db import models


class FantasyLeague(models.Model):
    id = models.BigAutoField(primary_key=True)

    # Existing Sprint 1 field.
    # Keep this so Brayden's importer continues to work.
    sleeper_league_id = models.CharField(
        max_length=100,
        unique=True,
    )

    name = models.CharField(
        max_length=255,
    )

    season = models.IntegerField(
        null=True,
        blank=True,
    )

    # League scoring/settings
    ppr = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
    )

    te_premium = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
    )

    starter_count = models.IntegerField(
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "fantasy_leagues"

    def __str__(self):
        return f"{self.name} ({self.season})"


class FantasyRoster(models.Model):
    id = models.BigAutoField(primary_key=True)

    league = models.ForeignKey(
        FantasyLeague,
        on_delete=models.DO_NOTHING,
        db_column="league_id",
        related_name="rosters",
    )

    # Existing Sprint 1 field.
    sleeper_roster_id = models.IntegerField()

    # Existing Sprint 1 field.
    owner_sleeper_id = models.CharField(
        max_length=100,
        null=True,
        blank=True,
    )

    owner_name = models.CharField(
        max_length=255,
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "fantasy_rosters"

    def __str__(self):
        return self.owner_name or f"Roster {self.sleeper_roster_id}"


class Player(models.Model):
    id = models.BigAutoField(primary_key=True)

    sleeper_id = models.CharField(max_length=100, unique=True)

    first_name = models.CharField(
        max_length=255,
        null=True,
        blank=True,
    )

    last_name = models.CharField(
        max_length=255,
        null=True,
        blank=True,
    )

    full_name = models.CharField(
        max_length=255,
    )

    position = models.CharField(
        max_length=20,
        null=True,
        blank=True,
    )

    age = models.FloatField(
        null=True,
        blank=True,
    )

    team_id = models.IntegerField(
        null=True,
        blank=True,
    )

    headshot_url = models.TextField(
        null=True,
        blank=True,
    )

    status = models.CharField(
        max_length=50,
        null=True,
        blank=True,
    )

    injury_status = models.CharField(
        max_length=100,
        null=True,
        blank=True,
    )

    years_exp = models.IntegerField(
        null=True,
        blank=True,
    )

    jersey_number = models.IntegerField(
        null=True,
        blank=True,
    )

    height = models.CharField(
        max_length=20,
        null=True,
        blank=True,
    )

    weight = models.IntegerField(
        null=True,
        blank=True,
    )

    college = models.CharField(
        max_length=255,
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    owned_percentage = models.FloatField(
        null=True,
        blank=True,
    )

    class Meta:
        managed = False
        db_table = "players"

    def __str__(self):
        return self.full_name


class FantasyRosterPlayer(models.Model):
    id = models.BigAutoField(primary_key=True)

    roster = models.ForeignKey(
        FantasyRoster,
        on_delete=models.DO_NOTHING,
        db_column="roster_id",
        related_name="roster_players",
    )

    player = models.ForeignKey(
        Player,
        on_delete=models.DO_NOTHING,
        db_column="player_id",
        related_name="roster_entries",
    )

    created_at = models.DateTimeField()

    class Meta:
        managed = False
        db_table = "fantasy_roster_players"

    def __str__(self):
        return f"{self.roster} - {self.player}"


class UserLeagueConnection(models.Model):
    PLATFORM_SLEEPER = "sleeper"
    PLATFORM_YAHOO = "yahoo"
    PLATFORM_ESPN = "espn"

    PLATFORM_CHOICES = [
        (PLATFORM_SLEEPER, "Sleeper"),
        (PLATFORM_YAHOO, "Yahoo"),
        (PLATFORM_ESPN, "ESPN"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="league_connections",
    )

    league = models.ForeignKey(
        FantasyLeague,
        on_delete=models.CASCADE,
        related_name="user_connections",
    )

    platform = models.CharField(
        max_length=20,
        choices=PLATFORM_CHOICES,
    )

    external_user_id = models.CharField(
        max_length=100,
        null=True,
        blank=True,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "league"],
                name="unique_user_league_connection",
            )
        ]

    def __str__(self):
        return f"{self.user.username} - {self.league.name}"