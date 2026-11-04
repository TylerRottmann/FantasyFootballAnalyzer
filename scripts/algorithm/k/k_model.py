from pathlib import Path
import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from scripts.algorithm.k.feature_names import BUCKETS, K_FEATURE_NAMES, TARGETS

MODEL_PATH = Path(__file__).with_name('k_model.pkl')


class KVolumeEfficiencyModel:
    """Predict kick attempts by bucket and make rate, then rebuild made/missed counts."""
    def __init__(self):
        self.parameters = {
            "max_iter": 150, "learning_rate": 0.05, "max_leaf_nodes": 7,
            "l2_regularization": 1, "random_state": 42,
        }
        self.models_ = []
        self.k_feature_names_ = list(K_FEATURE_NAMES)
        self.k_targets_ = list(TARGETS)
        self.k_model_schema_ = 2
        self.k_training_seasons_ = []

    @staticmethod
    def _paired_targets():
        pairs = [(f'fg_made_{bucket}', f'fg_missed_{bucket}') for bucket in BUCKETS]
        pairs.append(('pat_made', 'pat_missed'))
        return pairs

    def fit(self, X, y):
        values = np.asarray(y, dtype=float).copy()
        indexes = {name: i for i, name in enumerate(TARGETS)}
        for made_name, missed_name in self._paired_targets():
            made_idx, missed_idx = indexes[made_name], indexes[missed_name]
            made = values[:, made_idx].copy()
            missed = values[:, missed_idx].copy()
            attempts = made + missed
            values[:, made_idx] = attempts
            values[:, missed_idx] = np.divide(
                made, attempts, out=np.zeros_like(made), where=attempts > 0,
            )
        self.models_ = []
        rate_targets = {missed for _made, missed in self._paired_targets()}
        X = np.asarray(X)
        for index, name in enumerate(TARGETS):
            if name in rate_targets:
                made_name = next(made for made, missed in self._paired_targets() if missed == name)
                exposure = values[:, indexes[made_name]]
                mask = exposure > 0
                if not np.any(mask):
                    raise ValueError(f"No positive-attempt training rows for {name}.")
                model = HistGradientBoostingRegressor(**self.parameters).fit(X[mask], values[mask, index])
            else:
                model = HistGradientBoostingRegressor(**self.parameters).fit(X, values[:, index])
            self.models_.append(model)
        self.n_features_in_ = np.asarray(X).shape[1]
        return self

    def predict(self, X):
        values = np.column_stack([model.predict(X) for model in self.models_])
        values = np.maximum(np.asarray(values, dtype=float), 0.0)
        indexes = {name: i for i, name in enumerate(TARGETS)}
        for made_name, missed_name in self._paired_targets():
            made_idx, missed_idx = indexes[made_name], indexes[missed_name]
            attempts = values[:, made_idx].copy()
            make_rate = np.clip(values[:, missed_idx], 0.0, 1.0)
            values[:, made_idx] = attempts * make_rate
            values[:, missed_idx] = attempts * (1.0 - make_rate)
        return values

def create_model():
    return KVolumeEfficiencyModel()

def train_model(X, y, seasons, save=True):
    model = create_model().fit(X, y)
    model.k_training_seasons_ = list(seasons)
    if save:
        joblib.dump(model, MODEL_PATH)
    return model

def load_model():
    if not MODEL_PATH.exists():
        return None
    model = joblib.load(MODEL_PATH)
    if (not isinstance(model, KVolumeEfficiencyModel)
            or getattr(model, 'k_model_schema_', None) != 2
            or getattr(model, 'k_feature_names_', None) != K_FEATURE_NAMES
            or getattr(model, 'k_targets_', None) != TARGETS):
        raise ValueError('Kicker feature or target order changed; retrain the model.')
    return model

def predict(model, X):
    # Counts and made yardage cannot be negative; expected counts are fractional.
    return np.maximum(model.predict(X), 0)
