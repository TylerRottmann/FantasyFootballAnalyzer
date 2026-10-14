def get_projection(item):
    prediction = item.get("prediction")

    if prediction is None:
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

    total_score, assignment = max(states.values(), key=lambda state: state[0])
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
