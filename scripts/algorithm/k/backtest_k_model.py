"""Evaluate the saved kicker model strictly after its training seasons."""
import argparse
import json
from pathlib import Path
from scripts.algorithm.k.train_k_model import build_dataset, evaluate, get_players
from scripts.algorithm.k.k_model import load_model

def main(season, output=None):
    model = load_model()
    if model is None:
        raise ValueError('Train the kicker model first.')
    if not model.k_training_seasons_ or season <= max(model.k_training_seasons_):
        raise ValueError('Backtest season must follow every saved-model training season.')
    data = build_dataset(season, get_players())
    result = {'test_season': season, 'training_seasons': model.k_training_seasons_,
              'dataset': data[4], **evaluate(model, data)}
    if output:
        Path(output).write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result, indent=2))
    return result

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--season', type=int, required=True)
    parser.add_argument('--output')
    args = parser.parse_args()
    main(args.season, args.output)
