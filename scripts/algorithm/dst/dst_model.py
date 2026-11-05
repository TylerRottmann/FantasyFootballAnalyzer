import os
import joblib

from scripts.algorithm.stat_line_model import StatLineModel
from scripts.algorithm.stat_targets import POSITION_STAT_TARGETS
from scripts.algorithm.dst.feature_names import DST_FEATURE_NAMES

MODEL_PATH = os.path.join(os.path.dirname(__file__), "dst_stat_model.pkl")
TARGETS = POSITION_STAT_TARGETS["DEF"]


def create_model():
    return StatLineModel(TARGETS, max_iter=180, max_leaf_nodes=6, min_samples_leaf=35)


def save_model(model):
    joblib.dump(model, MODEL_PATH)


def load_model():
    if not os.path.exists(MODEL_PATH):
        return None
    model = joblib.load(MODEL_PATH)
    if (getattr(model, "target_names_", None) != list(TARGETS)
            or getattr(model, "n_features_in_", None) != len(DST_FEATURE_NAMES)):
        raise ValueError("D/ST feature or target schema changed; retrain the model.")
    return model


def train_model(X, y):
    model = create_model().fit(X, y)
    save_model(model)
    return model


def predict(model, X):
    return model.predict(X)
