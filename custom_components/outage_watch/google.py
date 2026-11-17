"""Interpret incidents from the Google Workspace Status Dashboard."""

STATUS_PAGE = "https://www.google.com/appsstatus/dashboard/"
FEED_URL = STATUS_PAGE + "incidents.json"

IMPACT = {"SERVICE_INFORMATION": 1, "SERVICE_DISRUPTION": 1, "SERVICE_OUTAGE": 2}


def parse_workspace(payload):
    if not isinstance(payload, list):
        raise ValueError("Expected a Google Workspace incident list")
    active = []
    for incident in payload:
        if not incident["id"] or not incident["begin"]:
            raise ValueError("Invalid Google Workspace incident")
        if incident.get("end"):
            continue
        active.append((IMPACT[incident["status_impact"]], incident))
    active.sort(key=lambda row: row[0], reverse=True)
    if not active:
        return {"level": "none", "maintenance": False, "incident": "", "components": []}
    severity, primary = active[0]
    components = list(dict.fromkeys(
        str(product["title"])[:100]
        for _, incident in active
        for product in incident.get("affected_products", [])
    ))
    update = primary.get("most_recent_update") or {}
    message = update.get("text") or primary.get("external_desc") or "Google reports a Workspace incident."
    return {
        "level": "major" if severity == 2 else "minor",
        "maintenance": False,
        "incident": str(message).strip()[:300],
        "components": components[:20],
    }
