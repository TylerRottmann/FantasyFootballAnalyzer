import os

import joblib
from sklearn.ensemble import HistGradientBoostingRegressor

from scripts.algorithm.rb.feature_names import RB_FEATURE_NAMES


MODEL_PATH = os.path.join(os.path.dirname(__file__), "rb_model.pkl")


def create_model():
    return HistGradientBoostingRegressor(
        max_iter=300,
        learning_rate=0.05,
        max_leaf_nodes=15,
        max_bins=32,
        l2_regularization=1.0,
        random_state=42,
    )


def save_model(model):
    joblib.dump(model, MODEL_PATH)


def load_model():
    if not os.path.exists(MODEL_PATH):
        return None
    model = joblib.load(MODEL_PATH)
    if getattr(model, "rb_feature_names_", None) != RB_FEATURE_NAMES:
        raise ValueError("RB feature order changed; retrain the RB model.")
    return model


def train_model(X, y, seasons):
    model = create_model()
    model.fit(X, y)
    model.rb_feature_names_ = list(RB_FEATURE_NAMES)
    model.rb_training_seasons_ = list(seasons)
    model.rb_scoring_ = "PPR"
    save_model(model)
    return model


def predict(model, X):
    return model.predict(X)
