from statistics import mean


def label_boom_bust(previous_points, actual_points):
    """
    Label a historical game using only prior games
    to calculate the expected fantasy-point baseline.
    """

    if len(previous_points) < 3:
        return None

    baseline = mean(float(p) for p in previous_points[-3:])

    if baseline < 5:
        return None

    boom_threshold = max(
        baseline * 1.5,
        baseline + 5,
    )

    bust_threshold = max(
        0,
        min(baseline * 0.5, baseline - 5),
    )

    if actual_points >= boom_threshold:
        label = "boom"
    elif actual_points <= bust_threshold:
        label = "bust"
    else:
        label = "normal"

    return {
        "label": label,
        "baseline": round(baseline, 2),
        "boom_threshold": round(boom_threshold, 2),
        "bust_threshold": round(bust_threshold, 2),
    }