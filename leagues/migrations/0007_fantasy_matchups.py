from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("leagues", "0006_defenseprojection"),
        ("analyzer", "0004_fantasyleagues_fantasyrosterplayers_fantasyrosters_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="FantasyMatchup",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("season", models.IntegerField()),
                ("week", models.IntegerField()),
                ("platform", models.CharField(max_length=20)),
                ("external_id", models.CharField(blank=True, max_length=100)),
                ("points", models.FloatField(blank=True, null=True)),
                ("opponent_points", models.FloatField(blank=True, null=True)),
                ("is_final", models.BooleanField(default=False)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("league", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="matchups", to="leagues.fantasyleague")),
                ("opponent", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="opponent_matchups", to="leagues.fantasyroster")),
                ("roster", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="matchups", to="leagues.fantasyroster")),
            ],
            options={
                "db_table": "fantasy_matchups",
                "constraints": [
                    models.UniqueConstraint(fields=("league", "roster", "season", "week", "platform"), name="unique_fantasy_roster_matchup_week"),
                ],
            },
        ),
    ]
