"""Versioned artifact validation for Boom/Bust v2."""

ARTIFACT_VERSION = 2
POSITIONS = frozenset({"QB", "RB", "WR", "TE"})
CLASSES = frozenset({"boom", "bust", "normal"})


def validate_model_artifact(artifact, expected_position=None):
    """Validate metadata and the calibrated prediction interface."""
    if not isinstance(artifact, dict):
        raise ValueError("Model artifact must be a dictionary.")

    required = {
        "artifact_version",
        "position",
        "model",
        "feature_columns",
        "classes",
        "train_season",
        "calibration_season",
        "test_season",
    }

    missing = required - artifact.keys()

    if missing:
        raise ValueError(
            f"Missing artifact fields: {sorted(missing)}"
        )

    if type(artifact["artifact_version"]) is not int or (
        artifact["artifact_version"] != ARTIFACT_VERSION
    ):
        raise ValueError("Unsupported artifact version.")

    position = artifact["position"]

    if position not in POSITIONS:
        raise ValueError("Unsupported artifact position.")

    if expected_position is not None and position != expected_position:
        raise ValueError("Model position mismatch.")

    columns = artifact["feature_columns"]

    if not isinstance(columns, list) or not columns:
        raise ValueError("Feature columns must be a nonempty list.")

    if not all(isinstance(c, str) and c for c in columns):
        raise ValueError("Invalid feature column name.")

    if len(columns) != len(set(columns)):
        raise ValueError("Duplicate feature columns.")

    classes = artifact["classes"]

    if not isinstance(classes, (list, tuple)):
        raise ValueError("Classes must be an ordered sequence.")

    if len(classes) != 3 or set(classes) != CLASSES:
        raise ValueError("Unexpected outcome classes.")

    model = artifact["model"]

    if not callable(getattr(model, "predict_proba", None)):
        raise ValueError("Model lacks predict_proba.")

    model_classes = getattr(model, "classes_", None)

    if model_classes is None or list(model_classes) != list(classes):
        raise ValueError("Artifact/model class order mismatch.")

    seasons = [
        artifact["train_season"],
        artifact["calibration_season"],
        artifact["test_season"],
    ]

    if not all(type(s) is int for s in seasons):
        raise ValueError("Invalid artifact season.")

    if not seasons[0] < seasons[1] < seasons[2]:
        raise ValueError("Artifact seasons must be chronological.")

    return True
