from django import template
import re

register = template.Library()

@register.filter
def extract_video_id(url):
    match = re.search(r'v=([^&]+)', url)
    if match:
        return match.group(1)
    return ''