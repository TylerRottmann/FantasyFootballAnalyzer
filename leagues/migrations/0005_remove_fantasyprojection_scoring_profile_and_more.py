from django.db import migrations, models


def remove_duplicate_projections(apps, schema_editor):
    """
    Keep the lowest-ID projection for each player, season,
    week, and model version.
    """
    Projection = apps.get_model("leagues", "FantasyProjection")

    rows = (
        Projection.objects
        .order_by("player_id", "season", "week", "model_version", "id")
        .values_list(
            "id",
            "player_id",
            "season",
            "week",
            "model_version",
        )
        .iterator()
    )

    seen = set()
    duplicate_ids = []

    for row_id, player_id, season, week, version in rows:
        key = (player_id, season, week, version)

        if key in seen:
            duplicate_ids.append(row_id)
        else:
            seen.add(key)

    for start in range(0, len(duplicate_ids), 1000):
        Projection.objects.filter(
            id__in=duplicate_ids[start:start + 1000]
        ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("leagues", "0004_scoringprofile_fantasyprojection"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="fantasyprojection",
            name="unique_fantasy_projection",
        ),

        migrations.RemoveIndex(
            model_name="fantasyprojection",
            name="projection_lookup_idx",
        ),

        migrations.RemoveField(
            model_name="fantasyprojection",
            name="scoring_profile",
        ),

        migrations.RunPython(
            remove_duplicate_projections,
            reverse_code=migrations.RunPython.noop,
        ),

        migrations.AddIndex(
            model_name="fantasyprojection",
            index=models.Index(
                fields=["season", "week"],
                name="projection_lookup_idx",
            ),
        ),

        migrations.AddConstraint(
            model_name="fantasyprojection",
            constraint=models.UniqueConstraint(
                fields=(
                    "player",
                    "season",
                    "week",
                    "model_version",
                ),
                name="unique_fantasy_projection",
            ),
        ),

        migrations.DeleteModel(
            name="ScoringProfile",
        ),
    ]
