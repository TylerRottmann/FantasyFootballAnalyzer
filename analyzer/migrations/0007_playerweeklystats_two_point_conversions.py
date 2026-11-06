from django.db import migrations


def add_two_point_conversion_columns(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return

    table = schema_editor.quote_name("player_weekly_stats")

    columns = (
        "passing_2pt_conversions",
        "rushing_2pt_conversions",
        "receiving_2pt_conversions",
    )

    for column in columns:
        quoted_column = schema_editor.quote_name(column)
        schema_editor.execute(
            f"ALTER TABLE {table} "
            f"ADD COLUMN IF NOT EXISTS {quoted_column} integer NULL"
        )


def remove_two_point_conversion_columns(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return

    table = schema_editor.quote_name("player_weekly_stats")

    columns = (
        "receiving_2pt_conversions",
        "rushing_2pt_conversions",
        "passing_2pt_conversions",
    )

    for column in columns:
        quoted_column = schema_editor.quote_name(column)
        schema_editor.execute(
            f"ALTER TABLE {table} "
            f"DROP COLUMN IF EXISTS {quoted_column}"
        )


class Migration(migrations.Migration):
    dependencies = [
        ("analyzer", "0006_playeradp"),
    ]

    operations = [
        migrations.RunPython(
            add_two_point_conversion_columns,
            remove_two_point_conversion_columns,
        ),
    ]
