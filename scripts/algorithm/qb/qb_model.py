import os
import joblib

from scripts.algorithm.stat_line_model import StatLineModel
from scripts.algorithm.stat_targets import POSITION_STAT_TARGETS, POSITION_EFFICIENCY_TARGETS
from scripts.algorithm.qb.feature_names import QB_FEATURE_NAMES

MODEL_PATH = os.path.join(os.path.dirname(__file__), "qb_stat_model.pkl")
TARGETS = POSITION_STAT_TARGETS["QB"]


def create_model():
    return StatLineModel(TARGETS, efficiency_targets=POSITION_EFFICIENCY_TARGETS["QB"])


def save_model(model):
    joblib.dump(model, MODEL_PATH)


def load_model():
    if not os.path.exists(MODEL_PATH):
        return None
    model = joblib.load(MODEL_PATH)
    if (getattr(model, "target_names_", None) != list(TARGETS)
            or getattr(model, "efficiency_targets_", None) != POSITION_EFFICIENCY_TARGETS["QB"]
            or getattr(model, "n_features_in_", None) != len(QB_FEATURE_NAMES)):
        raise ValueError("QB feature or target schema changed; retrain the QB model.")
    return model


def train_model(X, y):
    model = create_model().fit(X, y)
    save_model(model)
    return model


def predict(model, X):
    return model.predict(X)
