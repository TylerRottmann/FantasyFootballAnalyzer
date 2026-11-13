"""Pickup horizons, roster needs and comparisons that preserve unknown forecasts."""
from scripts.commands.lineup import can_fill_slot
from leagues.services.player_availability import BLOCKED, normalize_status

LONG_TERM_MIN_WEEKLY_GAIN = 2.0
LONG_TERM_MIN_POSITIVE_SHARE = 0.60
LONG_TERM_MIN_WEEKS = 4
SHORT_TERM_MIN_WEEKLY_GAIN = 3.0
TAG_CANDIDATES_PER_POSITION = 8
TAG_DROPS_PER_HORIZON = 3


def drop_options(owned, horizon):
    """Only evaluate healthy bench players with a known value for the horizon."""
    rows = (row for row in owned
        if row['roster_slot'] == 'BN'
        and (row['prediction'].rest_of_season is not None if horizon == 'long'
             else row['prediction'].this_week is not None)
        and not ({normalize_status(getattr(row['player'], 'injury_status', '')),
            normalize_status(getattr(row['player'], 'status', ''))} & (BLOCKED | {'QUESTIONABLE'})))
    metric = 'rest_of_season' if horizon == 'long' else 'this_week'
    return sorted(rows, key=lambda row: (getattr(row['prediction'], metric), row['player'].full_name, row['player'].pk))


def _slot_bits(row, slots):
    return [1 << index for index, slot in enumerate(slots) if can_fill_slot(row, slot)]


def _points(row, metric, week=None):
    if week is None:
        return getattr(row['prediction'], metric)
    return getattr(row['prediction'], 'weekly', {}).get(week)


def _known_scores(rows, slots, metric, week=None):
    """Best known score for each filled-slot mask; each player is used once."""
    states = {0: 0.0}
    for row in rows:
        points = _points(row, metric, week)
        if points is None:
            continue
        updated = states.copy()
        for mask, score in states.items():
            for bit in _slot_bits(row, slots):
                if not mask & bit:
                    next_mask = mask | bit
                    updated[next_mask] = max(updated.get(next_mask, float('-inf')), score + points)
        states = updated
    return states


def _unknown_masks(rows, slots, metric, week=None):
    # Unknown players may start or sit. Reserve every possible assignment,
    # rather than treating their missing forecasts as zero points.
    masks = {0}
    for row in rows:
        if _points(row, metric, week) is not None:
            continue
        masks |= {mask | bit for mask in masks for bit in _slot_bits(row, slots) if not mask & bit}
    return masks


def _lineup_gain(before, after, unknown_masks):
    """A gain must hold regardless of where unchanged unknown players start."""
    gains = []
    for reserved in unknown_masks:
        before_mask, before_score = max(((mask, score) for mask, score in before.items() if not mask & reserved),
            key=lambda item: (item[0].bit_count(), item[1]))
        possible = [(mask, score) for mask, score in after.items()
            if not mask & reserved and mask & before_mask == before_mask]
        if not possible:
            return None
        _, after_score = max(possible, key=lambda item: (item[0].bit_count(), item[1]))
        gains.append(after_score - before_score)
    return min(gains)


def _weekly_lineup_gains(before_rows, after_rows, slots, weeks):
    gains = []
    for week in weeks:
        if not any(_points(row, 'this_week', week) is not None for row in after_rows):
            continue
        before = _known_scores(before_rows, slots, 'this_week', week)
        unknown_masks = _unknown_masks(before_rows, slots, 'this_week', week)
        after = _known_scores(after_rows, slots, 'this_week', week)
        gain = _lineup_gain(before, after, unknown_masks)
        if gain is not None:
            gains.append((week, gain))
    return gains


def _significant_long_term_gain(gains, remaining_week_count):
    if remaining_week_count < LONG_TERM_MIN_WEEKS or len(gains) < LONG_TERM_MIN_WEEKS:
        return None
    values = [gain for _, gain in gains]
    positive_share = sum(gain > 0.1 for gain in values) / len(values)
    average_gain = sum(values) / len(values)
    if average_gain >= LONG_TERM_MIN_WEEKLY_GAIN and positive_share >= LONG_TERM_MIN_POSITIVE_SHARE:
        return average_gain
    return None


def suggested_pickup_horizons(available, owned, roster_positions):
    """Return roster-specific long/short pickup tags for each available player."""
    slots = [slot for slot in roster_positions if slot in {'QB', 'RB', 'WR', 'TE', 'FLEX', 'SUPER_FLEX'}]
    tags = {}
    if not slots or not owned:
        return tags

    all_weeks = sorted({week for row in available for week in row['prediction'].weekly})
    near_weeks = all_weeks[:2]
    remaining_week_count = len(all_weeks)
    # Only the leading projection candidates at each position can reasonably
    # earn a pickup tag. Bounding this roster-aware search keeps the page fast.
    best_candidates = {}
    for horizon in ('long', 'short'):
        per_position = {}
        for row in available:
            prediction = row['prediction']
            if horizon == 'long':
                score = prediction.rest_of_season
            else:
                near = [prediction.weekly.get(w) for w in near_weeks]
                score = max((value for value in near if value is not None), default=prediction.this_week or 0.0)
            if score is None or score <= 0:
                continue
            bucket = per_position.setdefault(row['player'].position, [])
            bucket.append((score, row))
        for bucket in per_position.values():
            bucket.sort(key=lambda item: (-item[0], item[1]['player'].full_name, item[1]['player'].pk))
            for _, row in bucket[:TAG_CANDIDATES_PER_POSITION]:
                best_candidates[row['player'].pk] = row
    eligible_owned = [row for row in owned if any(can_fill_slot(row, slot) for slot in slots)]
    long_drops = drop_options(eligible_owned, 'long')[:TAG_DROPS_PER_HORIZON]
    eligible_short = [row for row in owned if any(can_fill_slot(row, slot) for slot in slots)
        and row['roster_slot'] not in {'IR', 'TAXI'}]
    short_drops = drop_options(eligible_short, 'short')[:TAG_DROPS_PER_HORIZON]
    for pickup in best_candidates.values():
        player_id = pickup['player'].pk
        if not any(can_fill_slot(pickup, slot) for slot in slots):
            continue
        long_gain = None
        for drop in (long_drops if pickup['prediction'].rest_of_season is not None else ()):
            after_rows = [row for row in eligible_owned if row['player'].pk != drop['player'].pk] + [pickup]
            profile = _weekly_lineup_gains(eligible_owned, after_rows, slots, all_weeks)
            long_gain = _significant_long_term_gain(profile, remaining_week_count)
            if long_gain is not None:
                break
        if long_gain is not None:
            tags[player_id] = 'long'
            continue

        # Immediate value can be concentrated in this week or next week. A
        # one-off spike is short-term even if it raises the season total a little.
        short_profile = []
        for drop in short_drops:
            after_rows = [row for row in eligible_short if row['player'].pk != drop['player'].pk] + [pickup]
            profile = _weekly_lineup_gains(eligible_short, after_rows, slots, near_weeks)
            if sum(value >= SHORT_TERM_MIN_WEEKLY_GAIN for _, value in profile):
                short_profile = profile
                break
        if short_profile:
            tags[player_id] = 'short'
    return tags


def suggested_moves(available, owned, roster_positions, pickup_horizons=None):
    slots = [slot for slot in roster_positions if slot in {'QB', 'RB', 'WR', 'TE', 'FLEX', 'SUPER_FLEX'}]
    cards = []
    for horizon, title, metric in (
        ('long', 'Long-term pickups', 'rest_of_season'),
        ('short', 'Short-term pickups', 'this_week'),
    ):
        card = {'horizon': horizon, 'title': title, 'pickup': None}
        cards.append(card)
        def has_horizon_projection(row):
            prediction = row['prediction']
            if horizon == 'long':
                return prediction.rest_of_season is not None and prediction.rest_of_season > 0
            near_weeks = sorted(prediction.weekly)[:2]
            if near_weeks:
                return any(prediction.weekly.get(w) is not None and prediction.weekly[w] > 0 for w in near_weeks)
            return prediction.this_week is not None and prediction.this_week > 0

        candidates = [row for row in available if has_horizon_projection(row)
            and (pickup_horizons is None or pickup_horizons.get(row['player'].pk) == horizon)
            and any(can_fill_slot(row, slot) for slot in slots)]
        eligible_owned = [row for row in owned if any(can_fill_slot(row, slot) for slot in slots)
            and (horizon == 'long' or row['roster_slot'] not in {'IR', 'TAXI'})]
        if not slots or not owned:
            card['message'] = 'Refresh your league so we can check your lineup needs.'
            continue
        if not candidates:
            card['message'] = ('No clear long-term pickup with complete season predictions yet.' if horizon == 'long'
                else 'No available player with a positive projection this week.')
            continue

        # Within a position the highest forecast is the strongest equivalent
        # pickup. Names and IDs make ties stable across repeated page loads.
        best_by_position = {}
        def candidate_projection(row):
            if horizon == 'short' and row['prediction'].weekly:
                near = [row['prediction'].weekly.get(w) for w in sorted(row['prediction'].weekly)[:2]]
                return max((value for value in near if value is not None), default=0.0)
            return getattr(row['prediction'], metric) or 0.0

        for row in sorted(candidates, key=lambda r: (-candidate_projection(r), r['player'].full_name, r['player'].pk)):
            best_by_position.setdefault(row['player'].position, row)
        drops = [row for row in drop_options(eligible_owned, horizon) if getattr(row['prediction'], metric) is not None]
        best_rank = None
        upgrade_without_drop = False
        for pickup in best_by_position.values():
            weeks = sorted(pickup['prediction'].weekly)
            if horizon == 'long':
                no_drop_profile = _weekly_lineup_gains(eligible_owned, eligible_owned + [pickup], slots, weeks)
                upgrade_without_drop |= _significant_long_term_gain(no_drop_profile, len(weeks)) is not None
            else:
                near_weeks = weeks[:2]
                no_drop_profile = _weekly_lineup_gains(eligible_owned, eligible_owned + [pickup], slots, near_weeks)
                if not no_drop_profile and not weeks:
                    before = _known_scores(eligible_owned, slots, metric)
                    unknown_masks = _unknown_masks(eligible_owned, slots, metric)
                    gain_without_drop = _lineup_gain(before,
                        _known_scores(eligible_owned + [pickup], slots, metric), unknown_masks)
                    no_drop_profile = [(None, gain_without_drop)] if gain_without_drop is not None else []
                upgrade_without_drop |= any(gain >= SHORT_TERM_MIN_WEEKLY_GAIN for _, gain in no_drop_profile)
            for drop in drops:
                after_rows = [row for row in eligible_owned if row['player'].pk != drop['player'].pk] + [pickup]
                if horizon == 'long':
                    profile = _weekly_lineup_gains(eligible_owned, after_rows, slots, weeks)
                    gain = _significant_long_term_gain(profile, len(weeks))
                    if gain is None:
                        continue
                    next_week_gain = None
                    gain_week_label = ''
                else:
                    near_weeks = weeks[:2]
                    profile = _weekly_lineup_gains(eligible_owned, after_rows, slots, near_weeks)
                    if not profile and not weeks:
                        before = _known_scores(eligible_owned, slots, metric)
                        unknown_masks = _unknown_masks(eligible_owned, slots, metric)
                        old_gain = _lineup_gain(before, _known_scores(after_rows, slots, metric), unknown_masks)
                        profile = [(None, old_gain)] if old_gain is not None else []
                    qualifying = [(week, value) for week, value in profile
                        if value >= SHORT_TERM_MIN_WEEKLY_GAIN]
                    if not qualifying:
                        continue
                    gain_week, gain = max(qualifying, key=lambda item: item[1])
                    next_week_gain = next((value for week, value in profile
                        if gain_week is not None and week == gain_week + 1), None)
                    gain_week_label = ('next week' if len(near_weeks) > 1 and gain_week == near_weeks[1]
                        else 'this week')
                # Long-term suggestions require a significant sustained weekly gain.
                drop_value = getattr(drop['prediction'], metric)
                rank = (gain, getattr(pickup['prediction'], metric), -drop_value)
                if best_rank is None or rank > best_rank:
                    best_rank = rank
                    card.update(pickup=pickup, drop=drop, gain=gain)
                    if horizon == 'short':
                        card['next_week_gain'] = next_week_gain
                        card['gain_week_label'] = gain_week_label
                        card['message'] = (f'Improves your best projected lineup by {gain:.1f} points {gain_week_label}.'
                            if gain_week_label == 'next week'
                            else 'Improves your best projected lineup this week.')
                    else:
                        card['message'] = (f'Improves your projected lineup by {gain:.1f} points per week across the remaining forecast.'
                            if gain > 0 else 'No significant season-long improvement.')
        if card['pickup']:
            continue
        if upgrade_without_drop:
            card['message'] = 'A pickup could help, but there’s no clear bench player to drop. Hold for now.'
        elif any(getattr(row['prediction'], metric) is None for row in eligible_owned):
            card['message'] = 'Some relevant predictions are missing. No clear upgrade yet.'
        else:
            card['message'] = ('Your roster options project better. No clear long-term upgrade.' if horizon == 'long'
                else 'Your current options project just as well or better. Hold for now.')
    return cards
