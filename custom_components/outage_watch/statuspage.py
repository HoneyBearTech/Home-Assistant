"""Parse Statuspage summaries and explicitly supported status-only responses."""


def parse_feed(payload, *, summary_only=False):
    level = payload["status"]["indicator"]
    if level not in ("none", "minor", "major", "critical", "maintenance"):
        raise ValueError("Unrecognized provider status")
    if summary_only and "incidents" not in payload:
        if not payload["page"]["name"] or not isinstance(payload["components"], list):
            raise ValueError("Invalid provider summary")
        impacted = [str(item["name"])[:100] for item in payload["components"]
                    if item["status"] in ("degraded_performance", "partial_outage", "major_outage")]
        return {"level": "none" if level == "maintenance" else level,
                "maintenance": level == "maintenance", "incident": "",
                "components": impacted[:20]}
    incidents = payload["incidents"]
    if not isinstance(incidents, list):
        raise ValueError("Invalid incident list")
    incident = incidents[0] if incidents else {}
    return {
        "level": "none" if level == "maintenance" else level,
        "maintenance": level == "maintenance" or any(
            item.get("status") == "in_progress" for item in payload.get("scheduled_maintenances", [])
        ),
        "incident": str(incident.get("name", ""))[:300],
        "components": [str(item["name"])[:100] for item in incident.get("components", [])][:20],
    }
