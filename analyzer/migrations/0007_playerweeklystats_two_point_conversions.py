from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("analyzer", "0006_playeradp")]

    operations = [
        migrations.RunSQL(
            sql=(
                "ALTER TABLE player_weekly_stats "
                "ADD COLUMN passing_2pt_conversions integer NULL, "
                "ADD COLUMN rushing_2pt_conversions integer NULL, "
                "ADD COLUMN receiving_2pt_conversions integer NULL"
            ),
            reverse_sql=(
                "ALTER TABLE player_weekly_stats "
                "DROP COLUMN receiving_2pt_conversions, "
                "DROP COLUMN rushing_2pt_conversions, "
                "DROP COLUMN passing_2pt_conversions"
            ),
        ),
    ]
