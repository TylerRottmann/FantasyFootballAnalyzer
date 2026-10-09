import os
import joblib

from sklearn.ensemble import HistGradientBoostingRegressor


MODEL_PATH = os.path.join(
    os.path.dirname(__file__),
    "wr_model.pkl",
)


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

    return joblib.load(MODEL_PATH)


def train_model(X, y):
    model = create_model()
    model.fit(X, y)
    save_model(model)
    return model


def predict(model, X):
    return model.predict(X)
