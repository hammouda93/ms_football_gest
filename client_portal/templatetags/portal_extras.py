from django import template


register = template.Library()


@register.filter
def timecode(value):
    if value is None:
        return ""
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return value
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"
