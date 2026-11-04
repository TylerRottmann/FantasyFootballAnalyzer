"""Local, versioned historical dataset snapshots for Boom/Bust v2."""

import hashlib
import json
import os
import tempfile
from pathlib import Path

CACHE_VERSION = 1
CACHE_DIR = Path(__file__).with_name(".cache_v2")


def _cache_path(season):
    if type(season) is not int or not 2000 <= season <= 2100:
        raise ValueError("Season must be an integer between 2000 and 2100.")
    return CACHE_DIR / f"historical_{season}_v{CACHE_VERSION}.json"


def _validate_rows(rows, season):
    if not isinstance(rows, list) or not rows:
        raise ValueError("Historical dataset must be a nonempty list.")

    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"Record {index} is not a dictionary.")

        if row.get("season") != season:
            raise ValueError(f"Record {index} has an incorrect season.")

        if type(row.get("week")) is not int:
            raise ValueError(f"Record {index} has an invalid week.")

        if not 1 <= row["week"] <= 18:
            raise ValueError(f"Record {index} has an out-of-range week.")

        if row.get("player_id") is None:
            raise ValueError(f"Record {index} is missing player_id.")

        if not any(row.get(f"position_{p}") == 1 for p in ("qb", "rb", "wr", "te")):
            raise ValueError(f"Record {index} has no supported position.")

    return rows


def _checksum(rows):
    payload = json.dumps(
        rows, sort_keys=True, allow_nan=False, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_cached_season(season):
    path = _cache_path(season)

    if not path.exists():
        return None

    with path.open(encoding="utf-8") as file:
        snapshot = json.load(file)

    if (
        type(snapshot) is not dict
        or snapshot.get("version") != CACHE_VERSION
        or snapshot.get("season") != season
    ):
        raise ValueError(f"Invalid cache metadata: {path}")

    rows = _validate_rows(snapshot.get("rows"), season)

    if snapshot.get("checksum") != _checksum(rows):
        raise ValueError(f"Cache checksum mismatch: {path}")

    return rows


def save_cached_season(season, rows):
    path = _cache_path(season)
    _validate_rows(rows, season)

    snapshot = {
        "version": CACHE_VERSION,
        "season": season,
        "checksum": _checksum(rows),
        "rows": rows,
    }

    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    temporary = None

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=CACHE_DIR,
            prefix=f".historical_{season}_",
            suffix=".tmp",
            delete=False,
        ) as file:
            temporary = Path(file.name)
            json.dump(snapshot, file, allow_nan=False)
            file.flush()
            os.fsync(file.fileno())

        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

    return path
