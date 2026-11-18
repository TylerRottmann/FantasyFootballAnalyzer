from django.db import migrations


SCHEDULES = (
    ("external-cache", list(range(0, 60, 5)), [], []),
    ("player-metadata", [20], [12], []),
    ("injuries", [35], [0, 3, 6, 9, 12, 15, 18, 21], []),
    ("adp", [50], [12], []),
    ("market", [10], [14], []),
    ("weekly", [0], [16], []),
)


def seed(apps, schema_editor):
    schedules = apps.get_model("analyzer", "ScheduledRefresh").objects.using(
        schema_editor.connection.alias
    )
    for name, minutes, hours, weekdays in SCHEDULES:
        schedules.update_or_create(
            name=name, defaults={"minutes": minutes, "hours": hours, "weekdays": weekdays}
        )


def unseed(apps, schema_editor):
    apps.get_model("analyzer", "ScheduledRefresh").objects.using(
        schema_editor.connection.alias
    ).filter(pk__in=[row[0] for row in SCHEDULES]).delete()


class Migration(migrations.Migration):
    dependencies = [("analyzer", "0013_scheduled_refresh")]
    operations = [migrations.RunPython(seed, unseed)]
