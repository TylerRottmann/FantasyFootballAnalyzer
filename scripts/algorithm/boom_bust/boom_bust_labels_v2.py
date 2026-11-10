"""Boom/Bust outcome labels based on pregame PPR expectations."""


def label_boom_bust_v2(actual_points, baseline):
    """Label an observed result against a pregame scoring baseline."""
    if baseline is None:
        return None

    baseline = float(baseline)
    actual_points = float(actual_points)

    # Negative fantasy scores are valid. Preserve the original
    # baseline in model features, but floor it for label thresholds.
    baseline = max(0.0, baseline)

    boom_threshold = max(baseline * 1.5, baseline + 5.0)
    bust_threshold = max(0.0, min(baseline * 0.5, baseline - 5.0))

    if actual_points >= boom_threshold:
        label = "boom"
    elif actual_points <= bust_threshold:
        label = "bust"
    else:
        label = "normal"

    return {
        "label": label,
        "boom_threshold": round(boom_threshold, 3),
        "bust_threshold": round(bust_threshold, 3),
    }
