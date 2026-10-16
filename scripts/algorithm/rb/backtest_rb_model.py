"""Evaluate the saved RB model only on a season after its training window."""

import argparse
import json
from pathlib import Path

from scripts.algorithm.rb.rb_model import load_model
from scripts.algorithm.rb.train_rb_model import build_dataset, compare_baseline, get_rb_players


def main(season, output=None):
    model = load_model()
    if model is None:
        raise ValueError("Train the RB model before running its backtest.")
    training_seasons = getattr(model, "rb_training_seasons_", [])
    if not training_seasons or season <= max(training_seasons):
        raise ValueError("RB holdout backtests require a season after all saved-model training seasons.")
    X, y, rows, counts = build_dataset(season, get_rb_players())
    if len(y) == 0:
        raise ValueError("No usable RB games are available for this backtest season.")
    result = {
        "scoring": "PPR", "training_seasons": training_seasons,
        "test_season": season, "dataset": counts,
        "first_test_week": min(row["week"] for row in rows),
        "last_test_week": max(row["week"] for row in rows),
        **compare_baseline(model, X, y),
    }
    print(json.dumps(result, indent=2))
    if output:
        Path(output).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--output")
    args = parser.parse_args()
    main(args.season, args.output)
