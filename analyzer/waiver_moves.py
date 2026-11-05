"""Pickup horizons, roster needs and comparisons that preserve unknown forecasts."""
from scripts.commands.lineup import can_fill_slot
from leagues.services.player_availability import BLOCKED, normalize_status


def drop_options(owned, horizon):
    """Only evaluate healthy bench players with a known remaining-season value."""
    return sorted((row for row in owned
        if row['roster_slot'] == 'BN'
        and row['prediction'].rest_of_season is not None
        and not ({normalize_status(getattr(row['player'], 'injury_status', '')),
            normalize_status(getattr(row['player'], 'status', ''))} & (BLOCKED | {'QUESTIONABLE'}))
        and (horizon == 'long' or row['value'].horizon in {'short', 'fading', 'unknown'})),
        key=lambda row: (row['prediction'].rest_of_season, row['player'].full_name, row['player'].pk))


def _slot_bits(row, slots):
    return [1 << index for index, slot in enumerate(slots) if can_fill_slot(row, slot)]


def _known_scores(rows, slots, metric):
    """Best known score for each filled-slot mask; each player is used once."""
    states = {0: 0.0}
    for row in rows:
        points = getattr(row['prediction'], metric)
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


def _unknown_masks(rows, slots, metric):
    # Unknown players may start or sit. Reserve every possible assignment,
    # rather than treating their missing forecasts as zero points.
    masks = {0}
    for row in rows:
        if getattr(row['prediction'], metric) is not None:
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


def _depth_upgrade(pickup, drop, owned, slots):
    """Recognize a lasting positional upgrade or a spare player at a covered position."""
    incoming = pickup['prediction'].rest_of_season
    outgoing = drop['prediction'].rest_of_season
    if pickup['player'].position == drop['player'].position:
        return incoming > outgoing
    source_demand = sum(can_fill_slot(drop, slot) for slot in slots)
    stronger_cover = [row for row in owned if row['player'].pk != drop['player'].pk
        and row['player'].position == drop['player'].position
        and row['prediction'].rest_of_season is not None
        and row['prediction'].rest_of_season >= outgoing]
    destination_demand = sum(can_fill_slot(pickup, slot) for slot in slots)
    destination_count = sum(row['player'].position == pickup['player'].position for row in owned)
    # Allow one reserve beyond the league's eligible starting slots. Unknown
    # teammates still count as depth and cannot be selected as drops.
    return len(stronger_cover) >= source_demand and destination_count < destination_demand + 1


def suggested_moves(available, owned, roster_positions):
    slots = [slot for slot in roster_positions if slot in {'QB', 'RB', 'WR', 'TE', 'FLEX', 'SUPER_FLEX'}]
    cards = []
    for horizon, title, metric in (
        ('long', 'Long-term pickups', 'rest_of_season'),
        ('short', 'Short-term pickups', 'this_week'),
    ):
        card = {'horizon': horizon, 'title': title, 'pickup': None}
        cards.append(card)
        candidates = [row for row in available if row['value'].horizon == horizon
            and getattr(row['prediction'], metric) is not None
            and getattr(row['prediction'], metric) > 0
            and any(can_fill_slot(row, slot) for slot in slots)]
        eligible_owned = [row for row in owned if any(can_fill_slot(row, slot) for slot in slots)
            and (horizon == 'long' or row['roster_slot'] not in {'IR', 'TAXI'})]
        if not slots or not owned:
            card['message'] = 'Refresh your league so we can check your lineup needs.'
            continue
        if not candidates:
            card['message'] = ('No clear long-term pickup with complete season predictions yet.' if horizon == 'long'
                else 'No temporary fill-in with a positive prediction this week.')
            continue

        # Within a position the highest forecast is the strongest equivalent
        # pickup. Names and IDs make ties stable across repeated page loads.
        best_by_position = {}
        for row in sorted(candidates, key=lambda r: (-getattr(r['prediction'], metric), r['player'].full_name, r['player'].pk)):
            best_by_position.setdefault(row['player'].position, row)
        before = _known_scores(eligible_owned, slots, metric)
        unknown_masks = _unknown_masks(eligible_owned, slots, metric)
        drops = [row for row in drop_options(eligible_owned, horizon) if getattr(row['prediction'], metric) is not None]
        best_rank = None
        upgrade_without_drop = False
        for pickup in best_by_position.values():
            gain_without_drop = _lineup_gain(before, _known_scores(eligible_owned + [pickup], slots, metric), unknown_masks)
            upgrade_without_drop |= gain_without_drop is not None and gain_without_drop > 0.1
            for drop in drops:
                after_rows = [row for row in eligible_owned if row['player'].pk != drop['player'].pk] + [pickup]
                gain = _lineup_gain(before, _known_scores(after_rows, slots, metric), unknown_masks)
                if gain is None:
                    continue
                depth = horizon == 'long' and gain >= 0 and _depth_upgrade(pickup, drop, eligible_owned, slots)
                if gain <= 0.1 and not depth:
                    continue
                # Confirmed lineup gains rank first; depth upgrades then use
                # the pickup's season forecast without inventing bench points.
                rank = (gain > 0.1, gain, getattr(pickup['prediction'], metric), -drop['prediction'].rest_of_season)
                if best_rank is None or rank > best_rank:
                    best_rank = rank
                    card.update(pickup=pickup, drop=drop, gain=gain)
                    if horizon == 'short':
                        card['message'] = 'Improves your best projected lineup this week.'
                    elif gain > 0.1:
                        card['message'] = 'Strengthens your projected lineup for the rest of this season.'
                    elif pickup['player'].position == drop['player'].position:
                        card['message'] = f'A stronger season projection at {pickup["player"].position}.'
                    else:
                        card['message'] = f'You have stronger cover at {drop["player"].position}. Adds {pickup["player"].position} depth for the season.'
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
