"""Independent regressors for the components of a fantasy stat line."""
import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.dummy import DummyRegressor


class StatLineModel:
    def __init__(self, target_names, *, efficiency_targets=None, max_iter=250, learning_rate=0.04,
                 max_leaf_nodes=12, min_samples_leaf=20, l2_regularization=2.0):
        self.target_names_ = list(target_names)
        # Map an outcome target to (volume target, optional maximum rate).
        # The model learns outcomes per opportunity, then scales them by the
        # separately predicted opportunity count at inference time.
        self.efficiency_targets_ = dict(efficiency_targets or {})
        for outcome, (volume, _cap) in self.efficiency_targets_.items():
            if outcome not in self.target_names_ or volume not in self.target_names_:
                raise ValueError(f"Efficiency mapping {outcome!r} -> {volume!r} must reference model targets.")
        self.parameters = {
            "max_iter": max_iter,
            "learning_rate": learning_rate,
            "max_leaf_nodes": max_leaf_nodes,
            "min_samples_leaf": min_samples_leaf,
            "l2_regularization": l2_regularization,
            "random_state": 42,
        }
        self.models_ = []
        self.feature_masks_ = []

    def fit(self, X, y):
        X_values = np.asarray(X, dtype=float).copy()
        X_values[~np.isfinite(X_values)] = np.nan
        values = np.asarray(y, dtype=float)
        if values.ndim != 2 or values.shape[1] != len(self.target_names_):
            raise ValueError("Target matrix does not match the stat-line schema.")
        target_indices = {name: index for index, name in enumerate(self.target_names_)}
        train_values = values.copy()
        for outcome, (volume, _cap) in self.efficiency_targets_.items():
            outcome_index, volume_index = target_indices[outcome], target_indices[volume]
            denominators = values[:, volume_index]
            train_values[:, outcome_index] = np.divide(
                values[:, outcome_index], denominators,
                out=np.zeros_like(denominators, dtype=float), where=denominators > 0,
            )
        self.models_ = []
        self.feature_masks_ = []
        for index in range(values.shape[1]):
            target_name = self.target_names_[index]
            efficiency = self.efficiency_targets_.get(target_name)
            if efficiency is None:
                X_target = X_values
                y_target = train_values[:, index]
            else:
                volume_index = target_indices[efficiency[0]]
                mask = values[:, volume_index] > 0
                if not np.any(mask):
                    raise ValueError(f"No positive-opportunity training rows for {target_name}.")
                X_target = X_values[mask]
                y_target = train_values[mask, index]
            # HistGradientBoosting's threshold binning can fail on a feature
            # with only one observed value (common in chronological folds and
            # sparse efficiency targets). Keep only columns that vary in this
            # target's actual training slice.
            varying = []
            for feature_index in range(X_target.shape[1]):
                observed = X_target[:, feature_index]
                observed = observed[np.isfinite(observed)]
                if observed.size and np.unique(observed).size > 1:
                    varying.append(feature_index)
            feature_mask = np.zeros(X_target.shape[1], dtype=bool)
            feature_mask[varying] = True
            self.feature_masks_.append(feature_mask)
            if varying:
                model = HistGradientBoostingRegressor(**self.parameters)
                model.fit(X_target[:, feature_mask], y_target)
            else:
                # Preserve a valid constant forecast if every input column is
                # constant or missing in this training slice.
                model = DummyRegressor(strategy="mean")
                model.fit(np.zeros((len(y_target), 1)), y_target)
            self.models_.append(model)
        self.n_features_in_ = np.asarray(X).shape[1]
        # Initial uncertainty calibration. Trainers report untouched holdouts;
        # these residual scales provide per-stat ranges for live scoring.
        residuals = values - self.predict(X)
        self.residual_std_ = np.nan_to_num(np.nanstd(residuals, axis=0), nan=0.0)
        return self

    def predict(self, X):
        if len(self.models_) != len(self.target_names_):
            raise ValueError("Stat-line model is not fully trained.")
        X_values = np.asarray(X, dtype=float).copy()
        X_values[~np.isfinite(X_values)] = np.nan
        predictions = []
        for model, feature_mask in zip(self.models_, self.feature_masks_):
            if np.any(feature_mask):
                predictions.append(model.predict(X_values[:, feature_mask]))
            else:
                predictions.append(model.predict(np.zeros((len(X_values), 1))))
        values = np.column_stack(predictions)
        # First clamp projected volumes and rates, then restore the raw stat
        # line units so scoring and storage retain the existing schema.
        values = np.maximum(values, 0.0)
        target_indices = {name: index for index, name in enumerate(self.target_names_)}
        for outcome, (volume, cap) in self.efficiency_targets_.items():
            outcome_index, volume_index = target_indices[outcome], target_indices[volume]
            rate = values[:, outcome_index]
            if cap is not None:
                rate = np.minimum(rate, float(cap))
            values[:, outcome_index] = rate * values[:, volume_index]
        return values

    def predict_uncertainty(self, X):
        """Return per-target residual scales learned during fit."""
        scales = getattr(self, "residual_std_", None)
        if scales is None:
            return None
        return np.broadcast_to(np.asarray(scales, dtype=float), (len(X), len(scales))).copy()
