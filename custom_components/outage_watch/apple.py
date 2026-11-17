"""Read the iCloud portion of Apple's public System Status feed."""
import json
import re

STATUS_PAGE = "https://www.apple.com/support/systemstatus/"
FEED_URL = STATUS_PAGE + "data/system_status_en_US.js"


def parse_icloud(body):
    text = body.decode("utf-8-sig").strip()
    # Apple has served both raw JSON and a JSONP wrapper at this URL.
    wrapped = re.fullmatch(r"\w+\s*\((.*)\)\s*;?", text, re.DOTALL)
    payload = json.loads(wrapped[1] if wrapped else text)
    services = [item for item in payload["services"]
                if item["serviceName"].startswith("iCloud ")]
    if not services:
        raise ValueError("Apple feed has no iCloud components")
    active = []
    maintenance = False
    for service in services:
        if not isinstance(service["events"], list):
            raise ValueError("Invalid Apple event list")
        for event in service["events"]:
            state = event["eventStatus"].lower()
            kind = event["statusType"].lower()
            if state in ("resolved", "scheduled", "completed"):
                continue
            if kind == "maintenance":
                maintenance = True
            else:
                active.append((kind == "outage", service["serviceName"], event.get("message") or ""))
    active.sort(key=lambda item: not item[0])
    return {
        "level": ("major" if active[0][0] else "minor") if active else "none",
        "maintenance": maintenance,
        "incident": str(active[0][2]).strip()[:300] if active else "",
        "components": list(dict.fromkeys(name for _, name, _ in active))[:20],
    }
