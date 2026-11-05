from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("analyzer", "0004_fantasyleagues_fantasyrosterplayers_fantasyrosters_and_more"),
        ("leagues", "0005_remove_fantasyprojection_scoring_profile_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="DefenseProjection",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("season", models.IntegerField()),
                ("week", models.IntegerField()),
                ("projected_fantasy_points", models.FloatField()),
                ("status", models.CharField(default="projected", max_length=20)),
                ("model_version", models.CharField(default="v1", max_length=50)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "team",
                    models.ForeignKey(
                        db_column="team_id",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="defense_projections",
                        to="analyzer.teams",
                    ),
                ),
            ],
            options={
                "db_table": "defense_projections",
                "indexes": [
                    models.Index(
                        fields=["season", "week"],
                        name="defense_proj_lookup_idx",
                    )
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("team", "season", "week", "model_version"),
                        name="unique_defense_projection",
                    )
                ],
            },
        ),
    ]
