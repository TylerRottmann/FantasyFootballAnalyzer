import os
import joblib

from scripts.algorithm.stat_line_model import StatLineModel
from scripts.algorithm.stat_targets import POSITION_STAT_TARGETS, POSITION_EFFICIENCY_TARGETS
from scripts.algorithm.rb.feature_names import RB_FEATURE_NAMES

MODEL_PATH = os.path.join(os.path.dirname(__file__), "rb_stat_model.pkl")
TARGETS = POSITION_STAT_TARGETS["RB"]


def create_model():
    return StatLineModel(TARGETS, efficiency_targets=POSITION_EFFICIENCY_TARGETS["RB"])


def save_model(model):
    joblib.dump(model, MODEL_PATH)


def load_model():
    if not os.path.exists(MODEL_PATH):
        return None
    model = joblib.load(MODEL_PATH)
    if (getattr(model, "target_names_", None) != list(TARGETS)
            or getattr(model, "efficiency_targets_", None) != POSITION_EFFICIENCY_TARGETS["RB"]
            or getattr(model, "n_features_in_", None) != len(RB_FEATURE_NAMES)):
        raise ValueError("RB feature or target schema changed; retrain the RB model.")
    return model


def train_model(X, y, seasons=None):
    model = create_model().fit(X, y)
    model.rb_training_seasons_ = list(seasons or [])
    save_model(model)
    return model


def predict(model, X):
    return model.predict(X)
