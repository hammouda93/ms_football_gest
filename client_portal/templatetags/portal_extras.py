from urllib.parse import parse_qs, urlparse

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


@register.filter
def youtube_embed_url(value):
    """Return a privacy-enhanced embed URL only for recognized YouTube links."""
    if not value:
        return ""
    try:
        parsed = urlparse(str(value))
    except (TypeError, ValueError):
        return ""

    host = parsed.netloc.lower().split(":", 1)[0]
    video_id = ""
    if host in {"youtu.be", "www.youtu.be"}:
        video_id = parsed.path.strip("/").split("/", 1)[0]
    elif host in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        if parsed.path == "/watch":
            video_id = parse_qs(parsed.query).get("v", [""])[0]
        elif parsed.path.startswith(("/embed/", "/shorts/", "/live/")):
            parts = parsed.path.strip("/").split("/")
            video_id = parts[1] if len(parts) > 1 else ""

    if not video_id or not all(character.isalnum() or character in "-_" for character in video_id):
        return ""
    return f"https://www.youtube-nocookie.com/embed/{video_id}"
