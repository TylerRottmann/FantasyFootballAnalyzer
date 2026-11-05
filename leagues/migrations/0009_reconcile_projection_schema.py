"""Reconcile projection history without removing the live uniqueness rule."""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('leagues', '0008_fantasyprojection_projected_stats'),
    ]

    operations = [
        # 0004 and 0005 recorded two constraints under the same name. The live
        # database already has the correct four-column constraint from 0005.
        # Reset only the recorded state; do not drop that database constraint.
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.RemoveConstraint(
                    model_name='fantasyprojection',
                    name='unique_fantasy_projection',
                ),
                migrations.AddConstraint(
                    model_name='fantasyprojection',
                    constraint=models.UniqueConstraint(
                        fields=('player', 'season', 'week', 'model_version'),
                        name='unique_fantasy_projection',
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name='TeamWeekProjection',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('season', models.IntegerField()),
                ('week', models.IntegerField()),
                ('projected_points', models.FloatField(null=True)),
                ('points_by_position', models.JSONField(default=dict)),
                ('lineup', models.JSONField(default=list)),
                ('model_version', models.CharField(max_length=50)),
                ('scoring_version', models.CharField(max_length=50)),
                ('generated_at', models.DateTimeField(auto_now=True)),
                ('league', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='leagues.fantasyleague')),
                ('roster', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='leagues.fantasyroster')),
            ],
            options={
                'constraints': [models.UniqueConstraint(
                    fields=('league', 'roster', 'season', 'week', 'model_version'),
                    name='unique_team_week_projection',
                )],
            },
        ),
    ]
