def get_projection(item):
    prediction = item.get("prediction")

    if prediction is None:
        return 0.0

    # Incomplete league-specific scores must not be treated as
    # complete projections in lineup totals or recommendations.
    status = (
        prediction.get("status")
        if isinstance(prediction, dict)
        else getattr(prediction, "status", None)
    )
    if status == "partial_scoring":
        usable = (
            prediction.get("usable_partial_scoring", False)
            if isinstance(prediction, dict)
            else getattr(prediction, "usable_partial_scoring", False)
        )
        if usable is not True:
            return 0.0

    # Prediction object
    if hasattr(prediction, "projected_fantasy_points"):
        value = prediction.projected_fantasy_points

    # Dictionary prediction
    elif isinstance(prediction, dict):
        value = prediction.get("projected_fantasy_points", 0.0)

    # Raw number fallback
    else:
        value = prediction

    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def can_fill_slot(item, slot):
    if item["player"] is None:
        return slot == "DEF"

    position = item["player"].position

    if slot == "FLEX":
        return position in {"RB", "WR", "TE"}

    if slot == "SUPER_FLEX":
        return position in {"QB", "RB", "WR", "TE"}

    return position == slot


def build_current_lineup(players, starting_positions):
    lineup = []
    used_roster_ids = set()

    # Sleeper imports save each player's actual lineup slot. If any saved
    # starter slots exist, preserve them exactly and leave empty slots empty.
    # Older imports with no saved starter slots still use the legacy fallback.
    has_saved_starters = any(
        (item["roster_player"].roster_slot or "").upper()
        not in {"", "BN", "IR", "TAXI"}
        for item in players
    )

    for slot in starting_positions:
        selected = None

        if has_saved_starters:
            selected = next(
                (
                    item for item in players
                    if item["roster_player"].id not in used_roster_ids
                    and (item["roster_player"].roster_slot or "").upper()
                    == slot.upper()
                    and can_fill_slot(item, slot)
                ),
                None,
            )
        else:
            for item in players:
                roster_player_id = item["roster_player"].id

                if roster_player_id in used_roster_ids:
                    continue

                if not can_fill_slot(item, slot):
                    continue

                selected = item
                break

        lineup.append({
            "slot": slot,
            "item": selected,
        })

        if selected is not None:
            used_roster_ids.add(selected["roster_player"].id)

    return lineup


def build_optimized_lineup(players, starting_positions):
    # Track which lineup slots are filled. This bounds the search to
    # O(players * slots * 2**slots), instead of exploring player subsets.
    empty_assignment = (None,) * len(starting_positions)
    states = {0: (0.0, empty_assignment)}

    for item in players:
        projection = get_projection(item)
        next_states = states.copy()

        for filled_mask, (score, assignment) in states.items():
            for slot_index, slot in enumerate(starting_positions):
                slot_bit = 1 << slot_index
                if filled_mask & slot_bit or not can_fill_slot(item, slot):
                    continue

                candidate_score = score + projection
                candidate_mask = filled_mask | slot_bit
                previous = next_states.get(candidate_mask)

                if previous is None or candidate_score > previous[0]:
                    candidate_assignment = list(assignment)
                    candidate_assignment[slot_index] = item
                    next_states[candidate_mask] = (
                        candidate_score,
                        tuple(candidate_assignment),
                    )

        states = next_states

    # Fill available lineup slots before comparing scores. An eligible player
    # with zero or negative points must not be replaced by an empty slot.
    total_score, assignment = max(
        states.values(),
        key=lambda state: (sum(item is not None for item in state[1]), state[0]),
    )
    return [
        {"slot": slot, "item": item}
        for slot, item in zip(starting_positions, assignment)
    ], total_score


def build_risk_adjusted_lineup(players, starting_positions, strategy, *, baseline_lineup=None, max_projection_gap=3.0):
    """Prefer safer or more volatile players without taking a large projection hit.

    Eligible alternatives must project no more than ``max_projection_gap`` below
    the normal optimizer's player in the same slot. Among those alternatives,
    ``safe`` minimizes combined boom/bust probability and ``risky`` maximizes it.
    Projection points break ties; missing risk data is treated as neutral.
    """
    if strategy not in {"safe", "risky"}:
        raise ValueError("strategy must be 'safe' or 'risky'")
    if baseline_lineup is None:
        baseline_lineup, _ = build_optimized_lineup(players, starting_positions)
    targets = [
        get_projection(entry["item"]) if entry["item"] is not None else None
        for entry in baseline_lineup
    ]

    empty_assignment = (None,) * len(starting_positions)
    states = {0: (0.0, 0.0, empty_assignment)}
    for item in players:
        projection = get_projection(item)
        boom_bust = item.get("boom_bust")
        if boom_bust is None:
            volatility = 0.5
        else:
            try:
                volatility = float(boom_bust.boom_probability) + float(boom_bust.bust_probability)
            except (AttributeError, TypeError, ValueError):
                volatility = 0.5
        risk_preference = -volatility if strategy == "safe" else volatility

        next_states = states.copy()
        for filled_mask, (risk_score, points_score, assignment) in states.items():
            for slot_index, slot in enumerate(starting_positions):
                slot_bit = 1 << slot_index
                if filled_mask & slot_bit or not can_fill_slot(item, slot):
                    continue
                target = targets[slot_index]
                if target is not None and projection < target - max_projection_gap:
                    continue
                candidate_mask = filled_mask | slot_bit
                candidate_assignment = list(assignment)
                candidate_assignment[slot_index] = item
                candidate = (
                    risk_score + risk_preference,
                    points_score + projection,
                    tuple(candidate_assignment),
                )
                previous = next_states.get(candidate_mask)
                if previous is None or candidate[:2] > previous[:2]:
                    next_states[candidate_mask] = candidate
        states = next_states

    _, total_score, assignment = max(
        states.values(),
        key=lambda state: (sum(item is not None for item in state[2]), state[0], state[1]),
    )
    return [
        {"slot": slot, "item": item}
        for slot, item in zip(starting_positions, assignment)
    ], total_score


def get_lineup_total(lineup):
    """
    Calculate the total projected points for a lineup.
    """

    return sum(
        get_projection(entry["item"])
        for entry in lineup
        if entry["item"] is not None
    )
