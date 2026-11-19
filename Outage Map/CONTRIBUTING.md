# Contributing

To propose a catalog entry, document what its public check actually covers. Verify that the endpoint answers a normal Home Assistant probe from your network. For provider incidents, prefer an official machine-readable feed and test that closed incidents are ignored. Include a sample response or a representative fixture for a new feed format.

Run the local checks from the repository root (the directory containing `scripts/` and `tests/`).

```sh
python3 scripts/validate_catalog.py
python3 -m unittest discover -s tests -v
node --check custom_components/outage_watch/www/outage-watch-card.js
```

Before release, verify the integration in a separate Home Assistant container and test the dashboard with both live data and the sample preview. Keep notification delivery opt-in.
