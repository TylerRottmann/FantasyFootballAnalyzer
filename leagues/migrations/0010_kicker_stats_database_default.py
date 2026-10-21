"""Keep projection inserts compatible with clients running older app code."""
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('leagues', '0009_reconcile_projection_schema')]
    operations = [migrations.AlterField(
        model_name='fantasyprojection', name='projected_stats',
        field=models.JSONField(default=dict, blank=True, db_default={}),
    )]
