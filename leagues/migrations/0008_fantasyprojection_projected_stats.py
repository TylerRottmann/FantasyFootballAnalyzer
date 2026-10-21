from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [('leagues', '0007_fantasy_matchups')]
    operations = [migrations.AddField(
        model_name='fantasyprojection', name='projected_stats',
        field=models.JSONField(default=dict, blank=True),
    )]
