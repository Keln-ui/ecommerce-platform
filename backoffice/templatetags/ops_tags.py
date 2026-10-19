"""Template tags that expose marketplace aggregates to admin templates."""

from django import template

from backoffice.ops import ops_snapshot

register = template.Library()


@register.simple_tag
def ops(days: int = 30):
    """Return the operations snapshot dict for the requested window."""
    return ops_snapshot(days)