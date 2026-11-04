from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("analyzer", "0007_playerweeklystats_two_point_conversions"),
    ]

    operations = [
        migrations.AddField(
            model_name="playerinjuryreport",
            name="injury_type",
            field=models.CharField(blank=True, max_length=100),
        ),
    ]
