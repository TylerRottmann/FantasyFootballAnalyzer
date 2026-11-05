from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("leagues", "0010_kicker_stats_database_default")]

    operations = [
        migrations.AddField(
            model_name="defenseprojection",
            name="projected_stats",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
