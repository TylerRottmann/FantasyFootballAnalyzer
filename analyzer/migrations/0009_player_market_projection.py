import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("analyzer", "0008_playerinjuryreport_injury_type"),
    ]

    operations = [
        migrations.CreateModel(
            name="PlayerMarketProjection",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("entity_key", models.CharField(max_length=80)),
                ("external_id", models.CharField(max_length=100)),
                ("position", models.CharField(choices=[("QB", "Quarterback"), ("RB", "Running Back"), ("WR", "Wide Receiver"), ("TE", "Tight End"), ("K", "Kicker"), ("DST", "Defense / Special Teams")], max_length=3)),
                ("season", models.PositiveSmallIntegerField()),
                ("week", models.PositiveSmallIntegerField()),
                ("sleeper_ppr", models.DecimalField(decimal_places=3, default=0, max_digits=9)),
                ("sleeper_half_ppr", models.DecimalField(decimal_places=3, default=0, max_digits=9)),
                ("sleeper_standard", models.DecimalField(decimal_places=3, default=0, max_digits=9)),
                ("rest_of_season_ppr", models.DecimalField(decimal_places=3, default=0, max_digits=10)),
                ("rest_of_season_half_ppr", models.DecimalField(decimal_places=3, default=0, max_digits=10)),
                ("rest_of_season_standard", models.DecimalField(decimal_places=3, default=0, max_digits=10)),
                ("projected_stats", models.JSONField(default=dict)),
                ("projection_available", models.BooleanField(default=False)),
                ("source", models.CharField(default="sleeper", max_length=30)),
                ("source_provider", models.CharField(blank=True, default="", max_length=50)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "player",
                    models.ForeignKey(blank=True, db_constraint=False, null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name="market_projections", to="analyzer.players"),
                ),
                (
                    "team",
                    models.ForeignKey(blank=True, db_constraint=False, null=True, on_delete=django.db.models.deletion.DO_NOTHING, related_name="market_projections", to="analyzer.teams"),
                ),
            ],
            options={
                "db_table": "player_market_projections",
                "ordering": ["season", "week", "position", "entity_key"],
                "constraints": [
                    models.UniqueConstraint(fields=("entity_key", "season", "week"), name="unique_market_projection_entity_week"),
                    models.CheckConstraint(condition=models.Q(("week__gte", 1), ("week__lte", 18)), name="market_projection_valid_week"),
                    models.CheckConstraint(condition=models.Q(models.Q(("player__isnull", False), ("team__isnull", True)), models.Q(("player__isnull", True), ("team__isnull", False)), _connector="OR"), name="market_projection_one_entity"),
                ],
                "indexes": [models.Index(fields=["season", "week", "position"], name="market_proj_filter_idx")],
            },
        ),
    ]
