from pathlib import Path
import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.multioutput import MultiOutputRegressor
from scripts.algorithm.k.feature_names import K_FEATURE_NAMES, TARGETS

MODEL_PATH = Path(__file__).with_name('k_model.pkl')

def create_model():
    return MultiOutputRegressor(HistGradientBoostingRegressor(
        max_iter=150, learning_rate=0.05, max_leaf_nodes=7,
        l2_regularization=1, random_state=42,
    ))

def train_model(X, y, seasons, save=True):
    model = create_model().fit(X, y)
    model.k_feature_names_ = list(K_FEATURE_NAMES)
    model.k_targets_ = list(TARGETS)
    model.k_training_seasons_ = list(seasons)
    if save:
        joblib.dump(model, MODEL_PATH)
    return model

def load_model():
    if not MODEL_PATH.exists():
        return None
    model = joblib.load(MODEL_PATH)
    if getattr(model, 'k_feature_names_', None) != K_FEATURE_NAMES or getattr(model, 'k_targets_', None) != TARGETS:
        raise ValueError('Kicker feature or target order changed; retrain the model.')
    return model

def predict(model, X):
    # Counts and made yardage cannot be negative; expected counts are fractional.
    return np.maximum(model.predict(X), 0)
