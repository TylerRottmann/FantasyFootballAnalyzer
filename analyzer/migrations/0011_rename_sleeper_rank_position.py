from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("analyzer", "0010_playermarketrank"),
    ]

    operations = [
        migrations.RenameField(
            model_name="playermarketrank",
            old_name="sleeper_rest_of_season_overall_rank",
            new_name="sleeper_rest_of_season_position_rank",
        ),
    ]
