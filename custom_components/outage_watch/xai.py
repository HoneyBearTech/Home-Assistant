"""Interpret active incidents in xAI's official RSS feed."""
from urllib.parse import urlsplit
from xml.etree import ElementTree

FEED_URL = "https://status.x.ai/feed.xml"
_GROK_PRODUCTS = frozenset({
    "grok-com", "grok-bot", "grok-in-x", "grok-build", "android-app", "ios-app",
    "api-global", "api-us", "api-eu", "api-voice", "imagine", "voice",
})
_SEVERITY = {"info": 0, "degradation": 1, "disruption": 1, "outage": 2}


def parse_xai(body):
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as error:
        raise ValueError("Invalid xAI RSS") from error
    channel = root.find("channel")
    if root.tag != "rss" or channel is None or channel.findtext("link", "").rstrip("/") != "https://status.x.ai":
        raise ValueError("Unexpected xAI feed")

    level = 0
    incident = ""
    components = []
    for item in channel.findall("item"):
        link = urlsplit(item.findtext("link", ""))
        product = link.path.lstrip("/").partition("/")[0]
        if link.hostname != "status.x.ai" or product not in _GROK_PRODUCTS:
            continue
        categories = {tag.text.strip().lower() for tag in item.findall("category") if tag.text}
        if categories.intersection({"resolved", "completed"}):
            continue
        severity = max((_SEVERITY.get(category, 0) for category in categories), default=0)
        title = item.findtext("title", "")
        if severity > level:
            level, incident = severity, title[:300]
        if severity and title.startswith("[") and "]" in title:
            component = title[1:title.index("]")][:100]
            if component not in components:
                components.append(component)
    return {"level": ("none", "minor", "major")[level], "incident": incident,
            "components": components[:20], "maintenance": False}
