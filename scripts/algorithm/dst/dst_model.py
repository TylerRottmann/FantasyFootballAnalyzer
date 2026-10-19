import os

import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from scripts.algorithm.dst.feature_names import (
    DST_ALL_FEATURE_NAMES,
    DST_SLIM_FEATURE_NAMES,
)

MODEL_PATH = os.path.join(os.path.dirname(__file__), "dst_model.pkl")


def _make_estimator(kind):
    if kind == "gbr":
        # D/ST weekly scores are very noisy, so this is much more
        # conservative than the QB model.
        return HistGradientBoostingRegressor(
            max_iter=150,
            learning_rate=0.03,
            max_depth=2,
            max_leaf_nodes=4,
            min_samples_leaf=60,
            l2_regularization=5.0,
            random_state=42,
        )
    if kind == "ridge":
        return make_pipeline(
            SimpleImputer(strategy="median"),
            StandardScaler(),
            Ridge(alpha=50.0),
        )
    raise ValueError(f"Unknown model kind: {kind}")


class DSTModel:
    """
    Wraps an estimator so callers always pass the FULL feature row
    (DST_ALL_FEATURE_NAMES order). The wrapper:

      1. picks out the columns this model was configured to use,
      2. fits / predicts with the chosen estimator,
      3. shrinks the prediction toward the league-average score:
             shrink * raw + (1 - shrink) * league_mean
         shrink=1.0 means no shrinkage.
    """

    def __init__(self, kind="gbr", feature_names=None, shrink=1.0):
        self.kind = kind
        self.feature_names = list(feature_names or DST_ALL_FEATURE_NAMES)
        self.shrink = shrink
        self.league_mean = None
        self.estimator = None

    def _select(self, X):
        index = [DST_ALL_FEATURE_NAMES.index(n) for n in self.feature_names]
        return np.asarray(X, dtype=float)[:, index]

    def fit(self, X, y):
        self.estimator = _make_estimator(self.kind)
        self.estimator.fit(self._select(X), y)
        self.league_mean = float(np.mean(y))
        return self

    def predict(self, X):
        raw = self.estimator.predict(self._select(X))
        return self.shrink * raw + (1 - self.shrink) * self.league_mean

    def describe(self):
        return (f"{self.kind}, {len(self.feature_names)} features, "
                f"shrink={self.shrink}")


# Configurations the trainer compares on the held-out season.
CANDIDATES = {
    "gbr_all":   dict(kind="gbr",   feature_names=DST_ALL_FEATURE_NAMES),
    "gbr_slim":  dict(kind="gbr",   feature_names=DST_SLIM_FEATURE_NAMES),
    "ridge_slim": dict(kind="ridge", feature_names=DST_SLIM_FEATURE_NAMES),
}
SHRINK_VALUES = [1.0, 0.7, 0.5]


def create_model(name="ridge_slim", shrink=1.0):
    return DSTModel(shrink=shrink, **CANDIDATES[name])


def save_model(model):
    joblib.dump(model, MODEL_PATH)


def load_model():
    if not os.path.exists(MODEL_PATH):
        return None
    return joblib.load(MODEL_PATH)


def train_model(X, y, name="ridge_slim", shrink=1.0):
    model = create_model(name, shrink).fit(X, y)
    save_model(model)
    return model


def predict(model, X):
    return model.predict(X)
