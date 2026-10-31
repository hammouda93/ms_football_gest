"""Validated Dailymotion share links, including private video identifiers."""

import re
from urllib.parse import parse_qs, urlparse


VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9]{4,64}$")


def extract_dailymotion_video_id(value):
    try:
        parsed = urlparse(str(value or "").strip())
        if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
            return ""
        host = parsed.hostname
    except (TypeError, ValueError):
        return ""
    parts = parsed.path.strip("/").split("/")
    video_id = ""
    if host in {"dai.ly", "www.dai.ly"}:
        video_id = parts[0]
    elif host in {"dailymotion.com", "www.dailymotion.com", "m.dailymotion.com"}:
        if len(parts) >= 2 and parts[0] == "video":
            video_id = parts[1]
        elif len(parts) >= 3 and parts[:2] == ["embed", "video"]:
            video_id = parts[2]
    elif host == "geo.dailymotion.com" and parts[0] == "player":
        video_id = parse_qs(parsed.query).get("video", [""])[0]
    # Legacy public URLs may append a title. Preserve private k... IDs too;
    # never turn a Studio edit URL into a client-facing share link.
    video_id = video_id.split("_", 1)[0]
    return video_id if VIDEO_ID_RE.fullmatch(video_id) else ""


def canonical_dailymotion_url(value):
    video_id = extract_dailymotion_video_id(value)
    return f"https://www.dailymotion.com/video/{video_id}" if video_id else ""
