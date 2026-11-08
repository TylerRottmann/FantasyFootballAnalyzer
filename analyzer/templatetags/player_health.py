from django import template
from django.utils.html import format_html
from leagues.services.player_availability import injury_label

register = template.Library()


@register.simple_tag
def injury_badge(player):
    if not player:
        return ''
    label = injury_label(player)
    if not label:
        return ''
    updated = getattr(player, 'updated_at', None)
    stamp = updated.strftime('%b %d, %Y %H:%M UTC') if updated else 'unknown'
    return format_html('<span class="injury-badge" title="Imported injury status; updated {}">{}</span>', stamp, label)


@register.simple_tag
def market_injury_badge(player):
    """Compact injury designation for the Market player rows."""
    if not player:
        return ''
    label = injury_label(player)
    compact_label = {
        'Questionable': 'Q',
        'Out': 'O',
        'Doubtful': 'D',
        'IR': 'IR',
    }.get(label, label)
    if not label:
        return ''
    updated = getattr(player, 'updated_at', None)
    stamp = updated.strftime('%b %d, %Y %H:%M UTC') if updated else 'unknown'
    return format_html(
        '<span class="injury-badge market-injury-badge" title="{}; updated {}">{}</span>',
        label,
        stamp,
        compact_label,
    )
