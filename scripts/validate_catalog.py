"""Validate the bundled Outage Watch service catalog."""
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

CATALOG = Path(__file__).resolve().parents[1] / "custom_components/outage_watch/www/catalog.json"


def main():
    entries = json.loads(CATALOG.read_text())
    ids = set()
    check_urls = set()
    for entry in entries:
        key = entry["id"]
        if not re.fullmatch(r"[a-z][a-z0-9_]*", key) or key in ids:
            raise ValueError(f"Invalid or duplicate catalog ID: {key}")
        ids.add(key)
        if not entry["name"].strip() or not re.fullmatch(r"[a-z0-9-]+", entry["icon"]):
            raise ValueError(f"{key}: invalid name or icon")
        if not (entry.get("url") or entry.get("feed")):
            raise ValueError(f"{key}: no monitoring endpoint")
        for field in ("url", "feed", "official", "crowd"):
            if field not in entry:
                continue
            url = urlsplit(entry[field])
            if url.scheme != "https" or not url.hostname or url.username or url.fragment:
                raise ValueError(f"{key}: invalid {field} URL")
        if entry.get("url"):
            url = urlsplit(entry["url"])
            normalized = (url.hostname, url.port or 443, url.path or "/", url.query)
            if normalized in check_urls:
                raise ValueError(f"{key}: duplicate check URL")
            check_urls.add(normalized)
    print(f"Validated {len(entries)} catalog entries")


if __name__ == "__main__":
    main()
